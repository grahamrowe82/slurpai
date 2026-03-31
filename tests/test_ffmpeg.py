"""Tests for the ffmpeg module."""

from pathlib import Path

from slurpai.ffmpeg import check_ffmpeg, extract_audio, extract_frames, has_video_stream


def test_check_ffmpeg():
    assert check_ffmpeg() is True


def test_has_video_stream_with_video(sample_video: Path):
    assert has_video_stream(sample_video) is True


def test_has_video_stream_with_audio(sample_audio: Path):
    assert has_video_stream(sample_audio) is False


def test_extract_audio(sample_video: Path, tmp_path: Path):
    output = tmp_path / "out.mp3"
    result = extract_audio(sample_video, output)
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_extract_frames(sample_video: Path, tmp_path: Path):
    frames_dir = tmp_path / "frames"
    count = extract_frames(sample_video, frames_dir, interval=1)
    assert count >= 1
    assert len(list(frames_dir.glob("frame_*.jpg"))) == count
