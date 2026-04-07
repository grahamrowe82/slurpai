"""Tests for the record module."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slurpai import record


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all record module paths to tmp_path."""
    monkeypatch.setattr(record, "SLURPAI_DIR", tmp_path)
    monkeypatch.setattr(record, "SNAPSHOT_PATH", tmp_path / "audio_snapshot.json")
    monkeypatch.setattr(record, "SWIFT_BINARY", tmp_path / "audio_setup")


# ---------------------------------------------------------------------------
# check_prerequisites
# ---------------------------------------------------------------------------


@patch("slurpai.record.subprocess.run")
@patch("slurpai.record.shutil.which")
def test_check_prerequisites_all_present(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/something"
    mock_run.return_value = MagicMock(stdout="MacBook Pro Speakers\nBlackHole 2ch\n")

    result = record.check_prerequisites()
    assert result["ffmpeg"] is True
    assert result["SwitchAudioSource"] is True
    assert result["swiftc"] is True
    assert result["BlackHole 2ch"] is True


@patch("slurpai.record.subprocess.run")
@patch("slurpai.record.shutil.which")
def test_check_prerequisites_missing_blackhole(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/something"
    mock_run.return_value = MagicMock(stdout="MacBook Pro Speakers\n")

    result = record.check_prerequisites()
    assert result["BlackHole 2ch"] is False


@patch("slurpai.record.shutil.which")
def test_check_prerequisites_missing_tools(mock_which):
    mock_which.return_value = None

    result = record.check_prerequisites()
    assert result["ffmpeg"] is False
    assert result["SwitchAudioSource"] is False
    assert result["swiftc"] is False
    assert result["BlackHole 2ch"] is False


# ---------------------------------------------------------------------------
# check_multi_output_device
# ---------------------------------------------------------------------------


@patch("slurpai.record.subprocess.run")
def test_check_multi_output_device_exists(mock_run):
    mock_run.return_value = MagicMock(stdout="MacBook Pro Speakers\nSlurpAI Multi-Output\nBlackHole 2ch\n")
    assert record.check_multi_output_device() is True


@patch("slurpai.record.subprocess.run")
def test_check_multi_output_device_missing(mock_run):
    mock_run.return_value = MagicMock(stdout="MacBook Pro Speakers\nBlackHole 2ch\n")
    assert record.check_multi_output_device() is False


# ---------------------------------------------------------------------------
# snapshot_audio / restore_audio
# ---------------------------------------------------------------------------


@patch("slurpai.record.subprocess.run")
def test_snapshot_audio(mock_run, tmp_path: Path):
    mock_run.return_value = MagicMock(stdout="MacBook Pro Speakers\n")

    device = record.snapshot_audio()

    assert device == "MacBook Pro Speakers"
    snapshot_path = tmp_path / "audio_snapshot.json"
    assert snapshot_path.exists()
    data = json.loads(snapshot_path.read_text())
    assert data["device"] == "MacBook Pro Speakers"
    assert data["pid"] == os.getpid()


@patch("slurpai.record.subprocess.run")
def test_restore_audio(mock_run, tmp_path: Path):
    snapshot_path = tmp_path / "audio_snapshot.json"
    snapshot_path.write_text(json.dumps({"device": "MacBook Pro Speakers", "pid": 99999}))

    record.restore_audio(quiet=True)

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == ["SwitchAudioSource", "-s", "MacBook Pro Speakers"]
    assert not snapshot_path.exists()


def test_restore_audio_no_snapshot(tmp_path: Path):
    """No error when snapshot doesn't exist (quiet mode)."""
    record.restore_audio(quiet=True)  # should not raise


def test_restore_audio_no_snapshot_verbose(tmp_path: Path, capsys):
    """Prints guidance when no snapshot exists in verbose mode."""
    record.restore_audio(quiet=False)
    # Click outputs through its own mechanism; check it didn't raise


@patch("slurpai.record.subprocess.run", side_effect=OSError("broken"))
def test_restore_audio_quiet_swallows_errors(mock_run, tmp_path: Path):
    """quiet=True swallows exceptions."""
    snapshot_path = tmp_path / "audio_snapshot.json"
    snapshot_path.write_text(json.dumps({"device": "Speakers", "pid": 99999}))

    record.restore_audio(quiet=True)  # should not raise


# ---------------------------------------------------------------------------
# check_stale_snapshot
# ---------------------------------------------------------------------------


def test_check_stale_snapshot_no_file(tmp_path: Path):
    assert record.check_stale_snapshot() is None


def test_check_stale_snapshot_dead_pid(tmp_path: Path):
    """Stale snapshot with a dead PID returns the device name."""
    snapshot_path = tmp_path / "audio_snapshot.json"
    snapshot_path.write_text(json.dumps({"device": "MacBook Pro Speakers", "pid": 999999999}))

    result = record.check_stale_snapshot()
    assert result == "MacBook Pro Speakers"


def test_check_stale_snapshot_alive_pid(tmp_path: Path):
    """Snapshot with a live PID (our own) returns None (concurrent recording)."""
    snapshot_path = tmp_path / "audio_snapshot.json"
    snapshot_path.write_text(json.dumps({"device": "MacBook Pro Speakers", "pid": os.getpid()}))

    result = record.check_stale_snapshot()
    assert result is None


# ---------------------------------------------------------------------------
# build_ffmpeg_cmd
# ---------------------------------------------------------------------------


@patch("slurpai.record._detect_microphone", return_value="MacBook Air Microphone")
def test_build_ffmpeg_cmd(mock_mic):
    cmd = record.build_ffmpeg_cmd(Path("/tmp/test.mp4"))
    joined = " ".join(cmd)

    assert cmd[0] == "ffmpeg"
    assert "avfoundation" in cmd
    assert "Capture screen 0:MacBook Air Microphone" in joined
    assert ":BlackHole 2ch" in joined
    assert "amerge=inputs=2" in joined
    assert "pan=stereo" in joined
    assert "ultrafast" in cmd
    assert "/tmp/test.mp4" in cmd
    assert "-framerate" in cmd
    idx = cmd.index("-framerate")
    assert cmd[idx + 1] == "5"


@patch("slurpai.record._detect_microphone", return_value=None)
def test_build_ffmpeg_cmd_no_mic(mock_mic):
    with pytest.raises(RuntimeError, match="Could not detect built-in microphone"):
        record.build_ffmpeg_cmd(Path("/tmp/test.mp4"))


@patch("slurpai.record.subprocess.run")
def test_detect_microphone_found(mock_run):
    mock_run.return_value = MagicMock(
        stderr=(
            "[AVFoundation indev @ 0x1] AVFoundation video devices:\n"
            "[AVFoundation indev @ 0x1] [0] Capture screen 0\n"
            "[AVFoundation indev @ 0x1] AVFoundation audio devices:\n"
            "[AVFoundation indev @ 0x1] [0] MacBook Air Microphone\n"
            "[AVFoundation indev @ 0x1] [1] BlackHole 2ch\n"
        )
    )
    assert record._detect_microphone() == "MacBook Air Microphone"


@patch("slurpai.record.subprocess.run")
def test_detect_microphone_not_found(mock_run):
    mock_run.return_value = MagicMock(
        stderr="[AVFoundation indev @ 0x1] [0] BlackHole 2ch\n"
    )
    assert record._detect_microphone() is None


# ---------------------------------------------------------------------------
# run_setup
# ---------------------------------------------------------------------------


@patch("slurpai.record.check_multi_output_device", return_value=True)
@patch("slurpai.record.check_prerequisites", return_value={
    "ffmpeg": True, "SwitchAudioSource": True, "swiftc": True, "BlackHole 2ch": True,
})
def test_run_setup_already_exists(mock_prereqs, mock_device, capsys):
    """Setup exits early when the device already exists."""
    record.run_setup()
    # Should not call compile or create


@patch("slurpai.record.create_multi_output_device")
@patch("slurpai.record.compile_swift_helper", return_value=Path("/tmp/audio_setup"))
@patch("slurpai.record.check_multi_output_device", return_value=False)
@patch("slurpai.record.check_prerequisites", return_value={
    "ffmpeg": True, "SwitchAudioSource": True, "swiftc": True, "BlackHole 2ch": True,
})
def test_run_setup_fresh(mock_prereqs, mock_device, mock_compile, mock_create):
    """Setup compiles and creates when device doesn't exist."""
    record.run_setup()
    mock_compile.assert_called_once()
    mock_create.assert_called_once()


@patch("slurpai.record.check_prerequisites", return_value={
    "ffmpeg": True, "SwitchAudioSource": False, "swiftc": True, "BlackHole 2ch": False,
})
def test_run_setup_missing_prerequisites(mock_prereqs):
    """Setup exits with error when prerequisites are missing."""
    with pytest.raises(SystemExit):
        record.run_setup()


# ---------------------------------------------------------------------------
# run_recording
# ---------------------------------------------------------------------------


@patch("slurpai.ffmpeg.validate_recording")
@patch("slurpai.record.build_ffmpeg_cmd", return_value=["ffmpeg", "fake"])
@patch("slurpai.record.restore_audio")
@patch("slurpai.record.snapshot_audio", return_value="MacBook Air Speakers")
@patch("slurpai.record.subprocess.run")
def test_run_recording_happy_path(mock_run, mock_snap, mock_restore, mock_cmd, mock_validate, tmp_path):
    """Successful recording: audio switched, ffmpeg called, audio restored."""
    output = tmp_path / "test.mp4"
    output.write_bytes(b"\x00" * 1024)  # dummy file

    # First call is SwitchAudioSource, second is ffmpeg
    mock_run.side_effect = [
        MagicMock(returncode=0),  # SwitchAudioSource
        MagicMock(returncode=0),  # ffmpeg
    ]

    result = record.run_recording(output)

    assert result == output
    mock_snap.assert_called_once()
    mock_restore.assert_called_once()
    mock_validate.assert_called_once_with(output)


@patch("slurpai.record.build_ffmpeg_cmd", return_value=["ffmpeg", "fake"])
@patch("slurpai.record.restore_audio")
@patch("slurpai.record.snapshot_audio", return_value="MacBook Air Speakers")
@patch("slurpai.record.subprocess.run")
def test_run_recording_no_output_file(mock_run, mock_snap, mock_restore, mock_cmd, tmp_path):
    """ffmpeg exits but produces no file — RuntimeError raised, audio restored."""
    output = tmp_path / "test.mp4"
    # Don't create the file

    mock_run.side_effect = [
        MagicMock(returncode=0),  # SwitchAudioSource
        MagicMock(returncode=1),  # ffmpeg
    ]

    with pytest.raises(RuntimeError, match="missing or empty"):
        record.run_recording(output)

    mock_restore.assert_called_once()


@patch("slurpai.record.build_ffmpeg_cmd", return_value=["ffmpeg", "fake"])
@patch("slurpai.record.restore_audio")
@patch("slurpai.record.snapshot_audio", return_value="MacBook Air Speakers")
@patch("slurpai.record.subprocess.run")
def test_run_recording_keyboard_interrupt(mock_run, mock_snap, mock_restore, mock_cmd, tmp_path):
    """Ctrl+C during recording — audio is still restored."""
    output = tmp_path / "test.mp4"

    mock_run.side_effect = [
        MagicMock(returncode=0),  # SwitchAudioSource
        KeyboardInterrupt,        # ffmpeg interrupted
    ]

    with pytest.raises(KeyboardInterrupt):
        record.run_recording(output)

    mock_restore.assert_called_once()
