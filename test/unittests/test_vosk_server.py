# Licensed under the Apache License, Version 2.0
"""Unit tests for the vosk-server-compatible WebSocket router (TestClient, no live server)."""
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _pcm_bytes(sample_rate: int = 16000, frames: int = 160) -> bytes:
    """Return minimal silent raw 16-bit mono PCM."""
    return b"\x00\x00" * frames


def _wav_bytes(sample_rate: int = 16000, frames: int = 160) -> bytes:
    """Return minimal silent WAV (for generic audio input)."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


class FakeModel:
    """Stub OVOS STT plugin that always returns 'hello world'."""

    def process_audio(self, audio, lang: str = "en") -> str:
        """Return a fixed transcript regardless of audio content."""
        return "hello world"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """FastAPI TestClient wired to the vosk-server router with a FakeModel."""
    from ovos_stt_http_server.routers.vosk_server import make_vosk_server_router
    app = FastAPI()
    app.include_router(make_vosk_server_router(FakeModel()))
    return TestClient(app)


class TestVoskServerProtocol:
    """Tests covering the vosk-server WebSocket wire protocol."""

    def test_full_protocol_config_audio_eof(self, client):
        """Happy-path: config frame → binary audio → eof → final text."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_text(json.dumps({"config": {"sample_rate": 16000}}))
            ws.send_bytes(_pcm_bytes())
            # Consume the partial emitted after the audio frame.
            partial = json.loads(ws.receive_text())
            assert "partial" in partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert result["text"] == "hello world"

    def test_trailing_slash_path(self, client):
        """Both /vosk and /vosk/ must be served."""
        with client.websocket_connect("/vosk/") as ws:
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert result["text"] == "hello world"

    def test_config_frame_updates_sample_rate(self, client):
        """Config frame with custom sample_rate is accepted without error."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_text(json.dumps({"config": {"sample_rate": 8000}}))
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert "text" in result

    def test_invalid_config_sample_rate_falls_back_to_default(self, client):
        """Non-numeric sample_rate in config must not crash; server continues."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_text(json.dumps({"config": {"sample_rate": "bad"}}))
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert "text" in result

    def test_config_null_inner_dict(self, client):
        """Config frame with null value must not crash."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_text(json.dumps({"config": None}))
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert "text" in result

    def test_non_json_text_frame_ignored(self, client):
        """Malformed JSON text frames must be silently ignored."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_text("not-json-at-all")
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert "text" in result

    def test_non_dict_json_text_frame_ignored(self, client):
        """JSON arrays / scalars in text frames must be silently ignored."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_text(json.dumps([1, 2, 3]))
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert "text" in result

    def test_eof_without_audio_no_crash(self, client):
        """eof on an empty buffer must not crash — no text frame expected."""
        # With no audio, the router skips the send and just closes.
        with client.websocket_connect("/vosk") as ws:
            ws.send_text(json.dumps({"eof": 1}))

    def test_multiple_audio_frames(self, client):
        """Multiple binary frames are buffered and transcribed together."""
        with client.websocket_connect("/vosk") as ws:
            for _ in range(3):
                ws.send_bytes(_pcm_bytes(frames=80))
                ws.receive_text()  # partial after each frame
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert result["text"] == "hello world"

    def test_disconnect_without_eof(self, client):
        """Client disconnect without eof must not raise on the server side."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # partial
        # If we reach here without exception, the server handled disconnect cleanly.

    def test_partial_reply_content(self, client):
        """Partial replies after each audio frame must have the 'partial' key."""
        with client.websocket_connect("/vosk") as ws:
            ws.send_bytes(_pcm_bytes())
            partial = json.loads(ws.receive_text())
            assert "partial" in partial
            assert isinstance(partial["partial"], str)
            ws.send_text(json.dumps({"eof": 1}))
            result = json.loads(ws.receive_text())
        assert result["text"] == "hello world"
