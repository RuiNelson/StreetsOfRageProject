/**
 * @file TestVDPTest02.cpp
 * @brief Test 02 — background colour register ($07).
 */

#include "TestVDP.hpp"
#include <cstdio>

void VDPTester::testBackgroundColor() {
    printf("\n[TEST 02] background color\n");
    initVDP();
    clearPlaneA();
    clearPlaneB();
    clearSAT();

    static constexpr uint16_t pal[] = {0x0000, 0x000E};
    loadCRAMPalette(0, pal, 2);

    writeReg(0x07, (0 << 4) | 1); // bg = palette 0, entry 1

    renderAndDump("vdp_02_bgcolor", true);
    printf("[VISUAL] vdp_02_bgcolor.png — expect solid red screen.\n");
}
