"""
windows.py — Cutaway window detection + beat snapping.

Every body segment >= MIN_BROLL_CUT is a potential window.
The matcher decides whether relevant b-roll exists — if not, the window is skipped.
No scoring gates here.
"""

from __future__ import annotations

from models import CutawayWindow, Segment

MAX_BROLL_CUT = 2.0
MIN_BROLL_CUT = 1.5


def _snap_to_beat(t: float, beats: list[float]) -> float:
    if not beats:
        return t
    return min(beats, key=lambda b: abs(b - t))


def _split_into_cuts(seg: Segment, beats: list[float]) -> list[CutawayWindow]:
    cuts: list[CutawayWindow] = []
    cursor = seg.start

    while cursor < seg.end - MIN_BROLL_CUT:
        cut_end = min(cursor + MAX_BROLL_CUT, seg.end)
        cut_dur = round(cut_end - cursor, 3)
        if cut_dur < MIN_BROLL_CUT:
            break
        cuts.append(CutawayWindow(
            start=cursor,
            end=cut_end,
            duration=cut_dur,
            beat_snapped_start=_snap_to_beat(cursor, beats),
            anchor_segment_id=seg.segment_id,
        ))
        cursor = cut_end

    return cuts


def detect_windows(segments: list[Segment], beats: list[float]) -> list[CutawayWindow]:
    """
    Return all body segments as potential cutaway windows.
    Relevance filtering happens in the matcher, not here.
    """
    windows: list[CutawayWindow] = []
    for seg in segments:
        if seg.zone.value != "body":
            continue
        if seg.duration < MIN_BROLL_CUT:
            continue
        windows.extend(_split_into_cuts(seg, beats))
    windows.sort(key=lambda w: w.start)
    return windows
