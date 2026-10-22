# Licensed under the Apache License, Version 2.0
"""vosk-server gRPC variant.

Implements `vosk.stt.v1.SttService` (`StreamingRecognize`) using the same
.proto contract as `alphacep/vosk-server/grpc/stt_server.py`. OVOS plugins
are batch-only, so we buffer audio for the lifetime of the streaming RPC
and emit a single final `SpeechRecognitionChunk` (`final=true`,
`end_of_utterance=true`) before closing the stream.
"""
import asyncio
import logging
from typing import AsyncIterator, Optional

import grpc

from ovos_plugin_manager.utils.audio import AudioData

from .proto import stt_service_pb2 as pb
from .proto import stt_service_pb2_grpc as pb_grpc


_LOG = logging.getLogger(__name__)


class _SttServicer(pb_grpc.SttServiceServicer):
    """Streaming gRPC service backed by an OVOS STT model container."""

    def __init__(self, model) -> None:
        """Initialise with a model container that exposes ``process_audio``."""
        self._model = model

    async def StreamingRecognize(
            self,
            request_iterator: AsyncIterator[pb.StreamingRecognitionRequest],
            context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[pb.StreamingRecognitionResponse]:
        """Buffer incoming audio chunks, transcribe once, yield a single final response.

        The first ``StreamingRecognitionRequest`` in the stream must carry a
        ``RecognitionConfig`` (``config`` oneof variant) to set ``sample_rate_hertz``
        and ``language_code``.  All subsequent requests with ``audio_content`` bytes are
        concatenated into a single PCM buffer.  When the client closes the stream the
        buffer is decoded by the OVOS STT model and the transcript is returned as a
        single ``StreamingRecognitionResponse`` with ``final=True`` and
        ``end_of_utterance=True``.
        """
        buffer = bytearray()
        sample_rate = 16000
        language = "en"
        async for request in request_iterator:
            which = request.WhichOneof("streaming_request")
            if which == "config":
                spec = request.config.specification
                if spec.sample_rate_hertz:
                    sample_rate = int(spec.sample_rate_hertz)
                if spec.language_code:
                    language = spec.language_code
            elif which == "audio_content":
                buffer.extend(request.audio_content)

        if buffer:
            audio = AudioData(bytes(buffer), sample_rate, 2)
            transcript = self._model.process_audio(audio, language) or ""
        else:
            transcript = ""

        chunk = pb.SpeechRecognitionChunk(
            alternatives=[pb.SpeechRecognitionAlternative(
                text=transcript,
                confidence=1.0,
            )],
            final=True,
            end_of_utterance=True,
        )
        yield pb.StreamingRecognitionResponse(chunks=[chunk])


async def start_grpc_server(model, host: str, port: int) -> grpc.aio.Server:
    """Start the gRPC server bound to host:port. Returns the running server.

    Caller is responsible for awaiting `server.wait_for_termination()` and
    `server.stop()` on shutdown.
    """
    server = grpc.aio.server()
    pb_grpc.add_SttServiceServicer_to_server(_SttServicer(model), server)
    addr = f"{host}:{port}"
    server.add_insecure_port(addr)
    await server.start()
    _LOG.info("Vosk-gRPC server listening on %s", addr)
    return server


def run_grpc_server_blocking(model, host: str = "0.0.0.0",
                             port: int = 50051) -> None:
    """Blocking helper — start the server and wait forever (or until cancelled).

    Intended for spawning from `__main__.py` either in its own thread or as
    a top-level asyncio.run() target.
    """
    async def _main():
        server = await start_grpc_server(model, host, port)
        try:
            await server.wait_for_termination()
        finally:
            await server.stop(grace=2.0)
    asyncio.run(_main())
