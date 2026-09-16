# ovos-stt-http-server

A lightweight FastAPI server that exposes any OVOS STT plugin as an HTTP service.

## Architecture

- **Framework**: FastAPI with Uvicorn ASGI server.
- **Plugin loading**: `ovos-plugin-manager` discovers and loads STT plugins by name. `ModelContainer` handles single-language mode; `MultiModelContainer` handles per-language model loading (both in `ovos_stt_http_server/__init__.py`).
- **CORS**: Unconditional `allow_origins=["*"]`, set in `create_app()` in `ovos_stt_http_server/__init__.py`.

## Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/status` | Returns `{"status": "ok", "plugin": ..., "lang_plugin": ...}` |
| `POST` | `/stt` | Raw audio bytes in body → transcribed text (plain text response) |
| `POST` | `/lang_detect` | Raw audio bytes in body → `{"lang": ..., "conf": ...}` |

### `/stt` query parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `lang` | system lang or `auto` | Language code or `auto` to trigger language detection |
| `sample_rate` | `16000` | Audio sample rate in Hz |
| `sample_width` | `2` | Sample width in bytes (2 = int16) |

## Usage

```bash
ovos-stt-server --engine ovos-stt-plugin-whisper --port 8080
ovos-stt-server --engine ovos-stt-plugin-whisper --lang-engine ovos-audio-transformer-plugin-fasterwhisper --multi
```

## Audio Format

Input audio must be raw PCM: 16 kHz, mono, 16-bit signed integer (int16). Send bytes directly as the POST body. The vendor-compat routers also accept their vendors' own audio encodings. See [audio-formats.md](audio-formats.md).

## See also

- [api-compatibility.md](api-compatibility.md): vendor-compatible STT endpoints (OpenAI, Deepgram, Google, AssemblyAI, and others)
- [audio-formats.md](audio-formats.md): accepted audio encodings and conversion
- [wyoming-integration.md](wyoming-integration.md): Home Assistant Voice / Wyoming bridge
- [voice-pihole.md](voice-pihole.md): DNS-redirect + reverse-proxy recipes
