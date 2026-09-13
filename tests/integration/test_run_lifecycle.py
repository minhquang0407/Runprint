"""Integration tests for end-to-end run lifecycle."""

import json
import sys
from pathlib import Path
from click.testing import CliRunner
from qr.cli import main
from qr.storage.local import RunStorage


def test_full_run_lifecycle():
    runner = CliRunner()
    with runner.isolated_filesystem():
        # 1. Init
        init_res = runner.invoke(main, ["init"])
        assert init_res.exit_code == 0

        # 2. Run a simple command
        cmd = [sys.executable, "-c", "import qr; qr.log({'loss': 0.42}); print('experiment executed successfully')"]
        run_res = runner.invoke(main, ["run", "--", *cmd])
        assert run_res.exit_code == 0
        assert "experiment executed successfully" in run_res.output
        assert "Run completed: exit=0" in run_res.output

        # 3. Check storage
        qr_dir = Path.cwd() / ".qr"
        runs = RunStorage.list_all_runs(qr_dir)
        assert len(runs) == 1
        manifest = runs[0]
        assert manifest.status == "completed"
        assert manifest.exit_code == 0

        # Check logs and metrics
        run_storage = RunStorage(qr_dir, manifest.run_id)
        assert run_storage.stdout_path.exists()
        assert "experiment executed successfully" in run_storage.stdout_path.read_text(encoding="utf-8")

        assert run_storage.metrics_path.exists()
        metric_line = run_storage.metrics_path.read_text(encoding="utf-8").strip()
        assert "0.42" in metric_line

        # 4. List command
        list_res = runner.invoke(main, ["list"])
        assert list_res.exit_code == 0
        assert manifest.run_id in list_res.output

        # 5. Show command
        show_res = runner.invoke(main, ["show", manifest.run_id])
        assert show_res.exit_code == 0
        assert "COMPLETED" in show_res.output
        assert "loss=0.42" in show_res.output
