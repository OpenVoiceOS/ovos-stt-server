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
"""End-to-end tests for the MCP /mcp and UTCP /utcp endpoints.

Boots the real FastAPI app (via create_app) with a stub STT model,
starts uvicorn on a free port in a background thread, and exercises the
live HTTP surface.

Run in isolation::

    pytest test/end2end/test_e2e_mcp_utcp.py -v --timeout=30
"""
from __future__ import annotations

import asyncio
import base64
import socket
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest
import uvicorn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_stub_model(transcription: str = "hello from stub") -> MagicMock:
    model = MagicMock()
    model.process_audio.return_value = transcription
    model.detect_language.return_value = ("en-us", 0.95)
    return model


# ---------------------------------------------------------------------------
# App + server fixture
# ---------------------------------------------------------------------------

def _start_server(app, health_path: str = "/status") -> tuple:
    """Start uvicorn in a daemon thread; return (base_url, server, thread)."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=asyncio.run, args=(server.serve(),), daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}{health_path}", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        server.should_exit = True
        raise RuntimeError("Server did not start in time")
    return f"http://127.0.0.1:{port}", server, thread


@pytest.fixture(scope="module")
def live_server():
    """Boot create_app with a stub model and serve on a free port."""
    import asyncio as _asyncio
    from unittest.mock import patch

    stub = _make_stub_model()

    with patch("ovos_stt_http_server.ModelContainer") as MockContainer:
        MockContainer.return_value = stub
        from ovos_stt_http_server import create_app
        app, _ = create_app("stub-stt")

    try:
        base_url, server, thread = _start_server(app)
    except RuntimeError as exc:
        pytest.skip(str(exc))

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def mcp_server():
    """Run MCP directly as its own Starlette app to avoid sub-app lifespan issues."""
    import asyncio as _asyncio

    stub = _make_stub_model()
    try:
        from ovos_stt_http_server.mcp_server import build_mcp_server
    except ImportError:
        pytest.skip("mcp extra not installed")

    mcp = build_mcp_server(stub)
    mcp_app = mcp.http_app()

    try:
        base_url, server, thread = _start_server(mcp_app, health_path="/mcp")
    except RuntimeError as exc:
        pytest.skip(str(exc))

    yield f"{base_url}/mcp"

    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# UTCP end-to-end
# ---------------------------------------------------------------------------

class TestUtcpE2E:
    def test_utcp_returns_200(self, live_server):
        resp = httpx.get(f"{live_server}/utcp", timeout=10)
        assert resp.status_code == 200

    def test_utcp_body_is_json(self, live_server):
        data = httpx.get(f"{live_server}/utcp", timeout=10).json()
        assert isinstance(data, dict)

    def test_utcp_has_tools_list(self, live_server):
        data = httpx.get(f"{live_server}/utcp", timeout=10).json()
        assert "tools" in data
        assert isinstance(data["tools"], list)
        assert len(data["tools"]) >= 1

    def test_utcp_advertised_stt_url_responds(self, live_server):
        """The tool URL listed in the UTCP manual must actually be callable."""
        data = httpx.get(f"{live_server}/utcp", timeout=10).json()
        stt_tool = next((t for t in data["tools"] if t["name"] == "stt"), None)
        assert stt_tool is not None, "stt tool not found in UTCP manual"
        url = stt_tool["tool_call_template"]["url"]
        # POST raw audio bytes — stub always returns the transcription
        # Do not pass sample_rate/sample_width; the endpoint uses defaults
        audio_bytes = b"\x00" * 320
        resp = httpx.post(
            url,
            content=audio_bytes,
            params={"lang": "en-us"},
            timeout=10,
        )
        assert resp.status_code == 200

    def test_utcp_status_url_responds(self, live_server):
        data = httpx.get(f"{live_server}/utcp", timeout=10).json()
        status_tool = next((t for t in data["tools"] if t["name"] == "status"), None)
        assert status_tool is not None
        url = status_tool["tool_call_template"]["url"]
        resp = httpx.get(url, timeout=10)
        assert resp.status_code == 200

    def test_utcp_version_field(self, live_server):
        data = httpx.get(f"{live_server}/utcp", timeout=10).json()
        assert "utcp_version" in data


# ---------------------------------------------------------------------------
# MCP end-to-end
# ---------------------------------------------------------------------------

class TestMcpE2E:
    """Drive a real MCP handshake (initialize → list_tools → call_tool) over HTTP.

    Uses a standalone MCP Starlette app served by its own uvicorn instance to
    avoid the sub-app lifespan issue in Starlette Mount.
    """

    def test_mcp_endpoint_accessible(self, mcp_server):
        """The MCP root must not 404."""
        resp = httpx.get(mcp_server, timeout=10)
        assert resp.status_code != 404

    def test_mcp_list_tools_via_client(self, mcp_server):
        """Use the MCP streamable-HTTP client to list tools."""
        from mcp.client.streamable_http import streamable_http_client
        from mcp import ClientSession

        async def _run():
            async with streamable_http_client(mcp_server) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return result.tools

        tools = asyncio.run(_run())
        names = [t.name for t in tools]
        assert "transcribe" in names

    def test_mcp_call_transcribe_tool(self, mcp_server):
        """Call the transcribe tool via MCP and get a text response."""
        from mcp.client.streamable_http import streamable_http_client
        from mcp import ClientSession

        audio_b64 = base64.b64encode(b"\x00" * 320).decode()

        async def _run():
            async with streamable_http_client(mcp_server) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "transcribe",
                        {"audio_b64": audio_b64, "lang": "en-us"},
                    )
                    return result

        result = asyncio.run(_run())
        assert result is not None
        texts = [
            c.text if hasattr(c, "text") else (c.get("text", "") if isinstance(c, dict) else str(c))
            for c in result.content
        ]
        assert any(texts), "Expected non-empty response from transcribe tool"
