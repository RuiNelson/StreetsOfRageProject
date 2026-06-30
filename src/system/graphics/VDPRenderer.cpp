/**
 * @file VDPRenderer.cpp
 * @brief VDP scanline renderer implementation.
 */

#include "VDPRenderer.hpp"
#include <algorithm>

/// Initializes renderer with references to VDP state, tile decoder, and framebuffer.
VDPRenderer::VDPRenderer(VDPState &state, VDPTile &tile, Framebuffer &fb) : state_(state), tile_(tile), fb_(fb) {
}

/// Renders full 224-scanline frame if display is enabled; otherwise clears framebuffer to black.
void VDPRenderer::renderFrame() {
    if (!state_.displayEnabled()) {
        fb_.clear();
        return;
    }

    for (int line = 0; line < VDPState::SCREEN_H; ++line) {
        state_.vCounter_ = static_cast<m_word>(line);
        renderScanline(line);
    }
}

/// Renders a single scanline (Y-coordinate): evaluates each pixel's plane B, plane A/window, and sprite layers, then
/// composites them using priority rules.
void VDPRenderer::renderScanline(int line) {
    VDPState &s      = state_;
    int       hsBase = s.hscrollBase();

    // ── Read HScroll values ─────────────────────────────────────────────
    int hscrollA = 0, hscrollB = 0;
    switch (s.hscrollMode()) {
        case 0: {
            int addr = hsBase;
            hscrollA = static_cast<int16_t>((s.vram_[addr] << 8) | s.vram_[addr + 1]);
            hscrollB = static_cast<int16_t>((s.vram_[addr + 2] << 8) | s.vram_[addr + 3]);
            break;
        }
        case 2: {
            int row  = (line / 8) * 8;
            int addr = (hsBase + row * 4) & 0xFFFF;
            hscrollA = static_cast<int16_t>((s.vram_[addr] << 8) | s.vram_[addr + 1]);
            hscrollB = static_cast<int16_t>((s.vram_[addr + 2] << 8) | s.vram_[addr + 3]);
            break;
        }
        case 3: {
            int addr = (hsBase + line * 4) & 0xFFFF;
            hscrollA = static_cast<int16_t>((s.vram_[addr] << 8) | s.vram_[addr + 1]);
            hscrollB = static_cast<int16_t>((s.vram_[addr + 2] << 8) | s.vram_[addr + 3]);
            break;
        }
        default:
            break;
    }

    bool twoCell  = s.vscrollMode() == 1;
    int  vscrollA = static_cast<int16_t>(s.vsram_[0]);
    int  vscrollB = static_cast<int16_t>(s.vsram_[1]);

    int planeAAddr = s.planeABase();
    int planeBAddr = s.planeBBase();

    // ── Background colour ────────────────────────────────────────────────
    m_byte bgR, bgG, bgB;
    tile_.cramToRGB(static_cast<m_byte>(s.bgColorPalette()), static_cast<m_byte>(s.bgColorIndex()), bgR, bgG, bgB);

    // ── Sprite layer (evaluated once for the whole scanline) ─────────────
    buildSpriteLine(line);

    // ── Per-pixel evaluation ─────────────────────────────────────────────
    for (int x = 0; x < VDPState::SCREEN_W; ++x) {
        int cellX = x / 8;
        int cellY = line / 8;

        int vsA = vscrollA;
        int vsB = vscrollB;
        if (twoCell) {
            int col = x / 16;
            int idx = col * 2;
            if (idx + 1 < VDPState::VSRAM_ENTRIES) {
                vsA = static_cast<int16_t>(s.vsram_[idx]);
                vsB = static_cast<int16_t>(s.vsram_[idx + 1]);
            }
        }

        PixelResult planeBPx = getPlanePixel(planeBAddr, hscrollB, vsB, x, line);

        PixelResult planeAPx;
        if (isWindowActive(cellX, cellY)) {
            planeAPx = getWindowPixel(x, line);
        } else {
            planeAPx = getPlanePixel(planeAAddr, hscrollA, vsA, x, line);
        }

        PixelResult spritePx = spriteLine_[x];

        CompositeResult cr = resolvePixel(planeBPx, planeAPx, spritePx, bgR, bgG, bgB);

        if (cr.valid) {
            fb_.setPixel(x, line, cr.b, cr.g, cr.r);
        } else {
            fb_.setPixel(x, line, bgB, bgG, bgR);
        }
    }
}

