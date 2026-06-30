/**
 * @file TestVDPTest05.cpp
 * @brief Test 05 — font rendering on Plane A.
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testFontPlaneA() {
    printf("\n[TEST 05] font on Plane A\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    static const uint16_t pal0[16] = {
        0x0000,
        0x0EEE,
        0x000E,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0EE0,
        0x0888,
        0x0AAA,
        0x0CCC,
        0x0EEE,
        0x0CEE,
        0x00EE,
        0x0E0E,
        0x0EEE,
    };
    static const uint16_t pal1[16] = {
        0x0000,
        0x0EE0,
        0x000E,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0EE0,
        0x0888,
        0x0AAA,
        0x0CCC,
        0x0EEE,
        0x0CEE,
        0x00EE,
        0x0E0E,
        0x0EEE,
    };
    loadCRAMPalette(0, pal0, 16);
    loadCRAMPalette(1, pal1, 16);

    static const uint16_t bgPal[] = {0x0400};
    loadCRAMPalette(2, bgPal, 1);
    writeReg(0x07, (2 << 4) | 0);

    loadFontTiles(1, 0);

    writeText(VRAM_PLANEA, 2, 2, PLANE_W_CELLS, "STREETS OF RAGE", 0, true);
    writeText(VRAM_PLANEA, 2, 4, PLANE_W_CELLS, "VDP TEST SUITE", 1, true);
    writeText(VRAM_PLANEA, 2, 6, PLANE_W_CELLS, "0123456789 ABCDEFGHIJKLMNOPQRSTUV", 0, false);
    writeText(VRAM_PLANEA, 2, 8, PLANE_W_CELLS, "WXYZ !\"#$%&'()*+,-./:;<=>?@[\\]^_`", 0, false);
    writeText(VRAM_PLANEA, 2, 10, PLANE_W_CELLS, "abcdefghijklmnopqrstuvwxyz{|}~", 0, false);

    renderAndDump("vdp_05_font", true);
    printf("[VISUAL] vdp_05_font.png — expect text lines on blue background.\n");
}
