# Licensed under the Apache License, Version 2.0
"""Unit tests for the whisper.cpp-compatible router (TestClient, no live server)."""
import io
import wave
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ovos_stt_http_server.routers.whisper_cpp_server import (
    WhisperCppResponse,
    make_whisper_cpp_server_router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_bytes() -> bytes:
    """Return a minimal valid WAV file (1-channel 16-bit 16 kHz)."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fake models
# ---------------------------------------------------------------------------

class FakeModel:
    """Minimal model stub — always transcribes to 'hello world'."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return a fixed transcript regardless of input."""
        return "hello world"


class FakeEmptyModel:
    """Stub that returns an empty transcript."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        """Return an empty string to exercise empty-transcript paths."""
        return ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient wired to a whisper.cpp router with FakeModel."""
    app = FastAPI()
    app.include_router(make_whisper_cpp_server_router(FakeModel()))
    return TestClient(app)


@pytest.fixture(scope="module")
def empty_client() -> TestClient:
    """TestClient wired to a whisper.cpp router with FakeEmptyModel."""
    app = FastAPI()
    app.include_router(make_whisper_cpp_server_router(FakeEmptyModel()))
    return TestClient(app)


@pytest.fixture(scope="module")
def wav() -> bytes:
    """Reusable WAV bytes fixture."""
    return _wav_bytes()


# ---------------------------------------------------------------------------
# /whisper-cpp/inference tests
# ---------------------------------------------------------------------------

class TestInferenceEndpoint:
    """Tests for the native whisper.cpp ``POST /whisper-cpp/inference`` endpoint."""

    def test_returns_transcript_json(self, client, wav):
        """Happy path: WAV upload returns JSON with transcribed text."""
        r = client.post("/whisper-cpp/inference", files={"file": ("audio.wav", wav, "audio/wav")})
        assert r.status_code == 200
        assert r.json() == {"text": "hello world"}

    def test_response_format_json_explicit(self, client, wav):
        """Explicit response_format=json returns the same JSON body."""
        r = client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"response_format": "json"},
        )
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"

    def test_response_format_text(self, client, wav):
        """response_format=text returns plain text transcript."""
        r = client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"response_format": "text"},
        )
        assert r.status_code == 200
        assert r.text == "hello world"

    def test_language_param_accepted(self, client, wav):
        """language= form field is accepted without error."""
        r = client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"language": "de"},
        )
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"

    def test_temperature_param_accepted(self, client, wav):
        """temperature= form field is accepted and silently ignored."""
        r = client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"temperature": "0.2"},
        )
        assert r.status_code == 200

    def test_prompt_param_accepted(self, client, wav):
        """prompt= form field is accepted and silently ignored."""
        r = client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"prompt": "some hint"},
        )
        assert r.status_code == 200

    def test_translate_param_accepted(self, client, wav):
        """translate= form field is accepted and silently ignored."""
        r = client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"translate": "false"},
        )
        assert r.status_code == 200

    def test_empty_transcript_returns_empty_text(self, empty_client, wav):
        """Empty model transcript surfaces as empty 'text' field."""
        r = empty_client.post(
            "/whisper-cpp/inference",
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        assert r.status_code == 200
        assert r.json()["text"] == ""

    def test_missing_file_returns_422(self, client):
        """No file field → FastAPI validation error 422."""
        r = client.post("/whisper-cpp/inference", data={"language": "en"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# /whisper-cpp/v1/audio/transcriptions tests
# ---------------------------------------------------------------------------

class TestOpenAITranscriptionsEndpoint:
    """Tests for the OpenAI-compatible ``POST /whisper-cpp/v1/audio/transcriptions``."""

    def test_returns_transcript_json(self, client, wav):
        """Happy path: WAV upload returns JSON with transcribed text."""
        r = client.post(
            "/whisper-cpp/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        assert r.status_code == 200
        assert r.json() == {"text": "hello world"}

    def test_model_field_accepted(self, client, wav):
        """model= form field (OpenAI convention) is accepted without error."""
        r = client.post(
            "/whisper-cpp/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"

    def test_language_param_accepted(self, client, wav):
        """language= form field is accepted without error."""
        r = client.post(
            "/whisper-cpp/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"language": "fr"},
        )
        assert r.status_code == 200

    def test_response_format_text(self, client, wav):
        """response_format=text returns plain text."""
        r = client.post(
            "/whisper-cpp/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"response_format": "text"},
        )
        assert r.status_code == 200
        assert r.text == "hello world"

    def test_empty_transcript(self, empty_client, wav):
        """Empty model transcript returns empty text field."""
        r = empty_client.post(
            "/whisper-cpp/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        assert r.status_code == 200
        assert r.json()["text"] == ""

    def test_missing_file_returns_422(self, client):
        """No file field → FastAPI validation error 422."""
        r = client.post("/whisper-cpp/v1/audio/transcriptions", data={"model": "whisper-1"})
        assert r.status_code == 422

    def test_temperature_and_prompt_accepted(self, client, wav):
        """temperature= and prompt= are accepted and silently ignored."""
        r = client.post(
            "/whisper-cpp/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"temperature": "0.0", "prompt": "hint"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# WhisperCppResponse model tests
# ---------------------------------------------------------------------------

class TestWhisperCppResponse:
    """Tests for the ``WhisperCppResponse`` Pydantic model."""

    def test_model_serialises_text(self):
        """model_dump returns expected dict structure."""
        resp = WhisperCppResponse(text="hello world")
        assert resp.model_dump() == {"text": "hello world"}

    def test_model_empty_text(self):
        """Empty text is valid."""
        resp = WhisperCppResponse(text="")
        assert resp.text == ""
