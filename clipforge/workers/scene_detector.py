"""Split videos into individual clips using scene detection."""

import subprocess
from pathlib import Path

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector

from clipforge.models.clip import Clip


def detect_scenes(video_path: str | Path, threshold: float = 27.0) -> list[tuple[float, float]]:
    """Detect scene boundaries in a video. Returns list of (start, end) in seconds."""
    video_path = Path(video_path)
    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    scenes = []
    for start, end in scene_list:
        scenes.append((start.get_seconds(), end.get_seconds()))

    return scenes


def split_video(video_path: str | Path, scenes: list[tuple[float, float]], output_dir: Path) -> list[Path]:
    """Split a video into clips based on scene boundaries using FFmpeg."""
    video_path = Path(video_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_paths = []

    for i, (start, end) in enumerate(scenes):
        output_path = output_dir / f"{video_path.stem}_clip{i:03d}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(video_path),
                "-t", str(end - start),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-avoid_negative_ts", "1",
                "-loglevel", "error",
                output_path,
            ],
            check=True,
        )
        clip_paths.append(output_path)

    return clip_paths


def process_video(video_path: str | Path, output_dir: Path, min_clip_duration: float = 1.0) -> list[Clip]:
    """Full scene detection pipeline: detect scenes, split video, return Clip objects."""
    video_path = Path(video_path)
    scenes = detect_scenes(video_path)

    # Filter out very short clips
    scenes = [(s, e) for s, e in scenes if (e - s) >= min_clip_duration]

    if not scenes:
        # If no scenes detected, treat the whole video as one clip
        import subprocess as sp
        result = sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True,
        )
        duration = float(result.stdout.strip())
        scenes = [(0.0, duration)]

    clip_dir = output_dir / "clips"
    clip_paths = split_video(video_path, scenes, clip_dir)

    clips = []
    for i, ((start, end), path) in enumerate(zip(scenes, clip_paths)):
        clips.append(Clip(
            source_video=str(video_path),
            index=i,
            start_time=start,
            end_time=end,
            clip_path=path,
        ))

    return clips
