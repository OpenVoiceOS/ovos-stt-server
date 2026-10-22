"""Live test: drive the official `wit` Python SDK against /wit/speech.

The SDK reads the API host from the `WIT_URL` env var (see wit.wit.WIT_API_HOST),
so we override it to point at our prefix — no monkey-patching needed.
"""
import io
import os

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.wit_ai import make_wit_ai_router

    def register(app, model):
        app.include_router(make_wit_ai_router(model))

    yield from run_live_server(register)


def test_speech_via_sdk(base_url, monkeypatch):
    import wit
    # wit reads WIT_URL at module-import time; reload after patching.
    monkeypatch.setenv("WIT_URL", f"{base_url}/wit")
    import importlib
    import wit.wit
    importlib.reload(wit.wit)
    from wit.wit import Wit

    client = Wit(access_token="ignored")
    wav = io.BytesIO(make_silent_wav())
    result = client.speech(wav, headers={"Content-Type": "audio/wav"})
    assert result["text"] == "hello world"
