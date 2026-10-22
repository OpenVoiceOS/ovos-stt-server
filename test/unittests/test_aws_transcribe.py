# Licensed under the Apache License, Version 2.0
"""Unit tests for the AWS Transcribe-compatible router (TestClient, no live SDK)."""
import base64
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_bytes(seconds: float = 0.1, sample_rate: int = 16000) -> bytes:
    """Build a minimal silent WAV blob."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


def _data_uri(wav: bytes) -> str:
    return "data:audio/wav;base64," + base64.b64encode(wav).decode()


class FakeModel:
    """Minimal STT stub that always returns 'hello world'."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        return "hello world"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    from ovos_stt_http_server.routers.aws_transcribe import make_aws_transcribe_router
    app = FastAPI()
    app.include_router(make_aws_transcribe_router(FakeModel()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Batch REST tests
# ---------------------------------------------------------------------------

class TestBatchActions:
    def test_start_job_inline_audio(self, client):
        wav = _wav_bytes()
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.StartTranscriptionJob"},
            json={
                "TranscriptionJobName": "unit-test-1",
                "LanguageCode": "en-US",
                "Media": {"MediaFileUri": _data_uri(wav)},
                "MediaFormat": "wav",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        job = body["TranscriptionJob"]
        assert job["TranscriptionJobStatus"] == "COMPLETED"
        assert job["TranscriptionJobName"] == "unit-test-1"
        assert "TranscriptFileUri" in job["Transcript"]
        # Private fields must be stripped
        assert "_text" not in job

    def test_start_job_no_audio_uri(self, client):
        """Omitting Media is valid — transcript is empty string."""
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.StartTranscriptionJob"},
            json={"TranscriptionJobName": "unit-no-audio"},
        )
        assert resp.status_code == 200
        job = resp.json()["TranscriptionJob"]
        assert job["TranscriptionJobStatus"] == "COMPLETED"

    def test_start_job_external_uri_not_fetched(self, client):
        """External S3-like URIs are accepted but not fetched (empty transcript)."""
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.StartTranscriptionJob"},
            json={
                "TranscriptionJobName": "unit-s3",
                "Media": {"MediaFileUri": "s3://bucket/audio.wav"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["TranscriptionJob"]["TranscriptionJobStatus"] == "COMPLETED"

    def test_get_job_found(self, client):
        # Ensure unit-test-1 exists from a prior test or create it
        client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.StartTranscriptionJob"},
            json={"TranscriptionJobName": "unit-get-1"},
        )
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.GetTranscriptionJob"},
            json={"TranscriptionJobName": "unit-get-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["TranscriptionJob"]["TranscriptionJobName"] == "unit-get-1"

    def test_get_job_not_found(self, client):
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.GetTranscriptionJob"},
            json={"TranscriptionJobName": "does-not-exist"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    def test_list_jobs(self, client):
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.ListTranscriptionJobs"},
            json={},
        )
        assert resp.status_code == 200
        summaries = resp.json()["TranscriptionJobSummaries"]
        assert isinstance(summaries, list)
        names = [s["TranscriptionJobName"] for s in summaries]
        assert "unit-test-1" in names or "unit-get-1" in names

    def test_delete_job(self, client):
        client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.StartTranscriptionJob"},
            json={"TranscriptionJobName": "unit-delete-me"},
        )
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.DeleteTranscriptionJob"},
            json={"TranscriptionJobName": "unit-delete-me"},
        )
        assert resp.status_code == 200
        # Confirm it's gone
        r2 = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.GetTranscriptionJob"},
            json={"TranscriptionJobName": "unit-delete-me"},
        )
        assert r2.status_code == 400

    def test_delete_nonexistent_job_is_noop(self, client):
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.DeleteTranscriptionJob"},
            json={"TranscriptionJobName": "ghost-job"},
        )
        assert resp.status_code == 200

    def test_unknown_action_returns_400(self, client):
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.NonExistentAction"},
            json={},
        )
        assert resp.status_code == 400
        assert "UnknownOperationException" in resp.json()["detail"]

    def test_missing_action_header_returns_400(self, client):
        resp = client.post("/aws/transcribe", json={})
        assert resp.status_code == 400

    def test_empty_body_dispatches_correctly(self, client):
        """Empty body should still dispatch when x-amz-target is valid."""
        resp = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.ListTranscriptionJobs"},
            content=b"",
        )
        assert resp.status_code == 200


class TestTranscriptResultEndpoint:
    def test_get_results_after_start(self, client):
        wav = _wav_bytes()
        start = client.post(
            "/aws/transcribe",
            headers={"x-amz-target": "Transcribe.StartTranscriptionJob"},
            json={
                "TranscriptionJobName": "unit-result-1",
                "LanguageCode": "en-US",
                "Media": {"MediaFileUri": _data_uri(wav)},
            },
        )
        assert start.status_code == 200

        resp = client.get("/aws/transcribe/results/unit-result-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["jobName"] == "unit-result-1"
        assert body["results"]["transcripts"][0]["transcript"] == "hello world"
        assert body["status"] == "COMPLETED"

    def test_get_results_unknown_job_returns_404(self, client):
        resp = client.get("/aws/transcribe/results/ghost-job-xyz")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket streaming tests
# ---------------------------------------------------------------------------

class TestStreamingWebSocket:
    def test_streaming_with_audio_and_empty_frame(self, client):
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
            "?language-code=en-US&sample-rate=16000"
        ) as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_bytes(b"")  # end-of-stream sentinel
            msg = json.loads(ws.receive_text())
        results = msg["Transcript"]["Results"]
        assert len(results) == 1
        alt = results[0]["Alternatives"][0]
        assert alt["Transcript"] == "hello world"
        assert results[0]["IsPartial"] is False

    def test_streaming_end_stream_json(self, client):
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
        ) as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text(json.dumps({"eventType": "EndStream"}))
            msg = json.loads(ws.receive_text())
        assert msg["Transcript"]["Results"][0]["Alternatives"][0]["Transcript"] == "hello world"

    def test_streaming_disconnect_without_end(self, client):
        """Client disconnect without end-of-stream must not raise server-side."""
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
        ) as ws:
            ws.send_bytes(_wav_bytes())
        # If we reach here without exception the server handled it cleanly.

    def test_streaming_no_audio_no_response(self, client):
        """Empty stream (no audio) should close without emitting a Transcript frame."""
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
        ) as ws:
            ws.send_bytes(b"")  # immediate end-of-stream, no audio
        # No data frame expected; clean close is the success criterion.

    def test_streaming_invalid_json_text_ignored(self, client):
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
        ) as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_text("not-valid-json")
            ws.send_text(json.dumps({"eventType": "EndStream"}))
            msg = json.loads(ws.receive_text())
        assert "Transcript" in msg

    def test_streaming_default_params(self, client):
        """Omitting query params should use defaults (sample-rate=16000, language=en-US)."""
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
        ) as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_bytes(b"")
            msg = json.loads(ws.receive_text())
        assert msg["Transcript"]["Results"][0]["Alternatives"][0]["Transcript"] == "hello world"

    def test_streaming_result_id_is_uuid(self, client):
        import re
        UUID_RE = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        with client.websocket_connect(
            "/aws/transcribestreaming/stream-transcription"
        ) as ws:
            ws.send_bytes(_wav_bytes())
            ws.send_bytes(b"")
            msg = json.loads(ws.receive_text())
        result_id = msg["Transcript"]["Results"][0]["ResultId"]
        assert UUID_RE.match(result_id), f"ResultId not a UUID: {result_id}"
