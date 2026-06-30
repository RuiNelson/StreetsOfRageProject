#pragma once

#include "Framebuffer.hpp"
#include "VDPState.hpp"
#include "VDPTile.hpp"
#include "data_types.hpp"

/**
 * @file VDPRenderer.hpp
 * @brief VDP scanline renderer — evaluates planes, sprites, window, and composites.
 */

class VDPRenderer {
    public:
    /// Initializes renderer with references to VDP state, tile decoder, and framebuffer.
    explicit VDPRenderer(VDPState &state, VDPTile &tile, Framebuffer &fb);

    /// Renders a full frame (224 scanlines) into the framebuffer. Respects display enabled flag.
    void renderFrame();

    /// Renders a single scanline into the framebuffer at the given Y position.
    void renderScanline(int line);

    /// Per-pixel layer evaluation result: color, palette, priority, and opacity.
    struct PixelResult {
        m_byte colorIndex; ///< Color index within palette (0–15).
        m_byte palette;    ///< Palette selection (0–3).
        bool   priority;   ///< High priority layer (overlays lower priority).
        bool   opaque;     ///< True if pixel is non-transparent.
    };

    /// Result of compositing all layers (planes A/B, sprites) at a pixel.
    struct CompositeResult {
        m_byte r, g, b; ///< Final RGB color (3-bit per channel).
        bool   valid;   ///< True if pixel came from a layer (not background).
    };

    // ── Layer evaluation ────────────────────────────────────────────────────

    /// Evaluates plane pixel at screen coordinates (X, Y) with given scroll offsets.
    PixelResult getPlanePixel(int planeBase, int hscroll, int vscroll, int screenX, int screenY) const;

    /// Evaluates window plane pixel at screen coordinates (X, Y).
    PixelResult getWindowPixel(int screenX, int screenY) const;

    /// Checks if window plane is active at cell coordinates (cellX, cellY).
    bool isWindowActive(int cellX, int cellY) const;

    /// Evaluates sprite pixel at screen coordinates (X, Y) using SAT. Sets SCOL bit (status 0x20) when two
    /// opaque sprite pixels overlap at the same screen position.
    ///
    /// Retained for reference/tests: the frame render path no longer calls this per pixel — see
    /// buildSpriteLine(), which evaluates the SAT once per scanline into spriteLine_.
    PixelResult getSpritePixel(int screenX, int screenY);

    // ── Compositing ─────────────────────────────────────────────────────────

    /// Resolves final pixel color by compositing plane B, plane A, sprite, and background colors using priority.
    CompositeResult resolvePixel(
        PixelResult planeBPx, PixelResult planeAPx, PixelResult spritePx, m_byte bgR, m_byte bgG, m_byte bgB) const;

    private:
    /// Evaluates the whole sprite layer for one scanline into spriteLine_. Walks the SAT link chain a single
    /// time (instead of re-scanning all 80 sprites per pixel), applying masking, the per-line limit / SOVR,
    /// and sprite-sprite collision (SCOL). The topmost (first in chain order) opaque sprite wins each pixel.
    void buildSpriteLine(int line);

    VDPState    &state_;
    VDPTile     &tile_;
    Framebuffer &fb_;

    /// Sprite layer for the scanline currently being rendered, filled by buildSpriteLine() and read by the
    /// per-pixel composite loop. Transparent (opaque=false) where no sprite covers the pixel.
    PixelResult spriteLine_[VDPState::SCREEN_W];
};