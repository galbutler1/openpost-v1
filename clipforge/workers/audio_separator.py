"""Separate audio into vocals and music using Demucs."""

import subprocess
from pathlib import Path

from clipforge.models.clip import Clip


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Extract audio track from a video file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            "-loglevel", "error",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def separate_audio(audio_path: Path, output_dir: Path, model: str = "htdemucs") -> dict[str, Path]:
    """Run Demucs to separate audio into stems (vocals, drums, bass, other).

    Returns dict mapping stem name to file path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "python3", "-m", "demucs",
            "--out", str(output_dir),
            "-n", model,
            "--two-stems", "vocals",  # just split vocals vs accompaniment for speed
            str(audio_path),
        ],
        check=True,
    )

    # Demucs outputs to: output_dir/<model>/<audio_stem>/vocals.wav, no_vocals.wav
    stem_name = audio_path.stem
    stems_dir = output_dir / model / stem_name

    stems = {}
    for stem_file in stems_dir.glob("*.wav"):
        stems[stem_file.stem] = stem_file

    return stems


def process_clip_audio(clip: Clip, work_dir: Path) -> Clip:
    """Extract and separate audio for a single clip."""
    if clip.clip_path is None:
        return clip

    audio_dir = work_dir / "audio"
    audio_path = audio_dir / f"{clip.id}.wav"

    # Extract audio from clip
    extract_audio(clip.clip_path, audio_path)

    # Separate into vocals + music
    stems = separate_audio(audio_path, work_dir / "stems")
    clip.vocals_path = stems.get("vocals")
    clip.music_path = stems.get("no_vocals")

    return clip
