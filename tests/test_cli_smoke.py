"""Smoke tests for the kb CLI: import paths and help/version invocation."""

from __future__ import annotations

from click.testing import CliRunner

from kb_cli import __version__
from kb_cli.cli import cli


def test_version_flag_prints_package_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_known_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output


def test_doctor_on_missing_kb_exits_nonzero(tmp_path) -> None:
    result = CliRunner().invoke(cli, ["doctor", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "No .kb/ found" in result.output
