"""
Restorability Scoring Engine
============================
Calculates a granular 0–100 Restorability Score across 3 core pillars:
  1. Source Code Provenance (Max 35 points)
     - Valid Git commit: +10
     - Clean working tree or complete git.diff patch: +15
     - Zero ignored untracked files: +10
  2. Environment Provenance (Max 35 points)
     - Pinned Python version: +10
     - Frozen package lockfile present: +15
     - No editable/local dependencies: +10
  3. Data & Inputs Provenance (Max 30 points)
     - Pure compute (no external inputs): +30
     - OR all inputs declared (+10) AND all have valid SHA-256 fingerprints (+20)

Status Bands:
  - 90 - 100: HIGHLY_RESTORABLE
  - 70 - 89:  PARTIALLY_RESTORABLE
  - < 70:     LOW_RESTORABILITY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from qr.manifest import RunManifest


@dataclass
class RestorabilityCriterion:
    category: str
    name: str
    score: int
    max_score: int
    passed: bool
    message: str


@dataclass
class RestorabilityReport:
    score: int
    status: str
    criteria: List[RestorabilityCriterion] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    @property
    def status_color(self) -> str:
        if self.status == "HIGHLY_RESTORABLE":
            return "green"
        elif self.status == "PARTIALLY_RESTORABLE":
            return "yellow"
        else:
            return "red"


def calculate_restorability_score(
    manifest: RunManifest,
    run_dir: Optional[Path] = None,
) -> RestorabilityReport:
    """
    Evaluate reproducibility readiness and calculate a 0-100 score.
    Returns a RestorabilityReport containing breakdown criteria and recommendations.
    """
    criteria: List[RestorabilityCriterion] = []
    recommendations: List[str] = []

    # =========================================================================
    # 1. Source Code Provenance (Max 35 points)
    # =========================================================================
    # Criterion 1: Git Commit (+10)
    has_commit = bool(manifest.git and manifest.git.commit)
    if has_commit and manifest.git and manifest.git.commit:
        criteria.append(
            RestorabilityCriterion(
                category="Source Code",
                name="Git Commit",
                score=10,
                max_score=10,
                passed=True,
                message=f"Commit: {manifest.git.commit[:8]}",
            )
        )
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Source Code",
                name="Git Commit",
                score=0,
                max_score=10,
                passed=False,
                message="No git commit recorded",
            )
        )
        recommendations.append("Initialize git and commit your code before running experiments.")

    # Criterion 2: Clean or Patched Working Tree (+15)
    if manifest.git:
        if not manifest.git.dirty:
            criteria.append(
                RestorabilityCriterion(
                    category="Source Code",
                    name="Working Tree State",
                    score=15,
                    max_score=15,
                    passed=True,
                    message="Clean working tree",
                )
            )
        elif manifest.git.diff_file:
            criteria.append(
                RestorabilityCriterion(
                    category="Source Code",
                    name="Working Tree State",
                    score=15,
                    max_score=15,
                    passed=True,
                    message="Working tree patch captured in git.diff",
                )
            )
        else:
            criteria.append(
                RestorabilityCriterion(
                    category="Source Code",
                    name="Working Tree State",
                    score=0,
                    max_score=15,
                    passed=False,
                    message="Uncommitted changes without diff patch",
                )
            )
            recommendations.append("Working tree was dirty but no git.diff patch was captured.")
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Source Code",
                name="Working Tree State",
                score=0,
                max_score=15,
                passed=False,
                message="Not a git repository",
            )
        )

    # Criterion 3: Untracked Files Completeness (+10)
    if manifest.git:
        if manifest.git.untracked_ignored:
            criteria.append(
                RestorabilityCriterion(
                    category="Source Code",
                    name="Untracked Files Completeness",
                    score=0,
                    max_score=10,
                    passed=False,
                    message=f"{len(manifest.git.untracked_ignored)} untracked file(s) excluded (>5MB or .qrignore)",
                )
            )
            recommendations.append(
                "Some untracked files were ignored due to size (>5MB) or .qrignore. Track data files via qr.dataset() instead."
            )
        else:
            criteria.append(
                RestorabilityCriterion(
                    category="Source Code",
                    name="Untracked Files Completeness",
                    score=10,
                    max_score=10,
                    passed=True,
                    message="All untracked source files captured in patch",
                )
            )
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Source Code",
                name="Untracked Files Completeness",
                score=0,
                max_score=10,
                passed=False,
                message="Not a git repository",
            )
        )

    # =========================================================================
    # 2. Runtime Environment Provenance (Max 35 points)
    # =========================================================================
    # Criterion 4: Python Version (+10)
    has_py_ver = bool(manifest.runtime and manifest.runtime.python_version)
    if has_py_ver:
        criteria.append(
            RestorabilityCriterion(
                category="Environment",
                name="Python Version",
                score=10,
                max_score=10,
                passed=True,
                message=f"Python {manifest.runtime.python_version}",
            )
        )
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Environment",
                name="Python Version",
                score=0,
                max_score=10,
                passed=False,
                message="Python version missing",
            )
        )
        recommendations.append("Ensure Python version is captured in runtime snapshot.")

    # Criterion 5: Package Lockfile (+15)
    has_lock = bool(manifest.runtime and manifest.runtime.packages_lock)
    if has_lock:
        criteria.append(
            RestorabilityCriterion(
                category="Environment",
                name="Package Lockfile",
                score=15,
                max_score=15,
                passed=True,
                message="Packages frozen in pip-freeze.txt",
            )
        )
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Environment",
                name="Package Lockfile",
                score=0,
                max_score=15,
                passed=False,
                message="No package lockfile recorded",
            )
        )
        recommendations.append("Record installed package dependencies using pip freeze.")

    # Criterion 6: No Editable Dependencies (+10)
    if has_lock:
        has_editable = False
        if run_dir and manifest.runtime.packages_lock:
            lock_path = run_dir / manifest.runtime.packages_lock
            if lock_path.is_file():
                try:
                    content = lock_path.read_text(encoding="utf-8", errors="replace")
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("-e ") or "@ file://" in line or "file:///" in line or line.startswith("file:"):
                            has_editable = True
                            break
                except Exception:
                    pass

        if has_editable:
            criteria.append(
                RestorabilityCriterion(
                    category="Environment",
                    name="Standard Dependencies",
                    score=0,
                    max_score=10,
                    passed=False,
                    message="Contains editable or local file:// dependencies",
                )
            )
            recommendations.append("Avoid editable or local packages (-e or file://) for reproducible runs.")
        else:
            criteria.append(
                RestorabilityCriterion(
                    category="Environment",
                    name="Standard Dependencies",
                    score=10,
                    max_score=10,
                    passed=True,
                    message="All dependencies from standard package sources",
                )
            )
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Environment",
                name="Standard Dependencies",
                score=0,
                max_score=10,
                passed=False,
                message="Cannot verify dependencies without lockfile",
            )
        )

    # =========================================================================
    # 3. Data & Inputs Provenance (Max 30 points)
    # =========================================================================
    datasets = manifest.inputs.datasets if manifest.inputs else []
    if not datasets:
        # Pure compute
        criteria.append(
            RestorabilityCriterion(
                category="Data & Inputs",
                name="Dataset Declaration",
                score=10,
                max_score=10,
                passed=True,
                message="Pure compute (no dataset inputs required)",
            )
        )
        criteria.append(
            RestorabilityCriterion(
                category="Data & Inputs",
                name="Dataset Integrity",
                score=20,
                max_score=20,
                passed=True,
                message="No dataset hashes required",
            )
        )
    else:
        criteria.append(
            RestorabilityCriterion(
                category="Data & Inputs",
                name="Dataset Declaration",
                score=10,
                max_score=10,
                passed=True,
                message=f"{len(datasets)} dataset(s) declared",
            )
        )

        missing_hashes = [d.name for d in datasets if not (getattr(d, "fingerprint", None) or getattr(d, "sha256", None))]
        if not missing_hashes:
            criteria.append(
                RestorabilityCriterion(
                    category="Data & Inputs",
                    name="Dataset Integrity",
                    score=20,
                    max_score=20,
                    passed=True,
                    message="All datasets verified with SHA-256 fingerprints",
                )
            )
        else:
            criteria.append(
                RestorabilityCriterion(
                    category="Data & Inputs",
                    name="Dataset Integrity",
                    score=0,
                    max_score=20,
                    passed=False,
                    message=f"{len(missing_hashes)} dataset(s) missing SHA-256 fingerprint",
                )
            )
            recommendations.append("Declare SHA-256 checksums for all input datasets to guarantee data provenance.")

    # Total score calculation
    total_score = sum(c.score for c in criteria)
    total_score = max(0, min(100, total_score))

    if total_score >= 90:
        status = "HIGHLY_RESTORABLE"
    elif total_score >= 70:
        status = "PARTIALLY_RESTORABLE"
    else:
        status = "LOW_RESTORABILITY"

    return RestorabilityReport(
        score=total_score,
        status=status,
        criteria=criteria,
        recommendations=recommendations,
    )
