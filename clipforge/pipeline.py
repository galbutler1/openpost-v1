"""Main processing pipeline — orchestrates all workers."""

import json
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from clipforge.models.clip import Clip
from clipforge.workers.scene_detector import process_video
from clipforge.workers.audio_separator import process_clip_audio
from clipforge.workers.transcriber import transcribe_clip
from clipforge.workers.audio_analyzer import analyze_clip_audio

console = Console()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def discover_videos(input_dir: Path) -> list[Path]:
    """Find all video files in a directory."""
    videos = [f for f in input_dir.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS]
    videos.sort()
    return videos


def process_single_video(video_path: Path, output_dir: Path) -> list[Clip]:
    """Run the full pipeline on a single video."""
    console.print(f"\n[bold cyan]Processing:[/] {video_path.name}")

    # Step 1: Scene detection + splitting
    console.print("  [dim]Detecting scenes and splitting...[/]")
    clips = process_video(video_path, output_dir)
    console.print(f"  [green]Found {len(clips)} clips[/]")

    processed_clips = []
    for clip in clips:
        # Step 2: Audio separation
        console.print(f"  [dim]Separating audio for {clip.id}...[/]")
        clip = process_clip_audio(clip, output_dir)

        # Step 3: Transcription
        console.print(f"  [dim]Transcribing {clip.id}...[/]")
        clip = transcribe_clip(clip)

        # Step 4: Audio analysis (beats + energy)
        console.print(f"  [dim]Analyzing audio for {clip.id}...[/]")
        clip = analyze_clip_audio(clip)

        processed_clips.append(clip)
        console.print(f"  [green]✓ {clip.id}[/] — {clip.duration:.1f}s, {len(clip.beats)} beats, tags: {clip.tags}")

    return processed_clips


def run_pipeline(input_dir: Path, output_dir: Path) -> list[Clip]:
    """Process all videos in input_dir and build a clip library."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    videos = discover_videos(input_dir)
    if not videos:
        console.print("[red]No video files found in input directory.[/]")
        return []

    console.print(f"[bold]Found {len(videos)} videos to process[/]")

    all_clips = []
    for video in videos:
        clips = process_single_video(video, output_dir)
        all_clips.extend(clips)

    # Save clip library as JSON
    library_path = output_dir / "clip_library.json"
    library_data = [clip.to_dict() for clip in all_clips]
    library_path.write_text(json.dumps(library_data, indent=2))

    console.print(f"\n[bold green]Done![/] {len(all_clips)} clips processed.")
    console.print(f"Clip library saved to: {library_path}")

    # Summary
    console.print("\n[bold]Library Summary:[/]")
    talking = sum(1 for c in all_clips if "talking" in c.tags)
    broll = sum(1 for c in all_clips if "b-roll" in c.tags)
    high_e = sum(1 for c in all_clips if "high-energy" in c.tags)
    console.print(f"  Talking clips: {talking}")
    console.print(f"  B-roll clips:  {broll}")
    console.print(f"  High-energy:   {high_e}")
    console.print(f"  Total duration: {sum(c.duration for c in all_clips):.1f}s")

    return all_clips
