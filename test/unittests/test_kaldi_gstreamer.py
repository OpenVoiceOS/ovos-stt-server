# Licensed under the Apache License, Version 2.0
"""Unit tests for the kaldi-gstreamer-compatible router.

Uses FastAPI's TestClient (+ websocket_connect) so no live server is
needed and no audio codec is required.
"""
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_bytes(seconds: float = 0.1, rate: int = 16000) -> bytes:
    """Return a minimal silent WAV byte-string."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class FakeModel:
    """Minimal STT model stub that always returns ``"hello world"``."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript regardless of audio content."""
        return "hello world"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Return a TestClient wrapping the kaldi-gstreamer router."""
    from ovos_stt_http_server.routers.kaldi_gstreamer import make_kaldi_gstreamer_router

    app = FastAPI()
    app.include_router(make_kaldi_gstreamer_router(FakeModel()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Speech WebSocket tests
# ---------------------------------------------------------------------------

class TestSpeechWS:
    """Tests for /client/ws/speech."""

    def test_transcript_partial_and_final(self, client):
        """Binary audio + EOS yields a partial frame then a final frame."""
        with client.websocket_connect("/client/ws/speech?lang=en") as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text("EOS")

            partial_raw = ws.receive_text()
            final_raw = ws.receive_text()

        partial = json.loads(partial_raw)
        final = json.loads(final_raw)

        # Both frames carry status 0
        assert partial["status"] == 0
        assert final["status"] == 0

        # Partial must have final=False
        assert partial["result"]["final"] is False
        assert partial["result"]["hypotheses"][0]["transcript"] == "hello world"

        # Final must have final=True
        assert final["result"]["final"] is True
        assert final["result"]["hypotheses"][0]["transcript"] == "hello world"

    def test_multiple_binary_chunks_are_buffered(self, client):
        """Audio split across multiple binary frames is concatenated before transcription."""
        wav = _wav_bytes()
        half = len(wav) // 2
        with client.websocket_connect("/client/ws/speech") as ws:
            ws.send_bytes(wav[:half])
            ws.send_bytes(wav[half:])
            ws.send_text("EOS")

            partial = json.loads(ws.receive_text())
            final = json.loads(ws.receive_text())

        assert partial["result"]["hypotheses"][0]["transcript"] == "hello world"
        assert final["result"]["final"] is True

    def test_unknown_text_frame_is_ignored(self, client):
        """Non-EOS text frames are silently discarded; EOS still triggers transcription."""
        with client.websocket_connect("/client/ws/speech") as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text("IGNORED_COMMAND")
            ws.send_text("EOS")

            partial = json.loads(ws.receive_text())
            final = json.loads(ws.receive_text())

        assert final["result"]["final"] is True

    def test_disconnect_without_eos(self, client):
        """Client disconnect without EOS must not raise on the server side."""
        with client.websocket_connect("/client/ws/speech") as ws:
            ws.send_bytes(_wav_bytes())
        # If the server raised, TestClient would propagate an exception here.

    def test_empty_buffer_no_result(self, client):
        """EOS with no audio data sent produces no frames (nothing to transcribe)."""
        with client.websocket_connect("/client/ws/speech") as ws:
            ws.send_text("EOS")
        # Server closes without emitting frames; TestClient should not hang.

    def test_lang_query_param_accepted(self, client):
        """The ``lang`` query parameter is accepted and forwarded to the model."""
        with client.websocket_connect("/client/ws/speech?lang=pt-PT") as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text("EOS")
            partial = json.loads(ws.receive_text())
            final = json.loads(ws.receive_text())
        assert final["result"]["final"] is True

    def test_result_hypotheses_structure(self, client):
        """Each hypotheses entry contains at least a ``transcript`` key."""
        with client.websocket_connect("/client/ws/speech") as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text("EOS")
            partial = json.loads(ws.receive_text())
            final = json.loads(ws.receive_text())

        for frame in (partial, final):
            hyps = frame["result"]["hypotheses"]
            assert isinstance(hyps, list)
            assert len(hyps) >= 1
            assert "transcript" in hyps[0]


# ---------------------------------------------------------------------------
# Status WebSocket tests
# ---------------------------------------------------------------------------

class TestStatusWS:
    """Tests for /client/ws/status."""

    def test_status_payload_keys(self, client):
        """Status endpoint emits the required capacity keys and closes."""
        with client.websocket_connect("/client/ws/status") as ws:
            raw = ws.receive_text()
        status = json.loads(raw)
        assert "num_workers_available" in status
        assert "num_requests_processed" in status

    def test_num_workers_available_positive(self, client):
        """num_workers_available must be at least 1 when the server is healthy."""
        with client.websocket_connect("/client/ws/status") as ws:
            status = json.loads(ws.receive_text())
        assert status["num_workers_available"] >= 1

    def test_num_requests_processed_is_int(self, client):
        """num_requests_processed must be a non-negative integer."""
        with client.websocket_connect("/client/ws/status") as ws:
            status = json.loads(ws.receive_text())
        assert isinstance(status["num_requests_processed"], int)
        assert status["num_requests_processed"] >= 0
