# AI agents: MCP and UTCP

This page shows how to give an AI agent speech-to-text with this server.

## Contents

- [What you can do](#what-you-can-do)
- [Start the server](#start-the-server)
- [Let Claude Code transcribe a recording](#let-claude-code-transcribe-a-recording)
- [Use the server from Claude Desktop](#use-the-server-from-claude-desktop)
- [Let opencode transcribe a recording](#let-opencode-transcribe-a-recording)
- [Let Mistral Vibe transcribe a recording](#let-mistral-vibe-transcribe-a-recording)
- [Give an OVOS persona or agent a speech-to-text tool](#give-an-ovos-persona-or-agent-a-speech-to-text-tool)
- [Let a UTCP agent discover the endpoints](#let-a-utcp-agent-discover-the-endpoints)
- [Send audio that is not 16 kHz PCM](#send-audio-that-is-not-16-khz-pcm)
- [Run the server in a container with MCP on](#run-the-server-in-a-container-with-mcp-on)
- [Reference](#reference)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

## What you can do

**MCP** (Model Context Protocol) is the protocol that Claude Code, Claude
Desktop, opencode, Mistral Vibe and most agent frameworks use to call tools. Start the server with
`--mcp` and it gives agents one tool, `transcribe`, at `/mcp`. MCP needs the
`mcp` extra.

**UTCP** (Universal Tool Calling Protocol) lets an agent call the plain HTTP
endpoints of the server directly. The server describes those endpoints in a
UTCP manual at `GET /utcp`. A UTCP client reads the manual once and then calls
`/stt/json`, `/lang_detect` and `/status`. The manual is always available and
needs no extra.

The examples use the CLI default address, `http://localhost:8080`. Change it
to the address of your server.

## Start the server

Every task on this page uses a running server with MCP on:

```bash
pip install --pre "ovos-stt-http-server[mcp]" ovos-stt-plugin-vosk
ovos-stt-server --engine ovos-stt-plugin-vosk --mcp
```

The outputs on this page come from the `ovos-stt-plugin-vosk` small English
model and a synthetic voice saying "turn on the kitchen lights please". A
better model gives a better transcript.

## Let Claude Code transcribe a recording

You get a `transcribe` tool in Claude Code. You can then ask Claude to
transcribe a file on your machine.

1. Add the server:

   ```bash
   claude mcp add --transport http ovos-stt http://localhost:8080/mcp
   ```

2. Make sure that Claude Code can connect:

   ```bash
   claude mcp list
   ```

   On success, the list shows:

   ```
   ovos-stt: http://localhost:8080/mcp (HTTP) - ✔ Connected
   ```

3. Ask Claude, for example: "Transcribe the recording /home/me/meeting.wav
   with the ovos-stt transcribe tool, language en-us." Claude calls
   `mcp__ovos-stt__transcribe` and replies with the transcript:

   ```
   the on the kitchen light sleeve
   ```

The tool reads the file on the server machine, so this recipe works when
Claude Code and the server run on the same machine. For a remote server,
Claude sends the audio as base64 in `audio_b64`.

If the list shows `✘ Failed to connect`, make sure that the server runs with
`--mcp`. See [Troubleshooting](#troubleshooting).

## Use the server from Claude Desktop

You get the same `transcribe` tool in Claude Desktop.

`claude_desktop_config.json` starts local MCP servers as commands. It does not
accept a URL. Use the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
bridge, which needs Node.js:

```json
{
  "mcpServers": {
    "ovos-stt": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8080/mcp"]
    }
  }
}
```

Restart Claude Desktop after you change the file. The bridge lists one tool,
`transcribe`.

`mcp-remote` accepts plain HTTP only for `localhost`. For a server at another
address, add `"--allow-http"` to `args`, or put the server behind HTTPS. A
Claude custom connector (Settings, Connectors) is for an MCP server on the
internet. For a server on your machine or your LAN, use `mcp-remote`.

## Let opencode transcribe a recording

You get `transcribe` in opencode.

1. Start the server with `--mcp`.
2. Add this entry to `opencode.json` in your project folder:

   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "mcp": {
       "ovos-stt": {
         "type": "remote",
         "url": "http://localhost:8080/mcp",
         "enabled": true
       }
     }
   }
   ```

3. Check the connection:

   ```console
   $ opencode mcp list
   ┌  MCP Servers
   │
   ●  ✓ ovos-stt connected
   │      http://localhost:8080/mcp
   │
   └  1 server(s)
   ```

## Let Mistral Vibe transcribe a recording

You get `transcribe` in Vibe.

1. Start the server with `--mcp`.
2. Add this entry to `~/.vibe/config.toml`:

   ```toml
   [[mcp_servers]]
   name = "ovos-stt"
   transport = "streamable-http"
   url = "http://localhost:8080/mcp"
   ```

   Write the entry in the file. Do not use `vibe mcp add` for this server: that
   command sets OAuth login for an HTTP server, and the server does not use
   OAuth.

3. Start `vibe`. Vibe loads the tools of the server when it starts. It gives
   each tool the server name as a prefix, and it changes each hyphen to `_`:
   `ovos_stt_transcribe`.

## Give an OVOS persona or agent a speech-to-text tool

You give an OVOS persona or agent a speech-to-text tool through the
[ovos-tool-adapters](https://github.com/OpenVoiceOS/ovos-tool-adapters)
toolboxes.

With MCP, add this toolbox to the agent configuration:

```json
{
  "toolboxes": ["ovos-mcp-toolbox"],
  "ovos-mcp-toolbox": {"transport": "http", "url": "http://localhost:8080/mcp", "timeout": 30}
}
```

The toolbox finds one tool, `transcribe`. A call with
`audio_path="/home/me/speech.wav"` and `lang="en-us"` returns:

```
content='the on the kitchen light sleeve' is_error=False
```

With UTCP, add this toolbox:

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "manual_call_templates": [
        {"name": "ovos_stt", "call_template_type": "http",
         "url": "http://localhost:8080/utcp", "http_method": "GET"}
      ]
    },
    "timeout": 30
  }
}
```

The toolbox finds three tools: `ovos_stt_stt`, `ovos_stt_lang_detect` and
`ovos_stt_status`. The toolbox replaces the dots in the UTCP tool names with
underscores. Call `ovos_stt_stt` with the audio as base64 in its `body`
argument, for example `body={"audio_b64": "<base64 of a WAV file>", "lang":
"en-us"}`. The call returns:

```
on the kitchen light sleeve
```

`ovos_stt_lang_detect` takes raw PCM bytes in `body`, which a toolbox cannot
send, so agents use `ovos_stt_stt` and `ovos_stt_status`.

## Let a UTCP agent discover the endpoints

You call the server from any UTCP 1.x client, with no MCP layer.

Install the client with `pip install --pre utcp utcp-http`, then run:

```python
import asyncio
import base64

from utcp.data.utcp_client_config import UtcpClientConfig
from utcp.utcp_client import UtcpClient


async def main():
    client = await UtcpClient.create(config=UtcpClientConfig(manual_call_templates=[{
        "name": "ovos_stt",
        "call_template_type": "http",
        "http_method": "GET",
        "url": "http://localhost:8080/utcp",
    }]))
    with open("speech.wav", "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()
    result = await client.call_tool("ovos_stt.stt", {"body": {"audio_b64": audio_b64, "lang": "en-us"}})
    print(result)


asyncio.run(main())
```

On success, the script prints the transcript and the language:

```
{'text': 'on the kitchen light sleeve', 'lang': 'en-us'}
```

The `stt` tool posts its `body` argument as JSON to `/stt/json`. `audio_b64`
holds a WAV file, or raw PCM at `sample_rate` and `sample_width`. Audio that is
not base64 answers HTTP 400. The UTCP HTTP client accepts plain HTTP only for `localhost`, `127.0.0.1` and `::1`. For a
server at another address, put it behind HTTPS. See
[Run behind a reverse proxy](#run-behind-a-reverse-proxy).

## Send audio that is not 16 kHz PCM

The MCP `transcribe` tool decodes a WAV file with its own sample rate, sample
width and channels. It reads all other bytes as raw PCM. For other formats,
convert the file to a 16-bit WAV first:

```bash
ffmpeg -i memo.mp3 -ar 16000 -ac 1 -c:a pcm_s16le memo.wav
```

Then send the WAV file. With the Python MCP client (`pip install --pre mcp`):

```python
import asyncio
import base64

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client("http://localhost:8080/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            with open("memo.wav", "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode()
            result = await session.call_tool("transcribe", {"audio_b64": audio_b64, "lang": "en-us"})
            print(result.content[0].text)


asyncio.run(main())
```

On success, the script prints the transcript:

```
on the kitchen light sleeve
```

An MP3 or OGG file sent as it is gives an empty transcript, with no error. A
float WAV gives the error `unknown format: 3`. Convert both with the `ffmpeg`
command above.

The UTCP `stt` tool and `POST /stt/json` decode WAV files the same way. The
raw `/stt` endpoint reads raw PCM only. Send it the output of
`ffmpeg -i memo.mp3 -ar 16000 -ac 1 -f s16le memo.pcm`.

## Run the server in a container with MCP on

You get the MCP endpoint from a container. Install the `mcp` extra in the
image and give `--mcp` to the server:

```dockerfile
FROM python:3.11-slim
RUN pip install --no-cache-dir --pre "ovos-stt-http-server[mcp]" ovos-stt-plugin-vosk
EXPOSE 9666
ENTRYPOINT ["ovos-stt-server", "--host", "0.0.0.0", "--port", "9666"]
CMD ["--engine", "ovos-stt-plugin-vosk", "--mcp"]
```

Build and run it:

```bash
podman build -t ovos-stt-mcp .
podman run -p 9666:9666 ovos-stt-mcp
```

The MCP endpoint is then `http://127.0.0.1:9666/mcp`. A `transcribe` call with
a 44.1 kHz stereo WAV returns `on the kitchen light sleeve`. The UTCP manual
at `http://127.0.0.1:9666/utcp` gives tool URLs on `http://127.0.0.1:9666`.

The same steps work with `docker` in place of `podman`.

## Reference

### MCP

The MCP endpoint is at `/mcp` and uses the streamable HTTP transport. The
server has no SSE endpoint. The MCP server has the name `ovos-stt` and one
tool, `transcribe`:

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `audio_b64` | string | none | Base64 of a WAV file or of raw PCM bytes. |
| `audio_path` | string | none | Absolute path of a WAV or raw PCM file on the server machine. |
| `lang` | string | `"auto"` | Language tag, for example `en-us`. |
| `sample_rate` | integer | `16000` | Sample rate of raw PCM, in Hz. A WAV file uses its own rate. |
| `sample_width` | integer | `2` | Bytes per sample of raw PCM. A WAV file uses its own width. |

Give one of `audio_b64` or `audio_path`. When you give both, the tool uses
`audio_path`. The tool returns the transcript as text, or an empty string when
it hears nothing.

A WAV file holds integer samples of 8, 16, 24 or 32 bits, mono or with more
channels. This includes the WAVE_FORMAT_EXTENSIBLE header that ffmpeg and sox
write for 24-bit, 32-bit and multi-channel files, on every supported Python
version. The tool converts the audio to 16-bit mono and averages the channels.
The server gives the WAV sample rate to the plugin with the audio.

Raw PCM is mono, signed and little-endian. The tool does not resample raw PCM
and does not check it: PCM at a rate other than `sample_rate` gives an empty or
incorrect transcript, with no error.

With `lang="auto"`, the server resolves the language the same way as for
`/stt?lang=auto`. It uses the language-detection plugin from `--lang-engine`.
When no detection is available, it uses the language that the STT plugin is
configured for. A server started with `--multi` resolves the language the same
way before it chooses the model for that language. When neither detection nor
a configured language gives a language, the call fails with
`no language was resolved for this audio`. Give an explicit `lang` when you
know the language.

### UTCP

`GET /utcp` returns a UTCP 1.0 manual. Each tool uses an HTTP call template:

| Tool | HTTP call | Arguments | Returns |
|---|---|---|---|
| `stt` | `POST /stt/json` | `body`: `{"audio_b64", "lang", "sample_rate", "sample_width"}` | `{"text": ..., "lang": ...}` |
| `lang_detect` | `POST /lang_detect` | `body` (raw PCM), `valid_langs` (optional, comma-separated) | `{"lang": ..., "conf": ...}` |
| `status` | `GET /status` | none | `{"status": ..., "plugin": ..., "lang_plugin": ...}` |

The client sends `body` as the request body and the other arguments as query
parameters. For `stt`, `body` is a JSON object with the audio as base64. For
`lang_detect`, `body` is raw PCM bytes. A UTCP client adds the manual name to the tool name, for example
`ovos_stt.stt`.

`lang_detect` needs a plugin that can detect the language. Without one, a
call with two or more `valid_langs` answers HTTP 501. A call with one
language returns that language with `conf` 1.0.

### Python

| Function | Module | Use |
|---|---|---|
| `start_stt_server(engine, enable_mcp=True)` | `ovos_stt_http_server` | Create the app with `/mcp` mounted. |
| `build_mcp(engine)` | `ovos_stt_http_server.mcp_server` | Create the FastMCP server. |
| `mount_mcp(app, engine, path="/mcp")` | `ovos_stt_http_server.mcp_server` | Mount MCP on your own FastAPI app. |
| `build_utcp_manual(engine, base_url)` | `ovos_stt_http_server.utcp` | Create the UTCP manual as a dict. |
| `make_utcp_router(engine)` | `ovos_stt_http_server.utcp` | Create the router that serves `GET /utcp`. |

## Deployment

### MCP availability

`/mcp` is mounted only when both are true:

- The `mcp` extra is installed: `pip install --pre "ovos-stt-http-server[mcp]"`.
- The server starts with `--mcp`, or `create_app`/`start_stt_server` gets
  `enable_mcp=True`.

The extra alone does not mount `/mcp`. This prevents an installed package from
exposing a tool endpoint that you did not ask for. With `--mcp` and no extra,
the server starts without `/mcp` and logs a warning that tells you to install
the `mcp` extra.

### Run behind a reverse proxy

The tool URLs in the UTCP manual come from each request. The server uses the
`Host` header and the `X-Forwarded-Proto` header. It does not read
`X-Forwarded-Host` or `X-Forwarded-Prefix`.

Configure the proxy as follows:

1. Send the public host name in `Host`. For nginx:
   `proxy_set_header Host $host;`.
2. Send the scheme in `X-Forwarded-Proto`. For nginx:
   `proxy_set_header X-Forwarded-Proto $scheme;`.
3. When the proxy does not connect from `127.0.0.1`, start the server with
   `FORWARDED_ALLOW_IPS` set to the address of the proxy. Without it, the
   server ignores `X-Forwarded-Proto` and the manual shows `http://` URLs.
4. Serve the server at the root of the host, not under a path prefix. The
   manual cannot show a prefix.

With nginx in front, a request for `/utcp` gives tool URLs such as
`https://stt.example.org/stt/json`, and MCP clients connect to
`https://stt.example.org/mcp`. The server answers both `/mcp` and `/mcp/`
with no redirect.

### Security

The MCP and UTCP endpoints have no authentication. Anybody who can connect to
the port can use them. Put an authenticating reverse proxy in front of a
server that other networks can reach.

`audio_path` reads any file that the server process can read. A client can
name any path on the server machine. The error for a path that does not exist
is different from the result for a file that exists, so a client can find out
which files exist. Do not give `/mcp` to clients that you do not trust.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/mcp` answers 404 | The server started without `--mcp`, or the `mcp` extra is not installed. | Run `pip install --pre "ovos-stt-http-server[mcp]"` and give `--mcp`. |
| `/mcp/sse` answers 404 | The server has no SSE endpoint. | Use the streamable HTTP URL, `/mcp`. |
| `transcribe` returns an empty string | The audio is not WAV or raw PCM at the given rate, or it has no speech. | Convert the audio with `ffmpeg`. See [Send audio that is not 16 kHz PCM](#send-audio-that-is-not-16-khz-pcm). |
| `unknown format: 3` | The WAV file holds float samples. | Convert it to a 16-bit WAV with `ffmpeg`. |
| `unknown format: 65534` (Python 3.10 and 3.11) or `unknown extended format: 00000003-...` (Python 3.12 and later) | The WAV file has an extensible header with float or compressed samples, as ffmpeg writes for float audio with more than two channels. | Convert it to a 16-bit WAV with `ffmpeg`. |
| `Provide either audio_b64 or audio_path` | The call has no audio. | Give one of the two arguments. |
| `mcp-remote` prints `Non-HTTPS URLs are only allowed for localhost` | The URL uses plain HTTP to an address that is not `localhost`. | Add `--allow-http`, or use HTTPS. |
| A UTCP client prints `URL must use HTTPS or be a literal loopback address` | The manual URL is plain HTTP to another host. | Put the server behind HTTPS. See [Run behind a reverse proxy](#run-behind-a-reverse-proxy). |
| The OVOS MCP toolbox logs `too many values to unpack (expected 2, got 3)` | `mcp` 1.x is installed. | Install `mcp` 2 or later. |
| `lang_detect` answers HTTP 501 | The STT plugin cannot detect the language, and no `--lang-engine` is set. | Start the server with a language-detection plugin, or give one language in `valid_langs`. |
