"""
gen_remixes.py — Generate remixes from cached segments.

Loads all 100 tagged videos from cache, picks the highest-performing
unused anchors, and generates remixes without re-downloading anything.

Usage:
    python gen_remixes.py --remixes 15 --min-perf 0 [--exclude-anchors ID1,ID2,...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

import config  # noqa: F401 — creates dirs
from assembler.anchor import select_anchors, warn_low_performance
from assembler.windows import detect_windows
from assembler.matcher import find_match, classify_topic, broll_compatibility_score
from assembler.editor import assemble_remix
from models import RemixPlan, Segment, Video, VideoMetadata
from pipeline.beats import detect_beats

console = Console()

VIDEOS_DIR = Path("data/videos")
SEGMENTS_DIR = Path("data/segments")

# Anchors already used in previous remix runs
PREVIOUSLY_USED_ANCHORS = {
    # Batch 1 — early test runs
    "DNBdqRQpMkr", "DOJlrzNCWIR", "DOJsbgbCeka", "DT3Z00gCdUl",
    # Batch 2 — 13-video run
    "DGtl1oPN9nV", "DEVLB4LNTGi", "DDXkpPBuog1", "DGygHDUtpah",
    "DMG4Yv6oJKF", "DCmhWH9OMao", "DH3ZMJatz0b", "C-8x48op-y8",
    "DMiwzlcJQD3", "C8pmKyYJQk3", "DN1cV-X2kv7", "DPKBkcfDWIQ", "DNwMdrR0sDk",
    # Batch 3 — OpenPost v3 (11 videos)
    "C7w1eMUvXLp", "C8DYloWp_7r", "C8cZ9ICuaA_", "C9dqJWMJusG",
    "C9iZLenJPiE", "DDVQPIuuZe5", "DEdLTHbuSxp", "DFvYDyWtZ6c",
    "DGyGX1FsdtX", "DMWSxWCJDUt", "DMyb9R5JK0c",
    # Batch 4 — 4 videos
    "DH1UhIqNm2g", "C9fB5nROqRU", "DMO3YWuoD4p", "DHbAaC3tCjM",
    # Batch 5 — 8 videos
    "C88FX6ZJejL", "C9KwMGDuZ19", "C9lBg3tJ1i5", "C8xq5PjJzz0",
    "DH1UhIqNm2g", "DMO3YWuoD4p", "DHbAaC3tCjM",
    # Batch 6 — 5 videos
    "DElOn_PtQwf", "DG_rJO3Nnw4", "C70eOWHOWvS", "DG5oB_LtHlA", "DDdH1DPN0Kb",
    # Batch 7 — 5 videos
    "DL5OckHNbpB", "DSXFQd0jTYq", "DTOjVRYDXnm", "C9yUhNFJJJK", "DQjvxK-CnO4",
    # Batch 7b — 2 videos (partial run before fix)
    "DFBQyfduWQ8", "DF3LyCNuYlR",
}


def load_all_videos(min_perf: float = 0.0) -> list[Video]:
    """Load all videos from cache, compute performance scores from full library."""
    # Load all metadata
    all_meta: dict[str, VideoMetadata] = {}
    for f in VIDEOS_DIR.glob("*.json"):
        vid_id = f.stem
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            all_meta[vid_id] = VideoMetadata(**d)
        except Exception:
            pass

    if not all_meta:
        console.print("[red]No video metadata found in data/videos/[/red]")
        return []

    # Compute performance scores relative to full library
    all_metas = list(all_meta.values())
    avg_views    = max(1, sum(v.view_count    for v in all_metas) / len(all_metas))
    avg_likes    = max(1, sum(v.like_count    for v in all_metas) / len(all_metas))
    avg_comments = max(1, sum(v.comment_count for v in all_metas) / len(all_metas))
    avg_shares   = max(1, sum(v.repost_count  for v in all_metas) / len(all_metas))

    def perf_score(meta: VideoMetadata) -> float:
        def ratio(val: int, avg: float) -> float:
            return min(val / avg, 2.0)
        raw = (
            ratio(meta.view_count,     avg_views)    * 0.40
            + ratio(meta.like_count,   avg_likes)    * 0.25
            + ratio(meta.comment_count, avg_comments) * 0.20
            + ratio(meta.repost_count,  avg_shares)  * 0.15
        )
        return round(min(raw / 2.0 * 100, 100.0), 1)

    videos: list[Video] = []
    for vid_id, meta in all_meta.items():
        mp4_path = VIDEOS_DIR / f"{vid_id}.mp4"
        seg_path  = SEGMENTS_DIR / f"{vid_id}.json"

        if not mp4_path.exists() or not seg_path.exists():
            continue

        perf = perf_score(meta)
        if perf < min_perf:
            continue

        # Load segments
        try:
            cache = json.loads(seg_path.read_text(encoding="utf-8"))
            if isinstance(cache, dict):
                segments = [Segment(**s) for s in cache.get("segments", [])]
                full_transcript = cache.get("full_transcript", "")
            else:
                segments = [Segment(**s) for s in cache]
                full_transcript = ""
        except Exception as e:
            console.print(f"  [yellow]Could not load segments for {vid_id}: {e}[/yellow]")
            continue

        v = Video(
            video_id=vid_id,
            file_path=str(mp4_path),
            metadata=meta,
            performance_score=perf,
        )
        v.segments = segments
        v.full_transcript = full_transcript
        videos.append(v)

    console.print(f"Loaded [cyan]{len(videos)}[/cyan] videos with segments.")
    return videos


def build_remix(
    anchor: Video,
    all_videos: list[Video],
    remix_index: int,
) -> Path | None:
    """Build one remix. Returns None if no b-roll cuts were made."""
    try:
        beats = detect_beats(anchor.file_path)
    except Exception:
        beats = []

    windows = detect_windows(anchor.segments, beats)
    if not windows:
        console.print(f"  [yellow]No cutaway windows found.[/yellow]")
        return None

    # Pre-classify topic from the FULL video transcript — much more reliable
    # than classifying each 2-second body segment in isolation.
    full_text = anchor.full_transcript or " ".join(s.transcript for s in anchor.segments)
    video_topic = classify_topic(full_text)
    console.print(f"  [dim]Video topic: {video_topic or 'none'}[/dim]")

    plan_windows: list[tuple] = []
    used_segment_ids: set[str] = set()
    used_source_video_ids: set[str] = set()
    last_visual_type: str | None = None
    cut_count = 0

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
            video_topic=video_topic,
            last_visual_type=last_visual_type,
        )
        if match is not None:
            used_segment_ids.add(match.segment_id)
            used_source_video_ids.add(match.source_video_id)
            last_visual_type = match.visual_type.value
            cut_count += 1
            console.print(
                f"  [green]✓[/green] {window.start:.1f}s–{window.end:.1f}s → "
                f"{match.visual_type.value} from {match.source_video_id}"
            )
        else:
            console.print(
                f"  [dim]✗ {window.start:.1f}s–{window.end:.1f}s → no match[/dim]"
            )
        plan_windows.append((window, match))

    if cut_count == 0:
        console.print(f"  [yellow]0 b-roll cuts — skipping.[/yellow]")
        return None

    plan = RemixPlan(anchor_video=anchor, windows=plan_windows)
    video_lookup = {v.video_id: v.file_path for v in all_videos}
    console.print(f"  [cyan]Assembling ({cut_count} cuts)...[/cyan]")
    return assemble_remix(plan, remix_index, video_lookup=video_lookup)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate remixes from cached segments")
    parser.add_argument("--remixes", type=int, default=15, help="Number of remixes to generate")
    parser.add_argument("--min-perf", type=float, default=0.0, help="Min performance score for b-roll pool")
    parser.add_argument("--anchor-min-perf", type=float, default=0.0, help="Min performance score for anchors")
    parser.add_argument("--above-median-views", action="store_true", default=True, help="Only use anchors with above-median view counts")
    parser.add_argument("--all-views", action="store_true", default=False, help="Allow any view count (overrides --above-median-views)")
    parser.add_argument("--reuse-anchors", action="store_true", default=False, help="Allow previously used anchors (new b-roll will be selected)")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold cyan]Booster — Remix Generator[/bold cyan] (cache mode)",
        border_style="cyan",
    ))

    all_videos = load_all_videos(min_perf=args.min_perf)
    if not all_videos:
        sys.exit(1)

    # Show top candidates
    sorted_by_perf = sorted(all_videos, key=lambda v: v.performance_score, reverse=True)
    console.print("\n[bold]Top 15 by performance score:[/bold]")
    for v in sorted_by_perf[:15]:
        used_tag = " [dim][USED][/dim]" if v.video_id in PREVIOUSLY_USED_ANCHORS else ""
        console.print(
            f"  {v.video_id}: perf={v.performance_score:.1f}  "
            f"views={v.metadata.view_count:,}{used_tag}"
        )

    # Compute median view count across all loaded videos
    sorted_views = sorted(v.metadata.view_count for v in all_videos)
    median_views = sorted_views[len(sorted_views) // 2]
    console.print(f"Median views across library: [cyan]{median_views:,}[/cyan]")

    # Filter anchors: exclude previously used (unless --reuse-anchors), apply view threshold
    anchor_pool = [
        v for v in all_videos
        if (args.reuse_anchors or v.video_id not in PREVIOUSLY_USED_ANCHORS)
        and v.performance_score >= args.anchor_min_perf
        and (args.all_views or not args.above_median_views or v.metadata.view_count > median_views)
    ]

    # Score each anchor by b-roll compatibility (topic signal + body segment count)
    # and sort by that score descending so most-compatible anchors go first.
    for v in anchor_pool:
        full_text = v.full_transcript or " ".join(s.transcript for s in v.segments)
        body_count = sum(1 for s in v.segments if s.zone.value == "body")
        v._broll_score = broll_compatibility_score(full_text, body_count)

    anchor_pool.sort(key=lambda v: (v._broll_score, v.metadata.view_count), reverse=True)

    console.print(f"Anchor pool: [cyan]{len(anchor_pool)}[/cyan] eligible videos (above-median views, unused)")
    console.print("\n[bold]Top candidates by b-roll compatibility:[/bold]")
    for v in anchor_pool[:10]:
        console.print(f"  {v.video_id}: broll_score={v._broll_score:.0f}  views={v.metadata.view_count:,}")

    # Use select_anchors to pick eligible ones (body segment check), sorted by perf
    anchors = select_anchors(anchor_pool, args.remixes)

    for warning in warn_low_performance(anchors):
        console.print(f"[yellow]{warning}[/yellow]")

    if not anchors:
        console.print("[red]No eligible anchor candidates found.[/red]")
        sys.exit(1)

    console.print(f"\n[bold]Generating {len(anchors)} remix(es)...[/bold]\n")

    output_paths: list[Path] = []
    used_anchors: list[str] = []
    remix_idx = 1

    for anchor in anchors:
        console.print(
            f"[bold]Remix {remix_idx}:[/bold] anchor = [cyan]{anchor.video_id}[/cyan] "
            f"(perf={anchor.performance_score:.1f}, views={anchor.metadata.view_count:,})"
        )
        try:
            out = build_remix(anchor, all_videos, remix_idx)
            if out is not None:
                output_paths.append(out)
                used_anchors.append(anchor.video_id)
                console.print(f"  [green]Saved:[/green] {out}")
                remix_idx += 1
        except Exception as exc:
            console.print(f"  [red]Failed: {exc}[/red]")

    console.print("\n[bold green]Done![/bold green]")
    console.print(f"Produced {len(output_paths)} remix(es).")
    if output_paths:
        for p in output_paths:
            console.print(f"  {p}")
    console.print(f"\nAnchor IDs used: {used_anchors}")


if __name__ == "__main__":
    main()
