/**
 * @file TestVDPTest07.cpp
 * @brief Test 07 — two-plane layering (Plane A text over Plane B background).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testTwoPlanes() {
    printf("\n[TEST 07] two-plane layering\n");
    initVDP();
    clearPlaneA();
    clearSAT();

    loadCRAMPalette(0, BG::palette, 16);
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
    loadCRAMPalette(1, fontPal, 16);

    loadBGTiles();
    for (int ty = 0; ty < BG::TILE_H; ++ty) {
        for (int tx = 0; tx < BG::TILE_W; ++tx) {
            int      idx  = ty * BG::TILE_W + tx;
            uint16_t tile = (idx < BG::HALF) ? static_cast<uint16_t>(TILE_BG0_BASE + idx)
                                             : static_cast<uint16_t>(TILE_BG1_BASE + idx - BG::HALF);
            writeNametableEntry(VRAM_PLANEB, tx, ty, PLANE_W_CELLS, tile, 0, false, false, false);
        }
    }

    loadFontTiles(1, 0);
    writeText(VRAM_PLANEA, 2, 2, PLANE_W_CELLS, "STREETS OF RAGE", 1, true);
    writeText(VRAM_PLANEA, 2, 4, PLANE_W_CELLS, "TWO PLANES TEST", 1, true);
    writeText(VRAM_PLANEA, 2, 26, PLANE_W_CELLS, "PLANE A OVER PLANE B", 1, true);

    renderAndDump("vdp_07_twoplanes", true);
    printf("[VISUAL] vdp_07_twoplanes.png — text in front of background image.\n");
}