// ── Layer evaluation ────────────────────────────────────────────────────────

/// Checks if window plane is active at cell coordinates (cellX, cellY) based on window position and direction settings.
bool VDPRenderer::isWindowActive(int cellX, int cellY) const {
    const VDPState &s    = state_;
    int             hpos = s.windowHPos() * 2;
    int             vpos = s.windowVPos();

    if (vpos > 0) {
        if (s.windowDown()) {
            if (cellY >= vpos)
                return true;
        } else {
            if (cellY < vpos)
                return true;
        }
    }

    if (hpos > 0) {
        if (s.windowRight()) {
            return cellX >= hpos;
        } else {
            return cellX < hpos;
        }
    }

    return false;
}

/// Evaluates plane pixel at screen coordinates (screenX, screenY) with given scroll offsets.
/// Applies wrapping based on plane dimensions. Decodes nametable entry and looks up tile pixel.
VDPRenderer::PixelResult
VDPRenderer::getPlanePixel(int planeBase, int hscroll, int vscroll, int screenX, int screenY) const {
    const VDPState &s  = state_;
    int             pw = s.planeWidthCells();
    int             ph = s.planeHeightCells();

    int planeX = (screenX - hscroll) % (pw * 8);
    if (planeX < 0)
        planeX += pw * 8;

    int planeY = (screenY + vscroll) % (ph * 8);
    if (planeY < 0)
        planeY += ph * 8;

    int cellX        = planeX / 8;
    int cellY        = planeY / 8;
    int pixelInTileX = planeX % 8;
    int pixelInTileY = planeY % 8;

    int    entryAddr = (planeBase + (cellY * pw + cellX) * 2) & 0xFFFF;
    m_word entry     = static_cast<m_word>((s.vram_[entryAddr] << 8) | s.vram_[entryAddr + 1]);

    bool   priority  = (entry & 0x8000) != 0;
    m_byte palette   = static_cast<m_byte>((entry >> 13) & 0x03);
    bool   vflip     = (entry & 0x1000) != 0;
    bool   hflip     = (entry & 0x0800) != 0;
    int    tileIndex = entry & 0x07FF;

    m_byte colorIdx = tile_.getTilePixel(tileIndex * 32, pixelInTileX, pixelInTileY, hflip, vflip);

    return {colorIdx, palette, priority, colorIdx != 0};
}

/// Evaluates window plane pixel at screen coordinates (screenX, screenY). Window nametable is 64×32 in H40 mode.
VDPRenderer::PixelResult VDPRenderer::getWindowPixel(int screenX, int screenY) const {
    const VDPState &s      = state_;
    int             wBase  = s.windowBase();
    int             wWidth = 64; // Window nametable width in H40 mode

    int cellX        = screenX / 8;
    int cellY        = screenY / 8;
    int pixelInTileX = screenX % 8;
    int pixelInTileY = screenY % 8;

    int    entryAddr = (wBase + (cellY * wWidth + cellX) * 2) & 0xFFFF;
    m_word entry     = static_cast<m_word>((s.vram_[entryAddr] << 8) | s.vram_[entryAddr + 1]);

    bool   priority  = (entry & 0x8000) != 0;
    m_byte palette   = static_cast<m_byte>((entry >> 13) & 0x03);
    bool   vflip     = (entry & 0x1000) != 0;
    bool   hflip     = (entry & 0x0800) != 0;
    int    tileIndex = entry & 0x07FF;

    m_byte colorIdx = tile_.getTilePixel(tileIndex * 32, pixelInTileX, pixelInTileY, hflip, vflip);

    return {colorIdx, palette, priority, colorIdx != 0};
}

