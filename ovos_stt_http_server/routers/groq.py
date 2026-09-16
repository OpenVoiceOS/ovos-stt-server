# Licensed under the Apache License, Version 2.0
"""Groq-compatible STT endpoint.

Groq serves Whisper through an OpenAI-compatible surface rooted at
``/openai/v1``.  Existing Groq clients (the official ``groq`` SDK, or the
``openai`` SDK pointed at ``https://api.groq.com/openai/v1``) send
``multipart/form-data`` to ``POST /openai/v1/audio/transcriptions`` exactly as
the OpenAI Whisper API does; the JSON response carries an extra ``x_groq``
metadata block.

Usage::

    from ovos_stt_http_server.routers.groq import make_groq_router
    app.include_router(make_groq_router(model))

Then point the SDK at the server::

    from groq import Groq
    client = Groq(api_key="ignored", base_url="http://localhost:8080")
    result = client.audio.transcriptions.create(file=audio, model="whisper-large-v3")
"""
import io
import time
import uuid
import wave
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Header, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from ovos_plugin_manager.utils.audio import AudioData


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


def make_groq_router(model) -> APIRouter:
    """Create a Groq-compatible router and attach it to *model*.

    Exposes ``POST /groq/openai/v1/audio/transcriptions`` accepting the same
    ``multipart/form-data`` payload as the OpenAI Whisper API. The ``model`` and
    auth fields are accepted for client compatibility but not forwarded to the
    OVOS engine.

    Args:
        model: Any object with ``process_audio(audio: AudioData, lang: str)``
            returning a transcription string.

    Returns:
        Configured :class:`~fastapi.APIRouter` prefixed with ``/groq``.
    """
    router = APIRouter(prefix="/groq", tags=["groq"])

    @router.post(
        "/openai/v1/audio/transcriptions",
        summary="Transcribe audio (Groq Whisper-compatible)",
    )
    async def transcriptions(
        file: UploadFile = File(..., description="Audio file to transcribe."),
        model_name: str = Form(..., alias="model", description="Model name (accepted, ignored)."),
        language: Optional[str] = Form(default=None, description="ISO-639-1 language code."),
        prompt: Optional[str] = Form(default=None, description="Prompt hint (accepted, ignored)."),
        response_format: Optional[str] = Form(default="json", description="json, text or verbose_json."),
        temperature: Optional[float] = Form(default=0.0, description="Sampling temperature (ignored)."),
        authorization: Optional[str] = Header(default=None, description="Bearer token (accepted, ignored)."),
    ):
        """Transcribe audio using the OVOS STT plugin, Groq response shape.

        Returns ``{"text": ..., "x_groq": {...}}`` for ``json``/``verbose_json``
        (the extra ``x_groq`` block is what distinguishes Groq from plain
        OpenAI), or plain text for ``text``.
        """
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        audio = _audio_data_from_upload(file_bytes)
        lang = language or "auto"
        transcript = model.process_audio(audio, lang) or ""

        fmt = (response_format or "json").lower()
        if fmt == "text":
            return PlainTextResponse(content=transcript)
        if fmt in ("json", "verbose_json"):
            return JSONResponse(content={
                "text": transcript,
                "x_groq": {"id": f"req_{uuid.uuid4().hex[:24]}"},
            })
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported response_format: {response_format!r}. "
                   f"Use one of: json, text, verbose_json.",
        )

    return router
