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
"""Tests for the MCP server integration.

All tests mock the STT engine so no real model is required.
The ``fastmcp`` package itself is required (pip install 'ovos-stt-http-server[mcp]').
"""
import asyncio
import base64
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model(transcription: str = "hello world", detected_lang: str = "en-us"):
    """Return a minimal mock that quacks like ModelContainer."""
    model = MagicMock()
    model.process_audio.return_value = transcription
    model.detect_language.return_value = (detected_lang, 0.99)
    return model


def _get_tools(mcp):
    return asyncio.run(mcp.list_tools())


def _call_tool(mcp, name, kwargs):
    result = asyncio.run(mcp.call_tool(name, kwargs))
    return result.content


def _extract_text(content_list) -> str:
    """Extract plain text from a FastMCP content list."""
    parts = []
    for block in content_list:
        if isinstance(block, str):
            parts.append(block)
        elif hasattr(block, "text"):
            parts.append(block.text)
        elif isinstance(block, dict):
            parts.append(block.get("text", ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# build_mcp_server
# ---------------------------------------------------------------------------

class TestBuildMcpServer:
    @pytest.fixture(autouse=True)
    def _check_mcp(self):
        import fastmcp

    def test_returns_fastmcp_instance(self):
        from fastmcp import FastMCP
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(_make_model())
        assert isinstance(mcp, FastMCP)

    def test_transcribe_tool_registered(self):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(_make_model())
        tool_names = [t.name for t in _get_tools(mcp)]
        assert "transcribe" in tool_names

    def test_transcribe_tool_has_description(self):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(_make_model())
        transcribe = next(t for t in _get_tools(mcp) if t.name == "transcribe")
        assert transcribe.description

    def test_transcribe_tool_input_schema_has_audio_fields(self):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(_make_model())
        transcribe = next(t for t in _get_tools(mcp) if t.name == "transcribe")
        props = transcribe.parameters.get("properties", {})
        # at least one of the two audio input fields must be present
        assert "audio_b64" in props or "audio_path" in props

    def test_transcribe_tool_has_lang_param(self):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(_make_model())
        transcribe = next(t for t in _get_tools(mcp) if t.name == "transcribe")
        props = transcribe.parameters.get("properties", {})
        assert "lang" in props

    def test_custom_server_name_accepted(self):
        from fastmcp import FastMCP
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(_make_model(), server_name="my-stt")
        assert isinstance(mcp, FastMCP)


# ---------------------------------------------------------------------------
# transcribe tool execution (mocked AudioData)
# ---------------------------------------------------------------------------

class TestTranscribeTool:
    @pytest.fixture(autouse=True)
    def _check_mcp(self):
        import fastmcp

    def _call(self, model, **kwargs):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        mcp = build_mcp_server(model)
        result = asyncio.run(mcp.call_tool("transcribe", kwargs))
        return _extract_text(result.content)

    def test_transcribe_with_audio_b64(self):
        model = _make_model("hello world")
        raw = b"\x00" * 100
        audio_b64 = base64.b64encode(raw).decode()
        text = self._call(model, audio_b64=audio_b64, lang="en-us")
        assert "hello world" in text

    def test_transcribe_with_audio_path(self, tmp_path):
        model = _make_model("path transcription")
        audio_file = tmp_path / "test.pcm"
        audio_file.write_bytes(b"\x00" * 200)
        text = self._call(model, audio_path=str(audio_file), lang="en-us")
        assert "path transcription" in text

    def test_transcribe_explicit_lang_skips_detection(self):
        model = _make_model("explicit lang result")
        raw = b"\x00" * 50
        audio_b64 = base64.b64encode(raw).decode()
        self._call(model, audio_b64=audio_b64, lang="de-de")
        model.detect_language.assert_not_called()

    def test_transcribe_no_audio_raises(self):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        model = _make_model()
        mcp = build_mcp_server(model)
        # Calling with neither audio_b64 nor audio_path should raise
        with pytest.raises(Exception):
            asyncio.run(mcp.call_tool("transcribe", {}))

    def test_transcribe_empty_result_returns_empty_string(self):
        model = _make_model("")
        model.process_audio.return_value = None  # simulate None return
        raw = b"\x00" * 50
        audio_b64 = base64.b64encode(raw).decode()
        text = self._call(model, audio_b64=audio_b64, lang="en-us")
        assert text == ""

    def test_transcribe_both_inputs_given_audio_path_wins(self, tmp_path):
        """When both audio_b64 and audio_path are supplied, audio_path takes priority.

        The source reads ``if audio_path is not None`` first, so the file is
        used and the b64 string is ignored.
        """
        model = _make_model("from file")
        audio_file = tmp_path / "both.pcm"
        audio_file.write_bytes(b"\x01" * 100)
        # audio_b64 contains different data — if it were used the test would
        # still pass (same model mock), but we verify process_audio is called
        # with bytes matching the file content, not the b64.
        b64_data = base64.b64encode(b"\x02" * 100).decode()
        from ovos_stt_http_server.mcp_server import build_mcp_server
        from ovos_plugin_manager.utils.audio import AudioData
        mcp = build_mcp_server(model)
        asyncio.run(mcp.call_tool("transcribe", {
            "audio_b64": b64_data,
            "audio_path": str(audio_file),
            "lang": "en-us",
        }))
        call_audio: AudioData = model.process_audio.call_args[0][0]
        assert call_audio.frame_data == b"\x01" * 100

    def test_transcribe_invalid_base64_raises(self):
        """Passing a non-base64 string for audio_b64 raises an exception."""
        from ovos_stt_http_server.mcp_server import build_mcp_server
        model = _make_model()
        mcp = build_mcp_server(model)
        with pytest.raises(Exception):
            asyncio.run(mcp.call_tool("transcribe", {
                "audio_b64": "!!!not-valid-base64!!!",
                "lang": "en-us",
            }))

    def test_transcribe_audio_path_not_found_raises(self):
        """A non-existent audio_path must raise FileNotFoundError (or similar)."""
        from ovos_stt_http_server.mcp_server import build_mcp_server
        model = _make_model()
        mcp = build_mcp_server(model)
        with pytest.raises(Exception):
            asyncio.run(mcp.call_tool("transcribe", {
                "audio_path": "/tmp/__nonexistent_ovos_test_file__.pcm",
                "lang": "en-us",
            }))



# ---------------------------------------------------------------------------
# mount_mcp_on_fastapi
# ---------------------------------------------------------------------------

class TestMountMcpOnFastapi:
    @pytest.fixture(autouse=True)
    def _check_mcp(self):
        import fastmcp

    def test_mount_does_not_raise(self):
        from fastapi import FastAPI
        from ovos_stt_http_server.mcp_server import mount_mcp_on_fastapi
        app = FastAPI()
        model = _make_model()
        mount_mcp_on_fastapi(app, model, path="/mcp")

    def test_import_error_without_mcp(self, monkeypatch):
        """When mcp is not installed, _require_mcp() raises ImportError."""
        import ovos_stt_http_server.mcp_server as mod
        monkeypatch.setattr(mod, "_MCP_AVAILABLE", False)
        with pytest.raises(ImportError, match="FastMCP"):
            mod._require_mcp()

    def test_build_mcp_server_raises_when_mcp_unavailable(self, monkeypatch):
        """build_mcp_server() raises ImportError when _MCP_AVAILABLE is False."""
        import ovos_stt_http_server.mcp_server as mod
        monkeypatch.setattr(mod, "_MCP_AVAILABLE", False)
        with pytest.raises(ImportError):
            mod.build_mcp_server(_make_model())

    def test_mount_mcp_on_fastapi_raises_when_mcp_unavailable(self, monkeypatch):
        """mount_mcp_on_fastapi() raises ImportError when _MCP_AVAILABLE is False."""
        from fastapi import FastAPI
        import ovos_stt_http_server.mcp_server as mod
        monkeypatch.setattr(mod, "_MCP_AVAILABLE", False)
        app = FastAPI()
        with pytest.raises(ImportError):
            mod.mount_mcp_on_fastapi(app, _make_model())


# ---------------------------------------------------------------------------
# MCP module import-time graceful degradation (sys.modules blocking)
# ---------------------------------------------------------------------------

class TestMcpModuleImportDegradation:
    """Verify the except-ImportError branch at module level (lines 38-39).

    When ``mcp`` is not on sys.path at import time, the module must still load
    with ``_MCP_AVAILABLE = False`` rather than raising.
    """

    def test_module_loads_without_mcp_package(self):
        """Force a fresh import of mcp_server with mcp blocked in sys.modules."""
        import sys
        import importlib

        # Block the fastmcp package by inserting a sentinel that raises ImportError.
        blocked_keys = [k for k in list(sys.modules) if k == "fastmcp" or k.startswith("fastmcp.")]
        saved = {k: sys.modules.pop(k) for k in blocked_keys}
        # Use a fake module that raises on attribute access is complex;
        # simpler: set the key to None which causes ImportError on `import fastmcp`.
        sys.modules["fastmcp"] = None  # type: ignore

        # Remove the already-cached mcp_server module so it re-executes.
        mcp_server_saved = sys.modules.pop("ovos_stt_http_server.mcp_server", None)
        try:
            import ovos_stt_http_server.mcp_server as fresh_mod
            assert fresh_mod._MCP_AVAILABLE is False
        finally:
            # Restore everything.
            sys.modules.pop("fastmcp", None)
            sys.modules.update(saved)
            if mcp_server_saved is not None:
                sys.modules["ovos_stt_http_server.mcp_server"] = mcp_server_saved


# ---------------------------------------------------------------------------
# create_app integration: MCP absent → graceful degradation
# ---------------------------------------------------------------------------

class TestCreateAppMcpDegradation:
    def test_create_app_without_mcp_does_not_crash(self, monkeypatch):
        """create_app() continues normally when mcp extra is missing."""
        import ovos_stt_http_server.mcp_server as mcp_mod
        monkeypatch.setattr(mcp_mod, "_MCP_AVAILABLE", False)

        with patch("ovos_stt_http_server.ModelContainer") as mc:
            mc.return_value = _make_model()
            from ovos_stt_http_server import create_app
            # enable_mcp=True so this exercises the mount attempt/degradation path;
            # MCP is opt-in now, so create_app("mock-stt") alone would never try to mount.
            app, model = create_app("mock-stt", enable_mcp=True)

        from fastapi import FastAPI
        assert isinstance(app, FastAPI)

    def test_create_app_mcp_import_error_caught(self):
        """create_app(enable_mcp=True) catches ImportError from mount_mcp_on_fastapi gracefully.

        Patches the mcp_server submodule in sys.modules so the ``from … import``
        inside create_app triggers an ImportError through the module's own guard.
        """
        import sys
        import ovos_stt_http_server.mcp_server as mcp_mod

        with patch("ovos_stt_http_server.ModelContainer") as mc, \
             patch.object(mcp_mod, "mount_mcp_on_fastapi", side_effect=ImportError("no mcp")):
            mc.return_value = _make_model()
            # Force create_app to use the patched module by flushing its cache entry.
            saved = sys.modules.get("ovos_stt_http_server.mcp_server")
            sys.modules["ovos_stt_http_server.mcp_server"] = mcp_mod  # already patched
            try:
                from ovos_stt_http_server import create_app
                app, model = create_app("mock-stt", enable_mcp=True)
            finally:
                if saved is not None:
                    sys.modules["ovos_stt_http_server.mcp_server"] = saved

        from fastapi import FastAPI
        assert isinstance(app, FastAPI)


class TestTranscribeAudioFiles:
    """A WAV file is decoded with its own format, not read as raw PCM."""

    # 0.1 s of a known 16-bit ramp
    MONO = b"".join(i.to_bytes(2, "little", signed=True) for i in range(-2205, 2205))

    @pytest.fixture(autouse=True)
    def _check_mcp(self):
        import fastmcp

    @staticmethod
    def _wav(rate: int, channels: int = 1, width: int = 2, frames: bytes = None) -> bytes:
        import io
        import wave
        if frames is None:
            frames = b"".join(TestTranscribeAudioFiles.MONO[i:i + 2] * channels
                              for i in range(0, len(TestTranscribeAudioFiles.MONO), 2))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(width)
            wf.setframerate(rate)
            wf.writeframes(frames)
        return buf.getvalue()

    @staticmethod
    def _pcm16(*samples: int) -> bytes:
        return b"".join(s.to_bytes(2, "little", signed=True) for s in samples)

    def _received(self, **kwargs):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        model = _make_model("decoded")
        asyncio.run(build_mcp_server(model).call_tool("transcribe", {"lang": "en-us", **kwargs}))
        audio = model.process_audio.call_args[0][0]
        return audio.frame_data, audio.sample_rate, audio.sample_width

    def test_wav_b64_uses_the_file_format(self):
        wav = self._wav(44100)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self.MONO, 44100, 2)

    def test_wav_path_uses_the_file_format(self, tmp_path):
        path = tmp_path / "speech.wav"
        path.write_bytes(self._wav(22050))
        assert self._received(audio_path=str(path)) == (self.MONO, 22050, 2)

    def test_stereo_wav_is_averaged_to_mono(self):
        # (left, right) pairs and their mean; the sum of the first pair clips
        pairs = [(20000, 20000), (1000, -1000), (3000, 0), (-32768, -32768)]
        stereo = b"".join(self._pcm16(left, right) for left, right in pairs)
        wav = self._wav(48000, channels=2, frames=stereo)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(20000, 0, 1500, -32768), 48000, 2)

    def test_stereo_average_rounds_down(self):
        # an odd sum has no exact mean; floor division pins -0.5 to -1
        stereo = b"".join(self._pcm16(left, right) for left, right in [(-1, 0), (1, 0), (-3, 0)])
        wav = self._wav(16000, channels=2, frames=stereo)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(-1, 0, -2), 16000, 2)

    PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
    FLOAT_GUID = bytes.fromhex("0300000000001000800000aa00389b71")
    ALAW_GUID = bytes.fromhex("0600000000001000800000aa00389b71")

    @staticmethod
    def _extensible_wav(rate: int, channels: int, width: int, frames: bytes,
                        subformat: bytes = PCM_GUID, before_fmt: bytes = b"") -> bytes:
        """A WAVE_FORMAT_EXTENSIBLE file, as ffmpeg and sox write it."""
        fmt = b"".join([
            (0xFFFE).to_bytes(2, "little"), channels.to_bytes(2, "little"),
            rate.to_bytes(4, "little"), (rate * channels * width).to_bytes(4, "little"),
            (channels * width).to_bytes(2, "little"), (8 * width).to_bytes(2, "little"),
            (22).to_bytes(2, "little"), (8 * width).to_bytes(2, "little"),
            (0x3 if channels == 2 else 0x4).to_bytes(4, "little"), subformat])
        body = (b"WAVE" + before_fmt + b"fmt " + len(fmt).to_bytes(4, "little") + fmt
                + b"data" + len(frames).to_bytes(4, "little") + frames)
        return b"RIFF" + len(body).to_bytes(4, "little") + body

    def test_extensible_24bit_wav_becomes_16bit(self):
        frames = b"".join(v.to_bytes(3, "little", signed=True) for v in (4660 * 256, -4660 * 256))
        wav = self._extensible_wav(22050, 1, 3, frames)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(4660, -4660), 22050, 2)

    @pytest.mark.parametrize("subformat", [FLOAT_GUID, ALAW_GUID], ids=["float", "alaw"])
    def test_extensible_non_pcm_wav_is_rejected(self, subformat):
        """Only a PCM subformat may be read as PCM; float or A-law samples would be noise."""
        from ovos_stt_http_server.mcp_server import build_mcp_server
        wav = self._extensible_wav(16000, 1, 4 if subformat == self.FLOAT_GUID else 1,
                                   b"\x00\x00\x80\x3f" * 4, subformat=subformat)
        model = _make_model("noise")
        with pytest.raises(Exception, match="unknown"):
            asyncio.run(build_mcp_server(model).call_tool(
                "transcribe", {"audio_b64": base64.b64encode(wav).decode(), "lang": "en-us"}))
        model.process_audio.assert_not_called()

    def test_extensible_wav_after_an_odd_sized_chunk(self):
        # RIFF pads a chunk of odd size with one byte before the next chunk
        info = b"LIST" + (3).to_bytes(4, "little") + b"abc" + b"\x00"
        frames = b"".join(v.to_bytes(3, "little", signed=True) for v in (4660 * 256, -4660 * 256))
        wav = self._extensible_wav(22050, 1, 3, frames, before_fmt=info)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(4660, -4660), 22050, 2)

    def test_extensible_stereo_wav_is_averaged(self):
        frames = b"".join(self._pcm16(left, right) for left, right in [(20000, 20000), (3000, 0)])
        wav = self._extensible_wav(48000, 2, 2, frames)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(20000, 1500), 48000, 2)

    def test_8bit_wav_becomes_16bit(self):
        # 8-bit WAV samples are unsigned, centred on 128
        wav = self._wav(8000, width=1, frames=bytes([128, 178, 78, 255, 0]))
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(0, 50 * 256, -50 * 256, 127 * 256, -128 * 256), 8000, 2)

    def test_24bit_wav_becomes_16bit(self):
        samples = (4660 * 256, -4660 * 256, 0)
        frames = b"".join(v.to_bytes(3, "little", signed=True) for v in samples)
        wav = self._wav(22050, width=3, frames=frames)
        received = self._received(audio_b64=base64.b64encode(wav).decode())
        assert received == (self._pcm16(4660, -4660, 0), 22050, 2)

    def test_raw_pcm_keeps_the_given_format(self):
        received = self._received(audio_b64=base64.b64encode(self.MONO).decode(),
                                  sample_rate=8000, sample_width=2)
        assert received == (self.MONO, 8000, 2)