/// Evaluates topmost non-transparent sprite pixel at screen coordinates (screenX, screenY) by scanning SAT.
/// Sprite pixel lookup. Returns first opaque pixel found.
/// Also detects sprite-sprite collisions: when a second sprite's opaque pixel lands on the same screen
/// position as a prior opaque pixel, sets the SCOL flag (status bit 5). Once SCOL is already set for the
/// frame, reverts to early-return semantics to keep rendering cost identical to a no-collision scan.
VDPRenderer::PixelResult VDPRenderer::getSpritePixel(int screenX, int screenY) {
    VDPState            &s                    = state_;
    static constexpr int HW_SPRITES_PER_LINE  = 20;   // hardware limit (H40); SOVR set when exceeded
    static constexpr int MAX_SPRITES_PER_LINE = 1000; // extended render limit (not hardware-accurate)

    int         base          = s.satBase();
    int         spriteIdx     = 0;
    int         spritesOnLine = 0;
    bool        masked        = false;
    bool        sawNonZeroX   = false;
    PixelResult result        = {0, 0, false, false};

    for (int count = 0; count < VDPState::SAT_MAX_SPRITES; ++count) {
        int satAddr   = base + spriteIdx * 8;
        int satShadow = spriteIdx * 8; // offset into sat_[] shadow
        if (satAddr + 7 >= VDPState::VRAM_SIZE)
            break;

        // Y, size, link read from shadow (frozen at last VRAM write — immune to mid-frame SAT changes).
        // SAT word 1 is size in the high byte and link in the low byte.
        int yRaw  = ((s.sat_[satShadow] & 0x03) << 8) | s.sat_[satShadow + 1];
        int link  = s.sat_[satShadow + 3] & 0x7F;
        int sizeW = ((s.sat_[satShadow + 2] >> 2) & 0x03) + 1;
        int sizeH = (s.sat_[satShadow + 2] & 0x03) + 1;

        // Tile word and X position read live from VRAM (matches GPX behaviour)
        m_word tileWord = static_cast<m_word>((s.vram_[satAddr + 4] << 8) | s.vram_[satAddr + 5]);

        int xRaw = ((s.vram_[satAddr + 6] & 0x01) << 8) | s.vram_[satAddr + 7];

        int spriteX      = xRaw - 128;
        int spriteY      = yRaw - 128;
        int spritePixelW = sizeW * 8;
        int spritePixelH = sizeH * 8;

        bool onScanline = (screenY >= spriteY && screenY < spriteY + spritePixelH);

        if (onScanline) {
            // Sprite masking: a sprite at X=0 only hides subsequent ones once a prior
            // on-scanline sprite has had nonzero X (matches hardware/GPGX behaviour;
            // unused sprites parked at X=0 at the head of the chain must not mask).
            if (xRaw != 0)
                sawNonZeroX = true;
            else if (sawNonZeroX)
                masked = true;

            if (!masked) {
                spritesOnLine++;
                if (spritesOnLine == HW_SPRITES_PER_LINE + 1)
                    s.status_ |= 0x40; // SOVR
                if (spritesOnLine > MAX_SPRITES_PER_LINE)
                    break;

                if (screenX >= spriteX && screenX < spriteX + spritePixelW) {
                    bool   priority = (tileWord & 0x8000) != 0;
                    m_byte palette  = static_cast<m_byte>((tileWord >> 13) & 0x03);
                    bool   vflip    = (tileWord & 0x1000) != 0;
                    bool   hflip    = (tileWord & 0x0800) != 0;
                    int    baseTile = tileWord & 0x07FF;

                    int px = screenX - spriteX;
                    int py = screenY - spriteY;
                    if (hflip)
                        px = spritePixelW - 1 - px;
                    if (vflip)
                        py = spritePixelH - 1 - py;

                    int tileCol = px / 8;
                    int tileRow = py / 8;
                    int tileIdx = baseTile + tileCol * sizeH + tileRow;

                    int pixInTileX = px % 8;
                    int pixInTileY = py % 8;

                    m_byte colorIdx = tile_.getTilePixel(tileIdx * 32, pixInTileX, pixInTileY, false, false);

                    if (colorIdx != 0) {
                        if (!result.opaque) {
                            result = {colorIdx, palette, priority, true};
                            if (s.status_ & 0x0020) {
                                return result;
                            }
                        } else {
                            s.status_ |= 0x0020;
                            return result;
                        }
                    }
                }
            }
        }

        // link is a 7-bit field (0-127) but sat_[] shadow only holds SAT_MAX_SPRITES (80) entries; a link
        // beyond that range must stop the chain, otherwise satShadow indexes past sat_[] into unrelated
        // VDPState fields (matches GPGX, which breaks when link is out of range).
        if (link == 0 || link >= VDPState::SAT_MAX_SPRITES)
            break;
        spriteIdx = link;
    }

    return result;
}

