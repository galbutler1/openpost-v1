BOOSTER — VIDEO TAGGING & ASSEMBLY PROTOCOL v4
Engineering Spec — Full Implementation

---

## 1. INGESTION

Input per video:
- Video file
- Platform metadata: views, likes, comments, shares, post date

Steps:
1. Pull N reels via API (TikTok / Instagram) — N specified by user at runtime
2. Sort by view count descending
3. Compute performance_score for each video before processing (see Section 4.10)
4. Process all N videos

---

## 2. PER-VIDEO PROCESSING PIPELINE

Three layers run, merged into a single segmented timeline.

### Layer A — Transcript (Whisper)
- Transcribe full audio
- Output: word-level transcript with timestamps
- Capture exact words, no cleanup or paraphrasing

### Layer B — Vision (GPT-4o)
- Sample one frame every 2 seconds
- Label each frame with visual_type (see Section 4.3)
- Output: timestamped visual labels

### Layer C — Beat Detection
- Analyze anchor audio track for beat and transient timestamps
- Output: list of beat timestamps in seconds
- Used in Section 6.2 to snap cutaway window starts to nearest beat
- If no beat detectable, fall back to raw segment boundary — not a hard requirement

### Merge
- Align all three outputs on the same timestamp axis
- Produce unified segmented timeline (see Section 3)

---

## 3. SEGMENTATION RULE

A new segment starts whenever any tag changes. If consecutive seconds share identical tags they belong to one segment. Every second of the video must be covered with no gaps.

Minimum segment duration: 1 second. Any segment under 1 second gets reusability: none and is excluded from the b-roll pool.

---

## 4. PER-SEGMENT TAGS

Every segment receives all of the following tags. AI-assigned tags carry a confidence score 0–100. Computed scores carry no confidence modifier.

---

### 4.1 ZONE

Narrative position in the video.

| Value | Definition |
|-------|------------|
| hook  | Opening grab. Starts at 0:00. Ends when creator shifts from attention-grabbing to content delivery. Default to first 3 seconds if unclear. Identified by: bold claim, question, open loop, pattern interrupt, fast pace. |
| body  | Everything between hook and CTA. |
| cta   | Closing ask. Starts when creator shifts to asking viewer to act. Default to last 5 seconds if unclear. Identified by: "follow," "link in bio," "comment," "check this out," any direct ask. |

**Hook and CTA are hard protected zones. No b-roll is ever inserted here. Anchor visual always plays.**

**Short video zone conflict:** If hook end ≥ CTA start, hook takes priority from 0:00 through its full defined duration. CTA immediately follows. No body zone exists for that video.

---

### 4.2 CONTEXT TYPE

Whether b-roll can visually replace the Anchor at this moment. Most heavily weighted tag in the system.

| Value     | Definition |
|-----------|------------|
| specific  | Words reference something only visible in this video. Lock Anchor visual. No b-roll ever. |
| vague     | Words could be said in any creator's video. B-roll eligible if zone is body. |
| ambiguous | Cannot be clearly determined. Default to Anchor visual. Flag for manual review. |
| none      | No transcript. Silence or music only. |

Tag as **specific** if transcript contains:
- Demonstrative language pointing at something on screen: "this," "here," "that," "these," "look at," "right here," "as you can see"
- References to specific visible elements: colors, positions, named features, mechanisms, graphs, diagrams
- Instructions requiring sight of the action: "fold it like this," "press here," "watch what happens"
- Any sentence that loses meaning without the original visual

Tag as **vague** if transcript:
- Could appear in any creator's video in any niche
- Is emotionally general: struggle, surprise, excitement, motivation
- Makes complete sense as audio alone with no visual required
- Contains no product-specific or visually-dependent language

Examples of vague: "this changed everything," "nobody talks about this," "I almost quit," "we hit our first $10k month," "the response was overwhelming," "most people get this completely wrong," "I couldn't believe it," "here's what actually works," "after 3 years of failure," "the results were insane"

---

### 4.3 VISUAL TYPE

What is physically on screen. Assign the single most accurate label.

**Presenter:**
- founder-talking-neutral
- founder-talking-excited
- founder-talking-serious
- founder-laughing
- founder-sad
- founder-mad
- founder-thinking
- founder-reacting

**Product:**
- product-in-hand
- product-demo-feature
- product-demo-use-case
- product-close-up
- product-comparison

**Environment:**
- workspace
- outdoor
- lifestyle
- event
- travel

