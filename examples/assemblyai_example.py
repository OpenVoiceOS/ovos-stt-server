"""Drive the official AssemblyAI SDK against an ovos-stt-http-server instance.

Prerequisites:
    pip install assemblyai
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/assemblyai_example.py path/to/clip.wav
"""
import sys

import assemblyai as aai


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    aai.settings.base_url = f"{OVOS_HOST}/assemblyai"
    aai.settings.api_key = "ignored"
    # ovos-stt-http-server returns status=completed on the first poll
    aai.settings.polling_interval = 0.1

    transcript = aai.Transcriber().transcribe(audio_path)
    if transcript.status == aai.TranscriptStatus.error:
        sys.exit(f"transcription failed: {transcript.error}")
    print(transcript.text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
