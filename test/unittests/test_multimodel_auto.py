# Licensed under the Apache License, Version 2.0
"""MultiModelContainer must resolve "auto" before it routes.

The container holds one engine per language and picks the engine by the
language string. With `lang="auto"` and no `stt_lang` from the audio
transformers, it passed "auto" straight to `get_engine`, which loaded a plugin
configured with `lang="auto"` and cached it under that key. The audio then went
to an engine for a language that does not exist, and the caller was told the
language was "auto".

"auto" is a request to detect, not a language.
"""
import pytest


class FakeEngine:
    """Records the language it was configured and called with."""

    created = []

    def __init__(self, config=None):
        self.config_lang = (config or {}).get("lang")
        FakeEngine.created.append(self.config_lang)

    def execute(self, audio, language=None):
        return f"transcribed:{language}"

    def bind(self, lang_plugin):
        pass


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.created = []
    yield
    FakeEngine.created = []


def _container(monkeypatch, detector=None):
    import ovos_stt_http_server as srv

    monkeypatch.setattr(srv, "load_stt_plugin", lambda plugin: FakeEngine)
    container = srv.MultiModelContainer("fake-plugin", config={"lang": "en-us"})
    if detector is not None:
        monkeypatch.setattr(container, "detect_language", detector)
    return container


def test_auto_detects_and_routes_to_that_engine(monkeypatch):
    """The detected language picks the engine and is reported back."""
    container = _container(monkeypatch, lambda audio, valid=None: ("fr-fr", 0.9))

    utterance, lang = container.transcribe(b"x", "auto")

    assert lang == "fr-fr", "auto must resolve before the container routes"
    assert utterance == "transcribed:fr-fr"
    assert FakeEngine.created == ["fr-fr"], \
        f"an engine was built for {FakeEngine.created}, not for the detected language"
    assert "auto" not in container.engines, \
        "an engine was cached under the key auto"


def test_detection_failure_falls_back_to_the_configured_language(monkeypatch):
    """A control: a failed detection routes to the configured language."""

    def boom(audio, valid=None):
        raise NotImplementedError("no detector")

    container = _container(monkeypatch, boom)

    utterance, lang = container.transcribe(b"x", "auto")

    assert lang == "en-us"
    assert utterance == "transcribed:en-us"
    assert "auto" not in container.engines


def test_stt_lang_from_the_transformers_still_wins(monkeypatch):
    """A control: a language the transformers reported needs no detection."""
    container = _container(monkeypatch, lambda audio, valid=None: ("fr-fr", 0.9))
    monkeypatch.setattr(container, "transform_audio",
                        lambda audio: (audio, {"stt_lang": "pt-pt"}))

    assert container.transcribe(b"x", "auto")[1] == "pt-pt"
    assert FakeEngine.created == ["pt-pt"]


def test_an_explicit_language_is_not_detected(monkeypatch):
    """A control: an explicit language routes straight to its engine."""

    def boom(audio, valid=None):
        raise AssertionError("detection ran for an explicit language")

    container = _container(monkeypatch, boom)

    assert container.transcribe(b"x", "de-de")[1] == "de-de"
    assert FakeEngine.created == ["de-de"]
