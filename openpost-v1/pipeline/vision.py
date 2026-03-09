"""
vision.py — GPT-4o frame labelling via a single batched API call.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TypedDict

import cv2

from openai import OpenAI

import config
from models import VALID_VISUAL_TYPES


class FrameLabel(TypedDict):
    timestamp: float
    visual_type: str
    confidence: int


_SYSTEM_PROMPT = """\
You are a video-content analyst. You will receive a sequence of video frames.
For each frame you must assign exactly ONE visual_type from the following list:

PRESENTER:
  founder-talking-neutral, founder-talking-excited, founder-talking-serious,
  founder-laughing, founder-sad, founder-mad, founder-thinking, founder-reacting

PRODUCT:
  product-in-hand, product-demo-feature, product-demo-use-case,
  product-close-up, product-comparison

ENVIRONMENT:
  workspace, outdoor, lifestyle, event, travel

ACTION:
  working, celebrating, packaging, on-phone

PRODUCTION:
  text-overlay-only, blank-space, b-roll-cutaway, screen-recording, split-screen

FALLBACK:
  visual-type-unknown  (use ONLY if the frame truly matches none of the above)

Respond with a JSON array where each element has:
  - "frame_index": integer (0-based)
  - "visual_type": string (exactly one of the above values)
  - "confidence": integer 0-100

Output ONLY valid JSON. No markdown fences, no explanation.
"""


def _encode_frame(frame_bgr) -> str:
    """Encode an OpenCV BGR frame as a base64 JPEG string."""
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("Failed to encode frame as JPEG")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def label_frames(video_path: str, interval_seconds: float = 2.0) -> list[FrameLabel]:
    """
    Extract one frame every *interval_seconds* and label each with GPT-4o.

    All frames are sent in a SINGLE API call.
    Returns list of FrameLabel sorted by timestamp.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    frame_timestamps: list[float] = []
    encoded_frames: list[str] = []

    t = 0.0
    while t < duration:
        frame_num = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            break
        encoded_frames.append(_encode_frame(frame))
        frame_timestamps.append(round(t, 3))
        t += interval_seconds

    cap.release()

    if not encoded_frames:
        return []

    # Build the user message: each frame as an image_url content part
    content_parts: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Below are {len(encoded_frames)} frames extracted every "
                f"{interval_seconds}s from a short-form video. "
                "Label each frame with the appropriate visual_type."
            ),
        }
    ]

    for i, b64 in enumerate(encoded_frames):
        content_parts.append(
            {
                "type": "text",
                "text": f"Frame {i} (t={frame_timestamps[i]:.1f}s):",
            }
        )
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "low",
                },
            }
        )

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content_parts},
        ],
        max_tokens=4096,
        temperature=0,
    )

    raw = response.choices[0].message.content or "[]"
    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        parsed: list[dict] = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return unknown for all frames
        return [
            FrameLabel(
                timestamp=ts,
                visual_type="visual-type-unknown",
                confidence=0,
            )
            for ts in frame_timestamps
        ]

    labels: list[FrameLabel] = []
    for item in parsed:
        idx = int(item.get("frame_index", 0))
        vt = item.get("visual_type", "visual-type-unknown")
        if vt not in VALID_VISUAL_TYPES:
            vt = "visual-type-unknown"
        conf = max(0, min(100, int(item.get("confidence", 50))))
        ts = frame_timestamps[idx] if idx < len(frame_timestamps) else 0.0
        labels.append(FrameLabel(timestamp=ts, visual_type=vt, confidence=conf))

    labels.sort(key=lambda x: x["timestamp"])
    return labels
