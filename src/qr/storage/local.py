"""
Local Run Storage Manager
=========================
Manages filesystem paths, run directory layout, atomic manifest persistence,
and run ID allocation.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from qr.manifest import RunManifest


def generate_run_id() -> str:
    """Generate a human-readable run identifier: QR-YYYYMMDD-XXXX."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand_hex = secrets.token_hex(2).upper()
    return f"QR-{date_str}-{rand_hex}"


def atomic_write_text(target_path: Path, content: str) -> None:
    """Atomically write text content using a temporary file and replace."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".{target_path.name}.tmp_{secrets.token_hex(4)}")
    try:
        temp_path.write_text(content, encoding="utf-8")
        # os.replace is atomic on POSIX and Windows (Python 3.3+)
        os.replace(temp_path, target_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


class RunStorage:
    """Manages the folder and file assets for a single run inside `.qr/runs/<run_id>`."""

    def __init__(self, qr_dir: Path, run_id: str):
        self.qr_dir = qr_dir
        self.run_id = run_id
        self.run_dir = qr_dir / "runs" / run_id
        self.manifest_path = self.run_dir / "manifest.json"
        self.stdout_path = self.run_dir / "stdout.log"
        self.stderr_path = self.run_dir / "stderr.log"
        self.metrics_path = self.run_dir / "metrics.jsonl"
        self.artifacts_path = self.run_dir / "artifacts.json"
        self.git_diff_path = self.run_dir / "git.diff"

    def init_run_dir(self) -> Path:
        """Create the directory structure for this run."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir

    def save_manifest(self, manifest: RunManifest) -> None:
        """Atomically persist manifest to manifest.json."""
        atomic_write_text(self.manifest_path, manifest.to_json(indent=2))

    def load_manifest(self) -> RunManifest:
        """Load RunManifest from disk."""
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found for run {self.run_id} at {self.manifest_path}")
        return RunManifest.from_file(self.manifest_path)

    @staticmethod
    def list_all_runs(qr_dir: Path) -> List[RunManifest]:
        """Scan .qr/runs/ and load all valid manifests, sorted by start time desc."""
        runs_dir = qr_dir / "runs"
        if not runs_dir.exists():
            return []

        manifests: List[RunManifest] = []
        for child in runs_dir.iterdir():
            if child.is_dir():
                mf_file = child / "manifest.json"
                if mf_file.is_file():
                    try:
                        manifests.append(RunManifest.from_file(mf_file))
                    except Exception:
                        # Corrupted or unfinalized run
                        pass

        # Sort descending by start time
        manifests.sort(key=lambda m: m.timestamps.started_at, reverse=True)
        return manifests
