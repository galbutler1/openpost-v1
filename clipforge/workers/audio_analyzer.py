"""Analyze audio for beats and energy using librosa."""

from pathlib import Path

import librosa
import numpy as np

from clipforge.models.clip import Clip


def analyze_clip_audio(clip: Clip) -> Clip:
    """Detect beats and compute energy for a clip."""
    # Prefer the music track for beat detection, fall back to full audio
    audio_path = clip.music_path or clip.clip_path
    if audio_path is None:
        return clip

    y, sr = librosa.load(str(audio_path), sr=22050)

    # Beat detection
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    clip.beats = [round(float(t), 3) for t in beat_times]

    # Energy (RMS normalized to 0-1)
    rms = librosa.feature.rms(y=y)[0]
    clip.energy = round(float(np.mean(rms) / (np.max(rms) + 1e-6)), 3)

    # Auto-tag based on energy
    if clip.energy > 0.6:
        clip.tags.append("high-energy")
    elif clip.energy < 0.2:
        clip.tags.append("low-energy")

    if clip.has_speech:
        clip.tags.append("talking")
    else:
        clip.tags.append("b-roll")

    return clip
