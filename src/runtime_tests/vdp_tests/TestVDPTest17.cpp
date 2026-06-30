/**
 * @file TestVDPTest17.cpp
 * @brief Test 17 — sprite collision (two ducks converge until SCOL fires).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testSpriteCollision() {
    printf("\n[TEST 17] sprite collision (two ducks)\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();
    writeReg(0x0B, 0x00);

    static const uint16_t bgPal[] = {0x0200};
    loadCRAMPalette(3, bgPal, 1);
    writeReg(0x07, (3 << 4) | 0);

    loadCRAMPalette(0, Duck::palette, 16);
    loadDuckTiles();

    static const uint16_t fontPal[16] = {
        0x0000,
        0x000E,
        0x0EEE,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    };
    loadCRAMPalette(1, fontPal, 16);
    loadFontTiles(1, 0);

    // Window plane occupies the bottom of the screen (rows 18..27 → y ≥ 144).
    writeReg(0x12, static_cast<uint8_t>(0x80 | 18));

    constexpr int DUCK_Y      = 96;
    constexpr int MAX_FRAMES  = 300;
    constexpr int POST_FRAMES = 120; // ~2 seconds at 60 Hz
    // Positions tuned so the ~2-second walk ends in an opaque-pixel overlap:
    // gap 216 px, closing 2 px/frame → ~108 frames of approach before SCOL fires.
    constexpr int INITIAL_L = 20;
    constexpr int INITIAL_R = 268;

    int  leftX     = INITIAL_L;
    int  rightX    = INITIAL_R;
    bool collided  = false;
    int  postCount = 0;

    // Drain any stale SCOL from prior tests.
    (void)vdp().readControlPort();

    for (int frame = 0; frame < MAX_FRAMES; ++frame) {
        setSpriteEntry(0, leftX, DUCK_Y, 4, 4, TILE_DUCK_BASE, 0, 1, true, false, false);
        setSpriteEntry(1, rightX, DUCK_Y, 4, 4, TILE_DUCK_BASE, 0, 0, true, true, false);

        waitVBlank();

        uint16_t status = vdp().readControlPort();
        if (!collided && (status & 0x0020)) {
            collided                   = true;
            static const char *msg     = "COLISION!";
            constexpr int      MSG_LEN = 9;
            int                cellX   = (SCREEN_W_CELLS - MSG_LEN) / 2;
            int                cellY   = 19; // ~2/3 of 224 px (cell 19 = y=152)
            writeText(VRAM_WINDOW, cellX, cellY, PLANE_W_CELLS, msg, 1, true);
        }

        if (collided) {
            if (++postCount >= POST_FRAMES)
                break;
        } else {
            leftX += 1;
            rightX -= 1;
        }
    }

    vdp().dumpFrameBufferToPNG("vdp_17_collision.png", true);
    vdp().dumpEverythingToPNG("vdp_17_collision_full.png", true);
    printf("[VISUAL] vdp_17_collision.png      — two ducks collided; message on window plane.\n");
    printf("[VISUAL] vdp_17_collision_full.png — tile sheet + plane dumps.\n");
}
