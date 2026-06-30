/**
 * @file TestVDPTest14.cpp
 * @brief Test 14 — plane size 64×64 (SoR1 gameplay mode).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testPlaneSize64x64() {
    printf("\n[TEST 14] plane size 64x64\n");
    initVDP();
    clearSAT();

    writeReg(0x10, 0x11); // 64×64 cells
    writeReg(0x0B, 0x00);

    static const uint16_t pal[16] = {
        0x0200,
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
    loadCRAMPalette(0, pal, 16);
    loadCRAMPalette(1, pal, 16);
    writeReg(0x07, (0 << 4) | 0);

    loadFontTiles(1, 0);

    writeReg(0x05, 0x7A); // SAT at 0xF400

    static constexpr int PW = 64;
    static constexpr int PH = 64;

    for (int cy = 0; cy < PH; ++cy) {
        for (int cx = 0; cx < PW; ++cx) {
            writeNametableEntry(VRAM_PLANEA, cx, cy, PW, TILE_BLANK, 0, false, false, false);
        }
    }
    writeText(VRAM_PLANEA, 2, 2, PW, "ROWS  0-31: TOP HALF  (64x64 PLANE)", 0, true);
    writeText(VRAM_PLANEA, 2, 4, PW, "VScroll=0  -> visible at launch", 0, false);
    writeText(VRAM_PLANEA, 2, 34, PW, "ROWS 32-63: BOTTOM HALF", 1, true);
    writeText(VRAM_PLANEA, 2, 36, PW, "VScroll=+224 -> this region shows", 1, false);

    setVScrollFull(0, 0);
    renderAndDump("vdp_14a_plane64_top", true);

    setVScrollFull(224, 0);
    renderAndDump("vdp_14b_plane64_bot", true);

    writeReg(0x10, 0x01);
    writeReg(0x05, 0x68);

    printf("[VISUAL] vdp_14a_plane64_top.png — top-half text visible.\n");
    printf("[VISUAL] vdp_14b_plane64_bot.png — bottom-half text visible after scroll.\n");
}
