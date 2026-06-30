#pragma once

#include "data_types.hpp"
#include <SDL3/SDL.h>
#include <cstring>

/**
 * @brief 320×224 BGR framebuffer (3 bytes per pixel).
 *
 * Matches the Mega Drive NTSC visible area exactly (H40 mode: 320×224).
 * The VDP outputs 3 bits per colour channel (9-bit colour).
 * The framebuffer stores these native values; conversion to 8-bit-per-channel
 * is done on demand for display or PNG export.
 */
class Framebuffer {
    public:
    /// Framebuffer width (pixels). Mega Drive H40 mode.
    static constexpr int WIDTH = 320;
    /// Framebuffer height (pixels). NTSC visible area.
    static constexpr int HEIGHT = 224;
    /// Bytes per pixel (BGR order, 3-bit per channel stored in low 3 bits).
    static constexpr int BPP = 3;
    /// Bytes per scanline (WIDTH × BPP).
    static constexpr int PITCH = WIDTH * BPP;
    /// Total framebuffer size in bytes (WIDTH × HEIGHT × BPP).
    static constexpr int SIZE = WIDTH * HEIGHT * BPP;

    /// Initializes framebuffer to all black.
    Framebuffer();

    /// Returns mutable pointer to raw pixel data.
    void *getRawPointer();

    /// Returns const pointer to raw pixel data.
    const void *getRawPointer() const;

    /// Sets one pixel at (X, Y) with BGR values (each 0–7, stored in low 3 bits). Bounds checked.
    void setPixel(int x, int y, m_byte b, m_byte g, m_byte r);

    /// Reads one pixel at (X, Y) into BGR references. Bounds checked; returns black if out of bounds.
    void getPixel(int x, int y, m_byte &b, m_byte &g, m_byte &r) const;

    /// Fills entire framebuffer with black (all zeros).
    void clear();

    /// Returns new framebuffer with 3-bit values expanded to 8-bit (0→0, 7→255) via lookup table.
    Framebuffer convertTo8BitsPerPixel() const;

    /// Uploads framebuffer pixels (3-bit expanded to 8-bit) into an existing SDL_Texture via SDL_UpdateTexture.
    void uploadToTexture(SDL_Texture *tex) const;

    private:
    /// Pixel data array: [Y * WIDTH + X] * BPP gives BGR triple.
    m_byte pixels_[SIZE];
};
