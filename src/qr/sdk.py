"""
Tiny Python SDK
===============
Provides semantic logging, artifact registration, dataset declarations, and
in-process experiment tracking for Python scripts.

Can be run via:
1. CLI wrapper: `qr run -- python train.py`
2. In-code activation: Call `qr.activate()` inside `train.py` (e.g. before return).
3. Context manager: `with qr.run(...) as r:` for GridSearch / multi-run loops.
"""

from __future__ import annotations

import atexit
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Union

ENV_RUN_ID = "QR_RUN_ID"
ENV_RUN_DIR = "QR_RUN_DIR"

# Global session state
_PROCESS_START_PERF = time.perf_counter()
_PROCESS_START_ISO = datetime.now(timezone.utc).isoformat()

_BUFFERED_METRICS: List[Dict[str, Any]] = []
_BUFFERED_ARTIFACTS: List[Dict[str, Any]] = []
_BUFFERED_DATASETS: List[Dict[str, Any]] = []
_BUFFERED_NOTES: List[Dict[str, Any]] = []
_BUFFERED_PARAMS: Dict[str, Any] = {}

_ACTIVE_RUN_ID: Optional[str] = None
_ACTIVE_RUN_STORAGE: Optional[Any] = None
_ACTIVE_RUN_DIR: Optional[Path] = None
_ACTIVE_MANIFEST: Optional[Any] = None
_IS_FINALIZED: bool = False