/// Evaluates the sprite layer for one scanline into spriteLine_. This replaces the per-pixel getSpritePixel()
/// scan: the SAT link chain is walked a single time per line (O(sprites + width) instead of O(width × sprites)).
/// Masking, the per-line sprite limit / SOVR, topmost-wins ordering, and sprite-sprite collision (SCOL) are
/// preserved exactly — for each sprite the row is fixed, so only the horizontal span is iterated, and the first
/// opaque sprite in chain order claims each pixel (a later opaque pixel landing on a taken slot sets SCOL).
void VDPRenderer::buildSpriteLine(int line) {
    VDPState            &s                    = state_;
    static constexpr int HW_SPRITES_PER_LINE  = 20;   // hardware limit (H40); SOVR set when exceeded
    static constexpr int MAX_SPRITES_PER_LINE = 1000; // extended render limit (not hardware-accurate)

    for (int x = 0; x < VDPState::SCREEN_W; ++x)
        spriteLine_[x] = {0, 0, false, false};

    int  base          = s.satBase();
    int  spriteIdx     = 0;
    int  spritesOnLine = 0;
    bool masked        = false;
    bool sawNonZeroX   = false;

    for (int count = 0; count < VDPState::SAT_MAX_SPRITES; ++count) {
        int satAddr   = base + spriteIdx * 8;
        int satShadow = spriteIdx * 8; // offset into sat_[] shadow
        if (satAddr + 7 >= VDPState::VRAM_SIZE)
            break;

        // Y, size, link read from shadow (frozen at last VRAM write — immune to mid-frame SAT changes).
        // SAT word 1 is size in the high byte and link in the low byte.
        int yRaw  = ((s.sat_[satShadow] & 0x03) << 8) | s.sat_[satShadow + 1];
        int link  = s.sat_[satShadow + 3] & 0x7F;
        int sizeW = ((s.sat_[satShadow + 2] >> 2) & 0x03) + 1;
        int sizeH = (s.sat_[satShadow + 2] & 0x03) + 1;

        // Tile word and X position read live from VRAM (matches GPX behaviour)
        m_word tileWord = static_cast<m_word>((s.vram_[satAddr + 4] << 8) | s.vram_[satAddr + 5]);
        int    xRaw     = ((s.vram_[satAddr + 6] & 0x01) << 8) | s.vram_[satAddr + 7];

        int spriteX      = xRaw - 128;
        int spriteY      = yRaw - 128;
        int spritePixelW = sizeW * 8;
        int spritePixelH = sizeH * 8;

        bool onScanline = (line >= spriteY && line < spriteY + spritePixelH);

        if (onScanline) {
            // Sprite masking: a sprite at X=0 only hides subsequent ones once a prior on-scanline sprite has
            // had nonzero X (matches hardware/GPGX behaviour; unused sprites parked at X=0 at the head of the
            // chain must not mask).
            if (xRaw != 0)
                sawNonZeroX = true;
            else if (sawNonZeroX)
                masked = true;

            if (!masked) {
                spritesOnLine++;
                if (spritesOnLine == HW_SPRITES_PER_LINE + 1)
                    s.status_ |= 0x40; // SOVR
                if (spritesOnLine > MAX_SPRITES_PER_LINE)
                    break;

                bool   priority = (tileWord & 0x8000) != 0;
                m_byte palette  = static_cast<m_byte>((tileWord >> 13) & 0x03);
                bool   vflip    = (tileWord & 0x1000) != 0;
                bool   hflip    = (tileWord & 0x0800) != 0;
                int    baseTile = tileWord & 0x07FF;

                // The row within the sprite is constant across the span — resolve it once.
                int py = line - spriteY;
                if (vflip)
                    py = spritePixelH - 1 - py;
                int tileRow    = py / 8;
                int pixInTileY = py % 8;

                // Clip the horizontal span to the visible screen so only on-screen pixels are touched.
                int xStart = spriteX < 0 ? 0 : spriteX;
                int xEnd   = spriteX + spritePixelW;
                if (xEnd > VDPState::SCREEN_W)
                    xEnd = VDPState::SCREEN_W;

                for (int screenX = xStart; screenX < xEnd; ++screenX) {
                    int px = screenX - spriteX;
                    if (hflip)
                        px = spritePixelW - 1 - px;

                    int tileCol    = px / 8;
                    int pixInTileX = px % 8;
                    int tileIdx    = baseTile + tileCol * sizeH + tileRow;

                    m_byte colorIdx = tile_.getTilePixel(tileIdx * 32, pixInTileX, pixInTileY, false, false);
                    if (colorIdx != 0) {
                        if (!spriteLine_[screenX].opaque) {
                            spriteLine_[screenX] = {colorIdx, palette, priority, true};
                        } else {
                            s.status_ |= 0x0020; // SCOL: two opaque sprite pixels overlap
                        }
                    }
                }
            }
        }

        // link is a 7-bit field (0-127) but sat_[] shadow only holds SAT_MAX_SPRITES (80) entries; a link
        // beyond that range must stop the chain, otherwise satShadow indexes past sat_[] into unrelated
        // VDPState fields (matches GPGX, which breaks when link is out of range).
        if (link == 0 || link >= VDPState::SAT_MAX_SPRITES)
            break;
        spriteIdx = link;
    }
}

