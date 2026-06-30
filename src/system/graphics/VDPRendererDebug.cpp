/**
 * @file VDPRendererDebug.cpp
 * @brief Debug PNG export functions for VDPRenderer.
 */

#include "VDPRendererDebug.hpp"
#include <array>
#include <iomanip>
#include <sstream>

VDPRendererDebug::VDPRendererDebug(VDPState &state, VDPTile &tile, Framebuffer &fb)
    : state_(state), tile_(tile), fb_(fb) {
}

// ── Helper implementations ────────────────────────────────────────────────────

uint8_t VDPRendererDebug::expand3to8(uint8_t val) {
    static const uint8_t lut[8] = {0, 36, 73, 109, 146, 182, 219, 255};
    return lut[val & 0x07];
}

void VDPRendererDebug::setImagePixel(Image &img, int x, int y, m_byte b, m_byte g, m_byte r) const {
    ImageSize size = img.getSize();
    if (x < 0 || x >= size.width || y < 0 || y >= size.height)
        return;
    uint8_t *buf = static_cast<uint8_t *>(img.getRawBuffer());
    int      idx = (y * size.width + x) * 3;
    buf[idx]     = r; // Image buffer is RGB
    buf[idx + 1] = g;
    buf[idx + 2] = b;
}

Image VDPRendererDebug::renderPaletteRow(int paletteIdx, bool fullRange) const {
    const int colorH = 16;
    const int colorW = 16;
    Color     black  = {0, 0, 0, 255};

    Image colors;
    for (int c = 0; c < 16; ++c) {
        m_byte r8, g8, b8;
        if (fullRange)
            tile_.cramToRGB_FullRange(static_cast<m_byte>(paletteIdx), static_cast<m_byte>(c), r8, g8, b8);
        else
            tile_.cramToRGB(static_cast<m_byte>(paletteIdx), static_cast<m_byte>(c), r8, g8, b8);

        colors.addOnRight(Image(ImageSize{colorW, colorH}, Color{r8, g8, b8, 255}), 0, black);
    }

    std::ostringstream label;
    label << "P" << paletteIdx;
    return colors.addLabelOnBottom(label.str(), 0, black, Color{255, 255, 0, 255});
}

Image VDPRendererDebug::renderPlaneLayer(int planeBase, bool fullRange) const {
    Color black = {0, 0, 0, 255};

    Image result(ImageSize{320, 224}, black);

    int pw = state_.planeWidthCells();
    int ph = state_.planeHeightCells();

    int nonZero = 0;
    for (int i = 0; i < pw * ph; ++i) {
        int    ea = (planeBase + i * 2) & 0xFFFF;
        m_word e  = static_cast<m_word>((state_.vram_[ea] << 8) | state_.vram_[ea + 1]);
        if (e != 0)
            nonZero++;
    }

    for (int y = 0; y < VDPState::SCREEN_H; ++y) {
        for (int x = 0; x < VDPState::SCREEN_W; ++x) {
            int planeX = x % (pw * 8);
            int planeY = y % (ph * 8);

            int cellX        = planeX / 8;
            int cellY        = planeY / 8;
            int pixelInTileX = planeX % 8;
            int pixelInTileY = planeY % 8;

            int    entryAddr = (planeBase + (cellY * pw + cellX) * 2) & 0xFFFF;
            m_word entry     = static_cast<m_word>((state_.vram_[entryAddr] << 8) | state_.vram_[entryAddr + 1]);

            m_byte palette   = static_cast<m_byte>((entry >> 13) & 0x03);
            bool   vflip     = (entry & 0x1000) != 0;
            bool   hflip     = (entry & 0x0800) != 0;
            int    tileIndex = entry & 0x07FF;

            m_byte colorIdx = tile_.getTilePixel(tileIndex * 32, pixelInTileX, pixelInTileY, hflip, vflip);

            if (colorIdx != 0) {
                m_byte r8, g8, b8;
                if (fullRange)
                    tile_.cramToRGB_FullRange(palette, colorIdx, r8, g8, b8);
                else
                    tile_.cramToRGB(palette, colorIdx, r8, g8, b8);
                setImagePixel(result, x, y, b8, g8, r8);
            }
        }
    }

    Image info = Image("$" + std::to_string(planeBase), black, Color{255, 255, 0, 255});
    info.addOnRight(Image(std::to_string(pw) + "x" + std::to_string(ph), black, Color{200, 200, 200, 255}), 4, black);
    info.addOnRight(Image(std::to_string(nonZero) + " tiles", black, Color{0, 200, 255, 255}), 4, black);
    result.addOnTop(info, 0, black);

    return result;
}

