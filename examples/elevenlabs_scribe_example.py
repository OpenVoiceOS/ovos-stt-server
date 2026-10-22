"""Drive the official ElevenLabs SDK (Scribe STT) against ovos-stt-http-server.

Prerequisites:
    pip install elevenlabs
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/elevenlabs_scribe_example.py path/to/clip.wav
"""
import sys

from elevenlabs.client import ElevenLabs


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    client = ElevenLabs(api_key="ignored", base_url=f"{OVOS_HOST}/elevenlabs")
    with open(audio_path, "rb") as f:
        result = client.speech_to_text.convert(file=f, model_id="scribe_v1")
    print(result.text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
