/**
 * @file TestVDPTest12.cpp
 * @brief Test 12 — sprite masking (sprite at X=0 hides later-linked sprites).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testSpriteMasking() {
    printf("\n[TEST 12] sprite masking\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();

    static const uint16_t bgPal[] = {0x0060};
    loadCRAMPalette(3, bgPal, 1);
    writeReg(0x07, (3 << 4) | 0);

    loadCRAMPalette(1, Duck::palette, 16);
    loadDuckTiles();

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
    loadCRAMPalette(2, fontPal, 16);
    loadFontTiles(1, 0);

    writeText(VRAM_PLANEA, 1, 1, PLANE_W_CELLS, "SPRITE 0: DUCK (100,80)  VISIBLE", 2, true);
    writeText(VRAM_PLANEA, 1, 2, PLANE_W_CELLS, "SPRITE 1: MASK X=0 Y=80 (1x4)", 2, true);
    writeText(VRAM_PLANEA, 1, 3, PLANE_W_CELLS, "SPRITE 2: DUCK (200,80)  MASKED", 2, true);
    writeText(VRAM_PLANEA, 1, 4, PLANE_W_CELLS, "SPRITE 3: DUCK (250,160) VISIBLE", 2, true);

    setSpriteEntry(0, 100, 80, 4, 4, TILE_DUCK_BASE, 1, 1, true, false, false);

    setVRAMWrite(static_cast<uint16_t>(VRAM_SAT + 1 * 8));
    writeDataWord(static_cast<uint16_t>((80 + 128) & 0x1FF));
    writeDataWord(0x0302);
    writeDataWord(0x0000);
    writeDataWord(0x0000); // X=0 → masking trigger

    setSpriteEntry(2, 200, 80, 4, 4, TILE_DUCK_BASE, 1, 3, true, false, false);
    setSpriteEntry(3, 250, 160, 4, 4, TILE_DUCK_BASE, 1, 0, true, false, false);

    renderAndDump("vdp_12_sprmask", true);
    printf("[VISUAL] vdp_12_sprmask.png — duck0 visible, duck2 masked, duck3 visible.\n");
}
