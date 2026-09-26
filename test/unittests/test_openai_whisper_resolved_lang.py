# Licensed under the Apache License, Version 2.0
"""The OpenAI router must answer with the language the engine transcribed in.

`process_audio` resolves the language inside itself and returns the utterance
alone, so a request that asked for "auto" left the router holding the literal
string "auto". Two answers were wrong: the translator got `source=None` for
audio whose language the engine knew, and a `verbose_json` response reported
`language="en"` for audio detected as anything else.

`transcribe` reports the resolved language beside the utterance.
"""
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav_bytes(frames: int = 160) -> bytes:
    """Return minimal valid WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


class DetectingModel:
    """A model that resolves "auto" to French, as a real container does."""

    def __init__(self):
        self.seen = []

    def transcribe(self, audio, lang: str = "auto"):
        self.seen.append(lang)
        resolved = "fr-fr" if lang == "auto" else lang
        return "bonjour le monde", resolved

    def process_audio(self, audio, lang: str = "auto"):
        return self.transcribe(audio, lang)[0]


class LegacyModel:
    """A model object that predates transcribe()."""

    def process_audio(self, audio, lang: str = "auto"):
        return "hello world"


class RecordingTranslator:
    """A translator that records the source it was given."""

    def __init__(self):
        self.calls = []

    def translate(self, text, target=None, source=None):
        self.calls.append({"text": text, "target": target, "source": source})
        return f"[{target}] {text}"


def _client(model, translator=None) -> TestClient:
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    app = FastAPI()
    app.include_router(make_openai_whisper_router(model, translator=translator))
    return TestClient(app)


def _post(client, route, **data):
    return client.post(
        route,
        files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
        data={"model": "whisper-1", **data},
    )


class TestVerboseJson:
    def test_detected_language_is_reported(self):
        """verbose_json must report the language the engine transcribed in."""
        model = DetectingModel()
        resp = _post(_client(model), "/openai/v1/audio/transcriptions",
                     response_format="verbose_json")
        assert resp.status_code == 200
        assert resp.json()["language"] == "fr-fr"
        assert model.seen == ["auto"], "the router must still hand auto down"

    def test_explicit_language_is_reported(self):
        """A control: an explicit language is reported unchanged."""
        resp = _post(_client(DetectingModel()), "/openai/v1/audio/transcriptions",
                     response_format="verbose_json", language="pt-pt")
        assert resp.json()["language"] == "pt-pt"

    def test_unresolved_language_still_falls_back(self):
        """A control: a model that resolves nothing keeps the en fallback."""

        class UnresolvedModel:
            """Resolves nothing, and answers both calls, so this row is a
            control that must pass on the unfixed source too."""

            def transcribe(self, audio, lang="auto"):
                return "hello world", lang

            def process_audio(self, audio, lang="auto"):
                return "hello world"

        resp = _post(_client(UnresolvedModel()), "/openai/v1/audio/transcriptions",
                     response_format="verbose_json")
        assert resp.json()["language"] == "en"


class TestTranslations:
    def test_source_is_the_detected_language(self):
        """The translator must be told the language the engine answered in."""
        translator = RecordingTranslator()
        resp = _post(_client(DetectingModel(), translator),
                     "/openai/v1/audio/translations")
        assert resp.status_code == 200
        assert len(translator.calls) == 1
        assert translator.calls[0]["source"] == "fr-fr"
        assert translator.calls[0]["target"] == "en"

    def test_source_stays_none_when_nothing_resolves(self):
        """A control: source is None only when the language is unknown."""

        class UnresolvedModel:
            """Resolves nothing, and answers both calls, so this row is a
            control that must pass on the unfixed source too."""

            def transcribe(self, audio, lang="auto"):
                return "hello world", lang

            def process_audio(self, audio, lang="auto"):
                return "hello world"

        translator = RecordingTranslator()
        _post(_client(UnresolvedModel(), translator), "/openai/v1/audio/translations")
        assert translator.calls[0]["source"] is None


class TestLegacyModel:
    def test_model_without_transcribe_still_works(self):
        """A control: a model with process_audio alone keeps working."""
        resp = _post(_client(LegacyModel()), "/openai/v1/audio/transcriptions",
                     response_format="verbose_json")
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"
        assert resp.json()["language"] == "en"


class TestContainerTranscribe:
    def test_model_container_reports_the_detected_language(self, monkeypatch):
        """ModelContainer.transcribe returns the language detection produced."""
        import ovos_stt_http_server as srv

        class FakeEngine:
            lang = "en-us"
            available_languages = {"en-us", "fr-fr"}

            def __init__(self, config=None):
                pass

            def execute(self, audio, language=None):
                return f"transcribed:{language}"

        monkeypatch.setattr(srv, "load_stt_plugin", lambda plugin: FakeEngine)
        container = srv.ModelContainer("fake-plugin")
        monkeypatch.setattr(container, "detect_language",
                            lambda audio, valid=None: ("fr-fr", 0.9))

        utterance, lang = container.transcribe(b"x", "auto")
        assert lang == "fr-fr"
        assert utterance == "transcribed:fr-fr"
        assert container.process_audio(b"x", "auto") == "transcribed:fr-fr"

    def test_model_container_reports_the_fallback_language(self, monkeypatch):
        """A control: a failed detection reports the engine's own language."""
        import ovos_stt_http_server as srv

        class FakeEngine:
            lang = "pt-pt"
            available_languages = {"pt-pt"}

            def __init__(self, config=None):
                pass

            def execute(self, audio, language=None):
                return f"transcribed:{language}"

        monkeypatch.setattr(srv, "load_stt_plugin", lambda plugin: FakeEngine)
        container = srv.ModelContainer("fake-plugin")

        def boom(audio, valid=None):
            raise RuntimeError("no detector")

        monkeypatch.setattr(container, "detect_language", boom)
        assert container.transcribe(b"x", "auto")[1] == "pt-pt"
