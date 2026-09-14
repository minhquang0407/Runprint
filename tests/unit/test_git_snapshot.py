"""Unit tests for Git provenance collector."""

import subprocess
from pathlib import Path
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


def test_capture_git_snapshot_includes_untracked_source_files(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True)

    # Initial commit
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(tmp_path), check=True)

    # Add .qrignore
    (tmp_path / ".qrignore").write_text("*.log\ncustom_ignored_*\n", encoding="utf-8")
    subprocess.run(["git", "add", ".qrignore"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Add qrignore"], cwd=str(tmp_path), check=True)

    # Create untracked source file
    (tmp_path / "new_helper.py").write_text("def helper(): pass\n", encoding="utf-8")

    # Create untracked ignored extension file (binary/weights)
    (tmp_path / "model_weights.bin").write_text("fake binary", encoding="utf-8")

    # Create untracked file matching .qrignore
    (tmp_path / "custom_ignored_file.txt").write_text("secret or temp", encoding="utf-8")

    run_dir = tmp_path / "run_02"
    run_dir.mkdir()

    snap = capture_git_snapshot(tmp_path, run_dir)
    assert snap is not None
    assert snap.dirty is True

    # Check git.diff includes the untracked Python file!
    diff_path = run_dir / "git.diff"
    assert diff_path.exists()
    diff_content = diff_path.read_text(encoding="utf-8")
    assert "new_helper.py" in diff_content
    assert "def helper(): pass" in diff_content

    # Check binary and qrignored files are NOT in diff, but logged in untracked_ignored
    assert "model_weights.bin" not in diff_content
    assert "custom_ignored_file.txt" not in diff_content

    assert any("model_weights.bin" in f for f in snap.untracked_ignored)
    assert any("custom_ignored_file.txt" in f for f in snap.untracked_ignored)

    # Check git index is properly restored (status still shows ?? for untracked files, not staged)
    st_proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(tmp_path), capture_output=True, text=True)
    assert "?? new_helper.py" in st_proc.stdout
    assert "A  new_helper.py" not in st_proc.stdout
