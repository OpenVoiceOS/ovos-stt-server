"""Drive the official Deepgram SDK against an ovos-stt-http-server instance.

Prerequisites:
    pip install deepgram-sdk
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/deepgram_example.py path/to/clip.wav
"""
import sys
from pathlib import Path

from deepgram import DeepgramClient, DeepgramClientEnvironment


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    env = DeepgramClientEnvironment(
        base=f"{OVOS_HOST}/deepgram",
        production=f"{OVOS_HOST}/deepgram",
        # Agent (voice-agent) endpoints aren't implemented by ovos-stt-http-server,
        # but DeepgramClientEnvironment requires the field.
        agent=f"{OVOS_HOST.replace('http', 'ws')}/deepgram",
    )
    client = DeepgramClient(api_key="ignored", environment=env)

    audio_bytes = Path(audio_path).read_bytes()
    response = client.listen.v1.media.transcribe_file(
        request=audio_bytes,
        model="nova-3",
        language="en",
        punctuate=True,
    )
    transcript = response.results.channels[0].alternatives[0].transcript
    print(transcript)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
