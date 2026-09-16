# Licensed under the Apache License, Version 2.0
"""whisper.cpp server-compatible STT router.

Emulates the HTTP API of the official ``whisper.cpp`` server binary
(https://github.com/ggerganov/whisper.cpp/tree/master/examples/server).

The router is mounted under the ``/whisper-cpp`` prefix so it owns a unique
URL namespace like every other vendor router — in particular this keeps its
OpenAI-compatible alias from colliding with the dedicated OpenAI Whisper
router (which owns ``/v1``). Relative to that prefix it exposes the two
upstream whisper.cpp server paths:

* ``POST /whisper-cpp/inference`` — native whisper.cpp multipart endpoint.
* ``POST /whisper-cpp/v1/audio/transcriptions`` — OpenAI-compatible endpoint;
  semantically identical to ``/whisper-cpp/inference``.

Both accept ``multipart/form-data`` with at minimum a ``file`` field.
Extra form fields (``temperature``, ``response_format``, ``language``,
``prompt``, ``translate``, …) mirror the real server's contract and are
forwarded to the OVOS STT plugin where relevant.

Response shape when ``response_format`` is ``"json"`` (the default)::

    {"text": "<transcript>"}

When ``response_format="text"`` the raw transcript string is returned as
``text/plain``.
"""
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ovos_stt_http_server.audio_utils import multipart_audio_to_audiodata


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class WhisperCppResponse(BaseModel):
    """JSON response returned by both whisper.cpp endpoints."""

    text: str


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def make_whisper_cpp_server_router(model) -> APIRouter:
    """Create an ``APIRouter`` that emulates the whisper.cpp HTTP server API.

    The router uses the upstream ``whisper.cpp`` server's own paths under the
    ``/whisper-cpp`` prefix, so a client pointed at a real whisper.cpp server
    works against this router by changing only its base URL to ``…/whisper-cpp``:

    * ``POST /whisper-cpp/inference`` — native multipart inference endpoint.
    * ``POST /whisper-cpp/v1/audio/transcriptions`` — OpenAI-compatible alias.

    Args:
        model: Any object that exposes
               ``process_audio(audio: AudioData, lang: str) -> str``.
               Typically a ``ModelContainer`` or ``MultiModelContainer``.

    Returns:
        Configured ``APIRouter`` ready to pass to
        ``app.include_router(...)``.
    """
    router = APIRouter(prefix="/whisper-cpp", tags=["whisper-cpp-server"])

    async def _transcribe(
        file: UploadFile,
        language: Optional[str],
        response_format: Optional[str],
    ):
        """Shared transcription logic for both endpoints.

        Reads the uploaded file, converts it to ``AudioData`` via
        ``multipart_audio_to_audiodata``, runs it through the OVOS STT
        model, and returns either a JSON or plain-text response.

        Args:
            file: Uploaded audio file (UploadFile from FastAPI).
            language: BCP-47 language code, or ``None`` / ``"auto"`` for
                      language auto-detection.
            response_format: ``"json"`` (default) or ``"text"``.

        Returns:
            ``JSONResponse`` containing ``{"text": "..."}`` when format is
            ``"json"``; ``PlainTextResponse`` with the raw transcript when
            format is ``"text"``.
        """
        file_bytes = await file.read()
        audio = multipart_audio_to_audiodata(file_bytes, file.filename or "audio.wav")
        text = model.process_audio(audio, language or "auto") or ""
        if (response_format or "json").lower() == "text":
            return PlainTextResponse(text)
        return JSONResponse(WhisperCppResponse(text=text).model_dump())

    @router.post(
        "/inference",
        summary="Native whisper.cpp inference endpoint",
    )
    async def inference(
        file: UploadFile = File(..., description="Audio file to transcribe."),
        temperature: Optional[str] = Form(default=None),
        temperature_inc: Optional[str] = Form(default=None),
        response_format: Optional[str] = Form(default="json"),
        language: Optional[str] = Form(default=None),
        prompt: Optional[str] = Form(default=None),
        translate: Optional[bool] = Form(default=False),
    ):
        """Transcribe audio — native whisper.cpp ``POST /inference`` endpoint.

        Accepts ``multipart/form-data`` with a mandatory ``file`` field.
        Additional fields mirror the real server's contract:

        * ``temperature`` / ``temperature_inc`` — accepted, ignored.
        * ``response_format`` — ``"json"`` (default) or ``"text"``.
        * ``language`` — BCP-47 code; omit for auto-detection.
        * ``prompt`` — initial prompt; accepted, ignored.
        * ``translate`` — accepted, ignored (translation is handled by a
          separate OVOS plugin pipeline when needed).

        Args:
            file: Audio file upload (WAV, MP3, OGG, FLAC, …).
            temperature: Sampling temperature (accepted, ignored).
            temperature_inc: Temperature increment (accepted, ignored).
            response_format: ``"json"`` (default) or ``"text"``.
            language: BCP-47 language code; omit for auto-detection.
            prompt: Initial prompt hint (accepted, ignored).
            translate: Translation flag (accepted, ignored).

        Returns:
            ``{"text": "<transcript>"}`` for JSON format; plain text
            otherwise.
        """
        return await _transcribe(file, language, response_format)

    @router.post(
        "/v1/audio/transcriptions",
        summary="OpenAI-compatible audio transcription endpoint",
    )
    async def transcriptions(
        file: UploadFile = File(..., description="Audio file to transcribe."),
        model_name: Optional[str] = Form(default=None, alias="model"),
        language: Optional[str] = Form(default=None),
        prompt: Optional[str] = Form(default=None),
        response_format: Optional[str] = Form(default="json"),
        temperature: Optional[float] = Form(default=None),
    ):
        """Transcribe audio — OpenAI-compatible ``POST /v1/audio/transcriptions``.

        Identical in semantics to ``POST /inference``; provided so that
        any client built against the OpenAI Whisper API or the whisper.cpp
        server's OpenAI-compat layer works without modification.

        Args:
            file: Audio file upload (WAV, MP3, OGG, FLAC, …).
            model_name: Model identifier (accepted, ignored).
            language: BCP-47 language code; omit for auto-detection.
            prompt: Initial prompt hint (accepted, ignored).
            response_format: ``"json"`` (default) or ``"text"``.
            temperature: Sampling temperature (accepted, ignored).

        Returns:
            ``{"text": "<transcript>"}`` for JSON format; plain text
            otherwise.
        """
        return await _transcribe(file, language, response_format)

    return router
