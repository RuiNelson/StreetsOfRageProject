/**
 * @file TestVDPTest10.cpp
 * @brief Test 10 — full-screen VScroll (animated).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testVScrollFullScreen() {
    printf("\n[TEST 10] full-screen VScroll\n");
    initVDP();
    clearSAT();
    writeReg(0x0B, 0x00);

    static const uint16_t pal[16] = {
        0x0000,
        0x000E,
        0x0E00,
        0x0EE0,
        0x00E0,
        0x0E0E,
        0x00EE,
        0x0EEE,
        0x0006,
        0x0060,
        0x0606,
        0x0660,
        0x0066,
        0x0606,
        0x0066,
        0x0EEE,
    };
    loadCRAMPalette(0, pal, 16);
    writeReg(0x07, (0 << 4) | 0);

    static constexpr uint8_t tile[32] = {
        0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22,
        0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x44, 0x44, 0x44, 0x44, 0x44, 0x44, 0x44, 0x44,
    };
    for (int i = 0; i < 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), tile[i]);
    }
    dmaFromRAM(RAM_DMA_BUF, 0x0020, 16);

    for (int cy = 0; cy < PLANE_H_CELLS; ++cy) {
        for (int cx = 0; cx < PLANE_W_CELLS; ++cx) {
            writeNametableEntry(VRAM_PLANEA, cx, cy, PLANE_W_CELLS, 1, 0, false, false, false);
            writeNametableEntry(VRAM_PLANEB, cx, cy, PLANE_W_CELLS, 1, 0, false, false, false);
        }
    }

    static constexpr int FRAMES_10 = 180;
    for (int frame = 0; frame < FRAMES_10; ++frame) {
        setVScrollFull(static_cast<int16_t>(frame), 0);
        waitVBlank();
    }

    vdp().dumpFrameBufferToPNG("vdp_10_vscroll.png", true);
    vdp().dumpEverythingToPNG("vdp_10_vscroll_full.png", true);
    printf("[VISUAL] vdp_10_vscroll.png — Plane A scrolled up 180px vs Plane B (final frame).\n");
}
