"""Drive Microsoft Azure Speech REST short-form against an ovos-stt-http-server instance.

The WS path is documented in docs/api-compatibility.md (requires TLS via nginx
because the official SDK rejects ws://). For local testing, use raw REST:

Prerequisites:
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/azure_stt_example.py path/to/clip.wav
"""
import sys

import requests


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    with open(audio_path, "rb") as fp:
        r = requests.post(
            f"{OVOS_HOST}/azure-stt/cognitiveservices/v1",
            params={"language": "en-US"},
            data=fp.read(),
            headers={"Content-Type": "audio/wav",
                     "Ocp-Apim-Subscription-Key": "ignored"},
            timeout=10,
        )
    r.raise_for_status()
    body = r.json()
    print(body["DisplayText"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
