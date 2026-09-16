"""Drive the official Groq SDK against an ovos-stt-http-server instance.

Groq exposes Whisper through an OpenAI-compatible surface rooted at
``/openai/v1``; the ovos-stt-http-server Groq router mounts the same shape
under ``/groq``.

Prerequisites:
    pip install groq
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/groq_example.py path/to/clip.wav
"""
import sys
from pathlib import Path

from groq import Groq


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    client = Groq(api_key="ignored", base_url=f"{OVOS_HOST}/groq")
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(Path(audio_path).name, f.read()),
            model="whisper-large-v3",
        )
    print(result.text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
