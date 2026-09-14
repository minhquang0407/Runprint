"""
QR CLI Interface
================
Command-line interface for the QR reproducible research execution wrapper.
Commands: init, run, list, show, rerun, doctor, diff.
"""

from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
from typing import List, Optional

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from qr import __version__
from qr.manifest import (
    ArtifactItem,
    DatasetInput,
    RunInputs,
    RunManifest,
    Timestamps,
)
from qr.project import find_project_root, get_qr_dir, init_project, is_project_initialized
from qr.rerun import (
    cleanup_isolated_worktree,
    create_isolated_worktree,
    run_rerun_preflight,
)
from qr.snapshot.git import capture_git_snapshot
from qr.snapshot.hardware import capture_hardware_snapshot
from qr.snapshot.runtime import capture_runtime_snapshot
from qr.storage.index import RunIndex
from qr.storage.local import (
    RunStorage,
    generate_next_version_run_id,
    generate_run_id,
    resolve_run_id,
)
from qr.subprocess_runner import run_command_with_tee

console = Console()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="qr")
def main():
    """QR -- Reproducible Research Execution Wrapper.
    Run anything. Capture everything needed to reproduce it.
    """
    pass


@main.command()
@click.option("--name", default=None, help="Custom project name")
def init(name: Optional[str]):
    """Initialize a QR project in the current directory."""
    cwd = Path.cwd()
    qr_dir = init_project(cwd, project_name=name)
    console.print(
        Panel(
            f"[bold green]Initialized QR project in[/bold green] [cyan]{qr_dir}[/cyan]\n"
            f"[dim]Run your first experiment with:[/dim]\n"
            f"  [bold white]qr run -- python train.py[/bold white]",
            title="[bold cyan]Runprint (QR)[/bold cyan]",
            border_style="green",
        )
    )


def format_timestamp(iso_str: Optional[str]) -> str:
    """Format ISO timestamp to readable string YYYY-MM-DD HH:MM:SS."""
    if not iso_str:
        return "-"
    clean = iso_str.replace("T", " ")
    if "." in clean:
        clean = clean.split(".")[0]
    elif "+" in clean:
        clean = clean.split("+")[0]
    return clean


def format_duration(seconds: Optional[float]) -> str:
    """Format seconds into readable duration string (e.g. 1.25s or 2m 05s)."""
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.2f}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{int(m)}m {s:.1f}s ({seconds:.1f}s)"
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m {s:.0f}s ({seconds:.1f}s)"


