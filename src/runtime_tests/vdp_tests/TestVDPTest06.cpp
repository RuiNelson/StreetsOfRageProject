/**
 * @file TestVDPTest06.cpp
 * @brief Test 06 — background art on Plane B.
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testPlaneBBackground() {
    printf("\n[TEST 06] Plane B background\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    loadCRAMPalette(0, BG::palette, 16);
    writeReg(0x07, (0 << 4) | 0);
    loadBGTiles();

    for (int ty = 0; ty < BG::TILE_H; ++ty) {
        for (int tx = 0; tx < BG::TILE_W; ++tx) {
            int      idx  = ty * BG::TILE_W + tx;
            uint16_t tile = (idx < BG::HALF) ? static_cast<uint16_t>(TILE_BG0_BASE + idx)
                                             : static_cast<uint16_t>(TILE_BG1_BASE + idx - BG::HALF);
            writeNametableEntry(VRAM_PLANEB, tx, ty, PLANE_W_CELLS, tile, 0, false, false, false);
        }
    }

    renderAndDump("vdp_06_planeb", true);
    printf("[VISUAL] vdp_06_planeb.png — expect the background image on screen.\n");
}
