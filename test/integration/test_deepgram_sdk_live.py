"""Live test: drive the official Deepgram SDK against our /deepgram router.

Uses `DeepgramClientEnvironment` to override every host (base/production/agent)
to point at our local server, since the SDK ships with hard-coded URLs.
"""
import pytest

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.deepgram import make_deepgram_router

    def register(app, model):
        app.include_router(make_deepgram_router(model))

    yield from run_live_server(register)


def test_transcribe_file_via_sdk(base_url):
    import deepgram
    DeepgramClient = deepgram.DeepgramClient
    DeepgramClientEnvironment = deepgram.DeepgramClientEnvironment

    env = DeepgramClientEnvironment(
        base=f"{base_url}/deepgram",
        production=f"{base_url}/deepgram",
        agent=f"{base_url.replace('http', 'ws')}/deepgram",
        agent_rest=f"{base_url}/deepgram",
    )
    client = DeepgramClient(api_key="ignored", environment=env)

    response = client.listen.v1.media.transcribe_file(
        request=make_silent_wav(),
        model="nova-3",
        language="en",
    )
    # SDK returns a typed ListenV1Response — drill into the canonical shape
    transcript = response.results.channels[0].alternatives[0].transcript
    assert transcript == "hello world"
