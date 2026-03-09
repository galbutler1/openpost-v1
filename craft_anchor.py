"""Test the anchor-based remix system."""

from pathlib import Path
from clipforge.workers.anchor_remixer import generate_anchor_remix

LIBRARY = Path("output/clip_library.json")

# Video 1: Use the long product pitch as anchor
print("=== Video 1: Product Pitch (anchor: full product explanation) ===")
generate_anchor_remix(
    library_path=LIBRARY,
    output_path=Path("output/remixes/anchor_01_product_pitch.mp4"),
    anchor_id="C7uBpllO5HM_clip002",  # 12.3s - full product explanation
    cut_probability=0.45,
)

# Video 2: Use the entrepreneurship reflection as anchor
print("\n=== Video 2: Entrepreneurship (anchor: character building speech) ===")
generate_anchor_remix(
    library_path=LIBRARY,
    output_path=Path("output/remixes/anchor_02_entrepreneurship.mp4"),
    anchor_id="C-1Ay8QpmbF_clip001",  # 14.3s - "both paths build your character"
    cut_probability=0.45,
)

# Video 3: Use the pizza hustle story as anchor
print("\n=== Video 3: Pizza Hustle (anchor: pizza dropship story) ===")
generate_anchor_remix(
    library_path=LIBRARY,
    output_path=Path("output/remixes/anchor_03_pizza_hustle.mp4"),
    anchor_id="C-veQ69JCBF_clip008",  # 11.5s - the pizza dropship story
    cut_probability=0.5,
)

print("\n=== All done! ===")