class _RunState:
    """Tracks state of an individual active run (used for stack-based nesting)."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        storage: Any,
        manifest: Any,
        start_perf: float,
        start_iso: str,
    ):
        self.run_id = run_id
        self.run_dir = run_dir
        self.storage = storage
        self.manifest = manifest
        self.start_perf = start_perf
        self.start_iso = start_iso
        self.is_finalized = False


_RUN_STACK: List[_RunState] = []

_ORIGINAL_EXCEPHOOK = sys.excepthook
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr


class _TeeStream:
    """Tee a stream to both its original destination and a log file."""

    def __init__(self, original: Any, file_path: Path):
        self._original = original
        self._file = open(file_path, "a", encoding="utf-8", errors="replace")

    def write(self, data: str):
        try:
            self._original.write(data)
        except Exception:
            pass
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        try:
            self._file.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return getattr(self._original, "isatty", lambda: False)()

    def close(self):
        try:
            self._file.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _StreamStack:
    """Maintains a stack of tee streams for nested run contexts."""

    def __init__(self):
        self._stack: List[tuple] = []

    def push(self, stdout_path: Path, stderr_path: Path):
        try:
            stdout_tee = _TeeStream(sys.stdout, stdout_path)
            stderr_tee = _TeeStream(sys.stderr, stderr_path)
            self._stack.append((sys.stdout, sys.stderr, stdout_tee, stderr_tee))
            sys.stdout = stdout_tee
            sys.stderr = stderr_tee
        except Exception:
            pass

    def pop(self):
        if not self._stack:
            return
        orig_stdout, orig_stderr, stdout_tee, stderr_tee = self._stack.pop()
        stdout_tee.close()
        stderr_tee.close()
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr


_STREAM_STACK = _StreamStack()
_TEE_STDOUT: Optional[_TeeStream] = None
_TEE_STDERR: Optional[_TeeStream] = None


def _restore_streams():
    global _TEE_STDOUT, _TEE_STDERR
    if _TEE_STDOUT:
        sys.stdout = _TEE_STDOUT._original
        _TEE_STDOUT.close()
        _TEE_STDOUT = None
    if _TEE_STDERR:
        sys.stderr = _TEE_STDERR._original
        _TEE_STDERR.close()
        _TEE_STDERR = None


def _get_run_dir() -> Optional[Path]:
    """Get active run directory from run stack, environment, or in-process session."""
    if _RUN_STACK:
        return _RUN_STACK[-1].run_dir
    run_dir_str = os.environ.get(ENV_RUN_DIR)
    if run_dir_str:
        p = Path(run_dir_str)
        if p.exists():
            return p
    if _ACTIVE_RUN_DIR and _ACTIVE_RUN_DIR.exists():
        return _ACTIVE_RUN_DIR
    return None


def _get_run_id() -> Optional[str]:
    """Get active run ID."""
    if _RUN_STACK:
        return _RUN_STACK[-1].run_id
    return os.environ.get(ENV_RUN_ID) or _ACTIVE_RUN_ID


def _calculate_file_checksum(file_path: Path) -> Optional[str]:
    """Calculate SHA256 of file if it exists and is under 500MB."""
    try:
        if file_path.is_file() and file_path.stat().st_size <= 500 * 1024 * 1024:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
    except Exception:
        pass
    return None


def calculate_path_fingerprint(target: Path) -> Optional[str]:
    """Calculate SHA256 fingerprint for a file or directory (< 500MB)."""
    try:
        if not target.exists():
            return None
        hasher = hashlib.sha256()
        if target.is_file():
            if target.stat().st_size > 500 * 1024 * 1024:
                return None
            with open(target, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return f"sha256:{hasher.hexdigest()}"
        elif target.is_dir():
            files = sorted([p for p in target.rglob("*") if p.is_file()])
            if len(files) > 1000:
                for f in files[:1000]:
                    rel = str(f.relative_to(target))
                    hasher.update(f"{rel}:{f.stat().st_size}".encode("utf-8"))
            else:
                for f in files:
                    rel = str(f.relative_to(target))
                    hasher.update(rel.encode("utf-8"))
                    if f.stat().st_size <= 50 * 1024 * 1024:
                        with open(f, "rb") as fp:
                            for chunk in iter(lambda: fp.read(65536), b""):
                                hasher.update(chunk)
            return f"sha256:{hasher.hexdigest()}"
    except Exception:
        pass
    return None


def log(metrics: Dict[str, Any]) -> None:
    """
    Append structured metrics to `metrics.jsonl`.
    Adds an automatic timestamp if not already provided.
    If run directly (without active run), buffers metrics until `qr.activate()` or `qr.run()`.
    """
    payload = {"timestamp": time.time(), **metrics}
    run_dir = _get_run_dir()
    if run_dir:
        metrics_path = run_dir / "metrics.jsonl"
        try:
            with open(metrics_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception:
            pass
    else:
        _BUFFERED_METRICS.append(payload)


def params(parameters: Dict[str, Any]) -> None:
    """
    Declare or update in-code hyperparameters/parameters.
    Saved to manifest inputs and displayed in `qr show`.
    """
    global _BUFFERED_PARAMS
    active_manifest = None
    active_storage = None
    if _RUN_STACK:
        active_manifest = _RUN_STACK[-1].manifest
        active_storage = _RUN_STACK[-1].storage
    elif _ACTIVE_MANIFEST:
        active_manifest = _ACTIVE_MANIFEST
        active_storage = _ACTIVE_RUN_STORAGE

    if active_manifest:
        active_manifest.inputs.parameters.update(parameters)
        if active_storage:
            try:
                active_storage.save_manifest(active_manifest)
            except Exception:
                pass
    else:
        _BUFFERED_PARAMS.update(parameters)


def artifact(path: str, kind: Optional[str] = "generic", metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Register an output artifact reference (model checkpoint, eval report, plot, etc.).
    Records path, size, and checksum.
    """
    file_path = Path(path)
    size_bytes = file_path.stat().st_size if file_path.is_file() else None
    checksum = _calculate_file_checksum(file_path)

    record = {
        "path": str(path),
        "kind": kind,
        "size_bytes": size_bytes,
        "checksum": checksum,
        "metadata": metadata or {},
    }

    run_dir = _get_run_dir()
    if run_dir:
        artifacts_path = run_dir / "artifacts.json"
        artifacts_list = []
        if artifacts_path.exists():
            try:
                artifacts_list = json.loads(artifacts_path.read_text(encoding="utf-8"))
            except Exception:
                artifacts_list = []
        artifacts_list.append(record)
        try:
            artifacts_path.write_text(json.dumps(artifacts_list, indent=2), encoding="utf-8")
        except Exception:
            pass
    else:
        _BUFFERED_ARTIFACTS.append(record)


