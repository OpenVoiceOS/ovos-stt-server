"""Audio that ends inside a sample answers 400; a plugin fault stays 500.

The stub plugin reads audio through `AudioData.get_np_float32`, which numpy
rejects for a body cut inside a sample.
"""
from typing import ClassVar
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import ovos_stt_http_server as srv

PCM = b"".join(i.to_bytes(2, "little", signed=True) for i in range(-800, 800))


class StubSTT:
    available_languages: ClassVar[set] = set()

    def __init__(self, config=None):
        self.config = config or {}
        self.lang = "en"

    def execute(self, audio, language=None):
        audio.get_np_float32(16000)
        if language == "crash":
            raise ValueError("the plugin failed on its own account")
        return f"transcribed:{language}"

    def bind(self, detector):
        pass


@pytest.fixture(params=[False, True], ids=["single", "multi"])
def client(request):
    with patch("ovos_stt_http_server.load_stt_plugin", return_value=StubSTT):
        app, _ = srv.create_app("stub", multi=request.param)
    return TestClient(app, raise_server_exceptions=False)


def test_odd_length_body_answers_400_not_500(client):
    resp = client.post("/stt?lang=en", content=b"12345", headers={"Content-Type": "audio/wav"})
    assert resp.status_code == 400
    assert resp.json() == {
        "error": "the audio is 5 bytes, which is not a whole number of 2-byte samples. "
                 "Send complete samples."}


def test_whole_samples_are_served(client):
    resp = client.post("/stt?lang=en", content=PCM)
    assert (resp.status_code, resp.text) == (200, "transcribed:en")


def test_plugin_value_error_still_answers_500(client):
    resp = client.post("/stt?lang=crash", content=PCM)
    assert resp.status_code == 500


def test_odd_length_is_whole_samples_for_8_bit_audio(client):
    resp = client.post("/stt?lang=en&sample_width=1", content=b"12345")
    assert (resp.status_code, resp.text) == (200, "transcribed:en")


def test_misaligned_24_bit_audio_answers_400(client):
    resp = client.post("/stt?lang=en&sample_width=3", content=b"12345678")
    assert resp.status_code == 400
    assert resp.json() == {
        "error": "the audio is 8 bytes, which is not a whole number of 3-byte samples. "
                 "Send complete samples."}


def test_aligned_24_bit_audio_is_served(client):
    resp = client.post("/stt?lang=en&sample_width=3", content=b"123456")
    assert (resp.status_code, resp.text) == (200, "transcribed:en")