def _coerce_param_value(val: str):
    """Convert numeric string to float/int if possible."""
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def extract_cli_parameters(cmd_list: List[str]):
    """Extract config files and CLI flags/parameters from command."""
    configs: List[str] = []
    params = {}
    skip_next = False

    for i, arg in enumerate(cmd_list):
        if skip_next:
            skip_next = False
            continue

        if arg in ("--config", "-c", "--cfg", "--config-file") and i + 1 < len(cmd_list):
            configs.append(cmd_list[i + 1])
            skip_next = True
        elif arg.startswith("--config=") or arg.startswith("--cfg="):
            configs.append(arg.split("=", 1)[1])
        elif arg.startswith("--"):
            key_part = arg[2:]
            if "=" in key_part:
                k, v = key_part.split("=", 1)
                params[k] = _coerce_param_value(v)
            elif i + 1 < len(cmd_list) and not cmd_list[i + 1].startswith("-"):
                params[key_part] = _coerce_param_value(cmd_list[i + 1])
                skip_next = True
            else:
                params[key_part] = True
    return configs, params


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option("--tag", "-t", multiple=True, help="Tag for labeling the run (can specify multiple)")
@click.option("--parent", default=None, help="Parent run ID (used for lineage tracking)")
@click.option("--cwd", "custom_cwd", default=None, help="Custom working directory")
@click.option("--venv-python", default=None, hidden=True, help="Internal path to restored venv python")
def run(
    command: tuple,
    tag: tuple,
    parent: Optional[str],
    custom_cwd: Optional[str],
    venv_python: Optional[str] = None,
):
    """Execute a command, stream logs, and capture reproducible provenance.
    
    Example:
      qr run --tag baseline -- python train.py --config configs/baseline.yaml
    """
    cmd_list: List[str] = list(command)
    # Strip leading '--' if present
    if cmd_list and cmd_list[0] == "--":
        cmd_list = cmd_list[1:]

    if not cmd_list:
        console.print("[bold red]Error:[/bold red] No command specified to run.")
        sys.exit(1)

    work_dir = Path(custom_cwd).resolve() if custom_cwd else Path.cwd()
    project_root = find_project_root(work_dir)
    if project_root is None or not is_project_initialized(project_root):
        # Auto-init if not already initialized
        project_root = work_dir
        init_project(project_root)

    qr_dir = get_qr_dir(project_root)
    if parent:
        run_id = generate_next_version_run_id(parent, qr_dir)
    else:
        run_id = generate_run_id()
    storage = RunStorage(qr_dir, run_id)
    run_dir = storage.init_run_dir()

    # Pre-run Snapshots
    git_snap = capture_git_snapshot(project_root, run_dir)
    if git_snap and git_snap.dirty:
        warning_text = Text("[!] Working tree contains uncommitted changes. Snapshotting diff:\n", style="bold yellow")
        for f in git_snap.modified_files[:10]:
            warning_text.append(f"  - {f}\n", style="yellow")
        if len(git_snap.modified_files) > 10:
            warning_text.append(f"  ... and {len(git_snap.modified_files) - 10} more\n", style="dim yellow")
        console.print(warning_text)

    runtime_snap = capture_runtime_snapshot(run_dir, repo_root=project_root, python_executable=venv_python)
    hardware_snap = capture_hardware_snapshot()

    # Detect explicit config file flags and CLI parameters in argv
    detected_configs, detected_params = extract_cli_parameters(cmd_list)

    # Initial minimal manifest (persisted before process starts for crash-safety)
    manifest = RunManifest(
        run_id=run_id,
        parent_run_id=parent,
        tags=list(tag),
        command=cmd_list,
        cwd=str(work_dir),
        timestamps=Timestamps(),
        git=git_snap,
        runtime=runtime_snap,
        hardware=hardware_snap,
        inputs=RunInputs(configs=detected_configs, parameters=detected_params),
        status="running",
    )
    storage.save_manifest(manifest)

    tag_str = f" [magenta][{', '.join(tag)}][/magenta]" if tag else ""
    console.print(f"[bold cyan]Run {run_id}[/bold cyan]{tag_str} started [dim]({datetime.now().strftime('%H:%M:%S')})[/dim]")

    # Execute command with live tee logging
    env_overrides = {
        "QR_RUN_ID": run_id,
        "QR_RUN_DIR": str(run_dir),
    }

    # If executing with a restored virtual environment, isolate PATH and VIRTUAL_ENV
    if venv_python:
        py_path = Path(venv_python).resolve()
        bin_dir = py_path.parent
        venv_root = bin_dir.parent

        if cmd_list and cmd_list[0] in ("python", "python3", "python.exe", sys.executable):
            cmd_list[0] = str(py_path)

        curr_path = os.environ.get("PATH", "")
        env_overrides["PATH"] = f"{bin_dir}{os.pathsep}{curr_path}"
        env_overrides["VIRTUAL_ENV"] = str(venv_root)
        env_overrides["QR_RESTORED_ENV"] = str(venv_root)
        if "PYTHONHOME" in os.environ:
            env_overrides["PYTHONHOME"] = ""
    else:
        # Standard execution: resolve python to active virtualenv or current sys.executable
        if cmd_list and cmd_list[0] in ("python", "python3", "python.exe"):
            resolved_py = None
            active_venv = os.environ.get("VIRTUAL_ENV")
            if active_venv:
                venv_bin = Path(active_venv) / ("Scripts" if sys.platform == "win32" else "bin")
                cand = venv_bin / ("python.exe" if sys.platform == "win32" else "python")
                if cand.is_file():
                    resolved_py = cand

            if not resolved_py and sys.executable and Path(sys.executable).is_file():
                resolved_py = Path(sys.executable)

            if resolved_py:
                cmd_list[0] = str(resolved_py)
                curr_path = os.environ.get("PATH", "")
                bin_dir = resolved_py.parent
                env_overrides["PATH"] = f"{bin_dir}{os.pathsep}{curr_path}"
                if active_venv:
                    env_overrides["VIRTUAL_ENV"] = active_venv
                elif (bin_dir.parent / "pyvenv.cfg").exists():
                    env_overrides["VIRTUAL_ENV"] = str(bin_dir.parent)

    # Always ensure the QR SDK package directory is accessible in child python processes
    qr_pkg_dir = str(Path(__file__).resolve().parent.parent)
    curr_pypath = os.environ.get("PYTHONPATH", "")
    pypath_parts = curr_pypath.split(os.pathsep) if curr_pypath else []
    if qr_pkg_dir not in pypath_parts:
        env_overrides["PYTHONPATH"] = f"{qr_pkg_dir}{os.pathsep}{curr_pypath}" if curr_pypath else qr_pkg_dir


    exec_result = run_command_with_tee(
        command=cmd_list,
        cwd=work_dir,
        stdout_log_path=storage.stdout_path,
        stderr_log_path=storage.stderr_path,
        env_overrides=env_overrides,
    )

    # Collect SDK outputs (artifacts & datasets if registered)
    datasets_file = run_dir / "inputs_datasets.json"
    if datasets_file.exists():
        try:
            ds_data = json.loads(datasets_file.read_text(encoding="utf-8"))
            manifest.inputs.datasets = [DatasetInput(**item) for item in ds_data]
        except Exception:
            pass

    # Finalize manifest
    manifest.timestamps.finished_at = datetime.now(timezone.utc).isoformat()
    manifest.duration_seconds = exec_result.duration_seconds
    manifest.exit_code = exec_result.exit_code

    if exec_result.interrupted:
        manifest.status = "interrupted"
    elif exec_result.exit_code == 0:
        manifest.status = "completed"
    else:
        manifest.status = "failed"

    # Calculate Restorability Score
    report = None
    try:
        from qr.scoring import calculate_restorability_score
        report = calculate_restorability_score(manifest, run_dir)
        manifest.restorability_score = report.score
        manifest.restorability_status = report.status
    except Exception:
        pass

    storage.save_manifest(manifest)

    # Update SQLite index
    db_path = qr_dir / "index.sqlite"
    index = RunIndex(db_path)
    index.upsert_run(manifest)

    status_color = "green" if manifest.status == "completed" else "red"
    score_msg = ""
    if report:
        score_msg = f", restorability={report.score}/100 [{report.status_color}]({report.status})[/{report.status_color}]"
    console.print(
        f"\n[bold {status_color}]Run {manifest.status}: exit={exec_result.exit_code}[/bold {status_color}], "
        f"duration={format_duration(exec_result.duration_seconds)}, "
        f"ended={format_timestamp(manifest.timestamps.finished_at)}{score_msg} "
        f"[dim]({run_id})[/dim]"
    )

    sys.exit(exec_result.exit_code)


