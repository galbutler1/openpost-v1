"""Hand-crafted remix — curated clip selection for a compelling narrative."""

import subprocess
from pathlib import Path

OUTPUT_DIR = Path("output/remixes")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Video 1: "The Entrepreneur Origin Story" ---
# Hook → Problem → Solution → Hustle → Vision → CTA
video1_clips = [
    # Hook — immediately grabs attention with a bold claim
    ("output/clips/C-d7qToJO1T_clip001.mp4", None),   # "I invented this space-saving bowl, and it raised"
    ("output/clips/C-d7qToJO1T_clip002.mp4", None),   # "figures in less than four weeks."

    # Problem — relatable pain point
    ("output/clips/C7w1eMUvXLp_clip001.mp4", None),   # "Doing the dishes sucks, that's why I created"

    # Solution — show the product
    ("output/clips/C70eOWHOWvS_clip003.mp4", None),    # "It's a bowl that folds completely flat to save space..."
    ("output/clips/C7uBpllO5HM_clip001.mp4", None),    # "It rolls up to a bowl, then flats to a plate."

    # The grind
    ("output/clips/C-8x48op-y8_clip006.mp4", None),    # "And since then, I've been working my ass off"

    # Vision
    ("output/clips/C7w1eMUvXLp_clip007.mp4", None),    # "And I'm on a mission to revolutionize the kitchen experience."

    # CTA
    ("output/clips/C7w1eMUvXLp_clip008.mp4", None),    # "If that interests you, give me a follow..."
]

# --- Video 2: "Hustle Mentality" ---
# Motivational hook → hustle stories → lesson → closer
video2_clips = [
    # Hook — philosophical, stops the scroll
    ("output/clips/C-a60evpuLH_clip000.mp4", None),    # "You can only run your fastest when you're being chased."

    # Needed money, here's what I did
    ("output/clips/C-veQ69JCBF_clip000.mp4", None),    # "I needed capital. Here's three things I did..."
    ("output/clips/C-veQ69JCBF_clip002.mp4", None),    # "The first one was at-home car washing."
    ("output/clips/C-veQ69JCBF_clip004.mp4", None),    # "The second thing was window cleaning."
    ("output/clips/C-veQ69JCBF_clip006.mp4", None),    # "The third one was"
    ("output/clips/C-veQ69JCBF_clip007.mp4", None),    # "Pizza Dropship Inc."
    ("output/clips/C-veQ69JCBF_clip010.mp4", None),    # "We acted quickly and creatively..."

    # Lesson
    ("output/clips/C-veQ69JCBF_clip011.mp4", None),    # "Just because no one's doing it doesn't mean it's not possible."

    # Close
    ("output/clips/C-1Ay8QpmbF_clip002.mp4", None),    # "See you in the next one."
]

# --- Video 3: "Character Over Money" ---
# Deep hook → product context → philosophy → CTA
video3_clips = [
    # Hook — vulnerable, real
    ("output/clips/C-1Ay8QpmbF_clip000.mp4", None),    # "For me, the hardest part about entrepreneurship is not knowing..."

    # The lesson
    ("output/clips/C-1Ay8QpmbF_clip001.mp4", None),    # "success, or failure. But both paths lead to the same place..."

    # What he built
    ("output/clips/C-d7qToJO1T_clip001.mp4", None),    # "I invented this space-saving bowl, and it raised"
    ("output/clips/C-d7qToJO1T_clip002.mp4", None),    # "figures in less than four weeks."

    # Vision
    ("output/clips/C-d7qToJO1T_clip005.mp4", None),    # "to revolutionize the kitchen industry."

    # CTA
    ("output/clips/C-d7qToJO1T_clip007.mp4", None),    # "It's been easier. Drop me a follow."
]


def render_video(clips: list[tuple[str, float | None]], output_name: str):
    """Render a hand-crafted video from a list of (clip_path, max_duration) tuples."""
    output_path = (OUTPUT_DIR / output_name).resolve()
    trimmed = []

    for i, (clip_path, max_dur) in enumerate(clips):
        clip_path = Path(clip_path).resolve()
        trimmed_path = (OUTPUT_DIR / f"_craft_trim_{i}.mp4").resolve()

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
        ]
        if max_dur:
            cmd += ["-t", str(max_dur)]
        cmd += [
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,"
                   "pad=720:1280:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-ar", "44100",
            "-loglevel", "error",
            str(trimmed_path),
        ]
        subprocess.run(cmd, check=True)
        trimmed.append(trimmed_path)

    # Write concat list
    concat_file = (OUTPUT_DIR / f"{output_name}_concat.txt").resolve()
    with open(concat_file, "w") as f:
        for t in trimmed:
            f.write(f"file '{t}'\n")

    # Concatenate
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264", "-c:a", "aac",
        "-movflags", "+faststart",
        "-loglevel", "error",
        str(output_path),
    ], check=True)

    # Cleanup
    concat_file.unlink(missing_ok=True)
    for t in trimmed:
        t.unlink(missing_ok=True)

    print(f"✓ Rendered: {output_path}")


if __name__ == "__main__":
    print("Rendering Video 1: The Entrepreneur Origin Story")
    render_video(video1_clips, "crafted_01_origin_story.mp4")

    print("\nRendering Video 2: Hustle Mentality")
    render_video(video2_clips, "crafted_02_hustle_mentality.mp4")

    print("\nRendering Video 3: Character Over Money")
    render_video(video3_clips, "crafted_03_character_over_money.mp4")

    print("\nDone! Check output/remixes/")
