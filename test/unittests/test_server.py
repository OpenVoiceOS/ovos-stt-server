"""Tests for create_app / ModelContainer / MultiModelContainer."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import ovos_stt_http_server as srv


class FakeSTT:
    def __init__(self, config=None):
        self.config = config or {}

    def execute(self, audio, language=None):
        return f"transcribed:{language}"

    def detect_language(self, audio, valid_langs=None):
        return ("en", 0.99)

    def bind(self, lang_plugin):
        self.bound = lang_plugin


class FakeLangDetector:
    def detect(self, audio, valid_langs=None):
        return ("de", 0.77)


# ---------- ModelContainer ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_model_container_basic(load_stt):
    load_stt.return_value = FakeSTT
    mc = srv.ModelContainer("fake")
    assert isinstance(mc.engine, FakeSTT)
    assert mc.lang_plugin is None
    assert mc.process_audio(b"x", "en") == "transcribed:en"
    assert mc.detect_language(b"x") == ("en", 0.99)


@patch("ovos_stt_http_server.load_stt_plugin")
def test_model_container_load_failure(load_stt):
    load_stt.return_value = None
    with pytest.raises(ValueError, match="Failed to load STT"):
        srv.ModelContainer("missing")


@patch("ovos_stt_http_server.load_audio_transformer_plugin")
@patch("ovos_stt_http_server.load_stt_plugin")
def test_model_container_with_lang_plugin(load_stt, load_lang):
    load_stt.return_value = FakeSTT
    # Make our FakeLangDetector pass the subclass check
    with patch("ovos_stt_http_server.AudioLanguageDetector", FakeLangDetector):
        load_lang.return_value = FakeLangDetector
        mc = srv.ModelContainer("fake", lang_plugin="lp")
    assert isinstance(mc.lang_plugin, FakeLangDetector)
    assert mc.detect_language(b"x") == ("de", 0.77)


@patch("ovos_stt_http_server.load_audio_transformer_plugin")
@patch("ovos_stt_http_server.load_stt_plugin")
def test_model_container_lang_plugin_load_failure(load_stt, load_lang):
    load_stt.return_value = FakeSTT
    load_lang.return_value = None
    with pytest.raises(ValueError, match="Failed to load lang detection"):
        srv.ModelContainer("fake", lang_plugin="bad")


# ---------- MultiModelContainer ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_model_container_lazy_loads(load_stt):
    load_stt.return_value = FakeSTT
    mm = srv.MultiModelContainer("fake")
    assert mm.engines == {}
    out = mm.process_audio(b"x", "en")
    assert out == "transcribed:en"
    assert "en" in mm.engines
    # second call hits the cached engine
    out2 = mm.process_audio(b"x", "en")
    assert out2 == "transcribed:en"
    mm.unload_engine("en")
    assert "en" not in mm.engines
    mm.unload_engine("nope")  # no-op


@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_model_container_load_failure(load_stt):
    load_stt.return_value = None
    with pytest.raises(ValueError, match="Failed to load STT"):
        srv.MultiModelContainer("missing")


@patch("ovos_stt_http_server.load_audio_transformer_plugin")
@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_model_lang_detect(load_stt, load_lang):
    load_stt.return_value = FakeSTT
    with patch("ovos_stt_http_server.AudioLanguageDetector", FakeLangDetector):
        load_lang.return_value = FakeLangDetector
        mm = srv.MultiModelContainer("fake", lang_plugin="lp")
    assert mm.detect_language(b"x") == ("de", 0.77)
    # Trigger load_engine path that binds the lang plugin (line 85)
    mm.process_audio(b"x", "en")
    assert hasattr(mm.engines["en"], "bound")


@patch("ovos_stt_http_server.load_audio_transformer_plugin")
@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_model_lang_plugin_load_failure(load_stt, load_lang):
    load_stt.return_value = FakeSTT
    load_lang.return_value = None
    with pytest.raises(ValueError, match="Failed to load lang detection"):
        srv.MultiModelContainer("fake", lang_plugin="bad")


# ---------- create_app ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_status(load_stt):
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.get("/status")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "plugin": "fake-stt", "lang_plugin": None}


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_stt_endpoint(load_stt):
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.post("/stt?lang=en", content=b"\x00\x00" * 100)
    assert r.status_code == 200
    assert r.text == "transcribed:en"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_stt_lang_auto(load_stt):
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.post("/stt?lang=auto", content=b"\x00\x00" * 100)
    assert r.status_code == 200
    # FakeSTT.detect_language returns ("en", 0.99)
    assert r.text == "transcribed:en"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_lang_detect_single(load_stt):
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.post("/lang_detect?valid_langs=en", content=b"\x00\x00")
    assert r.status_code == 200
    assert r.json() == {"lang": "en", "conf": 1.0}


@patch("ovos_stt_http_server.load_audio_transformer_plugin")
@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_lang_detect_multi(load_stt, load_lang):
    load_stt.return_value = FakeSTT
    with patch("ovos_stt_http_server.AudioLanguageDetector", FakeLangDetector):
        load_lang.return_value = FakeLangDetector
        app, _model = srv.create_app("fake-stt", lang_plugin="lp")
    client = TestClient(app)
    r = client.post("/lang_detect?valid_langs=en,de", content=b"\x00\x00")
    assert r.status_code == 200
    assert r.json() == {"lang": "de", "conf": 0.77}


class NoDetectSTT(FakeSTT):
    """A plugin without language detection, e.g. ovos-stt-plugin-onnx-asr."""

    def detect_language(self, audio, valid_langs=None):
        raise NotImplementedError("OnnxASR does not support audio language detection")


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_lang_detect_plugin_without_detection(load_stt):
    """/lang_detect on a plugin without detection must say so, not 500.

    Regression: the unguarded call raised NotImplementedError (HTTP 500)
    for plugins like ovos-stt-plugin-onnx-asr that do not implement
    detect_language; the response now names the limitation with HTTP 501.
    """
    load_stt.return_value = NoDetectSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.post("/lang_detect", content=b"\x00\x00")
    assert r.status_code == 501
    detail = r.json()["detail"]
    assert "does not support" in detail or "detection" in detail
    detail.lower().index("detect")


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_lang_detect_no_valid_langs(load_stt):
    """/lang_detect without valid_langs must detect, not crash.

    Regression: ``request.query_params.get("valid_langs").split(",")`` raised
    AttributeError (HTTP 500) when the param was absent.
    """
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.post("/lang_detect", content=b"\x00\x00")
    assert r.status_code == 200
    assert r.json() == {"lang": "en", "conf": 0.99}


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_stt_with_sample_params(load_stt):
    """/stt must accept sample_rate/sample_width query params.

    Regression: query params arrive as strings and were passed straight to
    ``AudioData(... , sample_rate, sample_width)``, which asserts ints and
    raised TypeError (HTTP 500).
    """
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    client = TestClient(app)
    r = client.post("/stt?lang=en&sample_rate=8000&sample_width=2", content=b"\x00\x00" * 100)
    assert r.status_code == 200
    assert r.text == "transcribed:en"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_multi_mode(load_stt):
    load_stt.return_value = FakeSTT
    app, model = srv.create_app("fake-stt", multi=True)
    assert isinstance(model, srv.MultiModelContainer)
    client = TestClient(app)
    r = client.post("/stt?lang=en", content=b"\x00\x00" * 100)
    assert r.status_code == 200


@patch("ovos_stt_http_server.load_stt_plugin")
def test_start_stt_server_returns_app(load_stt):
    load_stt.return_value = FakeSTT
    app, model = srv.start_stt_server("fake-stt")
    assert app is not None
    assert model is not None


# ---------- Transformer pipelines ----------

class FakeUtteranceService:
    plugins = ["fake"]

    def transform(self, utterances, context=None):
        return [f"corrected:{u}" for u in utterances], {"touched": True}


class FakeAudioService:
    plugins = ["fake"]

    def transform(self, chunk, context=None):
        return chunk[::-1], {"stt_lang": "de"}


@patch("ovos_stt_http_server.load_stt_plugin")
def test_transformers_off_by_default(load_stt):
    """With no transformer config the transcript passes through untouched."""
    load_stt.return_value = FakeSTT
    mc = srv.ModelContainer("fake")
    assert mc.audio_transformers.plugins == []
    assert mc.utterance_transformers.plugins == []
    assert mc.process_audio(b"x", "en") == "transcribed:en"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_utterance_transformers_rewrite_transcript(load_stt):
    load_stt.return_value = FakeSTT
    mc = srv.ModelContainer("fake")
    mc.utterance_transformers = FakeUtteranceService()
    assert mc.process_audio(b"x", "en") == "corrected:transcribed:en"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_audio_transformers_run_before_stt_and_set_lang(load_stt):
    seen = {}

    class RecordingSTT(FakeSTT):
        def execute(self, audio, language=None):
            seen["audio"] = audio
            seen["language"] = language
            return "ok"

    load_stt.return_value = RecordingSTT
    mc = srv.ModelContainer("fake")
    mc.audio_transformers = FakeAudioService()
    audio = srv.AudioData(b"abc", 16000, 2)
    out = mc.process_audio(audio, "auto")
    assert out == "ok"
    # chain modified the audio and its stt_lang resolved the "auto" lang
    assert seen["audio"].frame_data == b"cba"
    assert seen["language"] == "de"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_explicit_lang_wins_over_detected(load_stt):
    seen = {}

    class RecordingSTT(FakeSTT):
        def execute(self, audio, language=None):
            seen["language"] = language
            return "ok"

    load_stt.return_value = RecordingSTT
    mc = srv.ModelContainer("fake")
    mc.audio_transformers = FakeAudioService()
    mc.process_audio(srv.AudioData(b"abc", 16000, 2), "pt")
    assert seen["language"] == "pt"


@patch("ovos_stt_http_server.load_stt_plugin")
def test_multi_model_container_shares_transformers(load_stt):
    load_stt.return_value = FakeSTT
    mm = srv.MultiModelContainer("fake")
    mm.utterance_transformers = FakeUtteranceService()
    assert mm.process_audio(b"x", "en") == "corrected:transcribed:en"
    assert mm.process_audio(b"x", "de") == "corrected:transcribed:de"


# ---------- MCP is opt-in via enable_mcp / --mcp ----------

@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_default_does_not_mount_mcp(load_stt):
    """Without enable_mcp, /mcp must never be mounted even if the extra is installed."""
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt")
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert not any(p == "/mcp" or p.startswith("/mcp/") for p in route_paths)


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_enable_mcp_mounts_route(load_stt):
    """enable_mcp=True must mount an /mcp route when the mcp extra is available."""
    pytest.importorskip("fastmcp")
    load_stt.return_value = FakeSTT
    app, _model = srv.create_app("fake-stt", enable_mcp=True)
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert any(p == "/mcp" or p.startswith("/mcp/") for p in route_paths)


@patch("ovos_stt_http_server.load_stt_plugin")
def test_create_app_enable_mcp_false_by_default_kwarg(load_stt):
    """create_app's enable_mcp keyword defaults to False."""
    import inspect
    sig = inspect.signature(srv.create_app)
    assert sig.parameters["enable_mcp"].default is False


@patch("ovos_stt_http_server.load_stt_plugin")
def test_start_stt_server_threads_enable_mcp(load_stt):
    """start_stt_server must forward enable_mcp through to create_app."""
    pytest.importorskip("fastmcp")
    load_stt.return_value = FakeSTT
    app, _model = srv.start_stt_server("fake-stt", enable_mcp=True)
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert any(p == "/mcp" or p.startswith("/mcp/") for p in route_paths)


@patch("ovos_stt_http_server.load_stt_plugin")
def test_start_stt_server_default_no_mcp(load_stt):
    load_stt.return_value = FakeSTT
    app, _model = srv.start_stt_server("fake-stt")
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert not any(p == "/mcp" or p.startswith("/mcp/") for p in route_paths)
