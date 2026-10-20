# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""POST /stt/json: base64 audio in a JSON body, for tool-calling clients."""
import base64
import io
import wave
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

PCM = b"".join(i.to_bytes(2, "little", signed=True) for i in range(-800, 800))


@pytest.fixture
def model():
    stub = MagicMock()
    stub.transcribe.return_value = ("hello", "en-us")
    return stub


@pytest.fixture
def client(model):
    with patch("ovos_stt_http_server.ModelContainer", return_value=model):
        from ovos_stt_http_server import create_app
        app, _ = create_app("stub-stt")
    return TestClient(app)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_transcribes_raw_pcm(client, model):
    resp = client.post("/stt/json", json={"audio_b64": _b64(PCM), "lang": "en-us", "sample_rate": 8000})
    assert resp.status_code == 200
    assert resp.json() == {"text": "hello", "lang": "en-us"}
    audio, lang = model.transcribe.call_args.args
    assert (audio.frame_data, audio.sample_rate, audio.sample_width, lang) == (PCM, 8000, 2, "en-us")


def test_decodes_a_wav_file(client, model):
    stereo = b"".join(PCM[i:i + 2] * 2 for i in range(0, len(PCM), 2))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(stereo)
    resp = client.post("/stt/json", json={"audio_b64": _b64(buf.getvalue()), "lang": "en-us"})
    assert resp.status_code == 200
    audio, _ = model.transcribe.call_args.args
    assert (audio.frame_data, audio.sample_rate, audio.sample_width) == (PCM, 44100, 2)


@pytest.mark.parametrize("bad", ["!!!not-base64!!!", "aGVsbG8", ""])
def test_rejects_audio_that_does_not_decode(client, model, bad):
    resp = client.post("/stt/json", json={"audio_b64": bad, "lang": "en-us"})
    assert resp.status_code == 400
    assert "audio_b64" in resp.json()["detail"]
    model.transcribe.assert_not_called()


def test_rejects_a_broken_wav(client, model):
    resp = client.post("/stt/json", json={"audio_b64": _b64(b"RIFF\x00\x00\x00\x00WAVEfmt "), "lang": "en-us"})
    assert resp.status_code == 400
    model.transcribe.assert_not_called()


def test_raw_stt_endpoint_is_unchanged(client, model):
    model.process_audio.return_value = "raw"
    resp = client.post("/stt?lang=en-us", content=PCM)
    assert (resp.status_code, resp.text) == (200, "raw")


def _wav16(frames: bytes, rate: int = 16000, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


def test_mime_wrapped_base64_is_rejected(client, model):
    # base64 with line breaks decodes in lenient mode; the strict decode refuses it
    resp = client.post("/stt/json", json={"audio_b64": base64.encodebytes(PCM).decode(), "lang": "en-us"})
    assert resp.status_code == 400
    model.transcribe.assert_not_called()


def test_a_header_cut_short_is_rejected(client, model):
    resp = client.post("/stt/json", json={"audio_b64": _b64(_wav16(PCM)[:20]), "lang": "en-us"})
    assert resp.status_code == 400
    assert "WAV" in resp.json()["detail"]
    model.transcribe.assert_not_called()


def test_a_wav_cut_inside_a_sample_drops_the_partial_frame(client, model):
    resp = client.post("/stt/json", json={"audio_b64": _b64(_wav16(PCM)[:-1]), "lang": "en-us"})
    assert resp.status_code == 200
    audio, _ = model.transcribe.call_args.args
    assert audio.frame_data == PCM[:-2]


def test_a_wav_with_an_unsupported_width_is_rejected(client, model):
    wav = bytearray(_wav16(b"\x00" * 50))
    wav[32:36] = (5).to_bytes(2, "little") + (40).to_bytes(2, "little")  # 5-byte samples
    resp = client.post("/stt/json", json={"audio_b64": _b64(bytes(wav)), "lang": "en-us"})
    assert resp.status_code == 400
    assert "sample width" in resp.json()["detail"]
    model.transcribe.assert_not_called()


def test_a_chunk_size_past_the_end_is_rejected(client, model):
    wav = bytearray(_wav16(PCM))
    wav[16:20] = (0xFFFF).to_bytes(4, "little")  # fmt chunk size beyond the file
    resp = client.post("/stt/json", json={"audio_b64": _b64(bytes(wav)), "lang": "en-us"})
    assert resp.status_code == 400
    model.transcribe.assert_not_called()


def test_raw_32bit_pcm_is_accepted(client, model):
    resp = client.post("/stt/json", json={"audio_b64": _b64(PCM), "lang": "en-us", "sample_width": 4})
    assert resp.status_code == 200
    audio, _ = model.transcribe.call_args.args
    assert audio.sample_width == 4


@pytest.mark.parametrize("field,value", [("sample_rate", 0), ("sample_rate", -16000),
                                         ("sample_width", 0), ("sample_width", 5)])
def test_rejects_an_impossible_raw_format(client, model, field, value):
    resp = client.post("/stt/json", json={"audio_b64": _b64(PCM), "lang": "en-us", field: value})
    assert resp.status_code == 422
    model.transcribe.assert_not_called()


def test_an_omitted_lang_uses_the_configured_one(model):
    with patch("ovos_stt_http_server.ModelContainer", return_value=model), \
            patch("ovos_stt_http_server.Configuration", return_value={"lang": "pt-PT"}):
        from ovos_stt_http_server import create_app
        app, _ = create_app("stub-stt")
        TestClient(app).post("/stt/json", json={"audio_b64": _b64(PCM)})
    assert model.transcribe.call_args.args[1] == "pt-pt"


def test_lang_is_lowercased(client, model):
    client.post("/stt/json", json={"audio_b64": _b64(PCM), "lang": "EN-US"})
    assert model.transcribe.call_args.args[1] == "en-us"


def test_the_response_reports_the_resolved_language(client, model):
    model.transcribe.return_value = ("bonjour", "fr-fr")
    resp = client.post("/stt/json", json={"audio_b64": _b64(PCM), "lang": "auto"})
    assert resp.json() == {"text": "bonjour", "lang": "fr-fr"}


@pytest.mark.parametrize("rate", [0, 2 ** 31])
def test_a_wav_with_an_impossible_rate_is_rejected(client, model, rate):
    wav = bytearray(_wav16(PCM))
    wav[24:28] = rate.to_bytes(4, "little")  # frame rate in the fmt chunk
    resp = client.post("/stt/json", json={"audio_b64": _b64(bytes(wav)), "lang": "en-us"})
    assert resp.status_code == 400
    assert "sample rate" in resp.json()["detail"]
    model.transcribe.assert_not_called()


def test_a_32bit_wav_becomes_16bit(client, model):
    frames = b"".join(v.to_bytes(4, "little", signed=True) for v in (1000 * 65536, -1000 * 65536))
    resp = client.post("/stt/json", json={"audio_b64": _b64(_wav16(frames, width=4)), "lang": "en-us"})
    assert resp.status_code == 200
    audio, _ = model.transcribe.call_args.args
    assert (audio.frame_data, audio.sample_width) == (b"".join(
        v.to_bytes(2, "little", signed=True) for v in (1000, -1000)), 2)


@pytest.mark.parametrize("rate,status", [(384000, 200), (384001, 422), (2 ** 31, 422)])
def test_raw_sample_rate_has_an_upper_bound(client, model, rate, status):
    resp = client.post("/stt/json", json={"audio_b64": _b64(PCM), "lang": "en-us", "sample_rate": rate})
    assert resp.status_code == status
