/**
 * @file Framebuffer.cpp
 * @brief 320×240 BGR framebuffer for the VDP emulator.
 */

#include "Framebuffer.hpp"

/// Initializes framebuffer and clears to black.
Framebuffer::Framebuffer() {
    clear();
}

/// Returns mutable pointer to pixel data for direct read/write access.
void *Framebuffer::getRawPointer() {
    return pixels_;
}

/// Returns const pointer to pixel data for read-only access.
const void *Framebuffer::getRawPointer() const {
    return pixels_;
}

/// Sets pixel at (X, Y) to BGR values (each 3-bit: 0–7, stored in low 3 bits). Silently clips out-of-bounds writes.
void Framebuffer::setPixel(int x, int y, m_byte b, m_byte g, m_byte r) {
    if (x < 0 || x >= WIDTH || y < 0 || y >= HEIGHT)
        return;
    int offset          = (y * WIDTH + x) * BPP;
    pixels_[offset + 0] = b;
    pixels_[offset + 1] = g;
    pixels_[offset + 2] = r;
}

/// Reads pixel at (X, Y) into BGR references. Returns black (0, 0, 0) if out of bounds.
void Framebuffer::getPixel(int x, int y, m_byte &b, m_byte &g, m_byte &r) const {
    if (x < 0 || x >= WIDTH || y < 0 || y >= HEIGHT) {
        b = g = r = 0;
        return;
    }
    int offset = (y * WIDTH + x) * BPP;
    b          = pixels_[offset + 0];
    g          = pixels_[offset + 1];
    r          = pixels_[offset + 2];
}

/// Fills entire framebuffer with black (all bytes = 0).
void Framebuffer::clear() {
    std::memset(pixels_, 0, SIZE);
}

/// Creates new framebuffer with 3-bit values expanded to 8-bit using lookup table.
/// Maps 3-bit channel [0..7] → 8-bit [0, 36, 73, 109, 146, 182, 219, 255] for linear expansion.
Framebuffer Framebuffer::convertTo8BitsPerPixel() const {
    static constexpr m_byte lut[8] = {0, 36, 73, 109, 146, 182, 219, 255};

    Framebuffer result;
    auto       *dst = static_cast<m_byte *>(result.getRawPointer());
    for (int i = 0; i < SIZE; ++i) {
        dst[i] = lut[pixels_[i] & 0x07];
    }
    return result;
}

/// Uploads 3-bit-expanded pixel data into an existing SDL_Texture (no alloc).
void Framebuffer::uploadToTexture(SDL_Texture *tex) const {
    Framebuffer expanded = convertTo8BitsPerPixel();
    SDL_UpdateTexture(tex, nullptr, expanded.getRawPointer(), PITCH);
}
