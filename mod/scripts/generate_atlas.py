#!/usr/bin/env python3
"""
Generate a texture atlas from individual icon files.

This script combines all icon PNGs into a single atlas image,
reducing the number of textures loaded by the mod.

Usage:
    python scripts/generate_atlas.py

Output:
    - assets/icons_atlas.png: The combined texture atlas
    - Prints the layout for use in Rust code
"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

# Configuration
ICON_SIZE = 128  # Each icon is 128x128
ICONS_PER_ROW = 8  # 8 icons per row in the atlas

# Icon definitions: (name, path, has_gray_variant)
# Order matters! This determines the index used in Rust code.
ICONS = [
    # Great Runes (colored + gray variants)
    ("godrick", "runes/godrick.png", True),
    ("unborn", "runes/unborn.png", True),
    ("rykard", "runes/rykard.png", True),
    ("radahn", "runes/radahn.png", True),
    ("morgott", "runes/morgott.png", True),
    ("mohg", "runes/mohg.png", True),
    ("malenia", "runes/malenia.png", True),
    # Other icons (no gray variant)
    ("kindling", "messmers_kindling.png", False),
    ("death", "death.png", False),
]


def main():
    script_dir = Path(__file__).parent
    assets_dir = script_dir.parent / "assets"
    output_path = assets_dir / "icons_atlas.png"

    # Calculate atlas dimensions
    # Row 0: colored icons
    # Row 1: gray icons (for runes) + other icons
    total_colored = len(ICONS)
    total_gray = sum(1 for _, _, has_gray in ICONS if has_gray)

    # We'll use 2 rows: colored on top, gray on bottom
    # Icons without gray variant will have empty space in row 1
    cols = max(total_colored, ICONS_PER_ROW)
    rows = 2

    atlas_width = cols * ICON_SIZE
    atlas_height = rows * ICON_SIZE

    print(f"Creating atlas: {atlas_width}x{atlas_height} ({cols} cols x {rows} rows)")
    print(f"Icon size: {ICON_SIZE}x{ICON_SIZE}")
    print()

    # Create atlas with transparent background
    atlas = Image.new("RGBA", (atlas_width, atlas_height), (0, 0, 0, 0))

    # Track layout for Rust code generation
    layout = []

    for idx, (name, path, has_gray) in enumerate(ICONS):
        col = idx % cols

        # Load and paste colored icon (row 0)
        colored_path = assets_dir / path
        if not colored_path.exists():
            print(f"Warning: {colored_path} not found, skipping")
            continue

        colored_img = Image.open(colored_path).convert("RGBA")
        if colored_img.size != (ICON_SIZE, ICON_SIZE):
            print(f"  Resizing {name} from {colored_img.size} to {ICON_SIZE}x{ICON_SIZE}")
            colored_img = colored_img.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)

        x = col * ICON_SIZE
        y_colored = 0
        atlas.paste(colored_img, (x, y_colored))
        print(f"[{idx}] {name}: col={col}, row=0 (colored)")

        # Load and paste gray icon (row 1) if it exists
        if has_gray:
            gray_path = assets_dir / path.replace(".png", "_gray.png")
            if gray_path.exists():
                gray_img = Image.open(gray_path).convert("RGBA")
                if gray_img.size != (ICON_SIZE, ICON_SIZE):
                    gray_img = gray_img.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
                y_gray = ICON_SIZE
                atlas.paste(gray_img, (x, y_gray))
                print(f"    {name}_gray: col={col}, row=1")
            else:
                print(f"    Warning: {gray_path} not found")

        layout.append({
            "name": name,
            "index": idx,
            "col": col,
            "has_gray": has_gray,
        })

    # Save atlas
    atlas.save(output_path, "PNG")
    print()
    print(f"Atlas saved to: {output_path}")
    print()

    # Generate Rust constants
    print("=" * 60)
    print("Rust code for src/dll/icon_atlas.rs:")
    print("=" * 60)
    print()
    print(f"pub const ATLAS_WIDTH: u32 = {atlas_width};")
    print(f"pub const ATLAS_HEIGHT: u32 = {atlas_height};")
    print(f"pub const ICON_SIZE: u32 = {ICON_SIZE};")
    print(f"pub const ICONS_PER_ROW: u32 = {cols};")
    print()
    print("// Icon indices (column in the atlas)")
    for item in layout:
        const_name = f"ICON_{item['name'].upper()}"
        print(f"pub const {const_name}: u32 = {item['index']};")
    print()
    print("// UV calculation helper")
    print("// For colored: row = 0")
    print("// For gray: row = 1")
    print("// u0 = (col * ICON_SIZE) / ATLAS_WIDTH")
    print("// v0 = (row * ICON_SIZE) / ATLAS_HEIGHT")
    print("// u1 = ((col + 1) * ICON_SIZE) / ATLAS_WIDTH")
    print("// v1 = ((row + 1) * ICON_SIZE) / ATLAS_HEIGHT")


if __name__ == "__main__":
    main()
