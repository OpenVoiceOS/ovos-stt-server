"""Drive the official `ibm-watson` SDK against an ovos-stt-http-server instance.

The SDK exposes `set_service_url()` for endpoint override — no monkey-patch.

Prerequisites:
    pip install ibm-watson
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/ibm_watson_example.py path/to/clip.wav
"""
import sys

from ibm_watson import SpeechToTextV1
from ibm_cloud_sdk_core.authenticators import NoAuthAuthenticator


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    stt = SpeechToTextV1(authenticator=NoAuthAuthenticator())
    stt.set_service_url(f"{OVOS_HOST}/watson/speech-to-text")
    stt.set_disable_ssl_verification(True)  # plain HTTP locally

    with open(audio_path, "rb") as fp:
        result = stt.recognize(
            audio=fp,
            content_type="audio/wav",
            model="en-US_BroadbandModel",
        ).get_result()

    text = result["results"][0]["alternatives"][0]["transcript"]
    print(text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
