# Wyoming integration

The [Wyoming protocol](https://github.com/rhasspy/wyoming) is Home Assistant's
length-prefixed JSONL framing for STT / TTS / wake-word over raw TCP. It is
**not** an HTTP API and is **not** implemented as a router in this server.

## Why not native?

- Wyoming uses raw TCP framing on port 10300, not HTTP. It does not fit the
  FastAPI router model the rest of `ovos-stt-http-server` uses.
- Dedicated bridge servers already exist and are kept in sync with upstream
  Wyoming (which evolves independently of our HTTP compat layer).
- Mixing two transport stacks in this repo would duplicate maintenance
  surface area for no functional gain.

## Use these adapter repos instead

Each adapter speaks Wyoming on its native TCP port and forwards to a backend
service of the matching type. Point it at this server (or any OVOS plugin)
and Home Assistant Voice / Voice PE picks it up transparently.

| Adapter | Repo | Backend it bridges |
|---|---|---|
| Wyoming STT  | [TigreGotico/wyoming-ovos-stt](https://github.com/TigreGotico/wyoming-ovos-stt) | Any OVOS STT plugin, or **this server's** `/stt` endpoint |
| Wyoming TTS  | [TigreGotico/wyoming-ovos-tts](https://github.com/TigreGotico/wyoming-ovos-tts) | Any OVOS TTS plugin (paired with [`ovos-tts-server`](https://github.com/OpenVoiceOS/ovos-tts-server)) |
| Wyoming wake | [TigreGotico/wyoming-ovos-wakeword](https://github.com/TigreGotico/wyoming-ovos-wakeword) | Any OVOS wake-word plugin |

## Typical deployment

```text
  ┌─────────────────────────┐         ┌──────────────────────────┐
  │  Home Assistant Voice   │  TCP    │  wyoming-ovos-stt        │
  │  (wyoming client)       ├────────►│  (port 10300)            │
  └─────────────────────────┘         └────────────┬─────────────┘
                                                   │ HTTP
                                                   ▼
                                       ┌──────────────────────────┐
                                       │  ovos-stt-http-server    │
                                       │  /stt (port 8080)        │
                                       └──────────────────────────┘
```

Run all three on the same box (or split them across hosts):

```bash
# 1. The STT engine
ovos-stt-server --engine ovos-stt-plugin-fasterwhisper --port 8080

# 2. The Wyoming bridge: point it at our HTTP endpoint
wyoming-ovos-stt --uri tcp://0.0.0.0:10300 --stt-url http://localhost:8080
```

Configure Home Assistant's Wyoming integration with `tcp://<host>:10300` and
all the usual HA voice-pipeline plumbing (intent recognition, fallback agents,
wake word) sees a normal Wyoming STT service, with no special-casing for OVOS.

## See also

- [`rhasspy/wyoming`](https://github.com/rhasspy/wyoming): protocol spec
- [Home Assistant Voice docs](https://www.home-assistant.io/voice_control/)
- The TTS counterpart lives in [`ovos-tts-server`](https://github.com/OpenVoiceOS/ovos-tts-server).
  The wake-word counterpart lives in any OVOS wake-word plugin repo.

---
[← Transformers](transformers.md) · [Home](README.md) · [Voice pihole →](voice-pihole.md)
