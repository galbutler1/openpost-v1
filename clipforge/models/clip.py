"""Data models for the clip library."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Clip:
    """A single clip extracted from a source video."""

    source_video: str
    index: int
    start_time: float  # seconds
    end_time: float  # seconds
    clip_path: Path | None = None
    vocals_path: Path | None = None
    music_path: Path | None = None
    transcript: str = ""
    has_speech: bool = False
    energy: float = 0.0  # 0-1 audio energy score
    beats: list[float] = field(default_factory=list)  # beat timestamps relative to clip
    tags: list[str] = field(default_factory=list)  # e.g. ["talking", "high-energy", "b-roll"]

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def id(self) -> str:
        return f"{Path(self.source_video).stem}_clip{self.index:03d}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_video": self.source_video,
            "index": self.index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "clip_path": str(self.clip_path) if self.clip_path else None,
            "vocals_path": str(self.vocals_path) if self.vocals_path else None,
            "music_path": str(self.music_path) if self.music_path else None,
            "transcript": self.transcript,
            "has_speech": self.has_speech,
            "energy": self.energy,
            "beats": self.beats,
            "tags": self.tags,
        }
