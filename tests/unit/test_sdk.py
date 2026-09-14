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
    assert runprint.activate is qr.activate
    assert runprint.init is qr.init
    assert runprint.finish is qr.finish


def test_sdk_activate_in_process(monkeypatch, tmp_path):
    """Calling qr.activate() inside Python code should automatically initialize, snapshot, and finalize the run."""
    from qr.sdk import _reset_sdk_state
    from qr.storage.index import RunIndex
    from qr.storage.local import RunStorage

    monkeypatch.delenv("QR_RUN_DIR", raising=False)
    monkeypatch.delenv("QR_RUN_ID", raising=False)
    _reset_sdk_state()

    # 1. User logs metrics and registers artifact before calling activate()
    model_file = tmp_path / "model.bin"
    model_file.write_bytes(b"dummy model weights")

    qr.input_dataset("train_set", str(tmp_path), version="1.0")
    qr.log({"val_accuracy": 0.96, "f1": 0.95})
    qr.artifact(str(model_file), kind="model")
    qr.note("Training finished before return")

    # 2. Activate run at the end of training
    run_id = qr.activate(cwd=tmp_path, tag="in_process_test")
    assert run_id is not None
    assert run_id.startswith("QR-")

    # 3. Verify files in storage
    qr_dir = tmp_path / ".qr"
    storage = RunStorage(qr_dir, run_id)
    assert storage.manifest_path.exists()

    manifest = storage.load_manifest()
    assert manifest.status == "completed"
    assert manifest.exit_code == 0
    assert "in_process_test" in manifest.tags
    assert len(manifest.inputs.datasets) == 1
    assert manifest.inputs.datasets[0].name == "train_set"

    # 4. Verify SQLite index
    db_path = qr_dir / "index.sqlite"
    index = RunIndex(db_path)
    runs = index.list_runs()
    assert len(runs) >= 1
    matching = [r for r in runs if r["run_id"] == run_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "completed"

    _reset_sdk_state()


def test_sdk_activate_when_cli_active(monkeypatch, tmp_path):
    """When already running under `qr run` CLI, qr.activate() acts as a no-op and preserves CLI run_id."""
    from qr.sdk import _reset_sdk_state

    _reset_sdk_state()
    cli_run_dir = tmp_path / "cli_run"
    cli_run_dir.mkdir(parents=True, exist_ok=True)
    cli_run_id = "QR-CLI-1234"

    monkeypatch.setenv("QR_RUN_DIR", str(cli_run_dir))
    monkeypatch.setenv("QR_RUN_ID", cli_run_id)

    qr.log({"epoch": 1, "loss": 0.2})
    result_run_id = qr.activate(cwd=tmp_path)
    assert result_run_id == cli_run_id

    # Buffered metrics should be flushed to cli_run_dir
    metrics_file = cli_run_dir / "metrics.jsonl"
    assert metrics_file.exists()

    _reset_sdk_state()


def test_sdk_params_in_code(monkeypatch, tmp_path):
    """qr.params and qr.activate(params=...) should record in-code parameters in the manifest."""
    from qr.sdk import _reset_sdk_state
    from qr.storage.local import RunStorage

    _reset_sdk_state()
    monkeypatch.delenv("QR_RUN_DIR", raising=False)
    monkeypatch.delenv("QR_RUN_ID", raising=False)

    qr.params({"learning_rate": 0.01, "batch_size": 32})
    run_id = qr.activate(cwd=tmp_path, params={"max_depth": 6})

    storage = RunStorage(tmp_path / ".qr", run_id)
    manifest = storage.load_manifest()

    assert manifest.inputs.parameters.get("learning_rate") == 0.01
    assert manifest.inputs.parameters.get("batch_size") == 32
    assert manifest.inputs.parameters.get("max_depth") == 6

    _reset_sdk_state()


def test_sdk_with_run_context_manager(monkeypatch, tmp_path):
    """with qr.run(...) should manage individual runs in loops/grid search."""
    from qr.sdk import _reset_sdk_state
    from qr.storage.index import RunIndex
    from qr.storage.local import RunStorage

    _reset_sdk_state()
    monkeypatch.delenv("QR_RUN_DIR", raising=False)
    monkeypatch.delenv("QR_RUN_ID", raising=False)

    run_ids = []
    for depth in [3, 5]:
        with qr.run(cwd=tmp_path, tag="grid", params={"depth": depth}) as r:
            run_ids.append(r.id)
            qr.log({"depth": depth, "val_acc": 0.90 + depth * 0.01})

    assert len(run_ids) == 2
    assert run_ids[0] != run_ids[1]

    # Check both runs persisted properly
    index = RunIndex(tmp_path / ".qr" / "index.sqlite")
    runs = index.list_runs()
    assert len(runs) >= 2

    # Check params in individual manifests
    for rid, d in zip(run_ids, [3, 5]):
        storage = RunStorage(tmp_path / ".qr", rid)
        manifest = storage.load_manifest()
        assert manifest.status == "completed"
        assert manifest.inputs.parameters.get("depth") == d

    _reset_sdk_state()


def test_sdk_with_run_nested_parent_child(monkeypatch, tmp_path):
    """with qr.run(...) nested calls should auto-inherit parent_run_id."""
    from qr.sdk import _reset_sdk_state
    from qr.storage.local import RunStorage

    _reset_sdk_state()
    monkeypatch.delenv("QR_RUN_DIR", raising=False)
    monkeypatch.delenv("QR_RUN_ID", raising=False)

    parent_id = None
    child_ids = []

    with qr.run(cwd=tmp_path, tag="parent_experiment") as parent:
        parent_id = parent.id
        for lr in [0.01, 0.001]:
            with qr.run(cwd=tmp_path, tag="child_trial", params={"lr": lr}) as child:
                child_ids.append(child.id)
                qr.log({"lr": lr, "loss": lr * 10})

    assert parent_id is not None
    assert len(child_ids) == 2

    # Verify parent manifest
    p_storage = RunStorage(tmp_path / ".qr", parent_id)
    p_manifest = p_storage.load_manifest()
    assert p_manifest.status == "completed"
    assert p_manifest.parent_run_id is None

    # Verify children have parent_id linked
    for cid in child_ids:
        c_storage = RunStorage(tmp_path / ".qr", cid)
        c_manifest = c_storage.load_manifest()
        assert c_manifest.status == "completed"
        assert c_manifest.parent_run_id == parent_id

    _reset_sdk_state()