**Action:**
- working
- celebrating
- packaging
- on-phone

**Production:**
- text-overlay-only
- blank-space
- b-roll-cutaway
- screen-recording
- split-screen

**Fallback:**
- visual-type-unknown — frame does not match any category. Flag for manual review.

---

### 4.4 ENERGY

| Value  | Definition |
|--------|------------|
| high   | Fast, loud, emphatic, dynamic movement |
| medium | Normal conversational pace |
| low    | Slow, quiet, emotional, deliberate, still |
| silent | No speech, music only, or complete silence |

Never cut high-energy Anchor with low-energy b-roll.

---

### 4.5 REUSABILITY

| Value  | Definition |
|--------|------------|
| high   | Visually compelling, no specific references, works in any context, clean shot |
| medium | Usable but mildly context-dependent or product-specific |
| low    | Too niche, too specific, or low visual quality |
| none   | Blank space, protected zone, transition, screen recording, or under 1 second |

---

### 4.6 SENTIMENT

| Value    | Definition |
|----------|------------|
| positive | Excitement, celebration, success, gratitude, joy |
| negative | Struggle, failure, frustration, sadness, fear |
| neutral  | Informational, flat, explanatory, no strong emotion |
| mixed    | Conflicting signals, bittersweet, complex emotion |

Negative sentiment Anchor windows never pull celebrating b-roll.

---

### 4.7 FACE VISIBLE

| Value | Definition |
|-------|------------|
| true  | Face clearly visible |
| false | No face — product-only, environment, or production shot |

---

### 4.8 PRODUCT IN SHOT

| Value | Definition |
|-------|------------|
| true  | Product clearly visible |
| false | No product in frame |

---

### 4.9 QUALITY SCORE

Computed. 0–100. Based on:
- Visual stability — camera shake, motion blur
- Lighting — consistent and well-lit vs dark or blown out
- Resolution — crisp vs pixelated or compressed

Segments with quality_score below 60 are excluded from the b-roll pool.

---

### 4.10 PERFORMANCE SCORE

Computed. 0–100. Inherited from parent video — identical across all segments from the same video.

Normalize source video's views, likes, comments, shares against the creator's own average across all posted videos.

Weighting:
- Views: 40%
- Likes: 25%
- Comments: 20%
- Shares: 15%

---

### 4.11 BROLL LIKELIHOOD SCORE

Computed composite. 0–100.

**Formula:**

```
numerator =
  (context_type_score × 0.30 × context_confidence) +
  (reusability_score  × 0.20 × reusability_confidence) +
  (quality_score      × 0.20) +
  (performance_score  × 0.15) +
  (sentiment_score    × 0.15 × sentiment_confidence)

denominator =
  (0.30 × context_confidence) +
  (0.20 × reusability_confidence) +
  0.35 +
  (0.15 × sentiment_confidence)

broll_likelihood_score = numerator / denominator
```

Dividing by the sum of applied weights keeps the score properly scaled 0–100 regardless of AI confidence levels.

**Score mappings:**

| Tag          | Value     | Score |
|--------------|-----------|-------|
| context_type | vague     | 100   |
| context_type | ambiguous | 30    |
| context_type | specific  | 0     |
| context_type | none      | 0     |
| reusability  | high      | 100   |
| reusability  | medium    | 60    |
| reusability  | low       | 20    |
| reusability  | none      | 0     |
| sentiment    | positive  | 100   |
| sentiment    | neutral   | 70    |
| sentiment    | mixed     | 50    |
| sentiment    | negative  | 30    |

**Thresholds:**
- ≥ 75 → preferred b-roll candidate
- 50–74 → usable, lower priority
- < 50 → excluded from b-roll pool

---

## 5. SEGMENT OUTPUT FORMAT

```json
{
  "segment_id": "uuid",
  "source_video_id": "uuid",
  "start": 4.0,
  "end": 11.0,
  "duration": 7.0,
  "transcript": "I couldn't believe the results, we sold out in 24 hours",
  "zone":            { "value": "body",                    "confidence": 94 },
  "context_type":    { "value": "vague",                   "confidence": 88 },
  "visual_type":     { "value": "founder-talking-excited", "confidence": 91 },
  "energy":          { "value": "high",                    "confidence": 85 },
  "reusability":     { "value": "high",                    "confidence": 79 },
  "sentiment":       { "value": "positive",                "confidence": 90 },
  "face_visible":    { "value": true,                      "confidence": 97 },
  "product_in_shot": { "value": false,                     "confidence": 93 },
  "quality_score": 82,
  "performance_score": 91,
  "broll_likelihood_score": 78
}
```

