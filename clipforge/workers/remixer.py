"""Remix engine — assemble new videos from a clip library using templates."""

import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipforge.models.clip import Clip


@dataclass
class RemixTemplate:
    """A structural template for assembling clips."""
    name: str
    description: str
    # Each slot defines what kind of clip to pull
    # Slots are dicts with filter criteria: {"tag": "talking", "min_duration": 2.0, "max_duration": 5.0}
    slots: list[dict]


# --- Built-in templates ---

TEMPLATES = {
    "hook_montage": RemixTemplate(
        name="hook_montage",
        description="Strong talking hook → rapid b-roll/mixed cuts → talking CTA",
        slots=[
            {"tag": "talking", "min_duration": 2.0, "max_duration": 5.0, "role": "hook"},
            {"min_duration": 1.0, "max_duration": 4.0, "role": "body"},
            {"min_duration": 1.0, "max_duration": 4.0, "role": "body"},
            {"min_duration": 1.0, "max_duration": 4.0, "role": "body"},
            {"tag": "talking", "min_duration": 1.5, "max_duration": 5.0, "role": "cta"},
        ],
    ),
    "reordered_narrative": RemixTemplate(
        name="reordered_narrative",
        description="Talking clips from different videos assembled into a new narrative",
        slots=[
            {"tag": "talking", "min_duration": 2.0, "max_duration": 6.0, "role": "hook"},
            {"tag": "talking", "min_duration": 2.0, "max_duration": 8.0, "role": "body"},
            {"tag": "talking", "min_duration": 2.0, "max_duration": 8.0, "role": "body"},
            {"tag": "talking", "min_duration": 1.5, "max_duration": 5.0, "role": "cta"},
        ],
    ),
    "highlight_reel": RemixTemplate(
        name="highlight_reel",
        description="Fast cuts of the highest-energy moments",
        slots=[
            {"min_duration": 1.0, "max_duration": 3.0, "prefer": "high-energy", "role": "body"},
            {"min_duration": 1.0, "max_duration": 3.0, "prefer": "high-energy", "role": "body"},
            {"min_duration": 1.0, "max_duration": 3.0, "prefer": "high-energy", "role": "body"},
            {"min_duration": 1.0, "max_duration": 3.0, "prefer": "high-energy", "role": "body"},
            {"min_duration": 1.0, "max_duration": 3.0, "prefer": "high-energy", "role": "body"},
            {"min_duration": 1.0, "max_duration": 3.0, "prefer": "high-energy", "role": "body"},
        ],
    ),
    "hook_swap": RemixTemplate(
        name="hook_swap",
        description="Different hook clip + same body content — for testing which hooks grab attention",
        slots=[
            {"tag": "talking", "min_duration": 2.0, "max_duration": 5.0, "role": "hook"},
            {"min_duration": 3.0, "max_duration": 15.0, "role": "body"},
        ],
    ),
}


def load_clip_library(library_path: Path) -> list[Clip]:
    """Load clips from a clip_library.json file."""
    data = json.loads(library_path.read_text())
    clips = []
    for d in data:
        clip = Clip(
            source_video=d["source_video"],
            index=d["index"],
            start_time=d["start_time"],
            end_time=d["end_time"],
            clip_path=Path(d["clip_path"]) if d.get("clip_path") else None,
            vocals_path=Path(d["vocals_path"]) if d.get("vocals_path") else None,
            music_path=Path(d["music_path"]) if d.get("music_path") else None,
            transcript=d.get("transcript", ""),
            has_speech=d.get("has_speech", False),
            energy=d.get("energy", 0.0),
            beats=d.get("beats", []),
            tags=d.get("tags", []),
        )
        clips.append(clip)
    return clips


def filter_clips(clips: list[Clip], slot: dict) -> list[Clip]:
    """Filter clips that match a slot's criteria."""
    matches = list(clips)

    # Filter by tag (required)
    if "tag" in slot:
        matches = [c for c in matches if slot["tag"] in c.tags]

    # Filter by duration
    min_dur = slot.get("min_duration", 0)
    max_dur = slot.get("max_duration", float("inf"))
    matches = [c for c in matches if min_dur <= c.duration <= max_dur]

    # Filter out clips with no video file
    matches = [c for c in matches if c.clip_path and Path(c.clip_path).exists()]

    # Sort by preference if specified
    if "prefer" in slot:
        preferred = [c for c in matches if slot["prefer"] in c.tags]
        others = [c for c in matches if slot["prefer"] not in c.tags]
        matches = preferred + others

    return matches


