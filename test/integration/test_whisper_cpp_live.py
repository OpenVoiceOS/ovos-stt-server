"""Live integration tests: hit the whisper.cpp-compat router via real HTTP.

whisper.cpp's HTTP server has no client SDK — apps use plain ``requests``
or ``curl``.  We mirror that exact wire interaction.
"""
import io

import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    """Start a live uvicorn server with the whisper.cpp router and yield its URL."""
    from ovos_stt_http_server.routers.whisper_cpp_server import (
        make_whisper_cpp_server_router,
    )

    def register(app, model):
        app.include_router(make_whisper_cpp_server_router(model))

    yield from run_live_server(register)


def _post_wav(url: str, **form_data) -> requests.Response:
    """POST a WAV file as multipart form to ``url``."""
    return requests.post(
        url,
        files={"file": ("clip.wav", io.BytesIO(make_silent_wav()), "audio/wav")},
        data=form_data,
    )


class TestInferenceLive:
    """Live HTTP tests for ``POST /whisper-cpp/inference``."""

    def test_basic_transcription(self, base_url):
        """Basic WAV upload returns 'hello world' transcript."""
        r = _post_wav(f"{base_url}/whisper-cpp/inference")
        r.raise_for_status()
        assert r.json() == {"text": "hello world"}

    def test_language_param(self, base_url):
        """language= form field is forwarded without error."""
        r = _post_wav(f"{base_url}/whisper-cpp/inference", language="de")
        r.raise_for_status()
        assert r.json()["text"] == "hello world"

    def test_response_format_text(self, base_url):
        """response_format=text returns plain transcript."""
        r = _post_wav(f"{base_url}/whisper-cpp/inference", response_format="text")
        r.raise_for_status()
        assert r.text == "hello world"


class TestOpenAITranscriptionsLive:
    """Live HTTP tests for ``POST /whisper-cpp/v1/audio/transcriptions``."""

    def test_basic_transcription(self, base_url):
        """Basic WAV upload returns 'hello world' transcript."""
        r = _post_wav(f"{base_url}/whisper-cpp/v1/audio/transcriptions")
        r.raise_for_status()
        assert r.json() == {"text": "hello world"}

    def test_model_field(self, base_url):
        """model= form field (OpenAI convention) is accepted."""
        r = _post_wav(f"{base_url}/whisper-cpp/v1/audio/transcriptions", model="whisper-1")
        r.raise_for_status()
        assert r.json()["text"] == "hello world"

    def test_response_format_text(self, base_url):
        """response_format=text returns plain transcript."""
        r = _post_wav(f"{base_url}/whisper-cpp/v1/audio/transcriptions", response_format="text")
        r.raise_for_status()
        assert r.text == "hello world"
