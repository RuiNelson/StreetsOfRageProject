/**
 * @file TestVDPTest13.cpp
 * @brief Test 13 — Window plane as a non-scrolling HUD overlay.
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testWindowHUD() {
    printf("\n[TEST 13] Window plane HUD\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();
    writeReg(0x0B, 0x00);

    static const uint16_t bgPal[16] = {
        0x0800,
        0x000E,
        0x0EEE,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0EE0,
        0x0008,
        0x0080,
        0x0808,
        0x0880,
        0x0088,
        0x0808,
        0x0088,
        0x0EEE,
    };
    static const uint16_t fontPal[16] = {
        0x0000,
        0x0EEE,
        0x0EE0,
        0x000E,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0888,
        0x0AAA,
        0x0CCC,
        0x0EEE,
        0x0CEE,
        0x00EE,
        0x0E0E,
        0x0EEE,
    };
    static const uint16_t hudPal[16] = {
        0x0220,
        0x0EEE,
        0x0EE0,
        0x000E,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0888,
        0x0AAA,
        0x0CCC,
        0x0EEE,
        0x0CEE,
        0x00EE,
        0x0E0E,
        0x0EEE,
    };
    loadCRAMPalette(0, bgPal, 16);
    loadCRAMPalette(1, fontPal, 16);
    loadCRAMPalette(2, hudPal, 16);
    writeReg(0x07, (0 << 4) | 0);

    static constexpr uint16_t TILE_STRIPE    = TILE_GIRL_BASE;
    static constexpr uint8_t  stripeTile[32] = {
        0x11, 0x22, 0x33, 0x44, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x55, 0x66, 0x77, 0x88,
        0x11, 0x22, 0x33, 0x44, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x55, 0x66, 0x77, 0x88,
    };
    for (int i = 0; i < 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), stripeTile[i]);
    }
    dmaFromRAM(RAM_DMA_BUF, static_cast<uint16_t>(TILE_STRIPE * 32), 16);

    for (int cy = 0; cy < PLANE_H_CELLS; ++cy) {
        for (int cx = 0; cx < PLANE_W_CELLS; ++cx) {
            writeNametableEntry(VRAM_PLANEA, cx, cy, PLANE_W_CELLS, TILE_STRIPE, 0, false, false, false);
        }
    }

    setHScrollFull(-128, 0);

    writeReg(0x12, static_cast<uint8_t>(0x80 | 25));
    loadFontTiles(1, 0);

    writeText(VRAM_WINDOW, 1, 25, PLANE_W_CELLS, "SCORE: 000000", 2, true);
    writeText(VRAM_WINDOW, 1, 26, PLANE_W_CELLS, "LIVES: 3   STAGE: 1-1", 2, true);
    writeText(VRAM_WINDOW, 1, 27, PLANE_W_CELLS, "WINDOW PLANE  (NON-SCROLLING HUD)", 1, true);

    renderAndDump("vdp_13_window", true);
    printf("[VISUAL] vdp_13_window.png — stripes scroll, HUD rows stay fixed.\n");
}
