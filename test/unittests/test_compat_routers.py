# Licensed under the Apache License, Version 2.0
"""Unit tests for the Chromium / Chrome Web Speech API compat router."""
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


class FakeModel:
    def process_audio(self, audio, lang: str = "auto") -> str:
        return "hello world"


class FakeEmptyModel:
    def process_audio(self, audio, lang: str = "auto") -> str:
        return ""


@pytest.fixture(scope="module")
def model():
    return FakeModel()


def _make_app(model) -> FastAPI:
    from ovos_stt_http_server.routers.chromium import make_chromium_router
    app = FastAPI()
    app.include_router(make_chromium_router(model))
    return app


@pytest.fixture(scope="module")
def client(model):
    return TestClient(_make_app(model))


@pytest.fixture(scope="module")
def wav_bytes():
    return _make_wav_bytes()


class TestChromiumRouter:
    def test_recognize_wav(self, client, wav_bytes):
        r = client.post(
            "/speech-api/v2/recognize?client=chromium&lang=en-US&key=fake&pFilter=0",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        assert r.status_code == 200
        # Two newline-delimited JSON objects, per the Chrome wire format
        lines = [l for l in r.text.split("\n") if l]
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"result": []}
        second = json.loads(lines[1])
        assert second["result_index"] == 0
        alt = second["result"][0]["alternative"][0]
        assert alt["transcript"] == "hello world"
        assert second["result"][0]["final"] is True

    def test_recognize_raw_pcm(self, client):
        raw = b"\x00\x00" * 1600
        r = client.post(
            "/speech-api/v2/recognize?lang=en-US",
            content=raw,
            headers={"Content-Type": "audio/x-raw; rate=16000; bits=16"},
        )
        assert r.status_code == 200
        lines = [l for l in r.text.split("\n") if l]
        assert json.loads(lines[1])["result"][0]["alternative"][0]["transcript"] == \
            "hello world"

    def test_empty_transcript_returns_empty_first_line_only(self, wav_bytes):
        """Empty transcription returns just `{"result":[]}` — no second line."""
        app = FastAPI()
        from ovos_stt_http_server.routers.chromium import make_chromium_router
        app.include_router(make_chromium_router(FakeEmptyModel()))
        c = TestClient(app)
        r = c.post(
            "/speech-api/v2/recognize",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        lines = [l for l in r.text.split("\n") if l]
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"result": []}

    def test_default_key_accepted(self, client, wav_bytes):
        """No key query param — still works (key is accepted-and-ignored)."""
        r = client.post(
            "/speech-api/v2/recognize?lang=en-US",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        assert r.status_code == 200
