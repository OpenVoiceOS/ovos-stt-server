# Licensed under the Apache License, Version 2.0
"""Unit tests for the OpenAI Whisper-compatible router.

Uses FastAPI TestClient (no live server, no real openai API key).
A FakeModel returning "hello world" drives all assertions.
"""
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_bytes(text_length: int = 160) -> bytes:
    """Return minimal valid WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * text_length)
    return buf.getvalue()


class FakeModel:
    """Minimal model stub returning a fixed transcript."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        return "hello world"


class LangRecordingModel:
    """Model stub that records the language it was called with.

    Mirrors the real onnx-asr plugin's behaviour: it has no notion of
    ``"auto"`` and would raise on a literal ``"auto"`` tag.
    """

    def __init__(self):
        self.received_lang = None

    def process_audio(self, audio, lang: str = "auto") -> str:
        if lang == "auto":
            raise KeyError("<|auto|>")
        self.received_lang = lang
        return "hello world"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient for the openai_whisper router mounted on a fresh app."""
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    app = FastAPI()
    app.include_router(make_openai_whisper_router(FakeModel()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Transcriptions endpoint
# ---------------------------------------------------------------------------

class TestTranscriptions:
    """Tests for POST /openai/v1/audio/transcriptions."""

    def test_json_response_default(self, client):
        """Default response_format=json returns {text: ...}."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "hello world"

    def test_json_response_explicit(self, client):
        """Explicit response_format=json returns {text: ...}."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "json"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_text_response_format(self, client):
        """response_format=text returns plain text."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "text"},
        )
        assert resp.status_code == 200
        assert resp.text == "hello world"

    def test_verbose_json_response_format(self, client):
        """response_format=verbose_json includes duration, language, segments."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "verbose_json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "hello world"
        assert "duration" in body
        assert "language" in body
        assert isinstance(body["segments"], list)
        assert body["segments"][0]["text"] == "hello world"

    def test_srt_response_format(self, client):
        """response_format=srt returns SRT-formatted plain text."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "srt"},
        )
        assert resp.status_code == 200
        assert "hello world" in resp.text
        assert "-->" in resp.text

    def test_vtt_response_format(self, client):
        """response_format=vtt returns WebVTT-formatted plain text."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "vtt"},
        )
        assert resp.status_code == 200
        assert "WEBVTT" in resp.text
        assert "hello world" in resp.text

    def test_with_language_param(self, client):
        """language param is forwarded to the model."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "language": "pt"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_with_temperature_and_prompt(self, client):
        """temperature and prompt are accepted without error."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={
                "model": "whisper-1",
                "temperature": "0.2",
                "prompt": "some hint",
            },
        )
        assert resp.status_code == 200

    def test_empty_file_returns_400(self, client):
        """Empty file body returns HTTP 400."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", b"", "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 400

    def test_missing_model_field_returns_422(self, client):
        """Missing required model field returns HTTP 422."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={},
        )
        assert resp.status_code == 422

    def test_unknown_response_format_returns_422(self, client):
        """Unknown response_format returns HTTP 422."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "xml"},
        )
        assert resp.status_code == 422

    def test_missing_language_falls_back_to_concrete_lang(self):
        """No ``language`` field must not leak the literal "auto" to the engine.

        The onnx-asr NeMo tokenizer has no ``<|auto|>`` token and raises on a
        literal "auto" tag, matching the live 500 seen in production.
        """
        from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

        stub = LangRecordingModel()
        app = FastAPI()
        app.include_router(make_openai_whisper_router(stub))
        c = TestClient(app)
        resp = c.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        assert stub.received_lang is not None
        assert stub.received_lang != "auto"

    def test_raw_bytes_fallback(self, client):
        """Non-WAV bytes (raw PCM) are accepted via fallback path."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.raw", b"\x00\x00" * 160, "application/octet-stream")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"


# ---------------------------------------------------------------------------
# Translations endpoint
# ---------------------------------------------------------------------------

class TestTranslations:
    """Tests for POST /openai/v1/audio/translations."""

    def test_json_response(self, client):
        """translations endpoint returns {text: ...} with json format."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_text_response_format(self, client):
        """translations endpoint supports response_format=text."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "text"},
        )
        assert resp.status_code == 200
        assert resp.text == "hello world"

    def test_verbose_json_response_format(self, client):
        """translations endpoint supports verbose_json."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "verbose_json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "hello world"
        assert body["language"] == "en"

    def test_empty_file_returns_400(self, client):
        """translations endpoint rejects empty files."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", b"", "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 400

    def test_missing_model_returns_422(self, client):
        """Missing model field returns 422."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={},
        )
        assert resp.status_code == 422


class FakeTranslator:
    """Minimal OVOS LanguageTranslator stub for the translations endpoint."""

    def translate(self, text, target=None, source=None):
        return f"[{target}] {text}"


def _client_with_translator() -> TestClient:
    from fastapi import FastAPI
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router
    app = FastAPI()
    app.include_router(make_openai_whisper_router(FakeModel(), translator=FakeTranslator()))
    return TestClient(app)


def test_translations_runs_through_translator():
    """/audio/translations transcribes then translates the text to English."""
    import io
    c = _client_with_translator()
    resp = c.post(
        "/openai/v1/audio/translations",
        files={"file": ("a.wav", io.BytesIO(b"RIFFxxxx"), "audio/wav")},
        data={"model": "whisper-1"},
    )
    assert resp.status_code == 200
    # FakeModel returns "hello world"; FakeTranslator prefixes the target lang
    assert resp.json()["text"] == "[en] hello world"


def test_translations_without_translator_returns_transcript():
    """Without a translator, /translations returns the untranslated transcript."""
    import io
    from fastapi import FastAPI
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router
    app = FastAPI()
    app.include_router(make_openai_whisper_router(FakeModel()))  # translator=None
    c = TestClient(app)
    resp = c.post(
        "/openai/v1/audio/translations",
        files={"file": ("a.wav", io.BytesIO(b"RIFFxxxx"), "audio/wav")},
        data={"model": "whisper-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "hello world"
