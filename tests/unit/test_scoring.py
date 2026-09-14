"""Unit tests for Restorability Scoring Engine."""

from pathlib import Path
from qr.manifest import (
    DatasetInput,
    GitSnapshot,
    HardwareSnapshot,
    RunInputs,
    RunManifest,
    RuntimeSnapshot,
    Timestamps,
)
from qr.scoring import calculate_restorability_score


def _create_mock_manifest(
    commit: str = "7a0a8d6a97e720c693755368a93735fb5a47644f",
    dirty: bool = False,
    diff_file: str = None,
    untracked_ignored=None,
    python_version: str = "3.11.5",
    packages_lock: str = "environment/pip-freeze.txt",
    datasets=None,
) -> RunManifest:
    return RunManifest(
        run_id="QR-TEST-001",
        command=["python", "train.py"],
        cwd="/workspace",
        timestamps=Timestamps(started_at="2026-09-14T00:00:00Z"),
        git=GitSnapshot(
            commit=commit,
            dirty=dirty,
            diff_file=diff_file,
            untracked_ignored=untracked_ignored or [],
        ),
        runtime=RuntimeSnapshot(
            os="Linux 6.1.0",
            python_version=python_version,
            python_executable="/usr/bin/python3",
            packages_lock=packages_lock,
            env_vars={"CUDA_VISIBLE_DEVICES": "0"},
        ),
        hardware=HardwareSnapshot(
            cpu="AMD EPYC",
            cpu_count=8,
            ram_gb=16.0,
            gpu=["NVIDIA A100"],
        ),
        inputs=RunInputs(
            datasets=datasets or [],
        ),
    )


def test_perfect_pure_compute_score(tmp_path: Path):
    manifest = _create_mock_manifest()
    # Create empty lockfile (no editable dependencies)
    lock_file = tmp_path / "environment" / "pip-freeze.txt"
    lock_file.parent.mkdir(parents=True)
    lock_file.write_text("torch==2.1.0\nnumpy==1.24.3\n", encoding="utf-8")

    report = calculate_restorability_score(manifest, tmp_path)
    assert report.score == 100
    assert report.status == "HIGHLY_RESTORABLE"
    assert len(report.recommendations) == 0


def test_score_penalizes_missing_git_and_dirty_tree(tmp_path: Path):
    manifest = _create_mock_manifest(commit=None, dirty=True, diff_file=None)
    manifest.git = None

    report = calculate_restorability_score(manifest, tmp_path)
    # Lost 35 pts from Source Code
    assert report.score <= 65
    assert report.status == "LOW_RESTORABILITY"
    assert any("git" in r.lower() for r in report.recommendations)


def test_score_penalizes_ignored_untracked_files(tmp_path: Path):
    manifest = _create_mock_manifest(
        dirty=True,
        diff_file="git.diff",
        untracked_ignored=["large_data.bin", "dataset.parquet"],
    )
    report = calculate_restorability_score(manifest, tmp_path)
    # Lost 10 pts for untracked files
    assert report.score == 90
    crit = next(c for c in report.criteria if c.name == "Untracked Files Completeness")
    assert crit.passed is False
    assert crit.score == 0


def test_score_penalizes_editable_dependency(tmp_path: Path):
    manifest = _create_mock_manifest()
    lock_file = tmp_path / "environment" / "pip-freeze.txt"
    lock_file.parent.mkdir(parents=True)
    lock_file.write_text("numpy==1.24.3\n-e git+https://github.com/org/repo#egg=mypkg\n", encoding="utf-8")

    report = calculate_restorability_score(manifest, tmp_path)
    # Lost 10 pts for editable dependency
    assert report.score == 90
    crit = next(c for c in report.criteria if c.name == "Standard Dependencies")
    assert crit.passed is False
    assert crit.score == 0
    assert any("editable" in r.lower() for r in report.recommendations)


def test_score_handles_datasets_with_and_without_fingerprint(tmp_path: Path):
    # With fingerprints
    ds1 = DatasetInput(name="imagenet", uri="data/train", fingerprint="sha256:abc1234567890123")
    manifest = _create_mock_manifest(datasets=[ds1])
    report = calculate_restorability_score(manifest, tmp_path)
    assert report.score == 100

    # Without fingerprint
    ds2 = DatasetInput(name="cifar10", uri="data/cifar")
    manifest_unhashed = _create_mock_manifest(datasets=[ds2])
    report_unhashed = calculate_restorability_score(manifest_unhashed, tmp_path)
    # Lost 20 pts from Dataset Integrity
    assert report_unhashed.score == 80
    assert report_unhashed.status == "PARTIALLY_RESTORABLE"
    crit = next(c for c in report_unhashed.criteria if c.name == "Dataset Integrity")
    assert crit.passed is False
    assert crit.score == 0
