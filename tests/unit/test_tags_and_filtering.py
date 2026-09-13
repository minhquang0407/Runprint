"""Unit tests for run tags and filtering."""

import sys
from click.testing import CliRunner
from qr.cli import main
from qr.storage.local import RunStorage
from pathlib import Path


def test_run_with_tags_and_filtering():
    runner = CliRunner(env={"COLUMNS": "160"})
    with runner.isolated_filesystem():
        # 1. Init
        runner.invoke(main, ["init"])

        # 2. Run with multiple tags
        cmd1 = [sys.executable, "-c", "print('run baseline')"]
        res1 = runner.invoke(main, ["run", "--tag", "baseline", "--tag", "exp1", "--", *cmd1])
        assert res1.exit_code == 0

        # Run with another tag
        cmd2 = [sys.executable, "-c", "print('run ablation')"]
        res2 = runner.invoke(main, ["run", "--tag", "ablation", "--", *cmd2])
        assert res2.exit_code == 0

        # 3. List without filter
        list_all = runner.invoke(main, ["list"])
        assert list_all.exit_code == 0
        assert "baseline" in list_all.output
        assert "ablation" in list_all.output

        # 4. List with tag filter
        list_baseline = runner.invoke(main, ["list", "--tag", "baseline"])
        assert list_baseline.exit_code == 0
        assert "baseline" in list_baseline.output
        assert "ablation" not in list_baseline.output

        # 5. List with nonexistent tag
        list_none = runner.invoke(main, ["list", "--tag", "nonexistent"])
        assert list_none.exit_code == 0
        assert "No runs found matching tag: nonexistent" in list_none.output
