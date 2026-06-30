/**
 * @file TestVDPSetup.cpp
 * @brief VDP test infrastructure — constructor, VBlank sync, control-port
 *        helpers, DMA, CRAM, nametable, sprite, scroll helpers, tile loading,
 *        and VDP init/clear/render utilities.
 */

#include "TestVDP.hpp"
#include "util/font/Font.hpp"
#include <SDL3/SDL.h>
#include <cmath>
#include <cstdio>

// ─── Constructor ────────────────────────────────────────────────────────────────

VDPTester::VDPTester() : MegaDriveEnvironment(VDP::VSync2, VDP::Integer) {
}

// ─── VBlank synchronisation ───────────────────────────────────────────────────

/// Runs on the run() thread (via runVDPInterrupts) — marks a fresh frame ready.
void VDPTester::vSync() {
    frameReady_ = true;
}

/** Waits for the next FRESH VBlank (discards interrupts queued mid-setup first). */
void VDPTester::waitVBlank() {
    // Drop any interrupts scheduled before now (stale inter-test / mid-setup frames).
    VDP::Interrupt discard;
    while (vdp().popInterrupt(discard)) {
    }

    // Dispatch interrupts on this thread until the next VSync arrives.
    frameReady_     = false;
    const Uint64 t0 = SDL_GetTicks();
    while (!frameReady_ && !shouldQuit() && (SDL_GetTicks() - t0) < 200) {
        runVDPInterrupts();
        if (frameReady_) {
            break;
        }
        SDL_Delay(1);
    }
}

// ─── Control-port helpers ────────────────────────────────────────────────────

void VDPTester::writeReg(uint8_t reg, uint8_t value) {
    vdp().writeControlPort(static_cast<uint16_t>(0x8000u | (reg << 8) | value));
}

void VDPTester::setAddress(uint8_t cd, uint16_t addr) {
    vdp().writeControlPort(makeWord1(cd, addr));
    vdp().writeControlPort(makeWord2(cd, addr));
}

void VDPTester::setVRAMWrite(uint16_t addr) {
    setAddress(CD_VRAM_W, addr);
}
void VDPTester::setCRAMWrite(uint16_t addr) {
    setAddress(CD_CRAM_W, addr);
}
void VDPTester::setVSRAMWrite(uint16_t addr) {
    setAddress(CD_VSRAM_W, addr);
}

void VDPTester::writeDataWord(uint16_t value) {
    vdp().writeDataPort(value);
}

// ─── DMA helpers ─────────────────────────────────────────────────────────────

/**
 * Sets up a 68k→VRAM DMA transfer and triggers it.
 * The VDP freezes the 68k bus while the transfer runs.
 *
 * @param srcAddr      Work-RAM source address (must be even; within one 128 KB bank).
 * @param dstVRAMAddr  VRAM destination address.
 * @param lengthWords  Number of 16-bit words to transfer (0 = 65536).
 */
void VDPTester::dmaFromRAM(uint32_t srcAddr, uint16_t dstVRAMAddr, uint16_t lengthWords) {
    uint32_t srcWord = srcAddr >> 1; // DMA source is word-addressed
    writeReg(0x13, static_cast<uint8_t>(lengthWords & 0xFF));
    writeReg(0x14, static_cast<uint8_t>((lengthWords >> 8) & 0xFF));
    writeReg(0x15, static_cast<uint8_t>(srcWord & 0xFF));
    writeReg(0x16, static_cast<uint8_t>((srcWord >> 8) & 0xFF));
    writeReg(0x17, static_cast<uint8_t>((srcWord >> 16) & 0x7F)); // bits 7-6 = 00 = 68k→VDP
    // Trigger: write address with CD5 set
    uint8_t cd = static_cast<uint8_t>(CD_VRAM_W | CD_DMA_BIT);
    vdp().writeControlPort(makeWord1(cd, dstVRAMAddr));
    vdp().writeControlPort(makeWord2(cd, dstVRAMAddr));
}

/**
 * Sets up a VRAM-fill DMA transfer.
 * The fill byte is written to @p lengthWords consecutive VRAM bytes.
 * Auto-increment must be 1 (set by initVDP, or adjust if needed).
 */
void VDPTester::dmaFill(uint16_t dstVRAMAddr, uint16_t lengthWords, uint8_t fillByte) {
    writeReg(0x13, static_cast<uint8_t>(lengthWords & 0xFF));
    writeReg(0x14, static_cast<uint8_t>((lengthWords >> 8) & 0xFF));
    writeReg(0x17, 0x80); // bits 7-6 = 10 = VRAM fill
    uint8_t cd = static_cast<uint8_t>(CD_VRAM_W | CD_DMA_BIT);
    vdp().writeControlPort(makeWord1(cd, dstVRAMAddr));
    vdp().writeControlPort(makeWord2(cd, dstVRAMAddr));
    // Writing to the data port triggers the fill
    writeDataWord(static_cast<uint16_t>(fillByte | (fillByte << 8)));
}