@main.command(name="list")
@click.option("--limit", default=20, help="Number of runs to display")
@click.option("--tag", "-t", default=None, help="Filter runs by tag")
def list_runs(limit: int, tag: Optional[str]):
    """List recorded experiments, optionally filtered by tag."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found. Run 'qr init' first.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    db_path = qr_dir / "index.sqlite"
    index = RunIndex(db_path)

    # If DB is empty, sync from storage
    rows = index.list_runs(limit=limit, tag=tag)
    if not rows and not tag:
        manifests = RunStorage.list_all_runs(qr_dir)
        if manifests:
            index.rebuild_from_manifests(manifests)
            rows = index.list_runs(limit=limit)

    if not rows:
        msg = f"[dim]No runs found{' matching tag: ' + tag if tag else ''}. Start with: qr run -- <command>[/dim]"
        console.print(msg)
        return

    table = Table(title="[bold cyan]QR Experiment Runs[/bold cyan]", border_style="dim")
    table.add_column("Run ID", style="bold cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Score", justify="right")
    table.add_column("Tags", style="magenta")
    table.add_column("Command", style="white")
    table.add_column("Duration", justify="right")
    table.add_column("Commit", style="dim")
    table.add_column("Dirty", justify="center")
    table.add_column("Started", style="dim")
    table.add_column("Ended", style="dim")

    for row in rows:
        st = row["status"]
        st_color = "green" if st == "completed" else ("red" if st == "failed" else "yellow")
        dur_str = format_duration(row.get("duration_seconds"))
        commit_str = (row["git_commit"][:7]) if row.get("git_commit") else "-"
        dirty_str = "[yellow]yes[/yellow]" if row.get("git_dirty") else "[green]no[/green]"
        started_str = format_timestamp(row.get("started_at"))
        ended_str = format_timestamp(row.get("finished_at"))
        tags_str = row.get("tags") or "-"

        score_val = row.get("restorability_score")
        if score_val is not None:
            color = "green" if score_val >= 90 else ("yellow" if score_val >= 70 else "red")
            score_str = f"[{color}]{score_val}[/{color}]"
        else:
            score_str = "-"

        table.add_row(
            row["run_id"],
            f"[{st_color}]{st}[/{st_color}]",
            score_str,
            tags_str,
            row["command"],
            dur_str,
            commit_str,
            dirty_str,
            started_str,
            ended_str,
        )

    console.print(table)


@main.command()
@click.argument("run_id")
def show(run_id: str):
    """Inspect full provenance and artifacts for a specific run."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    run_id = resolve_run_id(qr_dir, run_id)
    storage = RunStorage(qr_dir, run_id)
    try:
        manifest = storage.load_manifest()
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Run '{run_id}' not found.")
        return

    # Build Rich Display matching Phụ lục A
    st = manifest.status.upper()
    st_color = "green" if st == "COMPLETED" else "red"

    started_str = format_timestamp(manifest.timestamps.started_at)
    ended_str = format_timestamp(manifest.timestamps.finished_at) if manifest.timestamps.finished_at else "running / incomplete"
    dur_str = format_duration(manifest.duration_seconds)

    content = []
    content.append(f"[bold]Status:[/bold]       [{st_color}]{st}[/{st_color}] (exit={manifest.exit_code})")
    content.append(f"[bold]Started:[/bold]      {started_str}")
    content.append(f"[bold]Ended:[/bold]        {ended_str}")
    content.append(f"[bold]Duration:[/bold]     {dur_str}")
    if manifest.tags:
        content.append(f"[bold]Tags:[/bold]         [magenta]{', '.join(manifest.tags)}[/magenta]")
    content.append(f"[bold]Command:[/bold]      [white]{' '.join(manifest.command)}[/white]")
    content.append(f"[bold]Directory:[/bold]    [dim]{manifest.cwd}[/dim]")
    if manifest.parent_run_id:
        content.append(f"[bold]Lineage:[/bold]      [cyan]Parent = {manifest.parent_run_id}[/cyan]")

    content.append("\n[bold cyan]SOURCE[/bold cyan]")
    if manifest.git:
        content.append(f"  Commit:     {manifest.git.commit or 'N/A'}")
        content.append(f"  Branch:     {manifest.git.branch or 'N/A'}")
        content.append(f"  Dirty diff: {'yes (patch saved to git.diff)' if manifest.git.dirty else 'clean'}")
    else:
        content.append("  Git:        Not a git repository")

    content.append("\n[bold cyan]RUNTIME[/bold cyan]")
    content.append(f"  OS:         {manifest.runtime.os}")
    content.append(f"  Python:     {manifest.runtime.python_version}")
    content.append(f"  Lockfile:   {manifest.runtime.packages_lock or 'N/A'}")

    content.append("\n[bold cyan]HARDWARE[/bold cyan]")
    content.append(f"  CPU:        {manifest.hardware.cpu or 'N/A'} ({manifest.hardware.cpu_count or '?'} cores)")
    content.append(f"  RAM:        {manifest.hardware.ram_gb or '?'} GB")
    gpu_desc = ", ".join(manifest.hardware.gpu) if manifest.hardware.gpu else "No GPU detected"
    content.append(f"  GPU:        {gpu_desc}")

    # Display declared inputs
    if manifest.inputs.datasets or manifest.inputs.configs or manifest.inputs.parameters:
        content.append("\n[bold cyan]INPUTS[/bold cyan]")
        for cfg in manifest.inputs.configs:
            content.append(f"  Config:     {cfg}")
        if manifest.inputs.parameters:
            params_str = ", ".join(f"--{k} {v}" for k, v in manifest.inputs.parameters.items())
            content.append(f"  Parameters: {params_str}")
        for ds in manifest.inputs.datasets:
            fp_str = f" ({ds.fingerprint[:16]}...)" if ds.fingerprint else ""
            content.append(f"  Dataset:    {ds.name} [uri={ds.uri}{', ver=' + ds.version if ds.version else ''}{fp_str}]")

    # Check metrics
    if storage.metrics_path.exists():
        content.append("\n[bold cyan]METRICS LOGGED[/bold cyan]")
        lines = storage.metrics_path.read_text(encoding="utf-8").strip().splitlines()
        content.append(f"  Total logged steps: {len(lines)}")
        if lines:
            try:
                last_metric = json.loads(lines[-1])
                summary = ", ".join(f"{k}={v}" for k, v in last_metric.items() if k != "timestamp")
                content.append(f"  Latest step: {summary}")
            except Exception:
                pass

    # Check artifacts
    if storage.artifacts_path.exists():
        content.append("\n[bold cyan]ARTIFACTS REGISTERED[/bold cyan]")
        try:
            art_list = json.loads(storage.artifacts_path.read_text(encoding="utf-8"))
            for art in art_list:
                size_str = f"{round(art['size_bytes']/1024, 1)} KB" if art.get("size_bytes") else "unknown size"
                content.append(f"  - {art['path']} [{art.get('kind', 'generic')}] ({size_str})")
        except Exception:
            pass

    from qr.scoring import calculate_restorability_score

    scoring_report = calculate_restorability_score(manifest, storage.run_dir)

    content.append("\n[bold cyan]REPRODUCIBILITY CONTRACT[/bold cyan]")
    content.append("  Traceable:    [bold green]YES[/bold green] (Full snapshot & log preserved)")
    content.append(
        f"  Restorable:   [bold {scoring_report.status_color}]{scoring_report.status}[/bold {scoring_report.status_color}] "
        f"({scoring_report.score}/100)"
    )
    content.append("  Lineage:      Parent=" + (manifest.parent_run_id or "Root run"))

    console.print(
        Panel(
            "\n".join(content),
            title=f"[bold cyan]Experiment Run Details -- {run_id}[/bold cyan]",
            border_style="cyan",
        )
    )

    # Restorability Audit Checklist Table
    audit_table = Table(
        title=f"[bold]Restorability Audit Checklist -- Score: [{scoring_report.status_color}]{scoring_report.score}/100 ({scoring_report.status})[/{scoring_report.status_color}][/bold]",
        border_style="dim",
    )
    audit_table.add_column("Pillar", style="bold cyan")
    audit_table.add_column("Criterion", style="white")
    audit_table.add_column("Status", justify="center")
    audit_table.add_column("Score", justify="right")
    audit_table.add_column("Details", style="dim")

    for c in scoring_report.criteria:
        c_status = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
        score_display = f"{c.score}/{c.max_score}"
        score_colored = f"[green]+{score_display}[/green]" if c.passed else f"[red]{score_display}[/red]"
        audit_table.add_row(c.category, c.name, c_status, score_colored, c.message)

    console.print(audit_table)

    if scoring_report.recommendations:
        rec_panel = Panel(
            "\n".join(f"  [yellow]*[/yellow] {r}" for r in scoring_report.recommendations),
            title="[bold yellow]Reproducibility Recommendations[/bold yellow]",
            border_style="yellow",
        )
        console.print(rec_panel)


