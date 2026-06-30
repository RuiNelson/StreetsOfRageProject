// Unit tests for tools/recompiler/M68KMacros.hpp — the per-opcode ALU/flag
// semantics that DESIGN.md §2b calls "the highest-risk surface" and §7 says
// must be unit-tested in isolation. test_codegen.py (the Python side) only
// asserts which macro name + operand shape the generator emits; it never
// compiles or executes a macro, so a wrong macro body (e.g. NEG computing
// r-0 instead of 0-r) is invisible to it. This file drives each macro with
// concrete values and checks both the result and the CCR flags against the
// real 68000's documented behaviour.
//
// Standalone, no test framework dependency (none is used elsewhere in the
// project). Build and run:
//   g++ -std=c++23 -I src -I src/system/cpu \
//       tools/recompiler/tests/test_m68k_macros.cpp -o /tmp/test_m68k_macros \
//       && /tmp/test_m68k_macros
// or: tools/recompiler/tests/run_macro_tests.sh

#include "CPU68K.hpp"
#include "M68KMacros.hpp"

#include <cstdio>
#include <cstdlib>

namespace {

int g_checks   = 0;
int g_failures = 0;

void report(bool ok, const char *expr, const char *file, int line) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, expr);
    }
}

} // namespace

#define CHECK(expr) report(static_cast<bool>(expr), #expr, __FILE__, __LINE__)

// M68KMacros.hpp expects an unqualified cpu() in scope (exactly how generated
// Sor:: methods call it). Only cpu() is needed for the ALU/flag macros under
// test here — memory()/irqLevel()/serviceIRQ()/pace() back RTS/RTE/M68K_STEP,
// control-flow macros that are out of scope for this file.
CPU68K g_cpu{};
CPU68K &cpu() { return g_cpu; }

