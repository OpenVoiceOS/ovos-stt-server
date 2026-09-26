# Custom containers for ovos-stt-http-server

The base image installs only the server framework; the actual recognition engine
is a separate OVOS STT plugin.  Build a custom image by layering a plugin on top.

## Quick example — faster-whisper (local GPU/CPU inference)

```dockerfile
FROM ghcr.io/openvoiceos/ovos-stt-http-server:dev

RUN pip install --no-cache-dir ovos-stt-plugin-fasterwhisper

COPY config/mycroft.conf /config/mycroft/mycroft.conf

CMD ["--engine", "ovos-stt-plugin-fasterwhisper", \
     "--host", "0.0.0.0", "--port", "9666"]
```

`config/mycroft.conf` for this image:

```json
{
  "stt": {
    "module": "ovos-stt-plugin-fasterwhisper",
    "ovos-stt-plugin-fasterwhisper": {
      "model": "small",
      "language": "en"
    }
  }
}
```

Build and run:

```bash
docker build -t my-stt-fasterwhisper .
docker run -p 8080:9666 my-stt-fasterwhisper
curl http://localhost:8080/status
```

## Compose override for the custom image

Create `docker-compose.override.yml` alongside the root `docker-compose.yml`:

```yaml
services:
  ovos-stt:
    build: .
    image: my-stt-fasterwhisper
    command:
      - "--engine"
      - "ovos-stt-plugin-fasterwhisper"
      - "--host"
      - "0.0.0.0"
      - "--port"
      - "9666"
    volumes:
      - ./config:/config/mycroft
      - ~/.cache/huggingface:/root/.cache/huggingface   # reuse model cache
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Run with `docker compose up` (Compose merges the override automatically).

## Other plugin options

| Plugin | Notes |
|---|---|
| `ovos-stt-plugin-citrinet` | Nvidia NeMo Citrinet — ONNX, CPU-friendly |
| `ovos-stt-plugin-onnx-asr` | ONNX Runtime, many pre-trained models |
| `ovos-stt-plugin-mms` | Meta MMS multilingual |

## MCP / UTCP extras

The server exposes a UTCP tool manifest at `GET /utcp` with no extra dependencies.

For MCP (streamable-HTTP, compatible with Claude Desktop and claude-code), install
the optional extra:

```dockerfile
RUN pip install --no-cache-dir "ovos-stt-http-server[mcp]"
```

and pass `--mcp` when starting the server to mount the `/mcp` endpoint.
