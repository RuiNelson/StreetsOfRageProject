/**
 * @file cpu68k_test.cpp
 * @brief Unit tests for M68KMacros.hpp (68000 semantics used by the recompiler).
 *
 * Build & run:
 *
 *   clang++ -std=c++23 -I src -I tools/recompiler tests/cpu68k_test.cpp -o /tmp/cpu68k_test && /tmp/cpu68k_test
 */

#include "system/cpu/CPU68K.hpp"

#include <cassert>
#include <cstdio>

namespace {

CPU68K g_cpu{};

CPU68K &cpu() { return g_cpu; }

struct StubMemory {
    m_byte readByte(m_long) { return 0; }
    m_word readWord(m_long) { return 0; }
    m_long readLong(m_long) { return 0; }
    void writeByte(m_long, m_byte) {}
    void writeWord(m_long, m_word) {}
    void writeLong(m_long, m_long) {}
};

StubMemory g_mem;

StubMemory &memory() { return g_mem; }

int irqLevel() { return 0; }
void serviceIRQ() {}
void pace() {}

} // namespace

#include "M68KMacros.hpp"

namespace {

void resetCpu() {
    g_cpu = CPU68K{};
    g_cpu.sr = 0x2700;
}

void setCVZN(bool c, bool v, bool z, bool n) {
    M68K_SET_FLAG_C(c);
    M68K_SET_FLAG_V(v);
    M68K_SET_FLAG_Z(z);
    M68K_SET_FLAG_N(n);
}

CPU68K cpuWithCCR(bool c, bool v, bool z, bool n, bool x) {
    resetCpu();
    setCVZN(c, v, z, n);
    M68K_SET_FLAG_X(x);
    return g_cpu;
}

void testMoveFlags() {
    resetCpu();

    M68K_SET_FLAG_V(true);
    M68K_SET_FLAG_C(true);
    M68K_SET_FLAG_X(true);

    m_byte rb = 0x80;
    M68K_MOVE_B(rb);
    assert(M68K_FLAG_N && !M68K_FLAG_Z);
    assert(!M68K_FLAG_V && !M68K_FLAG_C);
    assert(M68K_FLAG_X);

    m_word rw = 0x0000;
    M68K_TST_W(rw);
    assert(!M68K_FLAG_N && M68K_FLAG_Z && !M68K_FLAG_V && !M68K_FLAG_C);

    m_long rl = 0x80000000u;
    M68K_MOVE_L(rl);
    assert(M68K_FLAG_N && !M68K_FLAG_Z && !M68K_FLAG_V && !M68K_FLAG_C);
    assert(M68K_FLAG_X);
}

void testAdd() {
    resetCpu();

    m_byte rb = 0x80;
    M68K_ADD_B(rb, 0x80);
    assert(rb == 0x00);
    assert(M68K_FLAG_C && M68K_FLAG_X && M68K_FLAG_V && M68K_FLAG_Z && !M68K_FLAG_N);

    rb = 0xFF;
    M68K_ADD_B(rb, 0x01);
    assert(rb == 0x00);
    assert(M68K_FLAG_C && M68K_FLAG_X && !M68K_FLAG_V && M68K_FLAG_Z);

    rb = 0x7F;
    M68K_ADD_B(rb, 0x01);
    assert(rb == 0x80);
    assert(!M68K_FLAG_C && !M68K_FLAG_X && M68K_FLAG_V && M68K_FLAG_N && !M68K_FLAG_Z);

    m_word rw = 0x8000;
    M68K_ADD_W(rw, 0x8000);
    assert(rw == 0x0000);
    assert(M68K_FLAG_C && M68K_FLAG_X && M68K_FLAG_V && M68K_FLAG_Z);

    rw = 0x7FFF;
    M68K_ADD_W(rw, 0x0001);
    assert(rw == 0x8000);
    assert(!M68K_FLAG_C && M68K_FLAG_V && M68K_FLAG_N);

    m_long rl = 0x80000000u;
    M68K_ADD_L(rl, 0x80000000u);
    assert(rl == 0x00000000u);
    assert(M68K_FLAG_C && M68K_FLAG_X && M68K_FLAG_V && M68K_FLAG_Z);

    rl = 0x7FFFFFFFu;
    M68K_ADD_L(rl, 0x00000001u);
    assert(rl == 0x80000000u);
    assert(!M68K_FLAG_C && M68K_FLAG_V && M68K_FLAG_N);

    rl = 2;
    M68K_ADD_L(rl, 3);
    assert(rl == 5);
    assert(!M68K_FLAG_C && !M68K_FLAG_V && !M68K_FLAG_Z && !M68K_FLAG_N);
}

void testSub() {
    resetCpu();

    m_byte rb = 0x00;
    M68K_SUB_B(rb, 0x01);
    assert(rb == 0xFF);
    assert(M68K_FLAG_C && M68K_FLAG_X && !M68K_FLAG_V && M68K_FLAG_N && !M68K_FLAG_Z);

    rb = 0x80;
    M68K_SUB_B(rb, 0x01);
    assert(rb == 0x7F);
    assert(!M68K_FLAG_C && M68K_FLAG_V && !M68K_FLAG_N);

    rb = 0x42;
    M68K_SUB_B(rb, 0x42);
    assert(rb == 0x00);
    assert(!M68K_FLAG_C && M68K_FLAG_Z && !M68K_FLAG_V);

    m_word rw = 0x0000;
    M68K_SUB_W(rw, 0x0001);
    assert(rw == 0xFFFF);
    assert(M68K_FLAG_C && M68K_FLAG_X && M68K_FLAG_N);

    rw = 0x8000;
    M68K_SUB_W(rw, 0x0001);
    assert(rw == 0x7FFF);
    assert(!M68K_FLAG_C && M68K_FLAG_V && !M68K_FLAG_N);

    m_long rl = 0x00000000u;
    M68K_SUB_L(rl, 0x00000001u);
    assert(rl == 0xFFFFFFFFu);
    assert(M68K_FLAG_C && M68K_FLAG_X && M68K_FLAG_N);

    rl = 0x80000000u;
    M68K_SUB_L(rl, 0x00000001u);
    assert(rl == 0x7FFFFFFFu);
    assert(!M68K_FLAG_C && M68K_FLAG_V && !M68K_FLAG_N);
}

void testCmpDoesNotTouchX() {
    resetCpu();

    M68K_SET_FLAG_X(true);
    M68K_CMP_B(0x00, 0x01);
    assert(M68K_FLAG_C && M68K_FLAG_N);
    assert(M68K_FLAG_X);

    M68K_SET_FLAG_X(false);
    M68K_CMP_B(0x00, 0x01);
    assert(M68K_FLAG_C);
    assert(!M68K_FLAG_X);

    M68K_SET_FLAG_X(true);
    M68K_CMP_W(0x8000, 0x0001);
    assert(M68K_FLAG_V && !M68K_FLAG_N && M68K_FLAG_X);

    M68K_SET_FLAG_X(false);
    M68K_CMP_L(0x42, 0x42);
    assert(M68K_FLAG_Z && !M68K_FLAG_C && !M68K_FLAG_X);
}

void testConditions() {
    {
        g_cpu = cpuWithCCR(false, false, false, false, false);
        assert(M68K_TEST_CC(12));
        assert(!M68K_TEST_CC(13));
        assert(M68K_TEST_CC(14));
        assert(!M68K_TEST_CC(15));
    }
    {
        g_cpu = cpuWithCCR(false, false, false, true, false);
        assert(!M68K_TEST_CC(12));
        assert(M68K_TEST_CC(13));
        assert(!M68K_TEST_CC(14));
        assert(M68K_TEST_CC(15));
    }
    {
        g_cpu = cpuWithCCR(false, true, false, true, false);
        assert(M68K_TEST_CC(12));
        assert(!M68K_TEST_CC(13));
        assert(M68K_TEST_CC(14));
        assert(!M68K_TEST_CC(15));
    }
    {
        g_cpu = cpuWithCCR(false, false, true, false, false);
        assert(M68K_TEST_CC(12));
        assert(!M68K_TEST_CC(14));
        assert(M68K_TEST_CC(15));
    }
    {
        g_cpu = cpuWithCCR(false, false, false, false, false);
        assert(M68K_TEST_CC(0));
        assert(!M68K_TEST_CC(1));
    }
    {
        g_cpu = cpuWithCCR(false, false, false, false, false);
        assert(M68K_TEST_CC(2));
        assert(!M68K_TEST_CC(3));
        assert(M68K_TEST_CC(4));
        assert(!M68K_TEST_CC(5));
        assert(M68K_TEST_CC(6));
        assert(!M68K_TEST_CC(7));
        assert(M68K_TEST_CC(8));
        assert(!M68K_TEST_CC(9));
        assert(M68K_TEST_CC(10));
        assert(!M68K_TEST_CC(11));
    }
    {
        g_cpu = cpuWithCCR(true, true, true, true, false);
        assert(!M68K_TEST_CC(2));
        assert(M68K_TEST_CC(3));
        assert(!M68K_TEST_CC(4));
        assert(M68K_TEST_CC(5));
        assert(!M68K_TEST_CC(6));
        assert(M68K_TEST_CC(7));
        assert(!M68K_TEST_CC(8));
        assert(M68K_TEST_CC(9));
        assert(!M68K_TEST_CC(10));
        assert(M68K_TEST_CC(11));
    }
}

void testDbcc() {
    resetCpu();

    g_cpu.d[0] = 0xAAAA0002u;
    assert(M68K_DBCC_DEC(1, 0) == true);
    assert(static_cast<m_word>(g_cpu.d[0] & 0xFFFFu) == 1);
    assert(M68K_DBCC_DEC(1, 0) == true);
    assert(static_cast<m_word>(g_cpu.d[0] & 0xFFFFu) == 0);
    assert(M68K_DBCC_DEC(1, 0) == false);
    assert(static_cast<m_word>(g_cpu.d[0] & 0xFFFFu) == 0xFFFF);
    assert((g_cpu.d[0] & 0xFFFF0000u) == 0xAAAA0000u);

    g_cpu.d[1] = 0x00000000u;
    assert(M68K_DBCC_DEC(1, 1) == false);
    assert(static_cast<m_word>(g_cpu.d[1] & 0xFFFFu) == 0xFFFF);

    g_cpu.d[2] = 0x00000005u;
    setCVZN(false, false, true, false);
    assert(M68K_DBCC_DEC(7, 2) == false);
    assert(static_cast<m_word>(g_cpu.d[2] & 0xFFFFu) == 5);

    setCVZN(false, false, false, false);
    assert(M68K_DBCC_DEC(7, 2) == true);
    assert(static_cast<m_word>(g_cpu.d[2] & 0xFFFFu) == 4);

    g_cpu.d[3] = 0x00000003u;
    setCVZN(true, true, false, true);
    M68K_SET_FLAG_X(true);
    m_word before = static_cast<m_word>(g_cpu.sr & 0x001F);
    M68K_DBCC_DEC(1, 3);
    m_word after = static_cast<m_word>(g_cpu.sr & 0x001F);
    assert(before == after);
}

void testShifts() {
    resetCpu();

    m_byte rb = 0x81;
    M68K_LSL_B(rb, 1);
    assert(rb == 0x02);
    assert(M68K_FLAG_C && M68K_FLAG_X);

    rb = 0x01;
    M68K_LSR_B(rb, 1);
    assert(rb == 0x00);
    assert(M68K_FLAG_C && M68K_FLAG_Z);

    rb = 0x80;
    M68K_ASR_B(rb, 1);
    assert(rb == 0xC0);
    assert(M68K_FLAG_N);

    rb = 0x40;
    M68K_ASL_B(rb, 1);
    assert(M68K_FLAG_V);

    M68K_SET_FLAG_C(true);
    rb = 0x12;
    M68K_LSL_B(rb, 0);
    assert(rb == 0x12);
    assert(!M68K_FLAG_C);

    g_cpu.d[0] = 0;
    assert(M68K_REG_SHIFT_COUNT(0, 8) == 8);
    assert(M68K_REG_SHIFT_COUNT(0, 16) == 16);
    g_cpu.d[0] = 5;
    assert(M68K_REG_SHIFT_COUNT(0, 16) == 5);
    g_cpu.d[0] = 64;
    assert(M68K_REG_SHIFT_COUNT(0, 16) == 16);
}

void testRotatesAndMul() {
    resetCpu();

    m_byte rb = 0x81;
    M68K_ROL_B(rb, 1);
    assert(rb == 0x03);
    assert(M68K_FLAG_C);

    rb = 0x01;
    M68K_ROR_B(rb, 1);
    assert(rb == 0x80);
    assert(M68K_FLAG_C);

    M68K_SET_FLAG_X(true);
    rb = 0x00;
    M68K_ROXL_B(rb, 1);
    assert(rb == 0x01);
    assert(!M68K_FLAG_X);

    m_long prod = M68K_MULU(0x8000, 0x0002);
    assert(prod == 0x00010000u);
    assert(!M68K_FLAG_Z && !M68K_FLAG_N && !M68K_FLAG_V && !M68K_FLAG_C);

    prod = M68K_MULS(0xFFFF, 0xFFFF);
    assert(prod == 0x00000001u);

    m_long div = M68K_DIVU(100, 7);
    assert(div == ((2u << 16) | 14u));
}

void testBcdAndNegx() {
    resetCpu();

    M68K_SET_FLAG_X(false);
    m_byte rb = 0x25;
    M68K_ABCD(rb, 0x37);
    assert(rb == 0x62);
    assert(!M68K_FLAG_C);

    M68K_SET_FLAG_X(false);
    rb = 0x50;
    M68K_ABCD(rb, 0x55);
    assert(rb == 0x05);
    assert(M68K_FLAG_C);

    M68K_SET_FLAG_X(false);
    rb = 0x42;
    M68K_SBCD(rb, 0x13);
    assert(rb == 0x29);
    assert(!M68K_FLAG_C);

    M68K_SET_FLAG_Z(true);
    M68K_SET_FLAG_X(false);
    rb = 0x01;
    M68K_ABCD(rb, 0x01);
    assert(!M68K_FLAG_Z);

    M68K_SET_FLAG_X(false);
    rb = 0x01;
    M68K_NEGX_B(rb);
    assert(rb == 0xFF);
    assert(M68K_FLAG_C && M68K_FLAG_X);
}

} // namespace

int main() {
    testMoveFlags();
    testAdd();
    testSub();
    testCmpDoesNotTouchX();
    testConditions();
    testDbcc();
    testShifts();
    testRotatesAndMul();
    testBcdAndNegx();

    std::printf("All M68K macro tests passed.\n");
    return 0;
}
