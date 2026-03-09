"""
log_remixes.py — Re-run matching for all past remix anchors and write a
detailed blueprint log showing anchor, b-roll order, timestamps, and gaps.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime

import config  # noqa
from assembler.windows import detect_windows
from assembler.matcher import find_match
from models import Segment, Video, VideoMetadata
from pipeline.beats import detect_beats

VIDEOS_DIR = Path("data/videos")
SEGMENTS_DIR = Path("data/segments")

# All remixes ever made, in chronological order of when they were produced.
# Format: (batch_label, anchor_video_id)
ALL_REMIXES = [
    # Batch 1 — early test runs
    ("Batch 1 (early test)", "DOJlrzNCWIR"),
    ("Batch 1 (early test)", "DOJsbgbCeka"),
    ("Batch 1 (early test)", "DNBdqRQpMkr"),
    ("Batch 1 (early test)", "DT3Z00gCdUl"),
    # Batch 2 — 13-video run (before Quick Story ban)
    ("Batch 2 (13-video run)", "DGtl1oPN9nV"),
    ("Batch 2 (13-video run)", "DEVLB4LNTGi"),
    ("Batch 2 (13-video run)", "DDXkpPBuog1"),
    ("Batch 2 (13-video run)", "DGygHDUtpah"),
    ("Batch 2 (13-video run)", "DMG4Yv6oJKF"),
    ("Batch 2 (13-video run)", "DCmhWH9OMao"),
    ("Batch 2 (13-video run)", "DH3ZMJatz0b"),
    ("Batch 2 (13-video run)", "C-8x48op-y8"),
    ("Batch 2 (13-video run)", "DMiwzlcJQD3"),
    ("Batch 2 (13-video run)", "C8pmKyYJQk3"),
    ("Batch 2 (13-video run)", "DN1cV-X2kv7"),
    ("Batch 2 (13-video run)", "DPKBkcfDWIQ"),
    ("Batch 2 (13-video run)", "DNwMdrR0sDk"),
    # Batch 3 — OpenPost v3 (11 videos, Quick Story banned, above-median views)
    ("Batch 3 (OpenPost v3)", "C7w1eMUvXLp"),
    ("Batch 3 (OpenPost v3)", "C8DYloWp_7r"),
    ("Batch 3 (OpenPost v3)", "C8cZ9ICuaA_"),
    ("Batch 3 (OpenPost v3)", "C9dqJWMJusG"),
    ("Batch 3 (OpenPost v3)", "C9iZLenJPiE"),
    ("Batch 3 (OpenPost v3)", "DDVQPIuuZe5"),
    ("Batch 3 (OpenPost v3)", "DEdLTHbuSxp"),
    ("Batch 3 (OpenPost v3)", "DFvYDyWtZ6c"),
    ("Batch 3 (OpenPost v3)", "DGyGX1FsdtX"),
    ("Batch 3 (OpenPost v3)", "DMWSxWCJDUt"),
    ("Batch 3 (OpenPost v3)", "DMyb9R5JK0c"),
]


def load_all_videos() -> list[Video]:
    all_meta: dict[str, VideoMetadata] = {}
    for f in VIDEOS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            all_meta[f.stem] = VideoMetadata(**d)
        except Exception:
            pass

    all_metas = list(all_meta.values())
    avg_views    = max(1, sum(v.view_count    for v in all_metas) / len(all_metas))
    avg_likes    = max(1, sum(v.like_count    for v in all_metas) / len(all_metas))
    avg_comments = max(1, sum(v.comment_count for v in all_metas) / len(all_metas))
    avg_shares   = max(1, sum(v.repost_count  for v in all_metas) / len(all_metas))

    def perf(meta):
        def r(val, avg): return min(val / avg, 2.0)
        raw = r(meta.view_count,avg_views)*0.40 + r(meta.like_count,avg_likes)*0.25 + \
              r(meta.comment_count,avg_comments)*0.20 + r(meta.repost_count,avg_shares)*0.15
        return round(min(raw/2.0*100, 100.0), 1)

    videos = []
    for vid_id, meta in all_meta.items():
        mp4 = VIDEOS_DIR / f"{vid_id}.mp4"
        seg = SEGMENTS_DIR / f"{vid_id}.json"
        if not mp4.exists() or not seg.exists():
            continue
        try:
            cache = json.loads(seg.read_text(encoding="utf-8"))
            segments = [Segment(**s) for s in (cache.get("segments", []) if isinstance(cache, dict) else cache)]
            transcript = cache.get("full_transcript", "") if isinstance(cache, dict) else ""
        except Exception:
            continue
        v = Video(video_id=vid_id, file_path=str(mp4), metadata=meta, performance_score=perf(meta))
        v.segments = segments
        v.full_transcript = transcript
        videos.append(v)
    return videos


def build_plan(anchor: Video, all_videos: list[Video]):
    """Return list of (window, matched_segment_or_None) for this anchor."""
    try:
        beats = detect_beats(anchor.file_path)
    except Exception:
        beats = []

    windows = detect_windows(anchor.segments, beats)
    used_segment_ids: set[str] = set()
    used_source_ids: set[str] = set()
    plan = []

    for window in windows:
        anchor_seg = next(
            (s for s in anchor.segments if s.segment_id == window.anchor_segment_id), None
        )
        if anchor_seg is None:
            plan.append((window, None))
            continue
        match = find_match(
            window=window,
            anchor_segment=anchor_seg,
            anchor_video_id=anchor.video_id,
            all_videos=all_videos,
            used_segment_ids=used_segment_ids,
            used_source_video_ids=used_source_ids,
        )
        if match:
            used_segment_ids.add(match.segment_id)
            used_source_ids.add(match.source_video_id)
        plan.append((window, match))
    return plan


def fmt_time(t: float) -> str:
    return f"{t:.1f}s"


def main():
    print("Loading videos...")
    all_videos = load_all_videos()
    vid_lookup = {v.video_id: v for v in all_videos}

    lines = []
    lines.append("=" * 70)
    lines.append("OPENPOST — REMIX LOG")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Total remixes logged: {len(ALL_REMIXES)}")
    lines.append("=" * 70)

    current_batch = None
    remix_num = 0

    for batch_label, anchor_id in ALL_REMIXES:
        if batch_label != current_batch:
            current_batch = batch_label
            lines.append("")
            lines.append("─" * 70)
            lines.append(f"  {batch_label.upper()}")
            lines.append("─" * 70)

        anchor = vid_lookup.get(anchor_id)
        if anchor is None:
            lines.append(f"\n[MISSING] {anchor_id} — no segments cached")
            continue

        remix_num += 1
        meta = anchor.metadata
        lines.append(f"\nRemix #{remix_num} — Anchor: {anchor_id}")
        lines.append(f"  Upload date : {meta.upload_date}")
        lines.append(f"  Views       : {meta.view_count:,}  |  Likes: {meta.like_count:,}")
        lines.append(f"  Transcript  : {(anchor.full_transcript or '').replace(chr(10),' ')[:120]}...")

        print(f"  Building plan for {anchor_id}...")
        plan = build_plan(anchor, all_videos)

        matched = [(w, seg) for w, seg in plan if seg is not None]
        lines.append(f"  B-roll cuts : {len(matched)} / {len(plan)} windows")
        lines.append("")

        if not matched:
            lines.append("  (no b-roll inserted — anchor plays uncut)")
            continue

        lines.append(f"  {'#':<3}  {'Window':<16}  {'Duration':<10}  {'Gap from prev':<15}  {'Visual Type':<28}  Source Video")
        lines.append(f"  {'-'*3}  {'-'*16}  {'-'*10}  {'-'*15}  {'-'*28}  {'-'*15}")

        prev_end = 0.0
        cut_num = 0
        for window, seg in plan:
            if seg is None:
                continue
            cut_num += 1
            gap = window.beat_snapped_start - prev_end
            gap_str = f"+{gap:.1f}s anchor" if gap > 0.02 else "consecutive"
            lines.append(
                f"  {cut_num:<3}  "
                f"{fmt_time(window.start)}-{fmt_time(window.end):<10}  "
                f"{fmt_time(window.duration):<10}  "
                f"{gap_str:<15}  "
                f"{seg.visual_type.value:<28}  "
                f"{seg.source_video_id}"
            )
            prev_end = window.beat_snapped_start + window.duration

    lines.append("")
    lines.append("=" * 70)
    lines.append("END OF LOG")
    lines.append("=" * 70)

    log_path = Path("remix_log.txt")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nLog written to {log_path} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
