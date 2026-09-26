# `ovos-stt-http-server` Documentation Hub

`ovos-stt-http-server` exposes any OVOS STT plugin as a network service. On
its own it speaks one native protocol. With compat routers enabled it
also answers as every major cloud STT API and every popular
self-hosted server, so **unmodified consumer apps transparently land on
this box** instead of a third-party cloud.

| Goal | Read |
| :--- | :--- |
| Run the server and use the native API | [index.md](index.md) |
| Make unmodified consumer apps stop calling cloud STT services | [voice-pihole.md](voice-pihole.md) |
| Drive this server with the official Python/Node SDK of a specific vendor | [api-compatibility.md](api-compatibility.md) |
| Replace an existing self-hosted STT server on the wire | [api-compatibility.md](api-compatibility.md) |
| Bridge Home Assistant Voice / Voice PE | [wyoming-integration.md](wyoming-integration.md) |
| Audio format negotiation | [audio-formats.md](audio-formats.md) |

## Compat coverage

Mounted by `create_app()` and live on `dev` (a runnable client script for each
is in [`../examples/`](../examples/); full reference in
[`api-compatibility.md`](api-compatibility.md)):

### Commercial cloud STT

| Vendor | Prefix |
| :--- | :--- |
| OpenAI Whisper | `/v1/audio/{transcriptions,translations}` |
| Groq | `/groq/openai/v1/audio/transcriptions` |
| Deepgram | `/deepgram/v1/listen` (HTTP + WS) |
| Google Cloud STT | `/google/v1/speech:recognize` |
| AssemblyAI | `/assemblyai/v2/{upload,transcript,realtime/ws}` |
| Gladia | `/gladia/v2/{upload,transcription,transcription/{id}}` |
| Speechmatics | `/speechmatics/...` (REST + WS) |
| Microsoft Azure Speech | `/azure-stt/cognitiveservices/v1` (REST + WS) |
| AWS Transcribe | `/aws/transcribe` (batch + streaming WS) |
| IBM Watson STT | `/watson/speech-to-text/v1/recognize` (REST + WS) |
| ElevenLabs Scribe | `/elevenlabs/v1/speech-to-text` |
| Wit.ai (Meta) | `/wit/speech` |
| Chromium Web Speech | `/speech-api/v2/recognize` |

### Self-hosted / open-source server protocols

| Server | Surface |
| :--- | :--- |
| whisper.cpp HTTP server | `/inference` (+ OpenAI alias `/v1/audio/transcriptions`) |
| vosk-server (WebRTC) | `/vosk-webrtc/offer` (needs the `aiortc` extra) |
| faster-whisper-server | re-uses `/v1/audio/transcriptions` |
| Wyoming (HA) | external adapter, see [wyoming-integration.md](wyoming-integration.md) |

### OpenAI-compatible Whisper hosts

Apps targeting Groq, Cloudflare Workers AI, Fireworks AI, Together AI, or
OpenRouter already speak the OpenAI `/v1/audio/transcriptions` contract. Point
them at this server's `/v1` prefix.

### Planned / not mounted by default

Present in the package but not mounted by `create_app()` (need a separate
process or CLI flag), tracked for a future release: vosk-server WebSocket
(`/vosk`), vosk gRPC (`--vosk-grpc-port`), vosk MQTT (`--vosk-mqtt-broker`),
and kaldi-gstreamer-server (`/client/ws/speech`).

## Voice-pihole

[voice-pihole.md](voice-pihole.md) collects every DNS-rewrite + reverse-proxy
+ CA-trust recipe across all the above vendors.

---

## TODO / WIP

### Streaming partial transcripts

Every compat router with a streaming surface (Deepgram WS, AssemblyAI
realtime, Speechmatics RT, Azure WS, Watson WS, vosk WS, AWS streaming,
Chromium) runs as buffered batch. Audio is collected for the lifetime
of the stream and a single final transcript is emitted on close. OVOS
STT plugins don't expose a partial / interim hypothesis interface.

Needed:
- A VAD-driven chunker upstream of the OVOS plugin call, OR
- New plugin-side streaming support (OPM contract change).

### Vendor coverage gaps

- **Web Speech API native binary protocol**: the `Sec-WebSocket-Protocol`
  framing modern Chrome/Edge use for the in-browser `SpeechRecognition`
  Web API. Distinct from the legacy `/speech-api/v2/recognize` REST.
- **Rev.ai**: REST + streaming WS.
- **Soniox**: gRPC streaming.
- **AssemblyAI streaming V3**: schema differs from the V2 realtime.
- **whisper.cpp `verbose_json` with segment timestamps**: needs VAD pipeline.
- **AWS Transcribe streaming over real HTTP/2 event-stream**: the WS surface
  ships a plain WS. SDK-level apps that bypass WS need a translator.
- **vosk gRPC `StatsService`**: second proto service not implemented.
