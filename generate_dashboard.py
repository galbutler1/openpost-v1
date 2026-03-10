#!/usr/bin/env python3
"""
OpenPost Dashboard Generator  v2
Builds /Users/galbutler/Desktop/openpost_master.html
"""

import os
import json
import base64
import re
from pathlib import Path
from datetime import datetime

# ── paths ─────────────────────────────────────────────────────────────────────
VIDEOS_DIR   = Path("/Users/galbutler/booster/data/videos")
SEGMENTS_DIR = Path("/Users/galbutler/booster/data/segments")
REMIX_LOG    = Path("/Users/galbutler/booster/openpost-v1/remix_log.txt")
LOGO_PATH    = Path("/Users/galbutler/Downloads/OpenPost Logo.png")   # PNG — latest logo
THUMBS_DIR   = Path("/tmp/thumbs")
OUTPUT_PATH  = Path("/Users/galbutler/Desktop/openpost_master.html")

# ── Step 1: Load thumbnails from /tmp/thumbs/ (reuse from prior run) ──────────
THUMBS_DIR.mkdir(parents=True, exist_ok=True)
thumb_b64 = {}
for jpg in THUMBS_DIR.glob("*.jpg"):
    video_id = jpg.stem
    with open(jpg, "rb") as f:
        thumb_b64[video_id] = base64.b64encode(f.read()).decode("ascii")
print(f"Loaded {len(thumb_b64)} cached thumbnails from {THUMBS_DIR}")

# ── Step 2: Embed PNG logo as base64
with open(LOGO_PATH, "rb") as f:
    logo_b64 = base64.b64encode(f.read()).decode("ascii")
logo_mime = "image/png"
print("Logo encoded (PNG)")

# ── Step 3: Load video metadata ───────────────────────────────────────────────
videos = {}
for jf in VIDEOS_DIR.glob("*.json"):
    video_id = jf.stem
    with open(jf) as f:
        data = json.load(f)
    data["video_id"] = video_id
    videos[video_id] = data
print(f"Loaded {len(videos)} video metadata files")

# ── Step 4: Load segment data ─────────────────────────────────────────────────
segments_data = {}
for jf in SEGMENTS_DIR.glob("*.json"):
    video_id = jf.stem
    with open(jf) as f:
        data = json.load(f)
    segments_data[video_id] = data
print(f"Loaded {len(segments_data)} segment files")

# ── Step 5: Sort videos by upload_date ASC → vid_num #001 = oldest ────────────
sorted_videos = sorted(videos.values(), key=lambda v: v.get("upload_date", "00000000"))
for i, v in enumerate(sorted_videos, 1):
    v["vid_num"] = i
video_by_id = {v["video_id"]: v for v in sorted_videos}

# ── Step 6: Parse remix log ────────────────────────────────────────────────────
def parse_remix_log(path: Path):
    text = path.read_text()
    remixes = []
    blocks = re.split(r'\nRemix #(\d+) — Anchor: (\S+)', text)
    i = 1
    while i < len(blocks):
        num    = int(blocks[i])
        anchor = blocks[i+1]
        body   = blocks[i+2]
        i += 3

        upload_date_m = re.search(r'Upload date\s*:\s*(\d+)', body)
        views_m       = re.search(r'Views\s*:\s*([\d,]+)', body)
        likes_m       = re.search(r'Likes:\s*([\d,]+)', body)
        cuts_m        = re.search(r'B-roll cuts\s*:\s*(\d+)\s*/\s*(\d+)', body)
        transcript_m  = re.search(r'Transcript\s*:\s*(.+)', body)

        upload_date = upload_date_m.group(1) if upload_date_m else ""
        views       = int(views_m.group(1).replace(",", "")) if views_m else 0
        likes       = int(likes_m.group(1).replace(",", "")) if likes_m else 0
        num_cuts    = int(cuts_m.group(1)) if cuts_m else 0
        num_windows = int(cuts_m.group(2)) if cuts_m else 0
        transcript  = transcript_m.group(1).strip() if transcript_m else ""

        cuts = []
        cut_pattern = re.compile(
            r'^\s{0,6}(\d+)\s{2,}'
            r'([\d.]+s-[\d.]+s)\s{2,}'
            r'([\d.]+s)\s{2,}'
            r'(\S[\S ]*?)\s{2,}'
            r'(\S[\S ]*?)\s{2,}'
            r'(\S+)\s*$',
            re.MULTILINE
        )
        for m in cut_pattern.finditer(body):
            cuts.append({
                "cut_num":      int(m.group(1)),
                "window":       m.group(2).strip(),
                "duration":     m.group(3).strip(),
                "gap":          m.group(4).strip(),
                "visual_type":  m.group(5).strip(),
                "source_video": m.group(6).strip(),
            })

        remixes.append({
            "remix_num":   num,
            "anchor_id":   anchor,
            "upload_date": upload_date,
            "views":       views,
            "likes":       likes,
            "num_cuts":    num_cuts,
            "num_windows": num_windows,
            "transcript":  transcript,
            "cuts":        cuts,
        })
    return remixes

remixes = parse_remix_log(REMIX_LOG)
print(f"Parsed {len(remixes)} remixes")

# ── Step 7: Topic classification ──────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "product":  ["product","invention","invented","bowl","magnet","hinge","manufacture","patent","sell","ship"],
    "journey":  ["journey","story","struggle","quit","dream","goal","mission","challenge","started"],
    "work":     ["working","building","grinding","packing","warehouse","factory"],
    "success":  ["million","revenue","viral","milestone","accomplished"],
    "emotion":  ["emotional","overwhelmed","scared","grateful"],
}

def classify_topic(transcript: str) -> str:
    t = transcript.lower()
    for topic, kws in TOPIC_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return topic
    return "general"

# ── Step 8: Compute stats ──────────────────────────────────────────────────────
total_remixes  = len(remixes)
total_cuts     = sum(r["num_cuts"] for r in remixes)
unique_sources = set()
for r in remixes:
    for c in r["cuts"]:
        unique_sources.add(c["source_video"])
total_segments = sum(len(s.get("segments", [])) for s in segments_data.values())
most_viewed    = max(sorted_videos, key=lambda v: v.get("view_count", 0))
anchor_ids     = {r["anchor_id"] for r in remixes}

print(f"Stats: remixes={total_remixes}, cuts={total_cuts}, sources={len(unique_sources)}, segments={total_segments}")

# ── Step 9: Utility ────────────────────────────────────────────────────────────
def fmt_date(d):
    s = str(d)
    if len(s) == 8:
        try:
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        except:
            pass
    return s

# ── Step 10: Build JS data objects ────────────────────────────────────────────
js_videos_list = []
for v in sorted_videos:
    vid_id = v["video_id"]
    seg_info = segments_data.get(vid_id, {})
    segs = seg_info.get("segments", [])
    full_transcript = seg_info.get("full_transcript", "")

    js_segs = []
    for s in segs:
        js_segs.append({
            "segment_id":    s.get("segment_id", ""),
            "start":         s.get("start", 0),
            "end":           s.get("end", 0),
            "duration":      s.get("duration", 0),
            "transcript":    s.get("transcript", ""),
            "zone":          s.get("zone", {}).get("value", ""),
            "visual_type":   s.get("visual_type", {}).get("value", ""),
            "quality_score": s.get("quality_score", 0),
            "reusability":   s.get("reusability", {}).get("value", ""),
        })

    visual_types = list(set(s["visual_type"] for s in js_segs if s["visual_type"]))
    topic        = classify_topic(full_transcript)
    thumb        = thumb_b64.get(vid_id, "")

    js_videos_list.append({
        "vid_num":         v["vid_num"],
        "video_id":        vid_id,
        "view_count":      v.get("view_count", 0),
        "like_count":      v.get("like_count", 0),
        "comment_count":   v.get("comment_count", 0),
        "repost_count":    v.get("repost_count", 0),
        "upload_date":     str(v.get("upload_date", "")),
        "upload_date_fmt": fmt_date(v.get("upload_date", "")),
        "is_anchor":       vid_id in anchor_ids,
        "full_transcript": full_transcript,
        "topic":           topic,
        "segments":        js_segs,
        "visual_types":    visual_types,
        "thumb":           thumb,
    })

js_remixes_list = []
for r in remixes:
    js_remixes_list.append({
        "remix_num":       r["remix_num"],
        "anchor_id":       r["anchor_id"],
        "upload_date":     r["upload_date"],
        "upload_date_fmt": fmt_date(r["upload_date"]),
        "views":           r["views"],
        "likes":           r["likes"],
        "num_cuts":        r["num_cuts"],
        "num_windows":     r["num_windows"],
        "transcript":      r["transcript"],
        "cuts":            r["cuts"],
    })

VIDEOS_JSON  = json.dumps(js_videos_list,  separators=(",", ":"))
REMIXES_JSON = json.dumps(js_remixes_list, separators=(",", ":"))

total_views_all = sum(v.get("view_count", 0) for v in sorted_videos)
total_likes_all = sum(v.get("like_count", 0) for v in sorted_videos)

STATS = {
    "total_reels":      len(sorted_videos),
    "total_remixes":    total_remixes,
    "total_cuts":       total_cuts,
    "unique_sources":   len(unique_sources),
    "total_segments":   total_segments,
    "most_viewed_id":   most_viewed["video_id"],
    "most_viewed_num":  most_viewed.get("view_count", 0),
    "total_views_all":  total_views_all,
    "total_likes_all":  total_likes_all,
    "total_followers":  None,  # set manually by user
}
STATS_JSON = json.dumps(STATS, separators=(",", ":"))