// ── Compositing ─────────────────────────────────────────────────────────────

/// Composites plane B, plane A/window, and sprite pixels using priority rules. Returns final RGB color or invalid if
/// all layers transparent.
VDPRenderer::CompositeResult VDPRenderer::resolvePixel(
    PixelResult planeBPx, PixelResult planeAPx, PixelResult spritePx, m_byte bgR, m_byte bgG, m_byte bgB) const {
    CompositeResult cr{0, 0, 0, false};

    if (!planeAPx.opaque && !planeBPx.opaque && !spritePx.opaque) {
        return cr; // valid=false → use background
    }

    // Front-to-back priority resolution
    //  1. High-priority sprite
    //  2. High-priority Plane A / Window
    //  3. High-priority Plane B
    //  4. Low-priority sprite
    //  5. Low-priority Plane A / Window
    //  6. Low-priority Plane B

    if (spritePx.opaque && spritePx.priority) {
        tile_.cramToRGB(spritePx.palette, spritePx.colorIndex, cr.r, cr.g, cr.b);
        cr.valid = true;
    } else if (planeAPx.opaque && planeAPx.priority) {
        tile_.cramToRGB(planeAPx.palette, planeAPx.colorIndex, cr.r, cr.g, cr.b);
        cr.valid = true;
    } else if (planeBPx.opaque && planeBPx.priority) {
        tile_.cramToRGB(planeBPx.palette, planeBPx.colorIndex, cr.r, cr.g, cr.b);
        cr.valid = true;
    } else if (spritePx.opaque && !spritePx.priority) {
        tile_.cramToRGB(spritePx.palette, spritePx.colorIndex, cr.r, cr.g, cr.b);
        cr.valid = true;
    } else if (planeAPx.opaque && !planeAPx.priority) {
        tile_.cramToRGB(planeAPx.palette, planeAPx.colorIndex, cr.r, cr.g, cr.b);
        cr.valid = true;
    } else if (planeBPx.opaque && !planeBPx.priority) {
        tile_.cramToRGB(planeBPx.palette, planeBPx.colorIndex, cr.r, cr.g, cr.b);
        cr.valid = true;
    }

    return cr;
}
