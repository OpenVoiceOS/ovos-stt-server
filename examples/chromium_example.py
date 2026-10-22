"""Drive the canonical `ovos-stt-plugin-chromium` against ovos-stt-http-server.

The plugin POSTs to `http://www.google.com/speech-api/v2/recognize` — we
monkey-patch its `requests.post` to retarget our local prefix. In
production replace this with an `/etc/hosts` + nginx redirect (see
docs/api-compatibility.md).

Prerequisites:
    pip install ovos-stt-plugin-chromium SpeechRecognition
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080

Usage:
    python examples/chromium_example.py path/to/clip.wav
"""
import io
import sys
import wave


OVOS_HOST = "http://localhost:8080"


def main(audio_path: str) -> None:
    import ovos_stt_plugin_chromium as chromium_mod
    real_post = chromium_mod.requests.post

    def patched_post(url, *args, **kwargs):
        if url.startswith("http://www.google.com/speech-api"):
            url = OVOS_HOST + "/speech-api" + url.split("/speech-api", 1)[1]
        return real_post(url, *args, **kwargs)

    chromium_mod.requests.post = patched_post

    from ovos_stt_plugin_chromium import ChromiumSTT
    import speech_recognition as sr

    with wave.open(audio_path) as wf:
        frames = wf.readframes(wf.getnframes())
        rate = wf.getframerate()
        sw = wf.getsampwidth()
    audio = sr.AudioData(frames, rate, sw)

    plugin = ChromiumSTT(config={"lang": "en-us"})
    print(plugin.execute(audio, language="en-us"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