namespace {

void reset() { g_cpu = CPU68K{}; }

void test_add() {
    reset();
    m_byte b = 0x7F;
    M68K_ADD_B(b, static_cast<m_byte>(1));
    CHECK(b == 0x80);
    CHECK(M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(M68K_FLAG_V); CHECK(!M68K_FLAG_C); CHECK(!M68K_FLAG_X);

    m_byte b2 = 0xFF;
    M68K_ADD_B(b2, static_cast<m_byte>(1));
    CHECK(b2 == 0x00);
    CHECK(!M68K_FLAG_N); CHECK(M68K_FLAG_Z); CHECK(!M68K_FLAG_V); CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X);

    m_long l = 1;
    M68K_ADD_L(l, static_cast<m_long>(1));
    CHECK(l == 2);
    CHECK(!M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(!M68K_FLAG_V); CHECK(!M68K_FLAG_C);
}

void test_sub_and_cmp() {
    reset();
    m_byte b = 0x80;
    M68K_SUB_B(b, static_cast<m_byte>(1));
    CHECK(b == 0x7F);
    CHECK(!M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(M68K_FLAG_V); CHECK(!M68K_FLAG_C); CHECK(!M68K_FLAG_X);

    m_byte b2 = 0;
    M68K_SUB_B(b2, static_cast<m_byte>(1));
    CHECK(b2 == 0xFF);
    CHECK(M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(!M68K_FLAG_V); CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X);

    // CMP must not touch X (it preserves whatever X already was).
    M68K_SET_FLAG_X(true);
    m_word w = 5;
    M68K_CMP_W(w, static_cast<m_word>(5));
    CHECK(w == 5); // CMP never writes its destination operand
    CHECK(M68K_FLAG_Z);
    CHECK(M68K_FLAG_X); // unchanged, still set from before
    M68K_SET_FLAG_X(false);
    M68K_CMP_W(w, static_cast<m_word>(5));
    CHECK(!M68K_FLAG_X); // unchanged, still clear from before
}

void test_neg() {
    // Regression test: M68K_NEG_B/W/L previously computed (r - 0) instead of
    // (0 - r) — a silent no-op on the value. 122 call sites in Sor.cpp.
    reset();
    m_byte b = 5;
    M68K_NEG_B(b);
    CHECK(b == static_cast<m_byte>(-5));
    CHECK(M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(!M68K_FLAG_V); CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X);

    m_byte zero = 0;
    M68K_NEG_B(zero);
    CHECK(zero == 0);
    CHECK(!M68K_FLAG_N); CHECK(M68K_FLAG_Z); CHECK(!M68K_FLAG_V); CHECK(!M68K_FLAG_C); CHECK(!M68K_FLAG_X);

    // Negating the most-negative byte overflows (can't represent +128 signed).
    m_byte minneg = 0x80;
    M68K_NEG_B(minneg);
    CHECK(minneg == 0x80);
    CHECK(M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(M68K_FLAG_V); CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X);

    m_word w = 1234;
    M68K_NEG_W(w);
    CHECK(w == static_cast<m_word>(-1234));

    m_long l = 0xDEAD;
    M68K_NEG_L(l);
    CHECK(l == static_cast<m_long>(-0xDEAD));
}

void test_negx() {
    reset();
    M68K_SET_FLAG_X(false);
    m_byte b = 5;
    M68K_NEGX_B(b);
    CHECK(b == static_cast<m_byte>(-5));
    CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X);

    M68K_SET_FLAG_X(true);
    m_byte b2 = 5;
    M68K_NEGX_B(b2);
    CHECK(b2 == static_cast<m_byte>(-6)); // 0 - 5 - 1(X)
}

void test_not_and_logic() {
    reset();
    m_byte b = 0x0F;
    M68K_NOT_B(b);
    CHECK(b == 0xF0);
    CHECK(M68K_FLAG_N); CHECK(!M68K_FLAG_Z); CHECK(!M68K_FLAG_V); CHECK(!M68K_FLAG_C);

    m_word w = 0xFF00;
    M68K_AND_W(w, static_cast<m_word>(0x0FF0));
    CHECK(w == 0x0F00);
    CHECK(!M68K_FLAG_V); CHECK(!M68K_FLAG_C);

    m_word w2 = 0;
    M68K_OR_W(w2, static_cast<m_word>(0));
    CHECK(w2 == 0);
    CHECK(M68K_FLAG_Z);

    m_byte b2 = 0xAA;
    M68K_EOR_B(b2, static_cast<m_byte>(0xFF));
    CHECK(b2 == 0x55);
}

void test_clr_and_tst() {
    reset();
    m_long l = 0xDEADBEEFu;
    M68K_CLR_L(l);
    CHECK(l == 0);
    CHECK(M68K_FLAG_Z); CHECK(!M68K_FLAG_N); CHECK(!M68K_FLAG_V); CHECK(!M68K_FLAG_C);

    m_byte b = 0x80;
    M68K_TST_B(b);
    CHECK(b == 0x80); // TST never writes
    CHECK(M68K_FLAG_N); CHECK(!M68K_FLAG_Z);
}

void test_ext_and_swap() {
    reset();
    cpu().d[0] = 0xAAAA00FFu; // low byte 0xFF should sign-extend negative
    M68K_EXT_W(0);
    CHECK((cpu().d[0] & 0xFFFFFFFFu) == 0xAAAAFFFFu); // high word untouched, low word sign-extended
    CHECK(M68K_FLAG_N);

    cpu().d[1] = 0x0000007Fu;
    M68K_EXT_L(1);
    CHECK(cpu().d[1] == 0x0000007Fu);
    CHECK(!M68K_FLAG_N);

    m_long l = 0x12345678u;
    M68K_SWAP(l);
    CHECK(l == 0x56781234u);
}

void test_shifts_logical() {
    reset();
    // LSL: bit shifted out of bit7 becomes C and X; logical shifts never set V.
    m_byte b = 0x80;
    M68K_LSL_B(b, 1);
    CHECK(b == 0x00);
    CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X); CHECK(M68K_FLAG_Z); CHECK(!M68K_FLAG_V);

    // Zero count: C cleared, X preserved from before the shift.
    M68K_SET_FLAG_X(true);
    m_byte b2 = 0x42;
    M68K_LSL_B(b2, 0);
    CHECK(b2 == 0x42);
    CHECK(!M68K_FLAG_C);
    CHECK(M68K_FLAG_X); // preserved, not cleared

    m_byte b3 = 0x01;
    M68K_LSR_B(b3, 1);
    CHECK(b3 == 0x00);
    CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_Z);
}

