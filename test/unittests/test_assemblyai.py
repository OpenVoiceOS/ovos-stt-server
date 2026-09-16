# Licensed under the Apache License, Version 2.0
"""Unit tests for the AssemblyAI-compatible router (TestClient, no live SDK)."""
import base64
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes() -> bytes:
    """Return minimal valid WAV bytes (1-channel, 16-bit, 16 kHz, 160 frames)."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


class FakeModel:
    """Minimal STT model stub that always returns 'hello world'."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript regardless of audio content."""
        return "hello world"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Build a FastAPI app with the AssemblyAI router and return a TestClient."""
    from ovos_stt_http_server.routers.assemblyai import make_assemblyai_router

    app = FastAPI()
    app.include_router(make_assemblyai_router(FakeModel()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /assemblyai/v2/upload
# ---------------------------------------------------------------------------

class TestUpload:
    def test_upload_returns_upload_url(self, client):
        """Upload endpoint must return a JSON body with an upload_url field."""
        resp = client.post("/assemblyai/v2/upload", content=_wav_bytes())
        assert resp.status_code == 200
        body = resp.json()
        assert "upload_url" in body
        assert "/assemblyai/v2/uploads/" in body["upload_url"]

    def test_upload_url_contains_uuid(self, client):
        """Each upload returns a distinct URL containing a UUID-like path segment."""
        r1 = client.post("/assemblyai/v2/upload", content=b"audio1")
        r2 = client.post("/assemblyai/v2/upload", content=b"audio2")
        assert r1.json()["upload_url"] != r2.json()["upload_url"]


# ---------------------------------------------------------------------------
# POST /assemblyai/v2/transcript
# ---------------------------------------------------------------------------

class TestCreateTranscriptErrors:
    def test_invalid_base64_returns_error(self, client):
        """Supplying malformed base64 in 'audio' must return status=error."""
        resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio": "!!!not-base64!!!"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"


class TestCreateTranscript:
    def test_base64_audio(self, client):
        """Inline base64 audio in the 'audio' field must be transcribed."""
        encoded = base64.b64encode(_wav_bytes()).decode()
        resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio": encoded, "language_code": "en"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["text"] == "hello world"
        assert body["language_code"] == "en"
        assert "id" in body

    def test_audio_url_pointing_at_upload(self, client):
        """SDK two-step flow: upload then reference via audio_url must work."""
        upload_resp = client.post("/assemblyai/v2/upload", content=_wav_bytes())
        upload_url = upload_resp.json()["upload_url"]

        resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio_url": upload_url},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["text"] == "hello world"

    def test_missing_audio_returns_error(self, client):
        """No audio field and no audio_url must return status=error."""
        resp = client.post("/assemblyai/v2/transcript", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "external" in body["error"].lower() or "not supported" in body["error"].lower()

    def test_unknown_upload_id_returns_error(self, client):
        """Referencing a non-existent upload ID must return status=error."""
        fake_url = "http://testserver/assemblyai/v2/uploads/00000000-0000-0000-0000-000000000000"
        resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio_url": fake_url},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "unknown upload id" in body["error"].lower()

    def test_external_audio_url_returns_error(self, client):
        """A non-upload audio_url (external) must return an error, not a crash."""
        resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio_url": "https://example.com/audio.wav"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"

    def test_transcript_stored_by_id(self, client):
        """A completed transcript must be retrievable by its ID."""
        encoded = base64.b64encode(_wav_bytes()).decode()
        create_resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio": encoded},
        )
        transcript_id = create_resp.json()["id"]

        get_resp = client.get(f"/assemblyai/v2/transcript/{transcript_id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["id"] == transcript_id
        assert body["status"] == "completed"

    def test_non_wav_audio_falls_back_to_raw(self, client):
        """Non-WAV bytes must not crash; fallback to raw AudioData is fine."""
        encoded = base64.b64encode(b"\xff\xfe" * 100).decode()
        resp = client.post(
            "/assemblyai/v2/transcript",
            json={"audio": encoded},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"


# ---------------------------------------------------------------------------
# GET /assemblyai/v2/transcript/{id}
# ---------------------------------------------------------------------------

class TestGetTranscript:
    def test_found(self, client):
        """GET by a previously created transcript ID returns the stored record."""
        encoded = base64.b64encode(_wav_bytes()).decode()
        create = client.post(
            "/assemblyai/v2/transcript",
            json={"audio": encoded},
        )
        tid = create.json()["id"]

        resp = client.get(f"/assemblyai/v2/transcript/{tid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == tid
        assert resp.json()["status"] == "completed"

    def test_not_found(self, client):
        """GET with an unknown ID returns status=error."""
        resp = client.get("/assemblyai/v2/transcript/does-not-exist")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert body["id"] == "does-not-exist"


# ---------------------------------------------------------------------------
# WebSocket /assemblyai/v2/realtime/ws  (legacy v2 endpoint)
# ---------------------------------------------------------------------------

class TestRealtimeWsV2:
    def test_session_begins_on_connect(self, client):
        """Server sends SessionBegins immediately after handshake."""
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["message_type"] == "SessionBegins"
            assert "session_id" in msg
            ws.send_text(json.dumps({"terminate_session": True}))

    def test_audio_frames_produce_final_transcript(self, client):
        """Binary audio frames followed by terminate_session must yield FinalTranscript."""
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            ws.receive_text()  # SessionBegins
            ws.send_bytes(b"\x00\x00" * 1600)
            ws.send_text(json.dumps({"terminate_session": True}))
            final = json.loads(ws.receive_text())
            assert final["message_type"] == "FinalTranscript"
            assert final["text"] == "hello world"
            session_terminated = json.loads(ws.receive_text())
            assert session_terminated["message_type"] == "SessionTerminated"

    def test_base64_audio_data_in_json(self, client):
        """Audio sent as JSON audio_data (base64) must also be buffered."""
        audio_b64 = base64.b64encode(b"\x00\x00" * 800).decode()
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            ws.receive_text()  # SessionBegins
            ws.send_text(json.dumps({"audio_data": audio_b64}))
            ws.send_text(json.dumps({"terminate_session": True}))
            final = json.loads(ws.receive_text())
            assert final["message_type"] == "FinalTranscript"

    def test_force_end_utterance_flushes(self, client):
        """force_end_utterance breaks the loop like terminate_session."""
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            ws.receive_text()  # SessionBegins
            ws.send_bytes(b"\x00\x00" * 160)
            ws.send_text(json.dumps({"force_end_utterance": True}))
            final = json.loads(ws.receive_text())
            assert final["message_type"] == "FinalTranscript"

    def test_disconnect_without_terminate_does_not_raise(self, client):
        """Abrupt disconnect (no terminate_session) must not raise on server side."""
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            ws.receive_text()  # SessionBegins
            ws.send_bytes(b"\x00\x00" * 160)
        # No assertion needed; success = no exception propagated

    def test_invalid_json_text_ignored(self, client):
        """Non-JSON text frames must be silently ignored."""
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            ws.receive_text()  # SessionBegins
            ws.send_bytes(b"\x00\x00" * 160)
            ws.send_text("not valid json")
            ws.send_text(json.dumps({"terminate_session": True}))
            final = json.loads(ws.receive_text())
            assert final["message_type"] == "FinalTranscript"

    def test_invalid_base64_audio_data_ignored(self, client):
        """A malformed base64 string in audio_data JSON must be silently ignored."""
        with client.websocket_connect("/assemblyai/v2/realtime/ws") as ws:
            ws.receive_text()  # SessionBegins
            ws.send_bytes(b"\x00\x00" * 160)  # valid audio so buffer is non-empty
            ws.send_text(json.dumps({"audio_data": "!!!not-base64!!!"}))
            ws.send_text(json.dumps({"terminate_session": True}))
            final = json.loads(ws.receive_text())
            assert final["message_type"] == "FinalTranscript"


# ---------------------------------------------------------------------------
# WebSocket /assemblyai/v3/ws  (Universal-Streaming v3)
# ---------------------------------------------------------------------------

class TestStreamingWsV3:
    def test_begin_on_connect(self, client):
        """Server sends Begin message immediately after accepting the v3 socket."""
        with client.websocket_connect("/assemblyai/v3/ws") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "Begin"
            assert "id" in msg
            assert "expires_at" in msg
            ws.send_text(json.dumps({"type": "Terminate"}))

    def test_binary_frames_plus_terminate(self, client):
        """Binary PCM frames followed by Terminate must yield Turn + Termination."""
        with client.websocket_connect("/assemblyai/v3/ws") as ws:
            ws.receive_text()  # Begin
            ws.send_bytes(b"\x00\x00" * 1600)
            ws.send_text(json.dumps({"type": "Terminate"}))
            turn = json.loads(ws.receive_text())
            termination = json.loads(ws.receive_text())
        assert turn["type"] == "Turn"
        assert turn["transcript"] == "hello world"
        assert turn["end_of_turn"] is True
        assert termination["type"] == "Termination"

    def test_keepalive_text_frame_ignored(self, client):
        """KeepAlive (or any non-Terminate) JSON frame must be silently ignored."""
        with client.websocket_connect("/assemblyai/v3/ws") as ws:
            ws.receive_text()  # Begin
            ws.send_bytes(b"\x00\x00" * 160)
            ws.send_text(json.dumps({"type": "KeepAlive"}))
            ws.send_text(json.dumps({"type": "Terminate"}))
            turn = json.loads(ws.receive_text())
            termination = json.loads(ws.receive_text())
        assert turn["type"] == "Turn"
        assert termination["type"] == "Termination"

    def test_disconnect_without_terminate(self, client):
        """Abrupt disconnect must not raise on server side."""
        with client.websocket_connect("/assemblyai/v3/ws") as ws:
            ws.receive_text()  # Begin
            ws.send_bytes(b"\x00\x00" * 160)
        # Success = no exception propagated

    def test_invalid_json_in_v3_ignored(self, client):
        """Non-JSON text frames in v3 must be silently ignored."""
        with client.websocket_connect("/assemblyai/v3/ws") as ws:
            ws.receive_text()  # Begin
            ws.send_bytes(b"\x00\x00" * 160)
            ws.send_text("not valid json at all")
            ws.send_text(json.dumps({"type": "Terminate"}))
            turn = json.loads(ws.receive_text())
            termination = json.loads(ws.receive_text())
        assert turn["type"] == "Turn"
        assert termination["type"] == "Termination"

    def test_empty_buffer_still_sends_turn(self, client):
        """Terminating immediately (no audio) must still emit a Turn+Termination."""
        with client.websocket_connect("/assemblyai/v3/ws") as ws:
            ws.receive_text()  # Begin
            ws.send_text(json.dumps({"type": "Terminate"}))
            turn = json.loads(ws.receive_text())
            termination = json.loads(ws.receive_text())
        assert turn["type"] == "Turn"
        assert turn["transcript"] == ""
        assert termination["type"] == "Termination"
