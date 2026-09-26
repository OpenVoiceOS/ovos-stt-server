"""Live tests for the /google router.

Option A — raw REST against the documented JSON shape (always works).
Option B — the official google-cloud-speech SDK driven via the documented
           AuthorizedSession.request monkey-patch from docs/api-compatibility.md.
"""
import base64
from urllib.parse import urlparse

import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.google_stt import make_google_stt_router

    def register(app, model):
        app.include_router(make_google_stt_router(model))

    yield from run_live_server(register)


# ----------------------------------------------------------------------
# Option A — raw REST
# ----------------------------------------------------------------------

def test_recognize_base64(base_url):
    wav = make_silent_wav()
    payload = {
        "config": {"languageCode": "en-US", "encoding": "LINEAR16", "sampleRateHertz": 16000},
        "audio": {"content": base64.b64encode(wav).decode()},
    }
    r = requests.post(f"{base_url}/google/v1/speech:recognize", json=payload)
    r.raise_for_status()
    assert r.json()["results"][0]["alternatives"][0]["transcript"] == "hello world"


def test_recognize_with_custom_language_code(base_url):
    wav = make_silent_wav()
    payload = {
        "config": {"languageCode": "de-DE", "encoding": "LINEAR16", "sampleRateHertz": 16000},
        "audio": {"content": base64.b64encode(wav).decode()},
    }
    r = requests.post(f"{base_url}/google/v1/speech:recognize", json=payload)
    r.raise_for_status()
    assert r.json()["results"][0]["alternatives"][0]["transcript"] == "hello world"


# ----------------------------------------------------------------------
# Option B — official google-cloud-speech SDK via documented monkey-patch
# (mirrors the snippet in docs/api-compatibility.md so doc drift is caught)
# ----------------------------------------------------------------------

def test_recognize_via_sdk_monkey_patch(base_url, monkeypatch):
    import google.cloud.speech_v1 as speech_v1
    from google.auth.credentials import AnonymousCredentials
    from google.auth.transport.requests import AuthorizedSession

    ovos_base = f"{base_url}/google"
    _orig_request = AuthorizedSession.request

    def _rewrite(self, method, url, *args, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https"):
            # Strip scheme+host, keep path+query, prepend our prefix
            new = ovos_base + parsed.path
            if parsed.query:
                new = f"{new}?{parsed.query}"
            url = new
        return _orig_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(AuthorizedSession, "request", _rewrite)

    client = speech_v1.SpeechClient(
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": urlparse(base_url).netloc},
        transport="rest",
    )

    audio = speech_v1.RecognitionAudio(content=make_silent_wav())
    config = speech_v1.RecognitionConfig(
        encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="en-US",
    )
    response = client.recognize(config=config, audio=audio)
    assert response.results[0].alternatives[0].transcript == "hello world"