void test_shifts_arithmetic() {
    reset();
    // ASR replicates the sign bit.
    m_byte b = static_cast<m_byte>(-4); // 0xFC
    M68K_ASR_B(b, 1);
    CHECK(b == static_cast<m_byte>(-2));
    CHECK(M68K_FLAG_N);

    // ASL sets V if the sign bit changes at any point during the shift.
    m_byte b2 = 0x40; // 0100_0000 -> shifting left changes sign bit
    M68K_ASL_B(b2, 1);
    CHECK(b2 == 0x80);
    CHECK(M68K_FLAG_V);

    m_byte b3 = 0x01;
    M68K_ASL_B(b3, 1); // 0x01 -> 0x02, sign bit (0) unchanged throughout
    CHECK(b3 == 0x02);
    CHECK(!M68K_FLAG_V);
}

void test_rotates_dont_touch_x() {
    // Regression test: M68K_ROL/ROR previously mirrored C into X on every
    // non-zero count. Real 68000 ROL/ROR never touch X (only ROXL/ROXR do).
    reset();
    M68K_SET_FLAG_X(false);
    m_byte b = 0x80;
    M68K_ROL_B(b, 1); // bit7 (1) rotates into bit0 and into C
    CHECK(b == 0x01);
    CHECK(M68K_FLAG_C);
    CHECK(!M68K_FLAG_X); // must remain unchanged, not mirror C

    M68K_SET_FLAG_X(true);
    m_byte b2 = 0x01;
    M68K_ROR_B(b2, 1);
    CHECK(b2 == 0x80);
    CHECK(M68K_FLAG_C);
    CHECK(M68K_FLAG_X); // still true from before — untouched by ROR

    m_word w = 0x0001;
    M68K_ROR_W(w, 1);
    CHECK(w == 0x8000);
    CHECK(M68K_FLAG_C);
    CHECK(M68K_FLAG_X); // still true — ROR_W must not touch it either
}

void test_roxl_roxr_do_use_x() {
    // ROXL/ROXR are the "extended" rotates and correctly chain through X.
    reset();
    M68K_SET_FLAG_X(true);
    m_byte b = 0x00;
    M68K_ROXL_B(b, 1); // X (1) rotates into bit0
    CHECK(b == 0x01);
    CHECK(!M68K_FLAG_X); // the bit rotated out (0) becomes the new X

    M68K_SET_FLAG_X(false);
    m_byte b2 = 0x01;
    M68K_ROXR_B(b2, 1); // old bit0 (1) rotates out and becomes new X; old X (0) rotates into bit7
    CHECK(b2 == 0x00);
    CHECK(M68K_FLAG_X);
}

void test_bitops() {
    reset();
    m_long l = 0;
    M68K_BTST(l, 3);
    CHECK(M68K_FLAG_Z); // bit 3 clear

    m_long l2 = 0;
    M68K_BSET(l2, 3);
    CHECK(l2 == 0x08);
    CHECK(M68K_FLAG_Z); // tested before the set: bit was clear

    M68K_BSET(l2, 3); // setting an already-set bit: Z reflects pre-set state
    CHECK(l2 == 0x08);
    CHECK(!M68K_FLAG_Z);

    m_long l3 = 0x08;
    M68K_BCLR(l3, 3);
    CHECK(l3 == 0);
    CHECK(!M68K_FLAG_Z);

    m_long l4 = 0x08;
    M68K_BCHG(l4, 3);
    CHECK(l4 == 0);
    M68K_BCHG(l4, 3);
    CHECK(l4 == 0x08);
}

