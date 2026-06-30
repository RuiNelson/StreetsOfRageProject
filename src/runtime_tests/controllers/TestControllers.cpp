/**
 * @file TestControllers.cpp
 * @brief Runtime test — Mega Drive controller readout via VDP display.
 */

#include "runtime_tests/controllers/TestControllers.hpp"
#include "util/font/Font.hpp"
#include <SDL3/SDL.h>

// ── VRAM / layout constants ──────────────────────────────────────────────────

static constexpr uint16_t VRAM_PLANEA = 0xC000;
static constexpr uint16_t TILE_FONT   = 1;  // tiles 1–95 = ASCII 0x20–0x7E
static constexpr int      PLANE_W     = 64; // nametable width (H40, 64×32)
static constexpr uint32_t RAM_DMA_BUF = 0xFF0000;

// Screen positions (H40: 40×28 visible cells, 0-indexed)
static constexpr int ROW_P1  = 2;
static constexpr int ROW_P2  = 9;
static constexpr int ROW_ESC = 17;

static constexpr int COL_LABEL   = 1;  // "Player X"
static constexpr int COL_STATUS  = 25; // "Connected" / "Disconnected"
static constexpr int COL_UP      = 9;  // "Up" (centred over "Down")
static constexpr int COL_LEFT    = 1;
static constexpr int COL_DOWN    = 7;
static constexpr int COL_RIGHT   = 12;
static constexpr int COL_START   = 28;
static constexpr int COL_A       = 26;
static constexpr int COL_B       = 30;
static constexpr int COL_C       = 34;
static constexpr int COL_ESC_MSG = 11; // centres "Press Esc to quit" (18 chars) in 40 cells

// ── Palette indices ──────────────────────────────────────────────────────────

static constexpr uint8_t PAL_GRAY   = 0; // unpressed buttons, misc text
static constexpr uint8_t PAL_YELLOW = 1; // player labels, pressed buttons
static constexpr uint8_t PAL_GREEN  = 2; // "Connected"
static constexpr uint8_t PAL_RED    = 3; // "Disconnected"

// ── CRAM values (format: 0000_BBB0_GGG0_RRR0) ───────────────────────────────

static constexpr uint16_t CLR_BLACK  = 0x0000;
static constexpr uint16_t CLR_GRAY   = 0x0888;
static constexpr uint16_t CLR_YELLOW = 0x00EE; // R=7, G=7, B=0
static constexpr uint16_t CLR_GREEN  = 0x00E0; // G=7
static constexpr uint16_t CLR_RED    = 0x000E; // R=7

// ── VDP helpers (module-private) ─────────────────────────────────────────────

static uint16_t word1(uint8_t cd, uint16_t addr) {
    return static_cast<uint16_t>(((cd & 0x03u) << 14) | (addr & 0x3FFFu));
}
static uint16_t word2(uint8_t cd, uint16_t addr) {
    return static_cast<uint16_t>(((cd & 0x3Cu) << 2) | ((addr >> 14) & 0x03u));
}
static uint16_t nametableWord(uint16_t tile, uint8_t pal, bool priority) {
    return static_cast<uint16_t>((priority ? 0x8000u : 0u) | ((pal & 3u) << 13) | (tile & 0x7FFu));
}

