"""Live test: hit our /assemblyai router via raw REST (matches the SDK's wire format)."""
import base64

import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.assemblyai import make_assemblyai_router

    def register(app, model):
        app.include_router(make_assemblyai_router(model))

    yield from run_live_server(register)


def test_submit_b64_transcript(base_url):
    wav = make_silent_wav()
    r = requests.post(
        f"{base_url}/assemblyai/v2/transcript",
        json={"audio": base64.b64encode(wav).decode()},
        headers={"Authorization": "ignored"},
    )
    r.raise_for_status()
    j = r.json()
    assert j["status"] == "completed"
    assert j["text"] == "hello world"
    assert "id" in j


def test_get_transcript_returns_stub(base_url):
    # POST to create
    wav = make_silent_wav()
    r = requests.post(
        f"{base_url}/assemblyai/v2/transcript",
        json={"audio": base64.b64encode(wav).decode()},
    )
    tid = r.json()["id"]
    # GET should return a transcript object with status field
    r2 = requests.get(f"{base_url}/assemblyai/v2/transcript/{tid}")
    r2.raise_for_status()
    assert "status" in r2.json()


def test_audio_url_returns_error(base_url):
    r = requests.post(
        f"{base_url}/assemblyai/v2/transcript",
        json={"audio_url": "https://example.com/clip.wav"},
    )
    r.raise_for_status()
    j = r.json()
    assert j["status"] == "error"
