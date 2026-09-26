"""The containers must never hand the literal "auto" to an STT engine.

A plugin gets the language as a vocabulary token. `ovos-stt-plugin-onnx-asr`
builds `<|auto|>`, which the NeMo vocabulary does not hold, and answers
`KeyError: '<|auto|>'`. The vendor-compat routers pass "auto" whenever the
caller sends no language, which is the default request shape for every vendor
API this server imitates, so the failure reaches a user as HTTP 500.

Measured live on stt.openvoiceos.pt in
`knowledge/wiki/audits/ser9/stt-compat-default-language.md`.
"""
from typing import ClassVar
from unittest.mock import patch

import pytest

import ovos_stt_http_server as srv


class RejectsAuto:
    """A backend of the onnx-asr class: "auto" is not a vocabulary token."""

    lang: ClassVar[str] = "en-US"
    available_languages: ClassVar[set] = {"en-US", "pt-PT"}

    def __init__(self, config=None):
        self.config = config or {}

    def execute(self, audio, language=None):
        if language in (None, "auto"):
            raise KeyError(f"<|{language}|>")
        return f"transcribed:{language}"

    def bind(self, lang_plugin):
        self.bound = lang_plugin


class RejectsAutoConfiguredAuto(RejectsAuto):
    """A backend whose own configured language is "auto".

    The server's default is "auto", so a deployment can hand it straight to
    the plugin config.
    """

    lang: ClassVar[str] = "auto"


class DetectsAuto:
    """A detector that answers "auto", which resolves nothing."""

    def detect(self, audio, valid_langs=None):
        return ("auto", 0.5)


class DetectsPortuguese:
    def detect(self, audio, valid_langs=None):
        return ("pt-PT", 0.91)


# ---------- ModelContainer ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_the_configured_language_answers_when_nothing_detects(load_stt):
    load_stt.return_value = RejectsAuto
    mc = srv.ModelContainer("fake")
    assert mc.process_audio(b"x", "auto") == "transcribed:en-US"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_a_detector_that_answers_auto_does_not_reach_the_engine(load_stt):
    load_stt.return_value = RejectsAuto
    mc = srv.ModelContainer("fake")
    mc.lang_plugin = DetectsAuto()
    # "auto" from a detector resolves nothing, so the configured language holds
    assert mc.process_audio(b"x", "auto") == "transcribed:en-US"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_a_configured_auto_does_not_reach_the_engine(load_stt):
    load_stt.return_value = RejectsAutoConfiguredAuto
    mc = srv.ModelContainer("fake")
    # nothing resolves a language: the caller must be told, not the engine
    with pytest.raises(ValueError) as err:
        mc.process_audio(b"x", "auto")
    assert "auto" in str(err.value)


# ---------- MultiModelContainer ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_resolves_auto_through_the_detector(load_stt):
    load_stt.return_value = RejectsAuto
    mc = srv.MultiModelContainer("fake")
    mc.lang_plugin = DetectsPortuguese()
    assert mc.process_audio(b"x", "auto") == "transcribed:pt-PT"
    # the engine is cached under the resolved language, never under "auto"
    assert set(mc.engines) == {"pt-PT"}


@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_falls_back_to_the_configured_language(load_stt):
    load_stt.return_value = RejectsAuto
    mc = srv.MultiModelContainer("fake", config={"lang": "pt-PT"})
    assert mc.process_audio(b"x", "auto") == "transcribed:pt-PT"
    assert "auto" not in mc.engines


@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_with_nothing_to_resolve_raises_instead_of_loading_auto(load_stt):
    load_stt.return_value = RejectsAuto
    mc = srv.MultiModelContainer("fake")
    with pytest.raises(ValueError) as err:
        mc.process_audio(b"x", "auto")
    assert "auto" in str(err.value)
    # no engine was loaded under the literal, so the cache stays clean
    assert mc.engines == {}


# ---------- the HTTP answer ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_the_route_answers_400_rather_than_500(load_stt):
    from fastapi.testclient import TestClient

    load_stt.return_value = RejectsAutoConfiguredAuto
    app, _ = srv.create_app("fake")
    client = TestClient(app)
    resp = client.post("/stt?lang=auto", content=b"\x00\x00" * 16)
    assert resp.status_code == 400, resp.text
    assert "no language was resolved" in resp.json()["error"]


@patch("ovos_stt_http_server.load_stt_plugin")
def test_the_wit_route_that_reads_no_language_answers_400(load_stt):
    """wit_ai hardcodes "auto" and reads no language from the request.

    A caller cannot work that route around, so it is the one that proves the
    container, not the router, now holds the answer.
    """
    import io
    import wave

    from fastapi.testclient import TestClient

    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    wav = buf.getvalue()

    load_stt.return_value = RejectsAutoConfiguredAuto
    app, _ = srv.create_app("fake")
    resp = TestClient(app).post("/wit/speech", content=wav,
                                headers={"Content-Type": "audio/wav"})
    assert resp.status_code == 400, resp.text

    load_stt.return_value = RejectsAuto
    app, _ = srv.create_app("fake")
    resp = TestClient(app).post("/wit/speech", content=wav,
                                headers={"Content-Type": "audio/wav"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "transcribed:en-US"


class BrokenBackend(RejectsAuto):
    """A backend that fails for a reason of its own, with a language resolved."""

    def execute(self, audio, language=None):
        raise ValueError("model weights for en-US are corrupt on disk")


@patch("ovos_stt_http_server.load_stt_plugin")
def test_a_server_fault_stays_500(load_stt):
    """The 400 handler must answer for an unresolved language and nothing else.

    Bound to ValueError itself, the handler told the caller that a broken
    server was a bad request, and handed it the internal message. A retry
    policy reads 400 as "do not retry".
    """
    from fastapi.testclient import TestClient

    load_stt.return_value = BrokenBackend
    app, _ = srv.create_app("fake")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/stt?lang=en-US", content=b"\x00\x00" * 16)
    assert resp.status_code == 500, resp.text
    assert "corrupt on disk" not in resp.text


@patch("ovos_stt_http_server.load_stt_plugin")
def test_a_bad_query_parameter_stays_500(load_stt):
    """int("notanumber") raises ValueError too, and is not a language answer."""
    from fastapi.testclient import TestClient

    load_stt.return_value = RejectsAuto
    app, _ = srv.create_app("fake")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/stt?lang=en-US&sample_rate=notanumber",
                       content=b"\x00\x00" * 16)
    assert resp.status_code == 500, resp.text
