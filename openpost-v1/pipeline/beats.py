"""
beats.py — librosa beat detection on the audio track of a video.
"""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile  # noqa: F401 – ensure soundfile backend is available


def detect_beats(video_path: str) -> list[float]:
    """
    Load audio from *video_path* and return a list of beat timestamps in seconds.

    Returns an empty list if no beats are detectable (speech-only content).
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    try:
        y, sr = librosa.load(str(path), sr=None, mono=True)
    except Exception as exc:
        # Audio could not be decoded (no audio track, corrupt file, etc.)
        print(f"[warn] Beat detection could not load audio for {path.name}: {exc}")
        return []

    if len(y) == 0:
        return []

    try:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    except Exception as exc:
        print(f"[warn] Beat tracking failed for {path.name}: {exc}")
        return []

    if beat_frames is None or len(beat_frames) == 0:
        return []

    beat_times: list[float] = librosa.frames_to_time(
        beat_frames, sr=sr
    ).tolist()

    # Sanity check: discard if tempo is unrealistically low (< 50 BPM) or there
    # are very few beats — likely a speech-only track with no real rhythm.
    scalar_tempo = float(np.atleast_1d(tempo)[0])
    if scalar_tempo < 50 or len(beat_times) < 4:
        return []

    return [round(t, 3) for t in beat_times]
