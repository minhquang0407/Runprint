"""Unit tests for Git provenance collector."""

import subprocess
from pathlib import Path
import tempfile
from qr.snapshot.git import capture_git_snapshot, is_git_repository


def test_capture_git_snapshot_in_repo(tmp_path: Path):
    # Initialize a temporary git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True)

    # Initial commit
    file1 = tmp_path / "hello.py"
    file1.write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(tmp_path), check=True)

    run_dir = tmp_path / "run_01"
    run_dir.mkdir()

    # Clean state
    snap = capture_git_snapshot(tmp_path, run_dir)
    assert snap is not None
    assert snap.dirty is False
    assert snap.commit is not None
    assert len(snap.commit) >= 7

    # Modify file to make it dirty
    file1.write_text("print('hello dirty')\n", encoding="utf-8")
    snap_dirty = capture_git_snapshot(tmp_path, run_dir)
    assert snap_dirty is not None
    assert snap_dirty.dirty is True
    assert (run_dir / "git.diff").exists()
    diff_text = (run_dir / "git.diff").read_text(encoding="utf-8")
    assert "hello dirty" in diff_text
