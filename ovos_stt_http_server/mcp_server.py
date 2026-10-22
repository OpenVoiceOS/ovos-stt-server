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
import tempfile
import warnings
from typing import TYPE_CHECKING, Optional

from ovos_utils.log import LOG

from ovos_stt_http_server.audio_utils import to_audio_data
from ovos_stt_http_server.version import VERSION_MAJOR, VERSION_MINOR

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
            'Enable the extra: pip install "ovos-stt-http-server[mcp]"'
        )


def build_mcp(
    engine: "ModelContainer | MultiModelContainer",
    server_name: str = "ovos-stt",
) -> "FastMCP":
    """Create and return a configured :class:`FastMCP` instance.

    The returned object exposes a single ``transcribe`` tool that accepts audio
    as either a file path or base64-encoded bytes and returns the transcription
    as a plain string.

    Parameters
    ----------
    engine:
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

        Provide **one** of ``audio_b64`` (base64-encoded audio) or
        ``audio_path`` (absolute path to an audio file on the server). A WAV file
        is decoded with its own sample rate and width; any other bytes are
        read as raw mono PCM.

        Args:
            audio_b64: Base64-encoded WAV file or raw PCM bytes.
            audio_path: Absolute path to a WAV or raw PCM file on the server.
            lang: BCP-47 language tag (e.g. ``"en-us"``) or ``"auto"`` for
                automatic language detection.
            sample_rate: Sample rate of raw PCM in Hz (default 16 000).
            sample_width: Sample width of raw PCM in bytes (default 2 = 16-bit).

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

        audio = to_audio_data(raw_bytes, sample_rate, sample_width)
        # the container resolves "auto" the same way as for HTTP /stt
        result = engine.process_audio(audio, lang)
        LOG.debug(f"[MCP] transcribe lang={lang} result={result!r}")
        return result or ""

    return mcp


class _MountRoot:
    """ASGI app that serves the root of a mounted *app* at the bare mount *path*."""

    def __init__(self, app, path: str):
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send):
        root_path = scope.get("root_path", "") + self.path
        await self.app({**scope, "root_path": root_path, "path": root_path + "/"},
                       receive, send)


def mount_mcp(app, engine, path: str = "/mcp") -> None:
    """Mount the MCP server onto an existing FastAPI *app* at *path*.

    Uses FastMCP's streamable-HTTP ASGI transport. There is no SSE endpoint.

    Parameters
    ----------
    app:
        A :class:`fastapi.FastAPI` (or any Starlette) application.
    engine:
        The STT model container.
    path:
        Mount prefix (default ``"/mcp"``).
    """
    _require_mcp()
    from starlette.routing import Route

    mcp = build_mcp(engine)
    # Serve the streamable-HTTP transport at the mount root so the endpoint
    # is exactly *path* (FastMCP defaults to an internal /mcp sub-path, which
    # would yield /mcp/mcp when mounted).
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    app.mount(path, mcp_app)

    # Mount(path) answers a request for the bare path with a 307 to path + "/".
    # Behind a proxy the redirect can name the wrong scheme or host, and MCP
    # clients refuse it, so the bare path is routed to the same transport.
    app.router.routes.insert(0, Route(path, endpoint=_MountRoot(mcp_app, path)))

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


def _deprecated(old: str, new: str) -> None:
    warnings.warn(
        f"{old} is deprecated, use {new}; it will be removed in "
        f"{VERSION_MAJOR}.{VERSION_MINOR + 1}.0",
        DeprecationWarning, stacklevel=3)


def build_mcp_server(model, server_name: str = "ovos-stt") -> "FastMCP":
    """Deprecated name of :func:`build_mcp`."""
    _deprecated("build_mcp_server", "build_mcp")
    return build_mcp(model, server_name)


def mount_mcp_on_fastapi(app, model, path: str = "/mcp") -> None:
    """Deprecated name of :func:`mount_mcp`."""
    _deprecated("mount_mcp_on_fastapi", "mount_mcp")
    mount_mcp(app, model, path)
