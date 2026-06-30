/**
 * @file TestVDPTest03.cpp
 * @brief Test 03 — CRAM palette display.
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testCRAMPalette() {
    printf("\n[TEST 03] CRAM palette\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    static const uint16_t pal0[16] = {
        0x0000,
        0x0002,
        0x0004,
        0x0006,
        0x0008,
        0x000A,
        0x000C,
        0x000E,
        0x000E,
        0x000C,
        0x000A,
        0x0008,
        0x0006,
        0x0004,
        0x0002,
        0x0000,
    };
    static const uint16_t pal1[16] = {
        0x0000,
        0x0020,
        0x0040,
        0x0060,
        0x0080,
        0x00A0,
        0x00C0,
        0x00E0,
        0x00E0,
        0x00C0,
        0x00A0,
        0x0080,
        0x0060,
        0x0040,
        0x0020,
        0x0000,
    };
    static const uint16_t pal2[16] = {
        0x0000,
        0x0200,
        0x0400,
        0x0600,
        0x0800,
        0x0A00,
        0x0C00,
        0x0E00,
        0x0E00,
        0x0C00,
        0x0A00,
        0x0800,
        0x0600,
        0x0400,
        0x0200,
        0x0000,
    };
    static const uint16_t pal3[16] = {
        0x0000,
        0x0EEE,
        0x0E00,
        0x00E0,
        0x000E,
        0x0EE0,
        0x00EE,
        0x0E0E,
        0x0864,
        0x0468,
        0x0648,
        0x0ACE,
        0x0CA8,
        0x08AC,
        0x0C8A,
        0x0EEE,
    };
    loadCRAMPalette(0, pal0, 16);
    loadCRAMPalette(1, pal1, 16);
    loadCRAMPalette(2, pal2, 16);
    loadCRAMPalette(3, pal3, 16);

    for (int tileIdx = 0; tileIdx < 64; ++tileIdx) {
        uint8_t pv = static_cast<uint8_t>((tileIdx << 4) | tileIdx);
        setVRAMWrite(static_cast<uint16_t>((TILE_GIRL_BASE + tileIdx) * 32));
        for (int row = 0; row < 8; ++row) {
            writeDataWord(static_cast<uint16_t>((pv << 8) | pv));
        }
    }

    for (int pal = 0; pal < 4; ++pal) {
        for (int entry = 0; entry < 16; ++entry) {
            int      cellX     = entry * 2;
            int      cellY     = pal * 7;
            uint16_t tileIndex = static_cast<uint16_t>(TILE_GIRL_BASE + pal * 16 + entry);
            for (int dy = 0; dy < 6 && (cellY + dy) < SCREEN_H_CELLS; ++dy) {
                for (int dx = 0; dx < 2; ++dx) {
                    writeNametableEntry(VRAM_PLANEA,
                                        cellX + dx,
                                        cellY + dy,
                                        PLANE_W_CELLS,
                                        tileIndex,
                                        static_cast<uint8_t>(pal),
                                        false,
                                        false,
                                        false);
                }
            }
        }
    }

    renderAndDump("vdp_03_cram", true);
    printf("[VISUAL] vdp_03_cram.png — expect 4 rows of 16 colour swatches.\n");
}