---

## 6. ASSEMBLY ENGINE

### 6.1 ANCHOR SELECTION

Select Anchor based on:
- performance_score — highest relative to creator average
- Hook zone quality — short, punchy, high confidence tagging
- CTA zone present and clearly tagged
- Sufficient body length to have multiple cutaway windows

Can be auto-selected or manually overridden. If manually selected Anchor has performance_score < 50, system surfaces a warning but does not block.

User specifies X remixes to generate at runtime. Each remix uses a different Anchor, selected in descending performance_score order.

---

### 6.2 CUTAWAY WINDOW DETECTION

Scan Anchor's segmented timeline for eligible windows:
- zone: body
- context_type: vague with confidence ≥ 75
- broll_likelihood_score ≥ 50
- Duration ≥ 1 second

All other segments lock Anchor visual.

Snap each eligible window's **start** to the nearest beat timestamp from Layer C. If no beat detectable, use raw segment boundary.

---

### 6.3 B-ROLL MATCHING

For each eligible window, query the clip library and apply filters in this order:
1. zone: body only
2. quality_score ≥ 60
3. broll_likelihood_score ≥ 50
4. energy matches Anchor energy at that window
5. sentiment matches Anchor sentiment at that window
6. face_visible matches window need:
   - Emotional / narrative → prefer face_visible: true
   - Product / environment → face_visible: false acceptable
7. product_in_shot matches window need:
   - Product-referenced transcript → prefer product_in_shot: true
   - Non-product transcript → either acceptable
8. visual_type most relevant to Anchor transcript:
   - Emotional narrative → founder-reacting, founder-laughing, founder-sad, founder-talking-excited
   - Work / grind narrative → working, workspace, packaging
   - Product narrative → product-demo-use-case, product-in-hand, product-close-up
   - Success / milestone narrative → celebrating, founder-talking-excited
9. Exclude all clips from same source video as Anchor
10. Clips longer than window duration are trimmed from their start

Sort remaining candidates by broll_likelihood_score descending. Top result wins.

If no match survives all filters → default to Anchor visual. Never force a bad match.

---

### 6.4 FINAL ASSEMBLY

- Anchor audio plays 100% uninterrupted. Never cut audio.
- At each matched cutaway window: video cuts to b-roll visually
- B-roll plays for the duration of the window then cuts back to Anchor
- Output: assembled video file, same total length as Anchor, saved locally for review

---

## 7. EDGE CASES

| Situation | Behavior |
|-----------|----------|
| Hook not identifiable | Tag first 3 seconds as hook |
| CTA not identifiable | Tag last 5 seconds as cta |
| Hook and CTA overlap (short video) | Hook takes 0:00 through its duration, CTA follows, no body |
| No speech throughout | context_type: none, rely on visual_type and energy only |
| Hard cut or transition frame | blank-space, reusability: none |
| Music-only section | energy: silent, context_type: none |
| Segment under 1 second | reusability: none, excluded from b-roll pool |
| AI tag confidence < 75 | Default to Anchor visual for that window, flag for manual review |
| No b-roll match found | Default to Anchor visual, no forced match |
| Frame doesn't match any visual_type | visual-type-unknown, flag for manual review |
| No beat detectable | Use raw segment boundary |
| Manual Anchor performance_score < 50 | Surface warning, proceed |

---

## 8. OUTPUT

- X assembled video files saved locally (X specified by user)
- One file per remix
- Named by Anchor video ID + remix index
- User reviews manually for quality

---

---

# FUTURE / POST-V1 NOTES
*(Not implemented in v1 — saved for later)*

- **Auto-posting:** Post remixes to creator account on optimized schedule
- **Performance tracking:** Track views, watch time, shares, follows per remix
- **Feedback loop:** Feed performance data back to improve b-roll selection over time
- **learned_boost:** Per-clip multiplier (0.5–1.5) on performance_score, updated based on watch time retention at the moment each b-roll clip played
- **Failed window logging:** Track windows where no b-roll match was found — surfaces content creation gaps
- **Clip reuse fatigue:** Limit how often same clip appears across multiple remixes
- **Performance score refresh:** Periodic refresh of performance_score as videos age and engagement changes