@main.command()
@click.argument("run_id")
@click.option("--allow-hardware-change", is_flag=True, default=False, help="Bypass hardware warnings")
@click.option("--allow-dataset-mismatch", is_flag=True, default=False, help="Bypass dataset fingerprint mismatch")
@click.option("--allow-env-mismatch", is_flag=True, default=False, help="Bypass environment package version drift")
@click.option("--isolated", is_flag=True, default=False, help="Run in an isolated git worktree")
@click.option("--restore-env", is_flag=True, default=False, help="Reconstruct dedicated virtual environment from recorded lockfile")
@click.option("--reproduce", is_flag=True, default=False, help="1-click reproduction: implies --isolated and --restore-env")
@click.option("--recreate-env", is_flag=True, default=False, help="Force rebuilding virtual environment even if cached")
def rerun(
    run_id: str,
    allow_hardware_change: bool,
    allow_dataset_mismatch: bool,
    allow_env_mismatch: bool,
    isolated: bool,
    restore_env: bool,
    reproduce: bool,
    recreate_env: bool,
):
    """Re-execute a previous run with reproducibility preflight and lineage tracking."""
    if reproduce:
        isolated = True
        restore_env = True

    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    run_id = resolve_run_id(qr_dir, run_id)
    storage = RunStorage(qr_dir, run_id)
    try:
        manifest = storage.load_manifest()
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Run '{run_id}' not found.")
        return

    console.print(f"[bold cyan]RERUN PREFLIGHT -- {run_id}[/bold cyan]")
    report = run_rerun_preflight(
        manifest,
        project_root,
        storage.run_dir,
        allow_dataset_mismatch=allow_dataset_mismatch,
        allow_env_mismatch=allow_env_mismatch,
        restore_env=restore_env,
    )

    for item in report.checks:
        if item.passed:
            console.print(f"  [bold green][OK][/bold green] {item.name}: {item.message}")
        elif item.is_warning:
            console.print(f"  [bold yellow][!][/bold yellow] {item.name}: {item.message}")
        else:
            console.print(f"  [bold red][FAIL][/bold red] {item.name}: {item.message}")

    if not report.can_proceed:
        console.print("\n[bold red]Preflight failed:[/bold red] Cannot guarantee faithful rerun.")
        sys.exit(1)

    work_dir = project_root
    isolated_wt_path: Optional[Path] = None

    if isolated:
        if not manifest.git or not manifest.git.commit:
            console.print("[bold red]Error:[/bold red] Cannot create isolated worktree: no git commit recorded.")
            sys.exit(1)
        
        wt_dir = qr_dir / "worktrees" / f"wt_{run_id}"
        console.print(f"\n[cyan]Setting up isolated git worktree at:[/cyan] {wt_dir}")
        try:
            diff_file = storage.git_diff_path if storage.git_diff_path.exists() else None
            work_dir = create_isolated_worktree(project_root, manifest.git.commit, diff_file, wt_dir)
            isolated_wt_path = work_dir
            console.print("[bold green][OK][/bold green] Isolated worktree ready.")
        except Exception as e:
            console.print(f"[bold red]Worktree creation failed:[/bold red] {e}")
            sys.exit(1)

    venv_py_path: Optional[Path] = None
    if restore_env:
        lock_path = storage.run_dir / manifest.runtime.packages_lock
        envs_dir = qr_dir / "envs" / f"env_{run_id}"
        console.print(f"\n[cyan]Setting up restored virtual environment at:[/cyan] {envs_dir}")
        try:
            from qr.env import create_isolated_environment

            venv_py_path = create_isolated_environment(
                venv_dir=envs_dir,
                lock_path=lock_path,
                python_version=manifest.runtime.python_version,
                recreate=recreate_env,
            )
            console.print("[bold green][OK][/bold green] Restored virtual environment ready.")
        except Exception as e:
            console.print(f"[bold red]Environment restoration failed:[/bold red] {e}")
            sys.exit(1)

    console.print("\n[bold green]Preflight passed.[/bold green] Spawning rerun process...")

    # Invoke run with --parent run_id and restored venv python
    ctx = click.get_current_context()
    try:
        ctx.invoke(
            run,
            command=tuple(manifest.command),
            tag=tuple(manifest.tags),
            parent=run_id,
            custom_cwd=str(work_dir),
            venv_python=str(venv_py_path) if venv_py_path else None,
        )
    finally:
        if isolated_wt_path and isolated_wt_path.exists():
            console.print(f"[dim]Cleaning up isolated worktree at {isolated_wt_path}...[/dim]")
            cleanup_isolated_worktree(project_root, isolated_wt_path)


