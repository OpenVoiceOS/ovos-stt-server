# Licensed under the Apache License, Version 2.0
"""Unit tests for the Groq-compatible router (no live server, no API key)."""
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
    from ovos_stt_http_server.routers.groq import make_groq_router
    app = FastAPI()
    app.include_router(make_groq_router(FakeModel()))
    return TestClient(app)


PATH = "/groq/openai/v1/audio/transcriptions"


class TestGroqRouter:
    def test_json_default(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model": "whisper-large-v3"})
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "hello world"
        # the x_groq block is what distinguishes Groq from plain OpenAI
        assert "x_groq" in body and body["x_groq"]["id"].startswith("req_")

    def test_text_format(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model": "whisper-large-v3", "response_format": "text"})
        assert r.status_code == 200
        assert r.text == "hello world"

    def test_language_param(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model": "whisper-large-v3", "language": "pt"})
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"

    def test_bearer_header_accepted(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model": "whisper-large-v3"},
                        headers={"Authorization": "Bearer gsk_fake"})
        assert r.status_code == 200

    def test_empty_file_400(self, client):
        r = client.post(PATH, files={"file": ("a.wav", b"", "audio/wav")},
                        data={"model": "whisper-large-v3"})
        assert r.status_code == 400

    def test_missing_model_422(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")}, data={})
        assert r.status_code == 422

    def test_unknown_format_422(self, client):
        r = client.post(PATH, files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
                        data={"model": "whisper-large-v3", "response_format": "xml"})
        assert r.status_code == 422

    def test_raw_bytes_fallback(self, client):
        r = client.post(PATH, files={"file": ("a.raw", b"\x00\x00" * 160, "application/octet-stream")},
                        data={"model": "whisper-large-v3"})
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"