static void writeReg(VDP &vdp, uint8_t reg, uint8_t val) {
    vdp.writeControlPort(static_cast<uint16_t>(0x8000u | (reg << 8) | val));
}
static void setVRAMWrite(VDP &vdp, uint16_t addr) {
    vdp.writeControlPort(word1(0x01, addr));
    vdp.writeControlPort(word2(0x01, addr));
}
static void setCRAMWrite(VDP &vdp, uint16_t addr) {
    vdp.writeControlPort(word1(0x03, addr));
    vdp.writeControlPort(word2(0x03, addr));
}
static void dmaFromRAM(VDP &vdp, uint32_t src, uint16_t dst, uint16_t words) {
    uint32_t srcWord = src >> 1;
    writeReg(vdp, 0x13, static_cast<uint8_t>(words & 0xFF));
    writeReg(vdp, 0x14, static_cast<uint8_t>((words >> 8) & 0xFF));
    writeReg(vdp, 0x15, static_cast<uint8_t>(srcWord & 0xFF));
    writeReg(vdp, 0x16, static_cast<uint8_t>((srcWord >> 8) & 0xFF));
    writeReg(vdp, 0x17, static_cast<uint8_t>((srcWord >> 16) & 0x7F));
    uint8_t cd = 0x01u | 0x20u;
    vdp.writeControlPort(word1(cd, dst));
    vdp.writeControlPort(word2(cd, dst));
}
static void dmaFill(VDP &vdp, uint16_t dst, uint16_t words, uint8_t fill) {
    writeReg(vdp, 0x13, static_cast<uint8_t>(words & 0xFF));
    writeReg(vdp, 0x14, static_cast<uint8_t>((words >> 8) & 0xFF));
    writeReg(vdp, 0x17, 0x80);
    uint8_t cd = 0x01u | 0x20u;
    vdp.writeControlPort(word1(cd, dst));
    vdp.writeControlPort(word2(cd, dst));
    vdp.writeDataPort(static_cast<uint16_t>(fill | (fill << 8)));
}

static void writeText(VDP &vdp, int col, int row, const char *text, uint8_t pal, bool priority = true) {
    for (int i = 0; text[i]; ++i) {
        uint8_t  ch   = static_cast<uint8_t>(text[i]);
        uint16_t tile = (ch >= 0x20 && ch <= 0x7E) ? static_cast<uint16_t>(TILE_FONT + (ch - 0x20)) : 0u;
        uint16_t addr = static_cast<uint16_t>(VRAM_PLANEA + (row * PLANE_W + col + i) * 2);
        setVRAMWrite(vdp, addr);
        vdp.writeDataPort(nametableWord(tile, pal, priority));
    }
}

static void loadPalette(VDP &vdp, uint8_t pal, const uint16_t *colors, int count) {
    setCRAMWrite(vdp, static_cast<uint16_t>(pal * 16 * 2));
    for (int i = 0; i < count; ++i) {
        vdp.writeDataPort(colors[i]);
    }
}

static void loadFont(VDP &vdp, SystemMemory &mem) {
    static constexpr int N = 0x7E - 0x20 + 1;
    for (int i = 0; i < N; ++i) {
        Font::fontCharToVDPTile(mem, static_cast<uint8_t>(0x20 + i), 1, 0, RAM_DMA_BUF + static_cast<uint32_t>(i * 32));
    }
    dmaFromRAM(vdp, RAM_DMA_BUF, static_cast<uint16_t>(TILE_FONT * 32), static_cast<uint16_t>(N * 16));
}

static void clearPlaneA(VDP &vdp) {
    setVRAMWrite(vdp, VRAM_PLANEA);
    for (int i = 0; i < PLANE_W * 32; ++i) {
        vdp.writeDataPort(0x0000);
    }
}

// ── Player display update ─────────────────────────────────────────────────────

static void updatePlayer(VDP &vdp, int baseRow, const PlayerControlsState &s) {
    int dpadRow = baseRow + 2;
    int btnRow  = baseRow + 3;

    if (s.connected) {
        writeText(vdp, COL_STATUS, baseRow, "Connected   ", PAL_GREEN);
    } else {
        writeText(vdp, COL_STATUS, baseRow, "Disconnected", PAL_RED);
    }

    writeText(vdp, COL_UP, dpadRow, "Up", s.up ? PAL_YELLOW : PAL_GRAY);
    writeText(vdp, COL_START, dpadRow, "Start", s.start ? PAL_YELLOW : PAL_GRAY);

    writeText(vdp, COL_LEFT, btnRow, "Left", s.left ? PAL_YELLOW : PAL_GRAY);
    writeText(vdp, COL_DOWN, btnRow, "Down", s.down ? PAL_YELLOW : PAL_GRAY);
    writeText(vdp, COL_RIGHT, btnRow, "Right", s.right ? PAL_YELLOW : PAL_GRAY);
    writeText(vdp, COL_A, btnRow, "A", s.a ? PAL_YELLOW : PAL_GRAY);
    writeText(vdp, COL_B, btnRow, "B", s.b ? PAL_YELLOW : PAL_GRAY);
    writeText(vdp, COL_C, btnRow, "C", s.c ? PAL_YELLOW : PAL_GRAY);
}