void test_scc() {
    reset();
    M68K_SET_FLAG_Z(true);
    m_byte b = 0;
    M68K_SCC(b, 7); // seq
    CHECK(b == 0xFF);
    M68K_SET_FLAG_Z(false);
    m_byte b2 = 0;
    M68K_SCC(b2, 7);
    CHECK(b2 == 0x00);
}

void test_exg_and_movea() {
    reset();
    cpu().d[0] = 1;
    cpu().a[1] = 2;
    M68K_EXG(cpu().d[0], cpu().a[1]);
    CHECK(cpu().d[0] == 2);
    CHECK(cpu().a[1] == 1);

    M68K_MOVEA_W(cpu().a[2], static_cast<m_word>(0xFFFF)); // -1, sign-extends
    CHECK(cpu().a[2] == 0xFFFFFFFFu);

    // ADDA never touches CCR.
    cpu().sr = 0x001Fu; // all flags set
    M68K_ADDA_L(cpu().a[3], static_cast<m_long>(5));
    CHECK(cpu().sr == 0x001Fu); // unchanged
}

void test_mul_div() {
    reset();
    m_long r = M68K_MULU(static_cast<m_word>(0xFFFF), static_cast<m_word>(2));
    CHECK(r == 0x1FFFEu);
    CHECK(!M68K_FLAG_N); CHECK(!M68K_FLAG_V); CHECK(!M68K_FLAG_C);

    m_long r2 = M68K_MULS(static_cast<m_word>(static_cast<m_word>(-1)), static_cast<m_word>(2));
    CHECK(r2 == 0xFFFFFFFEu); // -1 * 2 = -2
    CHECK(M68K_FLAG_N);

    m_long r3 = M68K_DIVU(static_cast<m_long>(10), static_cast<m_word>(3));
    CHECK((r3 & 0xFFFFu) == 3);   // quotient
    CHECK((r3 >> 16) == 1);       // remainder
    CHECK(!M68K_FLAG_V);

    m_long r4 = M68K_DIVS(static_cast<m_long>(static_cast<int32_t>(-7)), static_cast<m_word>(2));
    CHECK(static_cast<int16_t>(r4 & 0xFFFFu) == -3);  // truncates toward zero
    CHECK(static_cast<int16_t>(r4 >> 16) == -1);
}

void test_bcd() {
    reset();
    M68K_SET_FLAG_X(false);
    m_byte a = 0x09, b = 0x01;
    M68K_ABCD(a, b);
    CHECK(a == 0x10); // 9 + 1 = 10 in BCD
    CHECK(!M68K_FLAG_C);

    m_byte a2 = 0x59, b2 = 0x99;
    M68K_SET_FLAG_X(false);
    M68K_ABCD(a2, b2);
    CHECK(a2 == 0x58); // 59 + 99 = 158 -> BCD low 2 digits 58, carry out
    CHECK(M68K_FLAG_C); CHECK(M68K_FLAG_X);

    m_byte c = 0x10, d = 0x01;
    M68K_SET_FLAG_X(false);
    M68K_SBCD(c, d);
    CHECK(c == 0x09); // 10 - 1 = 9
    CHECK(!M68K_FLAG_C);
}

} // namespace

int main() {
    test_add();
    test_sub_and_cmp();
    test_neg();
    test_negx();
    test_not_and_logic();
    test_clr_and_tst();
    test_ext_and_swap();
    test_shifts_logical();
    test_shifts_arithmetic();
    test_rotates_dont_touch_x();
    test_roxl_roxr_do_use_x();
    test_bitops();
    test_scc();
    test_exg_and_movea();
    test_mul_div();
    test_bcd();

    std::fprintf(stderr, "%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
