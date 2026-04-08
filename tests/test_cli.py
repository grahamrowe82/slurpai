"""Tests for the CLI entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from slurpai.cli import slurpai


def test_help():
    runner = CliRunner()
    result = runner.invoke(slurpai, ["--help"])
    assert result.exit_code == 0
    assert "Convert voice notes" in result.output


def test_version():
    runner = CliRunner()
    result = runner.invoke(slurpai, ["--version"])
    assert result.exit_code == 0
    assert "0.2.1" in result.output


def test_dry_run(sample_audio: Path):
    runner = CliRunner()
    result = runner.invoke(slurpai, ["--dry-run", str(sample_audio)])
    assert result.exit_code == 0
    assert "Would process 1 file(s)" in result.output


def test_unsupported_file_skipped(tmp_path: Path):
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    runner = CliRunner()
    result = runner.invoke(slurpai, [str(txt)])
    assert "Skipping unsupported format" in result.output


def test_process_subcommand_explicit(sample_audio: Path):
    """The explicit 'process' subcommand works."""
    runner = CliRunner()
    result = runner.invoke(slurpai, ["process", "--dry-run", str(sample_audio)])
    assert result.exit_code == 0
    assert "Would process 1 file(s)" in result.output


def test_record_help():
    """The 'record' subcommand shows its own help."""
    runner = CliRunner()
    result = runner.invoke(slurpai, ["record", "--help"])
    assert result.exit_code == 0
    assert "Record screen" in result.output
    assert "--setup" in result.output
    assert "--restore" in result.output


@patch("platform.system", return_value="Linux")
def test_record_macos_only(mock_platform):
    """record refuses to run on non-macOS."""
    runner = CliRunner()
    result = runner.invoke(slurpai, ["record", "--setup"])
    assert result.exit_code != 0
    assert "only supported on macOS" in result.output
