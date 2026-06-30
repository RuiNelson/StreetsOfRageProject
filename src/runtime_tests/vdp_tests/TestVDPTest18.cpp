/**
 * @file TestVDPTest18.cpp
 * @brief Test 18 — raster HSync: per-scanline wavy HScroll animated via hSync callback.
 *
 * Demonstrates hardware-accurate HBlank interrupt gating:
 *   reg $00 bit 4 = 1 → HINT enabled
 *   reg $0A       = 0 → fires every scanline
 *   reg $0B       = 3 → per-scanline HScroll mode
 *
 * hSync(line) writes hSyncScrollA_[line] to the HScroll VRAM table each frame.
 * The main loop advances the sine-wave phase each VBlank, producing an animated wave.
 */

#include "TestVDP.hpp"
#include <cmath>
#include <cstdio>

// ── hSync callback ────────────────────────────────────────────────────────────

/// Called on the run() thread once per enabled scanline via runVDPInterrupts().
/// Writes the per-scanline HScroll value for Plane A to VRAM.
void VDPTester::hSync(int line) {
    if (line < 0 || line >= VDPState::SCREEN_H) {
        return;
    }
    uint16_t addr = static_cast<uint16_t>(VRAM_HSCROLL + line * 4);
    vdp().writeControlPort(makeWord1(CD_VRAM_W, addr));
    vdp().writeControlPort(makeWord2(CD_VRAM_W, addr));
    vdp().writeDataPort(static_cast<uint16_t>(hSyncScrollA_[line]));
}

// ── Test case ─────────────────────────────────────────────────────────────────

void VDPTester::testRasterHSync() {
    printf("\n[TEST 18] raster HSync — per-scanline wavy HScroll\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    static const uint16_t pal0[16] = {
        0x0000,
        0x0EEE,
        0x0EE0,
        0x00EE,
        0x0E0E,
        0x0E00,
        0x00E0,
        0x000E,
        0x0888,
        0x0AAA,
        0x0CCC,
        0x0CEE,
        0x0ECE,
        0x0EEC,
        0x0E80,
        0x080E,
    };
    loadCRAMPalette(0, pal0, 16);
    writeReg(0x07, 0x00); // bg: palette 0, index 0 (black)

    loadFontTiles(1, 0);

    // Fill every row of Plane A with repeating text so the wave is clearly visible.
    for (int row = 0; row < SCREEN_H_CELLS; ++row) {
        writeText(VRAM_PLANEA, 0, row, PLANE_W_CELLS, "STREETS OF RAGE  ", 0, false);
    }

    // Enable HBlank IRQ every scanline, and per-scanline HScroll.
    writeReg(0x00, 0x10); // Mode 1: HINT enable
    writeReg(0x0A, 0x00); // HINT counter = 0 → fires every line
    writeReg(0x0B, 0x03); // Mode 3: per-scanline HScroll, full-screen VScroll

    // Compute initial sine wave into hSyncScrollA_[].
    constexpr float kAmplitude  = 20.0f;
    constexpr float kWaves      = 2.0f; // 2 full waves across 224 lines
    constexpr float k2Pi        = 2.0f * static_cast<float>(M_PI);
    auto            computeWave = [&](float phase) {
        for (int y = 0; y < VDPState::SCREEN_H; ++y) {
            float angle      = phase + kWaves * k2Pi * y / VDPState::SCREEN_H;
            hSyncScrollA_[y] = static_cast<int16_t>(kAmplitude * std::sin(angle));
        }
    };

    computeWave(0.0f);

    // Write initial HScroll values to VRAM so the very first rendered frame has the wave.
    int16_t scrollBZero[VDPState::SCREEN_H] = {};
    setHScrollPerScanline(hSyncScrollA_, scrollBZero, VDPState::SCREEN_H);

    // Animate ~60 frames: each VBlank, advance the phase; hSync() writes the new
    // values to VRAM per-scanline so the render thread picks them up next frame.
    constexpr int   kFrames    = 60;
    constexpr float kPhaseStep = k2Pi / kFrames;
    float           phase      = 0.0f;
    for (int f = 0; f < kFrames; ++f) {
        waitVBlank();
        phase += kPhaseStep;
        computeWave(phase);
    }

    renderAndDump("vdp_18_raster_hsync");
    printf("[VISUAL] vdp_18_raster_hsync.png — expect text rows with wavy horizontal scroll.\n");
}
