"""
gen_textclips.py — Text+Clips generator.

Pure b-roll clips (zero audio) + Pillow-rendered title-card text overlays + CTA.
Text is drawn with Pillow → transparent PNG → ffmpeg overlay per clip → concat.

Usage:
    python gen_textclips.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console
from rich.panel import Panel

import config  # noqa: F401 — creates dirs
from models import Segment
from assembler.matcher import TOPIC_VISUAL_TYPES

console = Console()

VIDEOS_DIR   = Path("data/videos")
SEGMENTS_DIR = Path("data/segments")
OUTPUT_DIR   = Path("data/output")
MUSIC_DIR    = Path("data/music")

W, H             = 1080, 1920
PHRASE_DURATION  = 1.8   # seconds per phrase clip
CTA_DURATION     = 3.0
FONT_PATH        = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# Source videos permanently blocked from the text+clips pool
BLOCKED_SOURCES = {
    "DG_rJO3Nnw4",   # street interview — shows other people, not product
}
FONT_SIZE        = 84

# ── Scripts ───────────────────────────────────────────────────────────────────
# Each phrase: (display_text, preferred_visual_types, prefer_face_visible)
# preferred_visual_types: ordered list — first match wins.
# prefer_face: True = prefer shots where Gal is visible with product.

# ── Card layout constants ─────────────────────────────────────────────────────
CARD_TEXT_H  = 400   # white strip at top (px)
CARD_VID_Y   = 412   # video starts here (12px gap below text strip)
CARD_VID_H   = H - CARD_VID_Y           # = 1508
_w           = int(CARD_VID_H * 9 / 16)
CARD_VID_W   = _w if _w % 2 == 0 else _w + 1  # must be even for libx264
CARD_VID_X   = (W - CARD_VID_W) // 2    # centered
CARD_FONT_SZ = 82

SCRIPTS = [
    {
        # Classic Gal pitch: personal intro → what it is → why it matters
        "name": "pitch",
        "style": "card",
        "music_search": "Espresso Sabrina Carpenter no copyright cover vocals lyrics 2024",
        "phrases": [
            ("Hi, I'm Gal.",                    ["product-in-hand"],                           True),
            ("I invented this.",                ["product-in-hand"],                           True),
            ("It's a bowl.",                    ["product-close-up"],                          False),
            ("That folds flat.",                ["product-demo-feature"],                      False),
            ("Takes up almost\nno space.",      ["product-close-up", "product-in-hand"],       False),
            ("Fits in any\ndrawer.",            ["product-demo-use-case"],                     False),
            ("Dishwasher safe.",                ["product-demo-use-case"],                     False),
            ("Use it like\nany bowl.",          ["product-demo-use-case"],                     False),
            ("Just put it\naway differently.",  ["product-in-hand"],                           True),
        ],
        "cta": "Link in bio.",
    },
    {
        # Problem → solution, no numbers, just the core idea
        "name": "problem",
        "style": "card",
        "music_search": "Anti-Hero Taylor Swift no copyright cover vocals lyrics 2024",
        "phrases": [
            ("Bowls take up\ntoo much space.",  ["product-demo-use-case"],                     False),
            ("I made one\nthat doesn't.",       ["product-in-hand"],                           True),
            ("It folds\ncompletely flat.",      ["product-demo-feature"],                      False),
            ("Like this.",                      ["product-demo-feature"],                      False),
            ("Fits in a\nnormal drawer.",       ["product-demo-use-case"],                     False),
            ("Holds your food\nnormally.",      ["product-demo-use-case"],                     False),
            ("Dishwasher safe.",                ["product-demo-use-case"],                     False),
            ("It's a real\nproduct.",           ["product-close-up"],                          False),
            ("Made by me.",                     ["product-in-hand"],                           True),
        ],
        "cta": "Link in bio.",
    },
    {
        # Pure product demo — show don't tell
        "name": "demo",
        "style": "card",
        "music_search": "Blinding Lights The Weeknd no copyright cover vocals lyrics",
        "phrases": [
            ("This bowl\nfolds flat.",          ["product-demo-feature"],                      False),
            ("Watch.",                          ["product-demo-feature"],                      False),
            ("All the way\ndown.",              ["product-demo-feature"],                      False),
            ("Slides into\nany drawer.",        ["product-demo-use-case"],                     False),
            ("Opens back up.",                  ["product-demo-use-case"],                     False),
            ("Holds your food.",                ["product-demo-use-case"],                     False),
            ("Dishwasher safe.",                ["product-demo-use-case"],                     False),
            ("Zero cabinet\nspace wasted.",     ["product-close-up", "product-in-hand"],       False),
            ("I made this.",                    ["product-in-hand"],                           True),
        ],
        "cta": "Link in bio.",
    },
    {
        # Space-saving angle — relatable kitchen problem
        "name": "space",
        "style": "card",
        "music_search": "Levitating Dua Lipa no copyright cover vocals lyrics 2024",
        "phrases": [
            ("Look at this.",                   ["product-in-hand"],                           True),
            ("It's a bowl.",                    ["product-close-up"],                          False),
            ("That folds\ncompletely flat.",    ["product-demo-feature"],                      False),
            ("Fits right in\nyour drawer.",     ["product-demo-use-case"],                     False),
            ("No more\nstacked bowls.",         ["product-demo-use-case"],                     False),
            ("No more\nclutter.",               ["product-demo-use-case"],                     False),
            ("Just use it,\nfold it, done.",    ["product-demo-feature"],                      False),
            ("I built this\nfor my kitchen.",   ["product-in-hand"],                           True),
            ("Now it's yours.",                 ["product-close-up"],                          False),
        ],
        "cta": "Link in bio.",
    },
]


# ── Clip pool ─────────────────────────────────────────────────────────────────

def load_pool() -> list[Segment]:
    """Product-in-shot only, body zone, no text-overlay clips."""
    pool: list[Segment] = []
    for f in SEGMENTS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            segs = d.get("segments", d) if isinstance(d, dict) else d
            for s in segs:
                seg = Segment(**s)
                if (
                    seg.zone.value == "body"
                    and seg.duration >= PHRASE_DURATION
                    and seg.quality_score >= 40
                    and seg.product_in_shot.value == "true"
                    and seg.source_video_id not in BLOCKED_SOURCES
                    and seg.visual_type.value not in ("text-overlay-only", "blank-space",
                                                       "screen-recording", "split-screen")
                ):
                    pool.append(seg)
        except Exception:
            pass
    console.print(f"Clip pool: [cyan]{len(pool)}[/cyan] product-in-shot segments")
    return pool


def load_hook_pool() -> list[Segment]:
    """Hook-zone segments — opening clips from real videos, product in shot."""
    pool: list[Segment] = []
    for f in SEGMENTS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            segs = d.get("segments", d) if isinstance(d, dict) else d
            for s in segs:
                seg = Segment(**s)
                if (
                    seg.zone.value == "hook"
                    and seg.duration >= PHRASE_DURATION
                    and seg.quality_score >= 40
                    and seg.product_in_shot.value == "true"
                    and seg.source_video_id not in BLOCKED_SOURCES
                    and seg.visual_type.value not in ("text-overlay-only", "blank-space",
                                                       "screen-recording", "split-screen")
                ):
                    pool.append(seg)
        except Exception:
            pass
    console.print(f"Hook pool: [cyan]{len(pool)}[/cyan] hook-zone segments")
    return pool


def pick_clip(
    preferred_vtypes: list[str],
    pool: list[Segment],
    used_ids: set[str],
    used_video_ids: set[str],
    prefer_face: bool = False,
) -> Segment | None:
    """Pick best clip matching preferred visual types in priority order."""
    def _candidates(vtypes: list[str], relax_source: bool) -> list[Segment]:
        base = [
            s for s in pool
            if s.segment_id not in used_ids
            and (relax_source or s.source_video_id not in used_video_ids)
            and s.visual_type.value in vtypes
        ]
        if prefer_face:
            # Prefer face-visible shots; fall back to any if none available
            with_face = [s for s in base if s.face_visible.value == "true"]
            return with_face if with_face else base
        return base

    # Try preferred types in order first, then fall back to any product type
    for attempt_vtypes in [preferred_vtypes,
                            ["product-in-hand", "product-demo-feature",
                             "product-demo-use-case", "product-close-up"]]:
        for relax in [False, True]:
            cands = _candidates(attempt_vtypes, relax)
            if cands:
                cands.sort(key=lambda s: s.quality_score, reverse=True)
                return cands[0]
    return None


# ── Text overlay rendering (Pillow) ──────────────────────────────────────────

def make_text_png(text: str, size: tuple[int, int] = (W, H)) -> Path:
    """Render white text near the top of frame on a solid black pill background."""
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    img  = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    lines = text.split("\n")

    line_boxes   = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    line_widths  = [b[2] - b[0] for b in line_boxes]
    line_heights = [b[3] - b[1] for b in line_boxes]
    LINE_GAP = 16
    total_h = sum(line_heights) + LINE_GAP * (len(lines) - 1)
    max_w   = max(line_widths)

    cx = size[0] / 2
    # Vertically centered
    y0 = (size[1] - total_h) / 2

    PAD = 36
    box_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(box_layer)
    bdraw.rounded_rectangle(
        [cx - max_w / 2 - PAD, y0 - PAD,
         cx + max_w / 2 + PAD, y0 + total_h + PAD],
        radius=22,
        fill=(0, 0, 0, 230),   # solid-looking black
    )
    img = Image.alpha_composite(img, box_layer)
    draw = ImageDraw.Draw(img)

    y = y0
    for i, line in enumerate(lines):
        x = cx - line_widths[i] / 2
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 180))   # subtle shadow
        draw.text((x,     y    ), line, font=font, fill=(255, 255, 255, 255))
        y += line_heights[i] + LINE_GAP

    tmp = Path(tempfile.mktemp(suffix=".png"))
    img.save(tmp, "PNG")
    return tmp


def make_card_bg_png(text: str) -> Path:
    """White 1080×1920 canvas with dark text centered in the top strip."""
    try:
        font = ImageFont.truetype(FONT_PATH, CARD_FONT_SZ)
    except Exception:
        font = ImageFont.load_default()

    img  = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = text.split("\n")

    line_boxes   = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    line_widths  = [b[2] - b[0] for b in line_boxes]
    line_heights = [b[3] - b[1] for b in line_boxes]
    LINE_GAP = 14
    total_h = sum(line_heights) + LINE_GAP * (len(lines) - 1)

    cx = W / 2
    # Sit text in lower portion of the white strip (feels closer to the video)
    y0 = CARD_TEXT_H * 0.62 - total_h / 2

    y = y0
    for i, line in enumerate(lines):
        x = cx - line_widths[i] / 2
        draw.text((x, y), line, font=font, fill=(18, 18, 18))
        y += line_heights[i] + LINE_GAP

    tmp = Path(tempfile.mktemp(suffix=".png"))
    img.save(tmp, "PNG")
    return tmp


def _build_card_clip(seg: Segment, text: str, mp4: str, duration: float, out: Path) -> None:
    """Card style: white bg with text at top, video inset below."""
    bg_png = make_card_bg_png(text)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(bg_png),   # input 0: white card bg
            "-i", mp4,                          # input 1: source video
            "-filter_complex",
            (
                f"[1:v]trim=start={seg.start:.6f}:duration={duration:.2f},"
                f"setpts=PTS-STARTPTS,fps=30,"
                f"scale={CARD_VID_W}:{CARD_VID_H}:force_original_aspect_ratio=decrease,"
                f"pad={CARD_VID_W}:{CARD_VID_H}:(ow-iw)/2:(oh-ih)/2[vid];"
                f"[0:v][vid]overlay={CARD_VID_X}:{CARD_VID_Y}[vout]"
            ),
            "-map", "[vout]",
            "-an",
            "-t", str(duration),
            "-r", "30",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
            "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")[-2000:]) from exc
    finally:
        bg_png.unlink(missing_ok=True)


def _build_card_cta_clip(text: str, duration: float, out: Path) -> None:
    """Card style CTA: full white frame with centered dark text."""
    try:
        font = ImageFont.truetype(FONT_PATH, CARD_FONT_SZ + 10)
    except Exception:
        font = ImageFont.load_default()

    img  = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = text.split("\n")
    line_boxes   = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    line_widths  = [b[2] - b[0] for b in line_boxes]
    line_heights = [b[3] - b[1] for b in line_boxes]
    LINE_GAP = 16
    total_h = sum(line_heights) + LINE_GAP * (len(lines) - 1)
    cx, y0 = W / 2, (H - total_h) / 2
    y = y0
    for i, line in enumerate(lines):
        draw.text((cx - line_widths[i] / 2, y), line, font=font, fill=(18, 18, 18))
        y += line_heights[i] + LINE_GAP

    tmp_png = Path(tempfile.mktemp(suffix=".png"))
    img.save(tmp_png, "PNG")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(tmp_png),
            "-t", str(duration), "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-an", str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")[-2000:]) from exc
    finally:
        tmp_png.unlink(missing_ok=True)


# ── ffmpeg per-clip helpers ───────────────────────────────────────────────────

def _build_phrase_clip(seg: Segment, text: str, mp4: str, duration: float, out: Path) -> None:
    """Trim + scale clip, overlay text PNG, output silent MP4."""
    txt_png = make_text_png(text)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", mp4,
            "-loop", "1", "-i", str(txt_png),
            "-filter_complex",
            (
                f"[0:v]trim=start={seg.start:.6f}:duration={duration:.2f},"
                f"setpts=PTS-STARTPTS,fps=30,"
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[vid];"
                f"[1:v]scale={W}:{H}[txt];"
                f"[vid][txt]overlay=0:0[vout]"
            ),
            "-map", "[vout]",
            "-an",
            "-t", str(duration),
            "-r", "30",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
            "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")[-2000:]) from exc
    finally:
        txt_png.unlink(missing_ok=True)


def _build_cta_clip(text: str, duration: float, out: Path) -> None:
    """Black frame + text overlay → silent MP4."""
    txt_png = make_text_png(text)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=black:size={W}x{H}:rate=30:duration={duration}",
            "-loop", "1", "-i", str(txt_png),
            "-filter_complex",
            f"[0:v][1:v]overlay=0:0[vout]",
            "-map", "[vout]",
            "-an",
            "-t", str(duration),
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
            "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")[-2000:]) from exc
    finally:
        txt_png.unlink(missing_ok=True)


def fetch_music(search_term: str) -> Path | None:
    """Download a track via yt-dlp search. Always fetches fresh to ensure variety."""
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    before = {f for f in MUSIC_DIR.glob("*.mp3")}
    out_template = str(MUSIC_DIR / "%(title)s.%(ext)s")
    cmd = [
        "yt-dlp",
        f"ytsearch1:{search_term}",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "-o", out_template,
        "--force-overwrites",
        "--quiet", "--no-warnings",
        "--no-playlist",
    ]
    subprocess.run(cmd, capture_output=True)
    after = {f for f in MUSIC_DIR.glob("*.mp3")}
    new_files = after - before
    if new_files:
        return list(new_files)[0]
    # File already existed (same title) — still return it
    files = sorted(MUSIC_DIR.glob("*.mp3"), key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0] if files else None


def add_music(video_path: Path, music_path: Path, out_path: Path, volume: float = 0.55) -> None:
    """Mix a music track (looped/trimmed) into a silent video."""
    dur_result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    duration = float(dur_result.stdout.strip())

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-map", "0:v",
        "-map", "1:a",
        "-filter:a", f"volume={volume}",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        "-shortest",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")[-2000:]) from exc


def _concat_clips(clips: list[Path], out: Path) -> None:
    """Concat silent MP4 segments — re-encode to fix timestamp discontinuities."""
    list_file = Path(tempfile.mktemp(suffix=".txt"))
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in clips), encoding="utf-8")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-r", "30",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
            "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")[-2000:]) from exc
    finally:
        list_file.unlink(missing_ok=True)


# ── Main builder ──────────────────────────────────────────────────────────────

def build_textclip(
    script: dict,
    pool: list[Segment],
    idx: int,
    global_used_ids: set[str],
    batch_dir: Path,
    hook_pool: list[Segment] | None = None,
) -> Path | None:
    name    = script["name"]
    phrases = script["phrases"]
    cta     = script["cta"]

    video_lookup = {f.stem: str(f) for f in VIDEOS_DIR.glob("*.mp4")}

    used_ids:       set[str] = set(global_used_ids)
    used_video_ids: set[str] = set()

    tmp_clips: list[Path] = []

    for i, (phrase_text, preferred_vtypes, prefer_face) in enumerate(phrases):
        # First phrase must come from hook zone — skip if none available
        seg = None
        if i == 0 and hook_pool:
            seg = pick_clip(preferred_vtypes, hook_pool, used_ids, used_video_ids, prefer_face)
            if seg:
                console.print(f"  [dim]First clip from hook zone[/dim]")
            else:
                console.print(f"  [yellow]✗ No hook clip for first phrase — skipping clip[/yellow]")
                continue
        else:
            seg = pick_clip(preferred_vtypes, pool, used_ids, used_video_ids, prefer_face)
        if seg is None:
            console.print(f"  [yellow]✗ '{phrase_text}' — no clip, skipping[/yellow]")
            continue
        mp4 = video_lookup.get(seg.source_video_id)
        if not mp4:
            continue

        used_ids.add(seg.segment_id)
        global_used_ids.add(seg.segment_id)
        used_video_ids.add(seg.source_video_id)

        tmp = Path(tempfile.mktemp(suffix=f"_tc{idx}_p{i}.mp4"))
        builder = _build_card_clip if script.get("style") == "card" else _build_phrase_clip
        try:
            builder(seg, phrase_text, mp4, PHRASE_DURATION, tmp)
            tmp_clips.append(tmp)
            console.print(
                f"  [green]✓[/green] '{phrase_text}' → {seg.visual_type.value} "
                f"from {seg.source_video_id} (q={seg.quality_score:.0f})"
            )
        except Exception as exc:
            console.print(f"  [red]✗ phrase {i} failed: {str(exc)[:120]}[/red]")

    if not tmp_clips:
        return None

    # CTA card
    cta_tmp = Path(tempfile.mktemp(suffix=f"_tc{idx}_cta.mp4"))
    cta_builder = _build_card_cta_clip if script.get("style") == "card" else _build_cta_clip
    try:
        cta_builder(cta, CTA_DURATION, cta_tmp)
        tmp_clips.append(cta_tmp)
        console.print(f"  [dim]CTA: '{cta}'[/dim]")
    except Exception as exc:
        console.print(f"  [yellow]CTA failed: {exc}[/yellow]")

    # Concat all
    output_path = batch_dir / f"textclip_{name}_{idx}.mp4"
    try:
        _concat_clips(tmp_clips, output_path)
    finally:
        for p in tmp_clips:
            p.unlink(missing_ok=True)

    return output_path


def main() -> None:
    console.print(Panel.fit(
        "[bold cyan]Booster — Text+Clips Generator[/bold cyan]",
        border_style="cyan",
    ))

    pool = load_pool()
    if not pool:
        console.print("[red]No clips loaded.[/red]")
        sys.exit(1)

    hook_pool = load_hook_pool()

    existing = sorted(
        [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("batch_")],
        key=lambda d: int(d.name.split("_")[1]) if d.name.split("_")[1].isdigit() else 0,
    )
    next_batch_num = (int(existing[-1].name.split("_")[1]) + 1) if existing else 1
    batch_dir = OUTPUT_DIR / f"batch_{next_batch_num}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"Output folder: [cyan]{batch_dir}[/cyan]\n")

    output_paths: list[Path] = []

    for idx, script in enumerate(SCRIPTS, start=1):
        global_used_ids: set[str] = set()  # fresh pool per video
        console.print(f"[bold]Text+Clip {idx}:[/bold] [cyan]{script['name']}[/cyan]")

        # Fetch a unique track per script
        music_search = script.get("music_search", "NCS no copyright background music")
        console.print(f"  [dim]Fetching music: {music_search}[/dim]")
        music_path = fetch_music(music_search)
        if music_path:
            console.print(f"  [dim]Track: {music_path.name}[/dim]")
        else:
            console.print("  [yellow]Music fetch failed — will be silent[/yellow]")

        try:
            silent_out = build_textclip(script, pool, idx, global_used_ids, batch_dir, hook_pool=hook_pool)
            if silent_out is None:
                continue
            if music_path:
                with_music = silent_out.with_stem(silent_out.stem + "_music")
                add_music(silent_out, music_path, with_music)
                silent_out.unlink(missing_ok=True)
                with_music.rename(silent_out)
                console.print(f"  [dim]Music mixed in at 55% volume[/dim]")
            output_paths.append(silent_out)
            console.print(f"  [green]Saved:[/green] {silent_out}\n")
        except Exception as exc:
            console.print(f"  [red]Failed: {exc}[/red]\n")

    console.print(f"[bold green]Done![/bold green] Produced {len(output_paths)} text+clip(s).")
    for p in output_paths:
        console.print(f"  {p}")


if __name__ == "__main__":
    main()
