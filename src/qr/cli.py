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
from qr.storage.local import RunStorage, generate_run_id
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
def run(command: tuple, tag: tuple, parent: Optional[str], custom_cwd: Optional[str]):
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

    runtime_snap = capture_runtime_snapshot(run_dir)
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

    storage.save_manifest(manifest)

    # Update SQLite index
    db_path = qr_dir / "index.sqlite"
    index = RunIndex(db_path)
    index.upsert_run(manifest)

    status_color = "green" if manifest.status == "completed" else "red"
    console.print(
        f"\n[bold {status_color}]Run {manifest.status}:[/bold {status_color}] "
        f"exit={exec_result.exit_code}, duration={exec_result.duration_seconds}s "
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
    table.add_column("Tags", style="magenta")
    table.add_column("Command", style="white")
    table.add_column("Duration", justify="right")
    table.add_column("Commit", style="dim")
    table.add_column("Dirty", justify="center")
    table.add_column("Started", style="dim")

    for row in rows:
        st = row["status"]
        st_color = "green" if st == "completed" else ("red" if st == "failed" else "yellow")
        dur_str = f"{row['duration_seconds']:.1f}s" if row["duration_seconds"] is not None else "-"
        commit_str = (row["git_commit"][:7]) if row.get("git_commit") else "-"
        dirty_str = "[yellow]yes[/yellow]" if row.get("git_dirty") else "[green]no[/green]"
        started_str = row["started_at"][:19].replace("T", " ") if row.get("started_at") else "-"
        tags_str = row.get("tags") or "-"

        table.add_row(
            row["run_id"],
            f"[{st_color}]{st}[/{st_color}]",
            tags_str,
            row["command"],
            dur_str,
            commit_str,
            dirty_str,
            started_str,
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
    storage = RunStorage(qr_dir, run_id)
    try:
        manifest = storage.load_manifest()
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/bold red] Run '{run_id}' not found.")
        return

    # Build Rich Display matching Phụ lục A
    st = manifest.status.upper()
    st_color = "green" if st == "COMPLETED" else "red"

    content = []
    content.append(f"[bold]Status:[/bold]       [{st_color}]{st}[/{st_color}] (exit={manifest.exit_code})")
    content.append(f"[bold]Started:[/bold]      {manifest.timestamps.started_at}")
    content.append(f"[bold]Duration:[/bold]     {manifest.duration_seconds}s")
    if manifest.tags:
        content.append(f"[bold]Tags:[/bold]         [magenta]{', '.join(manifest.tags)}[/magenta]")
    content.append(f"[bold]Command:[/bold]      [white]{' '.join(manifest.command)}[/white]")
    content.append(f"[bold]Directory:[/bold]    [dim]{manifest.cwd}[/dim]")

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

    content.append("\n[bold cyan]REPRODUCIBILITY CONTRACT[/bold cyan]")
    content.append("  Traceable:   [bold green]YES[/bold green] (Full snapshot & log preserved)")
    has_lock = bool(manifest.runtime.packages_lock)
    content.append(f"  Restorable:  {'[green]LIKELY[/green]' if has_lock else '[yellow]PARTIAL[/yellow]'}")
    content.append("  Lineage:     Parent=" + (manifest.parent_run_id or "Root run"))

    console.print(
        Panel(
            "\n".join(content),
            title=f"[bold cyan]Experiment Run Details -- {run_id}[/bold cyan]",
            border_style="cyan",
        )
    )


@main.command()
@click.argument("run_id")
@click.option("--allow-hardware-change", is_flag=True, default=False, help="Bypass hardware warnings")
@click.option("--allow-dataset-mismatch", is_flag=True, default=False, help="Bypass dataset fingerprint mismatch")
@click.option("--isolated", is_flag=True, default=False, help="Run in an isolated git worktree")
def rerun(run_id: str, allow_hardware_change: bool, allow_dataset_mismatch: bool, isolated: bool):
    """Re-execute a previous run with reproducibility preflight and lineage tracking."""
    project_root = find_project_root()
    if not project_root:
        console.print("[yellow]No QR project found.[/yellow]")
        return

    qr_dir = get_qr_dir(project_root)
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

    console.print("\n[bold green]Preflight passed.[/bold green] Spawning rerun process...")

    # Invoke run with --parent run_id
    ctx = click.get_current_context()
    try:
        ctx.invoke(
            run,
            command=tuple(manifest.command),
            tag=tuple(manifest.tags),
            parent=run_id,
            custom_cwd=str(work_dir),
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

    console.print(table)
    if not fix and (orphaned_runs or len(indexed_rows) != len(runs)):
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

    # Status & Exit
    table.add_row(
        "Status",
        f"[{'green' if m1.status == 'completed' else 'red'}]{m1.status}[/] (exit={m1.exit_code})",
        f"[{'green' if m2.status == 'completed' else 'red'}]{m2.status}[/] (exit={m2.exit_code})",
    )
    table.add_row("Duration", f"{m1.duration_seconds}s", f"{m2.duration_seconds}s")
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


if __name__ == "__main__":
    main()
