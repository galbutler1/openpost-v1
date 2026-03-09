"""Anchor-based remix engine.

Structure of every remix:
1. HOOK: First HOOK_PROTECTION_SECONDS of the anchor clip, always uncut.
2. BODY: Rest of the anchor clip with content-aware b-roll cuts on beats.
3. CTA: A clip from the SAME source video as the anchor (never from another video).

Audio is always the anchor clip's audio throughout the body.
"""

import json
import random
import subprocess
from pathlib import Path

from clipforge.models.clip import Clip

HOOK_PROTECTION_SECONDS = 4.0
END_PROTECTION_SECONDS = 3.0

# Vague / general language → b-roll is fine here.
# These are statements about the product, vision, or process in general terms.
BROLL_OK_KEYWORDS = {
    # Product descriptions (general)
    "bowl", "plate", "lid", "flat", "fold", "space", "dishwasher", "cabinets",
    "kitchen", "store", "wash", "magnetic", "plastic", "design",
    # Vision / mission / future
    "mission", "revolutionize", "goal", "imagine", "eventually", "future",
    "plan", "predict", "hopefully", "ideally",
    # General process / vague language
    "basically", "essentially", "typically", "usually", "generally", "kind of",
    # Market / industry (broad)
    "market", "industry", "consumers", "people", "customers", "demand",
    "product", "brand", "business", "content", "audience", "posting",
}

# Specific language → stay on anchor.
# Mentions of specific events, people, numbers, personal moments — needs full attention.
SPECIFIC_NO_BROLL_KEYWORDS = {
    # Specific people / entities
    "manufacturer", "factory", "supplier", "investor", "engineer", "partner",
    # Specific events / communications
    "got back", "called", "emailed", "told me", "reached out", "responded",
    "meeting", "met", "signed", "contract", "deal",
    # Specific numbers / metrics
    "raised", "figures", "hundred", "thousand", "million", "percent",
    "weeks", "days", "months", "year", "four", "five", "six",
    # Personal / emotional moments
    "invented", "personally", "honestly", "truth", "hardest", "realized",
    "learned", "changed", "decided", "chose", "switched", "failed", "succeeded",
    "i've", "i was", "i am", "i'm",
}

# CTA language → never cut away
CTA_KEYWORDS = {
    "follow", "subscribe", "comment", "link", "launch", "dm", "drop",
    "see you", "next one", "peace", "tap", "click", "check out",
}


def load_clip_library(library_path: Path) -> list[Clip]:
    data = json.loads(library_path.read_text())
    clips = []
    for d in data:
        clip = Clip(
            source_video=d["source_video"],
            index=d["index"],
            start_time=d["start_time"],
            end_time=d["end_time"],
            clip_path=Path(d["clip_path"]) if d.get("clip_path") else None,
            vocals_path=Path(d["vocals_path"]) if d.get("vocals_path") else None,
            music_path=Path(d["music_path"]) if d.get("music_path") else None,
            transcript=d.get("transcript", ""),
            has_speech=d.get("has_speech", False),
            energy=d.get("energy", 0.0),
            beats=d.get("beats", []),
            tags=d.get("tags", []),
        )
        clip.motion_score = d.get("motion_score", 0.0)
        clip.visual_category = d.get("visual_category", "unknown")
        clips.append(clip)
    return clips


