# ClipForge — Project Summary

## What It Is
A tool that takes all the videos from an Instagram account, breaks them down into their raw components, and automatically generates new short-form video variations from the existing footage. The creator posts these as Trial Reels to test what performs, then promotes winners to their main feed.

## How It Works

### Step 1: Download
Pull all videos from an Instagram account using `instaloader`. We tested this on @gal.butler (101 videos, 576MB).

### Step 2: Process (the analysis pipeline)
Each video goes through four stages:

1. **Scene Detection** (PySceneDetect) — Finds natural cut points in each video and splits it into individual clips. 10 videos → 75 clips.

2. **Audio Separation** (Demucs) — Splits each clip's audio into two tracks: isolated vocals and isolated music/background. This lets us remix voice and music independently.

3. **Transcription** (Whisper Large V3 Turbo via whisper-cpp) — Transcribes everything said in each clip. Uses the isolated vocal track for better accuracy.

4. **Audio Analysis** (librosa) — Detects every beat timestamp in the music and scores energy level (0-1). Auto-tags clips: "talking", "b-roll", "high-energy", "low-energy".

Everything is saved to a `clip_library.json` — a structured database of every clip with its video file, separated audio, transcript, beats, energy, and tags.

### Step 3: Remix (the generation engine)
Takes the clip library and assembles new videos using structural templates:

- **Hook + Montage** — Strong opener → rapid cuts on beat → CTA
- **Reordered Narrative** — Talking clips from different videos rearranged into a new story
- **Highlight Reel** — Fastest, highest-energy moments strung together
- **Hook Swap** — Test different opening hooks with the same body content

Clips are selected to match each template slot (by tag, duration, energy), pulled from different source videos for variety, and cuts are snapped to beat boundaries so transitions feel musical.

### Step 4: Post as Trial Reels (future)
Instagram's Trial Reels feature shows content to a small non-follower audience first. Post remix variations, measure which ones get the best watch time and engagement, then promote winners.

## Tech Stack
- **Python 3.12** with FFmpeg, Demucs, Whisper, PySceneDetect, librosa
- **CLI tool** (`clipforge`) with three commands: `download`, `process`, `remix`
- All local for now — production version will use FastAPI + Modal (serverless GPU) + Supabase + Cloudflare R2

## Current Status
- Download: working (pulled 101 videos from @gal.butler)
- Process pipeline: working (scene detect → audio separation → transcription → analysis)
- Remix engine: working (generated 5 test remixes from 10 videos)
- Reviewing remix output quality now

## What's Next
- Review remix quality and tune templates
- Process all 101 videos into full clip library
- Add caption overlay (auto-subtitles from transcripts)
- Add music swap (replace background music, re-sync cuts to new beat)
- Batch generation (hundreds of variations)
- Build web UI and API for the SaaS version
