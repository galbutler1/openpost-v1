from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------

class TagValue(BaseModel):
    """Generic tag container: a categorical value plus an AI confidence score."""

    value: str
    confidence: int = Field(ge=0, le=100)


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------

ZoneValue = Literal["hook", "body", "cta"]
ContextTypeValue = Literal["specific", "vague", "ambiguous", "none"]
EnergyValue = Literal["high", "medium", "low", "silent"]
ReusabilityValue = Literal["high", "medium", "low", "none"]
SentimentValue = Literal["positive", "negative", "neutral", "mixed"]

VALID_VISUAL_TYPES = {
    # Presenter
    "founder-talking-neutral",
    "founder-talking-excited",
    "founder-talking-serious",
    "founder-laughing",
    "founder-sad",
    "founder-mad",
    "founder-thinking",
    "founder-reacting",
    # Product
    "product-in-hand",
    "product-demo-feature",
    "product-demo-use-case",
    "product-close-up",
    "product-comparison",
    # Environment
    "workspace",
    "outdoor",
    "lifestyle",
    "event",
    "travel",
    # Action
    "working",
    "celebrating",
    "packaging",
    "on-phone",
    # Production
    "text-overlay-only",
    "blank-space",
    "b-roll-cutaway",
    "screen-recording",
    "split-screen",
    # Fallback
    "visual-type-unknown",
}


class Segment(BaseModel):
    segment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_video_id: str
    start: float
    end: float
    duration: float = 0.0
    transcript: str = ""

    zone: TagValue
    context_type: TagValue
    visual_type: TagValue
    energy: TagValue
    reusability: TagValue
    sentiment: TagValue
    face_visible: TagValue
    product_in_shot: TagValue

    narrative_broll_fit: TagValue = Field(
        default_factory=lambda: TagValue(value="50", confidence=50)
    )

    quality_score: float = Field(default=0.0, ge=0, le=100)
    performance_score: float = Field(default=0.0, ge=0, le=100)
    broll_likelihood_score: float = Field(default=0.0, ge=0, le=100)

    @model_validator(mode="after")
    def _fill_duration(self) -> "Segment":
        if self.duration == 0.0:
            self.duration = round(self.end - self.start, 3)
        return self


# ---------------------------------------------------------------------------
# Video-level metadata
# ---------------------------------------------------------------------------

class VideoMetadata(BaseModel):
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    repost_count: int = 0
    upload_date: str = ""  # YYYYMMDD string from yt-dlp


class Video(BaseModel):
    video_id: str
    file_path: str
    metadata: VideoMetadata = Field(default_factory=VideoMetadata)
    segments: list[Segment] = Field(default_factory=list)
    performance_score: float = Field(default=0.0, ge=0, le=100)
    full_transcript: str = ""


# ---------------------------------------------------------------------------
# Assembly models
# ---------------------------------------------------------------------------

class CutawayWindow(BaseModel):
    start: float
    end: float
    duration: float
    beat_snapped_start: float
    anchor_segment_id: str


class RemixPlan(BaseModel):
    anchor_video: Video
    windows: list[tuple[CutawayWindow, Optional[Segment]]] = Field(
        default_factory=list
    )