// ── Constructor ───────────────────────────────────────────────────────────────

TestControllers::TestControllers() : MegaDriveEnvironment(VDP::VSync, VDP::Integer) {
    VDP &v = vdp();
    v.reset();

    writeReg(v, 0x00, 0x00);
    writeReg(v, 0x01, 0x74); // display on, VBlank IRQ, DMA, Mode 5
    writeReg(v, 0x0B, 0x00);
    writeReg(v, 0x0C, 0x81); // H40
    writeReg(v, 0x02, 0x30); // Plane A at 0xC000
    writeReg(v, 0x03, 0x2C); // Window at 0xB000
    writeReg(v, 0x04, 0x07); // Plane B at 0xE000
    writeReg(v, 0x05, 0x68); // SAT at 0xD000
    writeReg(v, 0x0D, 0x3C); // HScroll at 0xF000
    writeReg(v, 0x07, 0x00); // background: palette 0, entry 0 (black)
    writeReg(v, 0x0F, 0x02); // auto-increment 2
    writeReg(v, 0x10, 0x01); // plane 64×32

    // blank tile 0
    writeReg(v, 0x0F, 0x01);
    dmaFill(v, 0x0000, 32, 0x00);
    writeReg(v, 0x0F, 0x02);

    // Palettes: [black, color] — index 0 = bg, index 1 = fg
    const uint16_t pal0[2] = {CLR_BLACK, CLR_GRAY};
    const uint16_t pal1[2] = {CLR_BLACK, CLR_YELLOW};
    const uint16_t pal2[2] = {CLR_BLACK, CLR_GREEN};
    const uint16_t pal3[2] = {CLR_BLACK, CLR_RED};
    loadPalette(v, PAL_GRAY, pal0, 2);
    loadPalette(v, PAL_YELLOW, pal1, 2);
    loadPalette(v, PAL_GREEN, pal2, 2);
    loadPalette(v, PAL_RED, pal3, 2);

    loadFont(v, memory());
    clearPlaneA(v);

    writeText(v, COL_LABEL, ROW_P1, "Player 1", PAL_YELLOW);
    writeText(v, COL_LABEL, ROW_P2, "Player 2", PAL_YELLOW);
    writeText(v, COL_ESC_MSG, ROW_ESC, "Press Esc to quit", PAL_GRAY, false);
}

// ── Frame synchronisation ──────────────────────────────────────────────────────

void TestControllers::vSync() {
    frameReady_ = true;
}

void TestControllers::waitVBlank() {
    VDP::Interrupt discard;
    while (vdp().popInterrupt(discard)) {
    }
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

// ── Run loop ──────────────────────────────────────────────────────────────────

void TestControllers::run() {
    // Events are pumped on the main thread by boot(); here we only read input
    // snapshots. Quit on window close (shouldQuit) or the Esc key.
    while (!shouldQuit()) {
        const bool *keys = SDL_GetKeyboardState(nullptr);
        if (keys && keys[SDL_SCANCODE_ESCAPE]) {
            break;
        }

        waitVBlank();

        PlayersControlState state = controllers().getCurrentState();
        updatePlayer(vdp(), ROW_P1, state.player1);
        updatePlayer(vdp(), ROW_P2, state.player2);
    }
}
