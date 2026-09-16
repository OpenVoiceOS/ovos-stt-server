# Licensed under the Apache License, Version 2.0
"""vosk-server WebRTC variant.

Mirrors `alphacep/vosk-server/webrtc/asr_server_webrtc.py`:
  - POST /vosk-webrtc/offer  with body {"sdp": ..., "type": "offer"}
  - Server creates RTCPeerConnection, accepts the audio track + datachannel
  - Server returns {"sdp": ..., "type": "answer"}
  - Client streams audio over the peer connection
  - When the audio track ends (or peer closes), server runs the OVOS plugin
    on the buffered audio and sends `{"text": "..."}` on the datachannel
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ovos_plugin_manager.utils.audio import AudioData


_LOG = logging.getLogger(__name__)

# Hold open peer connections so they don't get garbage-collected mid-stream.
_active_pcs: set = set()


class SDPOffer(BaseModel):
    """SDP offer body sent by the WebRTC client."""

    sdp: str
    type: str = "offer"


class SDPAnswer(BaseModel):
    """SDP answer returned by the server after processing the offer."""

    sdp: str
    type: str = "answer"


def make_vosk_webrtc_router(model) -> APIRouter:
    """vosk-server WebRTC-compatible router.

    Args:
        model: ModelContainer / MultiModelContainer.
    """
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from av.audio.resampler import AudioResampler
    except ImportError as exc:
        raise ImportError(
            "vosk-webrtc compat requires the [webrtc] extra: pip install "
            "ovos-stt-http-server[webrtc]"
        ) from exc

    router = APIRouter(prefix="/vosk-webrtc", tags=["vosk-webrtc"])

    @router.post("/offer", response_model=SDPAnswer)
    async def offer(payload: SDPOffer) -> SDPAnswer:
        """Exchange SDP offer for an SDP answer (vosk-server WebRTC handshake).

        The client POSTs an SDP offer; the server creates an RTCPeerConnection,
        sets the remote description, generates an answer, and returns it.
        Audio is buffered from the peer connection's audio track and transcribed
        when the track ends or the ICE connection closes.
        """
        offer_desc = RTCSessionDescription(sdp=payload.sdp, type=payload.type)
        pc = RTCPeerConnection()
        _active_pcs.add(pc)

        # Per-connection state
        buffer = bytearray()
        resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        datachannel: Optional[object] = None
        audio_finished = asyncio.Event()

        async def _send_result_and_close() -> None:
            """Run plugin on buffered audio, send via datachannel, close."""
            if buffer and datachannel is not None:
                audio = AudioData(bytes(buffer), 16000, 2)
                transcript = model.process_audio(audio, "auto") or ""
                try:
                    datachannel.send(json.dumps({"text": transcript}))
                except Exception:
                    _LOG.exception("failed to send transcript via datachannel")
            await pc.close()
            _active_pcs.discard(pc)

        @pc.on("datachannel")
        def _on_datachannel(channel):
            """Store the opened datachannel and signal readiness to the client."""
            nonlocal datachannel
            datachannel = channel
            # Upstream sends an empty JSON to signal "listening"
            channel.send("{}")

        @pc.on("iceconnectionstatechange")
        async def _on_ice_change():
            """Close the connection on ICE failure or explicit close."""
            if pc.iceConnectionState in ("failed", "closed"):
                audio_finished.set()
                await pc.close()
                _active_pcs.discard(pc)

        @pc.on("track")
        async def _on_track(track):
            """Accept incoming audio tracks; ignore any non-audio tracks."""
            if track.kind != "audio":
                return

            async def _pump():
                """Read frames from the audio track, resample to 16 kHz mono s16."""
                try:
                    while True:
                        frame = await track.recv()
                        for resampled in resampler.resample(frame):
                            buffer.extend(
                                bytes(resampled.planes[0])[: resampled.samples * 2]
                            )
                except Exception:
                    pass
                finally:
                    audio_finished.set()
                    await _send_result_and_close()

            asyncio.create_task(_pump())

            @track.on("ended")
            async def _on_ended():
                """Signal that the audio track has finished."""
                audio_finished.set()

        await pc.setRemoteDescription(offer_desc)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return SDPAnswer(
            sdp=pc.localDescription.sdp,
            type=pc.localDescription.type,
        )

    return router
