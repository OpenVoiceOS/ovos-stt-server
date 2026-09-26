"""Tests for audio_utils.multipart_audio_to_audiodata."""
import io
import wave

import pytest
from fastapi import HTTPException

from ovos_stt_http_server.audio_utils import multipart_audio_to_audiodata


def _make_wav(sample_rate=16000, sample_width=2, frames=b"\x00\x00" * 1600) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
    return buf.getvalue()


def test_wav_passthrough():
    raw = _make_wav()
    audio = multipart_audio_to_audiodata(raw, "clip.wav")
    assert audio.sample_rate == 16000
    assert audio.sample_width == 2
    assert len(audio.frame_data) == 1600 * 2


def test_wav_uppercase_extension():
    raw = _make_wav()
    audio = multipart_audio_to_audiodata(raw, "CLIP.WAV")
    assert audio.sample_rate == 16000


def test_no_extension_defaults_to_wav():
    raw = _make_wav()
    audio = multipart_audio_to_audiodata(raw, "noext")
    assert audio.sample_rate == 16000


def test_non_wav_without_pydub_raises_501(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pydub":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(HTTPException) as exc:
        multipart_audio_to_audiodata(b"x", "clip.mp3")
    assert exc.value.status_code == 501
    assert "pydub" in exc.value.detail.lower()


def test_non_wav_with_pydub(monkeypatch):
    """Force the pydub branch by passing a wav body with a non-wav extension."""
    import pydub
    raw_wav = _make_wav()
    # pydub.AudioSegment.from_file accepts WAV with format="raw" only if PCM-formatted.
    # Use format="wav" — but feed via extension different from "wav" to trigger pydub branch.
    # We monkey-patch pydub to read our buf regardless of declared format.
    import pydub
    original = pydub.AudioSegment.from_file

    def lenient_from_file(buf, format=None):
        return original(buf, format="wav")

    monkeypatch.setattr(pydub.AudioSegment, "from_file", staticmethod(lenient_from_file))
    audio = multipart_audio_to_audiodata(raw_wav, "clip.mp3")
    assert audio.sample_rate == 16000
