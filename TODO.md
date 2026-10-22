# TODO — ovos-stt-http-server

## Open issues

- [ ] #39 Dependency Dashboard
- [ ] #34 expose via UTCP and MCP
- [ ] #33 supported languages endpoint (enhancement)
- [ ] #32 translation endpoint (enhancement)
- [ ] #31 openai api compatibility (enhancement)

## Gaps

- [ ] No coverage workflow (gh-automations `coverage.yml`); CI has build-tests, lint, license-check, pip-audit, release_workflow, publish_stable but not coverage.
- [ ] Duplicate CI: both `build_tests.yml` and `unit_tests.yml` call the same `build-tests.yml@dev` reusable workflow — consolidate.
- [ ] README/CLI documentation is ahead of `__main__.py`: documented flags `--lang`, `--gradio`, `--cache`, `--title`, `--description`, `--info`, `--badge` are not implemented.
- [ ] Stale runtime deps: `gradio` and `flask` in `requirements/requirements.txt` are unused by any source module.
- [ ] Committed scratch artifacts: `ovos_stt_http_server.egg-info/`, `.pytest_cache/`, `.idea/`, and scratch report docs `AUDIT.md`, `MAINTENANCE_REPORT.md`, `SUGGESTIONS.md`, `QUICK_FACTS.md`.
- [ ] `POST /lang_detect` will raise when `valid_langs` query param is missing (no guard before `.split(",")`).
- [ ] Dual packaging (`pyproject.toml` + `setup.py`) duplicates metadata; consider dropping `setup.py`.

## Code TODOs

None found.
