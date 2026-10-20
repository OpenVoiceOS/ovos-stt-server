# Licensed under the Apache License, Version 2.0
"""Audio conversion utilities for STT server."""
import io
import wave
from array import array

from fastapi import HTTPException
from ovos_plugin_manager.utils.audio import AudioData


def multipart_audio_to_audiodata(file_bytes: bytes, filename: str) -> AudioData:
    """Convert uploaded audio file bytes to AudioData.

    Handles WAV directly via stdlib. Falls back to pydub for other formats.

    Args:
        file_bytes: Raw bytes from uploaded file.
        filename: Original filename (used to detect format).

    Returns:
        AudioData instance suitable for STT engine.

    Raises:
        HTTPException: 501 if non-WAV format is uploaded and pydub is not installed.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"

    if ext == "wav":
        with wave.open(io.BytesIO(file_bytes)) as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            audio_bytes = wf.readframes(wf.getnframes())
        return AudioData(audio_bytes, sample_rate, sample_width)

    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(file_bytes), format=ext)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        audio.export(buf, format="wav")
        buf.seek(0)
        with wave.open(buf) as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            audio_bytes = wf.readframes(wf.getnframes())
        return AudioData(audio_bytes, sample_rate, sample_width)
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail=f"Format '{ext}' requires pydub. Install with: pip install pydub",
        )


# the highest rate audio hardware records at; higher values overflow the resampler
MAX_SAMPLE_RATE = 384000
_WAVE_FORMAT_PCM = (1).to_bytes(2, "little")
_WAVE_FORMAT_EXTENSIBLE = (0xFFFE).to_bytes(2, "little")
_KSDATAFORMAT_SUBTYPE_PCM = bytes.fromhex("0100000000001000800000aa00389b71")


def _as_plain_pcm_wav(data: bytes) -> bytes:
    """Give a WAVE_FORMAT_EXTENSIBLE file with a PCM subformat the plain PCM tag.

    ffmpeg and sox write the extensible tag for 24-bit, 32-bit and
    multi-channel PCM, and ``wave`` before Python 3.12 rejects it.
    """
    pos = 12
    while pos + 8 <= len(data):
        chunk_id, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        if chunk_id == b"fmt ":
            tag = data[pos + 8:pos + 10]
            subformat = data[pos + 32:pos + 48]
            if tag == _WAVE_FORMAT_EXTENSIBLE and subformat == _KSDATAFORMAT_SUBTYPE_PCM:
                return data[:pos + 8] + _WAVE_FORMAT_PCM + data[pos + 10:]
            return data
        pos += 8 + size + (size & 1)
    return data


def to_audio_data(data: bytes, sample_rate: int, sample_width: int) -> AudioData:
    """Decode a WAV file to 16-bit mono PCM; read other bytes as raw PCM.

    The channels of a multi-channel WAV are averaged, so equal loud channels
    do not clip as a plain sum would.
    """
    if data[:4] != b"RIFF":
        return AudioData(data, sample_rate, sample_width)

    try:
        with wave.open(io.BytesIO(_as_plain_pcm_wav(data))) as wf:
            channels, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except RuntimeError as e:
        # wave raises a bare RuntimeError for a chunk size past the end of the file
        raise wave.Error(f"WAV chunk runs past the end of the file: {e}") from e
    if not 1 <= width <= 4:
        raise wave.Error(f"unsupported sample width: {width} bytes")
    if not 0 < rate <= MAX_SAMPLE_RATE:
        raise wave.Error(f"unsupported sample rate: {rate} Hz")
    # a file cut inside a sample ends in a partial frame
    frames = frames[:len(frames) - len(frames) % (width * channels)]
    # AudioData reads 8-bit samples as unsigned, as WAV stores them. Width
    # conversion works sample by sample, so it is safe on interleaved frames.
    pcm = array("h", AudioData(frames, rate, width).get_raw_data(convert_width=2))
    if channels > 1:
        pcm = array("h", (sum(frame) // channels
                          for frame in zip(*(pcm[c::channels] for c in range(channels)))))
    return AudioData(pcm.tobytes(), rate, 2)
