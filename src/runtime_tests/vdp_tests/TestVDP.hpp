#pragma once

#include <art/BackgroundTileData.hpp>
#include <art/CloudTileData.hpp>
#include <art/DuckTileData.hpp>
#include <art/GirlTileData.hpp>
#include <cstdint>
#include <string>
#include <system/MegaDriveEnvironment.hpp>

// ─── VRAM address constants ───────────────────────────────────────────────────

static constexpr uint16_t VRAM_WINDOW  = 0xB000; // reg $03 = 0x2C
static constexpr uint16_t VRAM_PLANEA  = 0xC000; // reg $02 = 0x30
static constexpr uint16_t VRAM_SAT     = 0xD000; // reg $05 = 0x68
static constexpr uint16_t VRAM_PLANEB  = 0xE000; // reg $04 = 0x07
static constexpr uint16_t VRAM_HSCROLL = 0xF000; // reg $0D = 0x3C

// ─── Tile index constants ─────────────────────────────────────────────────────

static constexpr uint16_t TILE_BLANK      = 0;
static constexpr uint16_t TILE_FONT_BASE  = 1;   // chars 0x20–0x7E → indices 1–95
static constexpr uint16_t TILE_GIRL_BASE  = 96;  // 72 tiles (6 wide × 12 tall)
static constexpr uint16_t TILE_DUCK_BASE  = 168; // 16 tiles (4 wide × 4 tall)
static constexpr uint16_t TILE_BG0_BASE   = 184; // 560 tiles (bg first half)
static constexpr uint16_t TILE_BG1_BASE   = 744; // 560 tiles (bg second half)
static constexpr uint16_t TILE_CLOUD_BASE = 184; // 18 tiles (6×3, shares slot with BG — never used together)

// ─── Work-RAM DMA staging buffer ─────────────────────────────────────────────

static constexpr uint32_t RAM_DMA_BUF = 0xFF0000; // start of work RAM

// ─── Plane geometry (H40, 64×32 plane) ───────────────────────────────────────

static constexpr int PLANE_W_CELLS  = 64;
static constexpr int PLANE_H_CELLS  = 32;
static constexpr int SCREEN_W_CELLS = 40;
static constexpr int SCREEN_H_CELLS = 28;

// ─── CD (command/direction) codes ────────────────────────────────────────────

static constexpr uint8_t CD_VRAM_W  = 0x01;
static constexpr uint8_t CD_CRAM_W  = 0x03;
static constexpr uint8_t CD_VSRAM_W = 0x05;
static constexpr uint8_t CD_DMA_BIT = 0x20; // OR with CD_VRAM_W to trigger DMA

// ─── Free helpers ─────────────────────────────────────────────────────────────

static uint16_t makeWord1(uint8_t cd, uint16_t addr) {
    return static_cast<uint16_t>(((cd & 0x03u) << 14) | (addr & 0x3FFFu));
}
static uint16_t makeWord2(uint8_t cd, uint16_t addr) {
    return static_cast<uint16_t>(((cd & 0x3Cu) << 2) | ((addr >> 14) & 0x03u));
}
static uint16_t nametableWord(uint16_t tileIndex, uint8_t palette, bool priority, bool hflip, bool vflip) {
    return static_cast<uint16_t>((priority ? 0x8000u : 0u) | ((palette & 3u) << 13) | (vflip ? 0x1000u : 0u) |
                                 (hflip ? 0x0800u : 0u) | (tileIndex & 0x7FFu));
}

// ─── VDPTester class ─────────────────────────────────────────────────────────

/**
 * @brief Tests the VDP emulator for good enough emulation to run Streets of Rage 1.
 *
 * SoR1 ROM analysis (boot table at $02C4, runtime writes):
 *   reg $0C = $81  → H40 only; interlace and shadow/highlight never used
 *   reg $0B = $00/$03 → HScroll: full-screen (menus) or per-scanline (gameplay)
 *   reg $0B VS=0  → VScroll: always full-screen
 *   reg $10 = $01/$11 → plane 64×32 (boot) or 64×64 (gameplay)
 *
 * Features not tested (SoR1 never uses them):
 *   H32 mode, interlace, shadow/highlight, per-2-cell VScroll,
 *   8-line-row HScroll, More than 64KB of VRAM, HBlank IRQ, external IRQ.
 */
