"""Audio-first remix engine.

Strategy:
1. Stitch vocal segments into a coherent voiceover narrative
2. Lay video clips on top as b-roll (muted, visual only)
3. Mix consistent music underneath
4. Burn in clean captions from transcripts
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from clipforge.models.clip import Clip


@dataclass
class NarrativeSegment:
    """A segment of the voiceover narrative."""
    clip: Clip
    text: str
    vocal_path: Path
    duration: float


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


def get_audio_duration(audio_path: Path) -> float:
    """Get duration of an audio file."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def build_narrative(clips: list[Clip], segment_ids: list[str]) -> list[NarrativeSegment]:
    """Build an ordered narrative from specific clip IDs."""
    clip_map = {c.id: c for c in clips}
    segments = []

    for clip_id in segment_ids:
        clip = clip_map.get(clip_id)
        if not clip or not clip.vocals_path or not clip.transcript:
            continue

        vocal_path = Path(clip.vocals_path).resolve()
        if not vocal_path.exists():
            continue

        duration = get_audio_duration(vocal_path)
        segments.append(NarrativeSegment(
            clip=clip,
            text=clip.transcript,
            vocal_path=vocal_path,
            duration=duration,
        ))

    return segments


def stitch_voiceover(segments: list[NarrativeSegment], output_path: Path, gap: float = 0.15) -> float:
    """Stitch vocal segments into one continuous voiceover with small gaps.

    Returns total duration.
    """
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build FFmpeg filter for concatenating with gaps
    inputs = []
    filter_parts = []

    for i, seg in enumerate(segments):
        inputs += ["-i", str(seg.vocal_path)]

    # Normalize each segment's audio level and add a small silence gap between them
    filter_chain = ""
    concat_inputs = ""

    for i in range(len(segments)):
        # Normalize audio level for each segment
        filter_chain += f"[{i}:a]loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];\n"
        # Add a silence pad at the end of each segment for the gap
        filter_chain += f"[a{i}]apad=pad_dur={gap}[ap{i}];\n"
        concat_inputs += f"[ap{i}]"

    # Concatenate all segments
    filter_chain += f"{concat_inputs}concat=n={len(segments)}:v=0:a=1[voiceover]"

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_chain,
        "-map", "[voiceover]",
        "-c:a", "aac",
        "-b:a", "192k",
        "-loglevel", "error",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)

    return get_audio_duration(output_path)


def select_broll_clips(clips: list[Clip], narrative_ids: set[str], total_duration: float) -> list[Clip]:
    """Select b-roll clips to fill the video duration.

    Prefers clips from different sources than the narrative where possible.
    """
    # All clips with video files, prefer ones NOT used in the narrative for visual variety
    available = [c for c in clips if c.clip_path and Path(c.clip_path).resolve().exists()]

    # Sort by energy (higher energy = more visually interesting)
    available.sort(key=lambda c: c.energy, reverse=True)

    selected = []
    accumulated = 0.0

    for clip in available:
        if accumulated >= total_duration:
            break
        selected.append(clip)
        accumulated += clip.duration

    return selected


def render_broll_track(broll_clips: list[Clip], target_duration: float, output_path: Path,
                       width: int = 720, height: int = 1280) -> Path:
    """Render b-roll clips into a single muted video track matching the target duration."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Trim and normalize each clip, then concatenate
    trimmed = []
    accumulated = 0.0

    for i, clip in enumerate(broll_clips):
        remaining = target_duration - accumulated
        if remaining <= 0:
            break

        clip_path = Path(clip.clip_path).resolve()
        clip_dur = min(clip.duration, remaining)
        trimmed_path = (output_path.parent / f"_broll_{i}.mp4").resolve()

        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-t", str(clip_dur),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-an",  # no audio — this is visual only
            "-c:v", "libx264",
            "-r", "30",
            "-loglevel", "error",
            str(trimmed_path),
        ], check=True)
        trimmed.append(trimmed_path)
        accumulated += clip_dur

    # Concatenate all b-roll
    concat_file = (output_path.parent / "_broll_concat.txt").resolve()
    with open(concat_file, "w") as f:
        for t in trimmed:
            f.write(f"file '{t}'\n")

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-movflags", "+faststart",
        "-loglevel", "error",
        str(output_path),
    ], check=True)

    # Cleanup
    concat_file.unlink(missing_ok=True)
    for t in trimmed:
        t.unlink(missing_ok=True)

    return output_path


def pick_music_track(clips: list[Clip]) -> Path | None:
    """Pick the best music track from separated audio.

    Chooses the longest one with the most beats (most musical).
    """
    candidates = []
    for clip in clips:
        if clip.music_path and Path(clip.music_path).exists() and len(clip.beats) > 3:
            candidates.append(clip)

    if not candidates:
        return None

    # Pick the one with the most beats (most musical content)
    candidates.sort(key=lambda c: len(c.beats), reverse=True)
    return Path(candidates[0].music_path).resolve()


def generate_captions_ass(segments: list[NarrativeSegment], output_path: Path, gap: float = 0.15):
    """Generate an ASS subtitle file with word-level-ish timing.

    Uses segment boundaries to time each transcript block.
    """
    output_path = output_path.resolve()

    ass_header = """[Script Info]