// ─── CRAM helpers ─────────────────────────────────────────────────────────────

/**
 * Loads @p count entries into the given @p palette (0–3).
 * CRAM format: 0000_BBB0_GGG0_RRR0 (3 bits per channel, bits 9/5/1).
 */
void VDPTester::loadCRAMPalette(uint8_t palette, const uint16_t *colors, int count) {
    setCRAMWrite(static_cast<uint16_t>(palette * 16 * 2)); // each entry = 2 bytes
    for (int i = 0; i < count && i < 16; ++i) {
        writeDataWord(colors[i]);
    }
}

// ─── Nametable helpers ────────────────────────────────────────────────────────

void VDPTester::writeNametableEntry(uint16_t base,
                                    int      cellX,
                                    int      cellY,
                                    int      planeWidthCells,
                                    uint16_t tileIndex,
                                    uint8_t  palette,
                                    bool     priority,
                                    bool     hflip,
                                    bool     vflip) {
    uint16_t offset = static_cast<uint16_t>((cellY * planeWidthCells + cellX) * 2);
    setVRAMWrite(static_cast<uint16_t>(base + offset));
    writeDataWord(nametableWord(tileIndex, palette, priority, hflip, vflip));
}

void VDPTester::writeText(uint16_t    nametableBase,
                          int         cellX,
                          int         cellY,
                          int         planeWidthCells,
                          const char *text,
                          uint8_t     palette,
                          bool        priority) {
    for (int i = 0; text[i]; ++i) {
        uint8_t  ch = static_cast<uint8_t>(text[i]);
        uint16_t tileIndex =
            (ch >= 0x20 && ch <= 0x7E) ? static_cast<uint16_t>(TILE_FONT_BASE + (ch - 0x20)) : TILE_BLANK;
        writeNametableEntry(
            nametableBase, cellX + i, cellY, planeWidthCells, tileIndex, palette, priority, false, false);
    }
}

// ─── Sprite helpers ───────────────────────────────────────────────────────────

/**
 * Writes one SAT entry.
 *
 * Coordinate convention: (0,0) = top-left corner of the visible display.
 *   SAT Y = y_screen + 128
 *   SAT X = x_screen + 128   (X=0 in SAT triggers sprite masking)
 *
 * @param link  Next sprite index in the display chain (0 = end of chain).
 */
void VDPTester::setSpriteEntry(int      spriteIdx,
                               int      x_screen,
                               int      y_screen,
                               uint8_t  wTiles,
                               uint8_t  hTiles,
                               uint16_t tileIndex,
                               uint8_t  palette,
                               int      link,
                               bool     priority,
                               bool     hflip,
                               bool     vflip) {
    uint16_t satAddr = static_cast<uint16_t>(VRAM_SAT + spriteIdx * 8);

    // Word 0: Y + 128 bias (9-bit value, bits 8:0)
    setVRAMWrite(satAddr);
    writeDataWord(static_cast<uint16_t>((y_screen + 128) & 0x1FF));

    // Word 1: size (high byte: WW HH in bits 3:2 and 1:0) | link (low byte)
    uint8_t sizeW = static_cast<uint8_t>((wTiles - 1) & 3);
    uint8_t sizeH = static_cast<uint8_t>((hTiles - 1) & 3);
    writeDataWord(static_cast<uint16_t>(((sizeW << 2) | sizeH) << 8 | (link & 0x7F)));

    // Word 2: tile descriptor
    writeDataWord(nametableWord(tileIndex, palette, priority, hflip, vflip));

    // Word 3: X + 128 bias (9-bit)
    writeDataWord(static_cast<uint16_t>((x_screen + 128) & 0x1FF));
}

// ─── Scroll helpers ───────────────────────────────────────────────────────────

/** Sets full-screen HScroll for both planes (reg $0B must be 0x00). */
void VDPTester::setHScrollFull(int16_t scrollA, int16_t scrollB) {
    setVRAMWrite(VRAM_HSCROLL);
    writeDataWord(static_cast<uint16_t>(scrollA));
    writeDataWord(static_cast<uint16_t>(scrollB));
}

/**
 * Writes per-scanline HScroll values (reg $0B must be 0x03).
 * Layout at HSCROLL base: for each scanline Y,
 *   offset Y*4+0 = Plane A scroll, offset Y*4+2 = Plane B scroll.
 */
