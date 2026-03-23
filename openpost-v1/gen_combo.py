"""
gen_combo.py — Combo generator: Re-Hook + B-Roll Remix in one video.

Structure of output:
  [best body segment hook 2-5s]  +  [full original video WITH b-roll cuts]

The hook grabs attention immediately, then the b-roll remix sustains it.

Usage:
    python gen_combo.py --combos 5 --anchor-min-perf 50
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

import config  # noqa: F401
from gen_rehooks import find_rehook_segment, hook_score, _HOOK_WORDS, _HOOK_PHRASES
from gen_remixes import load_all_videos, build_remix, PREVIOUSLY_USED_ANCHORS
from assembler.anchor import select_anchors
from assembler.matcher import broll_compatibility_score, classify_topic

console = Console()

OUTPUT_DIR = Path("data/output")


def _get_dimensions(path: str) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    w, h = r.stdout.strip().split(",")
    return int(w), int(h)


def prepend_hook_to_remix(
    anchor_path: str,
    remix_path: Path,
    hook_start: float,
    hook_end: float,
    out_path: Path,
) -> Path:
    """
    Prepend a hook clip from the original anchor video to the remix output.
    [hook trim from anchor] + [full remix video]
    """
    try:
        w, h = _get_dimensions(anchor_path)
    except Exception:
        w, h = 1080, 1920

    hs, he = hook_start, hook_end

    fc = (
        f"[0:v]trim=start={hs:.6f}:end={he:.6f},setpts=PTS-STARTPTS,"
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[hv];"
        f"[0:a]atrim=start={hs:.6f}:end={he:.6f},asetpts=PTS-STARTPTS[ha];"
        f"[hv][ha][1:v][1:a]concat=n=2:v=1:a=1[vout][aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", anchor_path,
        "-i", str(remix_path),
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
        str(out_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace")
        raise RuntimeError(f"ffmpeg failed: {stderr[-2000:]}") from exc

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Combo: Re-Hook + B-Roll Remix")
    parser.add_argument("--combos",          type=int,   default=5,   help="Number of combos to generate")
    parser.add_argument("--anchor-min-perf", type=float, default=50,  help="Min performance score for anchors")
    parser.add_argument("--min-perf",        type=float, default=0.0, help="Min perf for b-roll pool")
    parser.add_argument("--reuse-anchors",   action="store_true", default=True)
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold cyan]Booster — Combo Generator[/bold cyan] (Re-Hook + B-Roll)",
        border_style="cyan",
    ))

    all_videos = load_all_videos(min_perf=args.min_perf)
    if not all_videos:
        sys.exit(1)

    # Score and rank anchors by b-roll compatibility
    for v in all_videos:
        full_text = v.full_transcript or " ".join(s.transcript for s in v.segments)
        body_count = sum(1 for s in v.segments if s.zone.value == "body")
        v._broll_score = broll_compatibility_score(full_text, body_count)

    BLOCKED_ANCHORS = {"DOJlrzNCWIR", "DOJsbgbCeka"}
    anchor_pool = [
        v for v in all_videos
        if v.video_id not in BLOCKED_ANCHORS
        and v.performance_score >= args.anchor_min_perf
        and v.metadata.view_count > sorted(vv.metadata.view_count for vv in all_videos)[len(all_videos) // 2]
    ]
    anchor_pool.sort(key=lambda v: (v._broll_score, v.metadata.view_count), reverse=True)

    console.print(f"Anchor pool: [cyan]{len(anchor_pool)}[/cyan] videos\n")
    for v in anchor_pool[:8]:
        console.print(f"  {v.video_id}: broll={v._broll_score:.0f}  views={v.metadata.view_count:,}")

    anchors = select_anchors(anchor_pool, args.combos)
    if not anchors:
        console.print("[red]No eligible anchors.[/red]")
        sys.exit(1)

    console.print(f"\n[bold]Generating {len(anchors)} combo(s)...[/bold]\n")

    global_used_segment_ids: set[str] = set()
    output_paths: list[Path] = []
    idx = 1

    for anchor in anchors:
        console.print(
            f"[bold]Combo {idx}:[/bold] [cyan]{anchor.video_id}[/cyan] "
            f"(perf={anchor.performance_score:.1f}, views={anchor.metadata.view_count:,})"
        )

        # Step 1: find best hook segment
        hook_seg = find_rehook_segment(anchor.segments)
        if hook_seg is None:
            console.print("  [yellow]No hook segment — skipping.[/yellow]\n")
            continue

        score = hook_score(hook_seg)
        console.print(
            f"  Hook: {hook_seg.start:.1f}s–{hook_seg.end:.1f}s "
            f"| score={score:.1f} | \"{hook_seg.transcript[:60]}\""
        )

        # Step 2: build remix (b-roll cuts), temp name
        remix_tmp = OUTPUT_DIR / f"{anchor.video_id}_combo_remix_tmp_{idx}.mp4"
        try:
            remix_out = build_remix(anchor, all_videos, idx, global_used_segment_ids)
            if remix_out is None:
                console.print("  [yellow]Remix produced 0 cuts — skipping.[/yellow]\n")
                continue
        except Exception as exc:
            console.print(f"  [red]Remix failed: {exc}[/red]\n")
            continue

        # Step 3: prepend hook to remix
        final_out = OUTPUT_DIR / f"{anchor.video_id}_combo_{idx}.mp4"
        try:
            prepend_hook_to_remix(
                anchor_path=anchor.file_path,
                remix_path=remix_out,
                hook_start=hook_seg.start,
                hook_end=hook_seg.end,
                out_path=final_out,
            )
            # Clean up intermediate remix file
            remix_out.unlink(missing_ok=True)
            output_paths.append(final_out)
            console.print(f"  [green]Saved:[/green] {final_out}\n")
            idx += 1
        except Exception as exc:
            console.print(f"  [red]Combo assembly failed: {exc}[/red]\n")

    console.print(f"[bold green]Done![/bold green] Produced {len(output_paths)} combo(s).")
    for p in output_paths:
        console.print(f"  {p}")


if __name__ == "__main__":
    main()
