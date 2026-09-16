"""Live test: drive the official AssemblyAI v3 streaming SDK against our WS endpoint.

The current ``assemblyai`` SDK exposes Universal-Streaming (v3) via
``assemblyai.streaming.v3.StreamingClient``. Its ``_build_uri`` honours a
``ws://`` host as-is (``{host}/v3/ws``), so we point ``api_host`` straight at
the local ``/assemblyai`` route — no monkeypatching needed (in production a TLS
front end per the redirect docs makes the host ``wss://``).
"""
import threading

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.assemblyai import make_assemblyai_router

    def register(app, model):
        app.include_router(make_assemblyai_router(model))

    yield from run_live_server(register)


def test_streaming_v3_via_sdk(base_url):
    import assemblyai
    from assemblyai.streaming.v3 import (
        StreamingClient,
        StreamingClientOptions,
        StreamingParameters,
        StreamingEvents,
        TurnEvent,
    )

    # ws:// host is used verbatim by the SDK → ws://<host>/assemblyai/v3/ws
    ws_host = base_url.replace("http://", "ws://") + "/assemblyai"
    client = StreamingClient(StreamingClientOptions(api_host=ws_host, api_key="ignored"))

    turns = []
    done = threading.Event()

    def on_turn(_self, event: TurnEvent) -> None:
        if event.end_of_turn:
            turns.append(event.transcript)

    def on_terminated(_self, _event) -> None:
        done.set()

    client.on(StreamingEvents.Turn, on_turn)
    client.on(StreamingEvents.Termination, on_terminated)

    client.connect(StreamingParameters(sample_rate=16000))
    wav = make_silent_wav()
    client.stream(wav[: len(wav) // 2])
    client.stream(wav[len(wav) // 2:])
    client.disconnect(terminate=True)

    done.wait(timeout=5)
    assert turns, "no final Turn received"
    assert turns[0] == "hello world"
