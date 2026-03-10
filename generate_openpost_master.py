#!/usr/bin/env python3
"""
Generate openpost_master.html — interactive master index for the video remixing project.
"""

import json
import os
import re
import glob
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
VIDEOS_DIR   = Path("/Users/galbutler/booster/data/videos")
SEGMENTS_DIR = Path("/Users/galbutler/booster/data/segments")
REMIX_LOG    = Path("/Users/galbutler/booster/openpost-v1/remix_log.txt")
OUTPUT_PATH  = Path("/Users/galbutler/Desktop/openpost_master.html")

# ─── Load video metadata ──────────────────────────────────────────────────────
print("Loading video metadata...")
videos = {}
for p in VIDEOS_DIR.glob("*.json"):
    vid_id = p.stem
    with open(p) as f:
        videos[vid_id] = json.load(f)

print(f"  {len(videos)} videos loaded")

# ─── Sort by upload_date → assign vid_num ─────────────────────────────────────
sorted_ids = sorted(videos.keys(), key=lambda v: videos[v].get("upload_date", "00000000"))
vid_num = {vid_id: i+1 for i, vid_id in enumerate(sorted_ids)}
print(f"  vid_num range: {list(vid_num.values())[0]} → {list(vid_num.values())[-1]}")

# ─── Load segment data ────────────────────────────────────────────────────────
print("Loading segment data...")
segments_data = {}
for p in SEGMENTS_DIR.glob("*.json"):
    vid_id = p.stem
    with open(p) as f:
        segments_data[vid_id] = json.load(f)
print(f"  {len(segments_data)} segment files loaded")

# ─── Parse remix log ──────────────────────────────────────────────────────────
print("Parsing remix log...")

def parse_remix_log(log_path):
    with open(log_path) as f:
        text = f.read()

    remixes = []

    # Split on remix headers
    remix_blocks = re.split(r'\n(?=Remix #\d+)', text)

    for block in remix_blocks:
        block = block.strip()
        if not block.startswith("Remix #"):
            continue

        # Header line
        header_m = re.match(r'Remix #(\d+)\s*[—-]+\s*Anchor:\s*(\S+)', block)
        if not header_m:
            continue
        remix_num = int(header_m.group(1))
        anchor_id = header_m.group(2)

        # Date
        date_m = re.search(r'Upload date\s*:\s*(\d+)', block)
        upload_date = date_m.group(1) if date_m else ""

        # Views / Likes
        views_m = re.search(r'Views\s*:\s*([\d,]+)', block)
        likes_m = re.search(r'Likes:\s*([\d,]+)', block)
        views = int(views_m.group(1).replace(",","")) if views_m else 0
        likes = int(likes_m.group(1).replace(",","")) if likes_m else 0

        # B-roll cuts count
        cuts_m = re.search(r'B-roll cuts\s*:\s*(\d+)\s*/\s*(\d+)', block)
        cuts_used   = int(cuts_m.group(1)) if cuts_m else 0
        cuts_windows = int(cuts_m.group(2)) if cuts_m else 0

        # B-roll table rows
        broll_cuts = []
        # Look for table rows: index + window + duration + gap + visual_type + source
        row_pattern = re.compile(
            r'^\s*(\d+)\s+'                       # #
            r'([\d.]+s-[\d.]+s)\s+'               # window
            r'([\d.]+s)\s+'                       # duration
            r'(\S[^\s]+(?:\s+anchor)?)\s+'        # gap
            r'([\w-]+(?:-[\w]+)*)\s+'             # visual type
            r'(\S+)\s*$',                          # source video
            re.MULTILINE
        )
        for row_m in row_pattern.finditer(block):
            broll_cuts.append({
                "cut_num":     int(row_m.group(1)),
                "window":      row_m.group(2),
                "duration":    row_m.group(3),
                "gap":         row_m.group(4),
                "visual_type": row_m.group(5),
                "source_id":   row_m.group(6),
            })

        remixes.append({
            "remix_num":     remix_num,
            "anchor_id":     anchor_id,
            "upload_date":   upload_date,
            "views":         views,
            "likes":         likes,
            "cuts_used":     cuts_used,
            "cuts_windows":  cuts_windows,
            "broll_cuts":    broll_cuts,
        })

    return remixes

