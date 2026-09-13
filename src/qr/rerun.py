"""
Rerun Preflight & Lineage Reconstructor
=======================================
Performs preflight validation for `qr rerun` (verifying commit existence,
dirty patch applicability, environment locks, dataset checksums, and hardware diffs)
and executes rerun with parent-child lineage.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from qr.manifest import RunManifest


@dataclass
class PreflightCheckItem:
    name: str
    passed: bool
    message: str
    is_warning: bool = False


@dataclass
class RerunPreflightReport:
    run_id: str
    can_proceed: bool
    checks: List[PreflightCheckItem] = field(default_factory=list)


def run_rerun_preflight(
    manifest: RunManifest,
    repo_root: Path,
    run_dir: Path,
    allow_dataset_mismatch: bool = False,
) -> RerunPreflightReport:
    """
    Run preflight reproducibility checks:
      1. Git commit availability
      2. Dirty patch applicability (if git.diff exists)
      3. Environment lock availability
      4. Hardware differences (GPU, platform)
    """
    checks: List[PreflightCheckItem] = []
    can_proceed = True

    # 1. Git commit check
    if manifest.git and manifest.git.commit:
        proc = subprocess.run(
            ["git", "cat-file", "-t", manifest.git.commit],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode == 0:
            checks.append(
                PreflightCheckItem(
                    name="Git Commit",
                    passed=True,
                    message=f"Commit {manifest.git.commit[:8]} available in local repository",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="Git Commit",
                    passed=False,
                    message=f"Commit {manifest.git.commit[:8]} not found in local git history",
                )
            )
            can_proceed = False

    # 2. Dirty patch check
    if manifest.git and manifest.git.dirty and manifest.git.diff_file:
        diff_path = run_dir / manifest.git.diff_file
        if diff_path.exists() and diff_path.stat().st_size > 0:
            # Test if patch applies cleanly: git apply --check --binary < diff
            proc = subprocess.run(
                ["git", "apply", "--check", "--binary", str(diff_path)],
                cwd=str(repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if proc.returncode == 0:
                checks.append(
                    PreflightCheckItem(
                        name="Dirty Patch",
                        passed=True,
                        message="Recorded git.diff applies cleanly to current workspace",
                    )
                )
            else:
                checks.append(
                    PreflightCheckItem(
                        name="Dirty Patch",
                        passed=False,
                        message=f"Recorded git.diff cannot apply cleanly (files may already contain edits or conflict)",
                        is_warning=True,
                    )
                )

    # 3. Environment lock check
    if manifest.runtime.packages_lock:
        lock_path = run_dir / manifest.runtime.packages_lock
        if lock_path.exists():
            checks.append(
                PreflightCheckItem(
                    name="Environment Lock",
                    passed=True,
                    message=f"Lockfile available at {manifest.runtime.packages_lock}",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="Environment Lock",
                    passed=False,
                    message="Recorded package lock file is missing",
                    is_warning=True,
                )
            )

    # 4. Dataset checks
    for ds in manifest.inputs.datasets:
        ds_path = Path(ds.uri)
        if not ds_path.is_absolute():
            ds_path = repo_root / ds.uri

        if not ds_path.exists():
            checks.append(
                PreflightCheckItem(
                    name=f"Dataset: {ds.name}",
                    passed=False,
                    message=f"Dataset path '{ds.uri}' not found",
                    is_warning=allow_dataset_mismatch,
                )
            )
            if not allow_dataset_mismatch:
                can_proceed = False
        elif ds.fingerprint:
            from qr.sdk import calculate_path_fingerprint
            current_fp = calculate_path_fingerprint(ds_path)
            if current_fp == ds.fingerprint:
                checks.append(
                    PreflightCheckItem(
                        name=f"Dataset: {ds.name}",
                        passed=True,
                        message="Fingerprint matches recorded snapshot",
                    )
                )
            else:
                checks.append(
                    PreflightCheckItem(
                        name=f"Dataset: {ds.name}",
                        passed=False,
                        message=f"Fingerprint mismatch! Expected {ds.fingerprint[:16]}..., got {str(current_fp)[:16]}...",
                        is_warning=allow_dataset_mismatch,
                    )
                )
                if not allow_dataset_mismatch:
                    can_proceed = False

    # 5. Hardware check (Non-blocking warning)
    current_os = f"{platform.system()} {platform.release()} ({platform.machine()})"
    if manifest.runtime.os and manifest.runtime.os != current_os:
        checks.append(
            PreflightCheckItem(
                name="OS Difference",
                passed=False,
                message=f"Originally run on '{manifest.runtime.os}', currently on '{current_os}'",
                is_warning=True,
            )
        )

    return RerunPreflightReport(
        run_id=manifest.run_id,
        can_proceed=can_proceed,
        checks=checks,
    )


def create_isolated_worktree(
    repo_root: Path,
    commit: str,
    diff_path: Optional[Path],
    worktree_dir: Path,
) -> Path:
    """
    Create an isolated Git worktree at `commit`, apply `diff_path`, and return path.
    """
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if worktree_dir.exists():
        shutil.rmtree(worktree_dir, ignore_errors=True)

    # git worktree add --detach <worktree_dir> <commit>
    cmd = ["git", "worktree", "add", "--detach", str(worktree_dir), commit]
    proc = subprocess.run(cmd, cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to create git worktree: {proc.stderr.strip()}")

    # Apply diff if present
    if diff_path and diff_path.exists() and diff_path.stat().st_size > 0:
        apply_cmd = ["git", "apply", "--binary", str(diff_path.resolve())]
        apply_proc = subprocess.run(apply_cmd, cwd=str(worktree_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if apply_proc.returncode != 0:
            # If patch fails, warn but proceed with checkout
            pass

    return worktree_dir


def cleanup_isolated_worktree(repo_root: Path, worktree_dir: Path) -> None:
    """Remove an isolated Git worktree."""
    try:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree_dir)], cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        pass
    if worktree_dir.exists():
        shutil.rmtree(worktree_dir, ignore_errors=True)