Image VDPRendererDebug::renderSpriteLayer(bool fullRange) const {
    Color     black = {0, 0, 0, 255};
    Color     white = {200, 200, 200, 255};
    Color     red   = {180, 0, 0, 255};
    const int gap   = 8;

    Image result = Image("#", black, white);
    result.addOnRight(Image("Preview", black, white), gap, black);
    result.addOnRight(Image("X", black, white), gap, black);
    result.addOnRight(Image("Y", black, white), gap, black);
    result.addOnRight(Image("Sz", black, white), gap, black);
    result.addOnRight(Image("Tile", black, white), gap, black);
    result.addOnRight(Image("Link", black, white), gap, black);

    int                                         base          = state_.satBase();
    int                                         spriteIdx     = 0;
    bool                                        masked        = false;
    bool                                        sawNonZeroX   = false;
    int                                         spritesOnLine = 0;
    std::array<bool, VDPState::SAT_MAX_SPRITES> visited{};

    for (int row = 0; row < 20; ++row) {
        if (spriteIdx >= VDPState::SAT_MAX_SPRITES)
            break;
        if (visited[static_cast<size_t>(spriteIdx)])
            break;
        visited[static_cast<size_t>(spriteIdx)] = true;

        int satAddr = base + spriteIdx * 8;
        if (satAddr + 7 >= VDPState::VRAM_SIZE)
            break;

        int satShadow = spriteIdx * 8;

        int yRaw     = ((state_.sat_[satShadow] & 0x03) << 8) | state_.sat_[satShadow + 1];
        int link     = state_.sat_[satShadow + 3] & 0x7F;
        int sizeCode = state_.sat_[satShadow + 2];
        int sizeW    = ((sizeCode >> 2) & 0x03) + 1;
        int sizeH    = (sizeCode & 0x03) + 1;

        m_word tileWord = static_cast<m_word>((state_.vram_[satAddr + 4] << 8) | state_.vram_[satAddr + 5]);
        int    xRaw     = ((state_.vram_[satAddr + 6] & 0x01) << 8) | state_.vram_[satAddr + 7];

        int spriteX = xRaw - 128;
        int spriteY = yRaw - 128;

        if (xRaw != 0)
            sawNonZeroX = true;
        else if (sawNonZeroX)
            masked = true;

        if (!masked)
            spritesOnLine++;
        if (spritesOnLine > 20)
            masked = true;

        char buf[32];

        Image preview = Image(ImageSize{32, 32}, black);

        if (!masked) {
            m_byte palette  = static_cast<m_byte>((tileWord >> 13) & 0x03);
            int    baseTile = tileWord & 0x07FF;

            int padX = (32 - sizeW * 8) / 2;
            int padY = (32 - sizeH * 8) / 2;

            Image    spriteImg = Image(ImageSize{sizeW * 8, sizeH * 8}, black);
            uint8_t *spriteBuf = static_cast<uint8_t *>(spriteImg.getRawBuffer());

            for (int ty = 0; ty < sizeH; ++ty) {
                for (int tx = 0; tx < sizeW; ++tx) {
                    int tileIdx = baseTile + tx * sizeH + ty;
                    for (int py = 0; py < 8; ++py) {
                        for (int px = 0; px < 8; ++px) {
                            m_byte colorIdx = tile_.getTilePixel(tileIdx * 32, px, py, false, false);
                            if (colorIdx != 0) {
                                m_byte r8, g8, b8;
                                if (fullRange)
                                    tile_.cramToRGB_FullRange(palette, colorIdx, r8, g8, b8);
                                else
                                    tile_.cramToRGB(palette, colorIdx, r8, g8, b8);
                                int destX          = tx * 8 + px;
                                int destY          = ty * 8 + py;
                                int idx            = (destY * sizeW * 8 + destX) * 3;
                                spriteBuf[idx]     = r8; // Image buffer is RGB
                                spriteBuf[idx + 1] = g8;
                                spriteBuf[idx + 2] = b8;
                            }
                        }
                    }
                }
            }

            Image centered = spriteImg;

            if (padX > 0) {
                Image leftPad  = Image(ImageSize{padX, sizeH * 8}, black);
                Image rightPad = Image(ImageSize{padX, sizeH * 8}, black);
                centered.addOnLeft(leftPad, 0, black);
                centered.addOnRight(rightPad, 0, black);
            }

            if (padY > 0) {
                Image topPad    = Image(ImageSize{32, padY}, black);
                Image bottomPad = Image(ImageSize{32, padY}, black);
                centered.addOnTop(topPad, 0, black);
                centered.addOnBottom(bottomPad, 0, black);
            }

            ImageSize sz = centered.getSize();
            if (sz.width > 32 || sz.height > 32) {
                Image    cropped = Image(ImageSize{32, 32}, black);
                uint8_t *src     = static_cast<uint8_t *>(centered.getRawBuffer());
                uint8_t *dst     = static_cast<uint8_t *>(cropped.getRawBuffer());
                for (int y = 0; y < 32; ++y) {
                    for (int x = 0; x < 32; ++x) {
                        int si      = (y * sz.width + x) * 3;
                        int di      = (y * 32 + x) * 3;
                        dst[di]     = src[si];
                        dst[di + 1] = src[si + 1];
                        dst[di + 2] = src[si + 2];
                    }
                }
                centered = cropped;
            }

            preview = centered;
        }

        snprintf(buf, sizeof(buf), "%d", spriteIdx);
        Image col0 = Image(buf, black, white);

        snprintf(buf, sizeof(buf), "%d", spriteX);
        Image col1 = Image(buf, black, masked ? red : white);

        snprintf(buf, sizeof(buf), "%d", spriteY);
        Image col2 = Image(buf, black, white);

        snprintf(buf, sizeof(buf), "%dx%d", sizeW, sizeH);
        Image col3 = Image(buf, black, white);

        snprintf(buf, sizeof(buf), "$%X", tileWord & 0x07FF);
        Image col4 = Image(buf, black, white);

        snprintf(buf, sizeof(buf), "%d", link);
        Image col5 = Image(buf, black, white);

        Image rowImg = col0;
        rowImg.addOnRight(preview, gap, black);
        rowImg.addOnRight(col1, gap, black);
        rowImg.addOnRight(col2, gap, black);
        rowImg.addOnRight(col3, gap, black);
        rowImg.addOnRight(col4, gap, black);
        rowImg.addOnRight(col5, gap, black);

        result.addOnBottom(rowImg, gap, black);

        if (link == 0 || link >= VDPState::SAT_MAX_SPRITES)
            break;
        spriteIdx = link;
    }

    return result;
}

