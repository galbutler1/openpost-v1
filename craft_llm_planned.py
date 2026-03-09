"""Render videos from LLM-planned edit sequences."""

import json
import random
import subprocess
import shutil
from pathlib import Path

from clipforge.workers.anchor_remixer import load_clip_library

LIBRARY_PATH = Path("output/clip_library.json")
OUTPUT_DIR = Path("output/llm_remixes")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Edit plans from Haiku
plans = [
    {
        "title": "Character Over Money",
        "anchor_id": "C-1Ay8QpmbF_clip001",
        "supplemental_cuts": [
            {"clip_id": "C-8x48op-y8_clip006", "cut_in_at": 2.0, "duration": 2.5},
            {"clip_id": "C70eOWHOWvS_clip003", "cut_in_at": 7.0, "duration": 3.0},
        ],
        "cta_id": "C-1Ay8QpmbF_clip002",
    },
    {
        "title": "From Side Hustles to Startup",
        "anchor_id": "C-veQ69JCBF_clip008",
        "supplemental_cuts": [
            {"clip_id": "C-veQ69JCBF_clip002", "cut_in_at": 1.0, "duration": 1.2},
            {"clip_id": "C-veQ69JCBF_clip005", "cut_in_at": 4.5, "duration": 2.0},
            {"clip_id": "C70eOWHOWvS_clip003", "cut_in_at": 8.0, "duration": 3.0},
        ],
        "cta_id": "C-veQ69JCBF_clip011",
    },
    {
        "title": "What I Invented",
        "anchor_id": "C_BejCxpV04_clip004",
        "supplemental_cuts": [
            {"clip_id": "C7uBpllO5HM_clip001", "cut_in_at": 3.5, "duration": 2.0},
        ],
        "cta_id": "C-d7qToJO1T_clip008",
    },
    {
        "title": "The Problem I Solved",
        "anchor_id": "C7uBpllO5HM_clip002",
        "supplemental_cuts": [
            {"clip_id": "C7uBpllO5HM_clip001", "cut_in_at": 1.5, "duration": 2.0},
            {"clip_id": "C7w1eMUvXLp_clip005", "cut_in_at": 8.0, "duration": 1.5},
        ],
        "cta_id": "C7uBpllO5HM_clip003",
    },
    {
        "title": "Chase and Ambition",
        "anchor_id": "C-a60evpuLH_clip000",
        "supplemental_cuts": [
            {"clip_id": "C-a60evpuLH_clip003", "cut_in_at": 2.0, "duration": 2.0},
            {"clip_id": "C-8x48op-y8_clip006", "cut_in_at": 3.5, "duration": 3.0},
        ],
        "cta_id": "C-d7qToJO1T_clip009",
    },
]