def select_clips_for_template(
    clips: list[Clip],
    template: RemixTemplate,
    avoid_same_source: bool = True,
) -> list[Clip] | None:
    """Select clips to fill each slot in a template.

    Returns None if the template can't be filled.
    """
    selected = []
    used_sources = set()
    used_ids = set()

    for slot in template.slots:
        candidates = filter_clips(clips, slot)

        # Avoid reusing the same clip
        candidates = [c for c in candidates if c.id not in used_ids]

        # Prefer clips from different source videos for variety
        if avoid_same_source:
            diverse = [c for c in candidates if c.source_video not in used_sources]
            if diverse:
                candidates = diverse

        if not candidates:
            return None

        chosen = random.choice(candidates[:10])  # pick from top 10 matches
        selected.append(chosen)
        used_ids.add(chosen.id)
        used_sources.add(chosen.source_video)

    return selected


def snap_duration_to_beat(clip: Clip, target_duration: float | None = None) -> float:
    """Find the beat timestamp closest to the end of the clip for a clean cut."""
    if not clip.beats:
        return clip.duration

    if target_duration is None:
        target_duration = clip.duration

    # Find the last beat before or at the target duration
    valid_beats = [b for b in clip.beats if b <= target_duration and b > 0.5]
    if valid_beats:
        return valid_beats[-1]
    return clip.duration


def render_remix(
    selected_clips: list[Clip],
    output_path: Path,
    beat_sync: bool = True,
    target_width: int = 720,
    target_height: int = 1280,
) -> Path:
    """Concatenate selected clips into a single remix video using FFmpeg."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a concat file for FFmpeg
    concat_file = output_path.parent / f"{output_path.stem}_concat.txt"
    trimmed_clips = []

    for i, clip in enumerate(selected_clips):
        clip_path = Path(clip.clip_path).resolve()
        if beat_sync:
            duration = snap_duration_to_beat(clip)
        else:
            duration = clip.duration

        # Trim clip to beat-snapped duration and normalize resolution
        trimmed_path = (output_path.parent / f"_trim_{i}.mp4").resolve()
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(clip_path),
                "-t", str(duration),
                "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                       f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264",
                "-c:a", "aac",
                "-ar", "44100",
                "-loglevel", "error",
                str(trimmed_path),
            ],
            check=True,
        )
        trimmed_clips.append(trimmed_path)

    # Write concat list
    with open(concat_file, "w") as f:
        for tc in trimmed_clips:
            f.write(f"file '{tc}'\n")

    # Concatenate
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-movflags", "+faststart",
            "-loglevel", "error",
            str(output_path),
        ],
        check=True,
    )

    # Cleanup temp files
    concat_file.unlink(missing_ok=True)
    for tc in trimmed_clips:
        tc.unlink(missing_ok=True)

    return output_path


def generate_remixes(
    library_path: Path,
    output_dir: Path,
    template_name: str | None = None,
    count: int = 5,
    beat_sync: bool = True,
) -> list[Path]:
    """Generate remix variations from a clip library.

    Args:
        library_path: Path to clip_library.json
        output_dir: Where to save rendered remixes
        template_name: Specific template to use, or None for random
        count: Number of remixes to generate
        beat_sync: Whether to snap cuts to beat boundaries
    """
    clips = load_clip_library(library_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    templates_to_use = (
        [TEMPLATES[template_name]] if template_name and template_name in TEMPLATES
        else list(TEMPLATES.values())
    )

    for i in range(count):
        template = random.choice(templates_to_use)
        selected = select_clips_for_template(clips, template)

        if selected is None:
            continue

        output_path = output_dir / f"remix_{i:03d}_{template.name}.mp4"
        render_remix(selected, output_path, beat_sync=beat_sync)

        # Save metadata for this remix
        meta = {
            "template": template.name,
            "clips": [
                {
                    "id": c.id,
                    "source": c.source_video,
                    "transcript": c.transcript,
                    "duration": c.duration,
                    "role": slot.get("role", "unknown"),
                }
                for c, slot in zip(selected, template.slots)
            ],
        }
        meta_path = output_path.with_suffix(".json")
        meta_path.write_text(json.dumps(meta, indent=2))

        outputs.append(output_path)

    return outputs
