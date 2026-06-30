#!/usr/bin/env python3
"""
Converts PNG artwork to Mega Drive VDP tile data (C++ headers).

VDP tile format: 8×8 pixels, 4bpp, 32 bytes per tile.
Each byte: high nibble = left pixel (even col), low nibble = right pixel (odd col).
Row-major order: tile[row*4 + col//2].

CRAM colour format: 0000_BBB0_GGG0_RRR0  (3 bits per channel, bits 9/5/1)
Transparent colour: palette index 0 (always transparent in VDP).

Output files:
  GirlTileData.hpp      — 72 tiles (6×12), palette index 0 = transparent
  DuckTileData.hpp      — 16 tiles (4×4),  palette index 0 = transparent
  BackgroundTileData0.hpp — bg rows 0–13   (560 tiles)
  BackgroundTileData1.hpp — bg rows 14–27  (560 tiles)
  BackgroundTileData.hpp  — includes both halves + combined palette
"""

import os
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── helpers ──────────────────────────────────────────────────────────────────

def rgb_to_cram(r: int, g: int, b: int) -> int:
    """Convert 8-bit RGB to Mega Drive CRAM word (0000_BBB0_GGG0_RRR0)."""
    r3 = (r >> 5) & 7
    g3 = (g >> 5) & 7
    b3 = (b >> 5) & 7
    return (b3 << 9) | (g3 << 5) | (r3 << 1)


def image_to_indexed(img: Image.Image, max_colors: int, has_alpha: bool):
    """
    Quantize *img* to at most *max_colors* palette entries.

    If *has_alpha* is True the first palette slot is reserved for transparent
    pixels (any pixel with alpha < 128).  The remaining slots hold the opaque
    colours produced by quantization.

    Returns (indexed_img, palette_rgba) where palette_rgba is a list of
    (r, g, b, a) tuples of length max_colors.
    """
    if has_alpha:
        # Separate alpha mask before quantizing the opaque pixels.
        rgba   = img.convert("RGBA")
        pixels = list(rgba.getdata())
        alpha_mask = [p[3] < 128 for p in pixels]

        # Build an opaque-only image for quantization.
        opaque = Image.new("RGB", img.size, (0, 0, 0))
        opaque.putdata([p[:3] for p in pixels])
        quantized = opaque.quantize(colors=max_colors - 1, method=Image.Quantize.MEDIANCUT)
        q_pixels  = list(quantized.getdata())
        q_palette = quantized.getpalette()          # flat R,G,B list, 256 entries
        actual_colors = quantized.getcolors(maxcolors=65536)
        used_indices  = {idx for _count, idx in (actual_colors or [])}
        num_q = min(max_colors - 1, max((used_indices or {0})) + 1)

        # Build final palette: slot 0 = transparent, slots 1…N = quantized colours.
        palette_rgba = [(0, 0, 0, 0)]               # transparent
        for i in range(num_q):
            r, g, b = q_palette[i*3], q_palette[i*3+1], q_palette[i*3+2]
            palette_rgba.append((r, g, b, 255))
        # Pad to max_colors with black if needed.
        while len(palette_rgba) < max_colors:
            palette_rgba.append((0, 0, 0, 255))

        # Remap pixel indices: transparent → 0, opaque → qidx+1.
        indexed_pixels = []
        for is_transparent, qidx in zip(alpha_mask, q_pixels):
            indexed_pixels.append(0 if is_transparent else qidx + 1)

        result = Image.new("P", img.size)
        result.putdata(indexed_pixels)
        return result, palette_rgba

    else:
        rgb       = img.convert("RGB")
        quantized = rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
        q_palette = quantized.getpalette()
        actual_colors = quantized.getcolors(maxcolors=65536)
        used_indices  = {idx for _count, idx in (actual_colors or [])}
        num_q = min(max_colors, max((used_indices or {0})) + 1)
        palette_rgba = []
        for i in range(num_q):
            r, g, b = q_palette[i*3], q_palette[i*3+1], q_palette[i*3+2]
            palette_rgba.append((r, g, b, 255))
        while len(palette_rgba) < max_colors:
            palette_rgba.append((0, 0, 0, 255))
        return quantized, palette_rgba


