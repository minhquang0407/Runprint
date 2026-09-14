"""
Git Provenance Collector
========================
Captures Git commit hash, active branch, remote URL, uncommitted dirty status,
and writes full uncommitted patch into `git.diff` (including untracked source files).
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
import subprocess
from typing import List, Optional, Set, Tuple
from qr.manifest import GitSnapshot

# Default file extensions ignored for untracked patch generation
DEFAULT_IGNORED_EXTENSIONS: Set[str] = {
    ".csv",
    ".tsv",
    ".parquet",
    ".h5",
    ".hdf5",
    ".feather",
    ".arrow",
    ".pt",
    ".pth",
    ".ckpt",
    ".bin",
    ".onnx",
    ".pkl",
    ".pickle",
    ".weights",
    ".safetensors",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".zip",
    ".7z",
    ".mp4",
    ".avi",
    ".png",
    ".jpg",
    ".jpeg",
}

# 5 MB threshold for including untracked source files in git patch
MAX_UNTRACKED_FILE_SIZE_BYTES = 5 * 1024 * 1024


def _run_git(args: List[str], cwd: Path) -> Tuple[int, str]:
    """Run a git command and return (returncode, stdout_string)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip()
    except (FileNotFoundError, PermissionError):
        return -1, ""


def is_git_repository(path: Path) -> bool:
    """Check if the given directory is inside a Git working tree."""
    code, out = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return code == 0 and out == "true"


def load_qrignore_patterns(repo_root: Path) -> List[str]:
    """Load ignore patterns from .qrignore if present."""
    ignore_file = repo_root / ".qrignore"
    patterns: List[str] = []
    if ignore_file.exists():
        try:
            for line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except Exception:
            pass
    return patterns


def should_ignore_untracked(file_path: Path, repo_root: Path, custom_patterns: List[str]) -> bool:
    """Determine whether an untracked file should be excluded from git.diff patch."""
    # Check extension
    suffix = file_path.suffix.lower()
    if suffix in DEFAULT_IGNORED_EXTENSIONS:
        return True

    # Check custom patterns
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    for pat in custom_patterns:
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(file_path.name, pat):
            return True

    # Check file size (> 5MB)
    try:
        if file_path.stat().st_size > MAX_UNTRACKED_FILE_SIZE_BYTES:
            return True
    except Exception:
        return True

    return False


def capture_git_snapshot(repo_root: Path, run_dir: Path) -> Optional[GitSnapshot]:
    """
    Capture git state for the given repository:
      - HEAD commit SHA
      - Branch name
      - Remote URL
      - Dirty status (modified/staged/untracked)
      - Writes full git.diff if dirty (including untracked source files via intent-to-add)
    """
    if not is_git_repository(repo_root):
        return None

    # Get HEAD commit
    _, commit = _run_git(["rev-parse", "HEAD"], cwd=repo_root)

    # Get Branch name
    _, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)

    # Get remote URL
    _, remote = _run_git(["config", "--get", "remote.origin.url"], cwd=repo_root)

    # Check status
    _, status_output = _run_git(["status", "--porcelain"], cwd=repo_root)

    modified_files: List[str] = []
    untracked_files: List[str] = []
    is_dirty = bool(status_output.strip())

    if is_dirty:
        for line in status_output.splitlines():
            line = line.strip()
            if len(line) > 3:
                status_prefix = line[:2]
                file_path_str = line[3:].strip()
                modified_files.append(file_path_str)
                if status_prefix == "??":
                    untracked_files.append(file_path_str)

    # Filter untracked files into eligible vs ignored
    custom_patterns = load_qrignore_patterns(repo_root)
    eligible_untracked: List[str] = []
    untracked_ignored: List[str] = []

    for uf in untracked_files:
        full_p = repo_root / uf
        if full_p.is_file():
            if should_ignore_untracked(full_p, repo_root, custom_patterns):
                untracked_ignored.append(uf)
            else:
                eligible_untracked.append(uf)
        elif full_p.is_dir():
            # Check files in untracked directory
            for sub in full_p.rglob("*"):
                if sub.is_file():
                    sub_rel = str(sub.relative_to(repo_root)).replace("\\", "/")
                    if should_ignore_untracked(sub, repo_root, custom_patterns):
                        untracked_ignored.append(sub_rel)
                    else:
                        eligible_untracked.append(sub_rel)

    diff_file_rel: Optional[str] = None

    if is_dirty:
        # Use git add -N (intent-to-add) so git diff includes untracked source files
        try:
            if eligible_untracked:
                _run_git(["add", "-N", "--", *eligible_untracked], cwd=repo_root)

            code, diff_content = _run_git(["diff", "--binary", "HEAD"], cwd=repo_root)
            if code != 0:
                # If repo has no commits yet, git diff HEAD fails
                _, diff_content = _run_git(["diff", "--binary"], cwd=repo_root)

            diff_path = run_dir / "git.diff"
            diff_path.write_text(diff_content, encoding="utf-8")
            diff_file_rel = "git.diff"
        finally:
            if eligible_untracked:
                # Restore index back to untracked status without modifying working tree
                _run_git(["reset", "--", *eligible_untracked], cwd=repo_root)

    return GitSnapshot(
        commit=commit if commit else None,
        branch=branch if branch else None,
        dirty=is_dirty,
        diff_file=diff_file_rel,
        remote_url=remote if remote else None,
        modified_files=modified_files,
        untracked_ignored=untracked_ignored,
    )