def input_dataset(name: str, uri: str, version: Optional[str] = None, fingerprint: Optional[str] = None) -> None:
    """
    Declare an input dataset reference, version, and fingerprint.
    """
    fp = fingerprint
    if not fp:
        local_p = Path(uri)
        if local_p.exists():
            fp = calculate_path_fingerprint(local_p)

    record = {
        "name": name,
        "uri": uri,
        "version": version,
        "fingerprint": fp,
    }

    run_dir = _get_run_dir()
    if run_dir:
        datasets_path = run_dir / "inputs_datasets.json"
        datasets_list = []
        if datasets_path.exists():
            try:
                datasets_list = json.loads(datasets_path.read_text(encoding="utf-8"))
            except Exception:
                datasets_list = []
        datasets_list.append(record)
        try:
            datasets_path.write_text(json.dumps(datasets_list, indent=2), encoding="utf-8")
        except Exception:
            pass
    else:
        _BUFFERED_DATASETS.append(record)


def note(text: str) -> None:
    """Append an annotation to notes.jsonl."""
    payload = {"timestamp": time.time(), "text": text}
    run_dir = _get_run_dir()
    if run_dir:
        notes_path = run_dir / "notes.jsonl"
        try:
            with open(notes_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception:
            pass
    else:
        _BUFFERED_NOTES.append(payload)


@contextlib.contextmanager
def timer(name: str = "training_duration_seconds"):
    """
    Context manager to measure and automatically log execution time of a block.
    Saves the elapsed duration in seconds to metrics.jsonl.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - t0, 4)
        log({name: elapsed})


def _coerce_param_value(val: str) -> Any:
    """Convert numeric string to float/int if possible."""
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def _extract_cli_parameters(cmd_list: List[str]):
    """Extract config files and CLI flags/parameters from command."""
    configs: List[str] = []
    params_dict: Dict[str, Any] = {}
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
                params_dict[k] = _coerce_param_value(v)
            elif i + 1 < len(cmd_list) and not cmd_list[i + 1].startswith("-"):
                params_dict[key_part] = _coerce_param_value(cmd_list[i + 1])
                skip_next = True
            else:
                params_dict[key_part] = True
    return configs, params_dict


def _format_timestamp(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "-"
    clean = iso_str.replace("T", " ")
    if "." in clean:
        clean = clean.split(".")[0]
    elif "+" in clean:
        clean = clean.split("+")[0]
    return clean


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.2f}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{int(m)}m {s:.1f}s ({seconds:.1f}s)"
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m {s:.0f}s ({seconds:.1f}s)"


def _flush_buffers_to_dir(target_dir: Path) -> None:
    """Flush any buffered in-memory items to target run directory."""
    global _BUFFERED_METRICS, _BUFFERED_ARTIFACTS, _BUFFERED_DATASETS, _BUFFERED_NOTES

    if _BUFFERED_METRICS:
        metrics_path = target_dir / "metrics.jsonl"
        try:
            with open(metrics_path, "a", encoding="utf-8") as f:
                for m in _BUFFERED_METRICS:
                    f.write(json.dumps(m) + "\n")
        except Exception:
            pass
        _BUFFERED_METRICS.clear()

    if _BUFFERED_ARTIFACTS:
        artifacts_path = target_dir / "artifacts.json"
        artifacts_list = []
        if artifacts_path.exists():
            try:
                artifacts_list = json.loads(artifacts_path.read_text(encoding="utf-8"))
            except Exception:
                artifacts_list = []
        artifacts_list.extend(_BUFFERED_ARTIFACTS)
        try:
            artifacts_path.write_text(json.dumps(artifacts_list, indent=2), encoding="utf-8")
        except Exception:
            pass
        _BUFFERED_ARTIFACTS.clear()

    if _BUFFERED_DATASETS:
        datasets_path = target_dir / "inputs_datasets.json"
        datasets_list = []
        if datasets_path.exists():
            try:
                datasets_list = json.loads(datasets_path.read_text(encoding="utf-8"))
            except Exception:
                datasets_list = []
        datasets_list.extend(_BUFFERED_DATASETS)
        try:
            datasets_path.write_text(json.dumps(datasets_list, indent=2), encoding="utf-8")
        except Exception:
            pass
        _BUFFERED_DATASETS.clear()

    if _BUFFERED_NOTES:
        notes_path = target_dir / "notes.jsonl"
        try:
            with open(notes_path, "a", encoding="utf-8") as f:
                for n in _BUFFERED_NOTES:
                    f.write(json.dumps(n) + "\n")
        except Exception:
            pass
        _BUFFERED_NOTES.clear()


def _finalize_state(state: _RunState, status: str = "completed", exit_code: int = 0) -> None:
    """Finalize a specific run state, persist its manifest and update index."""
    if state.is_finalized:
        return

    _flush_buffers_to_dir(state.run_dir)

    now_iso = datetime.now(timezone.utc).isoformat()
    duration = max(0.01, round(time.perf_counter() - state.start_perf, 2))

    state.manifest.timestamps.finished_at = now_iso
    state.manifest.duration_seconds = duration
    state.manifest.exit_code = exit_code
    state.manifest.status = status

    # Re-collect datasets if registered
    datasets_file = state.run_dir / "inputs_datasets.json"
    if datasets_file.exists():
        try:
            from qr.manifest import DatasetInput
            ds_data = json.loads(datasets_file.read_text(encoding="utf-8"))
            state.manifest.inputs.datasets = [DatasetInput(**item) for item in ds_data]
        except Exception:
            pass

    # Calculate Restorability Score
    report = None
    try:
        from qr.scoring import calculate_restorability_score
        report = calculate_restorability_score(state.manifest, state.run_dir)
        state.manifest.restorability_score = report.score
        state.manifest.restorability_status = report.status
    except Exception:
        pass

    state.storage.save_manifest(state.manifest)

    # Update SQLite index
    try:
        from qr.storage.index import RunIndex
        db_path = state.storage.qr_dir / "index.sqlite"
        index = RunIndex(db_path)
        index.upsert_run(state.manifest)
    except Exception:
        pass

    # Print completion summary banner
    try:
        from rich.console import Console
        console = Console()
        status_color = "green" if status == "completed" else "red"
        score_msg = ""
        if report:
            score_msg = f", restorability={report.score}/100 [{report.status_color}]({report.status})[/{report.status_color}]"
        console.print(
            f"\n[bold {status_color}]Run {status}: exit={exit_code}[/bold {status_color}], "
            f"duration={_format_duration(duration)}, "
            f"ended={_format_timestamp(now_iso)}{score_msg} "
            f"[dim]({state.run_id})[/dim]"
        )
    except Exception:
        pass

    state.is_finalized = True


def _finalize_run(status: str = "completed", exit_code: int = 0) -> None:
    """Finalize the active in-process run and persist manifest & sqlite index."""
    global _IS_FINALIZED, _ACTIVE_MANIFEST, _ACTIVE_RUN_STORAGE, _ACTIVE_RUN_DIR
    if _IS_FINALIZED or not _ACTIVE_MANIFEST or not _ACTIVE_RUN_STORAGE or not _ACTIVE_RUN_DIR:
        return

    state = _RunState(
        run_id=_ACTIVE_RUN_ID,
        run_dir=_ACTIVE_RUN_DIR,
        storage=_ACTIVE_RUN_STORAGE,
        manifest=_ACTIVE_MANIFEST,
        start_perf=_PROCESS_START_PERF,
        start_iso=_PROCESS_START_ISO,
    )
    _finalize_state(state, status=status, exit_code=exit_code)
    _restore_streams()
    _IS_FINALIZED = True


def _atexit_handler():
    """Safety callback to ensure in-process run is cleanly finalized upon exit."""
    if not _IS_FINALIZED and _ACTIVE_MANIFEST and _ACTIVE_RUN_STORAGE:
        _finalize_run(status="completed", exit_code=0)


def _qr_excepthook(exc_type, exc_value, exc_traceback):
    """Safety callback to mark run as failed if an unhandled exception occurred."""
    if not _IS_FINALIZED and _ACTIVE_MANIFEST and _ACTIVE_RUN_STORAGE:
        _finalize_run(status="failed", exit_code=1)
    if _ORIGINAL_EXCEPHOOK:
        _ORIGINAL_EXCEPHOOK(exc_type, exc_value, exc_traceback)


def activate(
    *,
    tag: Optional[Union[str, List[str]]] = None,
    parent: Optional[str] = None,
    cwd: Optional[Union[str, Path]] = None,
    command: Optional[List[str]] = None,
    finalize: Optional[bool] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Activate QR experiment tracking directly from Python code.

    Can be called:
    1. At the end of training / before return (e.g. `qr.activate()`):
       Automatically initializes the run, commits all buffered metrics/artifacts,
       saves the manifest & sqlite index, and prints the completion summary.
    2. At the start of the script:
       Initializes the run, captures git & hardware snapshots, and registers
       an automatic completion hook upon script exit.
    3. Seamlessly compatible with `qr run`:
       If the script is executed via CLI (`qr run -- python ...`), `activate()`
       automatically detects the existing CLI session and acts as a no-op.

    Args:
        tag: Optional tag or list of tags to label the experiment.
        parent: Optional parent run ID for lineage tracking.
        cwd: Working directory (defaults to Path.cwd()).
        command: Command list (defaults to `python sys.argv`).
        finalize: Explicitly force finalization immediately (True) or keep open (False).
                  If None, auto-detected.
        params: In-code dictionary of hyperparameters/parameters to record.

    Returns:
        The active run_id.
    """
    global _ACTIVE_RUN_ID, _ACTIVE_RUN_DIR, _ACTIVE_RUN_STORAGE, _ACTIVE_MANIFEST, _IS_FINALIZED, _BUFFERED_PARAMS

    if params:
        _BUFFERED_PARAMS.update(params)

    # 1. If already finalized in this process, return run_id
    if _IS_FINALIZED and _ACTIVE_RUN_ID:
        return _ACTIVE_RUN_ID

    # 2. If running under `qr run` CLI wrapper
    cli_run_dir = os.environ.get(ENV_RUN_DIR)
    if cli_run_dir:
        target = Path(cli_run_dir)
        if target.exists():
            _flush_buffers_to_dir(target)
        return os.environ.get(ENV_RUN_ID)

    # 3. If an in-process run is already active and activate() is called again (e.g. at the end)
    if _ACTIVE_RUN_DIR and not _IS_FINALIZED:
        if _ACTIVE_MANIFEST and _BUFFERED_PARAMS:
            _ACTIVE_MANIFEST.inputs.parameters.update(_BUFFERED_PARAMS)
        _finalize_run(status="completed", exit_code=0)
        return _ACTIVE_RUN_ID

    # 4. Initialize in-process run
    from qr.manifest import DatasetInput, RunInputs, RunManifest, Timestamps
    from qr.project import find_project_root, get_qr_dir, init_project, is_project_initialized
    from qr.snapshot.git import capture_git_snapshot
    from qr.snapshot.hardware import capture_hardware_snapshot
    from qr.snapshot.runtime import capture_runtime_snapshot
    from qr.storage.local import RunStorage, generate_run_id
    from rich.console import Console
    from rich.text import Text

    console = Console()

    work_dir = Path(cwd).resolve() if cwd else Path.cwd()
    project_root = find_project_root(work_dir)
    if project_root is None or not is_project_initialized(project_root):
        project_root = work_dir
        init_project(project_root)

    qr_dir = get_qr_dir(project_root)
    run_id = generate_run_id()
    storage = RunStorage(qr_dir, run_id)
    run_dir = storage.init_run_dir()

    _ACTIVE_RUN_ID = run_id
    _ACTIVE_RUN_DIR = run_dir
    _ACTIVE_RUN_STORAGE = storage
    os.environ[ENV_RUN_ID] = run_id
    os.environ[ENV_RUN_DIR] = str(run_dir)

    # Start teeing stdout & stderr into run directory
    _setup_streams(storage.stdout_path, storage.stderr_path)

    # Pre-run snapshots
    git_snap = capture_git_snapshot(project_root, run_dir)
    if git_snap and git_snap.dirty:
        warning_text = Text("[!] Working tree contains uncommitted changes. Snapshotting diff:\n", style="bold yellow")
        for f in git_snap.modified_files[:10]:
            warning_text.append(f"  - {f}\n", style="yellow")
        if len(git_snap.modified_files) > 10:
            warning_text.append(f"  ... and {len(git_snap.modified_files) - 10} more\n", style="dim yellow")
        console.print(warning_text)

    runtime_snap = capture_runtime_snapshot(run_dir, repo_root=project_root)
    hardware_snap = capture_hardware_snapshot()

    # Command detection from sys.argv
    if command:
        cmd_list = list(command)
    else:
        cmd_list = ["python", *[str(a) for a in sys.argv]]

    detected_configs, detected_params = _extract_cli_parameters(cmd_list)
    # Merge in-code params with CLI detected params
    detected_params.update(_BUFFERED_PARAMS)

    tags_list = [tag] if isinstance(tag, str) else list(tag or [])

    tag_str = f" [magenta][{', '.join(tags_list)}][/magenta]" if tags_list else ""
    console.print(f"[bold cyan]Run {run_id}[/bold cyan]{tag_str} started [dim]({_format_timestamp(_PROCESS_START_ISO)})[/dim]")

    # Check if buffered calls exist
    has_buffered_data = bool(_BUFFERED_METRICS or _BUFFERED_ARTIFACTS or _BUFFERED_DATASETS or _BUFFERED_NOTES or _BUFFERED_PARAMS)

    # Flush all buffers to run_dir
    _flush_buffers_to_dir(run_dir)

    # Collect dataset inputs
    datasets_file = run_dir / "inputs_datasets.json"
    dataset_inputs = []
    if datasets_file.exists():
        try:
            ds_data = json.loads(datasets_file.read_text(encoding="utf-8"))
            dataset_inputs = [DatasetInput(**item) for item in ds_data]
        except Exception:
            pass

    manifest = RunManifest(
        run_id=run_id,
        parent_run_id=parent,
        tags=tags_list,
        command=cmd_list,
        cwd=str(work_dir),
        timestamps=Timestamps(started_at=_PROCESS_START_ISO),
        git=git_snap,
        runtime=runtime_snap,
        hardware=hardware_snap,
        inputs=RunInputs(
            configs=detected_configs,
            parameters=detected_params,
            datasets=dataset_inputs,
        ),
        status="running",
    )
    storage.save_manifest(manifest)
    _ACTIVE_MANIFEST = manifest

    # Register safety hooks for process termination / exceptions
    atexit.register(_atexit_handler)
    sys.excepthook = _qr_excepthook

    # Determine finalization behavior
    should_finalize = finalize if finalize is not None else has_buffered_data

    if should_finalize:
        _finalize_run(status="completed", exit_code=0)

    return run_id


def finish(status: str = "completed", exit_code: int = 0) -> None:
    """Manually finalize the active in-process run."""
    _finalize_run(status=status, exit_code=exit_code)


# Alias
init = activate


class RunContext:
    """Context object yielded by `with qr.run(...) as run:`."""

    def __init__(self, run_id: str, run_dir: Path):
        self.id = run_id
        self.run_id = run_id
        self.run_dir = run_dir

    def log(self, metrics: Dict[str, Any]) -> None:
        log(metrics)

    def artifact(self, path: str, kind: Optional[str] = "generic", metadata: Optional[Dict[str, Any]] = None) -> None:
        artifact(path, kind, metadata)

    def params(self, parameters: Dict[str, Any]) -> None:
        params(parameters)

    def note(self, text: str) -> None:
        note(text)

    def input_dataset(self, name: str, uri: str, version: Optional[str] = None, fingerprint: Optional[str] = None) -> None:
        input_dataset(name, uri, version, fingerprint)

    def timer(self, name: str = "training_duration_seconds"):
        return timer(name)


class _RunContextManager:
    """Context manager for `with qr.run(...)`."""

    def __init__(
        self,
        *,
        tag: Optional[Union[str, List[str]]] = None,
        parent: Optional[str] = None,
        cwd: Optional[Union[str, Path]] = None,
        command: Optional[List[str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        self.tag = tag
        self.parent = parent
        self.cwd = cwd
        self.command = command
        self.params = params or {}
        self.state: Optional[_RunState] = None

    def __enter__(self) -> RunContext:
        from qr.manifest import RunInputs, RunManifest, Timestamps
        from qr.project import find_project_root, get_qr_dir, init_project, is_project_initialized
        from qr.snapshot.git import capture_git_snapshot
        from qr.snapshot.hardware import capture_hardware_snapshot
        from qr.snapshot.runtime import capture_runtime_snapshot
        from qr.storage.local import RunStorage, generate_run_id
        from rich.console import Console

        console = Console()

        # Determine parent ID (auto-inherit from parent in run stack if nested)
        parent_id = self.parent
        if parent_id is None and _RUN_STACK:
            parent_id = _RUN_STACK[-1].run_id

        work_dir = Path(self.cwd).resolve() if self.cwd else Path.cwd()
        project_root = find_project_root(work_dir)
        if project_root is None or not is_project_initialized(project_root):
            project_root = work_dir
            init_project(project_root)

        qr_dir = get_qr_dir(project_root)
        run_id = generate_run_id()
        storage = RunStorage(qr_dir, run_id)
        run_dir = storage.init_run_dir()

        # Push stream tee
        _STREAM_STACK.push(storage.stdout_path, storage.stderr_path)

        # Snapshots
        git_snap = capture_git_snapshot(project_root, run_dir)
        runtime_snap = capture_runtime_snapshot(run_dir, repo_root=project_root)
        hardware_snap = capture_hardware_snapshot()

        if self.command:
            cmd_list = list(self.command)
        else:
            cmd_list = ["python", *[str(a) for a in sys.argv]]

        detected_configs, detected_params = _extract_cli_parameters(cmd_list)
        detected_params.update(self.params)

        tags_list = [self.tag] if isinstance(self.tag, str) else list(self.tag or [])
        start_iso = datetime.now(timezone.utc).isoformat()
        start_perf = time.perf_counter()

        manifest = RunManifest(
            run_id=run_id,
            parent_run_id=parent_id,
            tags=tags_list,
            command=cmd_list,
            cwd=str(work_dir),
            timestamps=Timestamps(started_at=start_iso),
            git=git_snap,
            runtime=runtime_snap,
            hardware=hardware_snap,
            inputs=RunInputs(
                configs=detected_configs,
                parameters=detected_params,
            ),
            status="running",
        )
        storage.save_manifest(manifest)

        state = _RunState(
            run_id=run_id,
            run_dir=run_dir,
            storage=storage,
            manifest=manifest,
            start_perf=start_perf,
            start_iso=start_iso,
        )
        self.state = state
        _RUN_STACK.append(state)

        os.environ[ENV_RUN_ID] = run_id
        os.environ[ENV_RUN_DIR] = str(run_dir)

        tag_str = f" [magenta][{', '.join(tags_list)}][/magenta]" if tags_list else ""
        parent_str = f" (child of {parent_id})" if parent_id else ""
        console.print(f"[bold cyan]Run {run_id}[/bold cyan]{tag_str}{parent_str} started [dim]({_format_timestamp(start_iso)})[/dim]")

        return RunContext(run_id=run_id, run_dir=run_dir)

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.state and not self.state.is_finalized:
            status = "failed" if exc_type is not None else "completed"
            exit_code = 1 if exc_type is not None else 0
            _finalize_state(self.state, status=status, exit_code=exit_code)

        _STREAM_STACK.pop()

        if _RUN_STACK and _RUN_STACK[-1] is self.state:
            _RUN_STACK.pop()

        # Restore environment from parent run on stack if present
        if _RUN_STACK:
            os.environ[ENV_RUN_ID] = _RUN_STACK[-1].run_id
            os.environ[ENV_RUN_DIR] = str(_RUN_STACK[-1].run_dir)
        else:
            os.environ.pop(ENV_RUN_ID, None)
            os.environ.pop(ENV_RUN_DIR, None)

        return False


def run(
    *,
    tag: Optional[Union[str, List[str]]] = None,
    parent: Optional[str] = None,
    cwd: Optional[Union[str, Path]] = None,
    command: Optional[List[str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> _RunContextManager:
    """
    Context manager to execute and track an experiment run.
    Ideal for GridSearch, K-Fold, and multi-option experiments.

    Example:
        for depth in [3, 5, 10]:
            with qr.run(tag="gridsearch", params={"depth": depth}) as r:
                model = train(depth)
                qr.log({"score": model.score()})
                qr.artifact("model.pkl")
    """
    return _RunContextManager(
        tag=tag,
        parent=parent,
        cwd=cwd,
        command=command,
        params=params,
    )


def _setup_streams(stdout_path: Path, stderr_path: Path):
    global _TEE_STDOUT, _TEE_STDERR
    try:
        _TEE_STDOUT = _TeeStream(sys.stdout, stdout_path)
        _TEE_STDERR = _TeeStream(sys.stderr, stderr_path)
        sys.stdout = _TEE_STDOUT
        sys.stderr = _TEE_STDERR
    except Exception:
        pass


def _reset_sdk_state():
    """Reset internal state for testing isolation."""
    global _BUFFERED_METRICS, _BUFFERED_ARTIFACTS, _BUFFERED_DATASETS, _BUFFERED_NOTES, _BUFFERED_PARAMS
    global _ACTIVE_RUN_ID, _ACTIVE_RUN_STORAGE, _ACTIVE_RUN_DIR, _ACTIVE_MANIFEST, _IS_FINALIZED
    global _RUN_STACK, _STREAM_STACK
    while _STREAM_STACK and len(_STREAM_STACK._stack) > 0:
        _STREAM_STACK.pop()
    _restore_streams()
    _BUFFERED_METRICS = []
    _BUFFERED_ARTIFACTS = []
    _BUFFERED_DATASETS = []
    _BUFFERED_NOTES = []
    _BUFFERED_PARAMS = {}
    _RUN_STACK = []
    _ACTIVE_RUN_ID = None
    _ACTIVE_RUN_STORAGE = None
    _ACTIVE_RUN_DIR = None
    _ACTIVE_MANIFEST = None
    _IS_FINALIZED = False
    os.environ.pop(ENV_RUN_ID, None)
    os.environ.pop(ENV_RUN_DIR, None)