class VDPTester : public MegaDriveEnvironment {
    private:
    /// Set by vSync() (on the run() thread) to signal a fresh frame is ready.
    bool frameReady_ = false;

    /// Per-scanline HScroll values updated by hSync(); used by testRasterHSync.
    int16_t hSyncScrollA_[VDPState::SCREEN_H] = {};

    // ── VBlank/HBlank synchronisation ──────────────────────────────────────
    void vSync() override;
    void hSync(int line) override;
    void waitVBlank();

    public:
    // ── Control-port helpers ───────────────────────────────────────────────
    void writeReg(uint8_t reg, uint8_t value);
    void setAddress(uint8_t cd, uint16_t addr);
    void setVRAMWrite(uint16_t addr);
    void setCRAMWrite(uint16_t addr); // addr = CRAM entry index × 2
    void setVSRAMWrite(uint16_t addr);
    void writeDataWord(uint16_t value);

    // ── DMA helpers ─────────────────────────────────────────────────────────
    void dmaFromRAM(uint32_t srcAddr, uint16_t dstVRAMAddr, uint16_t lengthWords);
    void dmaFill(uint16_t dstVRAMAddr, uint16_t lengthWords, uint8_t fillByte);

    // ── CRAM / palette helpers ───────────────────────────────────────────────
    void loadCRAMPalette(uint8_t palette, const uint16_t *colors, int count);

    // ── Nametable helpers (public for test code) ─────────────────────────────
    void writeNametableEntry(uint16_t base,
                             int      cellX,
                             int      cellY,
                             int      planeWidthCells,
                             uint16_t tileIndex,
                             uint8_t  palette,
                             bool     priority,
                             bool     hflip,
                             bool     vflip);
    void writeText(uint16_t    nametableBase,
                   int         cellX,
                   int         cellY,
                   int         planeWidthCells,
                   const char *text,
                   uint8_t     palette,
                   bool        priority);

    // ── Sprite helpers ───────────────────────────────────────────────────────
    void setSpriteEntry(int      spriteIdx,
                        int      x_screen,
                        int      y_screen,
                        uint8_t  wTiles,
                        uint8_t  hTiles,
                        uint16_t tileIndex,
                        uint8_t  palette,
                        int      link,
                        bool     priority,
                        bool     hflip,
                        bool     vflip);

    // ── Scroll helpers ───────────────────────────────────────────────────────
    void setHScrollFull(int16_t scrollA, int16_t scrollB);
    void setHScrollPerScanline(const int16_t *scrollA, const int16_t *scrollB, int lines);
    void setVScrollFull(int16_t scrollA, int16_t scrollB);

    // ── Tile loading ─────────────────────────────────────────────────────────
    void loadFontTiles(uint8_t fgIdx, uint8_t bgIdx);
    void loadGirlTiles();
    void loadDuckTiles();
    void loadBGTiles();
    void loadCloudTiles();

    // ── Utility ──────────────────────────────────────────────────────────────
    void initVDP();
    void clearPlaneA();
    void clearPlaneB();
    void clearSAT();
    void renderAndDump(const char *name, bool everything = false);

    // ── Test cases ───────────────────────────────────────────────────────────
    void testRegisters();
    void testBackgroundColor();
    void testCRAMPalette();
    void testVRAMFill();
    void testFontPlaneA();
    void testPlaneBBackground();
    void testTwoPlanes();
    void testHScrollFullScreen();
    void testHScrollPerScanline();
    void testVScrollFullScreen();
    void testSprites();
    void testSpriteMasking();
    void testWindowHUD();
    void testPlaneSize64x64();
    void testFullScene();
    void testAnimated();
    void testSpriteCollision();
    void testRasterHSync();

    public:
    VDPTester();

    protected:
    /// Cartridge entry point (runs on the CPU thread): runs the full test suite.
    void run() override;
};
