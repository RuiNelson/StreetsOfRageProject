/**
 * @file TestVDPTest15.cpp
 * @brief Test 15 — full scene composite.
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testFullScene() {
    printf("\n[TEST 15] full scene composite\n");
    initVDP();
    clearSAT();
    writeReg(0x0B, 0x00);

    loadCRAMPalette(0, BG::palette, 16);
    loadCRAMPalette(1, Girl::palette, 16);
    loadCRAMPalette(2, Duck::palette, 16);
    static const uint16_t hudPal[16] = {
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
    loadCRAMPalette(3, hudPal, 16);

    writeReg(0x07, 0x00);

    loadBGTiles();
    loadGirlTiles();
    loadDuckTiles();
    loadFontTiles(1, 0);

    // Plane B: background art
    clearPlaneB();
    for (int ty = 0; ty < BG::TILE_H; ++ty) {
        for (int tx = 0; tx < BG::TILE_W; ++tx) {
            int      idx  = ty * BG::TILE_W + tx;
            uint16_t tile = (idx < BG::HALF) ? static_cast<uint16_t>(TILE_BG0_BASE + idx)
                                             : static_cast<uint16_t>(TILE_BG1_BASE + idx - BG::HALF);
            writeNametableEntry(VRAM_PLANEB, tx, ty, PLANE_W_CELLS, tile, 0, false, false, false);
        }
    }

    clearPlaneA();

    writeReg(0x12, 0x80 | 25);
    writeText(VRAM_WINDOW, 2, 25, PLANE_W_CELLS, "SCORE: 028400   HI:100000", 3, true);
    writeText(VRAM_WINDOW, 2, 26, PLANE_W_CELLS, "AXEL LIVES: 3   STAGE 1", 3, true);
    writeText(VRAM_WINDOW, 2, 27, PLANE_W_CELLS, "STREETS OF RAGE I  RECOMPILED", 3, true);

    int si = 0;

    auto placeGirl = [&](int gx, int gy) {
        for (int row = 0; row < 3 && si < 78; ++row) {
            uint16_t tileL = static_cast<uint16_t>(TILE_GIRL_BASE + row * 24);
            uint16_t tileR = static_cast<uint16_t>(tileL + 12);
            int      nl = si + 1, nr = si + 2;
            setSpriteEntry(si, gx, gy + row * 32, 3, 4, tileL, 1, nl, true, false, false);
            ++si;
            setSpriteEntry(si, gx + 24, gy + row * 32, 3, 4, tileR, 1, nr, true, false, false);
            ++si;
        }
    };

    auto placeDuck = [&](int dx, int dy, int link) {
        setSpriteEntry(si, dx, dy, 4, 4, TILE_DUCK_BASE, 2, link, true, false, false);
        ++si;
    };

    placeGirl(40, 60);
    placeGirl(180, 50);
    int duckLink = si + 1;
    placeDuck(270, 110, duckLink);
    placeDuck(50, 130, 0);

    renderAndDump("vdp_15_scene", true);
    printf("[VISUAL] vdp_15_scene.png      — full scene: bg + sprites + HUD.\n");
    printf("[VISUAL] vdp_15_scene_full.png — tile sheet, plane dumps, SAT.\n");
}
