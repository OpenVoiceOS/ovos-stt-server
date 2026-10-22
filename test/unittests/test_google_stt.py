# Licensed under the Apache License, Version 2.0
"""Unit tests for the Google Cloud Speech v1-compatible router (TestClient, no live SDK)."""
import base64
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes() -> bytes:
    """Return a minimal silent mono WAV at 16 kHz suitable for test payloads."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


def _wav_b64() -> str:
    """Return the test WAV as a base64 string (the SDK's wire encoding)."""
    return base64.b64encode(_wav_bytes()).decode()


class FakeModel:
    """Minimal STT engine stub that always returns 'hello world'."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript regardless of audio content."""
        return "hello world"


class FakeModelEmpty:
    """STT stub that returns an empty string (simulates silence / no speech)."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return an empty transcript to exercise the empty-results branch."""
        return ""


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient for the Google STT router mounted on a bare FastAPI app."""
    from ovos_stt_http_server.routers.google_stt import make_google_stt_router

    app = FastAPI()
    app.include_router(make_google_stt_router(FakeModel()))
    return TestClient(app)


@pytest.fixture(scope="module")
def client_empty() -> TestClient:
    """TestClient backed by the empty-transcript stub."""
    from ovos_stt_http_server.routers.google_stt import make_google_stt_router

    app = FastAPI()
    app.include_router(make_google_stt_router(FakeModelEmpty()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECOGNIZE_PATH = "/google/v1/speech:recognize"


def _recognize_body(content: str = None, lang: str = "en-US", sample_rate: int = 16000) -> dict:
    """Build a minimal RecognizeRequest body dict."""
    return {
        "config": {
            "encoding": 1,
            "sampleRateHertz": sample_rate,
            "languageCode": lang,
        },
        "audio": {
            "content": content or _wav_b64(),
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoogleSttRecognize:
    """Tests for POST /google/v1/speech:recognize."""

    def test_recognize_returns_transcript(self, client):
        """Happy-path: valid WAV content → transcript in first alternative."""
        resp = client.post(_RECOGNIZE_PATH, json=_recognize_body())
        assert resp.status_code == 200
        body = resp.json()
        assert body["results"][0]["alternatives"][0]["transcript"] == "hello world"

    def test_recognize_language_propagated(self, client):
        """Language code from config is reflected in the result's languageCode field."""
        resp = client.post(_RECOGNIZE_PATH, json=_recognize_body(lang="pt-PT"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["results"][0]["languageCode"] == "pt-PT"

    def test_recognize_empty_transcript_returns_empty_results(self, client_empty):
        """When the model returns '', results list must be empty (no speech)."""
        resp = client_empty.post(_RECOGNIZE_PATH, json=_recognize_body())
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_recognize_missing_audio_field(self, client):
        """Request without audio key must return HTTP 400."""
        resp = client.post(_RECOGNIZE_PATH, json={"config": {"languageCode": "en-US"}})
        assert resp.status_code == 400

    def test_recognize_empty_audio_content_and_no_uri(self, client):
        """Request with audio.content absent and no uri must return HTTP 400."""
        resp = client.post(
            _RECOGNIZE_PATH,
            json={"config": {"languageCode": "en-US"}, "audio": {}},
        )
        assert resp.status_code == 400

    def test_recognize_uri_not_supported(self, client):
        """audio.uri is not supported locally; must return HTTP 400."""
        resp = client.post(
            _RECOGNIZE_PATH,
            json={
                "config": {"languageCode": "en-US"},
                "audio": {"uri": "gs://bucket/file.flac"},
            },
        )
        assert resp.status_code == 400

    def test_recognize_invalid_base64(self, client):
        """Malformed base64 in audio.content must return HTTP 400."""
        resp = client.post(
            _RECOGNIZE_PATH,
            json=_recognize_body(content="!!!not-base64!!!"),
        )
        assert resp.status_code == 400

    def test_recognize_invalid_json_body(self, client):
        """Non-JSON body must return HTTP 422 (FastAPI) or 400."""
        resp = client.post(
            _RECOGNIZE_PATH,
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)

    def test_recognize_no_config(self, client):
        """Config-less request uses defaults (16kHz, en-US) and still works."""
        resp = client.post(
            _RECOGNIZE_PATH,
            json={"audio": {"content": _wav_b64()}},
        )
        assert resp.status_code == 200
        assert resp.json()["results"][0]["alternatives"][0]["transcript"] == "hello world"

    def test_recognize_response_shape(self, client):
        """Response must contain results / alternatives / transcript / confidence / channelTag."""
        resp = client.post(_RECOGNIZE_PATH, json=_recognize_body())
        body = resp.json()
        result = body["results"][0]
        alt = result["alternatives"][0]
        assert "transcript" in alt
        assert "confidence" in alt
        assert "channelTag" in result
