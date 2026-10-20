# Licensed under the Apache License, Version 2.0
"""Unit tests for the OpenAI Whisper-compatible router.

Uses FastAPI TestClient (no live server, no real openai API key).
A FakeModel returning "hello world" drives all assertions.
"""
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_bytes(text_length: int = 160) -> bytes:
    """Return minimal valid WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * text_length)
    return buf.getvalue()


class FakeModel:
    """Minimal model stub returning a fixed transcript."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        return "hello world"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient for the openai_whisper router mounted on a fresh app."""
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    app = FastAPI()
    app.include_router(make_openai_whisper_router(FakeModel()))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Transcriptions endpoint
# ---------------------------------------------------------------------------

class TestTranscriptions:
    """Tests for POST /openai/v1/audio/transcriptions."""

    def test_json_response_default(self, client):
        """Default response_format=json returns {text: ...}."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "hello world"

    def test_json_response_explicit(self, client):
        """Explicit response_format=json returns {text: ...}."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "json"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_text_response_format(self, client):
        """response_format=text returns plain text."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "text"},
        )
        assert resp.status_code == 200
        assert resp.text == "hello world"

    def test_verbose_json_response_format(self, client):
        """response_format=verbose_json includes duration, language, segments."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "verbose_json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "hello world"
        assert "duration" in body
        assert "language" in body
        assert isinstance(body["segments"], list)
        assert body["segments"][0]["text"] == "hello world"

    def test_srt_response_format(self, client):
        """response_format=srt returns SRT-formatted plain text."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "srt"},
        )
        assert resp.status_code == 200
        assert "hello world" in resp.text
        assert "-->" in resp.text

    def test_vtt_response_format(self, client):
        """response_format=vtt returns WebVTT-formatted plain text."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "vtt"},
        )
        assert resp.status_code == 200
        assert "WEBVTT" in resp.text
        assert "hello world" in resp.text

    def test_with_language_param(self, client):
        """language param is forwarded to the model."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "language": "pt"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_with_temperature_and_prompt(self, client):
        """temperature and prompt are accepted without error."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={
                "model": "whisper-1",
                "temperature": "0.2",
                "prompt": "some hint",
            },
        )
        assert resp.status_code == 200

    def test_empty_file_returns_400(self, client):
        """Empty file body returns HTTP 400."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", b"", "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 400

    def test_missing_model_field_returns_422(self, client):
        """Missing required model field returns HTTP 422."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={},
        )
        assert resp.status_code == 422

    def test_unknown_response_format_returns_422(self, client):
        """Unknown response_format returns HTTP 422."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "xml"},
        )
        assert resp.status_code == 422

    def test_raw_bytes_fallback(self, client):
        """Non-WAV bytes (raw PCM) are accepted via fallback path."""
        resp = client.post(
            "/openai/v1/audio/transcriptions",
            files={"file": ("audio.raw", b"\x00\x00" * 160, "application/octet-stream")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"


# ---------------------------------------------------------------------------
# Translations endpoint
# ---------------------------------------------------------------------------

class TestTranslations:
    """Tests for POST /openai/v1/audio/translations."""

    def test_json_response(self, client):
        """translations endpoint returns {text: ...} with json format."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    def test_text_response_format(self, client):
        """translations endpoint supports response_format=text."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "text"},
        )
        assert resp.status_code == 200
        assert resp.text == "hello world"

    def test_verbose_json_response_format(self, client):
        """translations endpoint supports verbose_json."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={"model": "whisper-1", "response_format": "verbose_json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "hello world"
        assert body["language"] == "en"

    def test_empty_file_returns_400(self, client):
        """translations endpoint rejects empty files."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", b"", "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 400

    def test_missing_model_returns_422(self, client):
        """Missing model field returns 422."""
        resp = client.post(
            "/openai/v1/audio/translations",
            files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
            data={},
        )
        assert resp.status_code == 422


class FakeTranslator:
    """Minimal OVOS LanguageTranslator stub for the translations endpoint."""

    def translate(self, text, target=None, source=None):
        return f"[{target}] {text}"


def _client_with_translator() -> TestClient:
    from fastapi import FastAPI
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router
    app = FastAPI()
    app.include_router(make_openai_whisper_router(FakeModel(), translator=FakeTranslator()))
    return TestClient(app)


def test_translations_runs_through_translator():
    """/audio/translations transcribes then translates the text to English."""
    import io
    c = _client_with_translator()
    resp = c.post(
        "/openai/v1/audio/translations",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"model": "whisper-1"},
    )
    assert resp.status_code == 200
    # FakeModel returns "hello world"; FakeTranslator prefixes the target lang
    assert resp.json()["text"] == "[en] hello world"


def test_translations_without_translator_returns_transcript():
    """Without a translator, /translations returns the untranslated transcript."""
    import io
    from fastapi import FastAPI
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router
    app = FastAPI()
    app.include_router(make_openai_whisper_router(FakeModel()))  # translator=None
    c = TestClient(app)
    resp = c.post(
        "/openai/v1/audio/translations",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"model": "whisper-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "hello world"


class LangCapturingModel:
    """Model stub that records the language the router handed it."""

    def __init__(self):
        self.lang = None

    def process_audio(self, audio, lang: str = "auto") -> str:
        self.lang = lang
        return "hello world"


def test_router_hands_auto_to_process_audio_for_detection(monkeypatch):
    """An omitted language must reach process_audio as "auto", not resolved.

    The router used to resolve "auto" to the server's configured language
    itself, before ModelContainer.process_audio could detect it. That undid
    process_audio's own fallback for every route that goes through this
    router: a request with no language must let process_audio decide, since
    only it knows about a bound language detector and the stt_lang context.
    """
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    model = LangCapturingModel()
    app = FastAPI()
    app.include_router(make_openai_whisper_router(model))
    resp = TestClient(app).post(
        "/openai/v1/audio/transcriptions",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"model": "whisper-1"},
    )

    assert resp.status_code == 200
    assert model.lang == "auto"


def test_router_forwards_explicit_language_unchanged():
    """An explicit language must reach process_audio unchanged."""
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    model = LangCapturingModel()
    app = FastAPI()
    app.include_router(make_openai_whisper_router(model))
    resp = TestClient(app).post(
        "/openai/v1/audio/transcriptions",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"model": "whisper-1", "language": "it"},
    )

    assert resp.status_code == 200
    assert model.lang == "it"


# ---------------------------------------------------------------------------
# Compressed uploads: the OpenAI, Groq and ElevenLabs Scribe SDKs send FLAC,
# MP3 or OGG as they are. The engine must get the decoded PCM, not the
# compressed bytes read as PCM.
# ---------------------------------------------------------------------------

class _FrameCounter:
    """Model stub that reports what the engine received."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        return f"{audio.sample_rate}Hz {len(audio.frame_data) // audio.sample_width} samples"


def _tone_wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    import math
    from array import array
    pcm = array("h", (int(8000 * math.sin(2 * math.pi * 440 * n / rate)) for n in range(int(seconds * rate))))
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _encode(fmt: str) -> bytes:
    """Encode the tone with ffmpeg through pydub, the [audio] extra's decoder."""
    from pydub import AudioSegment
    buf = io.BytesIO()
    AudioSegment.from_wav(io.BytesIO(_tone_wav())).export(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture(scope="module")
def counter_app() -> TestClient:
    from ovos_stt_http_server.routers.elevenlabs_scribe import make_elevenlabs_scribe_router
    from ovos_stt_http_server.routers.groq import make_groq_router
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router

    app = FastAPI()
    app.include_router(make_openai_whisper_router(_FrameCounter()))
    app.include_router(make_groq_router(_FrameCounter()))
    app.include_router(make_elevenlabs_scribe_router(_FrameCounter()))
    return TestClient(app)


_ROUTES = [
    ("/openai/v1/audio/transcriptions", {"model": "whisper-1"}),
    ("/groq/openai/v1/audio/transcriptions", {"model": "whisper-large-v3"}),
    ("/elevenlabs/v1/speech-to-text", {"model_id": "scribe_v1"}),
]


@pytest.mark.parametrize("path, form", _ROUTES)
@pytest.mark.parametrize("fmt", ["flac", "mp3", "ogg"])
def test_compressed_upload_reaches_the_engine_decoded(counter_app, path, form, fmt):
    resp = counter_app.post(path, files={"file": (f"speech.{fmt}", _encode(fmt), f"audio/{fmt}")}, data=form)
    assert resp.status_code == 200, resp.text
    rate, samples, _ = resp.json()["text"].split()
    assert rate == "16000Hz"
    # 0.5 s of audio decodes to about 8000 samples; MP3 framing adds a little padding
    assert 7500 <= int(samples) <= 9500


@pytest.mark.parametrize("path, form", _ROUTES)
def test_wav_named_upload_without_wav_header_is_rejected(counter_app, path, form):
    resp = counter_app.post(path, files={"file": ("speech.wav", b"this is not audio", "audio/wav")}, data=form)
    assert resp.status_code == 400


@pytest.mark.parametrize("path, form", _ROUTES)
def test_undecodable_compressed_upload_is_rejected(counter_app, path, form):
    resp = counter_app.post(path, files={"file": ("speech.mp3", b"ID3 then nothing", "audio/mpeg")}, data=form)
    assert resp.status_code == 400
