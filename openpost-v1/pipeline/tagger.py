"""
tagger.py — GPT-4o full-video tagging + local score computation.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from openai import OpenAI

import config
from models import Segment, TagValue


# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

def compute_quality_score(video_path: str, start: float, end: float) -> float:
    path = Path(video_path)
    if not path.exists():
        return 50.0

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 50.0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = max(end - start, 0.1)
    n_samples = min(5, max(1, int(duration * fps // max(fps // 5, 1))))

    laps: list[float] = []
    brights: list[float] = []

    for i in range(n_samples):
        t = start + (duration / n_samples) * (i + 0.5)
        frame_num = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        laps.append(cv2.Laplacian(gray, cv2.CV_64F).var())
        brights.append(float(gray.mean()))

    cap.release()

    if not laps:
        return 50.0

    sharpness = min(float(np.mean(laps)) / 1000.0, 1.0) * 100.0
    avg_bright = float(np.mean(brights))
    brightness = max(0.0, 1.0 - abs(avg_bright - 130.0) / 130.0) * 100.0
    return round(min(max(sharpness * 0.6 + brightness * 0.4, 0.0), 100.0), 1)


def compute_broll_score(seg: Segment) -> float:
    """
    Composite b-roll likelihood score.

    Weights (must sum to 1.0):
      narrative_broll_fit  0.35  — largest: does b-roll make narrative sense here?
      context_type         0.20  — is the dialogue vague enough to cut away?
      reusability          0.15  — is this clip reusable as b-roll?
      quality_score        0.15  — visual quality
      performance_score    0.10  — source video performance
      sentiment            0.05  — emotional tone match signal
    """
    nbf_val  = float(seg.narrative_broll_fit.value) if seg.narrative_broll_fit.value.replace('.','').isdigit() else 50.0
    nbf_conf = seg.narrative_broll_fit.confidence / 100

    ctx_conf = seg.context_type.confidence / 100
    reu_conf = seg.reusability.confidence / 100
    sen_conf = seg.sentiment.confidence / 100

    ctx_score = {"vague": 100, "ambiguous": 30, "specific": 0, "none": 0}.get(seg.context_type.value, 0)
    reu_score = {"high": 100, "medium": 60, "low": 20, "none": 0}.get(seg.reusability.value, 0)
    sen_score = {"positive": 100, "neutral": 70, "mixed": 50, "negative": 30}.get(seg.sentiment.value, 70)

    numerator = (
        nbf_val             * 0.35 * nbf_conf
        + ctx_score         * 0.20 * ctx_conf
        + reu_score         * 0.15 * reu_conf
        + seg.quality_score * 0.15
        + seg.performance_score * 0.10
        + sen_score         * 0.05 * sen_conf
    )
    denominator = (
        0.35 * nbf_conf
        + 0.20 * ctx_conf
        + 0.15 * reu_conf
        + 0.25                     # quality + performance (no confidence)
        + 0.05 * sen_conf
    )

    if denominator <= 0:
        return 0.0
    return round(min(numerator / denominator, 100.0), 1)


# ---------------------------------------------------------------------------
# GPT-4o prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert video content analyst for short-form social media reels.

You will receive:
  1. The FULL VIDEO TRANSCRIPT (plain text) — read this first to understand the overall narrative
  2. A word-level transcript with timestamps
  3. A frame-label timeline (visual_type sampled every 2 seconds)
  4. The total video duration

Your task has two parts:

═══════════════════════════════════════════════
PART 1 — NARRATIVE ANALYSIS (internal reasoning)
═══════════════════════════════════════════════
Before producing any segments, understand the video at a high level:
- What TYPE of video is this? (personal encounter, product demo, founder story, milestone announcement, street interview, general motivation, etc.)
- What is the creator ACTUALLY talking about?
- Is this a moment where inserting b-roll footage would feel natural and additive to a viewer — or would it feel jarring, fake, or wrong?

Examples of when b-roll FITS:
  - Creator talking about their product journey, struggles, milestones → b-roll of product/workspace/founder fits
  - General motivational content, "I almost quit" → b-roll of founder working/struggling fits
  - Describing a process or result → b-roll of that process fits

Examples of when b-roll DOES NOT FIT:
  - Creator is in a real-world encounter ("yo I love your recent video") → no b-roll, it's an authentic moment
  - Creator is directly reacting to something happening on screen → keep original
  - Raw emotional confession directly into camera → b-roll would feel dishonest
  - Short punchy hook designed for pattern interrupt → don't break the moment

═══════════════════════════════════════════════
PART 2 — SEGMENT-LEVEL TAGGING
═══════════════════════════════════════════════
Produce a segmented timeline. A new segment starts when ANY tag changes.
Minimum 1 second per segment. Every second must be covered. Last segment ends at video_duration exactly.

IMPORTANT — keep segments SHORT and PRECISE:
- Aim for 2-5 second segments wherever content shifts even slightly.
- Do NOT lump 10-15 seconds into one segment unless the content is truly identical throughout.
- Tight segments = precise window boundaries = better b-roll cut timing.
- When the creator shifts from one topic/tone/context to another, start a new segment immediately.

For each segment assign ALL of these tags:

ZONE:
  hook  — opening grab, starts at 0.0. Default to first 3s if unclear.
  body  — everything between hook and CTA.
  cta   — closing ask. Default to last 5s if unclear. Signs: "follow", "link in bio", "comment", any direct ask.
  NOTE: If hook_end >= cta_start (short video), hook covers from 0:00, cta follows immediately, no body.

CONTEXT_TYPE:
  specific  — transcript references something only visible in this video ("this", "here", "look at", visible features, instructions requiring sight)
  vague     — could appear in any creator's video; makes sense as audio-only
  ambiguous — unclear
  none      — no speech

NARRATIVE_BROLL_FIT — integer 0-100:
  This is the most important tag. Based on your PART 1 narrative analysis:
  - 80-100: B-roll would clearly enhance this moment. The content is about something demonstrable, a journey, a product, a struggle — footage would add visual richness without breaking meaning.
  - 50-79:  B-roll might work. Content is general/motivational but not a perfect fit.
  - 20-49:  B-roll would feel awkward. Content is somewhat personal or contextual.
  - 0-19:   B-roll would feel wrong. This is a raw personal moment, real encounter, direct camera confession, or specific visual reference — cutting away would damage authenticity or lose meaning.

VISUAL_TYPE (single label):
  Presenter: founder-talking-neutral, founder-talking-excited, founder-talking-serious,
             founder-laughing, founder-sad, founder-mad, founder-thinking, founder-reacting
  Product:   product-in-hand, product-demo-feature, product-demo-use-case, product-close-up, product-comparison
  Environment: workspace, outdoor, lifestyle, event, travel
  Action:    working, celebrating, packaging, on-phone
  Production: text-overlay-only, blank-space, b-roll-cutaway, screen-recording, split-screen
  Fallback:  visual-type-unknown

ENERGY:
  high — fast, loud, emphatic, dynamic
  medium — normal conversational pace
  low — slow, quiet, deliberate, emotional
  silent — no speech, music only

REUSABILITY:
  high   — visually compelling, no specific references, works in any context
  medium — usable but somewhat context-dependent
  low    — too specific or low quality
  none   — blank space, transition, screen-recording, under 1s

SENTIMENT:
  positive, negative, neutral, mixed

FACE_VISIBLE: true / false
PRODUCT_IN_SHOT: true / false

Confidence: integer 0-100 reflecting your certainty.

Output FORMAT — respond with ONLY a valid JSON array (no markdown fences):
[
  {
    "start": <float>,
    "end": <float>,
    "transcript": "<words in this time range, or empty string>",
    "zone":                 {"value": "<zone>",         "confidence": <int>},
    "context_type":         {"value": "<type>",         "confidence": <int>},
    "narrative_broll_fit":  {"value": "<0-100>",        "confidence": <int>},
    "visual_type":          {"value": "<type>",         "confidence": <int>},
    "energy":               {"value": "<energy>",       "confidence": <int>},
    "reusability":          {"value": "<reusability>",  "confidence": <int>},
    "sentiment":            {"value": "<sentiment>",    "confidence": <int>},
    "face_visible":         {"value": <bool>,           "confidence": <int>},
    "product_in_shot":      {"value": <bool>,           "confidence": <int>}
  },
  ...
]
"""


