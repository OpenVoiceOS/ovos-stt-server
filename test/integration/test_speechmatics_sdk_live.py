# Licensed under the Apache License, Version 2.0
"""Live integration test: official speechmatics-batch SDK against our /speechmatics router.

Uses ``speechmatics.batch.AsyncClient`` with a custom ``url`` pointing at our
local uvicorn server, so no Speechmatics account is required. The SDK's base URL already includes the ``/v2`` API version and it appends
``/jobs``, so ``url='http://host/speechmatics/v2'`` lands on
``/speechmatics/v2/jobs`` — matching the router.
"""
import asyncio

import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    """Yield base URL for a live uvicorn server with the Speechmatics router."""
    import speechmatics.batch  # noqa: F401 — SDK required for this e2e test

    from ovos_stt_http_server.routers.speechmatics import make_speechmatics_router

    def register(app, model):
        app.include_router(make_speechmatics_router(model))

    yield from run_live_server(register)


def test_batch_transcribe_via_sdk(base_url, tmp_path):
    """AsyncClient.transcribe submits audio, polls until done, returns the transcript."""
    from speechmatics.batch import AsyncClient, TranscriptionConfig

    wav = tmp_path / "clip.wav"
    wav.write_bytes(make_silent_wav())

    async def run():
        client = AsyncClient(api_key="ignored", url=f"{base_url}/speechmatics/v2")
        try:
            return await client.transcribe(
                str(wav),
                transcription_config=TranscriptionConfig(language="en"),
                polling_interval=0.1,
            )
        finally:
            await client.close()

    transcript = asyncio.run(run())
    text = getattr(transcript, "transcript_text", None)
    if text is None:
        text = str(transcript)
    # the fake engine always returns "hello world"
    assert text == "hello world"
