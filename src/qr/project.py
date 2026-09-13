"""
Project Discovery and Management
================================
Detects QR workspace root, initializes `.qr/` metadata, and manages project config.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

QR_DIR_NAME = ".qr"
PROJECT_FILE = "project.json"
RUNS_DIR_NAME = "runs"


def find_project_root(start_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Traverse upwards from start_dir to find the nearest directory containing `.qr/`
    or `.git/`. Returns None if not inside a recognized project.
    """
    current = (start_dir or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / QR_DIR_NAME).is_dir():
            return parent
        if (parent / ".git").is_dir():
            # If inside a git repo without .qr/, it's a candidate root
            return parent
    return None


def get_qr_dir(repo_root: Optional[Path] = None) -> Path:
    """Get the `.qr` directory path for the given or detected project root."""
    root = repo_root or find_project_root()
    if root is None:
        raise FileNotFoundError(
            "Not inside a QR project. Run 'qr init' first to initialize this directory."
        )
    return root / QR_DIR_NAME


def is_project_initialized(root_path: Path) -> bool:
    """Check if .qr/ exists and has project.json."""
    return (root_path / QR_DIR_NAME / PROJECT_FILE).is_file()


def init_project(root_path: Path, project_name: Optional[str] = None) -> Path:
    """
    Initialize a new QR project in root_path.
    Creates:
      .qr/
      .qr/project.json
      .qr/runs/
    """
    qr_dir = root_path / QR_DIR_NAME
    runs_dir = qr_dir / RUNS_DIR_NAME

    qr_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    project_file = qr_dir / PROJECT_FILE
    name = project_name or root_path.resolve().name

    if not project_file.exists():
        metadata: Dict[str, Any] = {
            "schema_version": "0.1",
            "project_id": f"proj_{uuid.uuid4().hex[:12]}",
            "project_name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root_path": str(root_path.resolve()),
        }
        project_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return qr_dir


def load_project_metadata(root_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load metadata from .qr/project.json."""
    qr_dir = get_qr_dir(root_path)
    proj_file = qr_dir / PROJECT_FILE
    if not proj_file.exists():
        raise FileNotFoundError(f"Project metadata not found at {proj_file}")
    return json.loads(proj_file.read_text(encoding="utf-8"))
