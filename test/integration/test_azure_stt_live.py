"""Live tests for the /azure-stt router.

REST: raw HTTP via `requests`.
WS:   raw `websockets` client speaking Microsoft's HTTP-style WS framing.

The official `azure-cognitiveservices-speech` SDK does work end-to-end against
our /azure-stt/cognitiveservices/v1 path, but it requires a wss:// scheme
(plain ws is rejected by the SDK's URL parser). In CI we can't terminate TLS
on a random uvicorn port, so the SDK test is excluded here; production users
behind nginx (per docs/api-compatibility.md) get the full SDK path.
"""
import asyncio
import io
import json
import time
import uuid
import wave

import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.azure_stt import make_azure_stt_router

    def register(app, model):
        app.include_router(make_azure_stt_router(model))

    yield from run_live_server(register)


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

def test_rest_short_form(base_url):
    r = requests.post(
        f"{base_url}/azure-stt/cognitiveservices/v1?language=en-US",
        data=make_silent_wav(),
        headers={"Content-Type": "audio/wav",
                 "Ocp-Apim-Subscription-Key": "ignored"},
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    assert body["RecognitionStatus"] == "Success"
    assert body["DisplayText"] == "hello world"


# ---------------------------------------------------------------------------
# WS — raw client speaking the Microsoft wire format
# ---------------------------------------------------------------------------

def _build_text(path: str, request_id: str, body: str) -> str:
    return (
        f"X-RequestId:{request_id}\r\n"
        f"X-Timestamp:{time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())}\r\n"
        f"Path:{path}\r\n"
        f"Content-Type:application/json; charset=utf-8\r\n"
        f"\r\n{body}"
    )


def _build_binary(path: str, request_id: str, body: bytes) -> bytes:
    head = (
        f"X-RequestId:{request_id}\r\n"
        f"X-Timestamp:{time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())}\r\n"
        f"Path:{path}\r\n"
        f"Content-Type:audio/x-wav\r\n"
    ).encode("ascii")
    return len(head).to_bytes(2, "big") + head + body


def _parse_text(raw: str) -> tuple[dict, str]:
    head, _, body = raw.partition("\r\n\r\n")
    headers = {}
    for line in head.split("\r\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip()] = v.strip()
    return headers, body


def test_ws_streaming_protocol(base_url):
    import websockets.sync.client as websockets

    ws_url = base_url.replace("http://", "ws://") + \
        "/azure-stt/cognitiveservices/v1?language=en-US"
    request_id = uuid.uuid4().hex
    wav = make_silent_wav()

    transcripts = []
    paths = []

    with websockets.connect(ws_url) as ws:
        ws.send(_build_text("speech.config", request_id, json.dumps({"context": {}})))
        ws.send(_build_text("speech.context", request_id, "{}"))
        ws.send(_build_binary("audio", request_id, wav))
        ws.send(_build_binary("audio", request_id, b""))  # end of stream

        # Drain 6 frames: turn.start, startDetected, hypothesis,
        # endDetected, phrase, turn.end
        for _ in range(6):
            frame = ws.recv()
            headers, body = _parse_text(frame)
            paths.append(headers["Path"])
            if headers["Path"] in ("speech.hypothesis", "speech.phrase"):
                payload = json.loads(body)
                transcripts.append(payload.get("Text") or payload.get("DisplayText"))

    assert paths == [
        "turn.start", "speech.startDetected", "speech.hypothesis",
        "speech.endDetected", "speech.phrase", "turn.end",
    ]
    assert "hello world" in transcripts
