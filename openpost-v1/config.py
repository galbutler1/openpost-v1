from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]

_base = Path(__file__).parent
DATA_DIR: Path = _base / os.getenv("DATA_DIR", "data")
OUTPUT_DIR: Path = _base / os.getenv("OUTPUT_DIR", "data/output")

VIDEOS_DIR: Path = DATA_DIR / "videos"
SEGMENTS_DIR: Path = DATA_DIR / "segments"

# Ensure directories exist at import time
for _d in (VIDEOS_DIR, SEGMENTS_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
