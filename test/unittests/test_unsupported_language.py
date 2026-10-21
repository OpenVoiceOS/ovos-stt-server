"""An unsupported language answers 400; a plugin fault stays 500.

The stub plugin fails the way faster-whisper fails: it raises ValueError for a
language it does not know.
"""
from typing import ClassVar
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import ovos_stt_http_server as srv

PCM = b"".join(i.to_bytes(2, "little", signed=True) for i in range(-800, 800))


class StubSTT:
    available_languages: ClassVar[set] = {"en", "pt", "zh"}

    def __init__(self, config=None):
        self.config = config or {}
        self.lang = "en"

    def execute(self, audio, language=None):
        if language == "crash":
            raise ValueError("the plugin failed on its own account")
        if language.split("-")[0] not in self.available_languages:
            raise ValueError(f"'{language.split('-')[0]}' is not a valid language code")
        return f"transcribed:{language}"

    def bind(self, detector):
        pass


class SilentSTT(StubSTT):
    """An engine that advertises no languages: the server cannot check it."""
    available_languages: ClassVar[set] = set()

    def execute(self, audio, language=None):
        if language == "crash":
            raise ValueError("the plugin failed on its own account")
        return f"transcribed:{language}"


@pytest.fixture(params=[False, True], ids=["single", "multi"])
def make_client(request):
    def make(plugin=StubSTT):
        with patch("ovos_stt_http_server.load_stt_plugin", return_value=plugin):
            app, _ = srv.create_app("stub", multi=request.param)
        return TestClient(app, raise_server_exceptions=False)
    return make


def test_unknown_language_answers_400_not_500(make_client):
    resp = make_client().post("/stt?lang=xx-YY", content=PCM)
    assert resp.status_code == 400
    assert resp.json() == {"error": "the language 'xx-yy' is not one this STT engine supports."}


@pytest.mark.parametrize("lang", ["pt-PT", "zh-tw", "en-US"])
def test_regional_variant_of_a_supported_language_is_served(make_client, lang):
    resp = make_client().post(f"/stt?lang={lang}", content=PCM)
    assert (resp.status_code, resp.text) == (200, f"transcribed:{lang.lower()}")


def test_plugin_value_error_still_answers_500(make_client):
    resp = make_client(SilentSTT).post("/stt?lang=crash", content=PCM)
    assert resp.status_code == 500


def test_engine_without_advertised_languages_is_not_checked(make_client):
    resp = make_client(SilentSTT).post("/stt?lang=xx-YY", content=PCM)
    assert (resp.status_code, resp.text) == (200, "transcribed:xx-yy")
