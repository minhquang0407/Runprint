"""
Tiny Python SDK
===============
Provides optional semantic logging, artifact registration, and dataset declarations
for experiment code. Gracefully degrades to a no-op if run outside of `qr run`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

ENV_RUN_ID = "QR_RUN_ID"
ENV_RUN_DIR = "QR_RUN_DIR"


def _get_run_dir() -> Optional[Path]:
    """Get active run directory from environment."""
    run_dir_str = os.environ.get(ENV_RUN_DIR)
    if run_dir_str:
        p = Path(run_dir_str)
        if p.exists():
            return p
    return None


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


def log(metrics: Dict[str, Any]) -> None:
    """
    Append structured metrics to `metrics.jsonl`.
    Adds an automatic timestamp if not already provided.
    """
    run_dir = _get_run_dir()
    if not run_dir:
        return

    payload = {"timestamp": time.time(), **metrics}
    metrics_path = run_dir / "metrics.jsonl"
    try:
        with open(metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def artifact(path: str, kind: Optional[str] = "generic", metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Register an output artifact reference (model checkpoint, eval report, plot, etc.).
    Does NOT copy large files by default; records path, size, and checksum.
    """
    run_dir = _get_run_dir()
    if not run_dir:
        return

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


def input_dataset(name: str, uri: str, version: Optional[str] = None, fingerprint: Optional[str] = None) -> None:
    """
    Declare an input dataset reference, version, and fingerprint.
    If fingerprint is None, attempts to automatically calculate it for local paths.
    """
    run_dir = _get_run_dir()
    if not run_dir:
        return

    # Auto-calculate fingerprint if local path exists and none provided
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


def note(text: str) -> None:
    """Append a human or script annotation to notes.jsonl."""
    run_dir = _get_run_dir()
    if not run_dir:
        return

    payload = {"timestamp": time.time(), "text": text}
    notes_path = run_dir / "notes.jsonl"
    try:
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


@contextlib.contextmanager
def timer(name: str = "training_duration_seconds"):
    """
    Context manager to measure and automatically log execution time of a training or compute block.
    Saves the elapsed duration in seconds to metrics.jsonl.
    Gracefully degrades to a normal context manager if run outside `qr run`.

    Example:
        with qr.timer("train_duration_seconds"):
            model.fit(X_train, y_train)
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - t0, 4)
        log({name: elapsed})

