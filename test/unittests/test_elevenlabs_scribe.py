# Licensed under the Apache License, Version 2.0
"""Unit tests for the ElevenLabs Scribe-compatible router."""
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes(frames: int = 160) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


class FakeModel:
    def process_audio(self, audio, lang: str = "auto") -> str:
        return "hello world"


@pytest.fixture(scope="module")
def client() -> TestClient:
    from ovos_stt_http_server.routers.elevenlabs_scribe import make_elevenlabs_scribe_router
    app = FastAPI()
    app.include_router(make_elevenlabs_scribe_router(FakeModel()))
    return TestClient(app)


PATH = "/elevenlabs/v1/speech-to-text"


class TestScribeRouter:
    def test_basic(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model_id": "scribe_v1"})
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "hello world"
        assert body["language_code"] == "en"
        assert isinstance(body["words"], list)

    def test_language_code_echoed(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model_id": "scribe_v1", "language_code": "pt"})
        assert r.status_code == 200
        assert r.json()["language_code"] == "pt"

    def test_api_key_header_accepted(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model_id": "scribe_v1"},
                        headers={"xi-api-key": "fake"})
        assert r.status_code == 200

    def test_model_id_defaulted(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")}, data={})
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"

    def test_empty_file_400(self, client):
        r = client.post(PATH, files={"file": ("a.wav", b"", "audio/wav")},
                        data={"model_id": "scribe_v1"})
        assert r.status_code == 400

    def test_raw_bytes_fallback(self, client):
        r = client.post(PATH, files={"file": ("a.raw", b"\x00\x00" * 160, "application/octet-stream")},
                        data={"model_id": "scribe_v1"})
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"
