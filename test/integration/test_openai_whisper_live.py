# Licensed under the Apache License, Version 2.0
"""Live integration test: drive the official openai SDK against our /openai router.

The official ``openai`` SDK sends multipart/form-data to ``POST /audio/transcriptions``.
This test spins up a real uvicorn server with a FakeSTTEngine and verifies that
``openai.OpenAI(base_url=...).audio.transcriptions.create(...)`` works end-to-end.
"""
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    """Live uvicorn server with the openai_whisper router registered."""
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    def register(app, model):
        app.include_router(make_openai_whisper_router(model))

    yield from run_live_server(register)


def test_transcriptions_via_openai_sdk(base_url):
    """Official openai SDK transcriptions.create hits our router and returns text."""
    import openai

    client = openai.OpenAI(
        api_key="ignored",
        base_url=f"{base_url}/openai/v1",
    )
    wav_bytes = make_silent_wav(0.1)
    result = client.audio.transcriptions.create(
        file=("audio.wav", wav_bytes, "audio/wav"),
        model="whisper-1",
    )
    assert result.text == "hello world"


def test_transcriptions_verbose_json_via_sdk(base_url):
    """verbose_json response_format returns a TranscriptionVerbose-compatible dict."""
    import openai

    client = openai.OpenAI(
        api_key="ignored",
        base_url=f"{base_url}/openai/v1",
    )
    wav_bytes = make_silent_wav(0.1)
    result = client.audio.transcriptions.create(
        file=("audio.wav", wav_bytes, "audio/wav"),
        model="whisper-1",
        response_format="verbose_json",
    )
    assert result.text == "hello world"
    assert hasattr(result, "duration")
    assert hasattr(result, "language")


def test_translations_via_openai_sdk(base_url):
    """Official openai SDK translations.create hits our /audio/translations route."""
    import openai

    client = openai.OpenAI(
        api_key="ignored",
        base_url=f"{base_url}/openai/v1",
    )
    wav_bytes = make_silent_wav(0.1)
    result = client.audio.translations.create(
        file=("audio.wav", wav_bytes, "audio/wav"),
        model="whisper-1",
    )
    assert result.text == "hello world"
