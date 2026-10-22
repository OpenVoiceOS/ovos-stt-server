# Licensed under the Apache License, Version 2.0
"""Chromium / Chrome Web Speech API-compatible router.

Wire format reverse-engineered in
[OpenVoiceOS/ovos-stt-plugin-chromium](https://github.com/OpenVoiceOS/ovos-stt-plugin-chromium):

  POST http://www.google.com/speech-api/v2/recognize
       ?client=chromium&lang=<bcp47>&key=<scraped-key>&pFilter=0
  Content-Type: audio/x-flac; rate=<sample_rate>
  Body: FLAC-encoded audio

Response is **two lines** of JSON:
  {"result":[]}
  {"result":[{"alternative":[{"transcript":"...","confidence":0.83},...],
              "final":true}],"result_index":0}

We accept any `Content-Type` starting with `audio/`, decode it via
`pydub` (which can read FLAC, WAV, mp3, …), and run the OVOS plugin.
"""
import io
import json
import re
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import PlainTextResponse

from ovos_plugin_manager.utils.audio import AudioData


def _decode_audio(body: bytes, content_type: str) -> AudioData:
    """Decode any common audio container into PCM AudioData.

    Chrome uses FLAC by default; we accept anything pydub can read.
    """
    # Pull a hint for the input format from the Content-Type
    fmt = "flac"
    if content_type:
        ct = content_type.lower()
        if "wav" in ct:
            fmt = "wav"
        elif "ogg" in ct:
            fmt = "ogg"
        elif "mp3" in ct or "mpeg" in ct:
            fmt = "mp3"
        elif "x-raw" in ct or "l16" in ct:
            # Raw PCM — extract rate hint, treat as 16-bit mono
            m = re.search(r"rate[=\s]*(\d+)", ct)
            rate = int(m.group(1)) if m else 16000
            return AudioData(body, rate, 2)

    try:
        from pydub import AudioSegment
    except ImportError:
        # Last-resort: treat the body as already-PCM at 16k 16-bit
        return AudioData(body, 16000, 2)

    audio = AudioSegment.from_file(io.BytesIO(body), format=fmt)
    audio = audio.set_channels(1).set_sample_width(2)
    return AudioData(audio.raw_data, audio.frame_rate, audio.sample_width)


def make_chromium_router(model) -> APIRouter:
    """Chromium / Chrome Web Speech API-compatible router.

    Args:
        model: ModelContainer / MultiModelContainer instance.
    """
    router = APIRouter(prefix="/speech-api", tags=["chromium"])

    @router.post("/v2/recognize", response_class=PlainTextResponse)
    async def recognize(
            request: Request,
            client: Optional[str] = Query(default="chromium"),
            lang: str = Query(default="en-US"),
            key: Optional[str] = Query(default=None),
            pFilter: Optional[int] = Query(default=0),
    ) -> str:
        """Recognise a Chromium-formatted speech request.

        The response shape mirrors the upstream wire — first line is an
        empty `{"result":[]}`, second line carries alternatives. Some
        upstream clients only parse the second line, others parse the
        whole response as NDJSON; we emit both for compatibility.
        """
        body = await request.body()
        content_type = request.headers.get("Content-Type", "audio/x-flac")
        audio = _decode_audio(body, content_type)
        transcript = model.process_audio(audio, lang) or ""

        first = json.dumps({"result": []})
        if not transcript:
            return f"{first}\n"
        second = json.dumps({
            "result": [{
                "alternative": [
                    {"transcript": transcript, "confidence": 0.99},
                ],
                "final": True,
            }],
            "result_index": 0,
        })
        return f"{first}\n{second}\n"

    return router
