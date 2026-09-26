# Licensed under the Apache License, Version 2.0
"""Google Cloud Speech-to-Text v1-compatible STT endpoint.

Implements the REST surface of the Google Cloud Speech v1 API so that
clients configured with a URL-rewrite or monkey-patch pointing at this
server can call ``SpeechClient.recognize`` without modification.

Wire format reference:
  POST /google/v1/speech:recognize
  Body: JSON-serialised ``RecognizeRequest`` (camelCase, audio.content is base64).
  Response: JSON-serialised ``RecognizeResponse``.
"""
import base64
import io
import wave
from typing import List, Optional, Union

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from ovos_plugin_manager.utils.audio import AudioData


class GoogleSTTConfig(BaseModel):
    """Recognition configuration mirroring ``google.cloud.speech_v1.RecognitionConfig``.

    The SDK serialises ``AudioEncoding`` as an int (e.g. ``1`` for ``LINEAR16``);
    the REST API also accepts the string name.  Either form is accepted — the
    OVOS plugin ignores the encoding value and works off the raw bytes.
    """

    encoding: Optional[Union[str, int]] = Field(default="LINEAR16")
    sampleRateHertz: Optional[int] = Field(default=16000, gt=0)
    languageCode: Optional[str] = Field(default="en-US")
    maxAlternatives: Optional[int] = Field(default=1, ge=1, le=30)
    enableAutomaticPunctuation: Optional[bool] = None


class GoogleSTTAudio(BaseModel):
    """Audio input: inline base64 ``content`` or a GCS ``uri``."""

    content: Optional[str] = None
    uri: Optional[str] = None


class GoogleSTTRequest(BaseModel):
    """Request body for ``POST /google/v1/speech:recognize``."""

    config: Optional[GoogleSTTConfig] = None
    audio: Optional[GoogleSTTAudio] = None


class GoogleSTTAlternative(BaseModel):
    """A single recognition hypothesis."""

    transcript: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    words: List = Field(default_factory=list)


class GoogleSTTResult(BaseModel):
    """A single recognition result segment with alternatives and metadata."""

    alternatives: List[GoogleSTTAlternative] = Field(..., min_length=1)
    channelTag: int = Field(default=0)
    languageCode: str = Field(default="")


class GoogleSTTResponse(BaseModel):
    """Response for ``POST /google/v1/speech:recognize``."""

    results: List[GoogleSTTResult]


def make_google_stt_router(model) -> APIRouter:
    """Create a Google Cloud Speech v1-compatible REST router.

    The returned router exposes ``POST /google/v1/speech:recognize``.
    Clients using the official ``google-cloud-speech`` SDK can reach it by
    monkey-patching ``AuthorizedSession.request`` to prepend the server's
    base URL and the ``/google`` prefix (see ``docs/api-compatibility.md``).

    Args:
        model: Any object with a ``process_audio(audio, lang)`` method that
               returns a transcription string.

    Returns:
        An ``APIRouter`` with the Google STT endpoint registered under the
        ``/google`` prefix.
    """
    router = APIRouter(prefix="/google", tags=["google-stt"])

    @router.post("/v1/speech:recognize", response_model=GoogleSTTResponse)
    def recognize(
            body: GoogleSTTRequest,
            key: Optional[str] = Query(default=None),
            authorization: Optional[str] = Header(default=None),
    ) -> GoogleSTTResponse:
        """Transcribe audio via the Google Cloud STT v1 JSON interface.

        Accepts ``audio.content`` (base64-encoded audio bytes) together with
        an optional ``config`` block.  Returns a JSON body matching the shape
        of ``google.cloud.speech_v1.RecognizeResponse``.

        Args:
            body: Parsed ``RecognizeRequest`` body (config + audio).
            key: API key query parameter (accepted but ignored).
            authorization: Bearer-token header (accepted but ignored).

        Returns:
            ``GoogleSTTResponse`` with a ``results`` list.

        Raises:
            HTTPException 400: when ``audio`` is absent, ``audio.uri`` is
                supplied (not supported locally), ``audio.content`` is
                missing, or the base64 payload is malformed.
        """
        if body.audio is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="audio is required.",
            )
        if body.audio.uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="audio.uri (GCS) is not supported; supply audio.content (base64).",
            )
        if not body.audio.content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="audio.content (base64-encoded audio) is required.",
            )

        try:
            audio_bytes = base64.b64decode(body.audio.content)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="audio.content is not valid base64.",
            ) from exc

        config = body.config or GoogleSTTConfig()
        sr = config.sampleRateHertz or 16000
        lang = config.languageCode or "en-US"

        # Attempt to parse as WAV; fall back to raw PCM at the declared rate.
        try:
            with wave.open(io.BytesIO(audio_bytes)) as wf:
                sr = wf.getframerate()
                sw = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
            audio = AudioData(raw, sr, sw)
        except Exception:
            audio = AudioData(audio_bytes, sr, 2)

        transcript = model.process_audio(audio, lang) or ""
        if not transcript:
            return GoogleSTTResponse(results=[])

        return GoogleSTTResponse(
            results=[
                GoogleSTTResult(
                    alternatives=[GoogleSTTAlternative(transcript=transcript, confidence=0.9)],
                    channelTag=0,
                    languageCode=lang,
                )
            ]
        )

    return router
