"""Unit tests for secure environment variable allowlist filtering."""

import json
import os
from pathlib import Path
from qr.snapshot.runtime import (
    SAFE_REPRODUCIBILITY_ENV_VARS,
    filter_environment_variables,
    is_sensitive_key,
)


def test_is_sensitive_key():
    assert is_sensitive_key("AWS_SECRET_ACCESS_KEY") is True
    assert is_sensitive_key("GITHUB_TOKEN") is True
    assert is_sensitive_key("OPENAI_API_KEY") is True
    assert is_sensitive_key("DB_PASSWORD") is True
    assert is_sensitive_key("CUDA_VISIBLE_DEVICES") is False
    assert is_sensitive_key("OMP_NUM_THREADS") is False


def test_filter_environment_variables_allowlist_only(monkeypatch):
    # Setup test env
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/db")
    monkeypatch.setenv("HF_ACCESS_TOKEN", "hf_secret_12345")
    monkeypatch.setenv("WANDB_SESSION", "session_cookie_abc")
    monkeypatch.setenv("SECRET_KEY", "super_secret")
    monkeypatch.setenv("QR_TRACKING_MODE", "strict")

    captured = filter_environment_variables()

    # Allowed reproducibility flags MUST be present
    assert captured.get("CUDA_VISIBLE_DEVICES") == "0,1"
    assert captured.get("OMP_NUM_THREADS") == "4"
    assert captured.get("QR_TRACKING_MODE") == "strict"

    # Potential secrets MUST NOT be present
    assert "DATABASE_URL" not in captured
    assert "HF_ACCESS_TOKEN" not in captured
    assert "WANDB_SESSION" not in captured
    assert "SECRET_KEY" not in captured


def test_custom_project_allowlist(tmp_path: Path, monkeypatch):
    # Setup project.json with custom allowlist
    qr_dir = tmp_path / ".qr"
    qr_dir.mkdir()
    (qr_dir / "project.json").write_text(
        json.dumps({"capture_env": ["EXPERIMENT_PHASE", "DATA_SPLIT_SEED", "ACCIDENTAL_TOKEN"]}),
        encoding="utf-8",
    )

    monkeypatch.setenv("EXPERIMENT_PHASE", "ablation_study_v2")
    monkeypatch.setenv("DATA_SPLIT_SEED", "42")
    monkeypatch.setenv("ACCIDENTAL_TOKEN", "should_be_blocked")

    captured = filter_environment_variables(repo_root=tmp_path)
    assert captured.get("EXPERIMENT_PHASE") == "ablation_study_v2"
    assert captured.get("DATA_SPLIT_SEED") == "42"
    # Even if listed in custom keys, is_sensitive_key blocks it
    assert "ACCIDENTAL_TOKEN" not in captured