@main.command()
@click.option("--fix", is_flag=True, default=False, help="Auto-repair orphaned or unindexed runs")
def doctor(fix: bool):
    """Diagnose repository health, detect orphaned/interrupted runs, and sync SQLite cache."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found. Run 'qr init' first.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    runs = RunStorage.list_all_runs(qr_dir)
    db_path = qr_dir / "index.sqlite"
    index = RunIndex(db_path)

    table = Table(title="[bold cyan]QR Health & Integrity Report[/bold cyan]", border_style="dim")
    table.add_column("Category", style="bold white")
    table.add_column("Status")
    table.add_column("Details")

    # 1. Check Project Config
    proj_file = qr_dir / "project.json"
    if proj_file.is_file():
        table.add_row("Project Config", "[green][OK][/green]", str(proj_file))
    else:
        table.add_row("Project Config", "[red][MISSING][/red]", "project.json missing")

    # 2. Check for orphaned runs
    orphaned_runs = []
    for r in runs:
        if r.status == "running":
            orphaned_runs.append(r)

    if orphaned_runs:
        st_color = "[yellow]REPAIRED[/yellow]" if fix else "[red][ORPHANED][/red]"
        table.add_row(
            "Active Runs",
            st_color,
            f"Found {len(orphaned_runs)} run(s) stuck in 'running' status",
        )
        if fix:
            for r in orphaned_runs:
                r.status = "interrupted"
                r.timestamps.finished_at = datetime.now(timezone.utc).isoformat()
                storage = RunStorage(qr_dir, r.run_id)
                storage.save_manifest(r)
                index.upsert_run(r)
    else:
        table.add_row("Active Runs", "[green][OK][/green]", "All recorded runs properly finalized")

    # 3. Check SQLite Index consistency
    indexed_rows = index.list_runs(limit=1000)
    if len(indexed_rows) != len(runs):
        table.add_row(
            "SQLite Index",
            "[yellow]REBUILT[/yellow]" if fix else "[yellow]OUT OF SYNC[/yellow]",
            f"Index has {len(indexed_rows)} rows, but filesystem has {len(runs)} manifests",
        )
        if fix:
            index.rebuild_from_manifests(runs)
    else:
        table.add_row("SQLite Index", "[green][OK][/green]", f"{len(runs)} runs indexed accurately")

    # 4. Check Restorability Scores
    missing_scores = [r for r in runs if r.restorability_score is None]
    if missing_scores:
        st_color = "[yellow]BACKFILLED[/yellow]" if fix else "[yellow]UNSCORED[/yellow]"
        table.add_row(
            "Restorability Scores",
            st_color,
            f"{len(missing_scores)} run(s) missing restorability scores",
        )
        if fix:
            from qr.scoring import calculate_restorability_score
            for r in missing_scores:
                storage = RunStorage(qr_dir, r.run_id)
                report = calculate_restorability_score(r, storage.run_dir)
                r.restorability_score = report.score
                r.restorability_status = report.status
                storage.save_manifest(r)
                index.upsert_run(r)
    else:
        table.add_row("Restorability Scores", "[green][OK][/green]", "All runs scored")

    console.print(table)
    if not fix and (orphaned_runs or len(indexed_rows) != len(runs) or missing_scores):
        console.print("\n[yellow]Run [bold]qr doctor --fix[/bold] to auto-repair these issues.[/yellow]")


@main.command()
@click.argument("run_id_1")
@click.argument("run_id_2")
def diff(run_id_1: str, run_id_2: str):
    """Compare configuration, source, metrics, and outcomes between two runs."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    run_id_1 = resolve_run_id(qr_dir, run_id_1)
    run_id_2 = resolve_run_id(qr_dir, run_id_2)
    storage1 = RunStorage(qr_dir, run_id_1)
    storage2 = RunStorage(qr_dir, run_id_2)

    try:
        m1 = storage1.load_manifest()
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Run '{run_id_1}' not found.")
        return

    try:
        m2 = storage2.load_manifest()
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Run '{run_id_2}' not found.")
        return

    table = Table(title=f"[bold cyan]Run Comparison: {run_id_1} vs {run_id_2}[/bold cyan]", border_style="dim")
    table.add_column("Property", style="bold white")
    table.add_column(run_id_1, style="cyan")
    table.add_column(run_id_2, style="cyan")

    # Status & Timing
    table.add_row(
        "Status",
        f"[{'green' if m1.status == 'completed' else 'red'}]{m1.status}[/] (exit={m1.exit_code})",
        f"[{'green' if m2.status == 'completed' else 'red'}]{m2.status}[/] (exit={m2.exit_code})",
    )
    table.add_row("Started", format_timestamp(m1.timestamps.started_at), format_timestamp(m2.timestamps.started_at))
    table.add_row("Ended", format_timestamp(m1.timestamps.finished_at), format_timestamp(m2.timestamps.finished_at))
    table.add_row("Duration", format_duration(m1.duration_seconds), format_duration(m2.duration_seconds))
    table.add_row("Tags", ", ".join(m1.tags) or "-", ", ".join(m2.tags) or "-")
    table.add_row("Command", " ".join(m1.command), " ".join(m2.command))

    # Git
    c1 = (m1.git.commit[:7] if m1.git and m1.git.commit else "-") + (" (dirty)" if m1.git and m1.git.dirty else "")
    c2 = (m2.git.commit[:7] if m2.git and m2.git.commit else "-") + (" (dirty)" if m2.git and m2.git.dirty else "")
    table.add_row("Git Commit", c1, c2)

    # Runtime & Hardware
    table.add_row("Python", m1.runtime.python_version, m2.runtime.python_version)
    table.add_row("OS", m1.runtime.os, m2.runtime.os)
    g1 = ", ".join(m1.hardware.gpu) if m1.hardware.gpu else "None"
    g2 = ", ".join(m2.hardware.gpu) if m2.hardware.gpu else "None"
    table.add_row("GPU", g1, g2)

    # Compare CLI parameters if present
    all_params = sorted(set(list(m1.inputs.parameters.keys()) + list(m2.inputs.parameters.keys())))
    for p in all_params:
        v1 = m1.inputs.parameters.get(p, "-")
        v2 = m2.inputs.parameters.get(p, "-")
        diff_str = ""
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            delta = v2 - v1
            sign = "+" if delta > 0 else ""
            diff_str = f" [dim]({sign}{delta})[/dim]"
        table.add_row(f"Param: --{p}", str(v1), f"{v2}{diff_str}")

    # Compare latest metrics
    def _get_latest_metrics(storage: RunStorage):
        if storage.metrics_path.exists():
            lines = storage.metrics_path.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                try:
                    return json.loads(lines[-1])
                except Exception:
                    pass
        return {}

    met1 = _get_latest_metrics(storage1)
    met2 = _get_latest_metrics(storage2)
    all_keys = sorted(set(list(met1.keys()) + list(met2.keys())))

    for k in all_keys:
        if k == "timestamp":
            continue
        v1 = met1.get(k, "-")
        v2 = met2.get(k, "-")
        diff_str = ""
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            delta = v2 - v1
            sign = "+" if delta > 0 else ""
            diff_str = f" [dim]({sign}{delta:.4f})[/dim]"
        table.add_row(f"Metric: {k}", str(v1), f"{v2}{diff_str}")

    console.print(table)


