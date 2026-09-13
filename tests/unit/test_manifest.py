"""Unit tests for RunManifest data models and serialization."""

import json
from qr.manifest import (
    GitSnapshot,
    HardwareSnapshot,
    RunManifest,
    RuntimeSnapshot,
    Timestamps,
)


def test_manifest_serialization_and_deserialization():
    manifest = RunManifest(
        run_id="QR-20260914-TEST",
        command=["python", "train.py", "--epochs", "5"],
        cwd="/workspace/test",
        timestamps=Timestamps(
            started_at="2026-09-14T10:00:00Z",
            finished_at="2026-09-14T10:05:00Z",
        ),
        git=GitSnapshot(
            commit="abcdef123456",
            branch="main",
            dirty=True,
            diff_file="git.diff",
            modified_files=["train.py"],
        ),
        runtime=RuntimeSnapshot(
            os="Linux 6.1",
            python_version="3.13.0",
            python_executable="/usr/bin/python3",
            packages_lock="environment/pip-freeze.txt",
        ),
        hardware=HardwareSnapshot(
            cpu="AMD Ryzen",
            cpu_count=8,
            ram_gb=32.0,
            gpu=["NVIDIA RTX 4090"],
        ),
        status="completed",
        exit_code=0,
        duration_seconds=300.5,
    )

    json_str = manifest.to_json()
    assert "QR-20260914-TEST" in json_str
    assert "train.py" in json_str

    # Validate deserialization
    restored = RunManifest.from_json(json_str)
    assert restored.run_id == "QR-20260914-TEST"
    assert restored.command == ["python", "train.py", "--epochs", "5"]
    assert restored.git is not None
    assert restored.git.dirty is True
    assert restored.git.commit == "abcdef123456"
    assert restored.hardware.ram_gb == 32.0
    assert restored.status == "completed"
    assert restored.exit_code == 0
