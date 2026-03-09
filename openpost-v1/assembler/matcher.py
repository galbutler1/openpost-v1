"""
matcher.py — Topic-driven b-roll matching.

Rule: b-roll only plays when the clip's visual content specifically matches
what the anchor creator is talking about at that moment.

  anchor says "product/invention"  → show product footage
  anchor says "journey/struggle"   → show outdoor/lifestyle footage
  anchor says "success/revenue"    → show success/celebration footage
  anchor says "work/building"      → show workspace/working footage

If no clip matches the topic → return None (stay on anchor).
Never insert an off-topic clip just to fill a window.
"""

from __future__ import annotations

import re
from typing import Optional

from models import CutawayWindow, Segment, Video


# ── What visual types belong to each topic ───────────────────────────────────

TOPIC_VISUAL_TYPES: dict[str, set[str]] = {
    "product": {
        "product-demo-feature", "product-demo-use-case",
        "product-in-hand", "product-close-up", "product-comparison",
    },
    "work": {
        "working", "workspace", "packaging",
    },
    "journey": {
        "outdoor", "lifestyle", "travel", "event",
    },
    "success": {
        "celebrating", "founder-talking-excited",
    },
    "emotion": {
        "founder-reacting", "founder-laughing", "founder-sad",
    },
}


# ── Keyword sets ─────────────────────────────────────────────────────────────
# Single-word cues use word-boundary matching to avoid false positives
# e.g. "product" must NOT match "production", "sell" must NOT match "seller"

_PRODUCT_WORDS = {
    "product", "invention", "invented", "bowl", "magnet", "hinge",
    "prototype", "design", "launch", "sell", "sold", "ship", "order",
    "buy", "manufacture", "manufactured", "manufacturing", "patent",
    "trademark", "knockoff",
}
_PRODUCT_PHRASES = {
    "built this", "made this", "created this", "space saving",
    "my product", "my invention", "my idea", "our product", "this thing",
    "i invented", "we invented",
}

_WORK_WORDS = {
    "working", "building", "grinding", "packing", "sending", "hustle",
    "creating", "manufacturing", "warehouse", "factory",
}
_WORK_PHRASES = {
    "my office", "my desk", "my workspace",
}

_JOURNEY_WORDS = {
    "journey", "story", "struggle", "struggled", "quit", "dream",
    "goal", "mission", "vision", "challenge", "beginning", "started",
    "remember",
}
_JOURNEY_PHRASES = {
    "almost quit", "year ago", "years ago", "when i was", "looking back",
    "grew up", "wild ride", "been a wild", "wild journey",
}

_SUCCESS_WORDS = {
    "million", "revenue", "milestone", "viral", "accomplished", "proud",
    "incredible", "unbelievable",
}
_SUCCESS_PHRASES = {
    "sold out", "blew up", "took off", "made it", "record breaking",
    "went viral",
}

_EMOTION_WORDS = {
    "emotional", "overwhelmed", "scared", "grateful",
}
_EMOTION_PHRASES = {
    "real talk", "to be honest", "i cried", "didn't expect",
    "broke down", "confession",
}


def _match_words(text: str, words: set[str]) -> int:
    """Count word matches, allowing common suffixes (plurals, -ed, -ing)."""
    return sum(
        1 for w in words
        if re.search(r'\b' + re.escape(w) + r'(s|ed|ing|er|ly)?\b', text)
    )


def _match_phrases(text: str, phrases: set[str]) -> int:
    """Count phrase matches (substring)."""
    return sum(1 for p in phrases if p in text)


def topic_scores(transcript: str) -> dict[str, float]:
    """Return a score for each topic. Score 0 = no evidence."""
    t = transcript.lower()
    return {
        "product": _match_words(t, _PRODUCT_WORDS) + _match_phrases(t, _PRODUCT_PHRASES),
        "work":    _match_words(t, _WORK_WORDS)    + _match_phrases(t, _WORK_PHRASES),
        "journey": _match_words(t, _JOURNEY_WORDS) + _match_phrases(t, _JOURNEY_PHRASES),
        "success": _match_words(t, _SUCCESS_WORDS) + _match_phrases(t, _SUCCESS_PHRASES),
        "emotion": _match_words(t, _EMOTION_WORDS) + _match_phrases(t, _EMOTION_PHRASES),
    }


