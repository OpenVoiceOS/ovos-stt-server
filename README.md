# OpenVoiceOS STT HTTP Server

Turn any OVOS STT plugin into an HTTP microservice for speech-to-text and
spoken-language detection.

Pair it with the [companion client plugin](https://github.com/OpenVoiceOS/ovos-stt-server-plugin)
to offload transcription from an OVOS device, or point existing tooling at the
[vendor-compatible endpoints](#vendor-compatible-endpoints) below.

## Contents

- [Install](#install)
- [Configuration](#configuration)
- [Usage](#usage)
- [HTTP API](#http-api)
- [AI Agent Integration](#ai-agent-integration): MCP & UTCP
- [Vendor-compatible endpoints](#vendor-compatible-endpoints)
- [Docker](#docker)
- [Documentation](#documentation)
- [Examples](#examples)
- [Credits](#credits)

## Install

```bash
pip install ovos-stt-http-server
```

The server only hosts plugins. Install at least one STT plugin alongside it:

```bash
pip install ovos-stt-plugin-fasterwhisper
```

Optional extras:

| Extra | Installs | Enables |
|-------|----------|---------|
| `mcp` | `pip install "ovos-stt-http-server[mcp]"` | embedded [MCP](#mcp--model-context-protocol) server at `/mcp` (requires `--mcp` flag) |
| `audio` | `pip install "ovos-stt-http-server[audio]"` | non-WAV audio decoding (`pydub`) for the vendor-compat routers |

## Configuration

The STT plugin is configured exactly as it would be inside an assistant, under
`mycroft.conf`:

```json
{
  "stt": {
    "module": "ovos-stt-plugin-deepgram",
    "ovos-stt-plugin-deepgram": {"key": "xxxxx"}
  }
}
```

## Usage

```bash
$ ovos-stt-server --help
usage: ovos-stt-server [-h] --engine ENGINE [--lang-engine LANG_ENGINE]
                       [--host HOST] [--port PORT] [--multi] [--mcp]

options:
  -h, --help                 show this help message and exit
  --engine ENGINE            STT plugin to be used (required)
  --lang-engine LANG_ENGINE  audio language-detection plugin to be used (optional)
  --host HOST                host to bind (default: 0.0.0.0)
  --port PORT                TCP port (default: 8080)
  --multi                    load one plugin instance per language (more memory)
  --mcp                      mount MCP server at /mcp (requires ovos-stt-http-server[mcp])
```

For example, to serve [faster-whisper](https://github.com/OpenVoiceOS/ovos-stt-plugin-fasterwhisper)
for transcription with matching audio language detection:

```bash
ovos-stt-server \
  --engine ovos-stt-plugin-fasterwhisper \
  --lang-engine ovos-audio-transformer-plugin-fasterwhisper
```

## HTTP API

The native API is unauthenticated. Audio is sent as the raw request body.

| Method & path | Body | Purpose |
|---------------|------|---------|
| `GET /status` | none | Service status and loaded plugin names |
| `POST /stt` | raw PCM bytes | Transcribe audio → plain-text transcript |
| `POST /lang_detect` | raw PCM bytes | Detect the spoken language → `{"lang", "conf"}` |

`POST /stt` query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lang` | system lang or `auto` | Language code, or `auto` to run language detection first |
| `sample_rate` | `16000` | Audio sample rate in Hz |
| `sample_width` | `2` | Sample width in bytes (`2` = int16) |

The body must be **raw PCM** (16-bit signed, mono). Example with a WAV file
decoded to PCM on the fly:

```bash
# 16 kHz mono int16 PCM in body
curl -s --data-binary @speech.pcm \
  -H 'Content-Type: application/octet-stream' \
  'http://localhost:8080/stt?lang=en&sample_rate=16000&sample_width=2'
```

See [`examples/native_example.py`](examples/native_example.py) for a runnable
script that reads a WAV file and posts its PCM frames. Full reference:
[docs/index.md](docs/index.md).

### Transformer pipelines

The server can run OVOS transformer plugins around transcription, on every
endpoint: **audio transformers** process audio before STT (an
`AudioLanguageDetector` in the chain resolves `lang=auto`) and **utterance
transformers** rewrite the transcript before it is returned. Opt-in via the
standard mycroft.conf sections:

```json
{
  "utterance_transformers": {
    "ovos-utterance-corrections-plugin": {}
  }
}
```

Enabling an utterance transformer server-side means clients receive a
**different transcript than the raw STT output**. Use it for fleet-wide
vocabulary corrections. See
[docs/transformers.md](docs/transformers.md) for when to run transformers
server-side vs on-device and how to avoid double-processing.

## AI Agent Integration

### MCP: Model Context Protocol

Install the optional extra and start the server with `--mcp` to expose it as an
MCP tool provider:

```bash
pip install "ovos-stt-http-server[mcp]"
ovos-stt-server --engine ovos-stt-plugin-fasterwhisper --mcp
```

Installing the `mcp` extra alone does **not** mount the endpoint — the flag is
required. With `--mcp` set, the server mounts an MCP endpoint at `/mcp` using
the streamable-HTTP transport (compatible with both the legacy SSE path
`/mcp/sse` and the newer `POST /mcp` format). If `--mcp` is passed without the
extra installed, the server logs a warning and starts without `/mcp`.

#### Connecting an MCP client

##### Claude Desktop / claude-code (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "ovos-stt": {
      "transport": "http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

##### ovos-tool-adapters persona JSON

```json
{
  "toolboxes": ["ovos-mcp-toolbox"],
  "ovos-mcp-toolbox": {
    "transport": "http",
    "url": "http://localhost:8080/mcp",
    "timeout": 30
  }
}
```

#### Available MCP tool

| Tool | Description |
|---|---|
| `transcribe` | Transcribe PCM audio to text. Accepts `audio_b64` (base64 PCM) or `audio_path` (server-side file path), plus `lang`, `sample_rate`, `sample_width`. |

Example call (Python MCP client):

```python
import asyncio, base64
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def main():
    async with streamablehttp_client("http://localhost:8080/mcp") as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            audio_b64 = base64.b64encode(open("speech.pcm", "rb").read()).decode()
            result = await session.call_tool("transcribe", {
                "audio_b64": audio_b64,
                "lang": "en-us",
            })
            print(result.content[0].text)

asyncio.run(main())
```

### UTCP: Universal Tool Calling Protocol

No extra dependencies are required. Every running server exposes a UTCP manual at:

```
GET /utcp
```

The response is a UTCP-1.0 JSON document describing the `stt`, `lang_detect`, and
`status` tools so any UTCP client can discover and invoke them without separate
documentation. The `url` fields use the server's actual base URL, so the manual
is correct even behind a reverse proxy.

Register a UTCP client's provider config at `/utcp`:

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "tool_providers": [
        {
          "name": "ovos-stt",
          "provider_type": "http",
          "url": "http://localhost:8080/utcp"
        }
      ]
    }
  }
}
```

## Vendor-compatible endpoints

The server mounts compat routers under per-vendor prefixes so existing tools and
SDKs that already target a cloud STT API can be pointed at your local OVOS
instance with only a base-URL / endpoint override. Every router accepts (and
silently ignores) the vendor's auth token. Authentication is the job of your
reverse proxy.

| Vendor | Prefix | Client (see `examples/`) |
|--------|--------|--------------------------|
| OpenAI Whisper | `/v1/audio/transcriptions` | official `openai` |
| Groq | `/groq/openai/v1/audio/transcriptions` | official `groq` |
| Deepgram | `/deepgram/v1/listen` | official `deepgram-sdk` |
| Google Cloud STT | `/google/v1/speech:recognize` | HTTP |
| AssemblyAI | `/assemblyai/v2/...` | official `assemblyai` |
| Gladia | `/gladia/v2/transcription` | HTTP (upload → poll) |
| Speechmatics | `/speechmatics/...` | official `speechmatics-batch` |
| Microsoft Azure Speech | `/azure-stt/cognitiveservices/v1` | HTTP |
| AWS Transcribe | `/aws/...` | official `boto3` |
| IBM Watson STT | `/watson/speech-to-text/v1/recognize` | official `ibm-watson` |
| ElevenLabs Scribe | `/elevenlabs/v1/speech-to-text` | official `elevenlabs` |
| Wit.ai | `/wit/speech` | official `wit` |
| Chromium Web Speech | `/speech-api/v2/recognize` | `ovos-stt-plugin-chromium` |
| whisper.cpp server | `/inference` | HTTP |
| vosk-server (WebRTC) | `/vosk-webrtc/offer` | needs the `aiortc` extra |

A runnable script for each lives in [`examples/`](examples/). Full endpoint
reference, per-vendor notes, and network-redirect recipes:
[docs/api-compatibility.md](docs/api-compatibility.md).

## Docker

Any plugin can be served with a small Dockerfile:

```dockerfile
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    ovos-stt-http-server \
    ovos-stt-plugin-fasterwhisper

EXPOSE 8080
ENTRYPOINT ["ovos-stt-server", "--engine", "ovos-stt-plugin-fasterwhisper"]
```

Build and run:

```bash
docker build -t my-stt-server .
docker run -p 8080:8080 my-stt-server
```

Each plugin can ship its own Dockerfile in its repository using
`ovos-stt-http-server` as the base.

## Documentation

| Document | Covers |
|----------|--------|
| [docs/index.md](docs/index.md) | Overview, native HTTP API, architecture, audio format |
| [docs/api-compatibility.md](docs/api-compatibility.md) | Vendor routers: prefixes, endpoints, clients |
| [docs/audio-formats.md](docs/audio-formats.md) | Accepted audio encodings and conversion |
| [docs/transformers.md](docs/transformers.md) | Audio/utterance transformer plugins around transcription |
| [docs/wyoming-integration.md](docs/wyoming-integration.md) | Home Assistant Voice / Wyoming bridge |
| [docs/voice-pihole.md](docs/voice-pihole.md) | DNS-redirect + reverse-proxy recipes per vendor |

## Examples

[`examples/`](examples/) holds one runnable script per vendor router (driving
each vendor's real client SDK where one exists) plus a native-API script. See
[examples/README.md](examples/README.md).

## Credits

Developed by [TigreGótico](https://tigregotico.pt) for
[OpenVoiceOS](https://openvoiceos.org).

[![NGI0 Commons Fund](./ngi.png)](https://nlnet.nl/project/OpenVoiceOS)

This project was funded through the [NGI0 Commons Fund](https://nlnet.nl/commonsfund),
a fund established by [NLnet](https://nlnet.nl) with financial support from the
European Commission's [Next Generation Internet](https://ngi.eu) programme, under
the aegis of [DG Communications Networks, Content and Technology](https://commission.europa.eu/about-european-commission/departments-and-executive-agencies/communications-networks-content-and-technology_en)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429).
