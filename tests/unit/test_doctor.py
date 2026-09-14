"""Unit tests for qr doctor command."""

import json
from pathlib import Path
from click.testing import CliRunner
from qr.cli import main
from qr.manifest import HardwareSnapshot, RunManifest, RuntimeSnapshot, Timestamps
from qr.storage.local import RunStorage


def test_doctor_detects_and_repairs_orphaned_run():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(main, ["init"])
        qr_dir = Path.cwd() / ".qr"

        # Manually create a run stuck in 'running' status
        orphaned_id = "QR-ORPHANED-TEST"
        storage = RunStorage(qr_dir, orphaned_id)
        storage.init_run_dir()

        manifest = RunManifest(
            run_id=orphaned_id,
            command=["python", "long_job.py"],
            cwd=str(Path.cwd()),
            timestamps=Timestamps(),
            runtime=RuntimeSnapshot(
                os="TestOS",
                python_version="3.13.0",
                python_executable="python",
            ),
            hardware=HardwareSnapshot(),
            status="running",
        )
        storage.save_manifest(manifest)

        # 1. Doctor without --fix should detect orphaned run
        res = runner.invoke(main, ["doctor"])
        assert res.exit_code == 0
        assert "ORPHANED" in res.output
        assert "Found 1 run(s) stuck in 'running'" in res.output

        # 2. Doctor with --fix should repair it
        fix_res = runner.invoke(main, ["doctor", "--fix"])
        assert fix_res.exit_code == 0
        assert "REPAIRED" in fix_res.output

        # Verify manifest is now interrupted
        reloaded = storage.load_manifest()
        assert reloaded.status == "interrupted"

        # 3. Running doctor again should report all clean
        clean_res = runner.invoke(main, ["doctor"])
        assert clean_res.exit_code == 0
        assert "All recorded runs properly finalized" in clean_res.output
