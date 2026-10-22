# Licensed under the Apache License, Version 2.0
"""Unit tests for the IBM Watson STT compatible router (TestClient, no live SDK)."""
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes() -> bytes:
    """Return a minimal valid WAV file (16kHz, 16-bit, mono, 160 samples)."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


class FakeModel:
    """Minimal OVOS STT plugin stub."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript for any audio input."""
        return "hello world"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient with the IBM Watson router mounted on a bare FastAPI app."""
    from ovos_stt_http_server.routers.ibm_watson_stt import make_ibm_watson_stt_router

    app = FastAPI()
    app.include_router(make_ibm_watson_stt_router(FakeModel()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------

class TestIBMWatsonRest:
    """Tests for POST /watson/speech-to-text/v1/recognize (synchronous REST)."""

    def test_recognize_returns_transcript(self, client):
        """Happy-path: WAV body returns 'hello world' in Watson format."""
        resp = client.post(
            "/watson/speech-to-text/v1/recognize",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["results"][0]["alternatives"][0]["transcript"] == "hello world"
        assert body["results"][0]["final"] is True
        assert body["result_index"] == 0

    def test_recognize_empty_body(self, client):
        """Empty body is accepted without 500."""
        resp = client.post("/watson/speech-to-text/v1/recognize", content=b"")
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert "result_index" in body

    def test_recognize_model_query_param_accepted(self, client):
        """model= query param is accepted without error."""
        resp = client.post(
            "/watson/speech-to-text/v1/recognize?model=en-US_BroadbandModel",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        assert resp.status_code == 200

    def test_recognize_auth_header_ignored(self, client):
        """Authorization header is accepted and silently ignored."""
        resp = client.post(
            "/watson/speech-to-text/v1/recognize",
            content=_wav_bytes(),
            headers={
                "Content-Type": "audio/wav",
                "Authorization": "Bearer fake-api-key",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["results"][0]["alternatives"][0]["transcript"] == "hello world"

    def test_recognize_language_customization_id_ignored(self, client):
        """language_customization_id query param is accepted without error."""
        resp = client.post(
            "/watson/speech-to-text/v1/recognize?language_customization_id=abc-123",
            content=_wav_bytes(),
        )
        assert resp.status_code == 200

    def test_response_structure_complete(self, client):
        """Response has all required IBM Watson envelope fields."""
        resp = client.post("/watson/speech-to-text/v1/recognize", content=_wav_bytes())
        body = resp.json()
        assert isinstance(body["results"], list)
        assert len(body["results"]) == 1
        assert isinstance(body["results"][0]["alternatives"], list)
        assert len(body["results"][0]["alternatives"]) == 1
        assert "confidence" in body["results"][0]["alternatives"][0]


# ---------------------------------------------------------------------------
# WebSocket endpoint tests
# ---------------------------------------------------------------------------

class TestIBMWatsonWebSocket:
    """Tests for WS /watson/speech-to-text/v1/recognize (streaming WebSocket)."""

    def test_initial_listening_on_connect(self, client):
        """Server immediately sends listening state upon connection."""
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            ack = json.loads(ws.receive_text())
            assert ack == {"state": "listening"}
            ws.send_text(json.dumps({"action": "stop"}))

    def test_start_stop_returns_transcript(self, client):
        """Standard start/audio/stop flow returns transcript and closing state."""
        wav = _wav_bytes()
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            # 1. Receive initial listening
            ack = json.loads(ws.receive_text())
            assert ack == {"state": "listening"}

            # 2. Send start action
            ws.send_text(json.dumps({
                "action": "start",
                "content-type": "audio/l16;rate=16000",
                "model": "en-US_BroadbandModel",
            }))

            # 3. Stream audio
            ws.send_bytes(wav)

            # 4. Stop
            ws.send_text(json.dumps({"action": "stop"}))

            # 5. Receive transcript result
            result_msg = json.loads(ws.receive_text())
            assert "results" in result_msg
            assert result_msg["results"][0]["alternatives"][0]["transcript"] == "hello world"
            assert result_msg["results"][0]["final"] is True

            # 6. Receive closing "listening" state
            closing = json.loads(ws.receive_text())
            assert closing == {"state": "listening"}

    def test_disconnect_without_stop_no_server_error(self, client):
        """Abrupt disconnect (no stop action) must not raise on server side."""
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            _ack = ws.receive_text()
            ws.send_text(json.dumps({"action": "start", "content-type": "audio/wav"}))
            ws.send_bytes(_wav_bytes())
        # Reaching here without exception means server handled disconnect gracefully.

    def test_bad_json_text_ignored(self, client):
        """Non-JSON text frames are silently ignored."""
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            _ack = ws.receive_text()
            ws.send_text(json.dumps({"action": "start"}))
            ws.send_text("not-valid-json")
            ws.send_bytes(_wav_bytes())
            ws.send_text(json.dumps({"action": "stop"}))
            result_msg = json.loads(ws.receive_text())
        assert result_msg["results"][0]["alternatives"][0]["transcript"] == "hello world"

    def test_audio_before_start_ignored(self, client):
        """Binary frames received before the start action are silently dropped."""
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            _ack = ws.receive_text()
            # Audio before start is ignored
            ws.send_bytes(_wav_bytes())
            ws.send_text(json.dumps({"action": "start"}))
            # No audio was buffered after start, so results are skipped
            ws.send_text(json.dumps({"action": "stop"}))
            closing = json.loads(ws.receive_text())
        assert closing == {"state": "listening"}

    def test_content_type_rate_parsed(self, client):
        """Start action content-type with rate= is parsed without error."""
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            _ack = ws.receive_text()
            ws.send_text(json.dumps({
                "action": "start",
                "content-type": "audio/l16;rate=8000",
            }))
            ws.send_bytes(_wav_bytes())
            ws.send_text(json.dumps({"action": "stop"}))
            result_msg = json.loads(ws.receive_text())
        assert result_msg["results"][0]["alternatives"][0]["transcript"] == "hello world"

    def test_invalid_rate_falls_back_to_default(self, client):
        """Unparseable rate= value is silently ignored, defaulting to 16000."""
        with client.websocket_connect("/watson/speech-to-text/v1/recognize") as ws:
            _ack = ws.receive_text()
            ws.send_text(json.dumps({
                "action": "start",
                "content-type": "audio/l16;rate=not-a-number",
            }))
            ws.send_bytes(_wav_bytes())
            ws.send_text(json.dumps({"action": "stop"}))
            result_msg = json.loads(ws.receive_text())
        assert result_msg["results"][0]["alternatives"][0]["transcript"] == "hello world"
