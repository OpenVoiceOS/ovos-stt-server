# Licensed under the Apache License, Version 2.0
"""AssemblyAI-compatible STT endpoint (REST + realtime WebSocket)."""
import base64
import io
import json
import time
import uuid
import wave
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Header, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from ovos_plugin_manager.utils.audio import AudioData


# In-process store of uploaded audio: id → raw bytes. The official AssemblyAI
# SDK does a two-step POST /v2/upload → POST /v2/transcript flow, so we need
# to retain bytes between calls.
_UPLOAD_STORE: Dict[str, bytes] = {}
_TRANSCRIPT_STORE: Dict[str, "AssemblyAITranscript"] = {}


class AssemblyAIUploadResponse(BaseModel):
    """Response from POST /v2/upload."""
    upload_url: str


class AssemblyAIRequest(BaseModel):
    """Request body for POST /v2/transcript."""
    audio_url: Optional[str] = None
    audio: Optional[str] = Field(default=None, description="Base64-encoded audio bytes")
    language_code: Optional[str] = Field(default=None, min_length=1)
    punctuate: Optional[bool] = None
    format_text: Optional[bool] = None
    disfluencies: Optional[bool] = None
    speaker_labels: Optional[bool] = None


class AssemblyAIWord(BaseModel):
    """Word-level timing information."""
    text: str
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)


class AssemblyAITranscript(BaseModel):
    """AssemblyAI transcript response."""
    id: str
    status: Literal["queued", "processing", "completed", "error"] = "completed"
    audio_url: Optional[str] = None
    text: Optional[str] = None
    words: List[AssemblyAIWord] = Field(default_factory=list)
    language_code: Optional[str] = None
    audio_duration: Optional[float] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    error: Optional[str] = None


