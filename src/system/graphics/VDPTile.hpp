#pragma once

#include "VDPState.hpp"
#include "data_types.hpp"

/**
 * @file VDPTile.hpp
 * @brief Tile decoding and colour conversion for the VDP renderer.
 */

class VDPTile {
    public:
    explicit VDPTile(const VDPState &state) : state_(&state) {
    }

    // ── Tile decoding ──────────────────────────────────────────────────────

    /// Reads one pixel from a tile in VRAM.
    /// Tile format: 8×8 pixels, 4 bits per pixel (32 bytes per tile).
    m_byte getTilePixel(int tileAddr, int pixelX, int pixelY, bool hflip, bool vflip) const;

    // ── Colour conversion ───────────────────────────────────────────────────

    /// Converts CRAM palette entry to native 3-bit BGR values (0–7).
    void cramToRGB(m_byte palette, m_byte colorIndex, m_byte &r, m_byte &g, m_byte &b) const;

    /// Converts CRAM palette entry to full 8-bit BGR values (0–255).
    void cramToRGB_FullRange(m_byte palette, m_byte colorIndex, m_byte &r, m_byte &g, m_byte &b) const;

    private:
    const VDPState *state_;
};