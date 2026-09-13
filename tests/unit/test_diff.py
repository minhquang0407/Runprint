"""Unit tests for qr diff command."""

import sys
from click.testing import CliRunner
from qr.cli import main
from qr.storage.local import RunStorage
from pathlib import Path


def test_diff_between_two_runs():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(main, ["init"])

        # Run 1
        cmd1 = [sys.executable, "-c", "import qr; qr.log({'acc': 0.80, 'loss': 0.50}); print('run 1')"]
        runner.invoke(main, ["run", "--tag", "v1", "--", *cmd1])

        # Run 2
        cmd2 = [sys.executable, "-c", "import qr; qr.log({'acc': 0.88, 'loss': 0.35}); print('run 2')"]
        runner.invoke(main, ["run", "--tag", "v2", "--", *cmd2])

        qr_dir = Path.cwd() / ".qr"
        runs = RunStorage.list_all_runs(qr_dir)
        assert len(runs) == 2

        id_new = runs[0].run_id
        id_old = runs[1].run_id

        # Run diff
        diff_res = runner.invoke(main, ["diff", id_old, id_new])
        assert diff_res.exit_code == 0
        assert f"Run Comparison: {id_old} vs {id_new}" in diff_res.output
        assert "Metric: acc" in diff_res.output
        assert "0.8" in diff_res.output
        assert "0.88" in diff_res.output
        assert "(+0.0800)" in diff_res.output
