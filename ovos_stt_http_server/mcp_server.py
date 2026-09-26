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
"""MCP server for ovos-stt-http-server.

Exposes a ``transcribe`` tool via the Model Context Protocol using FastMCP.
When the host application is FastAPI the MCP server is mounted directly on the
same process via streamable-HTTP transport at ``/mcp``.

Install the optional dependency group to enable::

    pip install "ovos-stt-http-server[mcp]"
"""
from __future__ import annotations

import base64
import io
import tempfile
from typing import TYPE_CHECKING, Optional

from ovos_utils.log import LOG

if TYPE_CHECKING:
    from ovos_stt_http_server import ModelContainer, MultiModelContainer

_MCP_AVAILABLE = False
try:
    from fastmcp import FastMCP  # type: ignore
    _MCP_AVAILABLE = True
except ImportError:
    pass


def _require_mcp() -> None:
    if not _MCP_AVAILABLE:
        raise ImportError(
            "FastMCP is not installed. "
            "Enable the extra: pip install 'ovos-stt-http-server[mcp]'"
        )


def build_mcp_server(
    model: "ModelContainer | MultiModelContainer",
    server_name: str = "ovos-stt",
) -> "FastMCP":
    """Create and return a configured :class:`FastMCP` instance.

    The returned object exposes a single ``transcribe`` tool that accepts audio
    as either a file path or base64-encoded bytes and returns the transcription
    as a plain string.

    Parameters
    ----------
    model:
        An initialised ``ModelContainer`` or ``MultiModelContainer``.
    server_name:
        Human-readable name reported in MCP server info.

    Returns
    -------
    FastMCP
        A ready-to-use FastMCP server.
    """
    _require_mcp()
    from fastmcp import FastMCP  # type: ignore
    from ovos_plugin_manager.utils.audio import AudioData

    mcp = FastMCP(server_name)

    @mcp.tool()
    def transcribe(
        audio_b64: Optional[str] = None,
        audio_path: Optional[str] = None,
        lang: str = "auto",
        sample_rate: int = 16000,
        sample_width: int = 2,
    ) -> str:
        """Transcribe speech audio to text.

        Provide **one** of ``audio_b64`` (base64-encoded raw PCM bytes) or
        ``audio_path`` (absolute path to an audio file on the server).

        Args:
            audio_b64: Base64-encoded raw PCM audio bytes.
            audio_path: Absolute path to a WAV/PCM audio file accessible by the server.
            lang: BCP-47 language tag (e.g. ``"en-us"``) or ``"auto"`` for
                automatic language detection.
            sample_rate: Sample rate of the audio in Hz (default 16 000).
            sample_width: Sample width in bytes (default 2 = 16-bit).

        Returns:
            The transcribed text, or an empty string if nothing was heard.

        Raises:
            ValueError: When neither *audio_b64* nor *audio_path* is supplied.
        """
        if audio_b64 is None and audio_path is None:
            raise ValueError("Provide either audio_b64 or audio_path")

        if audio_path is not None:
            with open(audio_path, "rb") as fh:
                raw_bytes = fh.read()
        else:
            assert audio_b64 is not None  # guarded by the ValueError above
            raw_bytes = base64.b64decode(audio_b64)

        audio = AudioData(raw_bytes, sample_rate, sample_width)

        if lang == "auto":
            try:
                detected_lang, _conf = model.detect_language(raw_bytes)
                lang = detected_lang
            except Exception as e:
                # engines without audio language detection fall back to
                # their default language instead of failing the call
                lang = getattr(model, "default_lang", None) or "en-us"
                LOG.debug(f"[MCP] language detection unavailable ({e}); "
                          f"falling back to {lang}")

        result = model.process_audio(audio, lang)
        LOG.debug(f"[MCP] transcribe lang={lang} result={result!r}")
        return result or ""

    return mcp


def mount_mcp_on_fastapi(app, model, path: str = "/mcp") -> None:
    """Mount the MCP server onto an existing FastAPI *app* at *path*.

    Uses FastMCP's streamable-HTTP ASGI transport, which supports both the
    legacy ``/sse`` event-stream and the newer ``POST /mcp`` single-request
    format.  Clients may also connect via the SSE endpoint at ``/mcp/sse``.

    Parameters
    ----------
    app:
        A :class:`fastapi.FastAPI` (or any Starlette) application.
    model:
        The STT model container.
    path:
        Mount prefix (default ``"/mcp"``).
    """
    _require_mcp()
    mcp = build_mcp_server(model)
    # Serve the streamable-HTTP transport at the mount root so the endpoint
    # is exactly *path* (FastMCP defaults to an internal /mcp sub-path, which
    # would yield /mcp/mcp when mounted).
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    app.mount(path, mcp_app)

    # Starlette does not propagate lifespan events to mounted sub-apps, and
    # the streamable-HTTP transport requires its session manager running.
    # FastMCP exposes the required lifespan via `mcp_app.lifespan`; it must
    # be entered alongside the host application's own lifespan.
    from contextlib import asynccontextmanager
    _original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _lifespan_with_mcp(host_app):
        async with _original_lifespan(host_app):
            async with mcp_app.lifespan(host_app):
                yield

    app.router.lifespan_context = _lifespan_with_mcp
    LOG.info(f"MCP server mounted at {path} (streamable-HTTP)")
