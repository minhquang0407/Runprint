"""
Git Provenance Collector
========================
Captures Git commit hash, active branch, remote URL, uncommitted dirty status,
and writes uncommitted patch into `git.diff`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from qr.manifest import GitSnapshot


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


def capture_git_snapshot(repo_root: Path, run_dir: Path) -> Optional[GitSnapshot]:
    """
    Capture git state for the given repository:
      - HEAD commit SHA
      - Branch name
      - Remote URL
      - Dirty status (modified/staged/untracked)
      - Writes full git.diff if dirty
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
    is_dirty = bool(status_output.strip())

    if is_dirty:
        for line in status_output.splitlines():
            line = line.strip()
            if len(line) > 3:
                file_path = line[3:].strip()
                modified_files.append(file_path)

    diff_file_rel: Optional[str] = None

    if is_dirty:
        # Capture staged and unstaged diff against HEAD with binary support
        code, diff_content = _run_git(["diff", "--binary", "HEAD"], cwd=repo_root)
        if code != 0:
            # If repo has no commits yet, git diff HEAD fails
            _, diff_content = _run_git(["diff", "--binary"], cwd=repo_root)

        diff_path = run_dir / "git.diff"
        diff_path.write_text(diff_content, encoding="utf-8")
        diff_file_rel = "git.diff"

    return GitSnapshot(
        commit=commit if commit else None,
        branch=branch if branch else None,
        dirty=is_dirty,
        diff_file=diff_file_rel,
        remote_url=remote if remote else None,
        modified_files=modified_files,
    )
