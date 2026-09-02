# Licensed under the Apache License, Version 2.0
"""OpenAI Whisper-compatible STT endpoints.

Implements ``POST /openai/v1/audio/transcriptions`` (and
``/openai/v1/audio/translations``) using the multipart/form-data wire format
sent by the official ``openai`` Python SDK (``openai>=1.0``).

Usage::

    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router
    app.include_router(make_openai_whisper_router(model))

Then point the SDK at the server::

    from openai import OpenAI
    client = OpenAI(api_key="ignored", base_url="http://localhost:8080/openai/v1")
    result = client.audio.transcriptions.create(file=audio_bytes, model="whisper-1")
"""
import io
import time
import wave
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from ovos_config import Configuration
from pydantic import BaseModel, Field

from ovos_plugin_manager.utils.audio import AudioData


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TranscriptionResponse(BaseModel):
    """Minimal OpenAI transcription response (``response_format=json``, default)."""

    text: str = Field(..., description="Transcribed text.")


class TranscriptionSegment(BaseModel):
    """A single segment in a verbose JSON response."""

    id: int
    seek: int = 0
    start: float
    end: float
    text: str
    tokens: List[int] = Field(default_factory=list)
    temperature: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 1.0
    no_speech_prob: float = 0.0


class VerboseTranscriptionResponse(BaseModel):
    """OpenAI verbose_json transcription response."""

    task: str = "transcribe"
    language: str = "en"
    duration: float
    text: str
    segments: List[TranscriptionSegment] = Field(default_factory=list)
    words: List[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _audio_data_from_upload(file_bytes: bytes, sample_rate: int = 16000, sample_width: int = 2) -> AudioData:
    """Convert uploaded file bytes to an :class:`AudioData` instance.

    Tries to parse the bytes as a WAV container first so that sample-rate and
    sample-width are extracted automatically.  Falls back to the supplied
    defaults (16 kHz, 16-bit PCM) for raw/non-WAV formats.

    Args:
        file_bytes: Raw bytes from the multipart upload.
        sample_rate: Fallback sample rate when WAV metadata is unavailable.
        sample_width: Fallback sample width (bytes) when WAV metadata is
            unavailable.

    Returns:
        AudioData suitable for passing to ``model.process_audio``.
    """
    try:
        buf = io.BytesIO(file_bytes)
        with wave.open(buf, "r") as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            file_bytes = wf.readframes(wf.getnframes())
    except Exception:
        pass  # not a WAV — use raw bytes with defaults
    return AudioData(file_bytes, sample_rate, sample_width)


def _resolve_lang(language: Optional[str]) -> str:
    """Resolve a requested language to a concrete BCP-47 tag.

    ``None``/``"auto"`` fall back to the server's configured default language
    (``mycroft.conf``'s top-level ``lang``), and finally to ``"en"`` if that
    is itself unset or ``"auto"``. STT plugins expect a concrete language and
    error out on a literal ``"auto"`` tag.

    Args:
        language: BCP-47 language code, or ``None``/``"auto"`` for auto-detect.

    Returns:
        A concrete BCP-47 language code, never ``"auto"``.
    """
    lang = language or "auto"
    if lang == "auto":
        lang = Configuration().get("lang") or "en"
        if lang == "auto":
            lang = "en"
    return lang


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def make_openai_whisper_router(model, translator=None) -> APIRouter:
    """Create an OpenAI Whisper-compatible router and attach it to *model*.

    The router exposes:
    - ``POST /openai/v1/audio/transcriptions`` — transcribe audio to text.
    - ``POST /openai/v1/audio/translations`` — transcribe, then translate to English.

    Both endpoints accept ``multipart/form-data`` with at least ``file`` and
    ``model`` fields, exactly as sent by the official ``openai`` Python SDK.

    Args:
        model: Any object with a ``process_audio(audio: AudioData, lang: str)``
            method that returns a transcription string.
        translator: Optional OVOS ``LanguageTranslator`` (with a
            ``translate(text, target, source)`` method). OpenAI's
            ``/audio/translations`` always returns English, so when a translator
            is provided the transcript is translated to English after ASR. If
            ``None``, the transcript is returned untranslated.

    Returns:
        Configured :class:`~fastapi.APIRouter` prefixed with ``/openai``.
    """
    router = APIRouter(prefix="/openai", tags=["openai-whisper"])

    async def _transcribe(
        file: UploadFile,
        language: Optional[str],
        response_format: str,
        temperature: float,
        translate: bool = False,
    ):
        """Shared transcription logic used by both endpoints.

        Args:
            file: Uploaded audio file from the multipart form.
            language: BCP-47 language code, or ``None`` for auto-detect.
            response_format: One of ``json``, ``text``, ``verbose_json``,
                ``srt``, ``vtt``.
            temperature: Sampling temperature (accepted, not used by OVOS).
            translate: When ``True``, translate the transcript to English after
                ASR (the OpenAI ``/audio/translations`` contract).

        Returns:
            Response object appropriate for the requested ``response_format``.

        Raises:
            HTTPException: 400 if *file* is empty, 422 if *response_format*
                is unknown.
        """
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        audio = _audio_data_from_upload(file_bytes)
        lang = _resolve_lang(language)

        start = time.time()
        transcript = model.process_audio(audio, lang) or ""
        # OpenAI /audio/translations always returns English: transcribe in the
        # source language, then translate the text to English (extra step after
        # ASR) using the configured OVOS translate plugin.
        if translate and translator is not None and transcript:
            try:
                transcript = translator.translate(
                    transcript, target="en", source=lang,
                ) or transcript
            except Exception:
                pass  # fall back to the untranslated transcript
        if translate:
            lang = "en"
        duration = time.time() - start

        fmt = (response_format or "json").lower()

        if fmt == "text":
            return PlainTextResponse(content=transcript)

        if fmt == "srt":
            srt = f"1\n00:00:00,000 --> 00:00:{duration:06.3f}\n{transcript}\n\n"
            return PlainTextResponse(content=srt, media_type="text/plain")

        if fmt == "vtt":
            vtt = f"WEBVTT\n\n00:00:00.000 --> 00:00:{duration:06.3f}\n{transcript}\n\n"
            return PlainTextResponse(content=vtt, media_type="text/plain")

        if fmt == "verbose_json":
            obj = VerboseTranscriptionResponse(
                language=lang,
                duration=round(duration, 3),
                text=transcript,
                segments=[
                    TranscriptionSegment(
                        id=0,
                        start=0.0,
                        end=round(duration, 3),
                        text=transcript,
                    )
                ] if transcript else [],
            )
            return JSONResponse(content=obj.model_dump())

        if fmt == "json":
            return JSONResponse(content={"text": transcript})

        raise HTTPException(
            status_code=422,
            detail=f"Unsupported response_format: {response_format!r}. "
                   f"Use one of: json, text, verbose_json, srt, vtt.",
        )

    @router.post(
        "/v1/audio/transcriptions",
        summary="Transcribe audio (OpenAI Whisper-compatible)",
    )
    async def transcriptions(
        file: UploadFile = File(..., description="Audio file to transcribe."),
        model_name: str = Form(..., alias="model", description="Model name (accepted, ignored)."),
        language: Optional[str] = Form(default=None, description="BCP-47 language code."),
        prompt: Optional[str] = Form(default=None, description="Prompt hint (accepted, ignored)."),
        response_format: Optional[str] = Form(default="json", description="Response format."),
        temperature: Optional[float] = Form(default=0.0, description="Sampling temperature (ignored)."),
        timestamp_granularities: Optional[str] = Form(default=None, description="Granularities (ignored)."),
    ):
        """Transcribe audio to text using the OVOS STT plugin.

        Accepts ``multipart/form-data`` as sent by the official ``openai``
        Python SDK.  The ``model`` field is required for SDK compatibility but
        is not forwarded to the OVOS engine.

        Args:
            file: Uploaded audio file (WAV, MP3, OGG, FLAC, …).
            model_name: Whisper model name (e.g. ``whisper-1``); accepted but
                ignored — the OVOS plugin is always used.
            language: Optional BCP-47 language tag.  Defaults to ``auto``.
            prompt: Optional transcription hint; accepted, not used.
            response_format: Output format — ``json`` (default), ``text``,
                ``verbose_json``, ``srt``, or ``vtt``.
            temperature: Sampling temperature; accepted, not used.
            timestamp_granularities: Word/segment granularity; accepted, not
                used.

        Returns:
            ``{"text": "..."}`` for ``json`` (default), plain text for
            ``text``/``srt``/``vtt``, or a verbose object for
            ``verbose_json``.
        """
        return await _transcribe(file, language, response_format or "json", temperature or 0.0)

    @router.post(
        "/v1/audio/translations",
        summary="Translate audio to English (OpenAI Whisper-compatible)",
    )
    async def translations(
        file: UploadFile = File(..., description="Audio file to translate."),
        model_name: str = Form(..., alias="model", description="Model name (accepted, ignored)."),
        prompt: Optional[str] = Form(default=None, description="Prompt hint (accepted, ignored)."),
        response_format: Optional[str] = Form(default="json", description="Response format."),
        temperature: Optional[float] = Form(default=0.0, description="Sampling temperature (ignored)."),
    ):
        """Translate audio to English text using the OVOS STT plugin.

        The OVOS engine always transcribes in the detected or specified
        language; true translation is not performed.  This endpoint exists so
        that SDK callers targeting ``/audio/translations`` receive a valid
        response without errors.

        Args:
            file: Uploaded audio file.
            model_name: Whisper model name; accepted, ignored.
            prompt: Optional hint; accepted, not used.
            response_format: Output format (same options as transcriptions).
            temperature: Sampling temperature; accepted, not used.

        Returns:
            Same format as ``/audio/transcriptions``.
        """
        # Language forced to "en" for translation semantics.
        # auto-detect the source language, then translate the transcript to English
        return await _transcribe(file, None, response_format or "json",
                                 temperature or 0.0, translate=True)

    return router
