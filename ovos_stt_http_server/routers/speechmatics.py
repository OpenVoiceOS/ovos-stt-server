# Licensed under the Apache License, Version 2.0
"""Speechmatics-compatible STT endpoint (batch REST + realtime WebSocket).

Batch API mirrors the Speechmatics v2 REST surface used by
``speechmatics.batch_client.BatchClient``:

- ``POST  /speechmatics/v2/jobs``          — submit audio + config, returns job_id
- ``GET   /speechmatics/v2/jobs/{job_id}`` — poll status
- ``GET   /speechmatics/v2/jobs/{job_id}/transcript`` — retrieve result

Realtime API mirrors the Speechmatics WebSocket wire protocol used by
``speechmatics.client.WebsocketClient``.  The SDK connects to
``{base_url}/{language}?sm-sdk=…`` and speaks a JSON handshake:

- Client → ``StartRecognition``
- Server → ``RecognitionStarted``
- Client → binary audio frames + ``EndOfStream`` JSON
- Server → ``AudioAdded`` (one per audio chunk), ``AddTranscript``, ``EndOfTranscript``
"""
import json
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from ovos_plugin_manager.utils.audio import AudioData
from starlette.websockets import WebSocketState


# ---------------------------------------------------------------------------
# In-memory job store (single-process; good enough for proxy/local use)
# ---------------------------------------------------------------------------

_JOB_STORE: Dict[str, Dict[str, Any]] = {}


def _make_job_id() -> str:
    """Return a unique job identifier."""
    return str(uuid.uuid4()).replace("-", "")[:16]


