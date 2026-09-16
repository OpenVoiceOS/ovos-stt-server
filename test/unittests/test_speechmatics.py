# Licensed under the Apache License, Version 2.0
"""Unit tests for the Speechmatics-compatible router (TestClient, no live SDK).

Covers:
- Batch REST: submit_job, get_job_status, get_transcript, delete_job, list_jobs
- Realtime WebSocket: full handshake, audio streaming, transcript delivery
- Edge cases: missing jobs, empty audio, disconnect without EndOfStream
"""
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ovos_stt_http_server.routers.speechmatics import make_speechmatics_router, _JOB_STORE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_bytes(seconds: float = 0.05, sample_rate: int = 16000) -> bytes:
    """Return minimal silent WAV audio bytes for test fixtures."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


def _pcm_bytes(frames: int = 160) -> bytes:
    """Return raw PCM bytes (silence) for WebSocket binary frames."""
    return b"\x00\x00" * frames


class FakeModel:
    """Stub STT model that always returns 'hello world'."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript for any audio input."""
        return "hello world"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient wired to a fresh Speechmatics router."""
    app = FastAPI()
    app.include_router(make_speechmatics_router(FakeModel()))
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_job_store():
    """Wipe the in-memory job store before each test."""
    _JOB_STORE.clear()
    yield
    _JOB_STORE.clear()


# ---------------------------------------------------------------------------
# Batch REST
# ---------------------------------------------------------------------------

class TestBatchSubmitJob:
    def test_submit_multipart_returns_201_with_id(self, client):
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        resp = client.post(
            "/speechmatics/v2/jobs",
            files={
                "data_file": ("audio.wav", _wav_bytes(), "audio/wav"),
                "config": (None, cfg, "application/json"),
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert len(body["id"]) > 0

    def test_submit_stores_transcript(self, client):
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        resp = client.post(
            "/speechmatics/v2/jobs",
            files={
                "data_file": ("audio.wav", _wav_bytes(), "audio/wav"),
                "config": (None, cfg, "application/json"),
            },
        )
        job_id = resp.json()["id"]
        assert _JOB_STORE[job_id]["transcript"] == "hello world"

    def test_submit_no_audio_stores_empty_transcript(self, client):
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        resp = client.post(
            "/speechmatics/v2/jobs",
            files={"config": (None, cfg, "application/json")},
        )
        assert resp.status_code == 201
        job_id = resp.json()["id"]
        assert _JOB_STORE[job_id]["transcript"] == ""

    def test_submit_raw_body_returns_201(self, client):
        resp = client.post(
            "/speechmatics/v2/jobs",
            content=_wav_bytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert resp.status_code == 201

    def test_submit_malformed_config_fallback_to_english(self, client):
        resp = client.post(
            "/speechmatics/v2/jobs",
            files={
                "data_file": ("a.wav", _wav_bytes(), "audio/wav"),
                "config": (None, "not-json", "application/json"),
            },
        )
        assert resp.status_code == 201
        job_id = resp.json()["id"]
        assert _JOB_STORE[job_id]["language"] == "en"


class TestBatchJobStatus:
    def _submit(self, client) -> str:
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        return client.post(
            "/speechmatics/v2/jobs",
            files={
                "data_file": ("a.wav", _wav_bytes(), "audio/wav"),
                "config": (None, cfg, "application/json"),
            },
        ).json()["id"]

    def test_status_done(self, client):
        job_id = self._submit(client)
        resp = client.get(f"/speechmatics/v2/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["job"]["status"] == "done"

    def test_status_not_found(self, client):
        resp = client.get("/speechmatics/v2/jobs/doesnotexist")
        assert resp.status_code == 404

    def test_list_jobs_contains_submitted(self, client):
        job_id = self._submit(client)
        resp = client.get("/speechmatics/v2/jobs")
        assert resp.status_code == 200
        body = resp.json()
        assert "jobs" in body
        ids = [j["id"] for j in body["jobs"]]
        assert job_id in ids


class TestBatchTranscript:
    def _submit(self, client) -> str:
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        return client.post(
            "/speechmatics/v2/jobs",
            files={
                "data_file": ("a.wav", _wav_bytes(), "audio/wav"),
                "config": (None, cfg, "application/json"),
            },
        ).json()["id"]

    def test_get_transcript_words(self, client):
        job_id = self._submit(client)
        resp = client.get(f"/speechmatics/v2/jobs/{job_id}/transcript")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job"]["id"] == job_id
        assert body["job"]["status"] == "done"
        # "hello world" → 2 word results
        assert len(body["results"]) == 2

    def test_get_transcript_not_found(self, client):
        resp = client.get("/speechmatics/v2/jobs/ghost/transcript")
        assert resp.status_code == 404

    def test_get_transcript_empty_audio_has_no_results(self, client):
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        job_id = client.post(
            "/speechmatics/v2/jobs",
            files={"config": (None, cfg, "application/json")},
        ).json()["id"]
        resp = client.get(f"/speechmatics/v2/jobs/{job_id}/transcript")
        assert resp.status_code == 200
        assert resp.json()["results"] == []


class TestBatchDeleteJob:
    def _submit(self, client) -> str:
        cfg = json.dumps({"transcription_config": {"language": "en"}})
        return client.post(
            "/speechmatics/v2/jobs",
            files={
                "data_file": ("a.wav", _wav_bytes(), "audio/wav"),
                "config": (None, cfg, "application/json"),
            },
        ).json()["id"]

    def test_delete_existing_job(self, client):
        job_id = self._submit(client)
        resp = client.delete(f"/speechmatics/v2/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert job_id not in _JOB_STORE

    def test_delete_missing_job_returns_404(self, client):
        resp = client.delete("/speechmatics/v2/jobs/ghost")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Realtime WebSocket
# ---------------------------------------------------------------------------

class TestRealtimeWebSocket:
    def test_full_handshake_and_transcript(self, client):
        """Full happy-path: StartRecognition → audio → EndOfStream → transcript."""
        with client.websocket_connect("/speechmatics/v2/rt/en") as ws:
            # Send StartRecognition
            ws.send_text(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": {"language": "en"},
            }))
            started = json.loads(ws.receive_text())
            assert started["message"] == "RecognitionStarted"
            assert "id" in started
            assert "language_pack_info" in started

            # Send a binary audio chunk
            ws.send_bytes(_pcm_bytes())
            audio_added = json.loads(ws.receive_text())
            assert audio_added["message"] == "AudioAdded"
            assert audio_added["seq_no"] == 1

            # End the stream
            ws.send_text(json.dumps({"message": "EndOfStream", "last_seq_no": 1}))
            add_transcript = json.loads(ws.receive_text())
            assert add_transcript["message"] == "AddTranscript"
            metadata = add_transcript.get("metadata", {})
            assert "hello world" in metadata.get("transcript", "")

            end = json.loads(ws.receive_text())
            assert end["message"] == "EndOfTranscript"

    def test_no_audio_empty_transcript(self, client):
        """EndOfStream with no audio → empty transcript, EndOfTranscript still sent."""
        with client.websocket_connect("/speechmatics/v2/rt/en") as ws:
            ws.send_text(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": {"language": "en"},
            }))
            ws.receive_text()  # RecognitionStarted

            ws.send_text(json.dumps({"message": "EndOfStream", "last_seq_no": 0}))
            add_transcript = json.loads(ws.receive_text())
            assert add_transcript["message"] == "AddTranscript"
            assert add_transcript["results"] == []

            end = json.loads(ws.receive_text())
            assert end["message"] == "EndOfTranscript"

    def test_multiple_audio_chunks(self, client):
        """Multiple binary frames each get an AudioAdded ack with incrementing seq_no."""
        with client.websocket_connect("/speechmatics/v2/rt/fr") as ws:
            ws.send_text(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": {"language": "fr"},
            }))
            ws.receive_text()  # RecognitionStarted

            for expected_seq in range(1, 4):
                ws.send_bytes(_pcm_bytes(80))
                ack = json.loads(ws.receive_text())
                assert ack["message"] == "AudioAdded"
                assert ack["seq_no"] == expected_seq

            ws.send_text(json.dumps({"message": "EndOfStream", "last_seq_no": 3}))
            ws.receive_text()  # AddTranscript
            end = json.loads(ws.receive_text())
            assert end["message"] == "EndOfTranscript"

    def test_set_recognition_config_accepted_silently(self, client):
        """SetRecognitionConfig messages are accepted without a response."""
        with client.websocket_connect("/speechmatics/v2/rt/en") as ws:
            ws.send_text(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": {"language": "en"},
            }))
            ws.receive_text()  # RecognitionStarted

            # SetRecognitionConfig should not trigger a response
            ws.send_text(json.dumps({
                "message": "SetRecognitionConfig",
                "transcription_config": {"language": "en"},
            }))

            ws.send_text(json.dumps({"message": "EndOfStream", "last_seq_no": 0}))
            add_transcript = json.loads(ws.receive_text())
            assert add_transcript["message"] == "AddTranscript"
            ws.receive_text()  # EndOfTranscript

    def test_disconnect_before_end_of_stream(self, client):
        """Client disconnect (no EndOfStream) must not raise server-side."""
        with client.websocket_connect("/speechmatics/v2/rt/en") as ws:
            ws.send_text(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": {"language": "en"},
            }))
            ws.receive_text()  # RecognitionStarted
            ws.send_bytes(_pcm_bytes())
            ws.receive_text()  # AudioAdded
        # Implicit disconnect — server must handle cleanly (no exception)

    def test_language_from_url_path(self, client):
        """Language code in the URL path is used for transcription routing."""
        with client.websocket_connect("/speechmatics/v2/rt/pt") as ws:
            ws.send_text(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": {"language": "pt"},
            }))
            started = json.loads(ws.receive_text())
            assert started["message"] == "RecognitionStarted"
            assert started["language_pack_info"]["language_description"] == "pt"
            ws.send_text(json.dumps({"message": "EndOfStream", "last_seq_no": 0}))
            ws.receive_text()
            ws.receive_text()
