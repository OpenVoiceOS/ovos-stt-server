# Licensed under the Apache License, Version 2.0
"""Unit tests for the Deepgram-compatible router (TestClient, no live SDK)."""
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes() -> bytes:
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


@pytest.fixture(scope="module")
def client() -> TestClient:
    from ovos_stt_http_server.routers.deepgram import make_deepgram_router
    app = FastAPI()
    app.include_router(make_deepgram_router(FakeModel()))
    return TestClient(app)


class TestDeepgramRest:
    def test_listen_returns_transcript(self, client):
        resp = client.post("/deepgram/v1/listen", content=_wav_bytes(),
                           params={"language": "en", "model": "nova-3", "punctuate": True})
        assert resp.status_code == 200
        body = resp.json()
        alt = body["results"]["channels"][0]["alternatives"][0]
        assert alt["transcript"] == "hello world"
        assert body["metadata"]["channels"] == 1

    def test_listen_empty_body(self, client):
        resp = client.post("/deepgram/v1/listen", content=b"")
        assert resp.status_code == 200


class TestDeepgramWebsocket:
    def test_streaming_results_and_metadata(self, client):
        with client.websocket_connect("/deepgram/v1/listen?language=en") as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text(json.dumps({"type": "KeepAlive"}))   # ignored, keeps socket
            ws.send_text("not-json")                          # JSONDecodeError branch
            ws.send_text(json.dumps({"type": "CloseStream"}))  # flush + close
            results = json.loads(ws.receive_text())
            metadata = json.loads(ws.receive_text())
        assert results["type"] == "Results"
        assert results["channel"]["alternatives"][0]["transcript"] == "hello world"
        assert results["is_final"] is True
        assert metadata["type"] == "Metadata"

    def test_streaming_disconnect_without_close(self, client):
        with client.websocket_connect("/deepgram/v1/listen") as ws:
            ws.send_bytes(_wav_bytes())
        # client disconnect (no CloseStream) must not raise on the server side


class _FrameCounter:
    """Model stub that reports what the engine received."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        return f"{audio.sample_rate}Hz {len(audio.frame_data) // audio.sample_width} samples"


def _tone_wav(rate: int, seconds: float = 0.5) -> bytes:
    import math
    from array import array
    pcm = array("h", (int(8000 * math.sin(2 * math.pi * 440 * n / rate)) for n in range(int(seconds * rate))))
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


@pytest.fixture(scope="module")
def counter_client() -> TestClient:
    from ovos_stt_http_server.routers.deepgram import make_deepgram_router
    app = FastAPI()
    app.include_router(make_deepgram_router(_FrameCounter()))
    return TestClient(app)


def _transcript(resp) -> str:
    return resp.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


def test_listen_reads_the_wav_header(counter_client):
    resp = counter_client.post("/deepgram/v1/listen", content=_tone_wav(48000),
                               headers={"Content-Type": "audio/wav"})
    assert _transcript(resp) == "48000Hz 24000 samples"


def test_listen_decodes_flac(counter_client):
    from pydub import AudioSegment
    flac = io.BytesIO()
    AudioSegment.from_wav(io.BytesIO(_tone_wav(16000))).export(flac, format="flac")
    resp = counter_client.post("/deepgram/v1/listen", content=flac.getvalue(),
                               headers={"Content-Type": "audio/flac"})
    assert _transcript(resp) == "16000Hz 8000 samples"
