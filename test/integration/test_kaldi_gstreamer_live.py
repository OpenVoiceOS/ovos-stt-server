"""Live integration test for the kaldi-gstreamer-compatible router.

Runs a real uvicorn server and exercises the WS endpoints using the
websockets library (same as a real kaldi-gstreamer client would do).
"""
import json

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    """Yield a base URL for a live server with the kaldi-gstreamer router mounted."""
    from ovos_stt_http_server.routers.kaldi_gstreamer import make_kaldi_gstreamer_router

    def register(app, model):
        app.include_router(make_kaldi_gstreamer_router(model))

    yield from run_live_server(register)


def test_speech_ws_transcription(base_url):
    """Stream audio + EOS and receive partial + final JSON results."""
    import websockets
    import asyncio

    async def _run():
        ws_url = base_url.replace("http://", "ws://") + "/client/ws/speech?lang=en"
        async with websockets.connect(ws_url) as ws:
            wav = make_silent_wav()
            await ws.send(wav)
            await ws.send("EOS")

            frames = []
            async for msg in ws:
                frames.append(json.loads(msg))

        return frames

    frames = asyncio.run(_run())
    assert len(frames) == 2, f"expected 2 frames, got {frames}"
    partial, final = frames
    assert partial["status"] == 0
    assert partial["result"]["final"] is False
    assert partial["result"]["hypotheses"][0]["transcript"] == "hello world"
    assert final["status"] == 0
    assert final["result"]["final"] is True
    assert final["result"]["hypotheses"][0]["transcript"] == "hello world"


def test_status_ws(base_url):
    """Status endpoint emits a valid capacity JSON and closes."""
    import websockets
    import asyncio

    async def _run():
        ws_url = base_url.replace("http://", "ws://") + "/client/ws/status"
        async with websockets.connect(ws_url) as ws:
            msg = await ws.recv()
            return json.loads(msg)

    status = asyncio.run(_run())
    assert "num_workers_available" in status
    assert "num_requests_processed" in status
