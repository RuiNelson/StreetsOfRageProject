/**
 * @file VDPTile.cpp
 * @brief Tile decoding and colour conversion.
 */

#include "VDPTile.hpp"

/// Extracts one pixel from an 8×8 tile in VRAM. Each tile is 32 bytes (4 bytes per row, 2 pixels per byte, 4 bits per
/// pixel). Applies horizontal and vertical flip if specified. Returns 0 if address out of bounds.
m_byte VDPTile::getTilePixel(int tileAddr, int pixelX, int pixelY, bool hflip, bool vflip) const {
    if (vflip)
        pixelY = 7 - pixelY;
    if (hflip)
        pixelX = 7 - pixelX;

    int byteOffset = tileAddr + pixelY * 4 + (pixelX >> 1);
    if (byteOffset < 0 || byteOffset >= VDPState::VRAM_SIZE)
        return 0;

    m_byte byte = state_->vram_[byteOffset];
    // Even pixel (0,2,4,6) → high nibble; odd pixel (1,3,5,7) → low nibble
    return (pixelX & 1) == 0 ? (byte >> 4) & 0x0F : byte & 0x0F;
}

/// Converts CRAM palette entry to native 3-bit BGR values (0–7) directly from CRAM data layout.
/// CRAM entry format: bits 9–11=B, 5–7=G, 1–3=R (0x0EEE mask).
void VDPTile::cramToRGB(m_byte palette, m_byte colorIndex, m_byte &r, m_byte &g, m_byte &b) const {
    m_word entry = state_->cram_[(palette & 3) * 16 + (colorIndex & 15)];
    r            = static_cast<m_byte>((entry >> 1) & 0x07);
    g            = static_cast<m_byte>((entry >> 5) & 0x07);
    b            = static_cast<m_byte>((entry >> 9) & 0x07);
}

/// Converts CRAM palette entry to full 8-bit BGR values (0–255) using lookup table.
/// LUT maps 3-bit values [0..7] → [0, 36, 73, 109, 146, 182, 219, 255].
void VDPTile::cramToRGB_FullRange(m_byte palette, m_byte colorIndex, m_byte &r, m_byte &g, m_byte &b) const {
    static constexpr m_byte lut[8] = {0, 36, 73, 109, 146, 182, 219, 255};
    m_byte                  r3, g3, b3;
    cramToRGB(palette, colorIndex, r3, g3, b3);
    r = lut[r3];
    g = lut[g3];
    b = lut[b3];
}