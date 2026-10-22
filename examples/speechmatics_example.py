"""Drive the official speechmatics-batch SDK against an ovos-stt-http-server instance.

Prerequisites:
    pip install speechmatics-batch
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/speechmatics_example.py path/to/clip.wav
"""
import asyncio
import sys

from speechmatics.batch import AsyncClient, TranscriptionConfig


OVOS_HOST = "http://localhost:8080"


async def transcribe(audio_path: str) -> str:
    client = AsyncClient(api_key="ignored", url=f"{OVOS_HOST}/speechmatics/v2")
    try:
        transcript = await client.transcribe(
            audio_path,
            transcription_config=TranscriptionConfig(language="en"),
            polling_interval=0.5,
        )
    finally:
        await client.close()
    return transcript.transcript_text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    print(asyncio.run(transcribe(sys.argv[1])))
