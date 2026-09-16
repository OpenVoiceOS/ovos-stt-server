# Licensed under the Apache License, Version 2.0
"""Audio conversion utilities for STT server."""
import io
import wave

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
