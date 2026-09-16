# Licensed under the Apache License, Version 2.0
"""Kaldi GStreamer Server-compatible STT router.

Wire protocol reference:
  https://github.com/alumae/kaldi-gstreamer-server

The real server exposes two WebSocket endpoints:

  ws://<host>/client/ws/speech
      Clients stream raw audio (any audio that GStreamer can read; in
      practice 16 kHz 16-bit mono RAW PCM or WAV) as binary frames and
      receive JSON transcription hypotheses:

        Partial: {"status": 0, "result": {"hypotheses": [{"transcript": "..."}], "final": false}}
        Final:   {"status": 0, "result": {"hypotheses": [{"transcript": "..."}], "final": true}}
        EOS ACK: {"status": 0, "result": {"hypotheses": [], "final": true}}

      The client signals end-of-stream by sending the text message ``EOS``.
      The server may also emit a status-only message::

        {"status": 9, "message": "Recogniser not ready"}

  ws://<host>/client/ws/status
      Emits a JSON snapshot of server capacity every few seconds; clients
      poll this to decide whether to connect for transcription.

      {"num_workers_available": 1, "num_requests_processed": 0}

OVOS STT plugins are batch-only (no streaming VAD), so this
implementation buffers all incoming binary frames until ``EOS`` (or
disconnect) and then calls ``model.process_audio`` once.
"""
import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from ovos_plugin_manager.utils.audio import AudioData
from starlette.websockets import WebSocketState

# Kaldi status codes used in the wire protocol
_STATUS_SUCCESS = 0
_STATUS_NOT_AVAILABLE = 9

# Counter for processed requests (used in status endpoint)
_requests_processed: int = 0


def make_kaldi_gstreamer_router(model) -> APIRouter:
    """Create a kaldi-gstreamer-server compatible router.

    Args:
        model: A ModelContainer or compatible object with a
            ``process_audio(audio, lang)`` method.

    Returns:
        An :class:`~fastapi.APIRouter` that can be included in a
        :class:`~fastapi.FastAPI` application.
    """
    global _requests_processed
    router = APIRouter(prefix="/client", tags=["kaldi-gstreamer"])

    @router.websocket("/ws/speech")
    async def speech_ws(
        ws: WebSocket,
        lang: Optional[str] = Query(default="en"),
        content_type: Optional[str] = Query(default=None),
        sample_rate: Optional[int] = Query(default=16000),
        sample_width: Optional[int] = Query(default=2),
    ) -> None:
        """WebSocket speech transcription endpoint (kaldi-gstreamer wire protocol).

        Clients stream binary audio frames followed by the text message
        ``EOS`` to signal end-of-stream.  The server buffers all audio,
        runs the OVOS STT plugin, and emits:

        1. A *partial* result JSON frame (``"final": false``) with the
           recognised text.
        2. A *final* result JSON frame (``"final": true``) with the same
           text, after which the connection is closed.

        Args:
            ws: The WebSocket connection managed by FastAPI/Starlette.
            lang: BCP-47 language code passed to the STT plugin.
            content_type: Hint for audio encoding (accepted but not used;
                the plugin handles decoding).
            sample_rate: PCM sample rate in Hz (default 16 000).
            sample_width: PCM sample width in bytes (default 2 for 16-bit).
        """
        global _requests_processed
        await ws.accept()

        buffer = bytearray()
        sr = sample_rate or 16000
        sw = sample_width or 2
        language = lang or "en"

        try:
            while True:
                msg = await ws.receive()

                if msg["type"] == "websocket.disconnect":
                    break

                if (data := msg.get("bytes")) is not None:
                    buffer.extend(data)
                    continue

                if (text := msg.get("text")) is not None:
                    if text.strip() == "EOS":
                        break
                    # Unknown text frames are silently ignored.
                    continue

        except WebSocketDisconnect:
            pass

        if not buffer or ws.client_state != WebSocketState.CONNECTED:
            return

        audio = AudioData(bytes(buffer), sr, sw)
        transcript = model.process_audio(audio, language) or ""
        _requests_processed += 1

        # Emit a partial result first (mirrors real kaldi-gstreamer behaviour)
        partial = {
            "status": _STATUS_SUCCESS,
            "result": {
                "hypotheses": [{"transcript": transcript}],
                "final": False,
            },
        }
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(json.dumps(partial))

        # Emit the final result
        final = {
            "status": _STATUS_SUCCESS,
            "result": {
                "hypotheses": [{"transcript": transcript}],
                "final": True,
            },
        }
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(json.dumps(final))

        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()

    @router.websocket("/ws/status")
    async def status_ws(ws: WebSocket) -> None:
        """WebSocket status endpoint (kaldi-gstreamer wire protocol).

        Emits a single JSON capacity snapshot and closes.  Real clients
        poll this before deciding whether to open a speech session.

        Payload::

            {"num_workers_available": 1, "num_requests_processed": <n>}

        Args:
            ws: The WebSocket connection managed by FastAPI/Starlette.
        """
        await ws.accept()
        status = {
            "num_workers_available": 1,
            "num_requests_processed": _requests_processed,
        }
        await ws.send_text(json.dumps(status))
        await ws.close()

    return router
