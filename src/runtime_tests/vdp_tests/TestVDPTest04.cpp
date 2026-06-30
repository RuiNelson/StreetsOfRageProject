/**
 * @file TestVDPTest04.cpp
 * @brief Test 04 — VRAM fill DMA.
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testVRAMFill() {
    printf("\n[TEST 04] VRAM fill DMA\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    static const uint16_t pal[] = {
        0x0000,
        0x000E,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0EE0,
        0x0EEE,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x00EE,
        0x0EEE,
    };
    loadCRAMPalette(0, pal, 16);

    writeReg(0x0F, 0x01);
    dmaFill(0x0020, 32, 0xEE); // tile 1
    writeReg(0x0F, 0x02);

    writeReg(0x0F, 0x01);
    dmaFill(0x0040, 32, 0x11); // tile 2
    writeReg(0x0F, 0x02);

    for (int cy = 0; cy < SCREEN_H_CELLS; ++cy) {
        for (int cx = 0; cx < SCREEN_W_CELLS; ++cx) {
            uint16_t tile = ((cx + cy) & 1) ? 1u : 2u;
            writeNametableEntry(VRAM_PLANEA, cx, cy, PLANE_W_CELLS, tile, 0, false, false, false);
        }
    }

    renderAndDump("vdp_04_vramfill", true);
    printf("[VISUAL] vdp_04_vramfill.png     — expect yellow/red checkerboard.\n");
    printf("[VISUAL] vdp_04_vramfill_full.png— check tile sheet for filled tiles.\n");
}
