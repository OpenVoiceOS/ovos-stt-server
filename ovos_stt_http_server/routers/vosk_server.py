# Licensed under the Apache License, Version 2.0
"""Vosk-server-compatible WebSocket protocol.

Reference: https://github.com/alphacep/vosk-server/blob/master/websocket/asr_server.py
Protocol summary:
  - Client connects via WS (any path; bare host:port is canonical)
  - Client sends JSON `{"config": {"sample_rate": 16000}}` once at start
  - Client streams binary audio frames (16-bit PCM)
  - Client sends JSON `{"eof": 1}` to finalise
  - Server emits:
      `{"partial": "..."}` for in-progress partials
      `{"text": "..."}` for finals
      `{"text": "..."}` after eof — final result
"""
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ovos_plugin_manager.utils.audio import AudioData


def make_vosk_server_router(model) -> APIRouter:
    """Create a vosk-server-compatible WebSocket router.

    Vosk-server canonically lives at the bare host root; we expose it under
    ``/vosk`` so it coexists with other compat routers on the same FastAPI app.
    Behind nginx the path can be rewritten back to ``/`` for client compat.

    Args:
        model: An OVOS STT plugin instance exposing ``process_audio(audio, lang)``.

    Returns:
        APIRouter registered at ``/vosk`` with two WebSocket endpoints (``""``
        and ``"/"`` — both map to the same handler for tooling that appends a
        trailing slash).
    """
    router = APIRouter(prefix="/vosk", tags=["vosk-server"])

    @router.websocket("")
    @router.websocket("/")
    async def asr(ws: WebSocket) -> None:
        """Handle a vosk-server WebSocket session.

        Frame sequence expected from the client:

        1. ``{"config": {"sample_rate": <int>}}`` — optional config frame.
        2. Zero or more binary frames containing raw 16-bit PCM audio.
        3. ``{"eof": 1}`` — signals end of stream; triggers transcription.

        The server replies with ``{"partial": "..."}`` during streaming (this
        implementation always sends an empty partial after each audio frame to
        satisfy clients that wait for it) and ``{"text": "..."}`` as the final
        result after ``eof`` or on disconnect.

        Args:
            ws: The FastAPI WebSocket connection object.
        """
        await ws.accept()
        buffer = bytearray()
        sample_rate = 16000
        sample_width = 2
        language = "en"
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if (data := msg.get("bytes")) is not None:
                    buffer.extend(data)
                    # Emit an empty partial so clients that await a partial reply
                    # do not stall.
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_text(json.dumps({"partial": ""}))
                    continue
                if (text := msg.get("text")) is not None:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if "config" in payload:
                        cfg = payload["config"] or {}
                        if "sample_rate" in cfg:
                            try:
                                sample_rate = int(cfg["sample_rate"])
                            except (ValueError, TypeError):
                                pass
                        # vosk-server allows passing the model dir / lang
                        # through config — accept and ignore unknown keys.
                        continue
                    if payload.get("eof") == 1:
                        break
        except WebSocketDisconnect:
            pass

        if buffer and ws.client_state == WebSocketState.CONNECTED:
            audio = AudioData(bytes(buffer), sample_rate, sample_width)
            transcript = model.process_audio(audio, language) or ""
            await ws.send_text(json.dumps({"text": transcript}))
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()

    return router
