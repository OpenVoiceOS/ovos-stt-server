"""Live test: drive the vosk-server gRPC `SttService.StreamingRecognize` against our service."""
import asyncio
import socket

import pytest

from test.integration.conftest import FakeSTTEngine, make_silent_wav


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def grpc_server_port():
    """Start an isolated gRPC server on a free port for each test."""
    import grpc
    from ovos_stt_http_server.vosk_grpc_server import start_grpc_server

    port = _free_port()
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(
        start_grpc_server(FakeSTTEngine(), "127.0.0.1", port)
    )
    try:
        yield port, loop
    finally:
        loop.run_until_complete(server.stop(grace=1.0))
        loop.close()


def test_streaming_recognize(grpc_server_port):
    import grpc
    from ovos_stt_http_server.proto import stt_service_pb2 as pb
    from ovos_stt_http_server.proto import stt_service_pb2_grpc as pb_grpc

    port, loop = grpc_server_port
    wav = make_silent_wav()

    async def _run():
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = pb_grpc.SttServiceStub(channel)

            async def _requests():
                yield pb.StreamingRecognitionRequest(
                    config=pb.RecognitionConfig(
                        specification=pb.RecognitionSpec(
                            audio_encoding=pb.RecognitionSpec.LINEAR16_PCM,
                            sample_rate_hertz=16000,
                            language_code="en-US",
                        ),
                    ),
                )
                # Stream in two chunks
                yield pb.StreamingRecognitionRequest(audio_content=wav[: len(wav) // 2])
                yield pb.StreamingRecognitionRequest(audio_content=wav[len(wav) // 2 :])

            responses = []
            async for resp in stub.StreamingRecognize(_requests()):
                responses.append(resp)
            return responses

    responses = loop.run_until_complete(_run())
    assert responses, "no response received"
    chunk = responses[0].chunks[0]
    assert chunk.final is True
    assert chunk.alternatives[0].text == "hello world"