def make_assemblyai_router(model) -> APIRouter:
    """Create AssemblyAI-compatible router (synchronous stub)."""
    router = APIRouter(prefix="/assemblyai", tags=["assemblyai"])

    @router.post("/v2/upload", response_model=AssemblyAIUploadResponse)
    async def upload(request: Request) -> AssemblyAIUploadResponse:
        """Store raw audio bytes and return an upload URL usable in /transcript.

        The official AssemblyAI SDK calls this endpoint first, then references
        the returned URL via `audio_url` in the subsequent /transcript POST.
        """
        body = await request.body()
        upload_id = str(uuid.uuid4())
        _UPLOAD_STORE[upload_id] = body
        base = str(request.base_url).rstrip("/")
        return AssemblyAIUploadResponse(upload_url=f"{base}/assemblyai/v2/uploads/{upload_id}")

    @router.post("/v2/transcript", response_model=AssemblyAITranscript)
    def create_transcript(
            request: AssemblyAIRequest,
            authorization: Optional[str] = Header(default=None),
    ) -> AssemblyAITranscript:
        """Transcribe audio (AssemblyAI-compatible, synchronous stub).

        Accepts base64 audio in the `audio` field. The `audio_url` field is
        acknowledged but audio fetching is not supported — supply `audio` instead.

        Args:
            request: AssemblyAI transcript request.
            authorization: API key header (accepted, ignored).

        Returns:
            AssemblyAITranscript with status 'completed' and transcript text.
        """
        job_id = str(uuid.uuid4())
        lang = request.language_code or "en"

        # Resolve audio bytes from one of three sources:
        # - request.audio: base64-encoded inline
        # - request.audio_url pointing at our own /v2/uploads/{id} (SDK flow)
        # - anything else: not supported
        audio_bytes = None
        if request.audio:
            try:
                audio_bytes = base64.b64decode(request.audio)
            except Exception as exc:
                return AssemblyAITranscript(
                    id=job_id, status="error",
                    audio_url=request.audio_url, error=str(exc),
                )
        elif request.audio_url and "/assemblyai/v2/uploads/" in request.audio_url:
            upload_id = request.audio_url.rstrip("/").rsplit("/", 1)[-1]
            audio_bytes = _UPLOAD_STORE.pop(upload_id, None)
            if audio_bytes is None:
                return AssemblyAITranscript(
                    id=job_id, status="error",
                    audio_url=request.audio_url,
                    error=f"unknown upload id: {upload_id}",
                )
        else:
            return AssemblyAITranscript(
                id=job_id, status="error",
                audio_url=request.audio_url,
                error="audio_url fetching is not supported for external URLs; "
                      "upload via POST /v2/upload first or supply base64 'audio'.",
            )

        try:
            with wave.open(io.BytesIO(audio_bytes)) as wf:
                sr = wf.getframerate()
                sw = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
            audio = AudioData(raw, sr, sw)
        except Exception:
            audio = AudioData(audio_bytes, 16000, 2)
        transcript_text = model.process_audio(audio, lang)

        # SDK requires audio_url to be set on the response; synthesise one if
        # the caller went the inline-base64 route.
        audio_url = request.audio_url or f"inline://{job_id}"
        transcript = AssemblyAITranscript(
            id=job_id,
            status="completed",
            audio_url=audio_url,
            text=transcript_text or "",
            language_code=lang,
            confidence=0.9,
        )
        _TRANSCRIPT_STORE[job_id] = transcript
        return transcript

    @router.get("/v2/transcript/{transcript_id}", response_model=AssemblyAITranscript)
    def get_transcript(
            transcript_id: str,
            authorization: Optional[str] = Header(default=None),
    ) -> AssemblyAITranscript:
        """Get transcript by ID (AssemblyAI-compatible stub).

        Since this server is synchronous, all transcripts are immediately
        completed. This endpoint returns a not-found stub.

        Args:
            transcript_id: ID of the transcript to retrieve.
            authorization: API key header (accepted, ignored).

        Returns:
            AssemblyAITranscript stub with error status.
        """
        stored = _TRANSCRIPT_STORE.get(transcript_id)
        if stored is not None:
            return stored
        return AssemblyAITranscript(
            id=transcript_id,
            status="error",
            audio_url=f"unknown://{transcript_id}",
            error="Transcript not found.",
        )

    @router.websocket("/v2/realtime/ws")
    async def realtime_ws(ws: WebSocket) -> None:
        """Realtime WS endpoint matching AssemblyAI's wire format.

        Real-time AssemblyAI streams partial+final transcripts from a VAD-driven
        engine; OVOS STT plugins are batch-only, so this implementation buffers
        every chunk (sent as JSON `{"audio_data": "<base64>"}` per the SDK
        wire format) until the client sends `{"terminate_session": true}` or
        disconnects, then emits one FinalTranscript + SessionTerminated and
        closes.
        """
        await ws.accept()
        session_id = str(uuid.uuid4())
        sample_rate = int(ws.query_params.get("sample_rate", 16000))
        await ws.send_text(json.dumps({
            "message_type": "SessionBegins",
            "session_id": session_id,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S.000000",
                                        time.gmtime(time.time() + 3600)),
        }))
        buffer = bytearray()
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
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("terminate_session"):
                        break
                    if (audio_b64 := payload.get("audio_data")) is not None:
                        try:
                            buffer.extend(base64.b64decode(audio_b64))
                        except Exception:
                            continue
                    if payload.get("force_end_utterance"):
                        # SDK sends this to flush. Treat like terminate for our
                        # batch-only backend (we emit one transcript total).
                        break
        except WebSocketDisconnect:
            pass

        if buffer and ws.client_state == WebSocketState.CONNECTED:
            audio = AudioData(bytes(buffer), sample_rate, 2)
            transcript_text = model.process_audio(audio, "en") or ""
            duration_ms = int((time.time() - start) * 1000)
            await ws.send_text(json.dumps({
                "message_type": "FinalTranscript",
                "text": transcript_text,
                "confidence": 1.0,
                "audio_start": 0,
                "audio_end": duration_ms,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                         time.gmtime()),
                "punctuated": True,
                "text_formatted": True,
                "words": [],
            }))
            await ws.send_text(json.dumps({
                "message_type": "SessionTerminated",
            }))

        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()

    @router.websocket("/v3/ws")
    async def streaming_v3_ws(ws: WebSocket) -> None:
        """Universal-Streaming (v3) WS endpoint — what the current SDK uses.

        The v3 ``StreamingClient`` connects to ``/v3/ws``, streams raw PCM as
        binary frames and sends ``{"type":"Terminate"}`` to finish. OVOS STT
        plugins are batch-only, so buffer the audio and emit a single
        ``Begin`` → ``Turn`` (final) → ``Termination`` sequence.
        """
        await ws.accept()
        session_id = str(uuid.uuid4())
        sample_rate = int(ws.query_params.get("sample_rate", 16000))
        await ws.send_text(json.dumps({
            "type": "Begin",
            "id": session_id,
            "expires_at": int(time.time() + 3600),
        }))
        buffer = bytearray()
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
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "Terminate":
                        break
        except WebSocketDisconnect:
            pass

        if ws.client_state == WebSocketState.CONNECTED:
            transcript_text = ""
            if buffer:
                audio = AudioData(bytes(buffer), sample_rate, 2)
                transcript_text = model.process_audio(audio, "en") or ""
            await ws.send_text(json.dumps({
                "type": "Turn",
                "turn_order": 0,
                "turn_is_formatted": True,
                "end_of_turn": True,
                "transcript": transcript_text,
                "end_of_turn_confidence": 1.0,
                "words": [],
            }))
            await ws.send_text(json.dumps({
                "type": "Termination",
                "audio_duration_seconds": int(len(buffer) / (sample_rate * 2)),
                "session_duration_seconds": int(time.time() - start),
            }))
            await ws.close()

    return router
