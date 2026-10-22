# Licensed under the Apache License, Version 2.0
"""Unit tests for the Gladia-compatible router (upload -> transcription -> poll)."""
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
    from ovos_stt_http_server.routers.gladia import make_gladia_router
    app = FastAPI()
    app.include_router(make_gladia_router(FakeModel()))
    return TestClient(app)


class TestGladiaRouter:
    def test_full_flow(self, client):
        # 1. upload
        up = client.post("/gladia/v2/upload",
                         files={"audio": ("a.wav", _wav_bytes(), "audio/wav")})
        assert up.status_code == 200
        audio_url = up.json()["audio_url"]
        assert "/gladia/v2/upload/" in audio_url

        # 2. request transcription (runs synchronously)
        tx = client.post("/gladia/v2/transcription", json={"audio_url": audio_url})
        assert tx.status_code == 201
        job = tx.json()
        assert "id" in job and "result_url" in job

        # 3. poll result — already done
        res = client.get(f"/gladia/v2/transcription/{job['id']}")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "done"
        assert body["result"]["transcription"]["full_transcript"] == "hello world"

    def test_unknown_audio_url_404(self, client):
        r = client.post("/gladia/v2/transcription",
                        json={"audio_url": "/gladia/v2/upload/does-not-exist"})
        assert r.status_code == 404

    def test_unknown_job_404(self, client):
        r = client.get("/gladia/v2/transcription/nope")
        assert r.status_code == 404

    def test_empty_upload_400(self, client):
        r = client.post("/gladia/v2/upload",
                        files={"audio": ("a.wav", b"", "audio/wav")})
        assert r.status_code == 400

    def test_gladia_key_header_accepted(self, client):
        up = client.post("/gladia/v2/upload",
                         files={"audio": ("a.wav", _wav_bytes(), "audio/wav")},
                         headers={"x-gladia-key": "fake"})
        assert up.status_code == 200
