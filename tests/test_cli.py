"""Tests for the CLI entry point."""

from __future__ import annotations

from pathlib import Path

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
    assert "0.1.2" in result.output


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