void VDPTester::setHScrollPerScanline(const int16_t *scrollA, const int16_t *scrollB, int lines) {
    for (int y = 0; y < lines; ++y) {
        setVRAMWrite(static_cast<uint16_t>(VRAM_HSCROLL + y * 4));
        writeDataWord(static_cast<uint16_t>(scrollA[y]));
        writeDataWord(static_cast<uint16_t>(scrollB[y]));
    }
}

/** Sets full-screen VScroll for both planes (VSRAM words 0 and 1). */
void VDPTester::setVScrollFull(int16_t scrollA, int16_t scrollB) {
    setVSRAMWrite(0);
    writeDataWord(static_cast<uint16_t>(scrollA));
    writeDataWord(static_cast<uint16_t>(scrollB));
}

// ─── Tile loading ─────────────────────────────────────────────────────────────

/**
 * Encodes all 95 printable ASCII glyphs as VDP tiles in work RAM,
 * then DMAs them to VRAM starting at TILE_FONT_BASE.
 *
 * @param fgIdx  Palette index (0–15) for set pixels.
 * @param bgIdx  Palette index (0–15) for unset pixels (0 = transparent).
 */
void VDPTester::loadFontTiles(uint8_t fgIdx, uint8_t bgIdx) {
    static constexpr int N = 0x7E - 0x20 + 1; // 95 glyphs
    for (int i = 0; i < N; ++i) {
        Font::fontCharToVDPTile(
            memory(), static_cast<uint8_t>(0x20 + i), fgIdx, bgIdx, RAM_DMA_BUF + static_cast<uint32_t>(i * 32));
    }
    dmaFromRAM(RAM_DMA_BUF,
               static_cast<uint16_t>(TILE_FONT_BASE * 32),
               static_cast<uint16_t>(N * 16)); // 32 bytes = 16 words per tile
}

/**
 * Copies girl sprite tile data to work RAM and DMAs to VRAM.
 *
 * The girl is 6×12 tiles stored row-major in Girl::tiles[].
 * VDP sprites read tiles in COLUMN-MAJOR order within each SAT entry.
 * The girl is displayed as six 3×4 SAT entries (2 col-bands × 3 row-bands).
 * We rearrange the tiles into column-major order per 3×4 block:
 *
 *   Block (bx,by): cols [bx*3 .. bx*3+2], rows [by*4 .. by*4+3]
 *   VRAM order within block: col 0 rows 0–3, col 1 rows 0–3, col 2 rows 0–3
 *   Blocks stored sequentially: (0,0), (1,0), (0,1), (1,1), (0,2), (1,2)
 */
void VDPTester::loadGirlTiles() {
    int vramIdx = 0;
    for (int by = 0; by < 3; ++by) {
        for (int bx = 0; bx < 2; ++bx) {
            for (int c = 0; c < 3; ++c) {
                for (int r = 0; r < 4; ++r) {
                    int srcTile = (by * 4 + r) * Girl::TILE_W + (bx * 3 + c);
                    for (int b = 0; b < 32; ++b) {
                        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(vramIdx * 32 + b),
                                           Girl::tiles[srcTile][b]);
                    }
                    ++vramIdx;
                }
            }
        }
    }
    dmaFromRAM(RAM_DMA_BUF, static_cast<uint16_t>(TILE_GIRL_BASE * 32), static_cast<uint16_t>(Girl::TILE_COUNT * 16));
}

/**
 * Copies duck sprite tile data to work RAM and DMAs to VRAM.
 *
 * Rearranges from row-major (Duck::tiles) to column-major (VDP SAT order).
 * Duck is 4×4 tiles = one full SAT entry.
 */
void VDPTester::loadDuckTiles() {
    int vramIdx = 0;
    for (int c = 0; c < Duck::TILE_W; ++c) {
        for (int r = 0; r < Duck::TILE_H; ++r) {
            int srcTile = r * Duck::TILE_W + c;
            for (int b = 0; b < 32; ++b) {
                memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(vramIdx * 32 + b), Duck::tiles[srcTile][b]);
            }
            ++vramIdx;
        }
    }
    dmaFromRAM(RAM_DMA_BUF, static_cast<uint16_t>(TILE_DUCK_BASE * 32), static_cast<uint16_t>(Duck::TILE_COUNT * 16));
}