def get_duration(file_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def find_cta_for_anchor(anchor: Clip, all_clips: list[Clip]) -> Clip | None:
    """Find the CTA clip strictly from the same source video as the anchor.

    Priority:
    1. Short clip (<10s) from same source with CTA keywords
    2. Any clip from same source with CTA keywords
    3. Last clip (highest index) from same source that isn't the anchor
    Returns None rather than falling back to another source video.
    """
    cta_kws = ["follow", "see you", "next one", "peace", "comment",
               "subscribe", "dm", "launch day", "tap", "click"]

    # Only clips that come AFTER the anchor in the original video
    same_source = [
        c for c in all_clips
        if c.source_video == anchor.source_video
        and c.index > anchor.index
        and c.clip_path and Path(c.clip_path).exists()
    ]

    if not same_source:
        return None

    # Priority 1: short clip with CTA keywords
    short_ctas = [c for c in same_source
                  if any(kw in c.transcript.lower() for kw in cta_kws) and c.duration < 10.0]
    if short_ctas:
        return short_ctas[0]

    # Priority 2: any clip with CTA keywords
    any_cta = [c for c in same_source
               if any(kw in c.transcript.lower() for kw in cta_kws)]
    if any_cta:
        return any_cta[0]

    # Priority 3: last clip of the source video
    same_source.sort(key=lambda c: c.index, reverse=True)
    return same_source[0]


def get_content_zone(transcript: str, beat_time: float, clip_duration: float) -> tuple[str, set]:
    """Determine content zone at a beat timestamp using proportional word mapping.

    Returns (zone, window_words) where window_words is the set of words being
    spoken at this timestamp — used for relevant b-roll matching.

    Zones:
    - "cta": CTA language (follow, subscribe, etc) — never cut
    - "specific": Specific events, people, numbers — never cut
    - "generic": Vague product/vision/general talk — cut freely
    - "neutral": Everything else — cut occasionally
    """
    if not transcript or clip_duration <= 0:
        return "neutral", set()

    words = transcript.lower().split()
    if not words:
        return "neutral", set()

    progress = beat_time / clip_duration
    word_idx = int(progress * len(words))
    window_start = max(0, word_idx - 8)
    window_end = min(len(words), word_idx + 8)
    window_text = " ".join(words[window_start:window_end])
    window_words = set(window_text.split())

    if any(kw in window_text for kw in CTA_KEYWORDS):
        return "cta", window_words
    if any(kw in window_text for kw in SPECIFIC_NO_BROLL_KEYWORDS):
        return "specific", window_words
    if window_words & BROLL_OK_KEYWORDS:
        return "generic", window_words
    return "neutral", window_words


def pick_relevant_supplemental(anchor_words: set, supplementals: list[Clip], used_ids: set) -> Clip | None:
    """Pick the most topically relevant supplemental clip that hasn't been used yet.

    Scores by word overlap with current anchor topic words.
    Never reuses a clip that's already been used in this video.
    """
    available = [s for s in supplementals if s.id not in used_ids]
    if not available:
        return None
    scored = []
    for supp in available:
        supp_words = set(supp.transcript.lower().split())
        score = len(anchor_words & supp_words)
        scored.append((score, supp))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def classify_clips(clips: list[Clip]) -> dict[str, list[Clip]]:
    anchors = []
    supplementals = []

    for clip in clips:
        if not clip.clip_path or not Path(clip.clip_path).exists():
            continue
        if clip.has_speech and clip.duration >= 4.0:
            anchors.append(clip)
        else:
            supplementals.append(clip)

    anchors.sort(key=lambda c: c.duration, reverse=True)

    # Rank supplementals: product_demo and street_interview first, static_talking last
    category_rank = {"product_demo": 0, "street_interview": 1, "walking": 2,
                     "medium_motion": 3, "low_motion": 4, "static_talking": 5, "unknown": 6}
    supplementals.sort(key=lambda c: (
        category_rank.get(getattr(c, "visual_category", "unknown"), 6),
        -getattr(c, "motion_score", 0.0)
    ))

    return {"anchor": anchors, "supplemental": supplementals}


def build_cut_timeline(anchor: Clip, supplementals: list[Clip],
                       cut_probability: float = 0.45) -> list[dict]:
    """Build a clean timeline: anchor plays as one continuous clip, with b-roll
    inserted at semantically appropriate moments (when product/vague content is spoken).

    Structure: [anchor_block] [broll] [anchor_block] [broll] ... [anchor_end]

    The anchor is NEVER micro-cut at beats. It plays as long continuous blocks.
    B-roll replaces the VIDEO only — anchor audio plays throughout.
    """
    duration = anchor.duration
    end_start = max(0.0, duration - END_PROTECTION_SECONDS)
    words = anchor.transcript.lower().split()

    if not supplementals or duration < 4.0 or not words:
        return [{"type": "anchor", "start": 0.0, "end": duration, "clip": anchor, "clip_offset": 0.0}]

    # --- Step 1: Find good b-roll insertion windows ---
    # Scan the transcript proportionally to find stretches of product/vague talk
    window_size = 4.0   # evaluate content in 4-second windows
    step = 2.0          # slide every 2 seconds
    min_spacing = 8.0   # minimum seconds between b-roll cuts

    candidates = []  # (score, time, window_words)
    t = 1.0
    while t + window_size < end_start - 1.0:
        prog_start = t / duration
        prog_end = (t + window_size) / duration
        idx_start = int(prog_start * len(words))
        idx_end = int(prog_end * len(words))
        window_words = set(words[idx_start:idx_end])
        window_text = " ".join(words[idx_start:idx_end])

        has_cta = any(kw in window_text for kw in CTA_KEYWORDS)
        has_specific = any(kw in window_text for kw in SPECIFIC_NO_BROLL_KEYWORDS)
        broll_score = len(window_words & BROLL_OK_KEYWORDS)

        if not has_cta and not has_specific and broll_score > 0:
            candidates.append((broll_score, t, window_words))

        t += step

    # Sort by score, pick top ones spaced far enough apart
    candidates.sort(key=lambda x: x[0], reverse=True)
    selected = []  # (time, window_words)
    for score, start_t, window_words in candidates:
        if all(abs(start_t - s[0]) >= min_spacing for s in selected):
            selected.append((start_t, window_words))
        if len(selected) >= 4:
            break
    selected.sort(key=lambda x: x[0])

    if not selected:
        return [{"type": "anchor", "start": 0.0, "end": duration, "clip": anchor, "clip_offset": 0.0}]

    # --- Step 2: Snap insertion points to nearby beats ---
    beats = anchor.beats or []

    def snap_to_beat(t, beats, radius=1.5):
        nearby = [b for b in beats if abs(b - t) <= radius]
        return min(nearby, key=lambda b: abs(b - t)) if nearby else t

    # --- Step 3: Build timeline ---
    used_ids: set[str] = set()
    timeline = []
    current = 0.0

    for insert_t, window_words in selected:
        insert_t = snap_to_beat(insert_t, beats)
        broll_dur = random.uniform(2.5, 5.0)
        broll_end = snap_to_beat(min(insert_t + broll_dur, end_start), beats)

        if insert_t <= current + 0.5 or broll_end <= insert_t + 0.5:
            continue

        supp = pick_relevant_supplemental(window_words, supplementals, used_ids)
        if supp is None:
            continue

        # Anchor plays continuously up to this point
        timeline.append({
            "type": "anchor",
            "start": current,
            "end": insert_t,
            "clip": anchor,
            "clip_offset": current,
        })

        # B-roll replaces video (anchor audio still plays)
        cut_duration = broll_end - insert_t
        max_offset = max(0, supp.duration - cut_duration)
        supp_offset = random.uniform(0, max_offset) if max_offset > 0 else 0
        timeline.append({
            "type": "supplemental",
            "start": insert_t,
            "end": broll_end,
            "clip": supp,
            "clip_offset": supp_offset,
        })
        used_ids.add(supp.id)
        current = broll_end

    # Final anchor block runs to end
    if current < duration:
        timeline.append({
            "type": "anchor",
            "start": current,
            "end": duration,
            "clip": anchor,
            "clip_offset": current,
        })

    return timeline


def render_clip(clip_path: Path, output_path: Path, width: int, height: int):
    """Render a single clip normalized to target dimensions with its own audio."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-r", "30",
        "-loglevel", "error",
        str(output_path),
    ], check=True)


def render_anchor_remix(
    anchor: Clip,
    timeline: list[dict],
    cta: Clip | None,
    output_path: Path,
    hook_clip: Clip | None = None,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """Render the final video: hook clip (own audio) + body (anchor audio + b-roll) + CTA (own audio)."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent / f"_work_{output_path.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    anchor_path = Path(anchor.clip_path).resolve()

    # 1. Extract anchor audio (full, untouched)
    anchor_audio = (work_dir / "anchor_audio.m4a").resolve()
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(anchor_path),
        "-vn", "-c:a", "aac", "-b:a", "192k",
        "-loglevel", "error",
        str(anchor_audio),
    ], check=True)

    # 2. Build video segments
    segment_paths = []
    for idx, entry in enumerate(timeline):
        seg_path = (work_dir / f"seg_{idx:03d}.mp4").resolve()
        clip_path = Path(entry["clip"].clip_path).resolve()
        start = entry["clip_offset"]
        duration = entry["end"] - entry["start"]

        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(clip_path),
            "-t", str(duration),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-an",
            "-c:v", "libx264",
            "-r", "30",
            "-loglevel", "error",
            str(seg_path),
        ], check=True)
        segment_paths.append(seg_path)

    # 3. Concatenate video segments
    concat_file = (work_dir / "concat.txt").resolve()
    with open(concat_file, "w") as f:
        for sp in segment_paths:
            f.write(f"file '{sp}'\n")

    video_track = (work_dir / "video_track.mp4").resolve()
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-loglevel", "error",
        str(video_track),
    ], check=True)

    # 4. Combine video + anchor audio
    main_part = (work_dir / "main.mp4").resolve()
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_track),
        "-i", str(anchor_audio),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        "-loglevel", "error",
        str(main_part),
    ], check=True)

    # 5. Build final concat: [hook] + main_body + [cta]
    parts = []

    # Re-encode main to consistent format
    main_reencoded = (work_dir / "main_re.mp4").resolve()
    subprocess.run([
        "ffmpeg", "-y", "-i", str(main_part),
        "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-r", "30",
        "-loglevel", "error", str(main_reencoded),
    ], check=True)

    if hook_clip and hook_clip.clip_path and hook_clip.id != anchor.id:
        hook_rendered = (work_dir / "hook.mp4").resolve()
        render_clip(Path(hook_clip.clip_path).resolve(), hook_rendered, width, height)
        parts.append(hook_rendered)

    parts.append(main_reencoded)

    if cta and cta.clip_path:
        cta_rendered = (work_dir / "cta.mp4").resolve()
        render_clip(Path(cta.clip_path).resolve(), cta_rendered, width, height)
        parts.append(cta_rendered)

    if len(parts) == 1:
        import shutil
        shutil.copy2(parts[0], output_path)
    else:
        final_concat = (work_dir / "final_concat.txt").resolve()
        with open(final_concat, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(final_concat),
            "-c:v", "libx264", "-c:a", "aac",
            "-movflags", "+faststart",
            "-loglevel", "error",
            str(output_path),
        ], check=True)

    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)
    return output_path


