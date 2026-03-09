"""
anchor.py — Anchor video selection logic.
"""

from __future__ import annotations

from models import Video


def select_anchors(videos: list[Video], n_remixes: int) -> list[Video]:
    """
    Return up to *n_remixes* anchor candidates, sorted by performance_score desc.

    Eligibility: video must have at least one body segment with:
      - context_type == "vague"  AND  context_type.confidence >= 75

    If a selected anchor has performance_score < 50 a warning string is included
    in the returned list's accompanying warnings (caller handles printing).
    """
    eligible = []
    for v in videos:
        # Any video with at least one body segment >= 1.5s is eligible as an anchor
        has_eligible_body = any(
            seg.zone.value == "body" and seg.duration >= 1.5
            for seg in v.segments
        )
        if has_eligible_body:
            eligible.append(v)

    # Sort descending by performance_score
    eligible.sort(key=lambda v: v.performance_score, reverse=True)

    return eligible[:n_remixes]


def warn_low_performance(anchors: list[Video]) -> list[str]:
    """Return warning messages for anchors with performance_score < 50."""
    warnings = []
    for v in anchors:
        if v.performance_score < 50:
            warnings.append(
                f"[WARNING] Anchor '{v.video_id}' has performance_score "
                f"{v.performance_score:.1f} < 50. Proceeding anyway."
            )
    return warnings