def classify_topic(transcript: str) -> Optional[str]:
    """
    Return the dominant topic, or None if no clear signal.
    Classify from the full text provided — caller should pass full video
    transcript for best results, not just a 2-second segment snippet.
    """
    scores = topic_scores(transcript)
    best = max(scores, key=scores.get)
    return best if scores[best] >= 1 else None


def broll_compatibility_score(full_transcript: str, body_segment_count: int) -> float:
    """
    How compatible is this video as an anchor for b-roll insertion?
    Returns a score 0–100. Used to rank anchors before attempting remixes.
    """
    scores = topic_scores(full_transcript)
    best_score = max(scores.values())
    # Topic signal strength (0–50) + body segment count bonus (0–50)
    topic_signal = min(best_score * 5, 50)
    segment_bonus = min(body_segment_count * 5, 50)
    return round(topic_signal + segment_bonus, 1)


def _clip_quality(seg: Segment) -> float:
    """Rank matching clips by visual quality."""
    reu = {"high": 100, "medium": 60, "low": 20, "none": 0}.get(seg.reusability.value, 20)
    return seg.quality_score * 0.6 + reu * 0.4


def find_match(
    window: CutawayWindow,
    anchor_segment: Segment,
    anchor_video_id: str,
    all_videos: list[Video],
    used_segment_ids: set[str] | None = None,
    used_source_video_ids: set[str] | None = None,
    video_topic: str | None = None,
) -> Optional[Segment]:
    """
    Find a b-roll clip matching the anchor's topic.

    Topic resolution:
      1. Segment-level topic (what this specific 2-second window says) — primary.
         If the segment itself has clear keywords (score >= 1), always use that.
      2. Video-level topic (full transcript) — fallback ONLY when the segment
         has zero keyword signal on its own. This gets b-roll into segments like
         "Suitable for the best meal in the world" that clearly show the product
         but don't use the word "product".

    This prevents journey/outdoor clips bleeding into product-focused windows
    just because the video mentions "journey" somewhere else.
    """
    used_ids        = used_segment_ids       or set()
    used_source_ids = used_source_video_ids  or set()

    seg_scores = topic_scores(anchor_segment.transcript)
    seg_best   = max(seg_scores, key=seg_scores.get)
    seg_score  = seg_scores[seg_best]

    if video_topic == "product":
        # Product videos: always show product b-roll only.
        # Never let a passing "story" or "journey" word trigger outdoor clips.
        topic = "product"
    elif seg_score >= 1:
        # Non-product video: trust the segment's own topic signal
        topic = seg_best
    elif video_topic is not None:
        # Segment is ambiguous — fall back to video-level topic
        topic = video_topic
    else:
        return None

    valid_visual_types = TOPIC_VISUAL_TYPES[topic]

    matches: list[Segment] = []
    for video in all_videos:
        if video.video_id == anchor_video_id:
            continue
        if video.video_id in used_source_ids:
            continue
        # "Quick Story" video — never use as b-roll, text baked into the frame
        if video.video_id == "C8DYloWp_7r":
            continue
        # Egg-basket metaphor video — falling/outdoor clips make no sense as b-roll
        if video.video_id == "DB_--pIOLs3":
            continue
        for seg in video.segments:
            if seg.segment_id in used_ids:
                continue
            if seg.zone.value in ("hook", "cta"):
                continue
            if seg.duration < 1.5:
                continue
            if seg.quality_score < 20:
                continue
            if seg.visual_type.value in valid_visual_types:
                matches.append(seg)

    if not matches:
        return None

    matches.sort(key=_clip_quality, reverse=True)
    return matches[0]
