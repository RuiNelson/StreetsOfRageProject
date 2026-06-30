/**
 * @file TestVDPTest11.cpp
 * @brief Test 11 — sprite rendering (girl + duck with transparency).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testSprites() {
    printf("\n[TEST 11] sprites (girl + duck)\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();

    static const uint16_t bgPal[] = {0x0600};
    loadCRAMPalette(3, bgPal, 1);
    writeReg(0x07, (3 << 4) | 0);

    loadCRAMPalette(0, Girl::palette, 16);
    loadCRAMPalette(1, Duck::palette, 16);

    loadGirlTiles();
    loadDuckTiles();

    int spriteIdx = 0;

    auto addGirl = [&](int x, int y) {
        for (int row = 0; row < 3 && spriteIdx < 79; ++row) {
            int      nextLeft  = (spriteIdx + 1) < 79 ? spriteIdx + 1 : 0;
            int      nextRight = (spriteIdx + 2) < 79 ? spriteIdx + 2 : 0;
            uint16_t leftBase  = static_cast<uint16_t>(TILE_GIRL_BASE + row * 24);
            setSpriteEntry(spriteIdx, x, y + row * 32, 3, 4, leftBase, 0, nextLeft, true, false, false);
            ++spriteIdx;
            setSpriteEntry(spriteIdx,
                           x + 24,
                           y + row * 32,
                           3,
                           4,
                           static_cast<uint16_t>(leftBase + 12),
                           0,
                           nextRight,
                           true,
                           false,
                           false);
            ++spriteIdx;
        }
    };

    auto addDuck = [&](int x, int y, int linkNext) {
        setSpriteEntry(spriteIdx, x, y, 4, 4, TILE_DUCK_BASE, 1, linkNext, true, false, false);
        ++spriteIdx;
    };

    addGirl(20, 16);
    addGirl(160, 20);

    int duckLink0 = spriteIdx + 1;
    addDuck(260, 100, duckLink0);
    addDuck(100, 130, 0);

    renderAndDump("vdp_11_sprites", true);
    printf("[VISUAL] vdp_11_sprites.png — two girls and two ducks, transparent bg.\n");
}
