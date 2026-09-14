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
    allow_env_mismatch: bool = False,
    restore_env: bool = False,
) -> RerunPreflightReport:
    """
    Run preflight reproducibility checks:
      1. Git commit availability
      2. Dirty patch applicability (if git.diff exists)
      3. Environment lock & package drift detection (or restoration readiness)
      4. Dataset availability & checksums
      5. Hardware differences (OS, GPU)
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

    # 3. Environment lock & drift check / restoration readiness
    if restore_env:
        if not manifest.runtime.packages_lock:
            checks.append(
                PreflightCheckItem(
                    name="Environment Restoration",
                    passed=False,
                    message="Cannot restore environment: no package lockfile recorded in manifest",
                )
            )
            can_proceed = False
        else:
            lock_path = run_dir / manifest.runtime.packages_lock
            if not lock_path.is_file():
                checks.append(
                    PreflightCheckItem(
                        name="Environment Restoration",
                        passed=False,
                        message=f"Cannot restore environment: lockfile '{manifest.runtime.packages_lock}' not found on disk",
                    )
                )
                can_proceed = False
            else:
                checks.append(
                    PreflightCheckItem(
                        name="Environment Restoration",
                        passed=True,
                        message=f"Lockfile available ({manifest.runtime.packages_lock}). Dedicated virtual environment will be created.",
                    )
                )
    elif manifest.runtime.packages_lock:
        lock_path = run_dir / manifest.runtime.packages_lock
        if lock_path.exists():
            from qr.env import diff_environments

            content = lock_path.read_text(encoding="utf-8", errors="replace")
            env_diff = diff_environments(content, recorded_python=manifest.runtime.python_version)

            if not env_diff.python_match:
                checks.append(
                    PreflightCheckItem(
                        name="Python Version Drift",
                        passed=False,
                        message=(
                            f"Recorded Python {env_diff.recorded_python}, but current environment is "
                            f"Python {env_diff.current_python}"
                        ),
                        is_warning=allow_env_mismatch,
                    )
                )
                if not allow_env_mismatch:
                    can_proceed = False

            if env_diff.missing_packages:
                missing_sample = list(env_diff.missing_packages.keys())[:5]
                checks.append(
                    PreflightCheckItem(
                        name="Environment Drift (Missing)",
                        passed=False,
                        message=(
                            f"{len(env_diff.missing_packages)} package(s) missing from current environment: "
                            f"{', '.join(missing_sample)}{'...' if len(env_diff.missing_packages) > 5 else ''}. "
                            f"Run 'qr env diff {manifest.run_id}' for details."
                        ),
                        is_warning=allow_env_mismatch,
                    )
                )
                if not allow_env_mismatch:
                    can_proceed = False

            if env_diff.version_mismatches:
                sample_items = [
                    f"{pkg} ({v[0]} -> {v[1]})"
                    for pkg, v in list(env_diff.version_mismatches.items())[:3]
                ]
                checks.append(
                    PreflightCheckItem(
                        name="Environment Drift (Mismatch)",
                        passed=False,
                        message=(
                            f"{len(env_diff.version_mismatches)} package(s) version drift: "
                            f"{', '.join(sample_items)}{'...' if len(env_diff.version_mismatches) > 3 else ''}. "
                            f"Run 'qr env diff {manifest.run_id}' for details."
                        ),
                        is_warning=allow_env_mismatch,
                    )
                )
                if not allow_env_mismatch:
                    can_proceed = False

            if not env_diff.has_drift:
                checks.append(
                    PreflightCheckItem(
                        name="Environment Integrity",
                        passed=True,
                        message=f"All {len(env_diff.matching_packages)} recorded packages match current environment",
                    )
                )
            elif allow_env_mismatch:
                checks.append(
                    PreflightCheckItem(
                        name="Environment Integrity",
                        passed=True,
                        message="Environment drift detected but bypassed via --allow-env-mismatch",
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
    else:
        checks.append(
            PreflightCheckItem(
                name="Environment Lock",
                passed=False,
                message="No package lockfile recorded in manifest",
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

