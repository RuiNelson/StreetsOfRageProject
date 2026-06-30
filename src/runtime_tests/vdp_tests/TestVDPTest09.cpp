/**
 * @file TestVDPTest09.cpp
 * @brief Test 09 — per-scanline HScroll animated (SoR1 gameplay mode).
 */

#include "TestVDP.hpp"
#include <cmath>
#include <cstdio>

void VDPTester::testHScrollPerScanline() {
    printf("\n[TEST 09] per-scanline HScroll\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();
    writeReg(0x0B, 0x03);

    static const uint16_t pal[16] = {
        0x0400,
        0x000E,
        0x0EEE,
        0x00E0,
        0x00EE,
        0x0E00,
        0x0E0E,
        0x0EE0,
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

    static constexpr uint8_t hStripeTile[32] = {
        0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22,
        0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22,
    };
    for (int i = 0; i < 32; ++i) {
        memory().writeByte(RAM_DMA_BUF + static_cast<uint32_t>(i), hStripeTile[i]);
    }
    dmaFromRAM(RAM_DMA_BUF, 0x0020, 16);

    for (int cy = 0; cy < PLANE_H_CELLS; ++cy) {
        for (int cx = 0; cx < PLANE_W_CELLS; ++cx) {
            writeNametableEntry(VRAM_PLANEA, cx, cy, PLANE_W_CELLS, 1, 0, false, false, false);
        }
    }

    static int16_t         scrollA[224];
    static int16_t         scrollB[224];
    static constexpr int   FRAMES_09 = 180;
    static constexpr float PI09      = 3.14159265f;
    for (int frame = 0; frame < FRAMES_09; ++frame) {
        float phase = frame * 0.18f;
        for (int y = 0; y < 224; ++y) {
            float angle = y * 2.0f * PI09 / 64.0f + phase;
            scrollA[y]  = static_cast<int16_t>(static_cast<int>(16.0f * sinf(angle)));
            scrollB[y]  = 0;
        }
        setHScrollPerScanline(scrollA, scrollB, 224);
        waitVBlank();
    }

    vdp().dumpFrameBufferToPNG("vdp_09_hscroll_scanline.png", true);
    vdp().dumpEverythingToPNG("vdp_09_hscroll_scanline_full.png", true);
    printf("[VISUAL] vdp_09_hscroll_scanline.png — wavy sine-wave distortion (final frame).\n");
}
