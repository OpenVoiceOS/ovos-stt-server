# Licensed under the Apache License, Version 2.0
"""Microsoft Azure Speech (Cognitive Services) STT — REST + WebSocket streaming.

REST: short-form recognition (≤60s WAV body)
WS:   bidirectional streaming using Microsoft's proprietary HTTP-style
      header framing on top of WebSocket text/binary frames.
"""
import json
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.websockets import WebSocketState

from ovos_plugin_manager.utils.audio import AudioData
from ovos_stt_http_server.audio_utils import multipart_audio_to_audiodata


# ----------------------------------------------------------------------
# REST response model
# ----------------------------------------------------------------------

class AzureRESTResponse(BaseModel):
    """Canonical short-form REST response.

    Reference: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-speech-to-text-short
    """
    RecognitionStatus: str = "Success"
    DisplayText: str = ""
    Offset: int = 0
    Duration: int = 0


# ----------------------------------------------------------------------
# Microsoft WS framing helpers (text / binary)
# ----------------------------------------------------------------------

def _parse_text(raw: str) -> tuple[dict, str]:
    """Parse a Microsoft WS text frame: HTTP-style headers + blank line + body."""
    head, _, body = raw.partition("\r\n\r\n")
    headers: dict = {}
    for line in head.split("\r\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip()] = v.strip()
    return headers, body


def _parse_binary(raw: bytes) -> tuple[dict, bytes]:
    """Parse a Microsoft WS binary frame: 2B BE header-length, headers, body."""
    if len(raw) < 2:
        return {}, b""
    header_len = int.from_bytes(raw[:2], "big")
    head = raw[2 : 2 + header_len].decode("ascii", errors="replace")
    body = raw[2 + header_len :]
    headers: dict = {}
    for line in head.replace("\r\n\r\n", "").split("\r\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip()] = v.strip()
    return headers, body


def _build_text(path: str, request_id: str, body: str,
                content_type: str = "application/json; charset=utf-8") -> str:
    """Build a Microsoft WS text frame: headers + blank line + body."""
    head = (
        f"X-RequestId:{request_id}\r\n"
        f"X-Timestamp:{time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())}\r\n"
        f"Path:{path}\r\n"
        f"Content-Type:{content_type}\r\n"
    )
    return head + "\r\n" + body


# ----------------------------------------------------------------------
# Helpers shared between REST + WS
# ----------------------------------------------------------------------

_SSML_VOICE_RE = re.compile(r'<voice[^>]*name="([^"]+)"', re.I)


def _ms_units(seconds: float) -> int:
    """Convert seconds to 100-nanosecond units (Microsoft's Offset/Duration unit)."""
    return int(seconds * 10_000_000)


# ----------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------

def make_azure_stt_router(model) -> APIRouter:
    """Microsoft Azure Speech STT-compatible router.

    Args:
        model: ModelContainer or MultiModelContainer instance.

    Returns:
        Configured APIRouter — exposes both REST and WS at the canonical
        path `/azure-stt/cognitiveservices/v1`.
    """
    router = APIRouter(prefix="/azure-stt", tags=["azure-stt"])

    # -------- REST: short-form recognition --------
    @router.post(
        "/cognitiveservices/v1",
        response_model=AzureRESTResponse,
    )
    async def recognize(
            request: Request,
            language: str = Query(default="en-US"),
            format: str = Query(default="simple"),
            authorization: Optional[str] = Header(default=None),
            ocp_apim_subscription_key: Optional[str] = Header(
                default=None, alias="Ocp-Apim-Subscription-Key"),
    ) -> AzureRESTResponse:
        """REST short-form recognition.

        Body: WAV bytes (≤60s upstream; we don't enforce). Auth headers
        accepted and ignored.
        """
        audio_bytes = await request.body()
        audio = multipart_audio_to_audiodata(audio_bytes, "audio.wav")
        text = model.process_audio(audio, language) or ""
        # Duration = audio length in 100-ns units (not processing latency)
        audio_seconds = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
        return AzureRESTResponse(
            RecognitionStatus="Success" if text else "InitialSilenceTimeout",
            DisplayText=text,
            Offset=0,
            Duration=_ms_units(audio_seconds),
        )

    # -------- WS: streaming recognition --------
    @router.websocket("/cognitiveservices/v1")
    async def recognize_ws(ws: WebSocket) -> None:
        """Microsoft Azure Speech WS streaming protocol.

        OVOS STT plugins are batch-only, so this implementation buffers every
        audio binary frame for the lifetime of the WS turn and emits a single
        canonical Microsoft frame sequence on speech end:

          turn.start → speech.startDetected → speech.hypothesis →
          speech.endDetected → speech.phrase → turn.end

        Inbound:
          - text frames: speech.config (ack), speech.context (ack)
          - binary frames: header-prefixed audio chunks (Path: audio)
          - text frame: speech.audio.end (treated as terminate)
          - WS close

        Supports multi-turn connections: state resets on each turn.start cycle.
        """
        await ws.accept()
        language = ws.query_params.get("language", "en-US")
        # Connection-level identifiers
        conn_request_id = uuid.uuid4().hex
        try:
            while ws.client_state == WebSocketState.CONNECTED:
                turn_request_id = uuid.uuid4().hex
                buffer = bytearray()
                turn_started = False
                turn_lang = language
                start = time.time()
                try:
                    while True:
                        msg = await ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            return
                        if (data := msg.get("bytes")) is not None:
                            headers, body = _parse_binary(data)
                            path = headers.get("Path", "audio")
                            if path == "audio":
                                if not turn_started:
                                    # First audio chunk = start of turn
                                    await ws.send_text(_build_text(
                                        "turn.start",
                                        headers.get("X-RequestId", turn_request_id),
                                        json.dumps({"context": {
                                            "serviceTag": "ovos-stt-http-server",
                                        }}),
                                    ))
                                    await ws.send_text(_build_text(
                                        "speech.startDetected",
                                        headers.get("X-RequestId", turn_request_id),
                                        json.dumps({"Offset": 0}),
                                    ))
                                    turn_started = True
                                    if "X-RequestId" in headers:
                                        turn_request_id = headers["X-RequestId"]
                                # Audio body may be empty in the last frame
                                if body:
                                    buffer.extend(body)
                                # An empty audio binary frame upstream signals end-of-stream
                                if not body and turn_started:
                                    break
                            continue
                        if (text := msg.get("text")) is not None:
                            headers, body = _parse_text(text)
                            path = headers.get("Path", "")
                            if path == "speech.config":
                                # Connection config — acknowledged silently
                                continue
                            if path == "speech.context":
                                # Per-turn context — parse for language override
                                try:
                                    ctx = json.loads(body) if body else {}
                                    lang_hint = ctx.get("languageId", {}).get("languages") \
                                        if isinstance(ctx, dict) else None
                                    if isinstance(lang_hint, list) and lang_hint:
                                        turn_lang = lang_hint[0]
                                except json.JSONDecodeError:
                                    pass
                                if "X-RequestId" in headers:
                                    turn_request_id = headers["X-RequestId"]
                                continue
                            if path == "speech.audio.end":
                                if turn_started:
                                    break
                                continue
                except WebSocketDisconnect:
                    return

                # Finalise: run plugin and emit closing frame sequence.
                # Always emit all 4 frames when a turn was started, even if
                # no audio was buffered (empty-body terminator, or
                # speech.audio.end before any audio chunks arrived).
                if turn_started and ws.client_state == WebSocketState.CONNECTED:
                    if buffer:
                        audio = AudioData(bytes(buffer), 16000, 2)
                        transcript = model.process_audio(audio, turn_lang) or ""
                        audio_seconds = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
                    else:
                        transcript = ""
                        audio_seconds = 0.0
                    duration_ticks = _ms_units(audio_seconds)
                    await ws.send_text(_build_text(
                        "speech.hypothesis",
                        turn_request_id,
                        json.dumps({
                            "Text": transcript,
                            "Offset": 0,
                            "Duration": duration_ticks,
                        }),
                    ))
                    await ws.send_text(_build_text(
                        "speech.endDetected",
                        turn_request_id,
                        json.dumps({"Offset": duration_ticks}),
                    ))
                    await ws.send_text(_build_text(
                        "speech.phrase",
                        turn_request_id,
                        json.dumps({
                            "RecognitionStatus": "Success" if transcript else "InitialSilenceTimeout",
                            "DisplayText": transcript,
                            "Offset": 0,
                            "Duration": duration_ticks,
                        }),
                    ))
                    await ws.send_text(_build_text(
                        "turn.end",
                        turn_request_id,
                        "{}",
                    ))
                # Loop continues for the next turn (multi-turn connection).
                if ws.client_state != WebSocketState.CONNECTED:
                    return
        except WebSocketDisconnect:
            return

    return router
