"""Drive the official AWS boto3 `transcribe` client against ovos-stt-http-server.

The boto3 SDK accepts `endpoint_url=` cleanly — no monkey-patching needed.
Inline audio is passed as a `data:audio/wav;base64,…` Media URI; the SDK
treats it as opaque and forwards it verbatim.

Prerequisites:
    pip install boto3
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/aws_transcribe_example.py path/to/clip.wav
"""
import base64
import json
import sys
import time
import urllib.request

import boto3


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    client = boto3.client(
        "transcribe",
        endpoint_url=f"{OVOS_HOST}/aws/transcribe",
        region_name="us-east-1",
        aws_access_key_id="ignored",
        aws_secret_access_key="ignored",
    )

    wav = open(audio_path, "rb").read()
    media_uri = "data:audio/wav;base64," + base64.b64encode(wav).decode()
    job_name = f"job-{int(time.time())}"

    client.start_transcription_job(
        TranscriptionJobName=job_name,
        LanguageCode="en-US",
        Media={"MediaFileUri": media_uri},
        MediaFormat="wav",
    )

    # Synchronous on our side, but poll the way real apps do.
    for _ in range(20):
        r = client.get_transcription_job(TranscriptionJobName=job_name)
        if r["TranscriptionJob"]["TranscriptionJobStatus"] == "COMPLETED":
            break
        time.sleep(0.25)
    else:
        sys.exit("job did not complete in time")

    transcript_uri = r["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
    with urllib.request.urlopen(transcript_uri) as resp:
        body = json.loads(resp.read())
    print(body["results"]["transcripts"][0]["transcript"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
