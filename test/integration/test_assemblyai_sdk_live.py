"""Live test: drive the official AssemblyAI SDK against our /assemblyai router.

Uses `aai.settings.base_url` to override the host and the new
POST /v2/upload + POST /v2/transcript flow we wire up server-side.
"""
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.assemblyai import make_assemblyai_router

    def register(app, model):
        app.include_router(make_assemblyai_router(model))

    yield from run_live_server(register)


def test_transcribe_via_sdk(base_url, tmp_path, monkeypatch):
    import assemblyai as aai
    monkeypatch.setattr(aai.settings, "base_url", f"{base_url}/assemblyai")
    monkeypatch.setattr(aai.settings, "api_key", "ignored")
    # The SDK polls /transcript/{id} until status="completed"; ours returns
    # status="completed" on the very first poll so a low interval is fine.
    monkeypatch.setattr(aai.settings, "polling_interval", 0.05)

    wav = tmp_path / "clip.wav"
    wav.write_bytes(make_silent_wav())

    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(str(wav))
    assert transcript.status == aai.TranscriptStatus.completed
    assert transcript.text == "hello world"
