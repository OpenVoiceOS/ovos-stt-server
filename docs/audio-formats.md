# Audio Formats

The native `/stt` endpoint accepts raw PCM bytes (16 kHz, mono, 16-bit signed).

Compat routers accept uploaded audio files in a variety of formats via the
shared helper `ovos_stt_http_server.audio_utils.multipart_audio_to_audiodata`:

- **WAV** is decoded with the stdlib `wave` module.
- Any other format (mp3, flac, ogg, m4a, webm, …) is decoded via `pydub`,
  which requires `ffmpeg` to be available on the host.

`pydub` is an optional dependency — install via the `[audio]` extra:

```bash
pip install ovos-stt-http-server[audio]
```

If a non-WAV upload arrives and `pydub` is not installed, the server
replies with `501 Not Implemented`.

## Vendor-specific notes

| Vendor | Default content-type | Notes |
| :--- | :--- | :--- |
| OpenAI Whisper | `multipart/form-data` (`file=@`) | accepts whatever Whisper accepts |
| Deepgram | `audio/wav` or raw PCM body | Content-Type sniffed |
| Google Cloud STT | base64 in JSON body | `config.encoding` accepts `LINEAR16` or int 1 |
| AssemblyAI | base64 in JSON or `audio_url` referencing `/v2/upload` | SDK-driven 3-step flow |
| Speechmatics | `multipart/form-data` (`data_file=@`) | `config` form field carries JSON |
| Azure Speech | `audio/wav` body (REST) or framed WS audio | rest accepts ≤60s |
| AWS Transcribe | `data:audio/wav;base64,...` in `MediaFileUri` | inline only; S3 not fetched |
| IBM Watson | `audio/wav` or `audio/l16;rate=16000` | WS uses `audio/l16` |
| Wit.ai | `audio/wav` or `audio/raw;rate=...;bits=...` | content-type drives decoding |
| Chromium | `audio/x-flac;rate=...` | FLAC encoder → pydub decoder |
| vosk WS / MQTT | raw 16-bit PCM | rate from `config` |
| kaldi-gstreamer | `audio/x-raw,rate=...,format=S16LE,...` caps | parsed from content-type |
| whisper.cpp | `multipart/form-data` (`file=@`) | any audio pydub can read |

---
[← Index](index.md) · [Home](README.md) · [API compatibility →](api-compatibility.md)
