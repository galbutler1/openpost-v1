"""
gen_rehooks.py — Re-Hook generator.

Takes a video's most engaging body segment, duplicates it, and prepends
it to the full video so the viewer gets the punchline as the hook.

Structure of output:
  [best body segment 2-4s]  +  [full original video start→end]

No b-roll, no audio changes — purely a hook injection.

Usage:
    python gen_rehooks.py --videos 10
    python gen_rehooks.py --videos 5 --min-perf 40
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

import config  # noqa: F401 — creates dirs
from models import Segment, Video, VideoMetadata

console = Console()

VIDEOS_DIR   = Path("data/videos")
SEGMENTS_DIR = Path("data/segments")
OUTPUT_DIR   = Path("data/output")
REHOOK_LOG   = Path("data/rehook_log.json")

# ── Hook-signal keywords ───────────────────────────────────────────────────────
_HOOK_WORDS = {
    "wait", "actually", "honest", "truth", "real", "secret",
    "million", "viral", "sold", "shipped", "crazy", "insane",
    "never", "always", "worst", "best",
    "why", "how",
}
_HOOK_PHRASES = {
    "i made", "we made", "i sold", "we sold", "i quit", "went viral",
    "sold out", "almost quit", "blew up", "took off", "real talk",
    "to be honest", "didn't expect", "look at this", "check this out",
    "here's the thing", "the crazy part", "this is how",
}


# ── Scoring ────────────────────────────────────────────────────────────────────

def hook_score(seg: Segment) -> float:
    """
    Score a body segment as a re-hook candidate.
    Higher = better hook potential.
    """
    t = seg.transcript.lower()

    word_hits   = sum(1 for w in _HOOK_WORDS if w in t.split())
    phrase_hits = sum(1 for p in _HOOK_PHRASES if p in t)
    engagement  = word_hits + phrase_hits * 2

    # Visual quality contributes heavily
    qual = seg.quality_score / 100.0

    # Duration sweet spot: 1.5–5s. Very short or very long clips are weak hooks.
    if seg.duration < 1.5:
        dur_mult = 0.0
    elif seg.duration <= 5.0:
        dur_mult = 1.0
    else:
        dur_mult = max(0.3, 1.0 - (seg.duration - 5.0) * 0.1)

    return (engagement * 2.0 + qual * 3.0) * dur_mult


def find_rehook_segment(segments: list[Segment]) -> Segment | None:
    """Return the body segment with the highest hook score."""
    candidates = [
        s for s in segments
        if s.zone.value == "body"
        and s.duration >= 1.5
        and s.quality_score >= 25
    ]
    if not candidates:
        return None
    return max(candidates, key=hook_score)


# ── Video loading ──────────────────────────────────────────────────────────────

def load_videos(min_perf: float = 0.0) -> list[Video]:
    all_meta: dict[str, VideoMetadata] = {}
    for f in VIDEOS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            all_meta[f.stem] = VideoMetadata(**d)
        except Exception:
            pass

    if not all_meta:
        console.print("[red]No video metadata found.[/red]")
        return []

    all_metas = list(all_meta.values())
    avg_views    = max(1, sum(v.view_count    for v in all_metas) / len(all_metas))
    avg_likes    = max(1, sum(v.like_count    for v in all_metas) / len(all_metas))
    avg_comments = max(1, sum(v.comment_count for v in all_metas) / len(all_metas))
    avg_shares   = max(1, sum(v.repost_count  for v in all_metas) / len(all_metas))

    def perf_score(meta: VideoMetadata) -> float:
        def ratio(val, avg): return min(val / avg, 2.0)
        raw = (
            ratio(meta.view_count, avg_views)    * 0.40
            + ratio(meta.like_count, avg_likes)  * 0.25
            + ratio(meta.comment_count, avg_comments) * 0.20
            + ratio(meta.repost_count, avg_shares)    * 0.15
        )
        return round(min(raw / 2.0 * 100, 100.0), 1)

    videos: list[Video] = []
    for vid_id, meta in all_meta.items():
        mp4  = VIDEOS_DIR / f"{vid_id}.mp4"
        segs = SEGMENTS_DIR / f"{vid_id}.json"
        if not mp4.exists() or not segs.exists():
            continue
        perf = perf_score(meta)
        if perf < min_perf:
            continue
        try:
            cache = json.loads(segs.read_text(encoding="utf-8"))
            segments = [Segment(**s) for s in (cache.get("segments", []) if isinstance(cache, dict) else cache)]
            full_transcript = cache.get("full_transcript", "") if isinstance(cache, dict) else ""
        except Exception:
            continue
        v = Video(video_id=vid_id, file_path=str(mp4), metadata=meta, performance_score=perf)
        v.segments = segments
        v.full_transcript = full_transcript
        videos.append(v)

    return sorted(videos, key=lambda v: v.performance_score, reverse=True)


# ── ffmpeg assembly ────────────────────────────────────────────────────────────

def _get_dimensions(path: str) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    w, h = r.stdout.strip().split(",")
    return int(w), int(h)


def build_rehook(video: Video, hook_seg: Segment, idx: int) -> Path:
    """
    Prepend hook_seg to the full video.
    Output: [hook clip] + [full original video]
    """
    out = OUTPUT_DIR / f"{video.video_id}_rehook_{idx}.mp4"
    path = video.file_path

    try:
        w, h = _get_dimensions(path)
    except Exception:
        w, h = 1080, 1920

    hs = hook_seg.start
    he = hook_seg.end

    # Two inputs — same file twice (hook trim + full video)
    # [0:v] → hook video clip
    # [0:a] → hook audio clip
    # [hv][1:v] concat video → [vout]
    # [ha][1:a] concat audio → [aout]
    fc = (
        f"[0:v]trim=start={hs:.6f}:end={he:.6f},setpts=PTS-STARTPTS,"
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[hv];"
        f"[0:a]atrim=start={hs:.6f}:end={he:.6f},asetpts=PTS-STARTPTS[ha];"
        f"[hv][ha][1:v][1:a]concat=n=2:v=1:a=1[vout][aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", path,
        "-i", path,
        "-filter_complex", fc,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level", "4.0",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace")
        raise RuntimeError(f"ffmpeg failed for {out.name}:\n{stderr[-2000:]}") from exc

    return out


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Re-Hook generator")
    parser.add_argument("--videos",   type=int,   default=10,  help="Number of re-hooks to generate")
    parser.add_argument("--min-perf", type=float, default=0.0, help="Min performance score filter")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold cyan]Booster — Re-Hook Generator[/bold cyan]",
        border_style="cyan",
    ))

    videos = load_videos(min_perf=args.min_perf)
    if not videos:
        console.print("[red]No videos loaded.[/red]")
        return

    console.print(f"Loaded [cyan]{len(videos)}[/cyan] videos, picking top {args.videos} by performance.\n")

    # Load existing log
    log: list[dict] = []
    if REHOOK_LOG.exists():
        try:
            log = json.loads(REHOOK_LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    existing_ids = {e["video_id"] for e in log}

    output_paths: list[Path] = []
    idx = 1

    for video in videos[:args.videos]:
        hook_seg = find_rehook_segment(video.segments)

        if hook_seg is None:
            console.print(f"[dim]Skip {video.video_id} — no eligible body segment[/dim]")
            continue

        score = hook_score(hook_seg)
        console.print(
            f"[bold]Re-Hook {idx}:[/bold] [cyan]{video.video_id}[/cyan] "
            f"(perf={video.performance_score:.1f}, views={video.metadata.view_count:,})\n"
            f"  Hook segment: {hook_seg.start:.1f}s–{hook_seg.end:.1f}s "
            f"| score={score:.1f} | q={hook_seg.quality_score}\n"
            f"  Transcript: [dim]{hook_seg.transcript[:80]}[/dim]"
        )

        try:
            out = build_rehook(video, hook_seg, idx)
            output_paths.append(out)
            console.print(f"  [green]Saved:[/green] {out}\n")

            # Append to log (update existing entry if re-run)
            entry = {
                "rehook_num":       idx,
                "video_id":         video.video_id,
                "hook_start":       hook_seg.start,
                "hook_end":         hook_seg.end,
                "hook_transcript":  hook_seg.transcript,
                "hook_score":       round(score, 2),
                "quality_score":    hook_seg.quality_score,
                "created_at":       datetime.now().strftime("%Y-%m-%d"),
            }
            if video.video_id in existing_ids:
                log = [e if e["video_id"] != video.video_id else entry for e in log]
            else:
                log.append(entry)

            idx += 1
        except Exception as exc:
            console.print(f"  [red]Failed: {exc}[/red]\n")

    REHOOK_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")
    console.print(f"[bold green]Done![/bold green] Produced {len(output_paths)} re-hook(s).")
    for p in output_paths:
        console.print(f"  {p}")


if __name__ == "__main__":
    main()
