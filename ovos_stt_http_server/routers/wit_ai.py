# Licensed under the Apache License, Version 2.0
"""Wit.ai-compatible Speech endpoint.

The wit-python SDK env var `WIT_URL` lets users override the API host:
`os.environ['WIT_URL'] = 'http://localhost:8080/wit'` makes the SDK hit
our `/wit/speech?v=...` endpoint instead of `https://api.wit.ai/speech`.

We return the canonical final-result JSON shape:
  {"text": "...", "intents": [], "entities": {}, "traits": {}}
"""
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from ovos_plugin_manager.utils.audio import AudioData
from ovos_stt_http_server.audio_utils import multipart_audio_to_audiodata


class WitAIResponse(BaseModel):
    """Final-result JSON shape returned by Wit's /speech endpoint."""
    text: str
    intents: list = Field(default_factory=list)
    entities: dict = Field(default_factory=dict)
    traits: dict = Field(default_factory=dict)


def make_wit_ai_router(model) -> APIRouter:
    """Wit.ai-compatible router exposing the /speech endpoint."""
    router = APIRouter(prefix="/wit", tags=["wit-ai"])

    @router.post("/speech", response_model=WitAIResponse)
    async def speech(
            request: Request,
            v: Optional[str] = Query(default="20200513"),
            authorization: Optional[str] = Header(default=None),
    ) -> WitAIResponse:
        """Recognise speech from the request body.

        The Content-Type header tells us the encoding:
          - `audio/wav` — WAV with embedded format
          - `audio/raw;encoding=signed-integer;bits=16;rate=16000;endian=little`
            — raw PCM with parameters in the MIME type
          - anything else → try WAV decode, fall back to 16k 16-bit PCM
        """
        audio_bytes = await request.body()
        content_type = request.headers.get("Content-Type", "").lower()
        # Parse rate / bits from a Wit-style content-type header for raw PCM
        sample_rate = 16000
        sample_width = 2
        if content_type.startswith("audio/raw"):
            for kv in content_type.split(";"):
                kv = kv.strip()
                if kv.startswith("rate="):
                    try:
                        sample_rate = int(kv.split("=", 1)[1])
                    except ValueError:
                        pass
                elif kv.startswith("bits="):
                    try:
                        sample_width = max(1, int(kv.split("=", 1)[1]) // 8)
                    except ValueError:
                        pass
            audio = AudioData(audio_bytes, sample_rate, sample_width)
        else:
            try:
                audio = multipart_audio_to_audiodata(audio_bytes, "audio.wav")
            except Exception:
                audio = AudioData(audio_bytes, sample_rate, sample_width)

        text = model.process_audio(audio, "auto") or ""
        return WitAIResponse(text=text)

    return router
