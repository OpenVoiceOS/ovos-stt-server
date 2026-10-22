# Licensed under the Apache License, Version 2.0
"""AWS Transcribe-compatible STT — batch job flow.

Implements the boto3-compatible batch endpoints:
  POST /aws/transcribe       (action=StartTranscriptionJob, GetTranscriptionJob, etc.)

boto3 sends every API call as a single POST to the service host with the
action name in the X-Amz-Target header (or in JSON body for the JSON-1.1
protocol). We dispatch on X-Amz-Target.

Job results are kept in-process; the SDK fetches the transcript JSON from
the `TranscriptFileUri` returned by GetTranscriptionJob, so we also expose
a side-channel `GET /aws/transcribe/results/{id}` for that fetch.

Streaming (transcribestreaming.<region>.amazonaws.com) uses AWS event-stream
framing over HTTP/2; we approximate it with a WebSocket bridge at
`/aws/transcribestreaming/stream-transcription` that accepts binary audio
frames and emits Transcript events matching the SDK's parsed shape.
"""
import io
import json
import time
import uuid
import wave
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from starlette.websockets import WebSocketState

from ovos_plugin_manager.utils.audio import AudioData


# In-process job store. Maps job id → dict.
_jobs: Dict[str, Dict] = {}


# ----------------------------------------------------------------------
# Action handlers
# ----------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _start_transcription_job(body: dict, base_url: str, model) -> dict:
    """Handle the StartTranscriptionJob action.

    Accepts an optional ``data:audio/wav;base64,<payload>`` MediaFileUri so
    callers can embed audio inline without an S3 bucket.  External URIs are
    accepted but not fetched — the job completes immediately with an empty
    transcript (same as the real service for an unreachable media file).
    """
    job_name = body.get("TranscriptionJobName") or str(uuid.uuid4())
    media = body.get("Media") or {}
    media_uri = media.get("MediaFileUri") or media.get("RedactedMediaFileUri")
    language_code = body.get("LanguageCode") or "en-US"

    # We don't fetch external S3 URIs. boto3 callers that need batch
    # transcription should either upload locally or use our streaming
    # surface. For drop-in compat we accept and return a "completed" job
    # with empty transcript — the same way the API would for a missing file.
    transcript_text = ""
    if media_uri and media_uri.startswith("data:"):
        try:
            # data:audio/wav;base64,<payload>
            payload = media_uri.split(",", 1)[1]
            import base64 as _b64
            wav = _b64.b64decode(payload)
            with wave.open(io.BytesIO(wav)) as wf:
                sr, sw = wf.getframerate(), wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
            transcript_text = model.process_audio(AudioData(raw, sr, sw),
                                                  language_code) or ""
        except Exception:
            transcript_text = ""

    _jobs[job_name] = {
        "TranscriptionJobName": job_name,
        "TranscriptionJobStatus": "COMPLETED",
        "LanguageCode": language_code,
        "MediaSampleRateHertz": 16000,
        "MediaFormat": media.get("MediaFormat", "wav"),
        "Media": media,
        "Transcript": {
            "TranscriptFileUri": f"{base_url}/aws/transcribe/results/{job_name}",
        },
        "CreationTime": time.time(),
        "StartTime": time.time(),
        "CompletionTime": time.time(),
        "_text": transcript_text,
    }
    return {"TranscriptionJob": _public_job(_jobs[job_name])}


def _public_job(job: dict) -> dict:
    """Strip private fields (those starting with _) before returning to client."""
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _get_transcription_job(body: dict, **_) -> dict:
    """Handle the GetTranscriptionJob action.

    Raises HTTP 400 when the job name is unknown (matches the real service).
    """
    name = body.get("TranscriptionJobName")
    if not name or name not in _jobs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"BadRequestException: Job {name!r} not found",
        )
    return {"TranscriptionJob": _public_job(_jobs[name])}


def _list_transcription_jobs(**_) -> dict:
    """Handle the ListTranscriptionJobs action.

    Returns a summary list of all in-process jobs.
    """
    return {
        "TranscriptionJobSummaries": [
            {"TranscriptionJobName": n,
             "TranscriptionJobStatus": j["TranscriptionJobStatus"]}
            for n, j in _jobs.items()
        ],
    }