def _build_full_transcript(word_timestamps: list[dict]) -> str:
    return " ".join(w["word"] for w in word_timestamps) if word_timestamps else "(no speech)"


def _build_user_prompt(
    word_timestamps: list[dict],
    frame_labels: list[dict],
    beat_timestamps: list[float],
    video_duration: float,
) -> str:
    full_transcript = _build_full_transcript(word_timestamps)

    transcript_lines = [
        f"  [{w['start']:.2f}-{w['end']:.2f}] {w['word']}"
        for w in word_timestamps
    ] or ["  (no speech detected)"]

    frame_lines = [
        f"  t={fl['timestamp']:.1f}s → {fl['visual_type']} (conf={fl['confidence']})"
        for fl in frame_labels
    ] or ["  (no frames)"]

    beats_str = (
        ", ".join(f"{b:.2f}s" for b in beat_timestamps[:40])
        if beat_timestamps else "none detected"
    )

    return (
        f"VIDEO DURATION: {video_duration:.2f} seconds\n\n"
        f"FULL TRANSCRIPT (read this first for narrative context):\n{full_transcript}\n\n"
        f"WORD-LEVEL TRANSCRIPT WITH TIMESTAMPS:\n" + "\n".join(transcript_lines) + "\n\n"
        f"FRAME LABEL TIMELINE (every 2s):\n" + "\n".join(frame_lines) + "\n\n"
        f"BEAT TIMESTAMPS: {beats_str}\n\n"
        "Now produce the full segmented timeline as a JSON array."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tag_video(
    video_id: str,
    video_path: str,
    word_timestamps: list[dict],
    frame_labels: list[dict],
    beat_timestamps: list[float],
    video_duration: float,
    performance_score: float,
) -> tuple[list[Segment], str]:
    """
    Tag the full video with GPT-4o, compute local scores.
    Returns (segments, full_transcript).
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    full_transcript = _build_full_transcript(word_timestamps)
    user_prompt = _build_user_prompt(word_timestamps, frame_labels, beat_timestamps, video_duration)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=8192,
        temperature=0,
    )

    raw = (response.choices[0].message.content or "[]").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        raw_segments: list[dict] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"GPT-4o returned invalid JSON for {video_id}: {exc}\nRaw: {raw[:500]}"
        ) from exc

    segments: list[Segment] = []

    for raw_seg in raw_segments:
        start = float(raw_seg.get("start", 0.0))
        end = float(raw_seg.get("end", start + 1.0))
        duration = round(end - start, 3)

        def tv(key: str, default_val: str, default_conf: int = 50) -> TagValue:
            d = raw_seg.get(key, {})
            if isinstance(d, dict):
                return TagValue(
                    value=str(d.get("value", default_val)),
                    confidence=max(0, min(100, int(d.get("confidence", default_conf)))),
                )
            return TagValue(value=default_val, confidence=default_conf)

        def bool_tv(key: str, default_val: bool = False) -> TagValue:
            d = raw_seg.get(key, {})
            if isinstance(d, dict):
                raw_val = d.get("value", default_val)
                val = raw_val if isinstance(raw_val, bool) else str(raw_val).lower() == "true"
                return TagValue(
                    value=str(val).lower(),
                    confidence=max(0, min(100, int(d.get("confidence", 50)))),
                )
            return TagValue(value=str(default_val).lower(), confidence=50)

        reusability = tv("reusability", "low")
        if duration < 1.0:
            reusability = TagValue(value="none", confidence=100)

        seg = Segment(
            source_video_id=video_id,
            start=start,
            end=end,
            transcript=raw_seg.get("transcript", ""),
            zone=tv("zone", "body"),
            context_type=tv("context_type", "ambiguous"),
            narrative_broll_fit=tv("narrative_broll_fit", "50"),
            visual_type=tv("visual_type", "visual-type-unknown"),
            energy=tv("energy", "medium"),
            reusability=reusability,
            sentiment=tv("sentiment", "neutral"),
            face_visible=bool_tv("face_visible"),
            product_in_shot=bool_tv("product_in_shot"),
            quality_score=compute_quality_score(video_path, start, end),
            performance_score=performance_score,
            broll_likelihood_score=0.0,
        )

        seg.broll_likelihood_score = compute_broll_score(seg)
        segments.append(seg)

    return segments, full_transcript