Title: ClipForge Captions
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial Black,42,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,30,30,120,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

    events = []
    current_time = 0.0

    for seg in segments:
        start = current_time
        end = current_time + seg.duration

        # Format timestamps as H:MM:SS.CC
        def fmt(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            return f"{h}:{m:02d}:{s:05.2f}"

        # Split transcript into chunks of ~5 words for readable captions
        words = seg.text.split()
        chunk_size = 5
        chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

        if chunks:
            chunk_dur = seg.duration / len(chunks)
            for j, chunk in enumerate(chunks):
                cs = start + j * chunk_dur
                ce = start + (j + 1) * chunk_dur
                # Escape special ASS characters
                clean = chunk.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                events.append(f"Dialogue: 0,{fmt(cs)},{fmt(ce)},Default,,0,0,0,,{clean}")

        current_time = end + gap

    with open(output_path, "w") as f:
        f.write(ass_header)
        f.write("\n".join(events))
        f.write("\n")

    return output_path


def render_final(
    voiceover_path: Path,
    broll_path: Path,
    captions_path: Path,
    output_path: Path,
    music_path: Path | None = None,
    music_volume: float = 0.12,
):
    """Combine voiceover + b-roll + music + captions into final video."""
    output_path = output_path.resolve()
    voiceover_path = voiceover_path.resolve()
    broll_path = broll_path.resolve()
    captions_path = captions_path.resolve()

    inputs = [
        "-i", str(broll_path),      # 0: video
        "-i", str(voiceover_path),   # 1: voiceover
    ]

    if music_path:
        music_path = music_path.resolve()
        inputs += ["-i", str(music_path)]  # 2: music
        # Mix voiceover (full volume) + music (low volume), loop music if needed
        filter_audio = (
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0=$(ffprobe -v error -show_entries format=duration "
            f"-of default=noprint_wrappers=1:nokey=1 {voiceover_path}),"
            f"volume={music_volume}[music];"
            f"[1:a][music]amix=inputs=2:duration=first[mixed]"
        )
        # Simpler approach: just set music volume and mix
        filter_audio = (
            f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[vo];"
            f"[2:a]aloop=loop=-1:size=2000000000,volume={music_volume},"
            f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[mu];"
            f"[vo][mu]amix=inputs=2:duration=first:dropout_transition=2[mixed]"
        )
        audio_map = ["-map", "[mixed]"]
    else:
        filter_audio = None
        audio_map = ["-map", "1:a"]

    # Build the full command
    vo_dur_str = str(get_audio_duration(voiceover_path))

    cmd = ["ffmpeg", "-y"] + inputs

    if filter_audio:
        cmd += ["-filter_complex", filter_audio]

    cmd += [
        "-map", "0:v",
    ] + audio_map + [
        "-t", vo_dur_str,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        "-loglevel", "error",
        str(output_path),
    ]

    subprocess.run(cmd, check=True)
    return output_path


def create_audio_first_remix(
    library_path: Path,
    narrative_clip_ids: list[str],
    output_path: Path,
    music_volume: float = 0.12,
):
    """Full audio-first remix pipeline.

    Args:
        library_path: Path to clip_library.json
        narrative_clip_ids: Ordered list of clip IDs for the voiceover narrative
        output_path: Where to save the final video
    """
    output_path = Path(output_path).resolve()
    work_dir = output_path.parent / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    clips = load_clip_library(library_path)

    # 1. Build voiceover narrative
    print("  Building voiceover narrative...")
    segments = build_narrative(clips, narrative_clip_ids)
    if not segments:
        print("  ERROR: No valid segments found")
        return None

    voiceover_path = work_dir / "voiceover.m4a"
    total_duration = stitch_voiceover(segments, voiceover_path)
    print(f"  Voiceover: {total_duration:.1f}s from {len(segments)} segments")

    # 2. Select and render b-roll
    print("  Selecting b-roll...")
    narrative_ids = {s.clip.id for s in segments}
    broll_clips = select_broll_clips(clips, narrative_ids, total_duration)
    broll_path = work_dir / "broll.mp4"
    render_broll_track(broll_clips, total_duration, broll_path)
    print(f"  B-roll: {len(broll_clips)} clips")

    # 3. Pick a music track
    music_path = pick_music_track(clips)
    if music_path:
        print(f"  Music: {music_path.name}")
    else:
        print("  Music: none found")

    # 4. Generate captions
    print("  Generating captions...")
    captions_path = work_dir / "captions.ass"
    generate_captions_ass(segments, captions_path)

    # 5. Render final
    print("  Rendering final video...")
    render_final(voiceover_path, broll_path, captions_path, output_path,
                 music_path=music_path, music_volume=music_volume)

    # Cleanup work dir
    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)

    print(f"  ✓ Done: {output_path}")
    return output_path
