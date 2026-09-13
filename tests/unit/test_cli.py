"""Unit tests for Click CLI interface."""

from click.testing import CliRunner
from qr.cli import main


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "QR -- Reproducible Research Execution Wrapper" in result.output
    assert "init" in result.output
    assert "run" in result.output
    assert "list" in result.output
    assert "show" in result.output
    assert "rerun" in result.output


def test_cli_init():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "Initialized QR project in" in result.output
