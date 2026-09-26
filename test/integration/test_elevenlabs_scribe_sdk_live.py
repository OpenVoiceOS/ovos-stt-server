"""Live test: drive the official ElevenLabs SDK (Scribe STT) against our
/elevenlabs router.

The client defaults to ``https://api.elevenlabs.io`` and appends
``/v1/speech-to-text``; pointing ``base_url`` at ``{server}/elevenlabs`` makes
it hit our router unchanged.
"""
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.elevenlabs_scribe import make_elevenlabs_scribe_router

    def register(app, model):
        app.include_router(make_elevenlabs_scribe_router(model))

    yield from run_live_server(register)


def test_transcribe_via_elevenlabs_sdk(base_url, tmp_path):
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key="ignored", base_url=f"{base_url}/elevenlabs")

    wav = tmp_path / "clip.wav"
    wav.write_bytes(make_silent_wav())
    with open(wav, "rb") as f:
        result = client.speech_to_text.convert(file=f, model_id="scribe_v1")
    assert result.text == "hello world"