def extract_tiles(indexed_img: Image.Image, tile_cols: int, tile_rows: int):
    """
    Extract 8×8 tiles from an indexed image.

    Tiles are returned in row-major order (left-to-right, top-to-bottom).
    Each tile is 32 bytes in VDP 4bpp format.
    """
    pixels = list(indexed_img.getdata())
    W      = indexed_img.width
    tiles  = []
    for ty in range(tile_rows):
        for tx in range(tile_cols):
            tile = []
            for row in range(8):
                for col in range(0, 8, 2):
                    px = ty * 8 * W + row * W + tx * 8 + col
                    left  = pixels[px]     & 0x0F
                    right = pixels[px + 1] & 0x0F
                    tile.append((left << 4) | right)
            tiles.append(bytes(tile))
    return tiles


def palette_to_cram(palette_rgba):
    """Convert palette_rgba list → list of CRAM words (uint16_t)."""
    return [rgb_to_cram(r, g, b) for r, g, b, _a in palette_rgba]


# ── writers ──────────────────────────────────────────────────────────────────

def write_tile_array(f, name: str, tiles: list, start: int = 0, count: int = -1):
    """Write a C++ constexpr uint8_t array for the given tile slice."""
    if count < 0:
        count = len(tiles) - start
    f.write(f"// {count} tiles × 32 bytes = {count * 32} bytes\n")
    f.write(f"inline constexpr uint8_t {name}[{count}][32] = {{\n")
    for i in range(start, start + count):
        tile = tiles[i]
        hex_bytes = ", ".join(f"0x{b:02X}" for b in tile)
        f.write(f"    {{ {hex_bytes} }},  // tile {i}\n")
    f.write("};\n")


def write_palette_array(f, name: str, cram_words: list):
    """Write a C++ constexpr uint16_t array for CRAM palette words."""
    f.write(f"// {len(cram_words)} CRAM entries (0000_BBB0_GGG0_RRR0)\n")
    f.write(f"inline constexpr uint16_t {name}[{len(cram_words)}] = {{\n")
    for i, w in enumerate(cram_words):
        f.write(f"    0x{w:04X},  // index {i}\n")
    f.write("};\n")


# ── per-asset conversion ──────────────────────────────────────────────────────

def convert_sprite(png_path: str, out_path: str, guard: str,
                   tile_w: int, tile_h: int,
                   tile_array: str, palette_array: str,
                   has_alpha: bool = True):
    img      = Image.open(png_path)
    # Ensure dimensions are tile-aligned.
    img      = img.crop((0, 0, tile_w * 8, tile_h * 8))
    indexed, pal_rgba = image_to_indexed(img, 16, has_alpha)
    tiles    = extract_tiles(indexed, tile_w, tile_h)
    cram     = palette_to_cram(pal_rgba)

    with open(out_path, "w") as f:
        f.write(f"#pragma once\n\n")
        f.write(f"#include <cstdint>\n\n")
        f.write(f"// Auto-generated by convert_art.py — do not edit.\n")
        f.write(f"// Source: {os.path.basename(png_path)}  ({tile_w}×{tile_h} tiles, {tile_w*8}×{tile_h*8} px)\n")
        f.write(f"// Palette index 0 = transparent.\n\n")
        f.write(f"namespace {guard} {{\n\n")
        f.write(f"static constexpr int TILE_W = {tile_w};\n")
        f.write(f"static constexpr int TILE_H = {tile_h};\n")
        f.write(f"static constexpr int TILE_COUNT = {tile_w * tile_h};\n\n")
        write_palette_array(f, palette_array, cram)
        f.write("\n")
        write_tile_array(f, tile_array, tiles)
        f.write(f"\n}} // namespace {guard}\n")

    print(f"  {out_path}  ({tile_w*tile_h} tiles, {len(cram)} palette entries)")


