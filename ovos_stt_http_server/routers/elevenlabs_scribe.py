# Licensed under the Apache License, Version 2.0
"""ElevenLabs Scribe-compatible STT endpoint.

ElevenLabs' speech-to-text product (Scribe) exposes a single
``POST /v1/speech-to-text`` endpoint that accepts ``multipart/form-data`` with
a ``file`` part and a ``model_id`` field, authenticated with an ``xi-api-key``
header.  The JSON response carries ``language_code``, ``language_probability``,
``text`` and a ``words`` array.

Usage::

    from ovos_stt_http_server.routers.elevenlabs_scribe import make_elevenlabs_scribe_router
    app.include_router(make_elevenlabs_scribe_router(model))

Then point the SDK at the server::

    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key="ignored", base_url="http://localhost:8080")
    result = client.speech_to_text.convert(file=audio, model_id="scribe_v1")
"""
import io
import wave
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Header, UploadFile
from pydantic import BaseModel, Field

from ovos_plugin_manager.utils.audio import AudioData


class ScribeWord(BaseModel):
    """A single token in a Scribe transcript."""
    text: str
    type: str = "word"
    start: float = 0.0
    end: float = 0.0


class ScribeResponse(BaseModel):
    """ElevenLabs Scribe speech-to-text response."""
    language_code: str = Field(..., description="Detected/declared language.")
    language_probability: float = Field(default=1.0, ge=0.0, le=1.0)
    text: str = Field(..., description="Full transcript.")
    words: List[ScribeWord] = Field(default_factory=list)


def _audio_data_from_upload(file_bytes: bytes, sample_rate: int = 16000, sample_width: int = 2) -> AudioData:
    """Wrap uploaded bytes in AudioData, reading WAV metadata when present."""
    try:
        with wave.open(io.BytesIO(file_bytes), "r") as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            file_bytes = wf.readframes(wf.getnframes())
    except Exception:
        pass  # not a WAV — use raw bytes with defaults
    return AudioData(file_bytes, sample_rate, sample_width)


def make_elevenlabs_scribe_router(model) -> APIRouter:
    """Create an ElevenLabs Scribe-compatible router and attach it to *model*.

    Exposes ``POST /elevenlabs/v1/speech-to-text``. The ``model_id`` and
    ``xi-api-key`` fields are accepted for client compatibility but not
    forwarded to the OVOS engine.

    Args:
        model: Any object with ``process_audio(audio: AudioData, lang: str)``
            returning a transcription string.

    Returns:
        Configured :class:`~fastapi.APIRouter` prefixed with ``/elevenlabs``.
    """
    router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs-scribe"])

    @router.post(
        "/v1/speech-to-text",
        response_model=ScribeResponse,
        summary="Transcribe audio (ElevenLabs Scribe-compatible)",
    )
    async def speech_to_text(
        file: UploadFile = File(..., description="Audio file to transcribe."),
        model_id: str = Form(default="scribe_v1", description="Model id (accepted, ignored)."),
        language_code: Optional[str] = Form(default=None, description="ISO-639 language code."),
        xi_api_key: Optional[str] = Header(default=None, alias="xi-api-key", description="API key (accepted, ignored)."),
    ) -> ScribeResponse:
        """Transcribe audio using the OVOS STT plugin, Scribe response shape."""
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        audio = _audio_data_from_upload(file_bytes)
        lang = language_code or "auto"
        transcript = model.process_audio(audio, lang) or ""

        return ScribeResponse(
            language_code=lang if lang != "auto" else "en",
            language_probability=1.0,
            text=transcript,
            words=[],
        )

    return router
