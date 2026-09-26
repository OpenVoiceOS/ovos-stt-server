"""Live test: drive the Gladia v2 upload -> transcription -> poll flow against
our /gladia router.

Gladia has no official Python SDK (its API is consumed over REST), so this
exercises the documented HTTP flow against a real running server using httpx.
"""
import httpx
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.gladia import make_gladia_router

    def register(app, model):
        app.include_router(make_gladia_router(model))

    yield from run_live_server(register)


def test_gladia_flow(base_url, tmp_path):
    root = f"{base_url}/gladia"
    files = {"audio": ("clip.wav", make_silent_wav(), "audio/wav")}
    up = httpx.post(f"{root}/v2/upload", files=files, timeout=30)
    assert up.status_code == 200
    audio_url = up.json()["audio_url"]
    if audio_url.startswith("/"):
        audio_url = f"{base_url}{audio_url}"

    tx = httpx.post(f"{root}/v2/transcription", json={"audio_url": audio_url}, timeout=30)
    assert tx.status_code == 201
    job_id = tx.json()["id"]

    res = httpx.get(f"{root}/v2/transcription/{job_id}", timeout=30)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "done"
    assert body["result"]["transcription"]["full_transcript"] == "hello world"
