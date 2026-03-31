"""Tests for the transcription module (mocked — no API calls)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slurpai.transcribe import _extract_text, transcribe


class TestExtractText:
    def test_from_object_attribute(self):
        obj = MagicMock()
        obj.text = "Hello world"
        assert _extract_text(obj) == "Hello world"

    def test_from_dict(self):
        assert _extract_text({"text": "Hello world"}) == "Hello world"

    def test_strips_whitespace(self):
        assert _extract_text({"text": "  Hello world  "}) == "Hello world"

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match="missing text"):
            _extract_text({"text": ""})

    def test_raises_on_missing(self):
        with pytest.raises(ValueError, match="missing text"):
            _extract_text({})


class TestTranscribeOpenAI:
    @patch("slurpai.transcribe.OpenAI", create=True)
    def test_calls_api(self, mock_openai_cls, sample_audio: Path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_response = MagicMock()
        mock_response.text = "This is the transcript"
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_response

        # Patch the lazy import inside _transcribe_openai
        with patch("slurpai.transcribe.OpenAI", return_value=mock_client, create=True):
            # Need to patch at the point of import
            import slurpai.transcribe as mod
            with patch.object(mod, "_transcribe_openai") as mock_fn:
                mock_fn.return_value = "This is the transcript"
                result = transcribe(sample_audio, backend="openai")

        assert result == "This is the transcript"

    def test_raises_without_api_key(self, sample_audio: Path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            transcribe(sample_audio, backend="openai")


def test_unknown_backend(sample_audio: Path):
    with pytest.raises(ValueError, match="Unknown backend"):
        transcribe(sample_audio, backend="nonexistent")
