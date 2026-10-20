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
import wave
from array import array
from typing import TYPE_CHECKING, Optional

from ovos_utils.log import LOG

if TYPE_CHECKING:
    from ovos_plugin_manager.utils.audio import AudioData
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


_WAVE_FORMAT_PCM = (1).to_bytes(2, "little")
_WAVE_FORMAT_EXTENSIBLE = (0xFFFE).to_bytes(2, "little")
_KSDATAFORMAT_SUBTYPE_PCM = bytes.fromhex("0100000000001000800000aa00389b71")


def _as_plain_pcm_wav(data: bytes) -> bytes:
    """Give a WAVE_FORMAT_EXTENSIBLE file with a PCM subformat the plain PCM tag.

    ffmpeg and sox write the extensible tag for 24-bit, 32-bit and
    multi-channel PCM, and ``wave`` before Python 3.12 rejects it.
    """
    pos = 12
    while pos + 8 <= len(data):
        chunk_id, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        if chunk_id == b"fmt ":
            tag = data[pos + 8:pos + 10]
            subformat = data[pos + 32:pos + 48]
            if tag == _WAVE_FORMAT_EXTENSIBLE and subformat == _KSDATAFORMAT_SUBTYPE_PCM:
                return data[:pos + 8] + _WAVE_FORMAT_PCM + data[pos + 10:]
            return data
        pos += 8 + size + (size & 1)
    return data


def _to_audio_data(data: bytes, sample_rate: int, sample_width: int) -> "AudioData":
    """Decode a WAV file to 16-bit mono PCM; read other bytes as raw PCM.

    The channels of a multi-channel WAV are averaged, so equal loud channels
    do not clip as a plain sum would.
    """
    from ovos_plugin_manager.utils.audio import AudioData

    if data[:4] != b"RIFF":
        return AudioData(data, sample_rate, sample_width)

    with wave.open(io.BytesIO(_as_plain_pcm_wav(data))) as wf:
        channels, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    # AudioData reads 8-bit samples as unsigned, as WAV stores them. Width
    # conversion works sample by sample, so it is safe on interleaved frames.
    pcm = array("h", AudioData(frames, rate, width).get_raw_data(convert_width=2))
    if channels > 1:
        pcm = array("h", (sum(frame) // channels
                          for frame in zip(*(pcm[c::channels] for c in range(channels)))))
    return AudioData(pcm.tobytes(), rate, 2)


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

        audio = _to_audio_data(raw_bytes, sample_rate, sample_width)
        # the container resolves "auto" the same way as for HTTP /stt
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
