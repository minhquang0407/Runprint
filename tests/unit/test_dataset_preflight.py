"""Unit tests for dataset fingerprinting and rerun preflight verification."""

from pathlib import Path
from qr.manifest import DatasetInput, HardwareSnapshot, RunInputs, RunManifest, RuntimeSnapshot, Timestamps
from qr.rerun import run_rerun_preflight
from qr.sdk import calculate_path_fingerprint


def test_dataset_fingerprint_and_preflight(tmp_path: Path):
    # Create sample dataset file
    data_file = tmp_path / "dataset.csv"
    data_file.write_text("id,value\n1,100\n2,200\n", encoding="utf-8")

    fp = calculate_path_fingerprint(data_file)
    assert fp is not None
    assert fp.startswith("sha256:")

    run_dir = tmp_path / "run_dir"
    run_dir.mkdir()

    # Manifest with correct dataset fingerprint
    manifest = RunManifest(
        run_id="QR-TEST-DATASET",
        command=["python", "eval.py"],
        cwd=str(tmp_path),
        timestamps=Timestamps(),
        runtime=RuntimeSnapshot(
            os="TestOS",
            python_version="3.13.0",
            python_executable="python",
        ),
        hardware=HardwareSnapshot(),
        inputs=RunInputs(
            datasets=[
                DatasetInput(
                    name="my_dataset",
                    uri=str(data_file),
                    version="v1",
                    fingerprint=fp,
                )
            ]
        ),
    )

    # 1. Preflight should pass
    report = run_rerun_preflight(manifest, tmp_path, run_dir)
    assert report.can_proceed is True
    ds_check = [c for c in report.checks if c.name == "Dataset: my_dataset"][0]
    assert ds_check.passed is True

    # 2. Modify dataset content -> Preflight should fail
    data_file.write_text("id,value\n1,999\n", encoding="utf-8")
    report_modified = run_rerun_preflight(manifest, tmp_path, run_dir)
    assert report_modified.can_proceed is False
    ds_check_mod = [c for c in report_modified.checks if c.name == "Dataset: my_dataset"][0]
    assert ds_check_mod.passed is False
    assert "Fingerprint mismatch" in ds_check_mod.message

    # 3. Preflight with allow_dataset_mismatch should proceed as warning
    report_allowed = run_rerun_preflight(manifest, tmp_path, run_dir, allow_dataset_mismatch=True)
    assert report_allowed.can_proceed is True
