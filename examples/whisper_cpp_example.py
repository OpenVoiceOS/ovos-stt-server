"""Drive the whisper.cpp HTTP-server protocol against an ovos-stt-http-server instance.

whisper.cpp's HTTP server has no client SDK — `curl`-like requests is the
canonical pattern.

Prerequisites:
    pip install requests
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/whisper_cpp_example.py path/to/clip.wav
"""
import sys

import requests


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    with open(audio_path, "rb") as fp:
        r = requests.post(
            f"{OVOS_HOST}/whisper-cpp/inference",
            files={"file": (audio_path, fp, "audio/wav")},
            data={"language": "en", "response_format": "json"},
        )
    r.raise_for_status()
    print(r.json()["text"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
