"""
merger.py — Validate and clean the raw segment list from the tagger.
"""

from __future__ import annotations

from models import Segment, TagValue
from pipeline.tagger import compute_broll_score


# Tolerance for floating-point boundary checks
_GAP_TOLERANCE = 0.05  # seconds


def _merge_two(a: Segment, b: Segment) -> Segment:
    """Merge segment *b* into *a* (extend a's end to b's end)."""
    merged = a.model_copy(deep=True)
    merged.end = b.end
    merged.duration = round(merged.end - merged.start, 3)
    if b.transcript:
        merged.transcript = (
            f"{merged.transcript} {b.transcript}".strip()
        )
    return merged


def merge_segments(
    segments: list[Segment],
    video_duration: float,
) -> list[Segment]:
    """
    Post-process raw tagger output:

    1. Sort by start time.
    2. Fill any gap between segments by extending the preceding segment.
    3. Clamp last segment to video_duration.
    4. Merge segments shorter than 1 second into the adjacent segment
       (prefer previous; if first segment, merge forward).
    5. Recompute broll_likelihood_score for any merged segment.

    Returns the final clean segment list.
    """
    if not segments:
        return []

    segs = sorted(segments, key=lambda s: s.start)

    # --- Step 1: fix gaps -----------------------------------------------
    fixed: list[Segment] = [segs[0]]
    for s in segs[1:]:
        prev = fixed[-1]
        gap = s.start - prev.end
        if gap > _GAP_TOLERANCE:
            # Extend previous segment to cover the gap
            prev_copy = prev.model_copy(deep=True)
            prev_copy.end = s.start
            prev_copy.duration = round(prev_copy.end - prev_copy.start, 3)
            fixed[-1] = prev_copy
        elif gap < -_GAP_TOLERANCE:
            # Overlap: trim current segment start
            s_copy = s.model_copy(deep=True)
            s_copy.start = prev.end
            s_copy.duration = round(s_copy.end - s_copy.start, 3)
            if s_copy.duration <= 0:
                continue  # Fully overlapped; skip
            s = s_copy
        fixed.append(s)

    # Clamp last segment to video_duration
    if video_duration > 0:
        last = fixed[-1]
        if abs(last.end - video_duration) > _GAP_TOLERANCE or last.end > video_duration:
            last_copy = last.model_copy(deep=True)
            last_copy.end = video_duration
            last_copy.duration = round(last_copy.end - last_copy.start, 3)
            fixed[-1] = last_copy

    # --- Step 2: merge sub-second segments ------------------------------
    changed = True
    while changed:
        changed = False
        result: list[Segment] = []
        i = 0
        while i < len(fixed):
            seg = fixed[i]
            if seg.duration < 1.0 - _GAP_TOLERANCE:
                if result:
                    # Merge backward (into previous)
                    merged = _merge_two(result[-1], seg)
                    result[-1] = merged
                elif i + 1 < len(fixed):
                    # Merge forward (into next)
                    merged = _merge_two(seg, fixed[i + 1])
                    result.append(merged)
                    i += 2
                    changed = True
                    continue
                else:
                    # Only one segment and it's < 1s — keep as-is
                    result.append(seg)
                changed = True
            else:
                result.append(seg)
            i += 1
        fixed = result

    # --- Step 3: recompute scores for merged segments -------------------
    final: list[Segment] = []
    for seg in fixed:
        seg = seg.model_copy(deep=True)
        # Enforce sub-second rule after all merging
        if seg.duration < 1.0:
            seg.reusability = TagValue(value="none", confidence=100)
        seg.broll_likelihood_score = compute_broll_score(seg)
        final.append(seg)

    return final
