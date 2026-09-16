# Licensed under the Apache License, Version 2.0
"""Deepgram-compatible STT endpoint (REST + WebSocket streaming)."""
import json
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Header, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from ovos_plugin_manager.utils.audio import AudioData


class DeepgramWord(BaseModel):
    """A single word with timing in a Deepgram transcript."""
    word: str
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)


class DeepgramAlternative(BaseModel):
    """A single transcription alternative."""
    transcript: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    words: List[DeepgramWord] = Field(default_factory=list)


class DeepgramChannel(BaseModel):
    """A single audio channel's transcription results."""
    alternatives: List[DeepgramAlternative]


class DeepgramResults(BaseModel):
    """Top-level results container."""
    channels: List[DeepgramChannel]


class DeepgramMetadata(BaseModel):
    """Request metadata in Deepgram response."""
    request_id: str
    created: str
    duration: float = Field(..., ge=0.0)
    channels: int = Field(default=1, ge=1)
    models: List[str] = Field(default_factory=lambda: ["general"])


class DeepgramResponse(BaseModel):
    """Full Deepgram transcription response."""
    metadata: DeepgramMetadata
    results: DeepgramResults


def make_deepgram_router(model) -> APIRouter:
    """Create Deepgram-compatible router."""
    router = APIRouter(prefix="/deepgram", tags=["deepgram"])

    @router.post("/v1/listen", response_model=DeepgramResponse)
    async def listen(
            request: Request,
            language: str = Query(default="en"),
            model_name: Optional[str] = Query(default=None, alias="model"),
            punctuate: Optional[bool] = Query(default=None),
            diarize: Optional[bool] = Query(default=None),
            authorization: Optional[str] = Header(default=None),
    ) -> DeepgramResponse:
        """Transcribe audio (Deepgram-compatible).

        Args:
            request: Raw request whose body contains audio bytes.
            language: BCP-47 language code.
            model_name: Model name (accepted, ignored).
            punctuate: Punctuation flag (accepted, ignored).
            diarize: Diarization flag (accepted, ignored).
            authorization: Token auth header (accepted, ignored).

        Returns:
            DeepgramResponse with transcription results.
        """
        audio_bytes = await request.body()
        # Default 16kHz 16-bit mono
        audio = AudioData(audio_bytes, 16000, 2)
        start = time.time()
        transcript = model.process_audio(audio, language)
        duration = time.time() - start

        return DeepgramResponse(
            metadata=DeepgramMetadata(
                request_id=str(uuid.uuid4()),
                created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                duration=duration,
                channels=1,
                models=["ovos"],
            ),
            results=DeepgramResults(
                channels=[
                    DeepgramChannel(
                        alternatives=[
                            DeepgramAlternative(
                                transcript=transcript or "",
                                confidence=1.0,
                                words=[],
                            )
                        ]
                    )
                ]
            ),
        )

    @router.websocket("/v1/listen")
    async def listen_ws(
            ws: WebSocket,
            encoding: Optional[str] = Query(default=None),
            sample_rate: Optional[int] = Query(default=16000),
            channels: Optional[int] = Query(default=1),
            language: str = Query(default="en"),
    ) -> None:
        """Streaming WebSocket endpoint matching Deepgram's wire format.

        Real Deepgram streams partial results from a VAD-driven engine; OVOS
        STT plugins are batch-only, so this implementation buffers every
        binary frame until the client closes the socket (or sends a JSON
        `CloseStream` control message), then emits a single `Results`
        message followed by `Metadata` and closes.

        Inbound:
          - binary frames: raw audio bytes (encoding/sample_rate from query)
          - text frames: JSON control messages — `{"type": "CloseStream"}`
            triggers final transcription; `{"type": "KeepAlive"}` is acked
            with an empty ping reply.

        Outbound (JSON):
          - one `Results` message with is_final=true, speech_final=true
          - one `Metadata` message with request_id/duration
        """
        await ws.accept()
        request_id = str(uuid.uuid4())
        buffer = bytearray()
        sr = sample_rate or 16000
        sw = 2  # OVOS plugins expect 16-bit PCM
        start = time.time()
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if (data := msg.get("bytes")) is not None:
                    buffer.extend(data)
                    continue
                if (text := msg.get("text")) is not None:
                    try:
                        ctrl = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    ctype = ctrl.get("type")
                    if ctype == "CloseStream":
                        break
                    if ctype == "KeepAlive":
                        # Real DG echoes nothing; just keep the socket alive.
                        continue
        except WebSocketDisconnect:
            pass

        # Run OVOS plugin on the full buffer and emit canonical DG frames.
        if buffer and ws.client_state == WebSocketState.CONNECTED:
            audio = AudioData(bytes(buffer), sr, sw)
            transcript = model.process_audio(audio, language) or ""
            duration = time.time() - start
            await ws.send_text(json.dumps({
                "type": "Results",
                "channel_index": [0, 1],
                "duration": duration,
                "start": 0.0,
                "is_final": True,
                "speech_final": True,
                "channel": {
                    "alternatives": [{
                        "transcript": transcript,
                        "confidence": 1.0,
                        "words": [],
                    }],
                },
                "metadata": {
                    "request_id": request_id,
                    "model_info": {"name": "ovos", "version": "1.0"},
                },
            }))
            await ws.send_text(json.dumps({
                "type": "Metadata",
                "request_id": request_id,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "duration": duration,
                "channels": channels or 1,
                "models": ["ovos"],
            }))

        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()

    return router
