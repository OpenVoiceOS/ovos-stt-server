# Licensed under the Apache License, Version 2.0
"""IBM Watson Speech-to-Text — REST `/v1/recognize` + WS streaming."""
import json
import time
from typing import List, Optional

from fastapi import (APIRouter, Header, Query, Request, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from ovos_plugin_manager.utils.audio import AudioData
from ovos_stt_http_server.audio_utils import multipart_audio_to_audiodata


class WatsonAlternative(BaseModel):
    """A single transcription hypothesis from the Watson STT service."""

    transcript: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class WatsonResult(BaseModel):
    """One utterance result matching IBM Watson ``SpeechRecognitionResult``."""

    alternatives: List[WatsonAlternative]
    final: bool = True


class WatsonResponse(BaseModel):
    """Canonical Watson STT response shape."""
    results: List[WatsonResult]
    result_index: int = 0


def _make_response(text: str) -> WatsonResponse:
    """Build a ``WatsonResponse`` with a single final alternative."""
    return WatsonResponse(
        results=[WatsonResult(
            alternatives=[WatsonAlternative(transcript=text)],
            final=True,
        )],
    )


def make_ibm_watson_stt_router(model) -> APIRouter:
    """IBM Watson STT-compatible router."""
    router = APIRouter(prefix="/watson/speech-to-text", tags=["ibm-watson-stt"])

    @router.post("/v1/recognize", response_model=WatsonResponse)
    async def recognize(
            request: Request,
            model_name: str = Query(default="en-US_BroadbandModel", alias="model"),
            language_customization_id: Optional[str] = Query(default=None),
            authorization: Optional[str] = Header(default=None),
    ) -> WatsonResponse:
        """REST recognise — accepts raw audio body."""
        audio_bytes = await request.body()
        # The SDK sends `audio/wav` or `audio/l16;rate=16000`. Try WAV first;
        # fall back to raw PCM @16k/16-bit.
        try:
            audio = multipart_audio_to_audiodata(audio_bytes, "audio.wav")
        except Exception:
            audio = AudioData(audio_bytes, 16000, 2)
        lang = model_name.split("_", 1)[0] if "_" in model_name else "en-US"
        text = model.process_audio(audio, lang) or ""
        return _make_response(text)

    @router.websocket("/v1/recognize")
    async def recognize_ws(ws: WebSocket) -> None:
        """Watson STT WS streaming protocol.

        Wire format:
          - Client sends `{"action":"start","content-type":"audio/l16;rate=16000",...}`
          - Server replies `{"state":"listening"}`
          - Client streams binary audio frames
          - Client sends `{"action":"stop"}` (or closes the socket)
          - Server emits `{"results":[...]}` + final `{"state":"listening"}`

        OVOS plugins are batch-only; we buffer audio for the lifetime of the
        recognition turn and emit one final result on stop/disconnect.
        """
        await ws.accept()
        await ws.send_text(json.dumps({"state": "listening"}))
        buffer = bytearray()
        sample_rate = 16000
        sample_width = 2
        language = "en-US"
        started = False
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if (data := msg.get("bytes")) is not None:
                    if started:
                        buffer.extend(data)
                    continue
                if (text := msg.get("text")) is not None:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    action = payload.get("action")
                    if action == "start":
                        ct = payload.get("content-type") or ""
                        if "rate=" in ct:
                            try:
                                sample_rate = int(ct.split("rate=", 1)[1]
                                                  .split(";", 1)[0])
                            except ValueError:
                                pass
                        if "l16" in ct or "pcm" in ct:
                            sample_width = 2
                        model_param = payload.get("model")
                        if isinstance(model_param, str) and "_" in model_param:
                            language = model_param.split("_", 1)[0]
                        started = True
                        continue
                    if action == "stop":
                        break
        except WebSocketDisconnect:
            pass

        if buffer and ws.client_state == WebSocketState.CONNECTED:
            audio = AudioData(bytes(buffer), sample_rate, sample_width)
            transcript = model.process_audio(audio, language) or ""
            await ws.send_text(_make_response(transcript).model_dump_json())
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(json.dumps({"state": "listening"}))
            await ws.close()

    return router
