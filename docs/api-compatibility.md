# API Compatibility

## What you can do

You have code that sends audio to a cloud speech-to-text API, and you want the transcript to come from your own OVOS STT plugin instead. Change the base URL in that code to this server. The request, the response and the SDK stay the same.

Each vendor API has its own URL prefix, so all of them answer at the same time. The server accepts any API key and ignores it. Put authentication in your reverse proxy.

The OpenAI, Groq, ElevenLabs Scribe and Deepgram routes accept WAV at any sample rate, and compressed files that ffmpeg reads, such as FLAC, MP3 and OGG. Compressed formats need the `audio` extra (`pip install "ovos-stt-http-server[audio]"`) and ffmpeg. A `.raw` or `.pcm` upload is read as 16 kHz 16-bit mono PCM.

## User stories

Each recipe below was run against `ovos-stt-server --engine ovos-stt-plugin-vosk` with a 2.03 s clip of the words "turn on the kitchen light". The output lines are the real output.

### I have code for the OpenAI SDK

Set `base_url` to the `/openai/v1` prefix. `model` is accepted and ignored.

```python
from openai import OpenAI

client = OpenAI(api_key="unused", base_url="http://localhost:8080/openai/v1")
with open("kitchen.flac", "rb") as f:
    print(client.audio.transcriptions.create(model="whisper-1", file=f).text)
with open("kitchen.wav", "rb") as f:
    print(client.audio.transcriptions.create(model="whisper-1", file=f, response_format="srt"))
```

```text
turn on the kitchen light
1
00:00:00,000 --> 00:00:02,028
turn on the kitchen light
```

`response_format` can be `json`, `text`, `verbose_json`, `srt` or `vtt`. `verbose_json` gives the audio length in `duration` and one segment for the whole clip. `client.audio.translations.create(...)` returns English. When the server has a translation plugin, it translates the transcript; otherwise it returns the transcript. A file that is not audio gets a 400 error.

### I have code for the Groq SDK

Set `base_url` to the `/groq` prefix. The response has the extra `x_groq` block that the Groq SDK expects.

```python
from groq import Groq

client = Groq(api_key="unused", base_url="http://localhost:8080/groq")
with open("kitchen.wav", "rb") as f:
    print(client.audio.transcriptions.create(model="whisper-large-v3", file=f).text)
```

```text
turn on the kitchen light
```

### I have code for another vendor SDK

These SDKs were run against the same server and clip. Each line is the transcript the SDK returned.

| SDK | Setting | Call | Output |
| :--- | :--- | :--- | :--- |
| `deepgram-sdk` 7.13.0 | `DeepgramClientEnvironment(base="http://localhost:8080/deepgram", ...)` | `client.listen.v1.media.transcribe_file(request=wav, model="nova-3")` | `turn on the kitchen light` |
| `elevenlabs` 3.0.0a1 | `ElevenLabs(base_url="http://localhost:8080/elevenlabs")` | `client.speech_to_text.convert(file=f, model_id="scribe_v1")` | `turn on the kitchen light` |
| `ibm-watson` 11.2.0 | `stt.set_service_url("http://localhost:8080/watson/speech-to-text")` | `stt.recognize(audio=f, content_type="audio/wav")` | `turn on the kitchen light` |
| `assemblyai` 1.6.5 | `aai.settings.base_url = "http://localhost:8080/assemblyai"` | `aai.Transcriber().transcribe("kitchen.wav")` | `turn on the kitchen light` |

The Deepgram SDK needs all four URLs of `DeepgramClientEnvironment`: `base`, `production`, `agent` (with `ws://`) and `agent_rest`, each pointing at the `/deepgram` prefix.

## Endpoint status

"Live" means that the client in the table was run against a server with a real STT plugin and a speech clip, as in the stories above. "SDK test" means that the repository's integration tests run the client against a server with a stand-in engine.