remixes = parse_remix_log(REMIX_LOG)
print(f"  {len(remixes)} remixes parsed")
for r in remixes:
    print(f"    Remix #{r['remix_num']} anchor={r['anchor_id']} cuts={r['cuts_used']} broll_rows={len(r['broll_cuts'])}")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def fmt_date(d):
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d

def fmt_num(n):
    return f"{n:,}"

def title_from_transcript(transcript, words=10):
    w = transcript.split()
    return " ".join(w[:words]) + ("..." if len(w) > words else "")

def vid_num_str(vid_id):
    n = vid_num.get(vid_id)
    return f"#{n:03d}" if n else "???"

# ─── Build data objects for JS ────────────────────────────────────────────────
print("Building JS data objects...")

# videos_js: array sorted by vid_num
videos_js = []
for vid_id in sorted_ids:
    vm = videos[vid_id]
    sd = segments_data.get(vid_id, {})
    ft = sd.get("full_transcript", "")
    videos_js.append({
        "id":          vid_id,
        "num":         vid_num[vid_id],
        "upload_date": vm.get("upload_date",""),
        "view_count":  vm.get("view_count",0),
        "like_count":  vm.get("like_count",0),
        "comment_count": vm.get("comment_count",0),
        "repost_count": vm.get("repost_count",0),
        "full_transcript": ft,
        "title":       title_from_transcript(ft),
        "segments":    sd.get("segments",[]),
    })

# remixed set
remixed_ids = set(r["anchor_id"] for r in remixes)

# remixes_js with enriched anchor data
remixes_js = []
for r in remixes:
    anchor_id = r["anchor_id"]
    vm = videos.get(anchor_id, {})
    sd = segments_data.get(anchor_id, {})
    ft = sd.get("full_transcript", "")
    r_out = dict(r)
    r_out["view_count"]  = vm.get("view_count", r["views"])
    r_out["like_count"]  = vm.get("like_count", r["likes"])
    r_out["full_transcript"] = ft
    r_out["title"] = title_from_transcript(ft)
    r_out["segments"] = sd.get("segments", [])
    r_out["vid_num"] = vid_num.get(anchor_id, 0)
    remixes_js.append(r_out)

videos_js_str  = json.dumps(videos_js,  ensure_ascii=False, separators=(',',':'))
remixes_js_str = json.dumps(remixes_js, ensure_ascii=False, separators=(',',':'))
vid_num_js_str = json.dumps(vid_num,    ensure_ascii=False, separators=(',',':'))

print(f"  videos_js: {len(videos_js)} entries")
print(f"  remixes_js: {len(remixes_js)} entries")

# ─── HTML generation ──────────────────────────────────────────────────────────
print("Generating HTML...")

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenPost — Master Index</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0a0a0a;
  --card:#111;
  --card2:#161616;
  --border:#222;
  --border2:#2a2a2a;
  --text:#e8e8e8;
  --muted:#888;
  --dim:#555;
  --accent:#4a9eff;
  --accent2:#6f6fff;
  --font:'Inter',system-ui,sans-serif;
  --mono:'JetBrains Mono',monospace;
}}
html{{background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;line-height:1.5;scroll-behavior:smooth}}
body{{min-height:100vh}}

/* ── Layout ── */
#app{{display:flex;flex-direction:column;height:100vh}}

