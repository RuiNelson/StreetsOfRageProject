/**
 * @file TestVDPRunner.cpp
 * @brief VDP test runner — cartridge entry point (runs on the CPU thread).
 *
 * The SDL event pump and the CPU thread are provided by
 * MegaDriveEnvironment::boot(); this just sequences the test cases.
 */

#include "TestVDP.hpp"
#include <cstdio>

// ─── Entry point ─────────────────────────────────────────────────────────────

void VDPTester::run() {
    printf("=== VDP Test Suite ===\n");

    testRegisters();
    testBackgroundColor();
    testCRAMPalette();
    testVRAMFill();
    testFontPlaneA();
    testPlaneBBackground();
    testTwoPlanes();
    testHScrollFullScreen();
    testHScrollPerScanline();
    testVScrollFullScreen();
    testSprites();
    testSpriteMasking();
    testWindowHUD();
    testPlaneSize64x64();
    testFullScene();
    testAnimated();
    testSpriteCollision();
    testRasterHSync();

    printf("\n=== VDP tests complete — check PNG output files. ===\n");
}
