"""Drive the official `wit` Python SDK against an ovos-stt-http-server instance.

The SDK reads its API base from the `WIT_URL` environment variable — set it
before importing, and the SDK's `requests` calls flow through your prefix.

Prerequisites:
    pip install wit
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/wit_ai_example.py path/to/clip.wav
"""
import os
import sys


OVOS_HOST = "http://localhost:8080"
# MUST come before `import wit` (the module reads WIT_URL at load time)
os.environ["WIT_URL"] = f"{OVOS_HOST}/wit"

from wit import Wit  # noqa: E402


def main(audio_path: str) -> None:
    client = Wit(access_token="ignored")
    with open(audio_path, "rb") as fp:
        result = client.speech(fp, headers={"Content-Type": "audio/wav"})
    print(result["text"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
