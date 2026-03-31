"""Shared test fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sample_audio(tmp_path: Path) -> Path:
    """Create a tiny audio file (1 second of silence) for testing."""
    audio = tmp_path / "test.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "1", "-q:a", "9",
            str(audio),
        ],
        capture_output=True,
        check=True,
    )
    return audio


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Create a tiny video file (3 seconds, test pattern + silence)."""
    video = tmp_path / "test.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=1",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "3", "-shortest",
            str(video),
        ],
        capture_output=True,
        check=True,
    )
    return video