def _delete_transcription_job(body: dict, **_) -> dict:
    """Handle the DeleteTranscriptionJob action.

    Silently no-ops if the job does not exist (matches real service behaviour).
    """
    _jobs.pop(body.get("TranscriptionJobName", ""), None)
    return {}


ACTIONS = {
    "Transcribe.StartTranscriptionJob": _start_transcription_job,
    "Transcribe.GetTranscriptionJob": _get_transcription_job,
    "Transcribe.ListTranscriptionJobs": _list_transcription_jobs,
    "Transcribe.DeleteTranscriptionJob": _delete_transcription_job,
}


# ----------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------

class AWSStartJobRequest(BaseModel):
    """boto3 sends the action in X-Amz-Target and the body as JSON-1.1."""
    TranscriptionJobName: Optional[str] = None
    LanguageCode: Optional[str] = "en-US"
    Media: Optional[dict] = None
    MediaFormat: Optional[str] = None


def make_aws_transcribe_router(model) -> APIRouter:
    """AWS Transcribe-compatible router (batch + streaming WS).

    Args:
        model: ModelContainer or MultiModelContainer instance.
    """
    router = APIRouter(prefix="/aws", tags=["aws-transcribe"])

    @router.post("/transcribe")
    async def transcribe_action(request: Request) -> dict:
        """Single dispatching endpoint for all Transcribe batch actions.

        boto3 (and the AWS CLI / SDK) routes every batch API call to the
        service root and identifies the action via the X-Amz-Target header.
        """
        action = request.headers.get("x-amz-target", "")
        handler = ACTIONS.get(action)
        if handler is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"UnknownOperationException: {action!r}",
            )
        body = await request.json() if (await request.body()) else {}
        base_url = str(request.base_url).rstrip("/")
        try:
            return handler(body=body, base_url=base_url, model=model)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"InternalFailureException: {exc}",
            )

    @router.get("/transcribe/results/{job_name}")
    def transcript_result(job_name: str) -> dict:
        """The transcript JSON the SDK fetches from TranscriptFileUri."""
        if job_name not in _jobs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            )
        job = _jobs[job_name]
        text = job["_text"]
        return {
            "jobName": job_name,
            "accountId": "ovos-stt-http-server",
            "results": {
                "transcripts": [{"transcript": text}],
                "items": [],
            },
            "status": job["TranscriptionJobStatus"],
        }

    @router.websocket("/transcribestreaming/stream-transcription")
    async def stream_transcription(ws: WebSocket) -> None:
        """Streaming transcription WS surface.

        AWS upstream uses HTTP/2 + AWS event-stream framing; we expose a
        plain WebSocket variant where binary frames carry raw PCM audio
        and a final empty frame signals end-of-stream. The server emits a
        single Transcript event matching the boto3 parsed shape.
        """
        await ws.accept()
        sample_rate = int(ws.query_params.get("sample-rate", 16000))
        language = ws.query_params.get("language-code", "en-US")
        buffer = bytearray()
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if (data := msg.get("bytes")) is not None:
                    if not data:
                        break
                    buffer.extend(data)
                if (text := msg.get("text")) is not None:
                    try:
                        if json.loads(text).get("eventType") == "EndStream":
                            break
                    except json.JSONDecodeError:
                        continue
        except WebSocketDisconnect:
            pass

        if buffer and ws.client_state == WebSocketState.CONNECTED:
            audio = AudioData(bytes(buffer), sample_rate, 2)
            transcript = model.process_audio(audio, language) or ""
            await ws.send_text(json.dumps({
                "Transcript": {
                    "Results": [{
                        "Alternatives": [{
                            "Transcript": transcript,
                            "Items": [],
                        }],
                        "IsPartial": False,
                        "StartTime": 0.0,
                        "EndTime": len(buffer) / (sample_rate * 2),
                        "ResultId": str(uuid.uuid4()),
                    }],
                },
            }))
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()

    return router