| Vendor | Client | Status |
| :--- | :--- | :--- |
| OpenAI | `openai` SDK `audio.transcriptions`, `audio.translations`, all five response formats | Live |
| Groq | `groq` SDK | Live |
| Deepgram (REST) | `deepgram-sdk` | Live |
| ElevenLabs Scribe | `elevenlabs` SDK | Live |
| IBM Watson (REST) | `ibm-watson` SDK | Live |
| AssemblyAI | `assemblyai` SDK | Live |
| Deepgram, AssemblyAI, Speechmatics, Watson, AWS (streaming) | WebSocket clients | SDK test |
| Google Cloud STT, Speechmatics batch, Gladia, Azure, AWS Transcribe batch, Wit.ai, Chromium, whisper.cpp | vendor client or HTTP | SDK test |

## Reference

The shared network-redirect concept lives in
[`voice-pihole.md`](voice-pihole.md). Per-vendor sections cross-reference it.

### Mounted routers

`create_app()` mounts these routers. A runnable client script for each is in [`../examples/`](../examples/).

#### Commercial cloud STT

| Vendor | Method | Path | Client / example |
| :--- | :--- | :--- | :--- |
| OpenAI Whisper | POST | `/openai/v1/audio/transcriptions`, `/openai/v1/audio/translations` | official `openai`, [`openai_whisper_example.py`](../examples/openai_whisper_example.py) |
| Groq | POST | `/groq/openai/v1/audio/transcriptions` | official `groq`, [`groq_example.py`](../examples/groq_example.py); OpenAI-compatible, returns an extra `x_groq` block |
| Deepgram | POST / WS | `/deepgram/v1/listen` | official `deepgram-sdk`, [`deepgram_example.py`](../examples/deepgram_example.py) |
| Google Cloud STT | POST | `/google/v1/speech:recognize` | HTTP, [`../examples/`](../examples/) |
| AssemblyAI | POST / GET / WS | `/assemblyai/v2/upload`, `/assemblyai/v2/transcript`, realtime WS | official `assemblyai`, [`assemblyai_example.py`](../examples/assemblyai_example.py) |
| Gladia | POST / GET | `/gladia/v2/upload` → `/gladia/v2/transcription` → `/gladia/v2/transcription/{id}` | HTTP (no SDK), [`gladia_example.py`](../examples/gladia_example.py) |
| Speechmatics | POST / GET / WS | `/speechmatics/...` batch jobs + realtime WS | official `speechmatics-batch`, [`speechmatics_example.py`](../examples/speechmatics_example.py) |
| Microsoft Azure Speech | POST / WS | `/azure-stt/cognitiveservices/v1` | HTTP, [`azure_stt_example.py`](../examples/azure_stt_example.py) |
| AWS Transcribe | POST / WS | `/aws/transcribe` (batch) + streaming WS | official `boto3`, [`aws_transcribe_example.py`](../examples/aws_transcribe_example.py) |
| IBM Watson STT | POST / WS | `/watson/speech-to-text/v1/recognize` | official `ibm-watson`, [`ibm_watson_example.py`](../examples/ibm_watson_example.py) |
| ElevenLabs Scribe | POST | `/elevenlabs/v1/speech-to-text` | official `elevenlabs`, [`elevenlabs_scribe_example.py`](../examples/elevenlabs_scribe_example.py) |
| Wit.ai | POST | `/wit/speech` | official `wit`, [`wit_ai_example.py`](../examples/wit_ai_example.py) |
| Chromium Web Speech | POST | `/speech-api/v2/recognize` | `ovos-stt-plugin-chromium`, [`chromium_example.py`](../examples/chromium_example.py), [details below](#chromium--chrome-web-speech-api-speech-apiv2) |

#### Self-hosted / OSS server protocols

| Server | Method | Path | Client / example |
| :--- | :--- | :--- | :--- |
| whisper.cpp HTTP server | POST | `/whisper-cpp/inference` (and OpenAI alias `/whisper-cpp/v1/audio/transcriptions`) | HTTP, [`whisper_cpp_example.py`](../examples/whisper_cpp_example.py) |
| vosk-server (WebRTC) | POST | `/vosk-webrtc/offer` | requires the optional `aiortc` dependency |
| OpenAI-compatible Whisper hosts | POST | `/openai/v1/audio/transcriptions` | Groq, Cloudflare Workers AI, Fireworks AI, Together AI, OpenRouter, faster-whisper-server; all speak the OpenAI contract, so point them at the `/openai/v1` prefix |
| Wyoming (Home Assistant) | none | external adapter | see [`wyoming-integration.md`](wyoming-integration.md) |

### Not mounted by default

These routers exist in the package, but `create_app()` does not mount them in the default application. They need extra dependencies, a separate process, or a dedicated CLI flag:

| Server | Surface | Notes |
| :--- | :--- | :--- |
| vosk-server (WebSocket) | `/vosk` | router present, not mounted in the default app |
| vosk-server (gRPC) | `--vosk-grpc-port` | separate gRPC service |
| vosk-server (MQTT) | `--vosk-mqtt-broker` | separate MQTT bridge |
| kaldi-gstreamer-server | `/client/ws/speech`, `/client/ws/status` | router present, not mounted in the default app |


---

### Chromium / Chrome Web Speech API (`/speech-api/v2`)

**Upstream sources**:
- Wire format reverse-engineered in
  [OpenVoiceOS/ovos-stt-plugin-chromium](https://github.com/OpenVoiceOS/ovos-stt-plugin-chromium)
- Original protocol description: [Chromium speech API key history](http://web.archive.org/web/20160309230031/http://www.chromium.org/developers/how-tos/api-keys)

#### Endpoint

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/speech-api/v2/recognize` | FLAC body → newline-delimited JSON results |

Query parameters (all accepted, all silently ignored; the OVOS plugin
chooses what to recognise):

| Param | Notes |
| :--- | :--- |
| `client` | Defaults to `chromium`. Some upstream clients use `chrome`. |
| `lang` | BCP-47 language tag, forwarded to the OVOS plugin. |
| `key` | Chromium API key. Accepted, never validated. |
| `pFilter` | Profanity filter flag, accepted, ignored. |

#### Response

Two newline-delimited JSON lines, matching the upstream wire format
verbatim. Some clients only parse the second. Others stream both. We send
both even for empty results so streaming consumers see at least one frame:

```json
{"result":[]}
{"result":[{"alternative":[{"transcript":"hello world","confidence":0.99}],"final":true}],"result_index":0}
```

Empty-transcript case emits only the first line.

#### Pointing apps at this server

The canonical "SDK" for this API is the `ovos-stt-plugin-chromium`
package. It speaks the exact wire format. Drive it against this server
with a `requests` monkey-patch (in production replace this with the
nginx redirect below):

```python
import ovos_stt_plugin_chromium as chromium_mod
real_post = chromium_mod.requests.post

def patched_post(url, *args, **kwargs):
    if url.startswith("http://www.google.com/speech-api"):
        url = "http://localhost:8080/speech-api" + url.split("/speech-api", 1)[1]
    return real_post(url, *args, **kwargs)

chromium_mod.requests.post = patched_post

from ovos_stt_plugin_chromium import ChromiumSTT
plugin = ChromiumSTT(config={"lang": "en-us"})
# plugin.execute(audio) routes through patched_post → our server
```

A runnable version (with full `speech_recognition` audio fixture) lives in
[`examples/chromium_example.py`](../examples/chromium_example.py).

#### Network-level redirect

For DNS interception + reverse-proxy recipes (replace the vendor host on a LAN without touching client code), see the per-vendor section in [`voice-pihole.md`](voice-pihole.md).

## Deployment

The server listens on port 8080 by default. Put it behind a reverse proxy that checks the API key, because the server itself accepts any key. [`voice-pihole.md`](voice-pihole.md) shows how to send a client that has the vendor host name built in to this server.

## Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| The OpenAI SDK gets 404 | `base_url` ends in `/v1` | Use `http://host:8080/openai/v1` |
| A FLAC or MP3 upload gets 501 | The `audio` extra is not installed | `pip install "ovos-stt-http-server[audio]"`, and install ffmpeg |
| An upload gets 400 `The file is named .wav but has no WAV header` | The file is not a WAV file | Send the file with its real extension |
| `verbose_json` `language` is a code such as `en-US` | The server reports the language the plugin answered in, as a BCP-47 tag | OpenAI gives a language name such as `english`; read the field as a tag |

---
[← Audio formats](audio-formats.md) · [Home](README.md) · [Transformers →](transformers.md)
