"""Live tests for the /watson router using the official `ibm-watson` SDK.

The IBM SDK accepts `set_service_url()` cleanly — no monkey-patching needed
for the REST surface. The WS surface uses `recognize_using_websocket()`
which builds wss:// from the configured base; we use a raw websockets client
to exercise the protocol because local uvicorn doesn't do TLS.
"""
import io
import json

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.ibm_watson_stt import make_ibm_watson_stt_router

    def register(app, model):
        app.include_router(make_ibm_watson_stt_router(model))

    yield from run_live_server(register)


def test_rest_via_sdk(base_url):
    import ibm_watson
    from ibm_cloud_sdk_core.authenticators import IAMAuthenticator, NoAuthAuthenticator

    stt = ibm_watson.SpeechToTextV1(authenticator=NoAuthAuthenticator())
    stt.set_service_url(f"{base_url}/watson/speech-to-text")
    stt.set_disable_ssl_verification(True)  # local uvicorn HTTP

    wav = make_silent_wav()
    response = stt.recognize(
        audio=io.BytesIO(wav),
        content_type="audio/wav",
        model="en-US_BroadbandModel",
    ).get_result()
    assert response["results"][0]["alternatives"][0]["transcript"] == "hello world"


def test_ws_protocol_raw(base_url):
    """Raw WS client speaking Watson's start/audio/stop protocol."""
    import websockets.sync.client as websockets

    ws_url = base_url.replace("http://", "ws://") + "/watson/speech-to-text/v1/recognize"
    with websockets.connect(ws_url) as ws:
        listening = json.loads(ws.recv())
        assert listening == {"state": "listening"}

        ws.send(json.dumps({
            "action": "start",
            "content-type": "audio/l16;rate=16000",
            "model": "en-US_BroadbandModel",
        }))
        ws.send(make_silent_wav())
        ws.send(json.dumps({"action": "stop"}))

        results = json.loads(ws.recv())
        assert results["results"][0]["alternatives"][0]["transcript"] == "hello world"