Image VDPRendererDebug::renderWindowLayer(bool fullRange) const {
    Image result(ImageSize{320, 224}, Color{0, 0, 0, 255});

    int wBase  = state_.windowBase();
    int wWidth = 64;

    for (int y = 0; y < VDPState::SCREEN_H; ++y) {
        for (int x = 0; x < VDPState::SCREEN_W; ++x) {
            int cellX = x / 8;
            int cellY = y / 8;

            int  hpos   = state_.windowHPos() * 2;
            int  vpos   = state_.windowVPos();
            bool active = false;

            if (vpos > 0) {
                if (state_.windowDown()) {
                    if (cellY >= vpos)
                        active = true;
                } else {
                    if (cellY < vpos)
                        active = true;
                }
            }

            if (hpos > 0 && !active) {
                if (state_.windowRight()) {
                    if (cellX >= hpos)
                        active = true;
                } else {
                    if (cellX < hpos)
                        active = true;
                }
            }

            if (active) {
                int pixelInTileX = x % 8;
                int pixelInTileY = y % 8;

                int    entryAddr = (wBase + (cellY * wWidth + cellX) * 2) & 0xFFFF;
                m_word entry     = static_cast<m_word>((state_.vram_[entryAddr] << 8) | state_.vram_[entryAddr + 1]);

                m_byte palette   = static_cast<m_byte>((entry >> 13) & 0x03);
                bool   vflip     = (entry & 0x1000) != 0;
                bool   hflip     = (entry & 0x0800) != 0;
                int    tileIndex = entry & 0x07FF;

                m_byte colorIdx = tile_.getTilePixel(tileIndex * 32, pixelInTileX, pixelInTileY, hflip, vflip);

                if (colorIdx != 0) {
                    m_byte r8, g8, b8;
                    if (fullRange)
                        tile_.cramToRGB_FullRange(palette, colorIdx, r8, g8, b8);
                    else
                        tile_.cramToRGB(palette, colorIdx, r8, g8, b8);
                    setImagePixel(result, x, y, b8, g8, r8);
                }
            }
        }
    }

    return result;
}

// ── Public debug image methods ────────────────────────────────────────────────

