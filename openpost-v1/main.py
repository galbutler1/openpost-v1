"""
main.py — Booster v1 CLI entry point.

Usage:
    python main.py --url <profile_url> --download <N> --remixes <X>

Downloads N reels from the given profile URL, runs them through the full
pipeline, then generates X remix videos in data/output/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

import config  # noqa: F401 – creates dirs on import
from ingest import download_reels
from pipeline.transcribe import transcribe
from pipeline.vision import label_frames
from pipeline.beats import detect_beats
from pipeline.tagger import tag_video
from pipeline.merger import merge_segments
from assembler.anchor import select_anchors, warn_low_performance
from assembler.windows import detect_windows
from assembler.matcher import find_match
from assembler.editor import assemble_remix
from models import RemixPlan, Video

console = Console()


# ---------------------------------------------------------------------------
# Per-video pipeline
# ---------------------------------------------------------------------------

def _get_video_duration(file_path: str) -> float:
    """Return video duration in seconds via cv2."""
    import cv2
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return frames / fps


def process_video(video: Video) -> Video:
    """
    Run the full pipeline on one video and populate video.segments.
    Saves a segment JSON file to data/segments/{video_id}.json.
    Returns the updated Video object.
    """
    vid_id = video.video_id
    seg_path = config.SEGMENTS_DIR / f"{vid_id}.json"

    # If segments are already cached, load and return
    if seg_path.exists():
        console.print(f"  [dim]Using cached segments for {vid_id}[/dim]")
        cache = json.loads(seg_path.read_text())
        from models import Segment
        # Support both old format (plain list) and new format (dict with full_transcript)
        if isinstance(cache, dict):
            video.segments = [Segment(**s) for s in cache.get("segments", [])]
            video.full_transcript = cache.get("full_transcript", "")
        else:
            video.segments = [Segment(**s) for s in cache]
        return video

    file_path = video.file_path
    duration = _get_video_duration(file_path)

    if duration <= 0:
        console.print(f"  [red]Could not determine duration for {vid_id}, skipping.[/red]")
        return video

    console.print(f"  [cyan]Transcribing...[/cyan]")
    try:
        words = transcribe(file_path)
    except Exception as exc:
        console.print(f"  [yellow]Transcription failed: {exc}[/yellow]")
        words = []

    console.print(f"  [cyan]Labelling frames (vision)...[/cyan]")
    try:
        frame_labels = label_frames(file_path)
    except Exception as exc:
        console.print(f"  [yellow]Vision labelling failed: {exc}[/yellow]")
        frame_labels = []

    console.print(f"  [cyan]Detecting beats...[/cyan]")
    try:
        beats = detect_beats(file_path)
    except Exception as exc:
        console.print(f"  [yellow]Beat detection failed: {exc}[/yellow]")
        beats = []

    console.print(f"  [cyan]Tagging segments (GPT-4o)...[/cyan]")
    raw_segments, full_transcript = tag_video(
        video_id=vid_id,
        video_path=file_path,
        word_timestamps=words,
        frame_labels=frame_labels,
        beat_timestamps=beats,
        video_duration=duration,
        performance_score=video.performance_score,
    )

    console.print(f"  [cyan]Merging segments...[/cyan]")
    segments = merge_segments(raw_segments, duration)

    video.segments = segments
    video.full_transcript = full_transcript

    # Cache to disk — store full_transcript alongside segments
    seg_path.write_text(
        json.dumps({"full_transcript": full_transcript, "segments": [s.model_dump() for s in segments]}, indent=2)
    )
    console.print(
        f"  [green]Done:[/green] {len(segments)} segments saved to {seg_path.name}"
    )

    return video


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_remix(
    anchor: Video,
    all_videos: list[Video],
    remix_index: int,
) -> Path:
    """Build one remix from *anchor* against the full video pool."""

    # Beats for the anchor (for beat-snapping windows)
    try:
        beats = detect_beats(anchor.file_path)
    except Exception:
        beats = []

    # Detect cutaway windows in anchor
    windows = detect_windows(anchor.segments, beats)

    if not windows:
        console.print(
            f"  [yellow]No eligible cutaway windows found in anchor {anchor.video_id}.[/yellow]"
        )

    # Match b-roll for each window
    # - used_segment_ids: never reuse the same clip
    # - used_source_video_ids: never reuse the same source video in one remix
    plan_windows: list[tuple] = []
    used_segment_ids: set[str] = set()
    used_source_video_ids: set[str] = set()

    for window in windows:
        anchor_seg = next(
            (s for s in anchor.segments if s.segment_id == window.anchor_segment_id),
            None,
        )
        if anchor_seg is None:
            plan_windows.append((window, None))
            continue

        match = find_match(
            window=window,
            anchor_segment=anchor_seg,
            anchor_video_id=anchor.video_id,
            all_videos=all_videos,
            used_segment_ids=used_segment_ids,
            used_source_video_ids=used_source_video_ids,
        )
        if match is not None:
            used_segment_ids.add(match.segment_id)
            used_source_video_ids.add(match.source_video_id)
            console.print(
                f"  [green]✓[/green] {window.start:.1f}s–{window.end:.1f}s → "
                f"{match.visual_type.value} from {match.source_video_id}"
            )
        else:
            console.print(
                f"  [dim]✗ {window.start:.1f}s–{window.end:.1f}s → no match[/dim]"
            )
        plan_windows.append((window, match))

    plan = RemixPlan(anchor_video=anchor, windows=plan_windows)

    video_lookup = {v.video_id: v.file_path for v in all_videos}
    console.print(f"  [cyan]Assembling video with ffmpeg...[/cyan]")
    output_path = assemble_remix(plan, remix_index, video_lookup=video_lookup)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Booster v1 — automated b-roll remix generator"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Profile URL to download reels from (TikTok or Instagram)",
    )
    parser.add_argument(
        "--download",
        type=int,
        default=10,
        metavar="N",
        help="Number of reels to download (default: 10)",
    )
    parser.add_argument(
        "--remixes",
        type=int,
        default=3,
        metavar="X",
        help="Number of remix videos to generate (default: 3)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    console.print(
        Panel.fit(
            "[bold cyan]Booster v1[/bold cyan] — Video Tagging & Assembly",
            border_style="cyan",
        )
    )

    console.print(f"\n[bold]Step 1/3:[/bold] Downloading {args.download} reels from [cyan]{args.url}[/cyan]\n")

    try:
        videos = download_reels(args.url, args.download)
    except RuntimeError as exc:
        console.print(f"[red]Download failed:[/red] {exc}")
        sys.exit(1)

    if not videos:
        console.print("[red]No videos downloaded. Exiting.[/red]")
        sys.exit(1)

    console.print(f"[green]Downloaded {len(videos)} videos.[/green]\n")

    # -----------------------------------------------------------------------
    console.print(f"[bold]Step 2/3:[/bold] Processing all {len(videos)} videos through the pipeline\n")

    processed: list[Video] = []
    for i, video in enumerate(videos, 1):
        console.print(
            f"[bold]Video {i}/{len(videos)}:[/bold] [cyan]{video.video_id}[/cyan] "
            f"(perf={video.performance_score:.1f})"
        )
        try:
            video = process_video(video)
            processed.append(video)
        except Exception as exc:
            console.print(f"  [red]Pipeline failed for {video.video_id}: {exc}[/red]")

    if not processed:
        console.print("[red]No videos processed successfully. Exiting.[/red]")
        sys.exit(1)

    # -----------------------------------------------------------------------
    if args.remixes == 0:
        console.print("\n[bold green]All videos tagged and saved. Done![/bold green]")
        return

    console.print(f"\n[bold]Step 3/3:[/bold] Generating {args.remixes} remix(es)\n")

    anchors = select_anchors(processed, args.remixes)

    for warning in warn_low_performance(anchors):
        console.print(f"[yellow]{warning}[/yellow]")

    if not anchors:
        console.print("[red]No eligible anchor videos found. Exiting.[/red]")
        sys.exit(1)

    output_paths: list[Path] = []
    for remix_idx, anchor in enumerate(anchors, 1):
        console.print(
            f"[bold]Remix {remix_idx}/{len(anchors)}:[/bold] anchor = "
            f"[cyan]{anchor.video_id}[/cyan] (perf={anchor.performance_score:.1f})"
        )
        try:
            out = build_remix(anchor, processed, remix_idx)
            output_paths.append(out)
            console.print(f"  [green]Saved:[/green] {out}")
        except Exception as exc:
            console.print(f"  [red]Remix {remix_idx} failed: {exc}[/red]")

    console.print("\n[bold green]Done![/bold green]")
    if output_paths:
        console.print(f"Output files ({len(output_paths)}):")
        for p in output_paths:
            console.print(f"  {p}")
    else:
        console.print("[yellow]No remix files were produced.[/yellow]")


if __name__ == "__main__":
    main()