/* ── Tab bar ── */
#tabs{{
  position:sticky;top:0;z-index:100;
  background:rgba(10,10,10,0.92);
  backdrop-filter:blur(12px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:0;
  padding:0 20px;
}}
.tab-btn{{
  padding:14px 20px;
  border:none;background:none;color:var(--muted);
  font:500 13px var(--font);cursor:pointer;
  border-bottom:2px solid transparent;
  transition:color .2s,border-color .2s;
  white-space:nowrap;
}}
.tab-btn:hover{{color:var(--text)}}
.tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.tab-spacer{{flex:1}}
#search-wrap{{padding:0 0 0 12px}}
#search{{
  background:#1a1a1a;border:1px solid var(--border2);
  color:var(--text);border-radius:6px;
  padding:7px 12px;font:400 13px var(--font);
  width:220px;outline:none;
  transition:border-color .2s;
}}
#search:focus{{border-color:var(--accent)}}

/* ── Panels ── */
.panel{{display:none;flex:1;overflow-y:auto;padding:20px}}
.panel.active{{display:block}}

/* ── Remix cards ── */
.remixes-grid{{display:flex;flex-direction:column;gap:12px;max-width:1100px;margin:0 auto}}

.remix-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  overflow:hidden;
  transition:border-color .2s;
}}
.remix-card:hover{{border-color:var(--border2)}}

.card-header{{
  display:flex;align-items:center;gap:14px;
  padding:14px 16px;cursor:pointer;
  user-select:none;
}}
.card-header:hover{{background:rgba(255,255,255,0.02)}}

