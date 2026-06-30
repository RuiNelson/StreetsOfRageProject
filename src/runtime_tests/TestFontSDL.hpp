#pragma once

#include <SDL3/SDL.h>

/**
 * @file TestFontSDL.hpp
 * @brief Runtime test for the bitmap font renderer and 3D cube visualisation.
 *
 * This test verifies that Font::getCharTexture() produces correct SDL textures
 * from the 8×8 bitmap data in FontData.hpp, and demonstrates a rotating solid
 * cube with per-face background and glyph colours.
 */

/**
 * @brief Runs the font + cube runtime test.
 *
 * Creates a 640×480 SDL window and displays:
 *
 * 1. **"Hello World"** at top-left in two sizes (always fully opaque):
 *    - 8×8 glyphs scaled 2× (yellow, y=20)
 *    - 8×8 glyphs scaled 4× (cyan,  y=60)
 *
 * 2. **Solid cube** (200×200×200, half-size 100px) centred at (320, 240):
 *    - Rotates continuously on pitch (X) and yaw (Y) axes.
 *    - Back-face culled; visible faces depth-sorted back-to-front
 *      (painter's algorithm).
 *    - Each face has a distinct random background colour (set at init).
 *    - Each face displays a random ASCII glyph in a distinct random colour,
 *      depth-scaled and centred on the face.
 *
 * **Fade cycle** (cube only):
 *    - 0–10 s  : fully visible
 *    - 10–12 s : fades out (alpha 255→0)
 *    - 12–14 s : invisible — face glyphs and glyph colours are re-randomised
 *                 once at the start of this window; background colours unchanged
 *    - 14–16 s : fades back in (alpha 0→255)
 *    - repeat
 *
 * Press ESC or close the window to exit.
 */
void testFontSDL();
