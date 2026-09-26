# Licensed under the Apache License, Version 2.0
"""Live test: speak the vosk-server WS protocol against /vosk.

Vosk-server has no official client SDK — apps connect with raw ``websockets``
or any equivalent JSON-over-WS library. We mirror the exact wire format
used by the ``vosk-server/websocket/asr_server.py`` reference.
"""
import json

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.vosk_server import make_vosk_server_router

    def register(app, model):
        app.include_router(make_vosk_server_router(model))

    yield from run_live_server(register)


def test_vosk_protocol(base_url):
    """Full vosk-server wire sequence: config → audio → eof → final text."""
    import websockets.sync.client as websockets
    ws_url = base_url.replace("http://", "ws://") + "/vosk"
    with websockets.connect(ws_url) as ws:
        ws.send(json.dumps({"config": {"sample_rate": 16000}}))
        ws.send(make_silent_wav())
        # Consume partial emitted after the audio frame.
        _partial = json.loads(ws.recv())
        ws.send(json.dumps({"eof": 1}))
        result = json.loads(ws.recv())
        assert result["text"] == "hello world"