Image VDPRendererDebug::makeFinalOutputImage(bool fullRange) const {
    Image result(ImageSize{320, 224}, Color{0, 0, 0, 255});

    const m_byte *fbData = static_cast<const m_byte *>(fb_.getRawPointer());
    for (int y = 0; y < VDPState::SCREEN_H; ++y) {
        for (int x = 0; x < VDPState::SCREEN_W; ++x) {
            int    fbIdx = (y * Framebuffer::PITCH + x * 3);
            m_byte b     = fbData[fbIdx];
            m_byte g     = fbData[fbIdx + 1];
            m_byte r     = fbData[fbIdx + 2];
            if (fullRange) {
                r = expand3to8(r);
                g = expand3to8(g);
                b = expand3to8(b);
            }
            setImagePixel(result, x, y, b, g, r);
        }
    }

    return result;
}

Image VDPRendererDebug::makePalletesTable(bool fullRange) const {
    Color black = {0, 0, 0, 255};

    Image rows[4];
    for (int p = 0; p < 4; ++p)
        rows[p] = renderPaletteRow(p, fullRange);

    Image result = rows[0];
    result.addOnBottom(rows[1], 2, black);
    result.addOnBottom(rows[2], 2, black);
    result.addOnBottom(rows[3], 2, black);
    return result;
}

Image VDPRendererDebug::makeVSRAMImage() const {
    Color     black    = {0, 0, 0, 255};
    Color     fg       = {200, 200, 200, 255};
    const int colCount = 10;
    const int rowCount = 4;
    const int gap      = 1;

    Image result;
    for (int row = 0; row < rowCount; ++row) {
        Image rowImg;
        for (int col = 0; col < colCount; ++col) {
            int                idx = row * colCount + col;
            std::ostringstream oss;
            oss << std::hex << std::uppercase << std::setfill('0') << std::setw(4) << state_.vsram_[idx];
            rowImg.addOnRight(Image(oss.str(), black, fg), gap, black);
        }
        result.addOnBottom(rowImg, gap, black);
    }
    return result;
}

Image VDPRendererDebug::makeWindowLayerImage(bool fullRange) const {
    return renderWindowLayer(fullRange);
}

Image VDPRendererDebug::makeSpriteTablesImage(bool fullRange) const {
    return renderSpriteLayer(fullRange);
}

Image VDPRendererDebug::makeBackgroundLayerImage(bool fullRange) const {
    return renderPlaneLayer(state_.planeBBase(), fullRange);
}

Image VDPRendererDebug::makeForegroundLayerImage(bool fullRange) const {
    return renderPlaneLayer(state_.planeABase(), fullRange);
}

Image VDPRendererDebug::makeVramTilesImage(bool /*fullRange*/) const {
    static const Color palette[16] = {
        {20, 20, 20, 255},    // 0: cinzento muito escuro (transparente)
        {255, 50, 50, 255},   // 1: vermelho
        {255, 140, 0, 255},   // 2: laranja
        {255, 255, 0, 255},   // 3: amarelo
        {0, 200, 50, 255},    // 4: verde
        {0, 255, 200, 255},   // 5: verde-água
        {0, 180, 255, 255},   // 6: azul-céu
        {0, 50, 255, 255},    // 7: azul
        {150, 0, 255, 255},   // 8: roxo
        {255, 0, 200, 255},   // 9: magenta
        {255, 100, 150, 255}, // 10: rosa
        {200, 255, 0, 255},   // 11: lima
        {0, 255, 100, 255},   // 12: menta
        {255, 200, 0, 255},   // 13: âmbar
        {100, 200, 255, 255}, // 14: azul-claro
        {255, 80, 0, 255},    // 15: laranja-avermelhado
    };

    // Show the WHOLE VRAM as a tile sheet (64 KB / 32 bytes = 2048 tiles), not
    // just the first 128. A 32-wide grid of 64 rows covers every tile so the
    // city/character art at higher addresses is visible, not only the font that
    // lives near address 0.
    const int tilesX   = 32;
    const int tilesY   = VDPState::VRAM_SIZE / 32 / 32; // 2048 tiles / 32 cols = 64 rows
    const int tileSize = 8;

    Color black = {0, 0, 0, 255};
    Image result(ImageSize{tilesX * tileSize, tilesY * tileSize}, black);

    for (int ty = 0; ty < tilesY; ++ty) {
        for (int tx = 0; tx < tilesX; ++tx) {
            int tileAddr = (ty * tilesX + tx) * 32;
            for (int py = 0; py < tileSize; ++py) {
                for (int px = 0; px < tileSize; ++px) {
                    m_byte colorIdx = tile_.getTilePixel(tileAddr, px, py, false, false);
                    Color  c        = palette[colorIdx & 0x0F];
                    setImagePixel(result, tx * tileSize + px, ty * tileSize + py, c.b, c.g, c.r);
                }
            }
        }
    }

    return result;
}

