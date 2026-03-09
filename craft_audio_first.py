"""Craft audio-first remixes with curated narratives."""

from pathlib import Path
from clipforge.workers.audio_first_remixer import create_audio_first_remix

LIBRARY = Path("output/clip_library.json")

# --- Video 1: "Origin Story" ---
# Clean narrative arc: problem → invention → product → grind → vision
print("=== Video 1: Origin Story ===")
create_audio_first_remix(
    library_path=LIBRARY,
    narrative_clip_ids=[
        "C7uBpllO5HM_clip000",   # "I invented a dish that makes your kitchen experience easier."
        "C7w1eMUvXLp_clip001",    # "Doing the dishes sucks, that's why I created"
        "C70eOWHOWvS_clip003",    # "It's a bowl that folds completely flat to save space..."
        "C7uBpllO5HM_clip001",    # "It rolls up to a bowl, then flats to a plate."
        "C-8x48op-y8_clip006",    # "And since then, I've been working my ass off"
        "C-d7qToJO1T_clip001",    # "I invented this space-saving bowl, and it raised"
        "C-d7qToJO1T_clip002",    # "figures in less than four weeks."
        "C7w1eMUvXLp_clip007",    # "And I'm on a mission to revolutionize the kitchen experience."
        "C7w1eMUvXLp_clip008",    # "If that interests you, give me a follow..."
    ],
    output_path=Path("output/remixes/af_01_origin_story.mp4"),
)

# --- Video 2: "Hustle & Lessons" ---
# Motivational hook → real stories → wisdom
print("\n=== Video 2: Hustle & Lessons ===")
create_audio_first_remix(
    library_path=LIBRARY,
    narrative_clip_ids=[
        "C-a60evpuLH_clip000",    # "You can only run your fastest when you're being chased."
        "C-veQ69JCBF_clip000",    # "I needed capital. Here's three things I did..."
        "C-veQ69JCBF_clip003",    # "I got much better at sales...learned a lot about business."
        "C-veQ69JCBF_clip010",    # "We acted quickly and creatively..."
        "C-veQ69JCBF_clip011",    # "Just because no one's doing it doesn't mean it's not possible."
        "C-veQ69JCBF_clip012",    # "And there isn't money to be made."
    ],
    output_path=Path("output/remixes/af_02_hustle_lessons.mp4"),
)

# --- Video 3: "Character Over Money" ---
# Deep, philosophical, vulnerable
print("\n=== Video 3: Character Over Money ===")
create_audio_first_remix(
    library_path=LIBRARY,
    narrative_clip_ids=[
        "C-1Ay8QpmbF_clip000",    # "For me, the hardest part about entrepreneurship is not knowing..."
        "C-1Ay8QpmbF_clip001",    # "success, or failure. But both paths lead to the same place..."
        "C-a60evpuLH_clip003",    # "What helps me get motivated is thinking about the ambition"
        "C-d7qToJO1T_clip005",    # "to revolutionize the kitchen industry."
        "C-veQ69JCBF_clip011",    # "Just because no one's doing it doesn't mean it's not possible."
    ],
    output_path=Path("output/remixes/af_03_character.mp4"),
)

print("\n=== All done! ===")
