"""Drive Gladia's v2 upload -> transcription -> poll flow against ovos-stt-http-server.

Gladia's API is asynchronous; ovos-stt-http-server runs the OVOS engine
synchronously, so the job is already ``done`` on the first poll.

Gladia has **no official Python SDK** (it is consumed over its REST API), so
this example calls the HTTP endpoints directly rather than driving a vendor SDK.

Prerequisites:
    pip install requests
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/gladia_example.py path/to/clip.wav
"""
import sys

import requests


OVOS_HOST = "http://localhost:8080/gladia"


def main(audio_path: str) -> None:
    with open(audio_path, "rb") as f:
        up = requests.post(f"{OVOS_HOST}/v2/upload",
                           files={"audio": (audio_path, f, "audio/wav")})
    up.raise_for_status()
    audio_url = up.json()["audio_url"]
    if audio_url.startswith("/"):
        audio_url = f"http://localhost:8080{audio_url}"

    tx = requests.post(f"{OVOS_HOST}/v2/transcription", json={"audio_url": audio_url})
    tx.raise_for_status()
    job_id = tx.json()["id"]

    res = requests.get(f"{OVOS_HOST}/v2/transcription/{job_id}")
    res.raise_for_status()
    print(res.json()["result"]["transcription"]["full_transcript"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