/** Copies background tile data (both halves) to VRAM via two DMA transfers. */
void VDPTester::loadBGTiles() {
    // First half (BG0)
    for (int i = 0; i < BG::HALF * 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), BG0::tiles[i / 32][i % 32]);
    }
    dmaFromRAM(RAM_DMA_BUF, static_cast<uint16_t>(TILE_BG0_BASE * 32), static_cast<uint16_t>(BG::HALF * 16));

    // Second half (BG1)
    for (int i = 0; i < (BG::TILE_COUNT - BG::HALF) * 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), BG1::tiles[i / 32][i % 32]);
    }
    dmaFromRAM(RAM_DMA_BUF,
               static_cast<uint16_t>(TILE_BG1_BASE * 32),
               static_cast<uint16_t>((BG::TILE_COUNT - BG::HALF) * 16));
}

/**
 * Copies cloud sprite tile data to work RAM and DMAs to VRAM.
 * Cloud tiles are used in the nametable (not as SAT sprites), so no
 * column-major rearrangement is needed — just a straight copy.
 */
void VDPTester::loadCloudTiles() {
    for (int i = 0; i < Cloud::TILE_COUNT * 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), Cloud::tiles[i / 32][i % 32]);
    }
    dmaFromRAM(RAM_DMA_BUF, static_cast<uint16_t>(TILE_CLOUD_BASE * 32), static_cast<uint16_t>(Cloud::TILE_COUNT * 16));
}

// ─── Utility ──────────────────────────────────────────────────────────────────

/**
 * Initialises the VDP to a known H40 state matching SoR1 boot conditions.
 * Call at the start of every test case.
 */
void VDPTester::initVDP() {
    vdp().reset();

    // Mode registers
    writeReg(0x00, 0x00); // Mode 1: no HBlank IRQ, no freeze, no left-col blank
    writeReg(0x01, 0x74); // Mode 2: display on, VBlank IRQ, DMA enable, Mode 5
    writeReg(0x0B, 0x00); // Mode 3: HScroll full-screen, VScroll full-screen
    writeReg(0x0C, 0x81); // Mode 4: H40 (RS1=RS0=1), no interlace, no S/H

    // Nametable and table bases
    writeReg(0x02, 0x30); // Plane A at 0xC000
    writeReg(0x03, 0x2C); // Window at 0xB000 (H40: multiple of $1000)
    writeReg(0x04, 0x07); // Plane B at 0xE000
    writeReg(0x05, 0x68); // SAT at 0xD000 (H40: bit 0 ignored)
    writeReg(0x0D, 0x3C); // HScroll table at 0xF000

    // Misc
    writeReg(0x07, 0x00); // Background colour: palette 0, entry 0 (transparent)
    writeReg(0x0F, 0x02); // Auto-increment: 2 bytes per data port access
    writeReg(0x10, 0x01); // Plane size: 64×32 cells

    // Blank tile 0: fill with zeros via VRAM fill DMA (1 word = 32 bytes is
    // overkill, but harmless; we set auto-increment to 1 temporarily).
    writeReg(0x0F, 0x01);
    dmaFill(0x0000, 32, 0x00);
    writeReg(0x0F, 0x02);
}

/** Fills Plane A nametable with blank tile entries. */
void VDPTester::clearPlaneA() {
    setVRAMWrite(VRAM_PLANEA);
    for (int i = 0; i < PLANE_W_CELLS * PLANE_H_CELLS; ++i) {
        writeDataWord(0x0000); // tile 0, palette 0, no priority, no flip
    }
}

/** Fills Plane B nametable with blank tile entries. */
void VDPTester::clearPlaneB() {
    setVRAMWrite(VRAM_PLANEB);
    for (int i = 0; i < PLANE_W_CELLS * PLANE_H_CELLS; ++i) {
        writeDataWord(0x0000);
    }
}

/**
 * Terminates the sprite chain at entry 0 (link=0, size=1×1, position off-screen).
 * Ensures no stray sprites from a previous test appear.
 */
void VDPTester::clearSAT() {
    setVRAMWrite(VRAM_SAT);
    writeDataWord(0x0000); // Y=0  (off-screen; 0+128-128 = 0 → hidden)
    writeDataWord(0x0000); // size=1×1, link=0 (end of chain)
    writeDataWord(0x0000); // tile 0
    writeDataWord(0x0000); // X=0 (masking sprite — used intentionally in testSpriteMasking)
}

/** Waits one VBlank then dumps the framebuffer and optionally everything to PNG. */
void VDPTester::renderAndDump(const char *name, bool everything) {
    waitVBlank();
    vdp().dumpFrameBufferToPNG(std::string(name) + ".png", true);
    if (everything) {
        vdp().dumpEverythingToPNG(std::string(name) + "_full.png", true);
    }
}
