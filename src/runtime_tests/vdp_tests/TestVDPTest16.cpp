/**
 * @file TestVDPTest16.cpp
 * @brief Test 16 — animated scene (~8 seconds, 480 frames at 60 Hz).
 */

#include "TestVDP.hpp"
#include <cmath>
#include <cstdio>

void VDPTester::testAnimated() {
    printf("\n[TEST 16] animated scene (480 frames)\n");

    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    writeReg(0x0B, 0x03);

    static const uint16_t skyPal[16] = {
        0x0E40,
        Cloud::palette[1],
        Cloud::palette[2],
        Cloud::palette[3],
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
    };
    static const uint16_t hudPal[16] = {
        0x0000,
        0x0EEE,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
        0x0000,
    };

    loadCRAMPalette(0, skyPal, 16);
    loadCRAMPalette(1, Girl::palette, 16);
    loadCRAMPalette(2, Duck::palette, 16);
    loadCRAMPalette(3, hudPal, 16);

    writeReg(0x07, 0x00);

    loadCloudTiles();
    loadGirlTiles();
    loadDuckTiles();
    loadFontTiles(1, 0);

    // Plane B: cloud sky
    struct CloudPos {
        int cx, cy;
    };
    static constexpr CloudPos cloudPositions[] = {
        {0, 0},
        {10, 3},
        {20, 1},
        {30, 0},
        {40, 2},
        {50, 0},
        {58, 3},
        {5, 5},
    };
    for (auto &cp : cloudPositions) {
        for (int ty = 0; ty < Cloud::TILE_H; ++ty) {
            for (int tx = 0; tx < Cloud::TILE_W; ++tx) {
                int tileIdx = ty * Cloud::TILE_W + tx;
                int cellX   = (cp.cx + tx) % PLANE_W_CELLS;
                int cellY   = cp.cy + ty;
                if (cellY < PLANE_H_CELLS) {
                    writeNametableEntry(VRAM_PLANEB,
                                        cellX,
                                        cellY,
                                        PLANE_W_CELLS,
                                        static_cast<uint16_t>(TILE_CLOUD_BASE + tileIdx),
                                        0,
                                        false,
                                        false,
                                        false);
                }
            }
        }
    }

    writeReg(0x12, static_cast<uint8_t>(0x80 | 26));
    writeText(VRAM_WINDOW, 1, 26, PLANE_W_CELLS, "STREETS OF RAGE  VDP ANIMATED DEMO", 3, true);
    writeText(VRAM_WINDOW, 1, 27, PLANE_W_CELLS, "GIRL + DUCK RAINBOW ORBIT", 3, true);

    static constexpr int GIRL_X   = 136;
    static constexpr int GIRL_Y   = 64;
    static constexpr int ORBIT_CX = GIRL_X + 24; // 160
    static constexpr int ORBIT_CY = GIRL_Y + 48; // 112

    for (int row = 0; row < 3; ++row) {
        uint16_t tileL = static_cast<uint16_t>(TILE_GIRL_BASE + row * 24);
        uint16_t tileR = static_cast<uint16_t>(tileL + 12);
        int      satL  = 1 + row * 2;
        int      satR  = 2 + row * 2;
        int      nextL = satR;
        int      nextR = (row < 2) ? satR + 1 : 0;
        setSpriteEntry(satL, GIRL_X, GIRL_Y + row * 32, 3, 4, tileL, 1, nextL, true, false, false);
        setSpriteEntry(satR, GIRL_X + 24, GIRL_Y + row * 32, 3, 4, tileR, 1, nextR, true, false, false);
    }

    static constexpr uint16_t rainbow[] = {
        0x0EEE, 0x0EEA, 0x0EE6, 0x0EE0, 0x0EC0, 0x0E80, 0x0E40, 0x0E00, 0x0E04, 0x0E08, 0x0E0C, 0x0E0E,
        0x080E, 0x040E, 0x000E, 0x00CE, 0x00EE, 0x00EC, 0x00E8, 0x00E4, 0x00E0, 0x0CE0, 0x0EE0, 0x0EEC,
    };
    static constexpr int RAINBOW_LEN = static_cast<int>(sizeof(rainbow) / sizeof(rainbow[0]));

    static int16_t hScrollA[224];
    static int16_t hScrollB[224];

    static constexpr int   TOTAL_FRAMES = 480;
    static constexpr float PI           = 3.14159265f;

    for (int frame = 0; frame < TOTAL_FRAMES; ++frame) {

        float angle     = frame * (2.0f * PI / 180.0f);
        float cosA      = cosf(angle);
        float sinA      = sinf(angle);
        int   duckX     = ORBIT_CX - 16 + static_cast<int>(cosA * 72.0f);
        int   duckY     = ORBIT_CY - 16 + static_cast<int>(sinA * 28.0f);
        bool  duckFront = sinA >= 0.0f;
        bool  duckHFlip = cosA < 0.0f;

        if (duckFront) {
            setSpriteEntry(0, duckX, duckY, 4, 4, TILE_DUCK_BASE, 2, 1, true, duckHFlip, false);
            setSpriteEntry(6,
                           GIRL_X + 24,
                           GIRL_Y + 64,
                           3,
                           4,
                           static_cast<uint16_t>(TILE_GIRL_BASE + 2 * 24 + 12),
                           1,
                           0,
                           true,
                           false,
                           false);
        } else {
            setSpriteEntry(0, 0, -128, 1, 1, 0, 0, 1, false, false, false);
            setSpriteEntry(6,
                           GIRL_X + 24,
                           GIRL_Y + 64,
                           3,
                           4,
                           static_cast<uint16_t>(TILE_GIRL_BASE + 2 * 24 + 12),
                           1,
                           7,
                           true,
                           false,
                           false);
            setSpriteEntry(7, duckX, duckY, 4, 4, TILE_DUCK_BASE, 2, 0, true, duckHFlip, false);
        }

        float    skyT     = 0.5f + 0.5f * sinf(frame * (2.0f * PI / 480.0f));
        uint8_t  skyR     = static_cast<uint8_t>(skyT * 4.0f);
        uint8_t  skyG     = 3 + static_cast<uint8_t>(skyT * 3.0f);
        uint8_t  skyB     = 4 + static_cast<uint8_t>((1.0f - skyT * 0.5f) * 3.0f);
        uint16_t skyColor = static_cast<uint16_t>((skyB << 9) | (skyG << 5) | (skyR << 1));
        setCRAMWrite(0);
        writeDataWord(skyColor);

        // Duck yellow entries (1 and 2) cycle through the rainbow;
        // all other palette entries stay as in Duck::palette.
        uint16_t duckColor = rainbow[(frame / 4) % RAINBOW_LEN];
        setCRAMWrite(static_cast<uint16_t>(2 * 16 * 2 + 1 * 2)); // entry 1
        writeDataWord(duckColor);
        setCRAMWrite(static_cast<uint16_t>(2 * 16 * 2 + 2 * 2)); // entry 2
        writeDataWord(duckColor);

        uint16_t textColor = rainbow[(frame / 8) % RAINBOW_LEN];
        setCRAMWrite(static_cast<uint16_t>(3 * 16 * 2 + 1 * 2));
        writeDataWord(textColor);

        int16_t cloudDrift = static_cast<int16_t>(-(frame / 3));

        for (int y = 0; y < 224; ++y) {
            hScrollA[y] = 0;
            if (y > 80) {
                float depth   = (y - 80) / 144.0f;
                float shimmer = depth * 1.5f * sinf(y * 0.25f + frame * 0.18f);
                hScrollA[y]   = static_cast<int16_t>(static_cast<int>(shimmer));
            }
            hScrollB[y] = cloudDrift;
        }
        setHScrollPerScanline(hScrollA, hScrollB, 224);

        waitVBlank();
    }

    vdp().dumpFrameBufferToPNG("vdp_16_animated.png", true);
    vdp().dumpEverythingToPNG("vdp_16_animated_full.png", true);

    printf("[VISUAL] vdp_16_animated.png — duck cycles through rainbow colours.\n");
    printf("[VISUAL] vdp_16_animated_full.png  — tile sheet + plane debug view.\n");
}