def get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def render_planned_remix(plan: dict, clips: list, output_path: Path, width=720, height=1280):
    """Render a remix from an LLM edit plan.

    The anchor clip's full audio plays uninterrupted.
    At specified times, the video switches to supplemental clips (visual only).
    The anchor video shows whenever supplementals aren't playing.
    CTA is appended at the end with the anchor's music crossfading under it.
    """
    clip_map = {c.id: c for c in clips}
    work_dir = output_path.parent / f"_work_{output_path.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    anchor = clip_map[plan["anchor_id"]]
    anchor_path = Path(anchor.clip_path).resolve()
    anchor_dur = anchor.duration

    # 1. Extract anchor audio (plays the ENTIRE time uninterrupted)
    anchor_audio = (work_dir / "anchor_audio.m4a").resolve()
    subprocess.run([
        "ffmpeg", "-y", "-i", str(anchor_path),
        "-vn", "-c:a", "aac", "-b:a", "192k",
        "-loglevel", "error", str(anchor_audio),
    ], check=True)

    # 2. Build the video timeline
    # Sort supplemental cuts by time
    cuts = sorted(plan["supplemental_cuts"], key=lambda c: c["cut_in_at"])

    # Build segment list: anchor video except where supplementals cut in
    segments = []
    current_time = 0.0

    for cut in cuts:
        cut_start = cut["cut_in_at"]
        cut_dur = cut["duration"]
        cut_end = min(cut_start + cut_dur, anchor_dur)

        # Anchor segment before this cut
        if cut_start > current_time:
            segments.append({
                "type": "anchor",
                "source": anchor_path,
                "start": current_time,
                "duration": cut_start - current_time,
            })

        # Supplemental cut
        supp = clip_map.get(cut["clip_id"])
        if supp and supp.clip_path:
            segments.append({
                "type": "supplemental",
                "source": Path(supp.clip_path).resolve(),
                "start": 0.0,  # start from beginning of supplemental
                "duration": cut_end - cut_start,
            })
        current_time = cut_end

    # Remaining anchor after last cut
    if current_time < anchor_dur:
        segments.append({
            "type": "anchor",
            "source": anchor_path,
            "start": current_time,
            "duration": anchor_dur - current_time,
        })

    # 3. Render each video segment (muted — audio comes from anchor)
    seg_paths = []
    for i, seg in enumerate(segments):
        seg_path = (work_dir / f"seg_{i:03d}.mp4").resolve()
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(seg["start"]),
            "-i", str(seg["source"]),
            "-t", str(seg["duration"]),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-an", "-c:v", "libx264", "-r", "30",
            "-loglevel", "error", str(seg_path),
        ], check=True)
        seg_paths.append(seg_path)

    # 4. Concatenate video segments
    concat_file = (work_dir / "concat.txt").resolve()
    with open(concat_file, "w") as f:
        for sp in seg_paths:
            f.write(f"file '{sp}'\n")

    video_track = (work_dir / "video_track.mp4").resolve()
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264", "-loglevel", "error", str(video_track),
    ], check=True)

    # 5. Merge video + anchor audio
    main_part = (work_dir / "main.mp4").resolve()
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_track),
        "-i", str(anchor_audio),
        "-c:v", "copy", "-c:a", "aac",
        "-shortest", "-movflags", "+faststart",
        "-loglevel", "error", str(main_part),
    ], check=True)

    # 6. Append CTA (with anchor music fading underneath)
    cta_clip = clip_map.get(plan.get("cta_id"))
    if cta_clip and cta_clip.clip_path:
        cta_path = Path(cta_clip.clip_path).resolve()
        cta_norm = (work_dir / "cta_norm.mp4").resolve()
        subprocess.run([
            "ffmpeg", "-y", "-i", str(cta_path),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-r", "30",
            "-loglevel", "error", str(cta_norm),
        ], check=True)

        # Re-encode main to match
        main_re = (work_dir / "main_re.mp4").resolve()
        subprocess.run([
            "ffmpeg", "-y", "-i", str(main_part),
            "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-r", "30",
            "-loglevel", "error", str(main_re),
        ], check=True)

        final_concat = (work_dir / "final_concat.txt").resolve()
        with open(final_concat, "w") as f:
            f.write(f"file '{main_re}'\n")
            f.write(f"file '{cta_norm}'\n")

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(final_concat),
            "-c:v", "libx264", "-c:a", "aac",
            "-movflags", "+faststart",
            "-loglevel", "error", str(output_path.resolve()),
        ], check=True)
    else:
        shutil.copy2(main_part, output_path.resolve())

    # Cleanup
    shutil.rmtree(work_dir, ignore_errors=True)
    return output_path


if __name__ == "__main__":
    clips = load_clip_library(LIBRARY_PATH)

    for i, plan in enumerate(plans):
        print(f"\n=== {i+1}. {plan['title']} ===")
        print(f"  Anchor: {plan['anchor_id']}")
        print(f"  Supplementals: {len(plan['supplemental_cuts'])} cuts")
        print(f"  CTA: {plan.get('cta_id')}")

        out = OUTPUT_DIR / f"llm_{i:02d}_{plan['title'].lower().replace(' ', '_')}.mp4"
        try:
            render_planned_remix(plan, clips, out)
            dur = get_duration(out.resolve())
            print(f"  ✓ {out.name} ({dur:.1f}s)")
        except Exception as e:
            print(f"  ✗ Failed: {e}")

    print(f"\n=== Done! ===")