def make_speechmatics_router(model) -> APIRouter:
    """Create Speechmatics-compatible batch + realtime router.

    The returned router mounts at ``/speechmatics`` so that:
    - the ``speechmatics-batch`` ``AsyncClient(url='http://host/speechmatics/v2')``
      (whose base URL already includes ``/v2`` and which appends ``/jobs``)
      correctly submits to ``/speechmatics/v2/jobs``.
    - ``WebsocketClient(ConnectionSettings(url='ws://host/speechmatics/v2/rt'))``
      correctly connects to ``/speechmatics/v2/rt/{language}``.

    Args:
        model: Any object with a ``process_audio(AudioData, lang: str) -> str`` method.

    Returns:
        Configured ``APIRouter`` instance.
    """
    router = APIRouter(prefix="/speechmatics", tags=["speechmatics"])

    # ------------------------------------------------------------------
    # Batch REST endpoints
    # ------------------------------------------------------------------

    @router.post("/v2/jobs", status_code=201)
    async def submit_job(
            request: Request,
            data_file: Optional[UploadFile] = None,
    ) -> JSONResponse:
        """Accept audio + JSON config, run STT immediately, store result.

        The Speechmatics SDK POSTs multipart/form-data with two parts:
        ``config`` (JSON string) and ``data_file`` (audio bytes).  We
        transcribe synchronously and stash the result so the polling
        endpoint can return it instantly.

        Args:
            request: Raw FastAPI request (used to read multipart form).
            data_file: Audio upload part (may be None for fetch_url jobs).

        Returns:
            JSON with ``{"id": "<job_id>"}``.
        """
        content_type = request.headers.get("content-type", "")
        audio_bytes = b""
        language = "en"
        data_name = "audio"

        if "multipart" in content_type:
            form = await request.form()
            cfg_raw = form.get("config", "{}")
            if hasattr(cfg_raw, "read"):
                cfg_raw = await cfg_raw.read()
                cfg_raw = cfg_raw.decode()
            try:
                cfg = json.loads(cfg_raw)
            except (json.JSONDecodeError, TypeError):
                cfg = {}
            language = (
                cfg.get("transcription_config", {}).get("language", "en") or "en"
            )
            audio_part = form.get("data_file")
            if audio_part is not None and hasattr(audio_part, "read"):
                audio_bytes = await audio_part.read()
                data_name = getattr(audio_part, "filename", None) or data_name
        else:
            audio_bytes = await request.body()

        job_id = _make_job_id()
        transcript = ""
        if audio_bytes:
            audio = AudioData(audio_bytes, 16000, 2)
            transcript = model.process_audio(audio, language) or ""

        _JOB_STORE[job_id] = {
            "job_id": job_id,
            "status": "done",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "transcript": transcript,
            "language": language,
            "data_name": data_name,
        }
        return JSONResponse({"id": job_id}, status_code=201)

    @router.get("/v2/jobs/{job_id}")
    async def get_job_status(job_id: str) -> JSONResponse:
        """Return job status for a previously submitted job.

        Args:
            job_id: Opaque identifier returned by ``submit_job``.

        Returns:
            JSON with job details and ``status`` field (``"done"`` or ``"running"``).
        """
        job = _JOB_STORE.get(job_id)
        if job is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({
            "job": {
                "id": job["job_id"],
                "status": job["status"],
                "created_at": job["created_at"],
                "data_name": job.get("data_name", "audio"),
                "duration": 1.0,
                "config": {
                    "type": "transcription",
                    "transcription_config": {"language": job["language"]},
                },
            }
        })

    @router.get("/v2/jobs/{job_id}/transcript")
    async def get_transcript(
            job_id: str,
            format: Optional[str] = Query(default="json-v2"),
    ) -> JSONResponse:
        """Return the transcript for a completed job.

        The SDK calls this endpoint to retrieve the final transcript after
        polling ``/v2/jobs/{job_id}`` until status is ``"done"``.

        Args:
            job_id: Opaque identifier returned by ``submit_job``.
            format: Response format (accepted, ignored; always returns json-v2).

        Returns:
            Speechmatics json-v2 transcript JSON object.
        """
        job = _JOB_STORE.get(job_id)
        if job is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        transcript = job.get("transcript", "")
        words = transcript.split() if transcript else []
        results = []
        for i, word in enumerate(words):
            results.append({
                "type": "word",
                "start_time": i * 0.5,
                "end_time": (i + 1) * 0.5,
                "alternatives": [
                    {"content": word, "confidence": 1.0, "language": job["language"]}
                ],
            })
        return JSONResponse({
            "format": "2.9",
            "job": {
                "id": job_id,
                "status": "done",
                "created_at": job["created_at"],
                "data_name": job.get("data_name", "audio"),
                "duration": 1.0,
            },
            "results": results,
            "metadata": {
                "created_at": job["created_at"],
                "type": "transcription",
                "transcription_config": {"language": job["language"]},
            },
        })

    @router.delete("/v2/jobs/{job_id}", status_code=200)
    async def delete_job(job_id: str) -> JSONResponse:
        """Remove a job from the store.

        Args:
            job_id: Opaque identifier returned by ``submit_job``.

        Returns:
            JSON confirmation or 404 if not found.
        """
        if job_id not in _JOB_STORE:
            return JSONResponse({"error": "not found"}, status_code=404)
        _JOB_STORE.pop(job_id)
        return JSONResponse({"deleted": True})

    @router.get("/v2/jobs")
    async def list_jobs() -> JSONResponse:
        """List all known jobs.

        Returns:
            JSON with ``{"jobs": [...]}`` list of all job records.
        """
        jobs = [
            {
                "id": j["job_id"],
                "status": j["status"],
                "created_at": j["created_at"],
            }
            for j in _JOB_STORE.values()
        ]
        return JSONResponse({"jobs": jobs})

    # ------------------------------------------------------------------
    # Realtime WebSocket endpoint
    # ------------------------------------------------------------------

    @router.websocket("/v2/rt/{language}")
    async def realtime_ws(
            ws: WebSocket,
            language: str,
    ) -> None:
        """Speechmatics realtime WebSocket endpoint.

        Speaks the Speechmatics realtime wire protocol so that
        ``speechmatics.client.WebsocketClient`` can connect without
        modification.  OVOS STT plugins are batch-only; audio is buffered
        until ``EndOfStream`` arrives, then transcribed once and emitted
        as ``AddTranscript`` + ``EndOfTranscript``.

        Protocol (messages are JSON unless noted):
        - Client → ``{"message": "StartRecognition", "audio_format": …, …}``
        - Server → ``{"message": "RecognitionStarted", "id": …}``
        - Client → binary frames (raw PCM audio)
        - Server → ``{"message": "AudioAdded", "seq_no": N}``
        - Client → ``{"message": "EndOfStream", "last_seq_no": N}``
        - Server → ``{"message": "AddTranscript", …}``
        - Server → ``{"message": "EndOfTranscript"}``

        Args:
            ws: WebSocket connection.
            language: BCP-47 language code taken from the URL path.
        """
        await ws.accept()
        buffer = bytearray()
        seq_no = 0
        session_id = str(uuid.uuid4())
        sample_rate = 16000

        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break

                raw_bytes = msg.get("bytes")
                if raw_bytes is not None:
                    # Binary audio frame
                    buffer.extend(raw_bytes)
                    seq_no += 1
                    await ws.send_text(json.dumps({
                        "message": "AudioAdded",
                        "seq_no": seq_no,
                    }))
                    continue

                text = msg.get("text")
                if text is None:
                    continue

                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_type = ctrl.get("message", "")

                if msg_type == "StartRecognition":
                    # Extract sample rate from audio_format if provided
                    audio_fmt = ctrl.get("audio_format", {})
                    sample_rate = audio_fmt.get("sample_rate", 16000)
                    await ws.send_text(json.dumps({
                        "message": "RecognitionStarted",
                        "id": session_id,
                        "language_pack_info": {
                            "adapted": False,
                            "itn": False,
                            "language_description": language,
                            "word_delimiter": " ",
                            "writing_direction": "left-to-right",
                        },
                    }))

                elif msg_type == "EndOfStream":
                    # Transcribe buffered audio and close
                    transcript = ""
                    if buffer:
                        audio = AudioData(bytes(buffer), sample_rate, 2)
                        transcript = model.process_audio(audio, language) or ""

                    # Emit word-level transcript
                    words = []
                    offset = 0.0
                    for word in (transcript.split() if transcript else []):
                        words.append({
                            "type": "word",
                            "start_time": offset,
                            "end_time": offset + 0.5,
                            "alternatives": [
                                {"content": word, "confidence": 1.0}
                            ],
                        })
                        offset += 0.5

                    await ws.send_text(json.dumps({
                        "message": "AddTranscript",
                        "results": words,
                        "metadata": {
                            "start_time": 0.0,
                            "end_time": offset or 1.0,
                            "transcript": transcript,
                        },
                    }))
                    await ws.send_text(json.dumps({"message": "EndOfTranscript"}))
                    break

                elif msg_type == "SetRecognitionConfig":
                    # Accept config updates silently
                    pass

        except WebSocketDisconnect:
            pass
        finally:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close()

    return router
