# Licensed under the Apache License, Version 2.0
"""Live integration test: official speechmatics-rt SDK against our /speechmatics router.

Uses ``speechmatics.rt.AsyncClient`` pointed at our local uvicorn server's
realtime websocket route ``/speechmatics/v2/rt/{language}``. The RT SDK connects
to exactly the URL given (it does not append the language), so we include the
``/en`` segment. No Speechmatics account is required.
"""
import asyncio
import io

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    """Yield base URL for a live uvicorn server with the Speechmatics router."""
    import speechmatics.rt  # noqa: F401 — SDK required for this e2e test

    from ovos_stt_http_server.routers.speechmatics import make_speechmatics_router

    def register(app, model):
        app.include_router(make_speechmatics_router(model))

    yield from run_live_server(register)


def test_realtime_transcribe_via_sdk(base_url):
    """AsyncClient streams audio over websocket and collects AddTranscript messages."""
    from speechmatics.rt import (
        AsyncClient,
        AudioEncoding,
        AudioFormat,
        ServerMessageType,
        TranscriptionConfig,
    )

    ws_url = base_url.replace("http://", "ws://") + "/speechmatics/v2/rt/en"
    transcripts = []

    async def run():
        client = AsyncClient(api_key="ignored", url=ws_url)

        @client.on(ServerMessageType.ADD_TRANSCRIPT)
        def _on_add_transcript(msg):
            text = msg.get("metadata", {}).get("transcript", "")
            if text:
                transcripts.append(text)

        await client.transcribe(
            io.BytesIO(make_silent_wav()),
            transcription_config=TranscriptionConfig(language="en"),
            audio_format=AudioFormat(
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate=16000,
                chunk_size=1024,
            ),
        )

    asyncio.run(run())

    # the fake engine always returns "hello world"
    assert transcripts, "Expected at least one transcript message"
    assert "hello world" in " ".join(transcripts)
