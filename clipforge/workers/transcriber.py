"""Transcribe speech from clips using openai-whisper (Python)."""

import subprocess
from pathlib import Path

import whisper

from clipforge.models.clip import Clip

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = whisper.load_model("turbo")
    return _model


def transcribe_clip(clip: Clip, model_path: Path = None) -> Clip:
    """Transcribe speech in a clip using openai-whisper."""
    audio_path = clip.vocals_path or clip.clip_path
    if audio_path is None:
        return clip

    # whisper needs 16kHz mono WAV
    wav_16k = Path(str(audio_path).replace(".wav", "_16k.wav"))
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-ar", "16000",
            "-ac", "1",
            "-loglevel", "error",
            str(wav_16k),
        ],
        check=True,
    )

    model = _get_model()
    result = model.transcribe(str(wav_16k), fp16=False)
    text = result.get("text", "").strip()
    clip.transcript = text
    clip.has_speech = len(text) > 0

    wav_16k.unlink(missing_ok=True)
    return clip