.thumb-wrap{{position:relative;flex-shrink:0;width:60px;height:60px;border-radius:6px;overflow:hidden;background:#1a1a1a}}
.thumb-wrap img{{width:100%;height:100%;object-fit:cover;display:block}}
.thumb-link{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0);;transition:background .2s}}
.thumb-link:hover{{background:rgba(0,0,0,0.4)}}
.thumb-link::after{{content:'▶';color:#fff;font-size:18px;opacity:0;transition:opacity .2s}}
.thumb-link:hover::after{{opacity:1}}

.card-meta{{flex:1;min-width:0}}
.card-meta .row1{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
.card-meta .remix-num{{font:700 15px var(--font);color:#fff}}
.card-meta .vid-ref{{font:500 13px var(--font);color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:380px}}
.card-meta .vid-id{{font:400 11px var(--mono);color:var(--dim)}}
.card-meta .row2{{display:flex;align-items:center;gap:14px;margin-top:5px;flex-wrap:wrap}}
.stat{{font:400 12px var(--font);color:var(--muted)}}
.stat span{{color:var(--text);font-weight:500}}

.badge{{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 8px;border-radius:20px;
  font:600 11px var(--font);white-space:nowrap;
}}
.badge-cuts{{background:#1a2d1a;color:#4c4}}
.badge-nocuts{{background:#1a1a1a;color:#666}}
.badge-remixed{{background:#1a1a2d;color:#68f}}

.expand-icon{{
  flex-shrink:0;color:var(--dim);font-size:12px;
  transition:transform .25s;
}}
.remix-card.open .expand-icon{{transform:rotate(90deg)}}

/* ── Expanded section ── */
.card-body{{
  max-height:0;overflow:hidden;
  transition:max-height .35s cubic-bezier(0.4,0,0.2,1);
}}
.remix-card.open .card-body{{max-height:4000px}}
.card-body-inner{{
  border-top:1px solid var(--border);
  padding:16px;
  display:flex;flex-direction:column;gap:20px;
}}

/* ── Section labels ── */
.section-label{{
  font:600 10px var(--font);letter-spacing:.1em;
  text-transform:uppercase;color:var(--dim);
  margin-bottom:8px;
}}

/* ── Transcript ── */
.transcript-wrap{{display:flex;flex-wrap:wrap;gap:6px;align-items:flex-start}}
.seg-block{{
  display:inline-flex;flex-direction:column;
  border-radius:5px;padding:5px 8px;
  cursor:default;position:relative;
  max-width:320px;
  transition:filter .15s;
}}
.seg-block:hover{{filter:brightness(1.2)}}
.seg-zone-tag{{
  font:700 9px var(--mono);letter-spacing:.08em;
  text-transform:uppercase;margin-bottom:3px;opacity:.7;
}}
.seg-text{{font:400 12px var(--font);line-height:1.4}}

/* Zone colors */
.zone-hook{{background:#2d1a00;color:#f90}}
.zone-hook .seg-zone-tag{{color:#f90}}
.zone-cta{{background:#1a1a1a;color:#666}}
.zone-cta .seg-zone-tag{{color:#555}}
/* body visual types */
.vt-product{{background:#1a2d1a;color:#4c4}}
.vt-product .seg-zone-tag{{color:#4c4}}
.vt-founder{{background:#1a1a2d;color:#68f}}
.vt-founder .seg-zone-tag{{color:#68f}}
.vt-working{{background:#2d2a1a;color:#cc8}}
.vt-working .seg-zone-tag{{color:#cc8}}
.vt-outdoor{{background:#1a2d2a;color:#4cc}}
.vt-outdoor .seg-zone-tag{{color:#4cc}}
.vt-split{{background:#2a1a2d;color:#c8f}}
.vt-split .seg-zone-tag{{color:#c8f}}
.vt-other{{background:#1e1e1e;color:#999}}
.vt-other .seg-zone-tag{{color:#777}}

/* Tooltip */
.seg-block::after{{
  content:attr(data-tip);
  position:absolute;bottom:calc(100% + 6px);left:0;
  background:#1e1e1e;border:1px solid #333;
  color:#ccc;font:400 11px var(--mono);
  padding:5px 8px;border-radius:5px;
  white-space:pre;pointer-events:none;
  opacity:0;transition:opacity .15s;
  z-index:50;min-width:200px;
}}
.seg-block:hover::after{{opacity:1}}

/* ── B-roll table ── */
.broll-table{{width:100%;border-collapse:collapse;font-size:12px}}
.broll-table th{{
  text-align:left;padding:6px 10px;
  border-bottom:1px solid var(--border);
  color:var(--dim);font:600 10px var(--font);
  letter-spacing:.06em;text-transform:uppercase;
}}
.broll-table td{{
  padding:7px 10px;
  border-bottom:1px solid #1a1a1a;
  vertical-align:middle;
}}
.broll-table tr:last-child td{{border-bottom:none}}
.broll-table tr:hover td{{background:rgba(255,255,255,.02)}}

.cut-id{{font:500 12px var(--mono);color:var(--accent)}}
.window-cell{{font:400 12px var(--mono);color:var(--muted)}}

.vt-pill{{
  display:inline-block;padding:2px 7px;border-radius:12px;
  font:600 10px var(--font);letter-spacing:.04em;
  white-space:nowrap;
}}
.vt-pill.p-product{{background:#1a2d1a;color:#4c4}}
.vt-pill.p-founder{{background:#1a1a2d;color:#68f}}
.vt-pill.p-working{{background:#2d2a1a;color:#cc8}}
.vt-pill.p-outdoor,.vt-pill.p-lifestyle{{background:#1a2d2a;color:#4cc}}
.vt-pill.p-split{{background:#2a1a2d;color:#c8f}}
.vt-pill.p-other{{background:#1e1e1e;color:#999}}

.src-link{{color:var(--accent);text-decoration:none;font:500 12px var(--mono)}}
.src-link:hover{{text-decoration:underline}}
.view-btn{{
  display:inline-block;padding:3px 9px;
  background:#1a1a2d;border:1px solid #2a2a4d;
  color:#68f;border-radius:5px;font:500 11px var(--font);
  text-decoration:none;cursor:pointer;
  transition:background .15s;
}}
.view-btn:hover{{background:#22224d}}
.no-broll{{color:var(--dim);font-style:italic;font-size:12px}}

/* ── All Videos tab ── */
.videos-panel{{max-width:1200px;margin:0 auto}}
.videos-panel .controls{{display:flex;align-items:center;gap:12px;margin-bottom:16px}}
.videos-panel h2{{font:700 18px var(--font);color:#fff}}

.video-table{{width:100%;border-collapse:collapse}}
.video-table th{{
  position:sticky;top:0;background:#111;z-index:10;
  text-align:left;padding:10px 12px;
  border-bottom:2px solid var(--border);
  color:var(--dim);font:600 11px var(--font);
  letter-spacing:.07em;text-transform:uppercase;
  cursor:pointer;user-select:none;
}}
.video-table th:hover{{color:var(--text)}}
.video-table th.sort-asc::after{{content:' ↑'}}
.video-table th.sort-desc::after{{content:' ↓'}}
.video-table td{{
  padding:9px 12px;
  border-bottom:1px solid #171717;
  vertical-align:middle;
}}
.video-table tr:hover td{{background:rgba(255,255,255,.025)}}
.video-table .num-cell{{
  font:600 12px var(--mono);color:var(--dim);
  width:50px;
}}
.thumb-sm{{width:45px;height:45px;border-radius:4px;object-fit:cover;display:block;background:#1a1a1a}}
.video-table .title-cell{{max-width:320px}}
.video-table .title-text{{
  font:400 13px var(--font);color:var(--text);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;
}}
.video-table .id-cell{{font:400 11px var(--mono);color:var(--dim)}}
.video-table .id-link{{color:var(--accent);text-decoration:none}}
.video-table .id-link:hover{{text-decoration:underline}}
.video-table .date-cell{{font:400 12px var(--mono);color:var(--muted)}}
.video-table .num-stat{{font:400 12px var(--font);color:var(--muted)}}
.video-table .num-stat.hi{{color:var(--text);font-weight:500}}

.empty-row td{{text-align:center;color:var(--dim);padding:40px;font-style:italic}}

/* ── Scrollbar ── */
::-webkit-scrollbar{{width:6px;height:6px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:#333;border-radius:3px}}
::-webkit-scrollbar-thumb:hover{{background:#444}}

/* ── Responsive ── */
@media(max-width:700px){{
  .card-meta .vid-ref{{max-width:180px}}
  #search{{width:140px}}
}}
</style>
</head>
<body>
<div id="app">

<!-- Tab bar -->
<nav id="tabs">
  <button class="tab-btn active" onclick="switchTab('remixes')">Remixes (28)</button>
  <button class="tab-btn" onclick="switchTab('videos')">All Videos (100)</button>
  <div class="tab-spacer"></div>
  <div id="search-wrap">
    <input id="search" type="search" placeholder="Search videos…" oninput="filterVideos(this.value)">
  </div>
</nav>

<!-- Remixes panel -->
<div id="panel-remixes" class="panel active">
  <div class="remixes-grid" id="remixes-grid"></div>
</div>

<!-- All Videos panel -->
<div id="panel-videos" class="panel">
  <div class="videos-panel">
    <table class="video-table" id="video-table">
      <thead>
        <tr>
          <th onclick="sortVideos('num')">#</th>
          <th>Thumb</th>
          <th onclick="sortVideos('title')" class="sort-asc">Title</th>
          <th onclick="sortVideos('id')">ID</th>
          <th onclick="sortVideos('upload_date')">Posted</th>
          <th onclick="sortVideos('view_count')">Views</th>
          <th onclick="sortVideos('like_count')">Likes</th>
          <th>Remixed?</th>
        </tr>
      </thead>
      <tbody id="video-tbody"></tbody>
    </table>
  </div>
</div>

</div><!-- #app -->

<!-- ── Data ── -->
<script>
const VIDEOS  = {videos_js_str};
const REMIXES = {remixes_js_str};
const VID_NUM = {vid_num_js_str};
const REMIXED_IDS = new Set({json.dumps(list(remixed_ids))});

// ── Helpers ──────────────────────────────────────────────────────────────────
function fmtNum(n) {{
  if (n >= 1_000_000) return (n/1_000_000).toFixed(1)+'M';
  if (n >= 1_000)     return (n/1_000).toFixed(1)+'K';
  return String(n);
}}
function fmtDate(d) {{
  if (!d || d.length < 8) return d||'';
  return d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6,8);
}}
function esc(s) {{
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}
function igReel(id) {{ return `https://www.instagram.com/reel/${{id}}/`; }}
function igThumb(id) {{ return `https://www.instagram.com/p/${{id}}/media/?size=m`; }}
const PLACEHOLDER = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60'%3E%3Crect width='60' height='60' fill='%231a1a1a'/%3E%3Ctext x='50%25' y='55%25' font-size='22' text-anchor='middle' fill='%23333'%3E▶%3C/text%3E%3C/svg%3E`;
const PLACEHOLDER_LG = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60'%3E%3Crect width='60' height='60' fill='%231a1a1a'/%3E%3Ctext x='50%25' y='55%25' font-size='18' text-anchor='middle' fill='%23333'%3E▶%3C/text%3E%3C/svg%3E`;

function thumbImg(id, size=60, cls='') {{
  return `<img src="${{igThumb(id)}}" width="${{size}}" height="${{size}}" class="${{cls}}" alt="" onerror="this.src='${{size<=60?PLACEHOLDER:PLACEHOLDER_LG}}'">`;
}}

function vtClass(vt) {{
  if (!vt) return 'p-other';
  const v = vt.toLowerCase();
  if (v.startsWith('product')) return 'p-product';
  if (v.startsWith('founder')) return 'p-founder';
  if (v.includes('workspace') || v.includes('working')) return 'p-working';
  if (v.includes('outdoor') || v.includes('lifestyle')) return 'p-outdoor';
  if (v.includes('split')) return 'p-split';
  return 'p-other';
}}
function vtSegClass(zone, vt) {{
  if (zone === 'hook') return 'zone-hook';
  if (zone === 'cta')  return 'zone-cta';
  const v = (vt||'').toLowerCase();
  if (v.startsWith('product')) return 'vt-product';
  if (v.startsWith('founder')) return 'vt-founder';
  if (v.includes('workspace') || v.includes('working')) return 'vt-working';
  if (v.includes('outdoor') || v.includes('lifestyle')) return 'vt-outdoor';
  if (v.includes('split')) return 'vt-split';
  return 'vt-other';
}}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {{
  document.querySelectorAll('.tab-btn').forEach((b,i) => {{
    b.classList.toggle('active', ['remixes','videos'][i] === tab);
  }});
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-'+tab).classList.add('active');
  // show/hide search
  document.getElementById('search-wrap').style.display = tab==='videos' ? '' : 'none';
}}

// ── Build remix cards ─────────────────────────────────────────────────────────
function buildRemixes() {{
  const grid = document.getElementById('remixes-grid');
  grid.innerHTML = '';
  REMIXES.forEach((r, ri) => {{
    const anchorNum = r.vid_num;
    const card = document.createElement('div');
    card.className = 'remix-card';
    card.id = `remix-${{r.remix_num}}`;

    const hasCuts = r.cuts_used > 0;
    const badgeHtml = hasCuts
      ? `<span class="badge badge-cuts">${{r.cuts_used}} cuts</span>`
      : `<span class="badge badge-nocuts">No b-roll</span>`;
    const vidNumStr = anchorNum ? `#${{String(anchorNum).padStart(3,'0')}}` : '???';

    // Transcript segments
    let transcriptHtml = '';
    if (r.segments && r.segments.length) {{
      r.segments.forEach(seg => {{
        const zone = seg.zone?.value || '';
        const vt   = seg.visual_type?.value || '';
        const cls  = vtSegClass(zone, vt);
        const zoneLabel = zone.toUpperCase();
        const tip = `${{seg.start?.toFixed(1)}}s–${{seg.end?.toFixed(1)}}s | ${{vt || '—'}} | q=${{seg.quality_score?.toFixed(1)||'?'}}`;
        transcriptHtml += `<div class="seg-block ${{cls}}" data-tip="${{esc(tip)}}"><div class="seg-zone-tag">${{esc(zoneLabel)}}</div><div class="seg-text">${{esc(seg.transcript)}}</div></div>`;
      }});
    }} else {{
      transcriptHtml = `<span style="color:var(--dim);font-style:italic;font-size:12px">Transcript unavailable</span>`;
    }}

    // B-roll table
    let brollHtml = '';
    if (!hasCuts) {{
      brollHtml = `<div class="no-broll">Anchor plays uncut — no b-roll inserted.</div>`;
    }} else {{
      brollHtml = `<table class="broll-table"><thead><tr>
        <th>Cut ID</th><th>Window</th><th>Visual Type</th><th>Source Video</th><th></th>
      </tr></thead><tbody>`;
      r.broll_cuts.forEach(cut => {{
        const srcNum  = VID_NUM[cut.source_id];
        const srcStr  = srcNum ? `#${{String(srcNum).padStart(3,'0')}}` : '???';
        const cutId   = `V${{String(anchorNum).padStart(3,'0')}}:${{String(cut.cut_num).padStart(2,'0')}}`;
        const vtPill  = `<span class="vt-pill ${{vtClass(cut.visual_type)}}">${{esc(cut.visual_type)}}</span>`;
        const srcLink = `<a class="src-link" href="${{igReel(cut.source_id)}}" target="_blank">${{esc(srcStr)}} — ${{esc(cut.source_id)}}</a>`;
        const viewBtn = `<a class="view-btn" href="${{igReel(cut.source_id)}}" target="_blank">View clip</a>`;
        brollHtml += `<tr>
          <td><span class="cut-id">${{esc(cutId)}}</span></td>
          <td><span class="window-cell">${{esc(cut.window)}}</span></td>
          <td>${{vtPill}}</td>
          <td>${{srcLink}}</td>
          <td>${{viewBtn}}</td>
        </tr>`;
      }});
      brollHtml += `</tbody></table>`;
    }}

    card.innerHTML = `
      <div class="card-header" onclick="toggleCard(${{ri}})">
        <div class="thumb-wrap">
          ${{thumbImg(r.anchor_id, 60)}}
          <a class="thumb-link" href="${{igReel(r.anchor_id)}}" target="_blank" onclick="event.stopPropagation()"></a>
        </div>
        <div class="card-meta">
          <div class="row1">
            <span class="remix-num">Remix #${{r.remix_num}}</span>
            <span class="vid-ref">${{esc(vidNumStr)}} — ${{esc(r.title||'(no transcript)')}}</span>
            <span class="vid-id">${{esc(r.anchor_id)}}</span>
          </div>
          <div class="row2">
            <span class="stat">📅 <span>${{fmtDate(r.upload_date)}}</span></span>
            <span class="stat">👁 <span>${{fmtNum(r.view_count||r.views)}}</span></span>
            <span class="stat">♥ <span>${{fmtNum(r.like_count||r.likes)}}</span></span>
            ${{badgeHtml}}
          </div>
        </div>
        <span class="expand-icon">▶</span>
      </div>
      <div class="card-body">
        <div class="card-body-inner">
          <div>
            <div class="section-label">Transcript</div>
            <div class="transcript-wrap">${{transcriptHtml}}</div>
          </div>
          <div>
            <div class="section-label">B-Roll Cuts (${{r.cuts_used}} / ${{r.cuts_windows}} windows)</div>
            ${{brollHtml}}
          </div>
        </div>
      </div>
    `;
    grid.appendChild(card);
  }});
}}

function toggleCard(idx) {{
  const cards = document.querySelectorAll('.remix-card');
  cards[idx].classList.toggle('open');
}}

// ── Build video table ─────────────────────────────────────────────────────────
let _sortCol = 'num', _sortDir = 1, _filterStr = '';
let _videoRows = [...VIDEOS];

function buildVideoTable() {{
  renderVideoTable();
}}

function sortVideos(col) {{
  if (_sortCol === col) {{ _sortDir *= -1; }}
  else {{ _sortCol = col; _sortDir = 1; }}
  document.querySelectorAll('.video-table th').forEach(th => {{
    th.classList.remove('sort-asc','sort-desc');
  }});
  const thMap = {{'num':0,'title':2,'id':3,'upload_date':4,'view_count':5,'like_count':6}};
  const idx = thMap[col];
  if (idx !== undefined) {{
    const th = document.querySelectorAll('.video-table th')[idx];
    th.classList.add(_sortDir===1?'sort-asc':'sort-desc');
  }}
  renderVideoTable();
}}

function filterVideos(q) {{
  _filterStr = q.toLowerCase();
  renderVideoTable();
}}

function renderVideoTable() {{
  let rows = [...VIDEOS];
  // filter
  if (_filterStr) {{
    rows = rows.filter(v =>
      (v.title||'').toLowerCase().includes(_filterStr) ||
      v.id.toLowerCase().includes(_filterStr) ||
      String(v.num).includes(_filterStr)
    );
  }}
  // sort
  rows.sort((a,b) => {{
    let av = a[_sortCol], bv = b[_sortCol];
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();
    if (av < bv) return -_sortDir;
    if (av > bv) return _sortDir;
    return 0;
  }});

  const tbody = document.getElementById('video-tbody');
  if (!rows.length) {{
    tbody.innerHTML = `<tr class="empty-row"><td colspan="8">No videos match your search.</td></tr>`;
    return;
  }}
  tbody.innerHTML = rows.map(v => {{
    const numStr = '#'+String(v.num).padStart(3,'0');
    const remixedBadge = REMIXED_IDS.has(v.id)
      ? `<span class="badge badge-remixed">Remixed</span>` : '';
    const hiV = v.view_count > 100000 ? ' hi' : '';
    const hiL = v.like_count > 5000   ? ' hi' : '';
    return `<tr>
      <td class="num-cell">${{esc(numStr)}}</td>
      <td><a href="${{igReel(v.id)}}" target="_blank">${{thumbImg(v.id, 45, 'thumb-sm')}}</a></td>
      <td class="title-cell"><div class="title-text">${{esc(v.title||'—')}}</div></td>
      <td class="id-cell"><a class="id-link" href="${{igReel(v.id)}}" target="_blank">${{esc(v.id)}}</a></td>
      <td class="date-cell">${{fmtDate(v.upload_date)}}</td>
      <td class="num-stat${{hiV}}">${{fmtNum(v.view_count)}}</td>
      <td class="num-stat${{hiL}}">${{fmtNum(v.like_count)}}</td>
      <td>${{remixedBadge}}</td>
    </tr>`;
  }}).join('');
}}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  // Hide search by default (remixes tab active)
  document.getElementById('search-wrap').style.display = 'none';
  buildRemixes();
  buildVideoTable();
}});
</script>
</body>
</html>"""

# ─── Write output ─────────────────────────────────────────────────────────────
print(f"Writing output to {OUTPUT_PATH}...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

size = OUTPUT_PATH.stat().st_size
print(f"Output written: {OUTPUT_PATH}")
print(f"File size: {size:,} bytes ({size/1024:.1f} KB)")

if size < 50_000:
    print("ERROR: File is under 50KB — something went wrong!")
else:
    print("SUCCESS: File is > 50KB ✓")
