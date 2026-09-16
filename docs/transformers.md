# Transformer Pipelines

The server can run OVOS transformer plugins around transcription. Both
hooks live in the model containers, so **every** surface gets them: the
native `/stt` endpoint, all vendor-compat routers, the websocket streaming
routes, MCP and UTCP.

- **Audio transformers** process the audio *before* the STT stage. When the
  chain includes an `AudioLanguageDetector`, its detected language resolves
  `lang=auto` (an explicitly requested language always wins).
- **Utterance transformers** rewrite the *transcript* before it is
  returned.

## Configuration

Loading is config-gated and opt-in via the standard mycroft.conf sections;
with no config the server behaves exactly as before:

```json
{
  "audio_transformers": {
    "ovos-audio-transformer-plugin-speechbrain-langdetect": {}
  },
  "utterance_transformers": {
    "ovos-utterance-corrections-plugin": {}
  }
}
```

Chains run in ascending priority order (OVOS-TRANSFORM §4); an explicit
`"order"` list in a section wins over priorities. In multi-model mode
(`--multi`) one set of transformer instances is shared across the
per-language engines. See the
[ovos-plugin-manager transformer docs](https://github.com/OpenVoiceOS/ovos-plugin-manager/blob/dev/docs/transformers.md)
for the full contract.

## When to use — and the surprise factor

An utterance transformer on the *server* means clients receive a
**different transcript than what the STT engine heard** — a client sends
audio saying "who is the speaker of teh house" and gets back a corrected
string it can't distinguish from raw STT output. Do it on purpose:

- **Fleet-wide corrections**: domain vocabulary fixes (product names,
  callsigns, jargon) applied once, for every client of this server.
- **Language routing**: an `AudioLanguageDetector` in the audio chain lets
  heterogeneous clients send `lang=auto` and still hit the right model.
- **Audio cleanup**: server-side denoise before STT when clients are thin
  and can't do it themselves.

If the effect should be **per-device** (one bad microphone needs denoise),
run the audio transformer on that device instead — and never enable the
same plugin on both sides, or it is applied twice. Similarly, if the OVOS
stack consuming this server already runs utterance transformers
(ovos-core does), enable each text plugin in exactly one of the two places.

---
[← API compatibility](api-compatibility.md) · [Home](README.md) · [Wyoming integration →](wyoming-integration.md)
