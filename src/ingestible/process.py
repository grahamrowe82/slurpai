"""Core orchestrator — processes a single file through the ingest pipeline."""

from __future__ import annotations

from pathlib import Path

from .ffmpeg import extract_audio, extract_frames, has_video_stream
from .log import ProcessLog
from .transcribe import transcribe

AUDIO_EXTENSIONS = {".opus", ".m4a", ".ogg", ".mp3", ".wav"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm"}
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def process_file(
    input_path: Path,
    *,
    backend: str,
    frame_interval: int = 15,
    output_dir: Path | None = None,
    language: str = "en",
) -> Path:
    """Process a single audio/video file. Returns the output directory."""
    input_path = input_path.resolve()
    ext = input_path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported format: {ext}")

    out = _resolve_output_dir(input_path, output_dir)
    out.mkdir(parents=True, exist_ok=True)

    log = ProcessLog(out / "process.log")
    log.log(f"=== Ingestible v0.1.0 ===")
    log.log(f"Input:   {input_path}")
    log.log(f"Output:  {out}/")
    log.log(f"Backend: {backend}")

    transcript_path = out / "transcript.txt"
    is_video = ext in VIDEO_EXTENSIONS and has_video_stream(input_path)

    # --- Step 1: Transcribe ---
    # Always convert to MP3 first — normalises all formats into one known-good
    # path. This matches the proven bash script behaviour: no conditionals,
    # no format-compatibility surprises.
    if transcript_path.exists():
        log.skip(f"Transcript already exists: {transcript_path.name}")
    else:
        audio_tmp = out / "audio.mp3"
        if audio_tmp.exists():
            log.skip(f"Audio already extracted: {audio_tmp.name}")
        else:
            log.log("Extracting audio...")
            extract_audio(input_path, audio_tmp)
            log.log(f"Audio extracted: {_file_size(audio_tmp)}")

        log.log(f"Transcribing with {backend}...")
        text = transcribe(audio_tmp, backend=backend, language=language)
        transcript_path.write_text(text, encoding="utf-8")
        word_count = len(text.split())
        log.log(f"Transcript: {word_count} words")

        # Clean up intermediate audio
        audio_tmp.unlink(missing_ok=True)

    # --- Step 2: Extract frames (video only) ---
    frames_dir = out / "frames"
    if not is_video:
        log.skip("Audio-only file — no frames to extract")
    elif list(frames_dir.glob("frame_*.jpg")):
        existing = len(list(frames_dir.glob("frame_*.jpg")))
        log.skip(f"Frames already exist: {existing} frames")
    else:
        log.log(f"Extracting frames every {frame_interval}s...")
        count = extract_frames(input_path, frames_dir, interval=frame_interval)
        log.log(f"Extracted {count} frames")

    log.log("=== Done ===")
    return out


def _resolve_output_dir(input_path: Path, output_dir: Path | None) -> Path:
    """Derive output directory: <parent>/<stem>/ or <output_dir>/<stem>/."""
    stem = input_path.stem
    if output_dir:
        return output_dir / stem
    return input_path.parent / stem


def _file_size(path: Path) -> str:
    """Human-readable file size."""
    size = path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