class TestTranscribeAutoLanguage:
    """lang="auto" resolves the same way over MCP as over HTTP /stt."""

    @pytest.fixture(autouse=True)
    def _check_mcp(self):
        import fastmcp

    @pytest.fixture
    def container(self, monkeypatch):
        import ovos_stt_http_server as srv

        class PortugueseEngine:
            """An engine configured for pt-pt, with no language detection."""
            lang = "pt-pt"
            available_languages = {"pt-pt"}

            def __init__(self, config=None):
                pass

            def execute(self, audio, language=None):
                return f"transcribed:{language}"

        monkeypatch.setattr(srv, "load_stt_plugin", lambda plugin: PortugueseEngine)
        return srv.ModelContainer("fake-plugin")

    def _mcp(self, container, **kwargs):
        from ovos_stt_http_server.mcp_server import build_mcp_server
        audio_b64 = base64.b64encode(b"\x00" * 320).decode()
        result = asyncio.run(build_mcp_server(container).call_tool(
            "transcribe", {"audio_b64": audio_b64, **kwargs}))
        return _extract_text(result.content)

    def test_auto_without_detection_uses_the_engine_language(self, container):
        assert self._mcp(container, lang="auto") == "transcribed:pt-pt"

    def test_auto_uses_the_detected_language(self, container, monkeypatch):
        monkeypatch.setattr(container, "detect_language", lambda audio, valid=None: ("fr-fr", 0.9))
        assert self._mcp(container, lang="auto") == "transcribed:fr-fr"

    def test_omitted_lang_uses_the_engine_language(self, container):
        assert self._mcp(container) == "transcribed:pt-pt"

    def test_mcp_matches_http(self, container):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        with patch("ovos_stt_http_server.ModelContainer", return_value=container):
            from ovos_stt_http_server import create_app
            app, _ = create_app("fake-plugin")
        http = TestClient(app).post("/stt?lang=auto", content=b"\x00" * 320).text
        assert self._mcp(container, lang="auto") == http == "transcribed:pt-pt"


class TestMissingExtraWarning:
    """--mcp without the extra must warn where an operator can see it."""

    def test_warning_reaches_the_log_at_the_default_level(self):
        import subprocess
        import sys
        script = (
            "import sys; sys.modules['fastmcp'] = None\n"
            "from unittest.mock import MagicMock, patch\n"
            "with patch('ovos_stt_http_server.ModelContainer', return_value=MagicMock()):\n"
            "    from ovos_stt_http_server import create_app\n"
            "    create_app('stub-stt', enable_mcp=True)\n"
        )
        run = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stderr
        output = run.stdout + run.stderr
        assert "WARNING" in output
        assert 'pip install "ovos-stt-http-server[mcp]"' in output
