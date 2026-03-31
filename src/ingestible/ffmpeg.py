"""FFmpeg wrappers for audio extraction and frame capture."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def extract_audio(input_path: Path, output_path: Path) -> Path:
    """Extract audio from video as compressed MP3 for API upload.

    Uses mono, 16kHz, 64kbps — compresses a 10-min video from ~60MB to ~5MB,
    staying under the 25MB Whisper API limit.
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        str(output_path),
        "-loglevel", "warning",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr.strip()}")
    return output_path


def extract_frames(input_path: Path, output_dir: Path, *, interval: int = 15) -> int:
    """Extract video frames every `interval` seconds as JPEG.

    Returns the number of frames extracted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(output_dir / "frame_%03d.jpg")

    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        pattern,
        "-loglevel", "warning",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {result.stderr.strip()}")

    return len(list(output_dir.glob("frame_*.jpg")))


def has_video_stream(input_path: Path) -> bool:
    """Check if file contains a video stream using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return "video" in result.stdout.lower()
