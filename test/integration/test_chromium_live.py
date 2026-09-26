"""Live test: drive our /speech-api (Chromium Web Speech) router over HTTP.

The Chromium / Chrome Web Speech API POSTs an audio body to
``/speech-api/v2/recognize`` and returns newline-delimited JSON. There is no
clean pip-installable client (the in-browser API / ``ovos-stt-plugin-chromium``
is the closest, but the latter drags legacy deps), so we exercise the real wire
contract directly. We send raw PCM via the ``audio/x-raw`` content type the
router supports, which needs no system audio codecs in CI.
"""
import json

import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.chromium import make_chromium_router

    def register(app, model):
        app.include_router(make_chromium_router(model))

    yield from run_live_server(register)


def test_chromium_recognize_endpoint(base_url):
    # The WAV container carries 16 kHz mono 16-bit PCM; strip the 44-byte header
    # and post the raw frames as audio/x-raw (the router's no-codec fast path).
    pcm = make_silent_wav()[44:]

    resp = requests.post(
        f"{base_url}/speech-api/v2/recognize?client=chromium&lang=en-us",
        data=pcm,
        headers={"Content-Type": "audio/x-raw; rate=16000"},
        timeout=10,
    )
    assert resp.status_code == 200

    # Chromium wire format: newline-delimited JSON; the transcript lives in
    # result[].alternative[].transcript on the non-empty line.
    transcripts = [
        alt["transcript"]
        for line in resp.text.splitlines() if line.strip()
        for result in json.loads(line).get("result", [])
        for alt in result.get("alternative", [])
    ]
    assert "hello world" in transcripts