def generate_all_remixes(
    library_path: Path,
    output_dir: Path,
    cut_probability: float = 0.45,
    max_remixes: int = 0,
) -> list[Path]:
    clips = load_clip_library(library_path)
    classified = classify_clips(clips)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    anchors = classified["anchor"]
    supplementals = classified["supplemental"]

    print(f"Auto-generating remixes from library:")
    print(f"  {len(anchors)} anchor candidates")
    print(f"  {len(supplementals)} supplemental clips")

    # Pick best anchor per source video
    best_per_source = {}
    for a in anchors:
        src = a.source_video
        if src not in best_per_source:
            best_per_source[src] = a
        else:
            current = best_per_source[src]
            if len(a.beats) > len(current.beats):
                best_per_source[src] = a

    selected_anchors = list(best_per_source.values())
    selected_anchors.sort(key=lambda c: len(c.beats), reverse=True)

    if max_remixes > 0:
        selected_anchors = selected_anchors[:max_remixes]

    print(f"  Selected {len(selected_anchors)} anchors\n")

    outputs = []
    for i, anchor in enumerate(selected_anchors):
        print(f"--- Remix {i+1}/{len(selected_anchors)} ---")
        print(f"  Anchor: {anchor.id} ({anchor.duration:.1f}s, {len(anchor.beats)} beats)")
        print(f"  \"{anchor.transcript[:80]}\"")

        supps = [c for c in supplementals if c.source_video != anchor.source_video]
        if len(supps) < 3:
            supps = supplementals
        random.shuffle(supps)

        # CTA strictly from same source video
        cta = find_cta_for_anchor(anchor, clips)
        if cta:
            print(f"  CTA: {cta.id} (same source) — \"{cta.transcript[:50]}\"")
        else:
            print(f"  CTA: none found from same source")

        timeline = build_cut_timeline(anchor, supps, cut_probability=cut_probability)
        anchor_segs = sum(1 for t in timeline if t["type"] == "anchor")
        supp_segs = sum(1 for t in timeline if t["type"] == "supplemental")
        print(f"  Timeline: {anchor_segs} anchor + {supp_segs} supplemental segments")

        # Hook = clip000 of the anchor's source video (actual start of original video)
        hook_clip = next((c for c in clips
                          if c.source_video == anchor.source_video and c.index == 0
                          and c.clip_path and Path(c.clip_path).exists()), None)
        if hook_clip and hook_clip.id != anchor.id:
            print(f"  Hook: {hook_clip.id} — \"{hook_clip.transcript[:50]}\"")

        output_path = output_dir / f"auto_{i:03d}_{anchor.id}.mp4"
        try:
            render_anchor_remix(anchor, timeline, cta, output_path, hook_clip=hook_clip)
            outputs.append(output_path)
            print(f"  ✓ {output_path.name}\n")
        except Exception as e:
            print(f"  ✗ Failed: {e}\n")

    print(f"\n=== Generated {len(outputs)} remixes in {output_dir} ===")
    return outputs


def generate_anchor_remix(
    library_path: Path,
    output_path: Path,
    anchor_id: str | None = None,
    cut_probability: float = 0.5,
) -> Path | None:
    clips = load_clip_library(library_path)
    classified = classify_clips(clips)

    if anchor_id:
        anchor = next((c for c in clips if c.id == anchor_id), None)
        if not anchor:
            print(f"  ERROR: Anchor clip {anchor_id} not found")
            return None
    else:
        if not classified["anchor"]:
            print("  ERROR: No anchor clips found")
            return None
        anchor = classified["anchor"][0]

    print(f"  Anchor: {anchor.id} ({anchor.duration:.1f}s)")

    supps = [c for c in classified["supplemental"] if c.source_video != anchor.source_video]
    if len(supps) < 3:
        supps = classified["supplemental"]
    random.shuffle(supps)

    cta = find_cta_for_anchor(anchor, clips)

    timeline = build_cut_timeline(anchor, supps, cut_probability=cut_probability)
    result = render_anchor_remix(anchor, timeline, cta, output_path)
    print(f"  ✓ Done: {result}")
    return result
