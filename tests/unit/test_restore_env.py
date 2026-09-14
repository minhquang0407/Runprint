import sys
from pathlib import Path
from click.testing import CliRunner
import pytest

from qr.env import (
    sanitize_freeze_for_install,
    get_venv_bin_dir,
    get_venv_python,
    is_valid_venv,
    list_cached_envs,
    clean_cached_envs,
)
from qr.rerun import run_rerun_preflight
from qr.manifest import RunManifest, RuntimeSnapshot
from qr.cli import main


def test_sanitize_freeze_for_install(tmp_path: Path):
    freeze_input = """# A comment
numpy==1.24.3
pandas @ file:///non/existent/path/pandas-2.0.whl
-e /home/user/myproject#egg=myproject
-e .
requests @ git+https://github.com/psf/requests.git@v2.31.0
scipy==1.10.1
"""
    sanitized = sanitize_freeze_for_install(freeze_input)
    lines = [line.strip() for line in sanitized.splitlines() if line.strip()]

    assert "numpy==1.24.3" in lines
    assert "scipy==1.10.1" in lines
    assert "pandas" in lines
    assert "myproject" in lines
    assert "-e ." not in lines
    assert "requests @ git+https://github.com/psf/requests.git@v2.31.0" in lines


def test_get_venv_python_and_validity(tmp_path: Path):
    dummy_venv = tmp_path / "venv"
    assert not is_valid_venv(dummy_venv)

    bin_dir = get_venv_bin_dir(dummy_venv)
    assert bin_dir.name in ("Scripts", "bin")

    py_exe = get_venv_python(dummy_venv)
    assert py_exe.name in ("python.exe", "python")

    # Mock python executable inside bin_dir
    bin_dir.mkdir(parents=True, exist_ok=True)
    py_exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert is_valid_venv(dummy_venv)


def test_list_and_clean_cached_envs(tmp_path: Path):
    qr_dir = tmp_path / ".qr"
    envs_dir = qr_dir / "envs"
    env1 = envs_dir / "env_run001"
    env2 = envs_dir / "env_run002"

    bin1 = get_venv_bin_dir(env1)
    bin1.mkdir(parents=True, exist_ok=True)
    get_venv_python(env1).write_text("mock", encoding="utf-8")

    bin2 = get_venv_bin_dir(env2)
    bin2.mkdir(parents=True, exist_ok=True)
    get_venv_python(env2).write_text("mock", encoding="utf-8")

    # List environments
    cached = list_cached_envs(qr_dir)
    assert len(cached) == 2
    run_ids = {c["run_id"] for c in cached}
    assert run_ids == {"run001", "run002"}

    # Clean specific run
    cleaned = clean_cached_envs(qr_dir, run_id="run001")
    assert cleaned == 1
    assert not env1.exists()
    assert env2.exists()

    # Clean all remaining
    cleaned_all = clean_cached_envs(qr_dir)
    assert cleaned_all == 1
    assert not env2.exists()


def test_rerun_preflight_with_restore_env(tmp_path: Path):
    from qr.manifest import HardwareSnapshot, Timestamps

    manifest = RunManifest(
        run_id="run_preflight_test",
        command=["python", "train.py"],
        cwd=str(tmp_path),
        timestamps=Timestamps(started_at="2026-09-14T10:00:00Z"),
        hardware=HardwareSnapshot(cpu="Intel", cpu_count=4, ram_gb=16.0),
        runtime=RuntimeSnapshot(
            os="Linux 6.1",
            python_version="3.9.9",
            python_executable="/usr/bin/python3",
            platform="darwin",
            packages_lock="pip-freeze.txt",
        ),
    )

    run_dir = tmp_path / "runs" / "run_preflight_test"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Missing lockfile should fail preflight
    report_fail = run_rerun_preflight(
        manifest,
        repo_root=tmp_path,
        run_dir=run_dir,
        restore_env=True,
    )
    assert not report_fail.can_proceed
    fail_checks = [c for c in report_fail.checks if not c.passed and not c.is_warning]
    assert any("not found on disk" in c.message for c in fail_checks)

    # With lockfile present, preflight succeeds even if python/env differs
    lock_file = run_dir / "pip-freeze.txt"
    lock_file.write_text("numpy==1.24.3\n", encoding="utf-8")

    report_success = run_rerun_preflight(
        manifest,
        repo_root=tmp_path,
        run_dir=run_dir,
        restore_env=True,
    )
    assert report_success.can_proceed
    pass_checks = [c for c in report_success.checks if "Environment Restoration" in c.name]
    assert len(pass_checks) == 1
    assert pass_checks[0].passed


def test_cli_env_list_and_clean(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("qr.cli.find_project_root", lambda: tmp_path)
    (tmp_path / ".qr").mkdir(parents=True, exist_ok=True)

    # Empty list
    res = runner.invoke(main, ["env", "list"])
    assert res.exit_code == 0
    assert "No cached virtual environments found" in res.output

    # Create mock cached env
    env_dir = tmp_path / ".qr" / "envs" / "env_run_xyz"
    bin_dir = get_venv_bin_dir(env_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    get_venv_python(env_dir).write_text("mock", encoding="utf-8")

    # List with 1 item
    res = runner.invoke(main, ["env", "list"])
    assert res.exit_code == 0
    assert "run_xyz" in res.output
    assert "VALID" in res.output

    # Clean without flags
    res = runner.invoke(main, ["env", "clean"])
    assert "Specify either --run-id" in res.output

    # Clean with --run-id
    res = runner.invoke(main, ["env", "clean", "--run-id", "run_xyz"])
    assert res.exit_code == 0
    assert "Removed 1 cached virtual environment" in res.output
    assert not env_dir.exists()


def test_create_isolated_environment_empty_lock(tmp_path: Path):
    from qr.env import create_isolated_environment

    venv_dir = tmp_path / "test_venv"
    lock_path = tmp_path / "lock.txt"
    lock_path.write_text("# Empty lockfile\n", encoding="utf-8")

    py_exe = create_isolated_environment(venv_dir, lock_path)
    assert py_exe.is_file()
    assert is_valid_venv(venv_dir)

    # Calling again with recreate=False should reuse existing without error
    py_exe2 = create_isolated_environment(venv_dir, lock_path, recreate=False)
    assert py_exe2 == py_exe


def test_cli_rerun_help_flags():
    runner = CliRunner()
    res = runner.invoke(main, ["rerun", "--help"])
    assert res.exit_code == 0
    assert "--restore-env" in res.output
    assert "--reproduce" in res.output
    assert "--recreate-env" in res.output

