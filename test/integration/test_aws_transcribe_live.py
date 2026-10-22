"""Live test: drive the official boto3 `transcribe` client against /aws/transcribe.

boto3's `transcribe` client accepts `endpoint_url=` cleanly — no monkey-patch
needed for batch jobs. For streaming we use a raw WS client because
`transcribestreaming` over plain HTTP/1.1 WS is our adaptation; the official
HTTP/2 + event-stream framing is documented in the redirect docs.
"""
import base64
import json
import time

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.aws_transcribe import make_aws_transcribe_router

    def register(app, model):
        app.include_router(make_aws_transcribe_router(model))

    yield from run_live_server(register)


def test_batch_via_boto3(base_url):
    import boto3
    # boto3 sends the action to the endpoint_url path verbatim — point it
    # at the exact route, not just the /aws prefix.
    client = boto3.client(
        "transcribe",
        endpoint_url=f"{base_url}/aws/transcribe",
        region_name="us-east-1",
        aws_access_key_id="ignored",
        aws_secret_access_key="ignored",
    )

    wav = make_silent_wav()
    media_uri = "data:audio/wav;base64," + base64.b64encode(wav).decode()

    client.start_transcription_job(
        TranscriptionJobName="boto3-live-1",
        LanguageCode="en-US",
        Media={"MediaFileUri": media_uri},
        MediaFormat="wav",
    )

    # Poll (synchronous on our side, but SDK doesn't know that)
    for _ in range(5):
        r = client.get_transcription_job(TranscriptionJobName="boto3-live-1")
        if r["TranscriptionJob"]["TranscriptionJobStatus"] == "COMPLETED":
            break
        time.sleep(0.1)

    assert r["TranscriptionJob"]["TranscriptionJobStatus"] == "COMPLETED"

    # Fetch the transcript JSON via the SDK-returned URI
    import urllib.request
    transcript_uri = r["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
    with urllib.request.urlopen(transcript_uri) as resp:
        body = json.loads(resp.read())
    assert body["results"]["transcripts"][0]["transcript"] == "hello world"


def test_streaming_ws(base_url):
    import websockets.sync.client as websockets

    ws_url = base_url.replace("http://", "ws://") + \
        "/aws/transcribestreaming/stream-transcription?language-code=en-US&sample-rate=16000"
    with websockets.connect(ws_url) as ws:
        ws.send(make_silent_wav())
        ws.send(b"")  # end of stream

        message = ws.recv()
        parsed = json.loads(message)
        alt = parsed["Transcript"]["Results"][0]["Alternatives"][0]
        assert alt["Transcript"] == "hello world"
