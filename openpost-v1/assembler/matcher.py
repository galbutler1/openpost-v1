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

import random
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


# ── Product sub-type context hints ────────────────────────────────────────────
# When the anchor is talking about specific aspects, prefer matching visual type.
# These are applied as soft score boosts, not hard filters.

_SUBTYPE_HINTS: dict[str, set[str]] = {
    "product-demo-feature": {
        "fold", "flat", "hinge", "collapse", "compact", "space", "saves",
        "design", "patent", "magnet", "feature", "works", "mechanism",
        "manufactured", "manufacturing", "quality", "material", "built",
    },
    "product-demo-use-case": {
        "dishwasher", "wash", "meal", "food", "eat", "eating", "use",
        "store", "storage", "kitchen", "cook", "cooking", "normal",
        "everyday", "fits", "drawer", "cabinet",
    },
    "product-in-hand": {
        "hold", "holding", "hand", "grab", "show", "here it is", "look at",
        "this is it", "invented", "invention", "feel", "touch",
    },
    "product-close-up": {
        "detail", "close", "look closely", "you can see", "quality",
        "material", "texture", "inspect",
    },
    "product-comparison": {
        "compare", "versus", "vs", "normal bowl", "regular", "difference",
        "side by side", "other bowls", "unlike",
    },
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
    """Base visual quality score for a clip."""
    reu = {"high": 100, "medium": 60, "low": 20, "none": 0}.get(seg.reusability.value, 20)
    return seg.quality_score * 0.6 + reu * 0.4


def _subtype_boost(seg: Segment, anchor_transcript: str) -> float:
    """
    Bonus multiplier when a clip's visual type closely matches what the anchor
    is specifically describing at this moment.
    e.g. anchor says "fold flat" → boost product-demo-feature clips.
    Returns 1.0 (no change) to 1.5 (strong match).
    """
    vt = seg.visual_type.value
    hints = _SUBTYPE_HINTS.get(vt)
    if not hints:
        return 1.0
    t = anchor_transcript.lower()
    hits = sum(1 for kw in hints if kw in t)
    return 1.0 + min(hits * 0.15, 0.5)


def find_match(
    window: CutawayWindow,
    anchor_segment: Segment,
    anchor_video_id: str,
    all_videos: list[Video],
    used_segment_ids: set[str] | None = None,
    used_source_video_ids: set[str] | None = None,
    video_topic: str | None = None,
    last_visual_type: str | None = None,
) -> Optional[Segment]:
    """
    Find a b-roll clip matching the anchor's topic.

    Selection is weighted-random from the top candidates so different
    runs and windows produce variety rather than always the same top clip.

    Topic resolution:
      1. Segment-level topic (what this specific 2-second window says) — primary.
         If the segment itself has clear keywords (score >= 1), always use that.
      2. Video-level topic (full transcript) — fallback ONLY when the segment
         has zero keyword signal on its own.

    Scoring factors:
      - Base quality (_clip_quality)
      - Sub-type context boost (_subtype_boost): prefers clips whose visual type
        matches what the anchor is literally describing
      - Variety penalty: down-weights clips matching the last-used visual type
        to avoid repetitive back-to-back same-type cuts
    """
    used_ids        = used_segment_ids       or set()
    used_source_ids = used_source_video_ids  or set()

    seg_scores = topic_scores(anchor_segment.transcript)
    seg_best   = max(seg_scores, key=seg_scores.get)
    seg_score  = seg_scores[seg_best]

    if video_topic == "product":
        topic = "product"
    elif seg_score >= 1:
        topic = seg_best
    elif video_topic is not None:
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
        for seg in video.segments:
            if seg.segment_id in used_ids:
                continue
            # "Quick Story" text-overlay segment — baked-in text ruins the cut
            if seg.segment_id == "44c90259-ccab-45af-9b47-c9a4f8c4859d":
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

    # ── Composite score: quality × context relevance × variety ───────────────
    def score(seg: Segment) -> float:
        base = _clip_quality(seg)
        ctx  = _subtype_boost(seg, anchor_segment.transcript)
        # Down-weight if same visual type as the previous cut (reduce grouping)
        variety = 0.6 if (last_visual_type and seg.visual_type.value == last_visual_type) else 1.0
        return base * ctx * variety

    matches.sort(key=score, reverse=True)

    # Weighted-random pick from top candidates — high scores preferred but not
    # guaranteed, so different windows and runs produce different clips.
    top_n = min(8, len(matches))
    top   = matches[:top_n]
    weights = [max(score(s), 0.01) ** 2 for s in top]
    return random.choices(top, weights=weights, k=1)[0]