# ── Step 11: Render HTML ───────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenPost — Video Intelligence Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0a0a0a;
  --card:#111114;
  --card2:#18181c;
  --border:#1e1e20;
  --border2:#2a2a2e;
  --text:#e8e8e8;
  --text-muted:#666;
  --text-dim:#3a3a3a;
  --accent:#fff;
  --green:#22c55e;
  --orange:#f97316;
  --blue:#6366f1;
  --teal:#14b8a6;
  --yellow:#eab308;
  --red:#ef4444;
  --purple:#a855f7;
  --pink:#ec4899;
}}
html{{scroll-behavior:smooth}}
body{{
  font-family:'Inter',sans-serif;
  background:var(--bg);
  color:var(--text);
  min-height:100vh;
  font-size:14px;
  line-height:1.5;
}}

/* ── Nav ── */
/* ── Top nav ── */
.top-nav{{
  position:fixed;top:0;left:0;right:0;z-index:200;
  height:56px;
  background:rgba(10,10,10,0.88);
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;
  padding:0 28px;
  gap:16px;
}}
.nav-logo-btn{{
  display:flex;align-items:center;gap:0;
  background:none;border:none;cursor:pointer;padding:0;
  flex-shrink:0;
  transition:opacity .15s;
}}
.nav-logo-btn:hover{{opacity:.75}}
.nav-logo-img{{height:22px;width:auto;filter:brightness(0) invert(1)}}
.nav-spacer{{flex:1}}
.nav-auth-btns{{display:flex;gap:8px;align-items:center}}
.nav-login-btn{{
  padding:7px 18px;
  border-radius:8px;
  border:1px solid var(--border);
  background:transparent;
  color:var(--text-muted);
  font-family:'Inter',sans-serif;font-size:13px;font-weight:500;
  cursor:pointer;transition:all .15s;
}}
.nav-login-btn:hover{{color:#fff;border-color:#444}}
.nav-signup-btn{{
  padding:7px 18px;
  border-radius:8px;
  border:1px solid rgba(255,255,255,.85);
  background:#fff;
  color:#000;
  font-family:'Inter',sans-serif;font-size:13px;font-weight:700;
  cursor:pointer;transition:all .15s;
  letter-spacing:.1px;
}}
.nav-signup-btn:hover{{background:#e8e8e8;border-color:#e8e8e8}}

/* push content below fixed nav */
body{{padding-top:56px}}

/* ── View transitions ── */
.view{{
  display:none;
  opacity:0;
  transition:opacity .22s ease;
}}
.view.active{{
  display:block;
  animation:viewFadeIn .22s ease forwards;
}}
@keyframes viewFadeIn{{from{{opacity:0;transform:translateY(5px)}}to{{opacity:1;transform:translateY(0)}}}}

/* ── HOME ── */
.hero{{
  display:flex;flex-direction:column;align-items:center;
  padding:72px 24px 56px;
  text-align:center;
}}
.hero-logo{{width:180px;height:auto;margin-bottom:24px;display:block}}
.hero-sub{{font-size:15px;color:var(--text-muted);font-weight:400;margin-top:4px}}

/* ── Vanity row (views / likes / followers) ── */
.vanity-row{{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:20px;
  padding:0 32px 24px;
  max-width:1400px;margin:0 auto;
}}
.vanity-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:12px;
  padding:32px 24px;
  text-align:center;
}}
.vanity-num{{font-size:64px;font-weight:900;letter-spacing:-3px;color:#fff;line-height:1;margin-bottom:10px}}
.vanity-label{{font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;font-weight:600}}

/* ── 3 clickable stat cards ── */
.stats-grid{{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:14px;
  padding:0 32px 48px;
  max-width:1400px;margin:0 auto;
}}
@media(max-width:700px){{.stats-grid{{grid-template-columns:1fr}}}}

.stat-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  padding:28px 20px;
  text-align:center;
  transition:border-color .15s,transform .15s,background .15s;
  cursor:pointer;
  position:relative;
  display:flex;
  flex-direction:column;
  align-items:center;
}}
.stat-card:hover{{border-color:#fff3;background:#161618;transform:translateY(-3px)}}
.stat-card:active{{transform:translateY(0)}}
.stat-num{{font-size:52px;font-weight:800;letter-spacing:-2px;color:#fff;line-height:1;margin-bottom:8px}}
.stat-label{{font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.9px;font-weight:600}}
.stat-arrow{{position:absolute;bottom:14px;right:18px;font-size:16px;color:#444;transition:color .15s,transform .15s}}
.stat-card:hover .stat-arrow{{color:#888;transform:translateX(3px)}}

.home-section-header{{
  max-width:1400px;margin:0 auto;
  padding:0 32px 12px;
  display:flex;align-items:baseline;gap:12px;
}}
.home-section-title{{font-size:16px;font-weight:700;color:#fff}}
.home-section-sub{{font-size:13px;color:var(--text-muted)}}

.activity-list{{
  max-width:1400px;margin:0 auto;
  padding:0 32px 64px;
  display:flex;flex-direction:column;gap:8px;
}}
.activity-item{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  padding:14px 18px;
  display:flex;align-items:center;gap:16px;
  cursor:pointer;
  transition:border-color .15s,background .15s;
}}
.activity-item:hover{{border-color:var(--border2);background:var(--card2)}}
.activity-num{{font-size:11px;font-weight:700;color:var(--text-muted);min-width:68px}}
.activity-anchor{{font-size:13px;font-weight:600;color:#fff;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:monospace}}
.activity-transcript{{font-size:12px;color:var(--text-muted);flex:3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.activity-meta{{display:flex;flex-direction:column;align-items:flex-end;gap:4px;white-space:nowrap}}
.cut-badge{{
  background:rgba(34,197,94,.12);
  border:1px solid rgba(34,197,94,.25);
  color:var(--green);
  border-radius:6px;
  padding:3px 9px;
  font-size:11px;font-weight:600;
}}

/* ── LIBRARY ── */
/* Brand hero — big logo section at top */
.brand-header{{
  min-height:52vh;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:96px 32px 72px;
  text-align:center;
  border-bottom:1px solid var(--border);
}}
.brand-logo{{width:360px;max-width:80vw;height:auto;display:block;
  filter:brightness(0) invert(1);
  margin-bottom:14px;
}}
.brand-tagline{{font-size:18px;color:#fff;font-weight:500;letter-spacing:.1px;margin-bottom:48px}}
.brand-description{{display:none}}
.hero-vanity-row{{
  display:flex;gap:0;align-items:stretch;justify-content:center;
  flex-wrap:wrap;
  background:var(--card);
  border:1px solid var(--border);
  border-radius:14px;
  overflow:hidden;
}}
.hero-vanity-item{{
  text-align:center;
  padding:22px 40px;
  position:relative;
}}
.hero-vanity-item+.hero-vanity-item::before{{
  content:'';position:absolute;left:0;top:20%;height:60%;
  width:1px;background:var(--border);
}}
.hero-vanity-num{{font-size:26px;font-weight:800;letter-spacing:-1px;line-height:1;margin-bottom:5px}}
.hero-vanity-num.green{{color:#4ade80}}
.hero-vanity-num.blue{{color:#818cf8}}
.hero-vanity-num.teal{{color:#2dd4bf}}
.hero-vanity-label{{font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;font-weight:600}}

.library-header{{
  position:sticky;top:0;z-index:100;
  background:rgba(10,10,10,0.96);
  backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
  border-bottom:1px solid var(--border);
  padding:14px 32px;
  display:flex;align-items:center;gap:12px;
  flex-wrap:wrap;
}}
.search-input{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  padding:9px 14px;
  color:var(--text);
  font-family:'Inter',sans-serif;font-size:14px;
  width:300px;
  outline:none;
  transition:border-color .15s;
}}
.search-input::placeholder{{color:#3a3a3a}}
.search-input:focus{{border-color:#444}}
.filter-btns{{display:flex;gap:6px}}
.filter-btn{{
  padding:8px 16px;
  border-radius:8px;
  border:1px solid var(--border);
  background:var(--card);
  color:var(--text-muted);
  font-family:'Inter',sans-serif;font-size:13px;font-weight:500;
  cursor:pointer;transition:all .15s;
  white-space:nowrap;
}}
.filter-btn:hover{{color:var(--text);border-color:#444}}
.filter-btn.active{{background:rgba(255,255,255,.1);color:#fff;border-color:#555;font-weight:600}}
.filter-btn-count{{font-size:11px;color:inherit;opacity:.6;margin-left:4px}}
.filter-btn.active .filter-btn-count{{opacity:.7}}
.create-btn{{
  padding:8px 20px;
  border-radius:8px;
  border:1px solid rgba(255,255,255,.8);
  background:#fff;
  color:#000;
  font-family:'Inter',sans-serif;font-size:13px;font-weight:700;
  cursor:pointer;transition:all .15s;
  letter-spacing:.2px;
  white-space:nowrap;
}}
.create-btn:hover{{background:#e8e8e8;border-color:#e8e8e8;transform:translateY(-1px)}}
.create-btn:active{{transform:translateY(0)}}
.library-section-header{{
  max-width:1800px;margin:0 auto;
  padding:28px 32px 8px;
  display:flex;align-items:baseline;gap:10px;
}}
.library-section-title{{font-size:20px;font-weight:700;color:#fff;letter-spacing:-.3px}}
.library-count{{margin-left:auto;font-size:13px;color:var(--text-muted);font-weight:500}}
.clips-mode-btn{{
  padding:8px 16px;
  border-radius:8px;
  border:1px solid var(--border);
  background:var(--card);
  color:var(--text-muted);
  font-family:'Inter',sans-serif;font-size:13px;font-weight:500;
  cursor:pointer;transition:all .15s;
  white-space:nowrap;
  margin-left:6px;
}}
.clips-mode-btn:hover{{color:#fff;border-color:#444}}
.clips-mode-btn.active{{background:rgba(99,102,241,.15);color:#818cf8;border-color:rgba(99,102,241,.4);font-weight:600}}
.broll-mode-btn{{
  padding:8px 16px;
  border-radius:8px;
  border:1px solid var(--border);
  background:var(--card);
  color:var(--text-muted);
  font-family:'Inter',sans-serif;font-size:13px;font-weight:500;
  cursor:pointer;transition:all .15s;
  white-space:nowrap;
  margin-left:6px;
}}
.broll-mode-btn:hover{{color:#fff;border-color:#444}}
.broll-mode-btn.active{{background:rgba(20,184,166,.12);color:#2dd4bf;border-color:rgba(20,184,166,.35);font-weight:600}}

/* ── Clips grid ── */
.clips-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
  gap:12px;
  padding:20px 32px 48px;
  max-width:1800px;margin:0 auto;
}}
.clip-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  overflow:hidden;
  cursor:pointer;
  transition:transform .18s,box-shadow .18s,border-color .18s;
  position:relative;
}}
.clip-card:hover{{transform:translateY(-4px);box-shadow:0 12px 32px rgba(0,0,0,.5);border-color:var(--border2)}}
.clip-name-badge{{
  position:absolute;top:8px;left:8px;
  background:rgba(0,0,0,.78);
  backdrop-filter:blur(4px);
  color:#fff;font-size:10px;font-weight:700;
  padding:3px 8px;border-radius:6px;
  font-family:monospace;letter-spacing:.4px;
  max-width:calc(100% - 16px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}}
.clip-play-overlay{{
  position:absolute;inset:0;
  display:flex;align-items:center;justify-content:center;
  opacity:0;transition:opacity .2s;
  background:rgba(0,0,0,.28);
}}
.clip-card:hover .clip-play-overlay{{opacity:1}}
.clip-play-circle{{
  width:44px;height:44px;border-radius:50%;
  background:rgba(255,255,255,.15);
  backdrop-filter:blur(6px);
  border:1.5px solid rgba(255,255,255,.35);
  display:flex;align-items:center;justify-content:center;
}}
.clip-body{{padding:9px 11px}}
.clip-name-text{{font-size:11px;font-weight:700;color:#fff;font-family:monospace;margin-bottom:3px}}
.clip-vt{{font-size:10px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px}}
.clip-qs-row{{display:flex;align-items:center;gap:6px}}
.clip-dur{{font-size:10px;color:#3a3a3a;font-family:monospace}}

/* ── B-Roll analytical grid ── */
.broll-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:16px;
  padding:20px 32px 48px;
  max-width:1800px;margin:0 auto;
}}
.broll-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:12px;
  overflow:hidden;
  display:flex;
  flex-direction:column;
  transition:border-color .18s,box-shadow .18s;
}}
.broll-card:hover{{border-color:var(--border2);box-shadow:0 8px 28px rgba(0,0,0,.4)}}
.broll-card-top{{display:flex;gap:0;align-items:stretch}}
.broll-thumb-col{{
  width:90px;flex-shrink:0;position:relative;cursor:pointer;
}}
.broll-thumb-col:hover .clip-play-overlay{{opacity:1}}
.broll-thumb-img{{width:100%;height:100%;object-fit:cover;display:block;min-height:130px}}
.broll-thumb-placeholder{{
  width:100%;height:100%;min-height:130px;
  display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,#111,#1a1a1e);color:#2a2a2a;font-size:22px;
}}
.broll-info-col{{flex:1;padding:12px 14px;min-width:0}}
.broll-clip-name{{font-size:13px;font-weight:800;color:#fff;font-family:monospace;margin-bottom:4px}}
.broll-vt{{font-size:11px;margin-bottom:10px}}
.broll-vt-pill{{
  display:inline-block;padding:3px 9px;border-radius:20px;
  font-size:10px;font-weight:700;letter-spacing:.3px;
}}
.vt-product{{background:rgba(99,102,241,.15);color:#818cf8;border:1px solid rgba(99,102,241,.3)}}
.vt-founder{{background:rgba(99,149,255,.12);color:#93c5fd;border:1px solid rgba(99,149,255,.25)}}
.vt-outdoor{{background:rgba(20,184,166,.12);color:#2dd4bf;border:1px solid rgba(20,184,166,.25)}}
.vt-work{{background:rgba(234,179,8,.12);color:#fbbf24;border:1px solid rgba(234,179,8,.25)}}
.vt-excited{{background:rgba(236,72,153,.12);color:#f472b6;border:1px solid rgba(236,72,153,.25)}}
.vt-other{{background:rgba(255,255,255,.06);color:#888;border:1px solid var(--border)}}
/* score bars */
.score-rows{{display:flex;flex-direction:column;gap:6px}}
.score-row{{display:flex;align-items:center;gap:8px}}
.score-lbl{{font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.6px;font-weight:700;width:62px;flex-shrink:0}}
.score-bar-track{{flex:1;height:5px;background:#1e1e22;border-radius:3px;overflow:hidden}}
.score-bar-fill{{height:100%;border-radius:3px;transition:width .4s ease}}
.fill-green{{background:linear-gradient(90deg,#16a34a,#4ade80)}}
.fill-blue{{background:linear-gradient(90deg,#4338ca,#818cf8)}}
.fill-teal{{background:linear-gradient(90deg,#0d9488,#2dd4bf)}}
.fill-orange{{background:linear-gradient(90deg,#c2410c,#fb923c)}}
.fill-gray{{background:#333}}
.score-val{{font-size:10px;font-weight:700;color:#fff;width:26px;text-align:right;flex-shrink:0;font-family:monospace}}
.reu-badge{{
  display:inline-block;padding:2px 7px;border-radius:4px;
  font-size:9px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;
}}
.reu-high{{background:rgba(34,197,94,.15);color:#4ade80}}
.reu-medium{{background:rgba(234,179,8,.12);color:#fbbf24}}
.reu-low{{background:rgba(239,68,68,.1);color:#f87171}}
.reu-none{{background:rgba(255,255,255,.05);color:#555}}
.broll-card-bottom{{
  padding:10px 14px;
  border-top:1px solid var(--border);
  background:rgba(255,255,255,.015);
}}
.broll-transcript{{font-size:11px;color:#555;line-height:1.5;font-style:italic}}
.broll-meta-row{{
  display:flex;gap:12px;align-items:center;
  font-size:10px;color:var(--text-muted);
  margin-bottom:6px;
}}
.broll-meta-row span{{font-family:monospace}}

/* ── Enhanced blueprint cuts (card style) ── */
.bp-cuts-list{{display:flex;flex-direction:column;gap:10px;padding:14px 18px}}
.bp-cut-card{{
  display:flex;align-items:stretch;gap:0;
  background:var(--card2);
  border:1px solid var(--border);
  border-radius:10px;
  overflow:hidden;
  transition:border-color .15s;
}}
.bp-cut-card:hover{{border-color:var(--border2)}}
.bp-cut-thumb{{
  width:52px;flex-shrink:0;position:relative;cursor:pointer;
  background:#0d0d10;
}}
.bp-cut-thumb:hover .bp-thumb-play{{opacity:1}}
.bp-cut-thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
.bp-cut-thumb-placeholder{{width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#2a2a2a;font-size:16px}}
.bp-thumb-play{{
  position:absolute;inset:0;
  display:flex;align-items:center;justify-content:center;
  background:rgba(0,0,0,.45);
  opacity:0;transition:opacity .18s;
}}
.bp-cut-body{{flex:1;padding:10px 14px;min-width:0}}
.bp-cut-header{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.bp-cut-num{{font-size:10px;color:var(--text-muted);font-weight:700}}
.bp-cut-name{{font-size:12px;font-weight:800;color:#fff;font-family:monospace}}
.bp-cut-window{{font-size:11px;color:var(--text-muted);font-family:monospace;margin-left:auto}}
.bp-cut-details{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.bp-cut-ig{{
  font-size:10px;color:#818cf8;text-decoration:none;
  font-family:monospace;
  margin-left:auto;
  transition:color .15s;
}}
.bp-cut-ig:hover{{color:#a5b4fc;text-decoration:underline}}

/* blueprint play btn */
.bp-play-btn{{
  display:inline-flex;align-items:center;justify-content:center;
  width:24px;height:24px;border-radius:50%;
  background:rgba(255,255,255,.07);
  border:1px solid var(--border2);
  color:#888;cursor:pointer;
  transition:background .15s,color .15s,border-color .15s;
  flex-shrink:0;
  vertical-align:middle;
}}
.bp-play-btn:hover{{background:rgba(99,102,241,.2);border-color:rgba(99,102,241,.5);color:#818cf8}}
.bp-play-btn svg{{width:10px;height:10px;fill:currentColor}}

/* ── Video modal ── */
.modal-overlay{{
  position:fixed;inset:0;z-index:500;
  background:rgba(0,0,0,.85);
  backdrop-filter:blur(10px);
  display:none;align-items:center;justify-content:center;
  padding:24px;
}}
.modal-overlay.open{{display:flex}}
.modal-box{{
  background:#111114;
  border:1px solid var(--border2);
  border-radius:16px;
  overflow:hidden;
  max-width:400px;width:100%;
  box-shadow:0 32px 80px rgba(0,0,0,.6);
  position:relative;
}}
.modal-header{{
  display:flex;align-items:center;justify-content:space-between;
  padding:14px 18px 12px;
  border-bottom:1px solid var(--border);
  gap:12px;
}}
.modal-title{{font-size:13px;font-weight:700;color:#fff;font-family:monospace;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.modal-meta{{font-size:11px;color:var(--text-muted);white-space:nowrap}}
.modal-close{{
  background:none;border:none;color:var(--text-muted);
  cursor:pointer;font-size:22px;line-height:1;padding:0;
  transition:color .15s;flex-shrink:0;
}}
.modal-close:hover{{color:#fff}}
.modal-video{{width:100%;display:block;aspect-ratio:9/16;background:#000;outline:none}}

.video-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
  gap:14px;
  padding:20px 32px 48px;
  max-width:1800px;margin:0 auto;
}}
@media(max-width:900px){{.video-grid{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:600px){{.video-grid{{grid-template-columns:repeat(2,1fr)}}}}

.video-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  overflow:hidden;
  cursor:pointer;
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;
}}
.video-card:hover{{
  transform:translateY(-4px);
  box-shadow:0 12px 36px rgba(0,0,0,.55);
  border-color:var(--border2);
}}
.thumb-wrap{{
  position:relative;
  aspect-ratio:9/16;
  overflow:hidden;
  background:#0d0d10;
}}
.thumb-img{{width:100%;height:100%;object-fit:cover;display:block}}
.thumb-placeholder{{
  width:100%;height:100%;
  display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,#111,#1a1a1e);
  color:#2a2a2a;font-size:32px;
}}
.vid-num-badge{{
  position:absolute;top:8px;left:8px;
  background:rgba(0,0,0,.72);
  backdrop-filter:blur(4px);
  color:#fff;font-size:10px;font-weight:700;
  padding:3px 7px;border-radius:6px;
  letter-spacing:.5px;
}}
.remixed-badge{{
  position:absolute;top:8px;right:8px;
  background:rgba(34,197,94,.18);
  border:1px solid rgba(34,197,94,.4);
  color:var(--green);font-size:9px;font-weight:800;
  padding:3px 7px;border-radius:6px;
  text-transform:uppercase;letter-spacing:.6px;
}}
.card-body{{padding:10px 12px}}
.card-meta{{
  display:flex;gap:10px;
  font-size:12px;color:var(--text-muted);
  margin-bottom:7px;
}}
.card-transcript{{
  font-size:11px;color:var(--text-muted);
  display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden;
  line-height:1.5;
}}
.card-date{{font-size:10px;color:#333;margin-top:5px;font-weight:500}}

/* ── DETAIL ── */
.detail-wrap{{max-width:1280px;margin:0 auto;padding:28px 32px 64px}}
.back-btn{{
  display:inline-flex;align-items:center;gap:7px;
  color:var(--text-muted);font-size:13px;font-weight:500;
  cursor:pointer;background:none;border:none;
  padding:8px 0;margin-bottom:22px;
  font-family:'Inter',sans-serif;
  transition:color .15s;
}}
.back-btn:hover{{color:#fff}}
.back-btn svg{{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2}}

.detail-layout{{
  display:grid;
  grid-template-columns:380px 1fr;
  gap:32px;
  align-items:start;
}}
/* detail-layout always desktop 2-col */

/* Left column */
.detail-left{{position:sticky;top:76px}}
.detail-thumb-wrap{{
  aspect-ratio:9/16;
  border-radius:10px;overflow:hidden;
  background:#0d0d10;
  border:1px solid var(--border);
  cursor:pointer;
  position:relative;
}}
.detail-thumb-wrap:hover .play-overlay{{opacity:1}}
.play-overlay{{
  position:absolute;inset:0;
  background:rgba(0,0,0,.28);
  display:flex;align-items:center;justify-content:center;
  opacity:0;transition:opacity .2s;
}}
.play-icon{{
  width:54px;height:54px;
  background:rgba(255,255,255,.15);
  backdrop-filter:blur(6px);
  border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  border:1.5px solid rgba(255,255,255,.3);
}}
.detail-thumb-img{{width:100%;height:100%;object-fit:cover}}

.detail-meta-block{{padding:16px 0 12px}}
.detail-id-row{{
  display:flex;align-items:center;gap:8px;
  margin-bottom:12px;flex-wrap:wrap;
}}
.detail-vid-num{{font-size:12px;color:var(--text-muted);font-weight:700;letter-spacing:.4px}}
.detail-vid-id{{font-size:12px;color:#3a3a3a;font-family:monospace}}
.detail-ig-btn{{
  display:inline-flex;align-items:center;gap:6px;
  margin-top:2px;
  background:rgba(99,102,241,.12);
  border:1px solid rgba(99,102,241,.3);
  color:#818cf8;
  border-radius:8px;
  padding:7px 14px;
  font-size:12px;font-weight:600;
  cursor:pointer;text-decoration:none;
  font-family:'Inter',sans-serif;
  transition:background .15s,border-color .15s;
}}
.detail-ig-btn:hover{{background:rgba(99,102,241,.2);border-color:rgba(99,102,241,.5)}}

.detail-stats-grid{{
  display:grid;grid-template-columns:1fr 1fr;
  gap:8px;margin:14px 0;
}}
.detail-stat-card{{
  background:var(--card2);
  border:1px solid var(--border);
  border-radius:8px;
  padding:10px 12px;
}}
.detail-stat-val{{font-size:18px;font-weight:700;color:#fff;line-height:1}}
.detail-stat-lbl{{font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.6px;margin-top:3px;font-weight:600}}

.detail-meta-label{{font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.7px;font-weight:700;margin-bottom:7px}}
.detail-meta-section{{margin-bottom:16px}}

.topic-pill{{
  display:inline-block;
  padding:4px 12px;border-radius:20px;
  font-size:12px;font-weight:700;
  letter-spacing:.4px;
  text-transform:capitalize;
  border:1px solid;
}}
.topic-product{{background:rgba(99,102,241,.12);color:#818cf8;border-color:rgba(99,102,241,.3)}}
.topic-journey{{background:rgba(234,179,8,.12);color:#fbbf24;border-color:rgba(234,179,8,.3)}}
.topic-work{{background:rgba(20,184,166,.12);color:#2dd4bf;border-color:rgba(20,184,166,.3)}}
.topic-success{{background:rgba(34,197,94,.12);color:#4ade80;border-color:rgba(34,197,94,.3)}}
.topic-emotion{{background:rgba(239,68,68,.12);color:#f87171;border-color:rgba(239,68,68,.3)}}
.topic-general{{background:rgba(255,255,255,.06);color:var(--text-muted);border-color:var(--border)}}

.vt-pill{{
  display:inline-block;
  padding:3px 9px;border-radius:20px;
  font-size:11px;font-weight:500;
  background:rgba(255,255,255,.05);
  color:var(--text-muted);
  border:1px solid var(--border);
  margin:2px;
}}
.tags-wrap{{display:flex;flex-wrap:wrap;gap:4px}}

/* Right column — transcript */
.transcript-col{{}}
.section-heading{{
  font-size:16px;font-weight:700;color:#fff;
  margin-bottom:14px;
  padding-bottom:10px;
  border-bottom:1px solid var(--border);
}}
.section-subheading{{
  font-size:13px;font-weight:600;color:var(--text-muted);
  margin:20px 0 10px;
  text-transform:uppercase;letter-spacing:.6px;font-size:11px;
}}

.segment-block{{
  display:flex;
  border-radius:10px;
  overflow:hidden;
  margin-bottom:8px;
  background:var(--card);
  border:1px solid var(--border);
  transition:border-color .15s;
}}
.segment-block:hover{{border-color:var(--border2)}}
/* color-coded left bar */
.seg-bar{{width:4px;flex-shrink:0}}
/* hook → orange */
.zone-hook .seg-bar{{background:#f90}}
/* cta → gray */
.zone-cta .seg-bar{{background:#555}}
/* body + product* → green */
.zone-body-product .seg-bar{{background:#4c4}}
/* body + founder-talking (non-excited) → blue */
.zone-body-founder .seg-bar{{background:#68f}}
/* body + outdoor/lifestyle → teal */
.zone-body-outdoor .seg-bar{{background:#4cc}}
/* body + working/workspace → yellow */
.zone-body-work .seg-bar{{background:#cc8}}
/* body + celebrating/founder-talking-excited → pink */
.zone-body-excited .seg-bar{{background:#f6a}}
/* body + split-screen → purple */
.zone-body-split .seg-bar{{background:#c8f}}
/* body + other → light gray */
.zone-body-other .seg-bar{{background:#888}}

.seg-content{{padding:10px 14px;flex:1;min-width:0}}
.seg-header{{display:flex;align-items:center;gap:7px;margin-bottom:6px;flex-wrap:wrap}}
.seg-time{{font-size:11px;color:var(--text-muted);font-family:monospace;font-weight:600}}
.seg-zone-badge{{
  font-size:9px;font-weight:800;letter-spacing:.8px;text-transform:uppercase;
  padding:2px 7px;border-radius:4px;
}}
.zone-hook .seg-zone-badge{{background:rgba(255,153,0,.15);color:#f90}}
.zone-body-product .seg-zone-badge,
.zone-body-founder .seg-zone-badge,
.zone-body-outdoor .seg-zone-badge,
.zone-body-work .seg-zone-badge,
.zone-body-excited .seg-zone-badge,
.zone-body-split .seg-zone-badge,
.zone-body-other .seg-zone-badge{{background:rgba(100,100,255,.12);color:#aaf}}
.zone-cta .seg-zone-badge{{background:rgba(80,80,80,.25);color:#888}}

.seg-vt-badge{{
  font-size:10px;color:#555;
  background:rgba(255,255,255,.03);
  border:1px solid #1e1e20;
  border-radius:4px;padding:1px 6px;
}}
.seg-qs{{
  margin-left:auto;
  font-size:10px;font-weight:700;
  padding:2px 7px;border-radius:4px;
  flex-shrink:0;
}}
.seg-qs-high{{background:rgba(34,197,94,.12);color:#4ade80}}
.seg-qs-med{{background:rgba(234,179,8,.12);color:#fbbf24}}
.seg-qs-low{{background:rgba(239,68,68,.1);color:#f87171}}
.seg-text{{font-size:13px;color:var(--text);line-height:1.55}}

/* Remix section */
.remix-section{{
  margin-top:28px;
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  overflow:hidden;
}}
.remix-section-header{{
  padding:14px 18px;
  border-bottom:1px solid var(--border);
  background:rgba(34,197,94,.04);
  display:flex;align-items:center;gap:10px;
}}
.remix-dot{{width:8px;height:8px;border-radius:50%;background:var(--green);flex-shrink:0}}
.remix-section-title{{font-size:14px;font-weight:700;color:#fff}}
.remix-badge-num{{
  margin-left:auto;
  background:rgba(34,197,94,.12);
  border:1px solid rgba(34,197,94,.25);
  color:var(--green);
  border-radius:6px;
  padding:3px 9px;font-size:11px;font-weight:700;
}}
.remix-stats-row{{
  display:flex;gap:16px;
  padding:10px 18px;
  border-bottom:1px solid var(--border);
  flex-wrap:wrap;
}}
.remix-stat{{font-size:12px;color:var(--text-muted)}}
.remix-stat strong{{color:#fff}}

.cuts-table{{width:100%;border-collapse:collapse}}
.cuts-table th{{
  font-size:10px;font-weight:700;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.6px;
  padding:9px 14px;text-align:left;
  border-bottom:1px solid var(--border);
  background:rgba(255,255,255,.02);
}}
.cuts-table td{{
  padding:9px 14px;font-size:12px;
  border-bottom:1px solid rgba(255,255,255,.03);
  vertical-align:middle;
}}
.cuts-table tr:last-child td{{border-bottom:none}}
.cuts-table tr:hover td{{background:rgba(255,255,255,.02)}}
.cut-num-cell{{color:var(--text-muted);font-weight:700;font-size:11px}}
.cut-window-cell{{font-family:monospace;font-size:11px;color:#fff;white-space:nowrap}}
.cut-vt-pill{{
  display:inline-block;
  padding:2px 8px;border-radius:6px;
  font-size:10px;font-weight:600;
  background:rgba(255,255,255,.06);
  border:1px solid var(--border);
  color:var(--text-muted);
  white-space:nowrap;
}}
.cut-src-link{{
  color:#818cf8;text-decoration:none;font-family:monospace;font-size:11px;
  transition:color .15s;
}}
.cut-src-link:hover{{color:#a5b4fc;text-decoration:underline}}

/* Scrollbar */
::-webkit-scrollbar{{width:5px;height:5px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:#222;border-radius:3px}}
::-webkit-scrollbar-thumb:hover{{background:#333}}

/* Empty state */
.empty-state{{
  text-align:center;padding:80px 24px;
  color:var(--text-muted);
  grid-column:1/-1;
}}
.empty-state-icon{{font-size:40px;margin-bottom:12px;opacity:.3}}
.empty-state-text{{font-size:15px;font-weight:500}}
</style>
</head>
<body>

<!-- Top nav — fixed across all views -->
<nav class="top-nav">
  <button class="nav-logo-btn" onclick="showView('library')">
    <img src="data:{logo_mime};base64,{logo_b64}" class="nav-logo-img" alt="OpenPost">
  </button>
  <div class="nav-spacer"></div>
  <div class="nav-auth-btns">
    <button class="nav-login-btn">Log in</button>
    <button class="nav-signup-btn">Sign up</button>
  </div>
</nav>

<!-- LIBRARY VIEW (main / default) -->
<div id="view-library" class="view active">

  <!-- Brand hero header -->
  <div class="brand-header">
    <img src="data:{logo_mime};base64,{logo_b64}" class="brand-logo" alt="OpenPost">
    <div class="brand-tagline">Truly automated media growth</div>
    <div class="brand-description">Your content, remixed and ready to post — automatically.</div>
    <div class="hero-vanity-row" id="hero-vanity-row">
      <!-- populated by JS -->
    </div>
  </div>

  <!-- Library section header -->
  <div class="library-section-header">
    <div class="library-section-title">Library</div>
  </div>

  <!-- Sticky search + filter bar -->
  <div class="library-header">
    <input type="text" class="search-input" placeholder="Search by transcript, ID, date…" id="search-input" oninput="filterLibrary()">
    <div class="filter-btns">
      <button class="filter-btn active" data-filter="all" onclick="setFilter('all')" id="filter-all">All<span class="filter-btn-count" id="count-all"></span></button>
      <button class="filter-btn" data-filter="remixed" onclick="setFilter('remixed')" id="filter-remixed">Remixed<span class="filter-btn-count" id="count-remixed"></span></button>
      <button class="filter-btn" data-filter="unused" onclick="setFilter('unused')" id="filter-unused">Unused<span class="filter-btn-count" id="count-unused"></span></button>
    </div>
    <button class="clips-mode-btn" id="clips-mode-btn" onclick="toggleClipsMode()">Clips<span class="filter-btn-count" id="count-clips"></span></button>
    <button class="broll-mode-btn" id="broll-mode-btn" onclick="toggleBrollMode()">B-Roll<span class="filter-btn-count" id="count-broll"></span></button>
    <button class="create-btn">+ Create</button>
    <span class="library-count" id="library-count"></span>
  </div>
  <div class="video-grid" id="video-grid"></div>
  <div class="clips-grid" id="clips-grid" style="display:none"></div>
  <div class="broll-grid" id="broll-grid" style="display:none"></div>
</div>

<!-- Video modal -->
<div class="modal-overlay" id="video-modal" onclick="if(event.target===this)closeModal()">
  <div class="modal-box">
    <div class="modal-header">
      <div class="modal-title" id="modal-title"></div>
      <div class="modal-meta" id="modal-meta"></div>
      <button class="modal-close" onclick="closeModal()">&#xd7;</button>
    </div>
    <video class="modal-video" id="modal-video" controls playsinline></video>
  </div>
</div>

<!-- DETAIL VIEW -->
<div id="view-detail" class="view">
  <div class="detail-wrap">
    <button class="back-btn" id="back-btn" onclick="goBack()">
      <svg viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"/></svg>
      <span id="back-label">Back to Library</span>
    </button>
    <div id="detail-content"></div>
  </div>
</div>

<script>
// ── Data ──────────────────────────────────────────────────────────────────────
const VIDEOS = {VIDEOS_JSON};
const REMIXES = {REMIXES_JSON};
const STATS = {STATS_JSON};

const VIDEOS_BASE = 'file:///Users/galbutler/booster/data/videos/';

const videoById = {{}};
VIDEOS.forEach(v => videoById[v.video_id] = v);
const remixByAnchor = {{}};
REMIXES.forEach(r => remixByAnchor[r.anchor_id] = r);

// ── Clips index — all body segments across every video ─────────────────────
const CLIPS = [];
const segsByVideo = {{}};   // video_id → segments[]
VIDEOS.forEach(v => {{
  segsByVideo[v.video_id] = v.segments || [];
  const bodySegs = (v.segments || []).filter(s =>
    s.zone === 'body' && s.visual_type && s.quality_score >= 20
  );
  bodySegs.forEach((s, i) => {{
    CLIPS.push({{
      clip_id:     v.video_id + '__' + s.segment_id,
      clip_name:   '#' + String(v.vid_num).padStart(3,'0') + ':' + (i+1),
      video_id:    v.video_id,
      vid_num:     v.vid_num,
      start:       s.start,
      end:         s.end,
      duration:    s.duration,
      visual_type: s.visual_type,
      quality_score: s.quality_score,
      reusability: s.reusability,
      transcript:  s.transcript,
      thumb:       v.thumb,
    }});
  }});
}});

// For blueprint: find a segment's start time given video_id + visual_type
function findSegTime(videoId, visualType) {{
  const segs = segsByVideo[videoId] || [];
  const m = segs.find(s => s.zone === 'body' && s.visual_type === visualType);
  return m ? {{start: m.start, end: m.end}} : null;
}}

// ── Utilities ─────────────────────────────────────────────────────────────────
function fmtNum(n) {{
  if (n >= 1000000) return (n/1000000).toFixed(1) + 'M';
  if (n >= 1000)    return (n/1000).toFixed(1) + 'K';
  return n.toLocaleString();
}}
function fmtNumFull(n) {{ return (n||0).toLocaleString(); }}
function vidNumStr(n) {{ return '#' + String(n).padStart(3,'0'); }}
function escHtml(s) {{
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}
function thumbSrc(vid) {{
  return vid.thumb ? 'data:image/jpeg;base64,' + vid.thumb : null;
}}

// Segment zone → CSS class suffix
function segZoneClass(zone, vt) {{
  const z = (zone||'').toLowerCase();
  const v = (vt||'').toLowerCase();
  if (z === 'hook') return 'hook';
  if (z === 'cta')  return 'cta';
  if (z.startsWith('body')) {{
    if (v.startsWith('product'))                               return 'body-product';
    if (v === 'founder-talking-excited' || v === 'celebrating') return 'body-excited';
    if (v.startsWith('founder-talking'))                       return 'body-founder';
    if (v === 'outdoor' || v === 'lifestyle')                  return 'body-outdoor';
    if (v === 'working' || v === 'workspace')                  return 'body-work';
    if (v === 'split-screen')                                  return 'body-split';
    return 'body-other';
  }}
  return 'body-other';
}}
function zoneLabel(zone) {{
  if (!zone) return '';
  if (zone === 'hook') return 'HOOK';
  if (zone === 'cta')  return 'CTA';
  if (zone.startsWith('body')) return 'BODY';
  return zone.toUpperCase();
}}
function qsClass(score) {{
  if (score >= 70) return 'seg-qs-high';
  if (score >= 45) return 'seg-qs-med';
  return 'seg-qs-low';
}}

// ── Modal ──────────────────────────────────────────────────────────────────────
function openClip(videoId, start, end, label, meta) {{
  const vid = document.getElementById('modal-video');
  const src = VIDEOS_BASE + videoId + '.mp4';
  vid.src = src;
  vid.load();
  vid.addEventListener('loadedmetadata', function onLoad() {{
    vid.currentTime = start || 0;
    vid.play().catch(() => {{}});
    vid.removeEventListener('loadedmetadata', onLoad);
  }}, {{once: true}});
  // Pause near end of clip
  const clipEnd = end || 9999;
  vid.ontimeupdate = () => {{ if (vid.currentTime >= clipEnd) {{ vid.pause(); vid.ontimeupdate = null; }} }};
  document.getElementById('modal-title').textContent = label || videoId;
  document.getElementById('modal-meta').textContent  = meta  || '';
  document.getElementById('video-modal').classList.add('open');
}}
function closeModal() {{
  const el = document.getElementById('video-modal');
  el.classList.remove('open');
  const vid = document.getElementById('modal-video');
  vid.pause();
  vid.src = '';
  vid.ontimeupdate = null;
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});

// ── View management ───────────────────────────────────────────────────────────
let currentView  = 'library';
let previousView = 'library';
let currentFilter = 'all';
let clipsMode     = false;
let searchQuery   = '';

function showView(name) {{
  document.querySelectorAll('.view').forEach(v => {{
    v.classList.remove('active');
  }});
  document.getElementById('view-' + name).classList.add('active');

  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  const navEl = document.getElementById('nav-' + name);
  if (navEl) navEl.classList.add('active');

  previousView = currentView;
  currentView  = name;

  if (name === 'library') renderLibrary();
  window.scrollTo({{top:0,behavior:'instant'}});
}}

function showDetail(videoId, fromView) {{
  previousView = fromView || currentView;
  renderDetail(videoId);

  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-detail').classList.add('active');
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

  // Update back label
  document.getElementById('back-label').textContent = 'Back to Library';

  currentView = 'detail';
  window.scrollTo({{top:0,behavior:'instant'}});
}}

function goBack() {{
  showView('library');
}}

// ── HOME ──────────────────────────────────────────────────────────────────────
function renderHome() {{
  // ── Vanity row: total views, likes, followers (very large) ──────────────
  const followers = STATS.total_followers;
  const vr = document.getElementById('vanity-row');
  vr.innerHTML = `
    <div class="vanity-card">
      <div class="vanity-num">${{fmtNum(STATS.total_views_all)}}</div>
      <div class="vanity-label">Total Views</div>
    </div>
    <div class="vanity-card">
      <div class="vanity-num">${{fmtNum(STATS.total_likes_all)}}</div>
      <div class="vanity-label">Total Likes</div>
    </div>
    <div class="vanity-card">
      <div class="vanity-num">${{followers !== null ? fmtNum(followers) : '—'}}</div>
      <div class="vanity-label">Followers</div>
    </div>
  `;

  // ── 3 clickable stat cards ───────────────────────────────────────────────
  const sg = document.getElementById('stats-grid');
  sg.innerHTML = `
    <div class="stat-card" onclick="showView('library')" title="View all videos">
      <div class="stat-num">${{STATS.total_reels}}</div>
      <div class="stat-label">Total Videos</div>
      <div class="stat-arrow">→</div>
    </div>
    <div class="stat-card" onclick="showView('library');setFilter('remixed')" title="View remixed videos">
      <div class="stat-num">${{STATS.total_remixes}}</div>
      <div class="stat-label">Total Remixes</div>
      <div class="stat-arrow">→</div>
    </div>
    <div class="stat-card" onclick="showView('library');setFilter('remixed')" title="View b-roll breakdown">
      <div class="stat-num">${{STATS.total_cuts}}</div>
      <div class="stat-label">Total B-roll Clips</div>
      <div class="stat-arrow">→</div>
    </div>
  `;

  const recent = REMIXES.slice(-5).reverse();
  const al = document.getElementById('activity-list');
  al.innerHTML = recent.map(r => {{
    const snippet = r.transcript ? r.transcript.substring(0, 90) + (r.transcript.length > 90 ? '…' : '') : '(no transcript)';
    return `<div class="activity-item" onclick="showDetail('${{escHtml(r.anchor_id)}}','home')">
      <div class="activity-num">Remix #${{r.remix_num}}</div>
      <div class="activity-anchor">${{escHtml(r.anchor_id)}}</div>
      <div class="activity-transcript">${{escHtml(snippet)}}</div>
      <div class="activity-meta">
        <div class="cut-badge">${{r.num_cuts}} cuts</div>
        <div style="font-size:11px;color:#3a3a3a">${{escHtml(r.upload_date_fmt)}}</div>
      </div>
    </div>`;
  }}).join('');
}}

// ── LIBRARY ───────────────────────────────────────────────────────────────────
let brollMode = false;

function _clearModes() {{
  clipsMode = false; brollMode = false;
  document.getElementById('clips-mode-btn').classList.remove('active');
  document.getElementById('broll-mode-btn').classList.remove('active');
  document.getElementById('clips-grid').style.display = 'none';
  document.getElementById('broll-grid').style.display = 'none';
  document.getElementById('video-grid').style.display = '';
}}
function toggleClipsMode() {{
  const next = !clipsMode;
  _clearModes();
  if (next) {{
    clipsMode = true;
    document.getElementById('clips-mode-btn').classList.add('active');
    document.getElementById('video-grid').style.display = 'none';
    document.getElementById('clips-grid').style.display = '';
    renderClips();
  }} else renderLibrary();
  document.getElementById('library-count').textContent = '';
}}
function toggleBrollMode() {{
  const next = !brollMode;
  _clearModes();
  if (next) {{
    brollMode = true;
    document.getElementById('broll-mode-btn').classList.add('active');
    document.getElementById('video-grid').style.display = 'none';
    document.getElementById('broll-grid').style.display = '';
    renderBroll();
  }} else renderLibrary();
  document.getElementById('library-count').textContent = '';
}}

function setFilter(f) {{
  _clearModes();
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.filter === f);
  }});
  renderLibrary();
}}

function filterLibrary() {{
  searchQuery = document.getElementById('search-input').value.toLowerCase();
  if (clipsMode) renderClips();
  else if (brollMode) renderBroll();
  else renderLibrary();
}}

function renderClips() {{
  const q = searchQuery;
  let clips = CLIPS.filter(c => {{
    if (!q) return true;
    return (c.clip_name + ' ' + c.visual_type + ' ' + c.video_id).toLowerCase().includes(q);
  }});
  document.getElementById('library-count').textContent = clips.length + ' clip' + (clips.length !== 1 ? 's' : '');
  const grid = document.getElementById('clips-grid');
  if (!clips.length) {{
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-state-icon">🎬</div><div class="empty-state-text">No clips found</div></div>`;
    return;
  }}
  grid.innerHTML = clips.map(c => {{
    const src = c.thumb ? 'data:image/jpeg;base64,' + c.thumb : null;
    const thumbHtml = src
      ? `<img class="thumb-img" src="${{src}}" alt="" loading="lazy">`
      : `<div class="thumb-placeholder">&#9654;</div>`;
    const qsCls = c.quality_score >= 70 ? 'seg-qs-high' : c.quality_score >= 45 ? 'seg-qs-med' : 'seg-qs-low';
    const dur = c.duration ? c.duration.toFixed(1) + 's' : '';
    return `<div class="clip-card" onclick="openClip('${{escHtml(c.video_id)}}',${{c.start}},${{c.end}},'${{escHtml(c.clip_name)}}','${{escHtml(c.visual_type)}}')">
      <div class="thumb-wrap" style="aspect-ratio:9/16">
        ${{thumbHtml}}
        <div class="clip-name-badge">${{escHtml(c.clip_name)}}</div>
        <div class="clip-play-overlay">
          <div class="clip-play-circle">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="white"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          </div>
        </div>
      </div>
      <div class="clip-body">
        <div class="clip-name-text">${{escHtml(c.clip_name)}}</div>
        <div class="clip-vt">${{escHtml(c.visual_type)}}</div>
        <div class="clip-qs-row">
          <span class="seg-qs ${{qsCls}}">Q:${{c.quality_score}}</span>
          <span class="clip-dur">${{dur}}</span>
        </div>
      </div>
    </div>`;
  }}).join('');
}}

function renderBroll() {{
  const REU_SCORE = {{high:100, medium:60, low:20, none:0}};
  const q = searchQuery;
  let clips = CLIPS.filter(c => {{
    if (!q) return true;
    return (c.clip_name + ' ' + c.visual_type + ' ' + c.video_id).toLowerCase().includes(q);
  }});
  document.getElementById('library-count').textContent = clips.length + ' b-roll clip' + (clips.length !== 1 ? 's' : '');
  const grid = document.getElementById('broll-grid');
  if (!clips.length) {{
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-state-icon">🎬</div><div class="empty-state-text">No b-roll clips found</div></div>`;
    return;
  }}

  function vtPillClass(vt) {{
    if (!vt) return 'vt-other';
    if (vt.startsWith('product')) return 'vt-product';
    if (vt.startsWith('founder-talking-excited') || vt==='celebrating') return 'vt-excited';
    if (vt.startsWith('founder')) return 'vt-founder';
    if (vt==='outdoor'||vt==='lifestyle'||vt==='travel') return 'vt-outdoor';
    if (vt==='working'||vt==='workspace'||vt==='packaging') return 'vt-work';
    return 'vt-other';
  }}
  function barColor(vt) {{
    if (vt.startsWith('product')) return 'fill-blue';
    if (vt.startsWith('founder-talking-excited')||vt==='celebrating') return 'fill-orange';
    if (vt.startsWith('founder')) return 'fill-blue';
    if (vt==='outdoor'||vt==='lifestyle') return 'fill-teal';
    if (vt==='working'||vt==='workspace') return 'fill-orange';
    return 'fill-gray';
  }}

  grid.innerHTML = clips.map(c => {{
    const src = c.thumb ? 'data:image/jpeg;base64,' + c.thumb : null;
    const thumbHtml = src
      ? `<img class="broll-thumb-img" src="${{src}}" alt="" loading="lazy">`
      : `<div class="broll-thumb-placeholder">&#9654;</div>`;

    const reuScore  = REU_SCORE[c.reusability] || 0;
    const composite = Math.round(c.quality_score * 0.6 + reuScore * 0.4);
    const reuCls    = 'reu-' + (c.reusability || 'none');
    const vtCls     = vtPillClass(c.visual_type);
    const bc        = barColor(c.visual_type);
    const qsCls     = c.quality_score >= 70 ? 'seg-qs-high' : c.quality_score >= 45 ? 'seg-qs-med' : 'seg-qs-low';

    const srcVid = videoById[c.video_id];
    const dur    = c.duration ? c.duration.toFixed(1) + 's' : '';

    return `<div class="broll-card">
      <div class="broll-card-top">
        <div class="broll-thumb-col"
          onclick="openClip('${{escHtml(c.video_id)}}',${{c.start}},${{c.end}},'${{escHtml(c.clip_name)}}','${{escHtml(c.visual_type)}}')">
          ${{thumbHtml}}
          <div class="clip-play-overlay">
            <div class="clip-play-circle">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="white"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </div>
          </div>
          <div class="clip-name-badge">${{escHtml(c.clip_name)}}</div>
        </div>
        <div class="broll-info-col">
          <div class="broll-clip-name">${{escHtml(c.clip_name)}}</div>
          <div class="broll-vt"><span class="broll-vt-pill ${{vtCls}}">${{escHtml(c.visual_type)}}</span></div>
          <div class="score-rows">
            <div class="score-row">
              <span class="score-lbl">Quality</span>
              <div class="score-bar-track"><div class="score-bar-fill fill-green" style="width:${{c.quality_score}}%"></div></div>
              <span class="score-val">${{c.quality_score}}</span>
            </div>
            <div class="score-row">
              <span class="score-lbl">Reuse</span>
              <div class="score-bar-track"><div class="score-bar-fill ${{bc}}" style="width:${{reuScore}}%"></div></div>
              <span class="score-val"><span class="reu-badge ${{reuCls}}">${{(c.reusability||'none').toUpperCase()}}</span></span>
            </div>
            <div class="score-row">
              <span class="score-lbl">Composite</span>
              <div class="score-bar-track"><div class="score-bar-fill fill-teal" style="width:${{composite}}%"></div></div>
              <span class="score-val">${{composite}}</span>
            </div>
          </div>
          <div class="broll-meta-row" style="margin-top:10px">
            <span style="color:var(--text-muted)">${{dur}}</span>
            <span style="color:#333">&bull;</span>
            <span style="color:#444;font-size:10px">from ${{vidNumStr(srcVid ? srcVid.vid_num : 0)}}</span>
          </div>
        </div>
      </div>
      <div class="broll-card-bottom">
        <div class="broll-transcript">${{escHtml((c.transcript||'').substring(0,120) || '(no transcript for this segment)')}}</div>
      </div>
    </div>`;
  }}).join('');
}}

function renderLibrary() {{
  let vids = VIDEOS.filter(v => {{
    if (currentFilter === 'remixed' && !v.is_anchor) return false;
    if (currentFilter === 'unused'  &&  v.is_anchor) return false;
    if (searchQuery) {{
      const hay = (v.video_id + ' ' + (v.full_transcript||'') + ' ' + (v.upload_date_fmt||'') + ' ' + vidNumStr(v.vid_num)).toLowerCase();
      if (!hay.includes(searchQuery)) return false;
    }}
    return true;
  }});

  document.getElementById('library-count').textContent = vids.length + ' video' + (vids.length !== 1 ? 's' : '');

  const grid = document.getElementById('video-grid');
  if (!vids.length) {{
    grid.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">🎬</div>
      <div class="empty-state-text">No videos match your search</div>
    </div>`;
    return;
  }}

  grid.innerHTML = vids.map(v => {{
    const src = thumbSrc(v);
    const thumbHtml = src
      ? `<img class="thumb-img" src="${{src}}" alt="" loading="lazy">`
      : `<div class="thumb-placeholder">&#9654;</div>`;
    const remixedBadge = v.is_anchor
      ? `<div class="remixed-badge">Remixed</div>` : '';
    const snippet = (v.full_transcript || '').substring(0, 90);
    return `<div class="video-card" onclick="showDetail('${{escHtml(v.video_id)}}','library')">
      <div class="thumb-wrap">
        ${{thumbHtml}}
        <div class="vid-num-badge">${{vidNumStr(v.vid_num)}}</div>
        ${{remixedBadge}}
      </div>
      <div class="card-body">
        <div class="card-meta">
          <span>&#128065; ${{fmtNum(v.view_count)}}</span>
          <span>&#10084; ${{fmtNum(v.like_count)}}</span>
        </div>
        <div class="card-transcript">${{escHtml(snippet)}}</div>
        <div class="card-date">${{escHtml(v.upload_date_fmt)}}</div>
      </div>
    </div>`;
  }}).join('');
}}

// ── DETAIL ────────────────────────────────────────────────────────────────────
function renderDetail(videoId) {{
  const v = videoById[videoId];
  if (!v) {{
    document.getElementById('detail-content').innerHTML =
      '<p style="color:var(--text-muted);padding:40px">Video not found.</p>';
    return;
  }}
  const remix = remixByAnchor[videoId];
  const src   = thumbSrc(v);

  const thumbHtml = src
    ? `<img class="detail-thumb-img" src="${{src}}" alt="">`
    : `<div class="thumb-placeholder" style="height:100%;min-height:200px">&#9654;</div>`;

  // Stats grid
  const statsHtml = `
    <div class="detail-stats-grid">
      <div class="detail-stat-card">
        <div class="detail-stat-val">${{fmtNumFull(v.view_count)}}</div>
        <div class="detail-stat-lbl">&#128065; Views</div>
      </div>
      <div class="detail-stat-card">
        <div class="detail-stat-val">${{fmtNumFull(v.like_count)}}</div>
        <div class="detail-stat-lbl">&#10084; Likes</div>
      </div>
      <div class="detail-stat-card">
        <div class="detail-stat-val">${{fmtNumFull(v.comment_count)}}</div>
        <div class="detail-stat-lbl">&#128172; Comments</div>
      </div>
      <div class="detail-stat-card">
        <div class="detail-stat-val">${{fmtNumFull(v.repost_count)}}</div>
        <div class="detail-stat-lbl">&#128257; Reposts</div>
      </div>
    </div>
  `;

  // Topic pill
  const topicCls = 'topic-' + (v.topic || 'general');
  const topicHtml = `<span class="topic-pill ${{topicCls}}">${{escHtml(v.topic || 'general')}}</span>`;

  // Visual types
  const vtHtml = (v.visual_types||[]).length > 0
    ? (v.visual_types).map(vt => `<span class="vt-pill">${{escHtml(vt)}}</span>`).join('')
    : '<span style="color:#333;font-size:12px">None tagged</span>';

  // Segments
  const segsHtml = (v.segments||[]).map(s => {{
    const zc    = segZoneClass(s.zone, s.visual_type);
    const zl    = zoneLabel(s.zone);
    const qsCls = qsClass(s.quality_score);
    return `<div class="segment-block zone-${{zc}}">
      <div class="seg-bar"></div>
      <div class="seg-content">
        <div class="seg-header">
          <span class="seg-time">${{(s.start||0).toFixed(1)}}s – ${{(s.end||0).toFixed(1)}}s</span>
          <span class="seg-zone-badge">${{escHtml(zl)}}</span>
          ${{s.visual_type ? `<span class="seg-vt-badge">${{escHtml(s.visual_type)}}</span>` : ''}}
          <span class="seg-qs ${{qsCls}}">Q:${{(s.quality_score||0).toFixed(0)}}</span>
        </div>
        <div class="seg-text">${{escHtml(s.transcript || '')}}</div>
      </div>
    </div>`;
  }}).join('') || '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">No segments available</div>';

  // Remix section
  let remixHtml = '';
  if (remix) {{
    const cutsHtml = remix.cuts && remix.cuts.length > 0 ? `
      <div class="bp-cuts-list">
        ${{remix.cuts.map(c => {{
          const srcVid   = videoById[c.source_video];
          const vidNum   = srcVid ? String(srcVid.vid_num).padStart(3,'0') : '???';
          const bodySegs = (segsByVideo[c.source_video] || []).filter(s => s.zone === 'body' && s.visual_type && s.quality_score >= 20);
          const clipIdx  = bodySegs.findIndex(s => s.visual_type === c.visual_type);
          const clipNum  = clipIdx >= 0 ? clipIdx + 1 : '?';
          const clipName = '#' + vidNum + ':' + clipNum;
          const segTime  = findSegTime(c.source_video, c.visual_type);
          const seg      = segTime ? bodySegs.find(s => s.visual_type === c.visual_type) : null;
          const reuScore = {{high:100,medium:60,low:20,none:0}}[seg ? seg.reusability : 'none'] || 0;
          const composite = seg ? Math.round(seg.quality_score * 0.6 + reuScore * 0.4) : '—';
          const thumbSrcStr = srcVid && srcVid.thumb ? 'data:image/jpeg;base64,' + srcVid.thumb : null;
          const thumbHtml = thumbSrcStr
            ? `<img src="${{thumbSrcStr}}" style="width:100%;height:100%;object-fit:cover;display:block" alt="">`
            : `<div class="bp-cut-thumb-placeholder">&#9654;</div>`;
          const qsCls = seg ? (seg.quality_score >= 70 ? 'seg-qs-high' : seg.quality_score >= 45 ? 'seg-qs-med' : 'seg-qs-low') : 'seg-qs-low';
          return `<div class="bp-cut-card"
            onclick="openClip('${{escHtml(c.source_video)}}',${{segTime ? segTime.start : 0}},${{segTime ? segTime.end : 9999}},'${{escHtml(clipName)}}','${{escHtml(c.visual_type)}}')"
            style="cursor:pointer">
            <div class="bp-cut-thumb" style="min-height:72px">
              ${{thumbHtml}}
              <div class="bp-thumb-play">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="white"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </div>
            </div>
            <div class="bp-cut-body">
              <div class="bp-cut-header">
                <span class="bp-cut-num">Cut #${{c.cut_num}}</span>
                <span class="bp-cut-name">${{escHtml(clipName)}}</span>
                <span class="bp-cut-window">${{escHtml(c.window)}}</span>
              </div>
              <div class="bp-cut-details">
                <span class="cut-vt-pill">${{escHtml(c.visual_type)}}</span>
                ${{seg ? `<span class="seg-qs ${{qsCls}}">Q:${{seg.quality_score}}</span>` : ''}}
                ${{seg ? `<span style="font-size:10px;color:#444">composite ${{composite}}</span>` : ''}}
                <a class="bp-cut-ig" href="https://www.instagram.com/reel/${{encodeURIComponent(c.source_video)}}/" target="_blank" rel="noopener" onclick="event.stopPropagation()">${{escHtml(c.source_video)}} &#8599;</a>
              </div>
            </div>
          </div>`;
        }}).join('')}}
      </div>
    ` : `<div style="padding:16px 18px;color:var(--text-muted);font-size:13px">No b-roll cuts — anchor plays uncut</div>`;

    remixHtml = `
      <div class="remix-section">
        <div class="remix-section-header">
          <div class="remix-dot"></div>
          <div class="remix-section-title">Remix Blueprint</div>
          <div class="remix-badge-num">Remix #${{remix.remix_num}}</div>
        </div>
        <div class="remix-stats-row">
          <div class="remix-stat"><strong>${{remix.num_cuts}}</strong> b-roll cuts</div>
          <div class="remix-stat"><strong>${{remix.num_windows}}</strong> windows</div>
          <div class="remix-stat"><strong>${{fmtNum(remix.views)}}</strong> views</div>
          <div class="remix-stat"><strong>${{fmtNum(remix.likes)}}</strong> likes</div>
          <div class="remix-stat" style="margin-left:auto;color:#333">${{escHtml(remix.upload_date_fmt)}}</div>
        </div>
        ${{cutsHtml}}
      </div>`;
  }}

  document.getElementById('detail-content').innerHTML = `
    <div class="detail-layout">
      <!-- LEFT COLUMN -->
      <div class="detail-left">
        <div class="detail-thumb-wrap"
             onclick="window.open('https://www.instagram.com/reel/${{encodeURIComponent(videoId)}}/', '_blank')"
             title="View on Instagram">
          ${{thumbHtml}}
          <div class="play-overlay">
            <div class="play-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </div>
          </div>
        </div>

        <div class="detail-meta-block">
          <div class="detail-id-row">
            <span class="detail-vid-num">${{vidNumStr(v.vid_num)}}</span>
            <span class="detail-vid-id">${{escHtml(videoId)}}</span>
            ${{v.is_anchor ? '<span class="remixed-badge" style="position:static;margin-left:4px">Remixed</span>' : ''}}
          </div>

          <a class="detail-ig-btn"
             href="https://www.instagram.com/reel/${{encodeURIComponent(videoId)}}/"
             target="_blank" rel="noopener">
            View on Instagram &#8599;
          </a>

          ${{statsHtml}}

          <div class="detail-meta-section">
            <div class="detail-meta-label">Upload Date</div>
            <div style="font-size:13px;color:var(--text-muted)">${{escHtml(v.upload_date_fmt)}}</div>
          </div>

          <div class="detail-meta-section">
            <div class="detail-meta-label">Topic</div>
            ${{topicHtml}}
          </div>

          <div class="detail-meta-section">
            <div class="detail-meta-label">Visual Types</div>
            <div class="tags-wrap">${{vtHtml}}</div>
          </div>
        </div>
      </div>

      <!-- RIGHT COLUMN -->
      <div class="transcript-col">
        <div class="section-heading">Transcript &amp; Segments (${{(v.segments||[]).length}})</div>
        ${{segsHtml}}
        ${{remixHtml}}
      </div>
    </div>
  `;
}}

// ── Init ──────────────────────────────────────────────────────────────────────
(function renderHeroVanity() {{
  // Added stats — updated manually
  document.getElementById('hero-vanity-row').innerHTML = `
    <div class="hero-vanity-item">
      <div class="hero-vanity-num green">+35K</div>
      <div class="hero-vanity-label">Added Views</div>
    </div>
    <div class="hero-vanity-item">
      <div class="hero-vanity-num blue">+1K</div>
      <div class="hero-vanity-label">Added Likes</div>
    </div>
    <div class="hero-vanity-item">
      <div class="hero-vanity-num teal">+100</div>
      <div class="hero-vanity-label">Added Followers</div>
    </div>
    <div class="hero-vanity-item">
      <div class="hero-vanity-num" style="color:#f97316">+${{STATS.total_remixes}}</div>
      <div class="hero-vanity-label">Added Posts</div>
    </div>
  `;
}})();

(function renderFilterCounts() {{
  const total   = VIDEOS.length;
  const remixed = VIDEOS.filter(v => v.is_anchor).length;
  const unused  = total - remixed;
  document.getElementById('count-all').textContent     = ' (' + total + ')';
  document.getElementById('count-remixed').textContent = ' (' + remixed + ')';
  document.getElementById('count-unused').textContent  = ' (' + unused + ')';
  document.getElementById('count-clips').textContent   = ' (' + CLIPS.length + ')';
  document.getElementById('count-broll').textContent   = ' (' + CLIPS.length + ')';
}})();

renderLibrary();
</script>
</body>
</html>"""

# Write output
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(html, encoding="utf-8")

size_bytes = OUTPUT_PATH.stat().st_size
size_mb    = size_bytes / 1024 / 1024
print(f"\nDone! Written to: {OUTPUT_PATH}")
print(f"File size: {size_mb:.2f} MB ({size_bytes:,} bytes)")
if size_mb < 1:
    print("NOTE: File is under 1 MB — thumbnails may be missing (check /tmp/thumbs/)")
else:
    print("Size check passed")
