# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""UTCP manual router for ovos-stt-http-server.

Serves a ``GET /utcp`` endpoint that returns a UTCP-1.0 *manual* — a
self-describing JSON document listing every tool (endpoint) this server
exposes so that UTCP clients can discover and call them without any
out-of-band documentation.

No extra dependencies are required; the endpoint is always available.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.requests import Request

# UTCP manual version — bump when the tool list or schemas change.
_MANUAL_VERSION = "1.0.0"
_UTCP_SPEC_VERSION = "1.0.0"


def _stt_tool(base_url: str) -> Dict[str, Any]:
    return {
        "name": "stt",
        "description": (
            "Transcribe raw PCM audio to text. "
            "POST raw audio bytes to /stt with query params: "
            "lang (BCP-47 tag or 'auto'), sample_rate (default 16000), "
            "sample_width (default 2). Returns plain-text transcription."
        ),
        "inputs": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "format": "binary",
                    "description": "Raw PCM audio bytes (request body).",
                },
                "lang": {
                    "type": "string",
                    "default": "auto",
                    "description": "BCP-47 language tag or 'auto' for detection.",
                },
                "sample_rate": {
                    "type": "integer",
                    "default": 16000,
                    "description": "Audio sample rate in Hz.",
                },
                "sample_width": {
                    "type": "integer",
                    "default": 2,
                    "description": "Audio sample width in bytes (2 = 16-bit).",
                },
            },
            "required": ["body"],
        },
        "outputs": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Transcribed text."},
            },
        },
        "tags": ["stt", "speech-to-text", "ovos"],
        "average_response_size": 256,
        "tool_call_template": {
            "protocol": "http",
            "method": "POST",
            "url": f"{base_url}/stt",
            "query_params": {
                "lang": "{{lang}}",
                "sample_rate": "{{sample_rate}}",
                "sample_width": "{{sample_width}}",
            },
            "headers": {"Content-Type": "application/octet-stream"},
            "body": "{{body}}",
            "auth": {"type": "none"},
        },
    }


def _lang_detect_tool(base_url: str) -> Dict[str, Any]:
    return {
        "name": "lang_detect",
        "description": (
            "Detect the spoken language in raw PCM audio. "
            "POST audio bytes to /lang_detect with query param valid_langs "
            "(comma-separated BCP-47 tags). Returns {lang, conf}."
        ),
        "inputs": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "format": "binary",
                    "description": "Raw PCM audio bytes.",
                },
                "valid_langs": {
                    "type": "string",
                    "description": "Comma-separated list of candidate language tags.",
                },
            },
            "required": ["body", "valid_langs"],
        },
        "outputs": {
            "type": "object",
            "properties": {
                "lang": {"type": "string", "description": "Detected BCP-47 tag."},
                "conf": {"type": "number", "description": "Confidence score 0–1."},
            },
        },
        "tags": ["language-detection", "ovos"],
        "average_response_size": 64,
        "tool_call_template": {
            "protocol": "http",
            "method": "POST",
            "url": f"{base_url}/lang_detect",
            "query_params": {"valid_langs": "{{valid_langs}}"},
            "headers": {"Content-Type": "application/octet-stream"},
            "body": "{{body}}",
            "auth": {"type": "none"},
        },
    }


def _status_tool(base_url: str) -> Dict[str, Any]:
    return {
        "name": "status",
        "description": (
            "Return service health and loaded plugin names. "
            "GET /status → {status, plugin, lang_plugin}."
        ),
        "inputs": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "outputs": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "plugin": {"type": "string"},
                "lang_plugin": {"type": ["string", "null"]},
            },
        },
        "tags": ["status", "ovos"],
        "average_response_size": 128,
        "tool_call_template": {
            "protocol": "http",
            "method": "GET",
            "url": f"{base_url}/status",
            "auth": {"type": "none"},
        },
    }


def build_utcp_manual(base_url: str) -> Dict[str, Any]:
    """Return a UTCP-1.0 manual dict for all endpoints at *base_url*.

    Parameters
    ----------
    base_url:
        Scheme + host + optional port (e.g. ``"http://localhost:8080"``).
        Must NOT have a trailing slash.

    Returns
    -------
    dict
        A fully-formed UTCP manual ready to be serialised as JSON.
    """
    base_url = base_url.rstrip("/")
    return {
        "utcp_version": _UTCP_SPEC_VERSION,
        "manual_version": _MANUAL_VERSION,
        "tools": [
            _stt_tool(base_url),
            _lang_detect_tool(base_url),
            _status_tool(base_url),
        ],
    }


def make_utcp_router() -> APIRouter:
    """Create a FastAPI router that serves the UTCP manual at ``GET /utcp``.

    The ``base_url`` is inferred from the incoming request so the manual
    is always correct regardless of where the server is deployed.
    """
    router = APIRouter(tags=["utcp"])

    @router.get("/utcp", summary="UTCP manual — tool discovery")
    def utcp_manual(request: Request):
        """Return a UTCP-1.0 manual describing every endpoint on this server.

        UTCP clients point their provider config at this URL:

        ```json
        {
          "name": "ovos-stt",
          "provider_type": "http",
          "url": "http://<host>:<port>/utcp"
        }
        ```
        """
        # Derive base_url from the request so it works behind proxies.
        base_url = str(request.base_url).rstrip("/")
        manual = build_utcp_manual(base_url)
        return JSONResponse(content=manual)

    return router
