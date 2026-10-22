"""Live test: hit our /deepgram router via raw HTTP (matches the wire format)."""
import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.deepgram import make_deepgram_router

    def register(app, model):
        app.include_router(make_deepgram_router(model))

    yield from run_live_server(register)


def test_listen_basic(base_url):
    wav = make_silent_wav()
    r = requests.post(
        f"{base_url}/deepgram/v1/listen",
        data=wav,
        headers={"Content-Type": "audio/wav"},
    )
    r.raise_for_status()
    j = r.json()
    transcript = j["results"]["channels"][0]["alternatives"][0]["transcript"]
    assert transcript == "hello world"


def test_listen_with_language(base_url):
    wav = make_silent_wav()
    r = requests.post(
        f"{base_url}/deepgram/v1/listen?language=de",
        data=wav,
        headers={"Content-Type": "audio/wav"},
    )
    r.raise_for_status()
    assert r.json()["results"]["channels"][0]["alternatives"][0]["transcript"] == "hello world"


def test_listen_auth_header_ignored(base_url):
    wav = make_silent_wav()
    r = requests.post(
        f"{base_url}/deepgram/v1/listen",
        data=wav,
        headers={"Content-Type": "audio/wav", "Authorization": "Token abc123"},
    )
    r.raise_for_status()
    assert r.json()["results"]["channels"][0]["alternatives"][0]["transcript"] == "hello world"
