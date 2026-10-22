# AGENTS.md — ovos-stt-http-server

FastAPI micro-service that wraps any OVOS STT plugin and exposes it over HTTP, plus drop-in compatibility routers for several cloud STT vendor APIs.

## Setup

```bash
pip install -e .
# plus the STT plugin you want to serve, e.g.
pip install ovos-stt-plugin-fasterwhisper
```

Runtime deps: `ovos-plugin-manager`, `fastapi~=0.95`, `uvicorn~=0.22`, `ovos-utils`. Configuration is read from `mycroft.conf` via `ovos-config` (the `stt` section), exactly as inside a running assistant.

## Test

```bash
pytest test/
```

Tests live in `test/unittests/test_compat_routers.py` and use FastAPI `TestClient` with a `FakeModel`; no real STT plugin or network needed.

## Lint / Typecheck

Lint runs in CI via `OpenVoiceOS/gh-automations/.github/workflows/lint.yml@dev`. No local lint/type config committed.

## Layout

- `ovos_stt_http_server/__init__.py` — core. `ModelContainer` (single engine) and `MultiModelContainer` (one engine per language) wrap a loaded STT plugin; `create_app()` builds the FastAPI app with native endpoints `GET /status`, `POST /stt`, `POST /lang_detect`, then mounts the compat routers; `start_stt_server()` returns `(app, model)`.
- `ovos_stt_http_server/__main__.py` — CLI entry point `ovos-stt-server` (argparse, runs uvicorn).
- `ovos_stt_http_server/routers/` — vendor-compatible routers, each mounted under a prefix: `openai_whisper.py` (`/openai`), `deepgram.py`, `google_stt.py`, `assemblyai.py`, `speechmatics.py`. Each exposes a `make_*_router(model)` factory.
- `ovos_stt_http_server/audio_utils.py` — `multipart_audio_to_audiodata` and audio helpers.
- `ovos_stt_http_server/audio/` — sample audio clips per language (packaged data).

Entry point is a `console_scripts` script (`ovos-stt-server`), NOT an OVOS/OPM plugin entry-point group. This repo hosts plugins as a service; it does not register one.

## Conventions

- Branches: work on `dev`, stable on `master`. NEVER use `main`.
- Never edit `ovos_stt_http_server/version.py`; gh-automations bumps semver from conventional-commit prefixes (`feat:`, `fix:`, `feat!:`).
- New repos private by default; do not make source public without asking.
- Commit identity: JarbasAi <jarbasai@mailfence.com>.
- Reference `OpenVoiceOS/gh-automations` reusable workflows at `@dev`.
- No Neon / `neon-*` references.
- No meta-commentary in docs/commits/code (no history, no dates, describe current state only).
- CI is provided by OpenVoiceOS/gh-automations.

## Gotchas

- README documents CLI flags (`--lang`, `--multi`, `--gradio`, `--cache`, `--title`, `--description`, `--info`, `--badge`) that `__main__.py` does not implement; only `--engine`, `--lang-engine`, `--port`, `--host`, `--multi` exist. The Gradio web UI and language defaults described in the README are not wired into the current CLI.
- `gradio` and `flask` appear in `requirements/requirements.txt` but no source imports them; they are stale deps not used by the running server.
- `pyproject.toml` and `setup.py` both define metadata/entry points; `pyproject.toml` is the source of truth (`setup.py` reads `version.py` manually).
- `POST /lang_detect` calls `request.query_params.get("valid_langs").split(",")` and will error if `valid_langs` is absent.
- Default port in `__main__.py` is 8080; the README Docker example maps container port 9666.
