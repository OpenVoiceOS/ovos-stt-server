"""Call the native ovos-stt-http-server API (standard library only).

The native API needs no vendor SDK. ``POST /stt`` takes **raw PCM** bytes in the
request body (16-bit signed, mono) plus ``sample_rate`` / ``sample_width`` query
params. This script reads a WAV file with the stdlib ``wave`` module and posts
its PCM frames, so it works with any mono 16-bit WAV.

    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

    python examples/native_example.py path/to/clip.wav
    python examples/native_example.py path/to/clip.wav en
    python examples/native_example.py status
"""
import json
import sys
import urllib.parse
import urllib.request
import wave

OVOS_HOST = "http://localhost:8080"


def _get(path: str):
    with urllib.request.urlopen(f"{OVOS_HOST}{path}", timeout=30) as resp:
        return json.load(resp)


def transcribe(wav_path: str, lang: str = "auto") -> str:
    with wave.open(wav_path, "rb") as wf:
        if wf.getnchannels() != 1:
            sys.exit("error: expected a mono WAV file")
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
        pcm = wf.readframes(wf.getnframes())

    query = urllib.parse.urlencode(
        {"lang": lang, "sample_rate": sample_rate, "sample_width": sample_width}
    )
    req = urllib.request.Request(
        f"{OVOS_HOST}/stt?{query}",
        data=pcm,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8")


def main(argv: list) -> None:
    if argv == ["status"]:
        print(json.dumps(_get("/status"), ensure_ascii=False))
    elif len(argv) in (1, 2) and argv[0] != "status":
        print(transcribe(argv[0], argv[1] if len(argv) == 2 else "auto"))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
