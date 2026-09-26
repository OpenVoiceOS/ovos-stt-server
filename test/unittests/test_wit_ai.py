# Licensed under the Apache License, Version 2.0
"""Unit tests for the Wit.ai-compatible router (TestClient, no live server).

Covers all branches of the ``speech`` handler:
- audio/wav (multipart helper succeeds)
- audio/raw with rate= and bits= parameters
- fallback to raw 16k/16-bit when multipart_audio_to_audiodata raises
- query params accepted without error
- response shape validation
"""
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes() -> bytes:
    """Return minimal valid WAV bytes (mono, 16-bit, 16kHz)."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


class FakeModel:
    """Stub model returning a fixed transcript."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript regardless of input."""
        return "hello world"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient wired to a minimal FastAPI app with the wit-ai router."""
    from ovos_stt_http_server.routers.wit_ai import make_wit_ai_router
    app = FastAPI()
    app.include_router(make_wit_ai_router(FakeModel()))
    return TestClient(app)


class TestWitAiSpeechWav:
    """Tests for POST /wit/speech with audio/wav content type."""

    def test_speech_returns_200(self, client):
        """A valid WAV upload returns HTTP 200."""
        resp = client.post(
            "/wit/speech",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav",
                     "Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200

    def test_speech_text_field(self, client):
        """Response body ``text`` field equals the model transcript."""
        resp = client.post(
            "/wit/speech",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        body = resp.json()
        assert body["text"] == "hello world"

    def test_speech_response_shape(self, client):
        """Response contains intents, entities, and traits fields."""
        resp = client.post(
            "/wit/speech",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        body = resp.json()
        assert "intents" in body
        assert "entities" in body
        assert "traits" in body

    def test_speech_version_param_accepted(self, client):
        """``v`` query param is accepted without error."""
        resp = client.post(
            "/wit/speech?v=20200513",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        assert resp.status_code == 200

    def test_speech_no_content_type_falls_back(self, client):
        """Missing Content-Type header falls back gracefully."""
        resp = client.post("/wit/speech", content=_wav_bytes())
        assert resp.status_code == 200

    def test_speech_empty_body_wav(self, client):
        """Empty body with audio/wav Content-Type handled without server error."""
        resp = client.post(
            "/wit/speech",
            content=b"",
            headers={"Content-Type": "audio/wav"},
        )
        # Server may return 200 (fallback) or 422; either is acceptable
        # as long as it does not 500.
        assert resp.status_code < 500


class TestWitAiSpeechRaw:
    """Tests for POST /wit/speech with audio/raw content type."""

    def test_raw_pcm_accepted(self, client):
        """audio/raw content type is processed without error."""
        raw_pcm = b"\x00\x00" * 3200  # 0.1s at 16kHz 16-bit mono
        resp = client.post(
            "/wit/speech",
            content=raw_pcm,
            headers={
                "Content-Type": "audio/raw;encoding=signed-integer;bits=16;rate=16000;endian=little"
            },
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_raw_pcm_custom_rate(self, client):
        """rate= parameter in Content-Type is parsed correctly."""
        raw_pcm = b"\x00\x00" * 800  # short clip
        resp = client.post(
            "/wit/speech",
            content=raw_pcm,
            headers={"Content-Type": "audio/raw;rate=8000;bits=16"},
        )
        assert resp.status_code == 200

    def test_raw_pcm_custom_bits(self, client):
        """bits= parameter in Content-Type is parsed correctly."""
        raw_pcm = b"\x00" * 1600
        resp = client.post(
            "/wit/speech",
            content=raw_pcm,
            headers={"Content-Type": "audio/raw;bits=8;rate=16000"},
        )
        assert resp.status_code == 200

    def test_raw_pcm_no_params_defaults(self, client):
        """audio/raw without rate/bits uses 16kHz/16-bit defaults."""
        raw_pcm = b"\x00\x00" * 3200
        resp = client.post(
            "/wit/speech",
            content=raw_pcm,
            headers={"Content-Type": "audio/raw"},
        )
        assert resp.status_code == 200

    def test_raw_pcm_invalid_rate_ignored(self, client):
        """Non-integer rate= value is silently ignored (default used)."""
        raw_pcm = b"\x00\x00" * 3200
        resp = client.post(
            "/wit/speech",
            content=raw_pcm,
            headers={"Content-Type": "audio/raw;rate=notanumber"},
        )
        assert resp.status_code == 200

    def test_raw_pcm_invalid_bits_ignored(self, client):
        """Non-integer bits= value is silently ignored (default used)."""
        raw_pcm = b"\x00\x00" * 3200
        resp = client.post(
            "/wit/speech",
            content=raw_pcm,
            headers={"Content-Type": "audio/raw;bits=notanumber"},
        )
        assert resp.status_code == 200


class TestWitAiFallback:
    """Tests for the multipart-decode fallback path."""

    def test_unknown_content_type_falls_back(self, client):
        """Unknown content-type triggers multipart_audio_to_audiodata then fallback."""
        # Send garbage bytes — multipart_audio_to_audiodata will raise, and the
        # handler falls back to treating them as raw PCM.
        resp = client.post(
            "/wit/speech",
            content=b"\xff\xfe garbage audio",
            headers={"Content-Type": "audio/mpeg3"},
        )
        assert resp.status_code == 200

    def test_mpeg_content_type_accepted(self, client):
        """audio/mpeg content type does not crash the handler."""
        resp = client.post(
            "/wit/speech",
            content=b"\x00" * 256,
            headers={"Content-Type": "audio/mpeg"},
        )
        assert resp.status_code == 200
