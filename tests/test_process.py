"""Tests for the process orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ingestible.process import SUPPORTED_EXTENSIONS, process_file


def test_supported_extensions_include_common_formats():
    assert ".opus" in SUPPORTED_EXTENSIONS
    assert ".m4a" in SUPPORTED_EXTENSIONS
    assert ".mp4" in SUPPORTED_EXTENSIONS
    assert ".mp3" in SUPPORTED_EXTENSIONS


def test_process_audio_file(sample_audio: Path):
    """Process an audio file with mocked transcription."""
    with patch("ingestible.process.transcribe", return_value="Hello from the test"):
        out = process_file(sample_audio, backend="openai")

    assert out.is_dir()
    transcript = out / "transcript.txt"
    assert transcript.exists()
    assert transcript.read_text() == "Hello from the test"

    log = out / "process.log"
    assert log.exists()
    assert "Done" in log.read_text()

    # Audio-only: no frames directory should be populated
    frames = out / "frames"
    assert not list(frames.glob("frame_*.jpg")) if frames.exists() else True


def test_process_video_file(sample_video: Path):
    """Process a video file with mocked transcription."""
    with patch("ingestible.process.transcribe", return_value="Video transcript here"):
        out = process_file(sample_video, backend="openai", frame_interval=1)

    assert out.is_dir()
    transcript = out / "transcript.txt"
    assert transcript.exists()
    assert transcript.read_text() == "Video transcript here"

    frames = out / "frames"
    assert frames.is_dir()
    assert len(list(frames.glob("frame_*.jpg"))) >= 1


def test_idempotent_skip(sample_audio: Path):
    """Second run should skip transcription."""
    with patch("ingestible.process.transcribe", return_value="First run") as mock_t:
        process_file(sample_audio, backend="openai")
        assert mock_t.call_count == 1

    with patch("ingestible.process.transcribe", return_value="Second run") as mock_t:
        process_file(sample_audio, backend="openai")
        assert mock_t.call_count == 0  # Should have been skipped


def test_unsupported_format(tmp_path: Path):
    """Unsupported extensions raise ValueError."""
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")

    import pytest
    with pytest.raises(ValueError, match="Unsupported format"):
        process_file(txt, backend="openai")
