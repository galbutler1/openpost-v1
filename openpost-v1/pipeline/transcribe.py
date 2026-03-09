"""
transcribe.py — Whisper word-level transcription via OpenAI API.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from openai import OpenAI

import config


class WordTimestamp(TypedDict):
    word: str
    start: float
    end: float


def transcribe(video_path: str) -> list[WordTimestamp]:
    """
    Transcribe *video_path* using OpenAI Whisper with word-level timestamps.

    Returns a list of dicts: [{word, start, end}, ...] sorted by start time.
    An empty list is returned if the video has no speech.
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    with open(path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    words: list[WordTimestamp] = []

    # response.words is a list of Word objects when word timestamps are requested
    raw_words = getattr(response, "words", None) or []
    for w in raw_words:
        # Each element has .word, .start, .end attributes
        words.append(
            WordTimestamp(
                word=getattr(w, "word", ""),
                start=float(getattr(w, "start", 0.0)),
                end=float(getattr(w, "end", 0.0)),
            )
        )

    words.sort(key=lambda x: x["start"])
    return words
