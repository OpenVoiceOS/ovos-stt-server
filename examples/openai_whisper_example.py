"""Drive the official OpenAI SDK against an ovos-stt-http-server instance.

Prerequisites:
    pip install openai
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/openai_whisper_example.py path/to/clip.wav
"""
import sys

from openai import OpenAI


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    client = OpenAI(base_url=f"{OVOS_HOST}/openai/v1", api_key="ignored")
    with open(audio_path, "rb") as fp:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=fp,
        )
    print(response.text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
