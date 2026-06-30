/**
 * @file TestVDPTest08.cpp
 * @brief Test 08 — full-screen HScroll (animated).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testHScrollFullScreen() {
    printf("\n[TEST 08] full-screen HScroll\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();
    writeReg(0x0B, 0x00);

    static const uint16_t pal[16] = {
        0x0000,
        0x000E,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0EE0,
        0x0EEE,
        0x0008,
        0x0080,
        0x0808,
        0x0880,
        0x0088,
        0x0808,
        0x0088,
        0x0EEE,
    };
    loadCRAMPalette(0, pal, 16);
    writeReg(0x07, (0 << 4) | 0);

    static constexpr uint8_t stripeTile[32] = {
        0x11, 0x22, 0x33, 0x44, 0x11, 0x22, 0x33, 0x44, 0x11, 0x22, 0x33, 0x44, 0x11, 0x22, 0x33, 0x44,
        0x55, 0x66, 0x77, 0x88, 0x55, 0x66, 0x77, 0x88, 0x55, 0x66, 0x77, 0x88, 0x55, 0x66, 0x77, 0x88,
    };
    for (int i = 0; i < 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), stripeTile[i]);
    }
    dmaFromRAM(RAM_DMA_BUF, 0x0020, 16);

    for (int cy = 0; cy < PLANE_H_CELLS; ++cy) {
        for (int cx = 0; cx < PLANE_W_CELLS; ++cx) {
            writeNametableEntry(VRAM_PLANEA, cx, cy, PLANE_W_CELLS, 1, 0, false, false, false);
        }
    }

    static constexpr int FRAMES_08 = 180;
    for (int frame = 0; frame < FRAMES_08; ++frame) {
        setHScrollFull(static_cast<int16_t>(frame * 2), 0);
        waitVBlank();
    }

    vdp().dumpFrameBufferToPNG("vdp_08_hscroll_full.png", true);
    vdp().dumpEverythingToPNG("vdp_08_hscroll_full_full.png", true);
    printf("[VISUAL] vdp_08_hscroll_full.png — stripes scrolling right (final frame).\n");
}
