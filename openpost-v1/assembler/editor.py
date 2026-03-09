"""
editor.py — ffmpeg-based video assembly.

Anchor audio plays 100% unmodified from start to finish.
At each cutaway window the video stream is replaced with b-roll.

ffmpeg filter_complex approach:
  - Pre-split the anchor video stream into N labeled copies (one per trim operation).
    Without this, referencing [0:v] multiple times in filter_complex is undefined behavior.
  - Each anchor piece is trimmed from its labeled copy.
  - Each b-roll piece is trimmed from its actual start/end position in the source file.
  - All pieces are concatenated into [vout].
  - Anchor audio stream [0:a] maps directly to output — never touched.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from models import CutawayWindow, RemixPlan, Segment
from config import OUTPUT_DIR


def _get_video_dimensions(video_path: str) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True,
    )
    parts = result.stdout.strip().split(",")
    return int(parts[0]), int(parts[1])


def _get_video_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def assemble_remix(
    plan: RemixPlan,
    remix_index: int,
    video_lookup: dict[str, str] | None = None,
) -> Path:
    anchor = plan.anchor_video
    anchor_path = anchor.file_path
    video_lookup = video_lookup or {}

    output_path = OUTPUT_DIR / f"{anchor.video_id}_remix_{remix_index}.mp4"

    matched_windows: list[tuple[CutawayWindow, Segment]] = [
        (w, seg) for w, seg in plan.windows if seg is not None
    ]

    if not matched_windows:
        subprocess.run(
            ["ffmpeg", "-y", "-i", anchor_path, "-c", "copy", str(output_path)],
            check=True, capture_output=True,
        )
        return output_path

    matched_windows.sort(key=lambda x: x[0].beat_snapped_start)

    try:
        anchor_w, anchor_h = _get_video_dimensions(anchor_path)
    except Exception:
        anchor_w, anchor_h = 1080, 1920

    anchor_duration = _get_video_duration(anchor_path)

    # -----------------------------------------------------------------------
    # Plan the pieces we need
    # Each "piece" is either:
    #   ("anchor", start, end)  — a slice of the anchor video
    #   ("broll",  input_idx, seg_start, effective_duration)  — a b-roll slice
    # -----------------------------------------------------------------------
    pieces: list[dict] = []
    prev_end = 0.0

    # Build input list: input 0 = anchor, 1..N = b-roll files
    # (same file may appear multiple times if multiple windows use same source video — that's fine)
    inputs: list[str] = ["-i", anchor_path]

    MIN_CLIP = 1.5  # nothing — anchor or b-roll — may be shorter than this

    for w, seg in matched_windows:
        # Clamp beat-snapped start to window boundaries
        win_start = max(prev_end, min(w.beat_snapped_start, w.end - MIN_CLIP))
        effective_dur = min(w.duration, seg.duration, w.end - win_start)

        # Skip if b-roll clip would be too short
        if effective_dur < MIN_CLIP:
            continue

        # Skip if the anchor piece leading into this cut would be too short
        anchor_gap = win_start - prev_end
        if 0 < anchor_gap < MIN_CLIP:
            continue

        # Skip if the remaining anchor after this cut would be too short
        remaining = anchor_duration - (win_start + effective_dur)
        if 0 < remaining < MIN_CLIP:
            continue

        # Anchor piece before this window
        if anchor_gap > 0.02:
            pieces.append({"type": "anchor", "start": prev_end, "end": win_start})

        # B-roll piece
        broll_path = video_lookup.get(seg.source_video_id, "")
        if not broll_path:
            raise RuntimeError(f"No file path for source_video_id {seg.source_video_id}")
        inputs += ["-i", broll_path]
        broll_input_idx = len(inputs) // 2 - 1

        pieces.append({
            "type": "broll",
            "input_idx": broll_input_idx,
            "seg_start": seg.start,
            "duration": effective_dur,
        })

        prev_end = win_start + effective_dur

    # Final anchor piece (only if long enough)
    if anchor_duration - prev_end >= MIN_CLIP:
        pieces.append({"type": "anchor", "start": prev_end, "end": anchor_duration})

    # -----------------------------------------------------------------------
    # Count how many times we need to read from the anchor video stream
    # and pre-split it that many times to avoid reuse of the same stream label
    # -----------------------------------------------------------------------
    n_anchor_reads = sum(1 for p in pieces if p["type"] == "anchor")

    filter_parts: list[str] = []
    concat_labels: list[str] = []

    # Split anchor video stream up front
    if n_anchor_reads > 1:
        split_labels = "".join(f"[anch{i}]" for i in range(n_anchor_reads))
        filter_parts.append(f"[0:v]split={n_anchor_reads}{split_labels}")
    elif n_anchor_reads == 1:
        filter_parts.append(f"[0:v]split=1[anch0]")

    anchor_read_idx = 0

    for piece_idx, piece in enumerate(pieces):
        if piece["type"] == "anchor":
            label = f"[av{piece_idx}]"
            filter_parts.append(
                f"[anch{anchor_read_idx}]"
                f"trim=start={piece['start']:.6f}:end={piece['end']:.6f},"
                f"setpts=PTS-STARTPTS"
                f"{label}"
            )
            concat_labels.append(label)
            anchor_read_idx += 1

        else:  # broll
            label = f"[bv{piece_idx}]"
            filter_parts.append(
                f"[{piece['input_idx']}:v]"
                f"trim=start={piece['seg_start']:.6f}:duration={piece['duration']:.6f},"
                f"setpts=PTS-STARTPTS,"
                f"scale={anchor_w}:{anchor_h}:force_original_aspect_ratio=decrease,"
                f"pad={anchor_w}:{anchor_h}:(ow-iw)/2:(oh-ih)/2"
                f"{label}"
            )
            concat_labels.append(label)

    # Concatenate all pieces
    n_pieces = len(concat_labels)
    filter_parts.append(
        "".join(concat_labels) + f"concat=n={n_pieces}:v=1:a=0[vout]"
    )

    filter_complex = "; ".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",       # anchor audio, unmodified
            "-c:v", "libx264",
            "-profile:v", "high",
            "-level", "4.0",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",   # required for iOS Camera Roll import
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",  # metadata at front for smooth playback
            "-shortest",
            str(output_path),
        ]
    )

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace")
        raise RuntimeError(
            f"ffmpeg assembly failed for {output_path.name}:\n{stderr[-3000:]}"
        ) from exc

    return output_path
