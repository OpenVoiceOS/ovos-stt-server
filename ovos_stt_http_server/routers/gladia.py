# Licensed under the Apache License, Version 2.0
"""Gladia-compatible STT endpoints.

Gladia's v2 API is a three-step asynchronous flow:

1. ``POST /v2/upload`` — multipart audio upload, returns an ``audio_url``.
2. ``POST /v2/transcription`` — JSON ``{"audio_url": ...}``, returns an ``id``
   and a ``result_url``.
3. ``GET /v2/transcription/{id}`` — poll until ``status == "done"``; the result
   carries ``result.transcription.full_transcript``.

OVOS STT plugins are batch engines, so this router keeps an in-memory job store
and runs transcription synchronously at step 2: the job is already ``done`` by
the time the client polls, but the full async wire format is preserved so that
existing Gladia clients work unchanged.

Usage::

    from ovos_stt_http_server.routers.gladia import make_gladia_router
    app.include_router(make_gladia_router(model))
"""
import time
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, File, HTTPException, Header, UploadFile
from pydantic import BaseModel, Field

from ovos_plugin_manager.utils.audio import AudioData


class GladiaUploadResponse(BaseModel):
    """Response for POST /v2/upload."""
    audio_url: str
    audio_metadata: dict = Field(default_factory=dict)


class GladiaTranscriptionRequest(BaseModel):
    """Request body for POST /v2/transcription."""
    audio_url: str
    language: Optional[str] = None
    detect_language: bool = True


class GladiaTranscriptionInit(BaseModel):
    """Response for POST /v2/transcription (job accepted)."""
    id: str
    result_url: str


def make_gladia_router(model, base_url: str = "") -> APIRouter:
    """Create a Gladia-compatible router and attach it to *model*.

    Implements the three-step upload → transcription → poll flow with a
    synchronous in-memory job store. Audio uploaded at ``/v2/upload`` is held
    in memory keyed by a generated ``audio_url`` and transcribed when the
    matching ``/v2/transcription`` request arrives; the result is then served
    by ``GET /v2/transcription/{id}``.

    Args:
        model: Any object with ``process_audio(audio: AudioData, lang: str)``
            returning a transcription string.
        base_url: Optional absolute base (e.g. ``http://host:8080``) used to
            build ``audio_url``/``result_url`` values. Defaults to relative
            paths, which is sufficient for SDK clients that resolve against
            their configured base.

    Returns:
        Configured :class:`~fastapi.APIRouter` prefixed with ``/gladia``.
    """
    router = APIRouter(prefix="/gladia", tags=["gladia"])

    # audio_url -> {data, sr, sw};  job id -> result dict
    _uploads: Dict[str, AudioData] = {}
    _jobs: Dict[str, dict] = {}

    def _url(path: str) -> str:
        return f"{base_url}{path}" if base_url else path

    @router.post("/v2/upload", response_model=GladiaUploadResponse)
    async def upload(
        audio: UploadFile = File(...),
        x_gladia_key: Optional[str] = Header(default=None, alias="x-gladia-key"),
    ) -> GladiaUploadResponse:
        """Accept an audio upload and return a handle ``audio_url``."""
        data = await audio.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio file.")
        key = uuid.uuid4().hex
        # default 16kHz 16-bit mono; OVOS plugins normalise internally
        _uploads[key] = AudioData(data, 16000, 2)
        return GladiaUploadResponse(
            audio_url=_url(f"/gladia/v2/upload/{key}"),
            audio_metadata={"filename": audio.filename or "audio"},
        )

    @router.post("/v2/transcription", response_model=GladiaTranscriptionInit, status_code=201)
    async def transcription(
        req: GladiaTranscriptionRequest,
        x_gladia_key: Optional[str] = Header(default=None, alias="x-gladia-key"),
    ) -> GladiaTranscriptionInit:
        """Run transcription synchronously and register a finished job."""
        key = req.audio_url.rstrip("/").split("/")[-1]
        audio = _uploads.get(key)
        if audio is None:
            raise HTTPException(status_code=404, detail="Unknown audio_url.")
        lang = req.language or "auto"
        transcript = model.process_audio(audio, lang) or ""
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "id": job_id,
            "status": "done",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "result": {
                "transcription": {
                    "full_transcript": transcript,
                    "languages": [lang if lang != "auto" else "en"],
                    "utterances": [],
                },
            },
        }
        return GladiaTranscriptionInit(id=job_id, result_url=_url(f"/gladia/v2/transcription/{job_id}"))

    @router.get("/v2/transcription/{job_id}")
    async def get_transcription(
        job_id: str,
        x_gladia_key: Optional[str] = Header(default=None, alias="x-gladia-key"),
    ) -> dict:
        """Return the finished job result (Gladia poll endpoint)."""
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown transcription id.")
        return job

    return router
