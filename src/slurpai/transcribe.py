"""Transcription backends — OpenAI Whisper API and faster-whisper local."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def transcribe(audio_path: Path, *, backend: str, language: str = "en") -> str:
    """Transcribe an audio file, returning the text.

    Routes to the appropriate backend based on the `backend` argument.
    """
    if backend == "openai":
        return _transcribe_openai(audio_path, language=language)
    elif backend == "faster-whisper":
        return _transcribe_faster_whisper(audio_path, language=language)
    else:
        raise ValueError(f"Unknown backend: {backend!r}. Use 'openai' or 'faster-whisper'.")


def _extract_text(payload: Any) -> str:
    """Defensively extract text from an OpenAI transcription response."""
    text = getattr(payload, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    if isinstance(payload, dict):
        candidate = payload.get("text")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise ValueError("Transcription response missing text output")


def _transcribe_openai(audio_path: Path, *, language: str) -> str:
    """Transcribe using the OpenAI Whisper API via the SDK."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "OpenAI backend requires the openai package. "
            "Install with: pip install slurpai"
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Add it to your .env file or environment."
        )

    client = OpenAI()
    model = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1").strip() or "whisper-1"

    with audio_path.open("rb") as f:
        response = client.audio.transcriptions.create(
            file=f,
            model=model,
            language=language,
        )

    return _extract_text(response)


def _transcribe_faster_whisper(audio_path: Path, *, language: str) -> str:
    """Transcribe locally using faster-whisper on CPU."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "Local backend requires faster-whisper. "
            "Install with: pip install slurpai[local]"
        )

    model_size = os.getenv("SLURPAI_WHISPER_MODEL", "base").strip() or "base"
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, _info = model.transcribe(str(audio_path), language=language)
    text = " ".join(segment.text.strip() for segment in segments)

    if not text.strip():
        raise ValueError("Transcription produced no text")

    return text.strip()
