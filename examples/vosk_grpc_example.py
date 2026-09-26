"""Drive the vosk-server gRPC SttService against an ovos-stt-http-server gRPC port.

Prerequisites:
    pip install grpcio
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080 --vosk-grpc-port 50051

Usage:
    python examples/vosk_grpc_example.py path/to/clip.wav
"""
import asyncio
import sys
import wave

import grpc

from ovos_stt_http_server.proto import stt_service_pb2 as pb
from ovos_stt_http_server.proto import stt_service_pb2_grpc as pb_grpc


GRPC_TARGET = "localhost:50051"


async def transcribe(audio_path: str) -> str:
    with wave.open(audio_path) as wf:
        sample_rate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())

    async with grpc.aio.insecure_channel(GRPC_TARGET) as channel:
        stub = pb_grpc.SttServiceStub(channel)

        async def requests():
            yield pb.StreamingRecognitionRequest(
                config=pb.RecognitionConfig(
                    specification=pb.RecognitionSpec(
                        audio_encoding=pb.RecognitionSpec.LINEAR16_PCM,
                        sample_rate_hertz=sample_rate,
                        language_code="en-US",
                    ),
                ),
            )
            # Stream the audio in 64 KiB chunks
            chunk_size = 64 * 1024
            for i in range(0, len(pcm), chunk_size):
                yield pb.StreamingRecognitionRequest(
                    audio_content=pcm[i : i + chunk_size]
                )

        async for response in stub.StreamingRecognize(requests()):
            for chunk in response.chunks:
                if chunk.alternatives:
                    return chunk.alternatives[0].text
        return ""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    print(asyncio.run(transcribe(sys.argv[1])))
