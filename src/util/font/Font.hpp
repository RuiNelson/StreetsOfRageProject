#pragma once

#include <SDL3/SDL.h>
#include <cstddef>
#include <cstdint>

class SystemMemory;

struct Color {
    uint8_t r, g, b, a;
};

struct FontPixelBuffer {
    uint8_t *data;       // malloc'd, caller does free
    size_t   size_bytes; // data size
    int      width;      // 8
    int      height;     // 8
};

/**
 * @class Font
 * @brief 8×8 bitmap font renderer.
 *
 * Provides static methods to render ASCII glyphs (range 0x20–0x7E) using a
 * monochrome 8×8 bitmap dataset as either an SDL texture or a pixel buffer.
 */
class Font {
    public:
    Font() = delete;

    /**
     * @brief Converts an 8×8 bitmap character to a pixel buffer.
     * @param ascii ASCII code (0x20–0x7E). Out of range defaults to space (0x20).
     * @param withAlpha If true, output is RGBA (4 bytes/pixel). If false, RGB (3 bytes/pixel).
     * @param foreground Color for pixels set to 1 in the bitmap.
     * @param background Color for pixels set to 0 in the bitmap.
     * @return FontPixelBuffer with data allocated via malloc(). Caller must free() the data.
     */
    static FontPixelBuffer fontCharToPixels(uint8_t ascii, bool withAlpha, Color foreground, Color background);

    /**
     * @brief Creates an 8×8 grayscale SDL texture for a given ASCII character.
     * @param renderer SDL renderer used to create the texture.
     * @param ascii    ASCII code of the character to render (0x20–0x7E).
     *                  Values outside this range default to space (0x20).
     * @param foreground Color for pixels set to 1 in the bitmap.
     * @param background Color for pixels set to 0 in the bitmap.
     * @return Newly created SDL_Texture* with RGBA8888 format, or nullptr on failure.
     *
     * @note The caller owns the returned texture and is responsible for
     *       calling SDL_DestroyTexture() when it is no longer needed.
     */
    static SDL_Texture *fontCharToTexture(SDL_Renderer *renderer, uint8_t ascii, Color foreground, Color background);

    /**
     * @brief Encodes an 8×8 character glyph as a Mega Drive VDP tile into work RAM.
     *
     * Writes 32 bytes in VDP 4bpp format starting at @p ramAddress.
     * Each byte encodes two horizontally adjacent pixels:
     *   high nibble = left pixel, low nibble = right pixel.
     * Row-major order (8 rows × 4 bytes/row).
     *
     * @param memory     System memory to write the tile into.
     * @param ascii      ASCII code (0x20–0x7E). Out-of-range defaults to space.
     * @param fgIndex    4-bit palette index (0–15) for set pixels (foreground).
     * @param bgIndex    4-bit palette index (0–15) for unset pixels (background).
     * @param ramAddress Work-RAM destination address for the 32-byte tile.
     *                   Caller is responsible for ensuring the address is valid
     *                   and that 32 bytes are available from that address.
     */
    static void
    fontCharToVDPTile(SystemMemory &memory, uint8_t ascii, uint8_t fgIndex, uint8_t bgIndex, uint32_t ramAddress);
};