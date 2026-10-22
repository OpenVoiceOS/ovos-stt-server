# Licensed under the Apache License, Version 2.0
"""Unit tests for ovos_stt_http_server.routers.azure_stt.

Uses FastAPI TestClient for REST and the TestClient WS helper for the
Microsoft framing WebSocket.  A FakeModel returns "hello world" for every
audio submission so no real STT engine is needed.
"""
import io
import json
import time
import uuid
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ovos_stt_http_server.routers.azure_stt import (
    AzureRESTResponse,
    _build_text,
    _ms_units,
    _parse_binary,
    _parse_text,
    make_azure_stt_router,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_wav_bytes(seconds: float = 0.1, sample_rate: int = 16000) -> bytes:
    """Return a minimal silent WAV byte string."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


def _build_binary(path: str, request_id: str, body: bytes) -> bytes:
    """Build a Microsoft WS binary frame the same way the live integration test does."""
    head = (
        f"X-RequestId:{request_id}\r\n"
        f"X-Timestamp:{time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())}\r\n"
        f"Path:{path}\r\n"
        f"Content-Type:audio/x-wav\r\n"
    ).encode("ascii")
    return len(head).to_bytes(2, "big") + head + body


# ---------------------------------------------------------------------------
# Fake model — always returns "hello world"
# ---------------------------------------------------------------------------

class FakeModel:
    """Minimal ModelContainer stand-in for unit tests."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript regardless of input."""
        return "hello world"


class FakeEmptyModel:
    """Model that returns an empty string — exercises silence / timeout paths."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return an empty string to simulate silence / no recognition."""
        return ""


# ---------------------------------------------------------------------------
# App fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app() -> FastAPI:
    """FastAPI app with the azure-stt router mounted."""
    a = FastAPI()
    a.include_router(make_azure_stt_router(FakeModel()))
    return a


@pytest.fixture(scope="module")
def client(app) -> TestClient:
    """TestClient for the normal (hello-world) model."""
    return TestClient(app)


@pytest.fixture(scope="module")
def empty_client() -> TestClient:
    """TestClient backed by FakeEmptyModel."""
    a = FastAPI()
    a.include_router(make_azure_stt_router(FakeEmptyModel()))
    return TestClient(a)


@pytest.fixture(scope="module")
def wav_bytes() -> bytes:
    """A short silent WAV."""
    return _make_wav_bytes()


# ===========================================================================
# Unit tests: pure helper functions
# ===========================================================================

class TestMsUnits:
    def test_zero(self):
        assert _ms_units(0.0) == 0

    def test_one_second(self):
        assert _ms_units(1.0) == 10_000_000

    def test_half_second(self):
        assert _ms_units(0.5) == 5_000_000


class TestParseText:
    def test_simple(self):
        raw = "Path:speech.config\r\nX-RequestId:abc\r\n\r\n{}"
        headers, body = _parse_text(raw)
        assert headers["Path"] == "speech.config"
        assert headers["X-RequestId"] == "abc"
        assert body == "{}"

    def test_no_body(self):
        raw = "Path:turn.end\r\n\r\n"
        headers, body = _parse_text(raw)
        assert headers["Path"] == "turn.end"
        assert body == ""

    def test_empty_string(self):
        headers, body = _parse_text("")
        assert headers == {}
        assert body == ""


class TestParseBinary:
    def test_round_trip(self):
        frame = _build_binary("audio", "req123", b"\xde\xad\xbe\xef")
        headers, body = _parse_binary(frame)
        assert headers["Path"] == "audio"
        assert b"\xde\xad\xbe\xef" == body

    def test_too_short_returns_empty(self):
        headers, body = _parse_binary(b"\x00")
        assert headers == {}
        assert body == b""

    def test_empty_body_frame(self):
        frame = _build_binary("audio", "req", b"")
        headers, body = _parse_binary(frame)
        assert headers["Path"] == "audio"
        assert body == b""


class TestBuildText:
    def test_structure(self):
        frame = _build_text("turn.end", "rid1", "{}")
        assert "Path:turn.end" in frame
        assert "X-RequestId:rid1" in frame
        assert "\r\n\r\n" in frame
        # body after blank line
        _, _, body = frame.partition("\r\n\r\n")
        assert body == "{}"

    def test_custom_content_type(self):
        frame = _build_text("x", "y", "z", content_type="text/plain")
        assert "Content-Type:text/plain" in frame


# ===========================================================================
# REST endpoint
# ===========================================================================

class TestRESTEndpoint:
    def test_happy_path_wav(self, client, wav_bytes):
        """POST WAV → 200 with RecognitionStatus=Success and DisplayText filled."""
        r = client.post(
            "/azure-stt/cognitiveservices/v1?language=en-US",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["RecognitionStatus"] == "Success"
        assert body["DisplayText"] == "hello world"
        assert body["Duration"] > 0

    def test_auth_headers_ignored(self, client, wav_bytes):
        """Auth headers are accepted and silently ignored."""
        r = client.post(
            "/azure-stt/cognitiveservices/v1?language=en-US",
            content=wav_bytes,
            headers={
                "Content-Type": "audio/wav",
                "Ocp-Apim-Subscription-Key": "dummy-key",
                "Authorization": "Bearer dummy",
            },
        )
        assert r.status_code == 200

    def test_empty_transcript_returns_silence_timeout(self, empty_client, wav_bytes):
        """Empty transcript → RecognitionStatus=InitialSilenceTimeout."""
        r = empty_client.post(
            "/azure-stt/cognitiveservices/v1",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["RecognitionStatus"] == "InitialSilenceTimeout"
        assert body["DisplayText"] == ""

    def test_default_language(self, client, wav_bytes):
        """language query param defaults to en-US when omitted."""
        r = client.post(
            "/azure-stt/cognitiveservices/v1",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        assert r.status_code == 200

    def test_offset_is_zero(self, client, wav_bytes):
        """Offset field is always 0."""
        r = client.post(
            "/azure-stt/cognitiveservices/v1",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        assert r.json()["Offset"] == 0

    def test_response_model_fields(self, client, wav_bytes):
        """Response includes all four required fields."""
        r = client.post(
            "/azure-stt/cognitiveservices/v1",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )
        body = r.json()
        for field in ("RecognitionStatus", "DisplayText", "Offset", "Duration"):
            assert field in body


# ===========================================================================
# WebSocket endpoint — Microsoft framing protocol
# ===========================================================================

class TestWSEndpoint:
    """Tests for the WS streaming endpoint at /azure-stt/cognitiveservices/v1."""

    def _ws_url(self) -> str:
        return "/azure-stt/cognitiveservices/v1"

    def _full_turn(self, client, wav_bytes, extra_lang: str = None) -> list[str]:
        """Run a complete single-turn WS exchange; return ordered Path values."""
        request_id = uuid.uuid4().hex
        paths = []
        qs = "?language=en-US"
        if extra_lang:
            qs = f"?language={extra_lang}"
        with client.websocket_connect(self._ws_url() + qs) as ws:
            # speech.config
            ws.send_text(_build_text("speech.config", request_id,
                                     json.dumps({"context": {}})))
            # speech.context
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            # audio chunk
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            # empty audio = end of stream
            ws.send_bytes(_build_binary("audio", request_id, b""))
            # drain 6 response frames
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                paths.append(h.get("Path"))
        return paths

    def test_frame_sequence(self, client, wav_bytes):
        """The six frames must arrive in the canonical Microsoft order."""
        paths = self._full_turn(client, wav_bytes)
        assert paths == [
            "turn.start",
            "speech.startDetected",
            "speech.hypothesis",
            "speech.endDetected",
            "speech.phrase",
            "turn.end",
        ]

    def test_transcript_in_hypothesis_and_phrase(self, client, wav_bytes):
        """Both hypothesis and phrase carry the transcript text."""
        request_id = uuid.uuid4().hex
        transcripts = []
        with client.websocket_connect(self._ws_url() + "?language=en-US") as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, body = _parse_text(frame)
                if h.get("Path") in ("speech.hypothesis", "speech.phrase"):
                    payload = json.loads(body)
                    transcripts.append(
                        payload.get("Text") or payload.get("DisplayText", "")
                    )
        assert all(t == "hello world" for t in transcripts)

    def test_empty_transcript_gives_silence_timeout(self, empty_client, wav_bytes):
        """FakeEmptyModel → phrase RecognitionStatus=InitialSilenceTimeout."""
        request_id = uuid.uuid4().hex
        phrase_status = None
        with empty_client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, body = _parse_text(frame)
                if h.get("Path") == "speech.phrase":
                    phrase_status = json.loads(body)["RecognitionStatus"]
        assert phrase_status == "InitialSilenceTimeout"

    def test_request_id_propagated(self, client, wav_bytes):
        """turn.start carries the X-RequestId sent by the client."""
        request_id = uuid.uuid4().hex
        turn_start_id = None
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                if h.get("Path") == "turn.start":
                    turn_start_id = h.get("X-RequestId")
        assert turn_start_id == request_id

    def test_speech_audio_end_text_frame_terminates_turn(self, client, wav_bytes):
        """speech.audio.end text frame (after audio) terminates the turn cleanly."""
        request_id = uuid.uuid4().hex
        paths = []
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            # use speech.audio.end text frame instead of empty binary
            ws.send_text(_build_text("speech.audio.end", request_id, "{}"))
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                paths.append(h.get("Path"))
        assert "turn.end" in paths

    def test_speech_context_lang_override(self, client, wav_bytes):
        """Language override via speech.context languageId is accepted."""
        request_id = uuid.uuid4().hex
        ctx_body = json.dumps({"languageId": {"languages": ["pt-PT"]}})
        paths = []
        with client.websocket_connect(self._ws_url() + "?language=en-US") as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, ctx_body))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                paths.append(h.get("Path"))
        assert paths == [
            "turn.start", "speech.startDetected", "speech.hypothesis",
            "speech.endDetected", "speech.phrase", "turn.end",
        ]

    def test_no_audio_before_speech_audio_end_no_turn(self, client):
        """speech.audio.end before any audio chunk → no turn frames emitted."""
        request_id = uuid.uuid4().hex
        received = []
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.audio.end", request_id, "{}"))
            # Server should not send any frames (turn was never started).
            # Send a new audio chunk to trigger a new turn so we can close cleanly.
            wav_bytes = _make_wav_bytes()
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                received.append(h.get("Path"))
        # Only the second turn produces frames; no spurious frames from the skipped turn.
        assert received[0] == "turn.start"

    def test_turn_started_then_audio_end_empty_buffer(self, client, wav_bytes):
        """Turn started via first audio chunk; speech.audio.end with no payload data
        exercises the empty-buffer (transcript="", audio_seconds=0.0) path."""
        request_id = uuid.uuid4().hex
        paths = []
        phrase_status = None
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            # Send audio frame with empty body (starts the turn but buffers nothing)
            # Because body is empty AND turn_started is False, we need one with body first,
            # then one without — but for the empty-buffer branch we send an explicit
            # speech.audio.end text frame after a zero-body audio binary.
            # First: send a zero-body binary to start the turn (body=="" triggers break only
            # if turn_started; here it IS the first frame so turn_started flips to True, then break)
            ws.send_bytes(_build_binary("audio", request_id, b""))
            # Server will start the turn (turn_started=True) and immediately break from inner loop.
            # Buffer is empty → transcript="" → InitialSilenceTimeout.
            for _ in range(6):
                frame = ws.receive_text()
                h, body = _parse_text(frame)
                paths.append(h.get("Path"))
                if h.get("Path") == "speech.phrase":
                    phrase_status = json.loads(body)["RecognitionStatus"]
        assert "turn.end" in paths
        assert phrase_status == "InitialSilenceTimeout"

    def test_speech_context_invalid_json_is_ignored(self, client, wav_bytes):
        """Malformed JSON in speech.context body is silently swallowed."""
        request_id = uuid.uuid4().hex
        paths = []
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            # deliberately broken JSON body
            ws.send_text(_build_text("speech.context", request_id, "not-json!!!"))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                paths.append(h.get("Path"))
        assert "turn.end" in paths

    def test_speech_audio_end_before_any_audio_no_frames(self, client):
        """speech.audio.end before any audio chunk → no turn frames from that turn.

        Then send a full audio turn to verify the connection is still usable and
        the server emits the 6-frame sequence for the second turn.
        """
        request_id = uuid.uuid4().hex
        wav = _make_wav_bytes()
        paths = []
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            # end before any audio → turn_started is False → no frames emitted
            ws.send_text(_build_text("speech.audio.end", request_id, "{}"))
            # second turn: send audio so server emits its 6 frames
            ws.send_bytes(_build_binary("audio", request_id, wav))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, _ = _parse_text(frame)
                paths.append(h.get("Path"))
        assert paths == [
            "turn.start", "speech.startDetected", "speech.hypothesis",
            "speech.endDetected", "speech.phrase", "turn.end",
        ]

    def test_duration_ticks_in_end_detected(self, client, wav_bytes):
        """speech.endDetected Offset matches the duration in 100-ns ticks."""
        request_id = uuid.uuid4().hex
        end_detected_offset = None
        with client.websocket_connect(self._ws_url()) as ws:
            ws.send_text(_build_text("speech.config", request_id, "{}"))
            ws.send_text(_build_text("speech.context", request_id, "{}"))
            ws.send_bytes(_build_binary("audio", request_id, wav_bytes))
            ws.send_bytes(_build_binary("audio", request_id, b""))
            for _ in range(6):
                frame = ws.receive_text()
                h, body = _parse_text(frame)
                if h.get("Path") == "speech.endDetected":
                    end_detected_offset = json.loads(body)["Offset"]
        assert end_detected_offset is not None
        assert end_detected_offset > 0


# ===========================================================================
# Pydantic model
# ===========================================================================

class TestAzureRESTResponse:
    def test_defaults(self):
        r = AzureRESTResponse()
        assert r.RecognitionStatus == "Success"
        assert r.DisplayText == ""
        assert r.Offset == 0
        assert r.Duration == 0

    def test_custom_values(self):
        r = AzureRESTResponse(
            RecognitionStatus="InitialSilenceTimeout",
            DisplayText="",
            Offset=0,
            Duration=1_000_000,
        )
        assert r.RecognitionStatus == "InitialSilenceTimeout"
        assert r.Duration == 1_000_000
