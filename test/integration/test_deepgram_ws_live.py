"""Live test: drive the official Deepgram WS streaming client against /deepgram/v1/listen."""
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.deepgram import make_deepgram_router

    def register(app, model):
        app.include_router(make_deepgram_router(model))

    yield from run_live_server(register)


def test_streaming_via_sdk(base_url):
    import deepgram
    DeepgramClient = deepgram.DeepgramClient
    DeepgramClientEnvironment = deepgram.DeepgramClientEnvironment

    # Quirk: the Deepgram SDK reads `production` for both REST and WS — it
    # appends "/v1/listen" and pipes the result straight into websockets.connect,
    # which requires ws://. So we point `production` at the ws scheme; SDKs
    # using the REST surface need the override pattern from the other test.
    ws_base = base_url.replace("http://", "ws://")
    env = DeepgramClientEnvironment(
        base=f"{base_url}/deepgram",
        production=f"{ws_base}/deepgram",
        agent=f"{ws_base}/deepgram",
        agent_rest=f"{base_url}/deepgram",
    )
    client = DeepgramClient(api_key="ignored", environment=env)

    results = []
    metadata = []

    with client.listen.v1.connect(
        model="nova-3",
        encoding="linear16",
        sample_rate=16000,
        language="en",
    ) as socket:
        # Send audio in two halves to exercise the buffer concat path
        wav = make_silent_wav()
        socket.send_media(wav[: len(wav) // 2])
        socket.send_media(wav[len(wav) // 2 :])

        # Tell the server we're done. send_close_stream emits {"type":"CloseStream"}
        # which our handler treats as finalisation.
        socket.send_close_stream()

        # Drain inbound frames until Metadata (server closes after it).
        # recv() returns typed pydantic models, not raw JSON.
        while True:
            try:
                msg = socket.recv()
            except Exception:
                break
            if msg is None:
                break
            type_field = getattr(msg, "type", None)
            if type_field == "Results":
                results.append(msg)
            elif type_field == "Metadata":
                metadata.append(msg)
                break

    assert results, "no Results frame received"
    transcript = results[0].channel.alternatives[0].transcript
    assert transcript == "hello world"
