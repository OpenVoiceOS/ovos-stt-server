"""Live test: drive the official Groq SDK against our /groq router.

Groq's client defaults to ``https://api.groq.com`` and appends
``/openai/v1/audio/transcriptions``; pointing ``base_url`` at ``{server}/groq``
makes it hit our router unchanged.
"""
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.groq import make_groq_router

    def register(app, model):
        app.include_router(make_groq_router(model))

    yield from run_live_server(register)


def test_transcribe_via_groq_sdk(base_url, tmp_path):
    import groq

    client = groq.Groq(api_key="ignored", base_url=f"{base_url}/groq")

    wav = tmp_path / "clip.wav"
    wav.write_bytes(make_silent_wav())
    with open(wav, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(wav.name, f.read()), model="whisper-large-v3"
        )
    assert result.text == "hello world"
