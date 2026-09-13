"""Unit tests for Tiny Python SDK (qr.log, qr.artifact, qr.input_dataset, qr.note)."""

import json
from pathlib import Path
import qr
import runprint


def test_sdk_graceful_no_op_when_outside_qr_run(monkeypatch, tmp_path):
    """When run without QR_RUN_DIR, SDK functions must safely do nothing without raising exceptions."""
    monkeypatch.delenv("QR_RUN_DIR", raising=False)
    monkeypatch.delenv("QR_RUN_ID", raising=False)

    # None of these should throw any error
    qr.log({"train_loss": 0.35, "epoch": 1})
    qr.artifact(str(tmp_path / "model.pt"), kind="checkpoint")
    qr.input_dataset("train_data", str(tmp_path))
    qr.note("Test note outside run")

    runprint.log({"val_loss": 0.40})
    runprint.artifact(str(tmp_path / "plot.png"))
    runprint.input_dataset("val_data", str(tmp_path))
    runprint.note("Test note via runprint alias")


def test_sdk_log_metrics(monkeypatch, tmp_path):
    """qr.log should write JSON lines to metrics.jsonl inside active run directory."""
    monkeypatch.setenv("QR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("QR_RUN_ID", "test-run-123")

    qr.log({"epoch": 1, "loss": 0.55, "acc": 0.81})
    qr.log({"epoch": 2, "loss": 0.32, "acc": 0.92})

    metrics_file = tmp_path / "metrics.jsonl"
    assert metrics_file.exists()

    lines = [json.loads(line) for line in metrics_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["epoch"] == 1
    assert lines[0]["loss"] == 0.55
    assert lines[0]["acc"] == 0.81
    assert "timestamp" in lines[0]

    assert lines[1]["epoch"] == 2
    assert lines[1]["loss"] == 0.32
    assert lines[1]["acc"] == 0.92


def test_sdk_artifact_registration(monkeypatch, tmp_path):
    """qr.artifact should register metadata and sha256 checksum to artifacts.json."""
    monkeypatch.setenv("QR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("QR_RUN_ID", "test-run-123")

    # Create dummy artifact file
    dummy_model = tmp_path / "model.pkl"
    dummy_model.write_bytes(b"binary model weights data")

    qr.artifact(str(dummy_model), kind="model", metadata={"framework": "sklearn", "estimator": "RandomForest"})

    artifacts_file = tmp_path / "artifacts.json"
    assert artifacts_file.exists()

    data = json.loads(artifacts_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    record = data[0]
    assert record["path"] == str(dummy_model)
    assert record["kind"] == "model"
    assert record["size_bytes"] == len(b"binary model weights data")
    assert record["checksum"] is not None
    assert record["metadata"]["framework"] == "sklearn"


def test_sdk_input_dataset_fingerprinting(monkeypatch, tmp_path):
    """qr.input_dataset should record dataset metadata and compute SHA256 fingerprint."""
    monkeypatch.setenv("QR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("QR_RUN_ID", "test-run-123")

    # Create dummy dataset file
    csv_path = tmp_path / "dataset.csv"
    csv_path.write_text("feature1,feature2,target\n1,2,0\n3,4,1\n", encoding="utf-8")

    qr.input_dataset(name="raw_csv", uri=str(csv_path), version="1.0.0")

    datasets_file = tmp_path / "inputs_datasets.json"
    assert datasets_file.exists()

    data = json.loads(datasets_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["name"] == "raw_csv"
    assert data[0]["version"] == "1.0.0"
    assert data[0]["fingerprint"].startswith("sha256:")


def test_sdk_note(monkeypatch, tmp_path):
    """qr.note should append annotations to notes.jsonl."""
    monkeypatch.setenv("QR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("QR_RUN_ID", "test-run-123")

    qr.note("Hyperparameters tuned based on cross-validation")

    notes_file = tmp_path / "notes.jsonl"
    assert notes_file.exists()

    lines = [json.loads(line) for line in notes_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 1
    assert lines[0]["text"] == "Hyperparameters tuned based on cross-validation"
    assert "timestamp" in lines[0]


def test_sdk_timer(monkeypatch, tmp_path):
    """qr.timer should measure block execution duration and log it to metrics.jsonl."""
    import time
    monkeypatch.setenv("QR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("QR_RUN_ID", "test-run-123")

    with qr.timer("custom_training_seconds"):
        time.sleep(0.05)

    metrics_file = tmp_path / "metrics.jsonl"
    assert metrics_file.exists()

    lines = [json.loads(line) for line in metrics_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 1
    assert "custom_training_seconds" in lines[0]
    assert lines[0]["custom_training_seconds"] >= 0.04


def test_runprint_package_alias():
    """`runprint` must re-export the exact same functions and version as `qr`."""
    assert runprint.__version__ == qr.__version__
    assert runprint.log is qr.log
    assert runprint.artifact is qr.artifact
    assert runprint.input_dataset is qr.input_dataset
    assert runprint.note is qr.note
    assert runprint.timer is qr.timer