Image VDPRendererDebug::makeRegistersImage() const {
    Color     black = {0, 0, 0, 255};
    Color     white = {200, 200, 200, 255};
    Color     cyan  = {0, 200, 200, 255};
    const int gap   = 1;

    struct RegInfo {
        const char *name;
        int         idx;
    };
    static const RegInfo regs[] = {
        {"Mode Set 1", 0},
        {"Mode Set 2", 1},
        {"Plane A", 2},
        {"Window", 3},
        {"Plane B", 4},
        {"Sprite Attr", 5},
        {"BG Color", 7},
        {"Reset", 10},
        {"Scroll A H", 0x0B},
        {"Scroll B H", 0x0C},
        {"Scroll H", 0x0D},
        {"Scroll V", 0x0E},
        {"Auto Inc", 0x0F},
        {"Plane Sz", 0x10},
        {"Window H", 0x11},
        {"Window V", 0x12},
    };

    auto padRight = [](std::string s, int len) -> std::string {
        while ((int)s.size() < len)
            s += ' ';
        return s;
    };

    Image header = Image(padRight("Reg", 5), black, white);
    header.addOnRight(Image(padRight("Name", 15), black, white), gap, black);
    header.addOnRight(Image(padRight("Val", 4), black, white), gap, black);

    Image result = header;
    for (int row = 0; row < VDPState::REG_COUNT; ++row) {
        std::ostringstream addrStr;
        addrStr << "$" << std::hex << std::uppercase << std::setfill('0') << std::setw(2) << row;

        const char *name = "";
        for (auto &r : regs)
            if (r.idx == row) {
                name = r.name;
                break;
            }

        std::ostringstream valStr;
        valStr << std::hex << std::uppercase << std::setfill('0') << std::setw(2) << int(state_.regs_[row]);

        Image rowImg = Image(padRight(addrStr.str(), 5), black, cyan);
        rowImg.addOnRight(Image(padRight(name, 15), black, white), gap, black);
        rowImg.addOnRight(Image(padRight(valStr.str(), 4), black, cyan), gap, black);
        result.addOnBottom(rowImg, gap, black);
    }
    return result;
}

// ── PNG export ────────────────────────────────────────────────────────────────

void VDPRendererDebug::dumpFrameBufferToPNG(const std::string &path, bool fullRange) const {
    makeFinalOutputImage(fullRange).printToPNG(path);
}

void VDPRendererDebug::dumpEverythingToPNG(const std::string &path, bool fullRange) const {
    Color black = {0, 0, 0, 255};
    Color green = {0, 255, 0, 255};

    Image finalOutput     = makeFinalOutputImage(fullRange);
    Image colorRAM        = makePalletesTable(fullRange);
    Image vsRAM           = makeVSRAMImage();
    Image vramTiles       = makeVramTilesImage(fullRange);
    Image registers       = makeRegistersImage();
    Image backgroundLayer = makeBackgroundLayerImage(fullRange);
    Image foregroundLayer = makeForegroundLayerImage(fullRange);
    Image windowLayer     = makeWindowLayerImage(fullRange);
    Image spriteTables    = makeSpriteTablesImage(fullRange);

    finalOutput.addLabelOnTop("FinalOutput", 2, black, green);
    vramTiles.addLabelOnTop("VRAM Tiles", 2, black, green);
    colorRAM.addLabelOnTop("CRAM Palettes", 2, black, green);
    vsRAM.addLabelOnTop("VSRAM", 2, black, green);
    registers.addLabelOnTop("Registers", 2, black, green);
    backgroundLayer.addLabelOnTop("Plane B", 2, black, green);
    foregroundLayer.addLabelOnTop("Plane A", 2, black, green);
    windowLayer.addLabelOnTop("Window", 2, black, green);
    spriteTables.addLabelOnTop("SAT Sprites", 2, black, green);

    Image col0 = registers;

    Image col1 = finalOutput;
    col1.addOnBottom(colorRAM, 2, black);
    col1.addOnBottom(vsRAM, 2, black);

    Image col2 = vramTiles;

    backgroundLayer.addOnRight(foregroundLayer, 2, black);
    Image col3 = backgroundLayer;
    col3.addOnBottom(windowLayer, 2, black);

    Image col4 = spriteTables;

    Image all = col0;
    all.addOnRight(col1, 2, black);
    all.addOnRight(col2, 2, black);
    all.addOnRight(col3, 2, black);
    all.addOnRight(col4, 2, black);

    all.printToPNG(path);
}