def convert_background(png_path: str, crop_w: int, crop_h: int, out_dir: str):
    """
    Converts the background PNG to VDP tiles, split across two header files.
    A third umbrella header includes both and declares the combined palette.
    """
    img      = Image.open(png_path).convert("RGB")
    img      = img.crop((0, 0, crop_w, crop_h))
    indexed, pal_rgba = image_to_indexed(img, 16, has_alpha=False)
    tile_cols = crop_w // 8
    tile_rows = crop_h // 8
    tiles     = extract_tiles(indexed, tile_cols, tile_rows)
    cram      = palette_to_cram(pal_rgba)

    total     = len(tiles)
    half      = total // 2   # split evenly

    # Part 0: tiles 0 … half-1
    path0 = os.path.join(out_dir, "BackgroundTileData0.hpp")
    with open(path0, "w") as f:
        f.write("#pragma once\n\n#include <cstdint>\n\n")
        f.write("// Auto-generated by convert_art.py — do not edit.\n")
        f.write(f"// Background rows 0–{half // tile_cols - 1}  ({half} tiles)\n\n")
        f.write("namespace BG0 {\n\n")
        write_tile_array(f, "tiles", tiles, start=0, count=half)
        f.write("\n} // namespace BG0\n")
    print(f"  {path0}  ({half} tiles)")

    # Part 1: tiles half … total-1
    path1 = os.path.join(out_dir, "BackgroundTileData1.hpp")
    with open(path1, "w") as f:
        f.write("#pragma once\n\n#include <cstdint>\n\n")
        f.write("// Auto-generated by convert_art.py — do not edit.\n")
        f.write(f"// Background rows {half // tile_cols}–{tile_rows - 1}  ({total - half} tiles)\n\n")
        f.write("namespace BG1 {\n\n")
        write_tile_array(f, "tiles", tiles, start=half, count=total - half)
        f.write("\n} // namespace BG1\n")
    print(f"  {path1}  ({total - half} tiles)")

    # Umbrella header
    path_main = os.path.join(out_dir, "BackgroundTileData.hpp")
    with open(path_main, "w") as f:
        f.write("#pragma once\n\n#include <cstdint>\n\n")
        f.write('#include "BackgroundTileData0.hpp"\n')
        f.write('#include "BackgroundTileData1.hpp"\n\n')
        f.write("// Auto-generated by convert_art.py — do not edit.\n")
        f.write(f"// Source: {os.path.basename(png_path)}  cropped to {crop_w}×{crop_h} px\n")
        f.write(f"// {tile_cols} tiles wide × {tile_rows} tiles tall = {total} tiles total.\n\n")
        f.write("namespace BG {\n\n")
        f.write(f"static constexpr int TILE_W     = {tile_cols};\n")
        f.write(f"static constexpr int TILE_H     = {tile_rows};\n")
        f.write(f"static constexpr int TILE_COUNT = {total};\n")
        f.write(f"static constexpr int HALF       = {half};\n\n")
        write_palette_array(f, "palette", cram)
        f.write("\n} // namespace BG\n")
    print(f"  {path_main}  (palette + metadata, {total} tiles total)")


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    art = SCRIPT_DIR

    print("Converting girl.png …")
    convert_sprite(
        png_path      = os.path.join(art, "girl.png"),
        out_path      = os.path.join(art, "GirlTileData.hpp"),
        guard         = "Girl",
        tile_w        = 6,   # 48 px / 8
        tile_h        = 12,  # 96 px / 8
        tile_array    = "tiles",
        palette_array = "palette",
        has_alpha     = True,
    )

    print("Converting duck.png …")
    convert_sprite(
        png_path      = os.path.join(art, "duck.png"),
        out_path      = os.path.join(art, "DuckTileData.hpp"),
        guard         = "Duck",
        tile_w        = 4,   # 32 px / 8
        tile_h        = 4,   # 32 px / 8
        tile_array    = "tiles",
        palette_array = "palette",
        has_alpha     = True,
    )

    print("Converting background2.png …")
    convert_background(
        png_path = os.path.join(art, "background2.png"),
        crop_w   = 320,   # 40 tiles wide (full H40 screen width)
        crop_h   = 224,   # 28 tiles tall  (one VDP screen height)
        out_dir  = art,
    )

    print("Done.")
