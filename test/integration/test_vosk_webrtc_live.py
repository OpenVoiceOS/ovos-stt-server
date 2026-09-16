"""Live test: SDP-exchange contract for the vosk-server WebRTC variant.

Full audio-path WebRTC tests are notoriously flaky in CI (ICE candidate
gathering, mDNS, host-only routing). The vosk-server WebRTC handshake is
just a JSON-over-HTTP POST returning the SDP answer; once that contract is
honoured, the rest of the WebRTC flow is aiortc plumbing already covered
by aiortc's own test suite.

This test exercises the offer/answer endpoint with a real aiortc-generated
SDP offer to prove the server constructs a valid answer.
"""
import asyncio
import json

import pytest

from test.integration.conftest import run_live_server


@pytest.fixture(scope="module")
def base_url():
    # aiortc builds against system ffmpeg-7 dev headers (via PyAV) and ships no
    # wheels for the newest CI Python, so it cannot be a required dependency.
    # The webrtc router is itself optional (ImportError-gated in create_app),
    # so this single e2e skips when aiortc is absent — install the `test-webrtc`
    # extra to run it.
    pytest.importorskip("aiortc")
    from ovos_stt_http_server.routers.vosk_webrtc import make_vosk_webrtc_router

    def register(app, model):
        app.include_router(make_vosk_webrtc_router(model))

    yield from run_live_server(register)


def test_offer_answer_contract(base_url):
    import aiortc
    import requests
    from aiortc import RTCPeerConnection

    async def _make_offer() -> str:
        pc = RTCPeerConnection()
        pc.createDataChannel("results")
        pc.addTransceiver("audio", direction="sendonly")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        sdp = pc.localDescription.sdp
        await pc.close()
        return sdp

    offer_sdp = asyncio.run(_make_offer())
    resp = requests.post(
        f"{base_url}/vosk-webrtc/offer",
        json={"sdp": offer_sdp, "type": "offer"},
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["type"] == "answer"
    # The answer SDP must be a well-formed offer/answer-grade payload
    assert body["sdp"].startswith("v=")
    assert "m=audio" in body["sdp"]
    # Datachannel SCTP line — vosk-server's reference does the same
    assert "m=application" in body["sdp"] or "DTLS/SCTP" in body["sdp"] or \
        "UDP/DTLS/SCTP" in body["sdp"]