@main.group(name="env")
def env_group():
    """Manage and inspect experiment execution environments."""
    pass


@env_group.command(name="diff")
@click.argument("run_id")
def env_diff_cmd(run_id: str):
    """Compare recorded packages of a run against the current Python environment."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    run_id = resolve_run_id(qr_dir, run_id)
    storage = RunStorage(qr_dir, run_id)
    try:
        manifest = storage.load_manifest()
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Run '{run_id}' not found.")
        return

    if not manifest.runtime.packages_lock:
        console.print(f"[bold yellow]Warning:[/bold yellow] Run '{run_id}' has no recorded package lockfile.")
        return

    lock_path = storage.run_dir / manifest.runtime.packages_lock
    if not lock_path.exists():
        console.print(f"[bold red]Error:[/bold red] Lockfile '{lock_path}' not found on disk.")
        return

    from qr.env import diff_environments

    content = lock_path.read_text(encoding="utf-8", errors="replace")
    report = diff_environments(content, recorded_python=manifest.runtime.python_version)

    console.print(f"\n[bold cyan]Environment Drift Analysis -- {run_id}[/bold cyan]")
    py_st = (
        "[green]MATCH[/green]"
        if report.python_match
        else f"[bold red]MISMATCH[/bold red] (Run: {report.recorded_python} vs Current: {report.current_python})"
    )
    console.print(f"  Python Version: {py_st}")

    table = Table(title=f"Package Comparison ({run_id} vs Current Env)", border_style="dim")
    table.add_column("Package", style="bold white")
    table.add_column("Recorded Version", style="cyan")
    table.add_column("Current Version", style="magenta")
    table.add_column("Status", justify="center")

    # Mismatched packages
    for pkg, (rec_ver, cur_ver) in sorted(report.version_mismatches.items()):
        table.add_row(pkg, rec_ver, cur_ver, "[bold yellow]VERSION DRIFT[/bold yellow]")

    # Missing packages
    for pkg, rec_ver in sorted(report.missing_packages.items()):
        table.add_row(pkg, rec_ver, "[dim]<not installed>[/dim]", "[bold red]MISSING[/bold red]")

    # Extra packages (show up to 15)
    extra_items = list(report.extra_packages.items())
    for pkg, cur_ver in sorted(extra_items[:15]):
        table.add_row(pkg, "[dim]<not in run>[/dim]", cur_ver, "[dim cyan]EXTRA[/dim cyan]")
    if len(extra_items) > 15:
        table.add_row("...", "...", "...", f"[dim]... and {len(extra_items) - 15} more extras[/dim]")

    console.print(table)
    summary_parts = []
    summary_parts.append(f"[green]{len(report.matching_packages)} matching[/green]")
    if report.version_mismatches:
        summary_parts.append(f"[bold yellow]{len(report.version_mismatches)} drifted[/bold yellow]")
    if report.missing_packages:
        summary_parts.append(f"[bold red]{len(report.missing_packages)} missing[/bold red]")
    if report.extra_packages:
        summary_parts.append(f"[dim]{len(report.extra_packages)} extra in current[/dim]")

    console.print(f"\nSummary: {', '.join(summary_parts)}")
    if report.has_drift:
        console.print("[yellow][!] Environment drift detected. To rerun anyway, use: qr rerun <run_id> --allow-env-mismatch[/yellow]")
    else:
        console.print("[green][OK] Environment matches recorded run perfectly.[/green]")


@env_group.command(name="list")
def env_list_cmd():
    """List all cached virtual environments managed by qr."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    from qr.env import list_cached_envs

    cached = list_cached_envs(qr_dir)
    if not cached:
        console.print("[dim]No cached virtual environments found in .qr/envs/.[/dim]")
        return

    table = Table(title="Cached Virtual Environments", border_style="dim")
    table.add_column("Run ID", style="bold cyan")
    table.add_column("Status", justify="center")
    table.add_column("Size (MB)", justify="right")
    table.add_column("Created", style="dim")
    table.add_column("Path", style="dim")

    total_mb = 0.0
    for env in cached:
        status = "[green]VALID[/green]" if env["valid"] else "[bold red]INVALID[/bold red]"
        table.add_row(
            env["run_id"],
            status,
            f"{env['size_mb']:.1f}",
            env["created_at"],
            env["path"],
        )
        total_mb += env["size_mb"]

    console.print(table)
    console.print(f"\n[dim]Total cached environments: {len(cached)} ({total_mb:.1f} MB)[/dim]")
    console.print("[dim]Use 'qr env clean --all' to reclaim disk space.[/dim]")


@env_group.command(name="clean")
@click.option("--run-id", default=None, help="Specific run ID environment to remove.")
@click.option("--all", "clean_all", is_flag=True, help="Remove all cached virtual environments.")
def env_clean_cmd(run_id: Optional[str], clean_all: bool):
    """Clean cached virtual environments created for reruns."""
    if not run_id and not clean_all:
        console.print("[yellow]Specify either --run-id <run_id> or --all to clean environments.[/yellow]")
        return

    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
    from qr.env import clean_cached_envs

    if run_id:
        run_id = resolve_run_id(qr_dir, run_id)
    count = clean_cached_envs(qr_dir, run_id=run_id if not clean_all else None)
    if count == 0:
        console.print("[dim]No matching cached environments found to remove.[/dim]")
    else:
        console.print(f"[green][OK][/green] Removed {count} cached virtual environment(s).")


if __name__ == "__main__":
    main()


