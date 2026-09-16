# Licensed under the Apache License, Version 2.0
"""Unit tests for ovos_stt_http_server.vosk_grpc_server.

Exercises the servicer and helper functions without a live gRPC channel.
"""
import asyncio
import io
import wave
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ovos_stt_http_server.proto import stt_service_pb2 as pb
from ovos_stt_http_server.vosk_grpc_server import (
    _SttServicer,
    start_grpc_server,
    run_grpc_server_blocking,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeModel:
    """Minimal model stub — always returns 'hello world'."""

    def process_audio(self, audio, lang="en") -> str:
        return "hello world"


def _make_wav(seconds: float = 0.05, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


async def _iter(*items):
    """Yield items as an async iterator."""
    for item in items:
        yield item


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _SttServicer unit tests
# ---------------------------------------------------------------------------

class TestSttServicer:
    """Direct servicer tests — no live channel needed."""

    def setup_method(self):
        self.model = FakeModel()
        self.servicer = _SttServicer(self.model)
        self.ctx = MagicMock()  # fake ServicerContext

    # --- helpers ---

    def _config_request(self, sample_rate=16000, language_code="en-US"):
        return pb.StreamingRecognitionRequest(
            config=pb.RecognitionConfig(
                specification=pb.RecognitionSpec(
                    audio_encoding=pb.RecognitionSpec.LINEAR16_PCM,
                    sample_rate_hertz=sample_rate,
                    language_code=language_code,
                ),
            ),
        )

    def _audio_request(self, data: bytes):
        return pb.StreamingRecognitionRequest(audio_content=data)

    async def _collect(self, requests):
        responses = []
        async for r in self.servicer.StreamingRecognize(requests, self.ctx):
            responses.append(r)
        return responses

    # --- tests ---

    def test_config_then_audio_returns_transcript(self):
        """Config + audio → single final response with 'hello world'."""
        wav = _make_wav()
        requests = _iter(
            self._config_request(),
            self._audio_request(wav),
        )
        responses = _run(self._collect(requests))
        assert len(responses) == 1
        chunk = responses[0].chunks[0]
        assert chunk.final is True
        assert chunk.end_of_utterance is True
        assert chunk.alternatives[0].text == "hello world"
        assert chunk.alternatives[0].confidence == pytest.approx(1.0)

    def test_empty_audio_yields_empty_transcript(self):
        """No audio_content bytes → transcript is empty string, still final."""
        requests = _iter(self._config_request())
        responses = _run(self._collect(requests))
        assert len(responses) == 1
        chunk = responses[0].chunks[0]
        assert chunk.final is True
        assert chunk.alternatives[0].text == ""

    def test_multi_chunk_audio_is_concatenated(self):
        """Multiple audio_content requests are buffered and decoded once."""
        wav = _make_wav()
        half = len(wav) // 2
        requests = _iter(
            self._config_request(),
            self._audio_request(wav[:half]),
            self._audio_request(wav[half:]),
        )
        responses = _run(self._collect(requests))
        assert responses[0].chunks[0].alternatives[0].text == "hello world"

    def test_sample_rate_and_language_forwarded(self):
        """Language and sample-rate from config spec are passed to the model."""
        calls = []

        class InspectModel:
            def process_audio(self, audio, lang="en"):
                calls.append((audio.sample_rate, lang))
                return "ok"

        servicer = _SttServicer(InspectModel())
        wav = _make_wav(sample_rate=8000)
        requests = _iter(
            pb.StreamingRecognitionRequest(
                config=pb.RecognitionConfig(
                    specification=pb.RecognitionSpec(
                        sample_rate_hertz=8000,
                        language_code="pt-PT",
                    )
                )
            ),
            pb.StreamingRecognitionRequest(audio_content=wav),
        )

        async def run():
            out = []
            async for r in servicer.StreamingRecognize(requests, self.ctx):
                out.append(r)
            return out

        _run(run())
        assert calls == [(8000, "pt-PT")]

    def test_no_config_request_uses_defaults(self):
        """Audio-only stream (no config frame) falls back to 16000 Hz / 'en'."""
        calls = []

        class InspectModel:
            def process_audio(self, audio, lang="en"):
                calls.append((audio.sample_rate, lang))
                return "ok"

        servicer = _SttServicer(InspectModel())
        wav = _make_wav()
        requests = _iter(pb.StreamingRecognitionRequest(audio_content=wav))

        async def run():
            out = []
            async for r in servicer.StreamingRecognize(requests, self.ctx):
                out.append(r)
            return out

        _run(run())
        assert calls == [(16000, "en")]

    def test_model_returns_none_gives_empty_string(self):
        """If model.process_audio returns None the transcript is ''."""

        class NoneModel:
            def process_audio(self, audio, lang="en"):
                return None

        servicer = _SttServicer(NoneModel())
        requests = _iter(
            self._config_request(),
            self._audio_request(b"\x00" * 100),
        )

        async def run():
            out = []
            async for r in servicer.StreamingRecognize(requests, self.ctx):
                out.append(r)
            return out

        responses = _run(run())
        assert responses[0].chunks[0].alternatives[0].text == ""


# ---------------------------------------------------------------------------
# start_grpc_server
# ---------------------------------------------------------------------------

class TestStartGrpcServer:
    """Smoke-test the async server factory."""

    def test_start_and_stop(self):
        """start_grpc_server returns a server object that can be stopped."""
        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        async def _run():
            server = await start_grpc_server(FakeModel(), "127.0.0.1", port)
            await server.stop(grace=0)

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# run_grpc_server_blocking
# ---------------------------------------------------------------------------

class TestRunGrpcServerBlocking:
    """Unit-test the blocking wrapper by patching asyncio.run."""

    def test_run_grpc_server_blocking_calls_asyncio_run(self):
        """run_grpc_server_blocking delegates to asyncio.run with an async coroutine."""
        called_with = []

        async def fake_run(coro):
            called_with.append(coro)
            # Don't actually run, just cancel immediately
            coro.close()

        with patch("ovos_stt_http_server.vosk_grpc_server.asyncio.run", new=lambda c: called_with.append(c) or c.close()):
            run_grpc_server_blocking(FakeModel(), "127.0.0.1", 19999)

        assert called_with, "asyncio.run was never called"
