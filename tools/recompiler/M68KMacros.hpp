#pragma once

/**
 * @file M68KMacros.hpp
 * @brief Primitive 68000 operation macros for the recompiled cartridge.
 *
 * Each macro implements one instruction's ALU / flag semantics on values that
 * are already loaded into C++ temporaries. Register and memory access is emitted
 * as plain C++ by the recompiler (tools/recompiler/ea_codegen.py).
 *
 * Requires cpu(), memory(), irqLevel(), serviceIRQ(), pace() in scope.
 */

#include "data_types.hpp"
#include <cstdint>

/** Literal → 68000-sized value casts for generated code readability. */
#define BYTE(v) static_cast<m_byte>(v)
#define WORD(v) static_cast<m_word>(v)
#define LONG(v) static_cast<m_long>(v)

// =============================================================================
// CCR — condition-code register
// =============================================================================

/** Full 16-bit status register (system byte + CCR). */
#define M68K_SR (cpu().sr)

#define M68K_FLAG_C ((M68K_SR & 0x0001u) != 0)
#define M68K_FLAG_V ((M68K_SR & 0x0002u) != 0)
#define M68K_FLAG_Z ((M68K_SR & 0x0004u) != 0)
#define M68K_FLAG_N ((M68K_SR & 0x0008u) != 0)
#define M68K_FLAG_X ((M68K_SR & 0x0010u) != 0)

#define M68K_SET_FLAG_C(v) M68K_SR = static_cast<m_word>((M68K_SR & ~0x0001u) | ((v) ? 0x0001u : 0u))
#define M68K_SET_FLAG_V(v) M68K_SR = static_cast<m_word>((M68K_SR & ~0x0002u) | ((v) ? 0x0002u : 0u))
#define M68K_SET_FLAG_Z(v) M68K_SR = static_cast<m_word>((M68K_SR & ~0x0004u) | ((v) ? 0x0004u : 0u))
#define M68K_SET_FLAG_N(v) M68K_SR = static_cast<m_word>((M68K_SR & ~0x0008u) | ((v) ? 0x0008u : 0u))
#define M68K_SET_FLAG_X(v) M68K_SR = static_cast<m_word>((M68K_SR & ~0x0010u) | ((v) ? 0x0010u : 0u))

/** Interrupt priority mask (SR bits 10–8). */
#define M68K_INT_LEVEL() static_cast<int>((M68K_SR >> 8) & 0x07u)

// =============================================================================
// Branches — condition evaluation (control flow is plain C++ in the generator)
// =============================================================================

/** Evaluate a 68000 condition code (0=T … 15=LE). */
#define M68K_TEST_CC(cc) \
    ([&]() -> bool { \
        const bool C = M68K_FLAG_C, V = M68K_FLAG_V, Z = M68K_FLAG_Z, N = M68K_FLAG_N; \
        switch (cc) { \
        case 0:  return true; \
        case 1:  return false; \
        case 2:  return !C && !Z; \
        case 3:  return C || Z; \
        case 4:  return !C; \
        case 5:  return C; \
        case 6:  return !Z; \
        case 7:  return Z; \
        case 8:  return !V; \
        case 9:  return V; \
        case 10: return !N; \
        case 11: return N; \
        case 12: return N == V; \
        case 13: return N != V; \
        case 14: return !Z && (N == V); \
        case 15: return Z || (N != V); \
        default: return false; \
        } \
    }())

/** DBcc: decrement Dn word; branch while counter != −1 and cc false. */
#define M68K_DBCC_DEC(cc, n) \
    ([&]() -> bool { \
        if (M68K_TEST_CC(cc)) return false; \
        m_word c = static_cast<m_word>((static_cast<m_word>(cpu().d[n] & 0xFFFFu) - 1) & 0xFFFFu); \
        cpu().d[n] = static_cast<m_long>((cpu().d[n] & 0xFFFF0000u) | static_cast<m_long>(c)); \
        return c != 0xFFFFu; \
    }())

/** Shift/rotate count from Dn (low 6 bits); 0 → zeroMeans (8/16/32). */
#define M68K_REG_SHIFT_COUNT(reg, zeroMeans) \
    ([&]() -> int { \
        int r = static_cast<int>(cpu().d[reg] & 63); \
        return r != 0 ? r : static_cast<int>(zeroMeans); \
    }())

// =============================================================================
// CPU housekeeping
// =============================================================================

/** Poll VDP interrupts and advance emulation pacing. */
#define M68K_STEP() \
    do { \
        if (irqLevel() > M68K_INT_LEVEL()) serviceIRQ(); \
        pace(); \
    } while (0)

#define M68K_NOP() ((void)0)

#define M68K_RTS() \
    do { \
        cpu().ssp += 4; \
        if ((cpu().ssp & 0x00FFFFFFu) > 0x00FFFF00u) { \
            std::fprintf(stderr, "[RTS] ssp=$%06X fn=$%06X\n", \
                         static_cast<unsigned>(cpu().ssp & 0x00FFFFFFu), \
                         static_cast<unsigned>(lastFunction() & 0x00FFFFFFu)); \
        } \
        return; \
    } while (0)

#define M68K_RTE() \
    do { M68K_SR = memory().readWord(cpu().ssp); cpu().ssp += 6; return; } while (0)

#define M68K_RTR() \
    do { \
        M68K_SR = static_cast<m_word>((M68K_SR & 0xFF00u) | (memory().readWord(cpu().ssp) & 0x00FFu)); \
        cpu().ssp += 6; \
        return; \
    } while (0)

#define M68K_PUSH_RET(addr) \
    do { cpu().ssp -= 4; memory().writeLong(cpu().ssp, static_cast<m_long>(addr)); } while (0)

/** JSR/BSR with emulated-stack non-local return guard. */
#define M68K_JSR_GUARD(call, ret_pc, sp_var) \
    do { \
        m_long sp_var = cpu().ssp; \
        M68K_PUSH_RET(ret_pc); \
        call; \
        if ((cpu().ssp & 0x00FFFFFFu) > (sp_var & 0x00FFFFFFu)) return; \
    } while (0)

// =============================================================================
// Effective addresses — register / memory access (emitted by the recompiler)
// =============================================================================

#define M68K_AREG(n) ((n) == 7 ? cpu().ssp : cpu().a[n])

#define M68K_SIGNEXT_B(v) \
    static_cast<m_long>(static_cast<int32_t>(static_cast<int8_t>(static_cast<m_byte>(v))))
#define M68K_SIGNEXT_W(v) \
    static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(v))))

#define M68K_READ_D_B(n) static_cast<m_byte>(cpu().d[n] & 0xFFu)
#define M68K_READ_D_W(n) static_cast<m_word>(cpu().d[n] & 0xFFFFu)
#define M68K_READ_D_L(n) cpu().d[n]

#define M68K_WRITE_D_B(n, v) \
    do { cpu().d[n] = static_cast<m_long>((cpu().d[n] & 0xFFFFFF00u) | static_cast<m_long>(static_cast<m_byte>(v))); } while (0)
#define M68K_WRITE_D_W(n, v) \
    do { cpu().d[n] = static_cast<m_long>((cpu().d[n] & 0xFFFF0000u) | static_cast<m_long>(static_cast<m_word>(v))); } while (0)
#define M68K_WRITE_D_L(n, v) \
    do { cpu().d[n] = static_cast<m_long>(v); } while (0)

#define M68K_READ_A_B(n) static_cast<m_byte>(M68K_AREG(n) & 0xFFu)
#define M68K_READ_A_W(n) static_cast<m_word>(M68K_AREG(n) & 0xFFFFu)
#define M68K_READ_A_L(n) M68K_AREG(n)

#define M68K_WRITE_A_B(n, v) \
    do { \
        if ((n) == 7) \
            cpu().ssp = static_cast<m_long>((cpu().ssp & 0xFFFFFF00u) | static_cast<m_long>(static_cast<m_byte>(v))); \
        else \
            cpu().a[n] = static_cast<m_long>((cpu().a[n] & 0xFFFFFF00u) | static_cast<m_long>(static_cast<m_byte>(v))); \
    } while (0)
#define M68K_WRITE_A_W(n, v) \
    do { \
        m_long __se = static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(v)))); \
        if ((n) == 7) cpu().ssp = __se; else cpu().a[n] = __se; \
    } while (0)
#define M68K_WRITE_A_L(n, v) \
    do { if ((n) == 7) cpu().ssp = static_cast<m_long>(v); else cpu().a[n] = static_cast<m_long>(v); } while (0)

#define M68K_READ_MEM_B(a) memory().readByte(a)
#define M68K_READ_MEM_W(a) memory().readWord(a)
#define M68K_READ_MEM_L(a) memory().readLong(a)
#define M68K_WRITE_MEM_B(a, v) memory().writeByte(a, v)
#define M68K_WRITE_MEM_W(a, v) memory().writeWord(a, v)
#define M68K_WRITE_MEM_L(a, v) memory().writeLong(a, v)

#define M68K_INDEX_W(is_a, reg) \
    ((is_a) ? static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(M68K_AREG(reg) & 0xFFFFu))) \
            : static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(cpu().d[reg] & 0xFFFFu))))
#define M68K_INDEX_L(is_a, reg) ((is_a) ? M68K_AREG(reg) : cpu().d[reg])

#define M68K_ADDR_DISP(n, d) (M68K_AREG(n) + static_cast<m_long>(d))
#define M68K_ADDR_INDEX(n, d, is_a, idx) \
    (M68K_AREG(n) + static_cast<m_long>(d) + M68K_INDEX_W(is_a, idx))

#define M68K_STEP_A(n, bytes) \
    do { if ((n) == 7) cpu().ssp += (bytes); else cpu().a[n] += (bytes); } while (0)
#define M68K_STEP_A_SUB(n, bytes) \
    do { if ((n) == 7) cpu().ssp -= (bytes); else cpu().a[n] -= (bytes); } while (0)

#define M68K_READ_POSTINC_B(n) \
    ([&]() -> m_byte { m_byte __v = memory().readByte(M68K_AREG(n)); M68K_STEP_A(n, (n) == 7 ? 2 : 1); return __v; }())
#define M68K_READ_POSTINC_W(n) \
    ([&]() -> m_word { m_word __v = memory().readWord(M68K_AREG(n)); M68K_STEP_A(n, 2); return __v; }())
#define M68K_READ_POSTINC_L(n) \
    ([&]() -> m_long { m_long __v = memory().readLong(M68K_AREG(n)); M68K_STEP_A(n, 4); return __v; }())

#define M68K_READ_PREDEC_B(n) \
    ([&]() -> m_byte { M68K_STEP_A_SUB(n, (n) == 7 ? 2 : 1); return memory().readByte(M68K_AREG(n)); }())
#define M68K_READ_PREDEC_W(n) \
    ([&]() -> m_word { M68K_STEP_A_SUB(n, 2); return memory().readWord(M68K_AREG(n)); }())
#define M68K_READ_PREDEC_L(n) \
    ([&]() -> m_long { M68K_STEP_A_SUB(n, 4); return memory().readLong(M68K_AREG(n)); }())

#define M68K_WRITE_POSTINC_B(n, v) \
    do { memory().writeByte(M68K_AREG(n), v); M68K_STEP_A(n, (n) == 7 ? 2 : 1); } while (0)
#define M68K_WRITE_POSTINC_W(n, v) \
    do { memory().writeWord(M68K_AREG(n), v); M68K_STEP_A(n, 2); } while (0)
#define M68K_WRITE_POSTINC_L(n, v) \
    do { memory().writeLong(M68K_AREG(n), v); M68K_STEP_A(n, 4); } while (0)

#define M68K_WRITE_PREDEC_B(n, v) \
    do { M68K_STEP_A_SUB(n, (n) == 7 ? 2 : 1); memory().writeByte(M68K_AREG(n), v); } while (0)
#define M68K_WRITE_PREDEC_W(n, v) \
    do { M68K_STEP_A_SUB(n, 2); memory().writeWord(M68K_AREG(n), v); } while (0)
#define M68K_WRITE_PREDEC_L(n, v) \
    do { M68K_STEP_A_SUB(n, 4); memory().writeLong(M68K_AREG(n), v); } while (0)

#define M68K_RMW_D_B(n, OP, src) \
    do { m_byte __opd = M68K_READ_D_B(n); OP(__opd, src); M68K_WRITE_D_B(n, __opd); } while (0)
#define M68K_RMW_D_W(n, OP, src) \
    do { m_word __opd = M68K_READ_D_W(n); OP(__opd, src); M68K_WRITE_D_W(n, __opd); } while (0)
#define M68K_RMW_D_L(n, OP, src) \
    do { m_long __opd = M68K_READ_D_L(n); OP(__opd, src); M68K_WRITE_D_L(n, __opd); } while (0)

#define M68K_RMW_A_B(n, OP, src) \
    do { m_byte __opd = M68K_READ_A_B(n); OP(__opd, src); M68K_WRITE_A_B(n, __opd); } while (0)
#define M68K_RMW_A_W(n, OP, src) \
    do { m_word __opd = M68K_READ_A_W(n); OP(__opd, src); M68K_WRITE_A_W(n, __opd); } while (0)
#define M68K_RMW_A_L(n, OP, src) \
    do { m_long __opd = M68K_READ_A_L(n); OP(__opd, src); M68K_WRITE_A_L(n, __opd); } while (0)

#define M68K_RMW_MEM_B(addr, OP, src) \
    do { m_byte __opd = M68K_READ_MEM_B(addr); OP(__opd, src); M68K_WRITE_MEM_B(addr, __opd); } while (0)
#define M68K_RMW_MEM_W(addr, OP, src) \
    do { m_word __opd = M68K_READ_MEM_W(addr); OP(__opd, src); M68K_WRITE_MEM_W(addr, __opd); } while (0)
#define M68K_RMW_MEM_L(addr, OP, src) \
    do { m_long __opd = M68K_READ_MEM_L(addr); OP(__opd, src); M68K_WRITE_MEM_L(addr, __opd); } while (0)

#define M68K_RMW_POSTINC_B(n, OP, src) \
    do { \
        m_long __a = M68K_AREG(n); \
        m_byte __opd = memory().readByte(__a); \
        OP(__opd, src); \
        memory().writeByte(__a, __opd); \
        M68K_STEP_A(n, (n) == 7 ? 2 : 1); \
    } while (0)
#define M68K_RMW_POSTINC_W(n, OP, src) \
    do { \
        m_long __a = M68K_AREG(n); \
        m_word __opd = memory().readWord(__a); \
        OP(__opd, src); \
        memory().writeWord(__a, __opd); \
        M68K_STEP_A(n, 2); \
    } while (0)
#define M68K_RMW_POSTINC_L(n, OP, src) \
    do { \
        m_long __a = M68K_AREG(n); \
        m_long __opd = memory().readLong(__a); \
        OP(__opd, src); \
        memory().writeLong(__a, __opd); \
        M68K_STEP_A(n, 4); \
    } while (0)

#define M68K_RMW_PREDEC_B(n, OP, src) \
    do { \
        M68K_STEP_A_SUB(n, (n) == 7 ? 2 : 1); \
        m_long __a = M68K_AREG(n); \
        m_byte __opd = memory().readByte(__a); \
        OP(__opd, src); \
        memory().writeByte(__a, __opd); \
    } while (0)
#define M68K_RMW_PREDEC_W(n, OP, src) \
    do { \
        M68K_STEP_A_SUB(n, 2); \
        m_long __a = M68K_AREG(n); \
        m_word __opd = memory().readWord(__a); \
        OP(__opd, src); \
        memory().writeWord(__a, __opd); \
    } while (0)
#define M68K_RMW_PREDEC_L(n, OP, src) \
    do { \
        M68K_STEP_A_SUB(n, 4); \
        m_long __a = M68K_AREG(n); \
        m_long __opd = memory().readLong(__a); \
        OP(__opd, src); \
        memory().writeLong(__a, __opd); \
    } while (0)

#define M68K_RMW_D_B_UNARY(n, OP) \
    do { m_byte __opd = M68K_READ_D_B(n); OP(__opd); M68K_WRITE_D_B(n, __opd); } while (0)
#define M68K_RMW_D_W_UNARY(n, OP) \
    do { m_word __opd = M68K_READ_D_W(n); OP(__opd); M68K_WRITE_D_W(n, __opd); } while (0)
#define M68K_RMW_D_L_UNARY(n, OP) \
    do { m_long __opd = M68K_READ_D_L(n); OP(__opd); M68K_WRITE_D_L(n, __opd); } while (0)
#define M68K_RMW_A_B_UNARY(n, OP) \
    do { m_byte __opd = M68K_READ_A_B(n); OP(__opd); M68K_WRITE_A_B(n, __opd); } while (0)
#define M68K_RMW_A_W_UNARY(n, OP) \
    do { m_word __opd = M68K_READ_A_W(n); OP(__opd); M68K_WRITE_A_W(n, __opd); } while (0)
#define M68K_RMW_A_L_UNARY(n, OP) \
    do { m_long __opd = M68K_READ_A_L(n); OP(__opd); M68K_WRITE_A_L(n, __opd); } while (0)
#define M68K_RMW_MEM_B_UNARY(addr, OP) \
    do { m_byte __opd = M68K_READ_MEM_B(addr); OP(__opd); M68K_WRITE_MEM_B(addr, __opd); } while (0)
#define M68K_RMW_MEM_W_UNARY(addr, OP) \
    do { m_word __opd = M68K_READ_MEM_W(addr); OP(__opd); M68K_WRITE_MEM_W(addr, __opd); } while (0)
#define M68K_RMW_MEM_L_UNARY(addr, OP) \
    do { m_long __opd = M68K_READ_MEM_L(addr); OP(__opd); M68K_WRITE_MEM_L(addr, __opd); } while (0)
#define M68K_RMW_POSTINC_B_UNARY(n, OP) \
    do { \
        m_long __a = M68K_AREG(n); \
        m_byte __opd = memory().readByte(__a); \
        OP(__opd); \
        memory().writeByte(__a, __opd); \
        M68K_STEP_A(n, (n) == 7 ? 2 : 1); \
    } while (0)
#define M68K_RMW_POSTINC_W_UNARY(n, OP) \
    do { \
        m_long __a = M68K_AREG(n); \
        m_word __opd = memory().readWord(__a); \
        OP(__opd); \
        memory().writeWord(__a, __opd); \
        M68K_STEP_A(n, 2); \
    } while (0)
#define M68K_RMW_POSTINC_L_UNARY(n, OP) \
    do { \
        m_long __a = M68K_AREG(n); \
        m_long __opd = memory().readLong(__a); \
        OP(__opd); \
        memory().writeLong(__a, __opd); \
        M68K_STEP_A(n, 4); \
    } while (0)
#define M68K_RMW_PREDEC_B_UNARY(n, OP) \
    do { \
        M68K_STEP_A_SUB(n, (n) == 7 ? 2 : 1); \
        m_long __a = M68K_AREG(n); \
        m_byte __opd = memory().readByte(__a); \
        OP(__opd); \
        memory().writeByte(__a, __opd); \
    } while (0)
#define M68K_RMW_PREDEC_W_UNARY(n, OP) \
    do { \
        M68K_STEP_A_SUB(n, 2); \
        m_long __a = M68K_AREG(n); \
        m_word __opd = memory().readWord(__a); \
        OP(__opd); \
        memory().writeWord(__a, __opd); \
    } while (0)
#define M68K_RMW_PREDEC_L_UNARY(n, OP) \
    do { \
        M68K_STEP_A_SUB(n, 4); \
        m_long __a = M68K_AREG(n); \
        m_long __opd = memory().readLong(__a); \
        OP(__opd); \
        memory().writeLong(__a, __opd); \
    } while (0)

#define M68K_MOVEQ(n, imm) \
    do { m_long __v = M68K_SIGNEXT_B(imm); M68K_WRITE_D_L(n, __v); M68K_MOVE_L(__v); } while (0)

#define M68K_MOVE_B_TO_D(n, val) \
    do { m_byte __v = (val); M68K_WRITE_D_B(n, __v); M68K_MOVE_B(__v); } while (0)
#define M68K_MOVE_W_TO_D(n, val) \
    do { m_word __v = (val); M68K_WRITE_D_W(n, __v); M68K_MOVE_W(__v); } while (0)
#define M68K_MOVE_L_TO_D(n, val) \
    do { m_long __v = (val); M68K_WRITE_D_L(n, __v); M68K_MOVE_L(__v); } while (0)

#define M68K_MOVE_B_TO_MEM(addr, val) \
    do { m_byte __v = (val); M68K_WRITE_MEM_B(addr, __v); M68K_MOVE_B(__v); } while (0)
#define M68K_MOVE_W_TO_MEM(addr, val) \
    do { m_word __v = (val); M68K_WRITE_MEM_W(addr, __v); M68K_MOVE_W(__v); } while (0)
#define M68K_MOVE_L_TO_MEM(addr, val) \
    do { m_long __v = (val); M68K_WRITE_MEM_L(addr, __v); M68K_MOVE_L(__v); } while (0)

#define M68K_MOVE_B_TO_POSTINC(n, val) \
    do { m_byte __v = (val); M68K_WRITE_POSTINC_B(n, __v); M68K_MOVE_B(__v); } while (0)
#define M68K_MOVE_W_TO_POSTINC(n, val) \
    do { m_word __v = (val); M68K_WRITE_POSTINC_W(n, __v); M68K_MOVE_W(__v); } while (0)
#define M68K_MOVE_L_TO_POSTINC(n, val) \
    do { m_long __v = (val); M68K_WRITE_POSTINC_L(n, __v); M68K_MOVE_L(__v); } while (0)

#define M68K_MOVE_B_TO_PREDEC(n, val) \
    do { m_byte __v = (val); M68K_WRITE_PREDEC_B(n, __v); M68K_MOVE_B(__v); } while (0)
#define M68K_MOVE_W_TO_PREDEC(n, val) \
    do { m_word __v = (val); M68K_WRITE_PREDEC_W(n, __v); M68K_MOVE_W(__v); } while (0)
#define M68K_MOVE_L_TO_PREDEC(n, val) \
    do { m_long __v = (val); M68K_WRITE_PREDEC_L(n, __v); M68K_MOVE_L(__v); } while (0)

/** MOVE to An / USP — no CCR update (use M68K_MOVEA_* when flags from the source apply). */
#define M68K_MOVE_B_TO_A(n, val) \
    do { M68K_WRITE_A_B(n, (val)); } while (0)
#define M68K_MOVE_W_TO_A(n, val) \
    do { M68K_WRITE_A_W(n, (val)); } while (0)
#define M68K_MOVE_L_TO_A(n, val) \
    do { M68K_WRITE_A_L(n, (val)); } while (0)

#define M68K_CMP_D_B(n, src) M68K_CMP_B(M68K_READ_D_B(n), src)
#define M68K_CMP_D_W(n, src) M68K_CMP_W(M68K_READ_D_W(n), src)
#define M68K_CMP_D_L(n, src) M68K_CMP_L(M68K_READ_D_L(n), src)

#define M68K_TST_D_B(n) M68K_TST_B(M68K_READ_D_B(n))
#define M68K_TST_D_W(n) M68K_TST_W(M68K_READ_D_W(n))
#define M68K_TST_D_L(n) M68K_TST_L(M68K_READ_D_L(n))

#define M68K_TST_MEM_B(addr) M68K_TST_B(M68K_READ_MEM_B(addr))
#define M68K_TST_MEM_W(addr) M68K_TST_W(M68K_READ_MEM_W(addr))
#define M68K_TST_MEM_L(addr) M68K_TST_L(M68K_READ_MEM_L(addr))

#define M68K_CLR_TO_D_B(n) \
    do { m_byte __v = 0; M68K_CLR_B(__v); M68K_WRITE_D_B(n, __v); } while (0)
#define M68K_CLR_TO_D_W(n) \
    do { m_word __v = 0; M68K_CLR_W(__v); M68K_WRITE_D_W(n, __v); } while (0)
#define M68K_CLR_TO_D_L(n) \
    do { m_long __v = 0; M68K_CLR_L(__v); M68K_WRITE_D_L(n, __v); } while (0)
#define M68K_CLR_TO_MEM_B(addr) \
    do { m_byte __v = 0; M68K_CLR_B(__v); M68K_WRITE_MEM_B(addr, __v); } while (0)
#define M68K_CLR_TO_MEM_W(addr) \
    do { m_word __v = 0; M68K_CLR_W(__v); M68K_WRITE_MEM_W(addr, __v); } while (0)
#define M68K_CLR_TO_MEM_L(addr) \
    do { m_long __v = 0; M68K_CLR_L(__v); M68K_WRITE_MEM_L(addr, __v); } while (0)
#define M68K_CLR_TO_POSTINC_B(n) \
    do { m_byte __v = 0; M68K_CLR_B(__v); M68K_WRITE_POSTINC_B(n, __v); } while (0)
#define M68K_CLR_TO_POSTINC_W(n) \
    do { m_word __v = 0; M68K_CLR_W(__v); M68K_WRITE_POSTINC_W(n, __v); } while (0)
#define M68K_CLR_TO_POSTINC_L(n) \
    do { m_long __v = 0; M68K_CLR_L(__v); M68K_WRITE_POSTINC_L(n, __v); } while (0)
#define M68K_CLR_TO_PREDEC_B(n) \
    do { m_byte __v = 0; M68K_CLR_B(__v); M68K_WRITE_PREDEC_B(n, __v); } while (0)
#define M68K_CLR_TO_PREDEC_W(n) \
    do { m_word __v = 0; M68K_CLR_W(__v); M68K_WRITE_PREDEC_W(n, __v); } while (0)
#define M68K_CLR_TO_PREDEC_L(n) \
    do { m_long __v = 0; M68K_CLR_L(__v); M68K_WRITE_PREDEC_L(n, __v); } while (0)
#define M68K_CLR_TO_A_B(n) \
    do { m_byte __v = 0; M68K_CLR_B(__v); M68K_WRITE_A_B(n, __v); } while (0)
#define M68K_CLR_TO_A_W(n) \
    do { m_word __v = 0; M68K_CLR_W(__v); M68K_WRITE_A_W(n, __v); } while (0)
#define M68K_CLR_TO_A_L(n) \
    do { m_long __v = 0; M68K_CLR_L(__v); M68K_WRITE_A_L(n, __v); } while (0)

#define M68K_LEA(an, addr) M68K_WRITE_A_L(an, static_cast<m_long>(addr))
#define M68K_PEA(addr) \
    do { cpu().ssp -= 4; memory().writeLong(cpu().ssp, static_cast<m_long>(addr)); } while (0)

#define M68K_MULU_TO_D(n, src) M68K_WRITE_D_L(n, M68K_MULU(M68K_READ_D_W(n), src))
#define M68K_MULS_TO_D(n, src) M68K_WRITE_D_L(n, M68K_MULS(M68K_READ_D_W(n), src))
#define M68K_DIVU_TO_D(n, src) M68K_WRITE_D_L(n, M68K_DIVU(M68K_READ_D_L(n), src))
#define M68K_DIVS_TO_D(n, src) M68K_WRITE_D_L(n, M68K_DIVS(M68K_READ_D_L(n), src))

#define M68K_SWAP_D(n) \
    do { m_long __v = M68K_READ_D_L(n); M68K_SWAP(__v); M68K_WRITE_D_L(n, __v); } while (0)

#define M68K_SCC_TO_B(dst, cc) \
    do { m_byte __v = 0; M68K_SCC(__v, cc); (dst) = __v; } while (0)

#define M68K_SCC_TO_D_B(n, cc) \
    do { m_byte __v = 0; M68K_SCC(__v, cc); M68K_WRITE_D_B(n, __v); } while (0)
#define M68K_SCC_TO_A_B(n, cc) \
    do { m_byte __v = 0; M68K_SCC(__v, cc); M68K_WRITE_A_B(n, __v); } while (0)
#define M68K_SCC_TO_MEM_B(addr, cc) \
    do { m_byte __v = 0; M68K_SCC(__v, cc); M68K_WRITE_MEM_B(addr, __v); } while (0)
#define M68K_SCC_TO_POSTINC_B(n, cc) \
    do { m_byte __v = 0; M68K_SCC(__v, cc); M68K_WRITE_POSTINC_B(n, __v); } while (0)
#define M68K_SCC_TO_PREDEC_B(n, cc) \
    do { m_byte __v = 0; M68K_SCC(__v, cc); M68K_WRITE_PREDEC_B(n, __v); } while (0)


// ADD — arithmetic; sets N,Z,V,C,X.
#define M68K_ADD_B(r, s) \
    do { \
        m_byte __opd = (r), __s = (s); \
        m_word __full = static_cast<m_word>(__opd) + static_cast<m_word>(__s); \
        (r) = static_cast<m_byte>(__full); \
        bool __cy = (__full & 0x100u) != 0; \
        bool __ov = ((~(__opd ^ __s) & (__opd ^ (r))) & 0x80u) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)
#define M68K_ADD_W(r, s) \
    do { \
        m_word __opd = (r), __s = (s); \
        m_long __full = static_cast<m_long>(__opd) + static_cast<m_long>(__s); \
        (r) = static_cast<m_word>(__full); \
        bool __cy = (__full & 0x10000u) != 0; \
        bool __ov = ((~(__opd ^ __s) & (__opd ^ (r))) & 0x8000u) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)
#define M68K_ADD_L(r, s) \
    do { \
        m_long __opd = (r), __s = (s); \
        uint64_t __full = static_cast<uint64_t>(__opd) + static_cast<uint64_t>(__s); \
        (r) = static_cast<m_long>(__full); \
        bool __cy = (__full & 0x100000000u) != 0; \
        bool __ov = ((~(__opd ^ __s) & (__opd ^ (r))) & 0x80000000u) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)

// SUB — arithmetic; sets N,Z,V,C,X.
#define M68K_SUB_B(r, s) \
    do { \
        m_byte __opd = (r), __s = (s); \
        m_word __full = static_cast<m_word>(__opd) - static_cast<m_word>(__s); \
        (r) = static_cast<m_byte>(__full); \
        bool __cy = (__full & 0x100u) != 0; \
        bool __ov = (((__opd ^ __s) & (__opd ^ (r))) & 0x80u) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)
#define M68K_SUB_W(r, s) \
    do { \
        m_word __opd = (r), __s = (s); \
        m_long __full = static_cast<m_long>(__opd) - static_cast<m_long>(__s); \
        (r) = static_cast<m_word>(__full); \
        bool __cy = (__full & 0x10000u) != 0; \
        bool __ov = (((__opd ^ __s) & (__opd ^ (r))) & 0x8000u) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)
#define M68K_SUB_L(r, s) \
    do { \
        m_long __opd = (r), __s = (s); \
        uint64_t __full = static_cast<uint64_t>(__opd) - static_cast<uint64_t>(__s); \
        (r) = static_cast<m_long>(__full); \
        bool __cy = (__full & 0x100000000u) != 0; \
        bool __ov = (((__opd ^ __s) & (__opd ^ (r))) & 0x80000000u) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)

// CMP — compare; sets flags only (X preserved).
#define M68K_CMP_B(d, s) \
    do { \
        bool __x = M68K_FLAG_X; \
        m_byte __d = (d), __s = (s); \
        m_word __full = static_cast<m_word>(__d) - static_cast<m_word>(__s); \
        m_byte __r = static_cast<m_byte>(__full); \
        bool __cy = (__full & 0x100u) != 0; \
        bool __ov = (((__d ^ __s) & (__d ^ __r)) & 0x80u) != 0; \
        M68K_SET_FLAG_N(((__r) & 0x80u) != 0); M68K_SET_FLAG_Z((__r) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__x); \
    } while (0)
#define M68K_CMP_W(d, s) \
    do { \
        bool __x = M68K_FLAG_X; \
        m_word __d = (d), __s = (s); \
        m_long __full = static_cast<m_long>(__d) - static_cast<m_long>(__s); \
        m_word __r = static_cast<m_word>(__full); \
        bool __cy = (__full & 0x10000u) != 0; \
        bool __ov = (((__d ^ __s) & (__d ^ __r)) & 0x8000u) != 0; \
        M68K_SET_FLAG_N(((__r) & 0x8000u) != 0); M68K_SET_FLAG_Z((__r) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__x); \
    } while (0)
#define M68K_CMP_L(d, s) \
    do { \
        bool __x = M68K_FLAG_X; \
        m_long __d = (d), __s = (s); \
        uint64_t __full = static_cast<uint64_t>(__d) - static_cast<uint64_t>(__s); \
        m_long __r = static_cast<m_long>(__full); \
        bool __cy = (__full & 0x100000000u) != 0; \
        bool __ov = (((__d ^ __s) & (__d ^ __r)) & 0x80000000u) != 0; \
        M68K_SET_FLAG_N(((__r) & 0x80000000u) != 0); M68K_SET_FLAG_Z((__r) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__x); \
    } while (0)

// =============================================================================
// MOVE — data movement (flags only; stores are emitted by the recompiler)
// =============================================================================

/** MOVE.B/W/L — set N and Z; clear V and C. */
#define M68K_MOVE_B(r) do { M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_MOVE_W(r) do { M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_MOVE_L(r) do { M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

/** MOVEA — load An; no flags. Word source is sign-extended. */
#define M68K_MOVEA_W(ar, s) \
    do { (ar) = static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(s)))); } while (0)
#define M68K_MOVEA_L(ar, s) \
    do { (ar) = static_cast<m_long>(s); } while (0)

/** ADDA / SUBA / CMPA — address arithmetic. */
#define M68K_ADDA_W(ar, s) \
    do { (ar) = static_cast<m_long>((ar) + static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(s))))); } while (0)
#define M68K_ADDA_L(ar, s) \
    do { (ar) = static_cast<m_long>((ar) + static_cast<m_long>(s)); } while (0)
#define M68K_SUBA_W(ar, s) \
    do { (ar) = static_cast<m_long>((ar) - static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(s))))); } while (0)
#define M68K_SUBA_L(ar, s) \
    do { (ar) = static_cast<m_long>((ar) - static_cast<m_long>(s)); } while (0)
#define M68K_CMPA_W(ar, s) \
    M68K_CMP_L((ar), static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(s)))))
#define M68K_CMPA_L(ar, s) M68K_CMP_L((ar), (s))

// =============================================================================
// Logical / unary
// =============================================================================

// AND — bitwise; sets N,Z; clears V,C.
#define M68K_AND_B(r, s) \
    do { (r) = static_cast<m_byte>((r) & static_cast<m_byte>(s)); M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_AND_W(r, s) \
    do { (r) = static_cast<m_word>((r) & static_cast<m_word>(s)); M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_AND_L(r, s) \
    do { (r) = static_cast<m_long>((r) & static_cast<m_long>(s)); M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

// OR — bitwise; sets N,Z; clears V,C.
#define M68K_OR_B(r, s) \
    do { (r) = static_cast<m_byte>((r) | static_cast<m_byte>(s)); M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_OR_W(r, s) \
    do { (r) = static_cast<m_word>((r) | static_cast<m_word>(s)); M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_OR_L(r, s) \
    do { (r) = static_cast<m_long>((r) | static_cast<m_long>(s)); M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

// EOR — bitwise; sets N,Z; clears V,C.
#define M68K_EOR_B(r, s) \
    do { (r) = static_cast<m_byte>((r) ^ static_cast<m_byte>(s)); M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_EOR_W(r, s) \
    do { (r) = static_cast<m_word>((r) ^ static_cast<m_word>(s)); M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_EOR_L(r, s) \
    do { (r) = static_cast<m_long>((r) ^ static_cast<m_long>(s)); M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

#define M68K_TST_B(v) do { M68K_SET_FLAG_N((((v)) & 0x80u) != 0); M68K_SET_FLAG_Z(((v)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_TST_W(v) do { M68K_SET_FLAG_N((((v)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((v)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_TST_L(v) do { M68K_SET_FLAG_N((((v)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((v)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

#define M68K_CLR_B(r) do { (r) = 0; M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_CLR_W(r) do { (r) = 0; M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_CLR_L(r) do { (r) = 0; M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_NEG_B(r) \
    do { \
        m_byte __opd = (r), __s = static_cast<m_byte>(0); \
        m_word __full = static_cast<m_word>(__s) - static_cast<m_word>(__opd); \
        (r) = static_cast<m_byte>(__full); \
        bool __cy = (__full & 0x100u) != 0; \
        bool __ov = (((__opd & (r)) & 0x80u)) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)
#define M68K_NEG_W(r) \
    do { \
        m_word __opd = (r), __s = static_cast<m_word>(0); \
        m_long __full = static_cast<m_long>(__s) - static_cast<m_long>(__opd); \
        (r) = static_cast<m_word>(__full); \
        bool __cy = (__full & 0x10000u) != 0; \
        bool __ov = (((__opd & (r)) & 0x8000u)) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)
#define M68K_NEG_L(r) \
    do { \
        m_long __opd = (r), __s = static_cast<m_long>(0); \
        uint64_t __full = static_cast<uint64_t>(__s) - static_cast<uint64_t>(__opd); \
        (r) = static_cast<m_long>(__full); \
        bool __cy = (__full & 0x100000000u) != 0; \
        bool __ov = (((__opd & (r)) & 0x80000000u)) != 0; \
        M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(__ov); M68K_SET_FLAG_C(__cy); M68K_SET_FLAG_X(__cy); \
    } while (0)

#define M68K_NOT_B(r) do { (r) = static_cast<m_byte>(~(r)); M68K_SET_FLAG_N((((r)) & 0x80u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_NOT_W(r) do { (r) = static_cast<m_word>(~(r)); M68K_SET_FLAG_N((((r)) & 0x8000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)
#define M68K_NOT_L(r) do { (r) = static_cast<m_long>(~(r)); M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

#define M68K_SWAP(r) do { (r) = static_cast<m_long>(((r) >> 16) | ((r) << 16)); M68K_SET_FLAG_N((((r)) & 0x80000000u) != 0); M68K_SET_FLAG_Z(((r)) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); } while (0)

/** EXT.W — sign-extend low byte of Dn into bits 8–15; high word untouched. */
#define M68K_EXT_W(n) \
    do { \
        m_word __w = static_cast<m_word>(static_cast<int16_t>(static_cast<int8_t>(cpu().d[n] & 0xFFu))); \
        cpu().d[n] = static_cast<m_long>((cpu().d[n] & 0xFFFF0000u) | static_cast<m_long>(__w)); \
        M68K_SET_FLAG_N(((__w) & 0x8000u) != 0); M68K_SET_FLAG_Z((__w) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); \
    } while (0)

/** EXT.L — sign-extend low word of Dn to long. */
#define M68K_EXT_L(n) \
    do { \
        m_long __v = static_cast<m_long>(static_cast<int32_t>(static_cast<int16_t>(cpu().d[n] & 0xFFFFu))); \
        cpu().d[n] = __v; \
        M68K_SET_FLAG_N(((__v) & 0x80000000u) != 0); M68K_SET_FLAG_Z((__v) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); \
    } while (0)

#define M68K_EXG(a, b) do { m_long __t = (a); (a) = (b); (b) = __t; } while (0)

// =============================================================================
// Bit operations
// =============================================================================

#define M68K_BTST(v, bit) M68K_SET_FLAG_Z(((static_cast<m_long>(v) >> (bit)) & 1u) == 0)

#define M68K_BSET(r, bit) \
    do { \
        M68K_SET_FLAG_Z((((static_cast<m_long>(r) >> (bit)) & 1u) == 0)); \
        (r) |= static_cast<decltype(r)>(1) << (bit); \
    } while (0)

#define M68K_BCLR(r, bit) \
    do { \
        M68K_SET_FLAG_Z((((static_cast<m_long>(r) >> (bit)) & 1u) == 0)); \
        (r) &= ~(static_cast<decltype(r)>(1) << (bit)); \
    } while (0)

#define M68K_BCHG(r, bit) \
    do { \
        M68K_SET_FLAG_Z((((static_cast<m_long>(r) >> (bit)) & 1u) == 0)); \
        (r) ^= static_cast<decltype(r)>(1) << (bit); \
    } while (0)

// =============================================================================
// Shifts and rotates
// =============================================================================
#define M68K_LSL_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            __c = (__v & (1u << (nbits - 1))) != 0; __v = (__v << 1) & __mask; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_LSR_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            __c = (__v & 1u) != 0; __v >>= 1; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_ASL_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __sg = __v & (1u << (nbits - 1)); __c = __sg != 0; __v = (__v << 1) & __mask; if ((__v & (1u << (nbits - 1))) != __sg) __ov = true; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(__ov); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(__ov); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_ASR_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __sg = __v & (1u << (nbits - 1)); __c = (__v & 1u) != 0; __v = ((__v >> 1) | __sg) & __mask; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_ROL_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ms = (__v >> (nbits - 1)) & 1u; __v = ((__v << 1) | __ms) & __mask; __c = __ms != 0; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_ROR_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ls = __v & 1u; __v = ((__v >> 1) | (__ls << (nbits - 1))) & __mask; __c = __ls != 0; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_LSL_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            __c = (__v & (1u << (nbits - 1))) != 0; __v = (__v << 1) & __mask; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_LSR_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            __c = (__v & 1u) != 0; __v >>= 1; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_ASL_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __sg = __v & (1u << (nbits - 1)); __c = __sg != 0; __v = (__v << 1) & __mask; if ((__v & (1u << (nbits - 1))) != __sg) __ov = true; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(__ov); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(__ov); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_ASR_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __sg = __v & (1u << (nbits - 1)); __c = (__v & 1u) != 0; __v = ((__v >> 1) | __sg) & __mask; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_ROL_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ms = (__v >> (nbits - 1)) & 1u; __v = ((__v << 1) | __ms) & __mask; __c = __ms != 0; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_ROR_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ls = __v & 1u; __v = ((__v >> 1) | (__ls << (nbits - 1))) & __mask; __c = __ls != 0; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_LSL_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            __c = (__v & (1u << (nbits - 1))) != 0; __v = (__v << 1) & __mask; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_LSR_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            __c = (__v & 1u) != 0; __v >>= 1; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_ASL_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __sg = __v & (1u << (nbits - 1)); __c = __sg != 0; __v = (__v << 1) & __mask; if ((__v & (1u << (nbits - 1))) != __sg) __ov = true; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(__ov); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(__ov); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_ASR_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __sg = __v & (1u << (nbits - 1)); __c = (__v & 1u) != 0; __v = ((__v >> 1) | __sg) & __mask; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_X(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_ROL_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ms = (__v >> (nbits - 1)) & 1u; __v = ((__v << 1) | __ms) & __mask; __c = __ms != 0; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_ROR_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __c = false; \
        bool __ov = false; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ls = __v & 1u; __v = ((__v >> 1) | (__ls << (nbits - 1))) & __mask; __c = __ls != 0; \
        } \
        if ((cnt) == 0) { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } else { \
            M68K_SET_FLAG_C(__c); \
            M68K_SET_FLAG_V(false); \
        } \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_ROXL_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __x = M68K_FLAG_X; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ms = (__v >> (nbits - 1)) & 1u; __v = ((__v << 1) | (__x ? 1u : 0u)) & __mask; __x = __ms != 0; \
        } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(__x); M68K_SET_FLAG_X(__x); \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_ROXR_B(r, cnt) \
    do { \
        const int nbits = 8; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_byte>(r)) & __mask; \
        bool __x = M68K_FLAG_X; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ls = __v & 1u; __v = ((__v >> 1) | ((__x ? 1u : 0u) << (nbits - 1))) & __mask; __x = __ls != 0; \
        } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(__x); M68K_SET_FLAG_X(__x); \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_byte>(__v); \
    } while (0)
#define M68K_ROXL_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __x = M68K_FLAG_X; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ms = (__v >> (nbits - 1)) & 1u; __v = ((__v << 1) | (__x ? 1u : 0u)) & __mask; __x = __ms != 0; \
        } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(__x); M68K_SET_FLAG_X(__x); \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_ROXR_W(r, cnt) \
    do { \
        const int nbits = 16; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_word>(r)) & __mask; \
        bool __x = M68K_FLAG_X; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ls = __v & 1u; __v = ((__v >> 1) | ((__x ? 1u : 0u) << (nbits - 1))) & __mask; __x = __ls != 0; \
        } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(__x); M68K_SET_FLAG_X(__x); \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_word>(__v); \
    } while (0)
#define M68K_ROXL_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __x = M68K_FLAG_X; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ms = (__v >> (nbits - 1)) & 1u; __v = ((__v << 1) | (__x ? 1u : 0u)) & __mask; __x = __ms != 0; \
        } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(__x); M68K_SET_FLAG_X(__x); \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)
#define M68K_ROXR_L(r, cnt) \
    do { \
        const int nbits = 32; \
        m_long __mask = (nbits >= 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u); \
        m_long __v = static_cast<m_long>(static_cast<m_long>(r)) & __mask; \
        bool __x = M68K_FLAG_X; \
        for (int __i = 0; __i < static_cast<int>(cnt); ++__i) { \
            m_long __ls = __v & 1u; __v = ((__v >> 1) | ((__x ? 1u : 0u) << (nbits - 1))) & __mask; __x = __ls != 0; \
        } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(__x); M68K_SET_FLAG_X(__x); \
        M68K_SET_FLAG_N(((__v) & (1u << (nbits - 1))) != 0); \
        M68K_SET_FLAG_Z((__v & __mask) == 0); \
        (r) = static_cast<m_long>(__v); \
    } while (0)

// =============================================================================
// Multiply / divide / BCD / special registers
// =============================================================================

#define M68K_MULU(d, s) \
    ([&]() -> m_long { \
        m_long __r = static_cast<m_long>(static_cast<m_word>(d)) * static_cast<m_long>(static_cast<m_word>(s)); \
        M68K_SET_FLAG_N(((__r) & 0x80000000u) != 0); M68K_SET_FLAG_Z((__r) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); return __r; \
    }())

#define M68K_MULS(d, s) \
    ([&]() -> m_long { \
        int32_t __p = static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(d))) * \
                    static_cast<int32_t>(static_cast<int16_t>(static_cast<m_word>(s))); \
        m_long __r = static_cast<m_long>(__p); M68K_SET_FLAG_N(((__r) & 0x80000000u) != 0); M68K_SET_FLAG_Z((__r) == 0); M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); return __r; \
    }())

#define M68K_DIVU(d, s) \
    ([&]() -> m_long { \
        m_word __s = static_cast<m_word>(s); \
        if (__s == 0) return static_cast<m_long>(d); \
        m_long __q = static_cast<m_long>(d) / __s, __r = static_cast<m_long>(d) % __s; \
        if (__q > 0xFFFF) { M68K_SET_FLAG_V(true); return static_cast<m_long>(d); } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); M68K_SET_FLAG_N(((static_cast<m_word>(__q)) & 0x8000u) != 0); M68K_SET_FLAG_Z((static_cast<m_word>(__q)) == 0); \
        return static_cast<m_long>((__r << 16) | (__q & 0xFFFF)); \
    }())

#define M68K_DIVS(d, s) \
    ([&]() -> m_long { \
        int16_t __s = static_cast<int16_t>(static_cast<m_word>(s)); \
        if (__s == 0) return static_cast<m_long>(d); \
        int32_t __dst = static_cast<int32_t>(d), __q = __dst / __s, __r = __dst % __s; \
        if (__q > 32767 || __q < -32768) { M68K_SET_FLAG_V(true); return static_cast<m_long>(d); } \
        M68K_SET_FLAG_V(false); M68K_SET_FLAG_C(false); M68K_SET_FLAG_N(((static_cast<m_word>(__q)) & 0x8000u) != 0); M68K_SET_FLAG_Z((static_cast<m_word>(__q)) == 0); \
        return static_cast<m_long>((static_cast<m_long>(__r & 0xFFFF) << 16) | (static_cast<m_long>(__q) & 0xFFFF)); \
    }())

#define M68K_SCC(r, cc) ((r) = M68K_TEST_CC(cc) ? static_cast<m_byte>(0xFF) : static_cast<m_byte>(0))

#define M68K_ABCD(r, s) \
    ((r) = [&]() -> m_byte { \
        int __x = M68K_FLAG_X ? 1 : 0; \
        int __lo = ((r) & 0x0F) + ((s) & 0x0F) + __x, __hi = ((r) >> 4) + ((s) >> 4), __cy = 0; \
        if (__lo > 9) { __lo -= 10; ++__hi; } if (__hi > 9) { __hi -= 10; __cy = 1; } \
        m_byte __o = static_cast<m_byte>(((__hi & 0x0F) << 4) | (__lo & 0x0F)); \
        M68K_SET_FLAG_C(__cy != 0); M68K_SET_FLAG_X(__cy != 0); \
        if (__o != 0) M68K_SET_FLAG_Z(false); M68K_SET_FLAG_N((__o & 0x80u) != 0); \
        return __o; \
    }())

#define M68K_SBCD(r, s) \
    ((r) = [&]() -> m_byte { \
        int __x = M68K_FLAG_X ? 1 : 0; \
        int __lo = ((r) & 0x0F) - ((s) & 0x0F) - __x, __hi = ((r) >> 4) - ((s) >> 4), __bw = 0; \
        if (__lo < 0) { __lo += 10; --__hi; } if (__hi < 0) { __hi += 10; __bw = 1; } \
        m_byte __o = static_cast<m_byte>(((__hi & 0x0F) << 4) | (__lo & 0x0F)); \
        M68K_SET_FLAG_C(__bw != 0); M68K_SET_FLAG_X(__bw != 0); \
        if (__o != 0) M68K_SET_FLAG_Z(false); M68K_SET_FLAG_N((__o & 0x80u) != 0); \
        return __o; \
    }())

#define M68K_NBCD(r) \
    ((r) = [&]() -> m_byte { \
        int __x = M68K_FLAG_X ? 1 : 0; \
        m_byte __s = static_cast<m_byte>(r); \
        int __lo = -(__s & 0x0F) - __x, __hi = -(__s >> 4), __bw = 0; \
        if (__lo < 0) { __lo += 10; --__hi; } if (__hi < 0) { __hi += 10; __bw = 1; } \
        m_byte __o = static_cast<m_byte>(((__hi & 0x0F) << 4) | (__lo & 0x0F)); \
        M68K_SET_FLAG_C(__bw != 0); M68K_SET_FLAG_X(__bw != 0); \
        if (__o != 0) M68K_SET_FLAG_Z(false); M68K_SET_FLAG_N((__o & 0x80u) != 0); \
        return __o; \
    }())

#define M68K_NEGX_B(r) ((r) = [&]() -> m_byte { \
        int __x = M68K_FLAG_X ? 1 : 0; \
        m_word __f = static_cast<m_word>(0u - static_cast<m_word>(static_cast<m_byte>(r)) - __x); \
        m_byte __o = static_cast<m_byte>(__f); bool __bw = (__f & 0x100u) != 0; \
        if (__o != 0) M68K_SET_FLAG_Z(false); M68K_SET_FLAG_N((__o & 0x80u) != 0); \
        M68K_SET_FLAG_V((((r) & __o) & 0x80u) != 0); M68K_SET_FLAG_C(__bw); M68K_SET_FLAG_X(__bw); \
        return __o; }())

#define M68K_NEGX_W(r) ((r) = [&]() -> m_word { \
        int __x = M68K_FLAG_X ? 1 : 0; \
        m_long __f = static_cast<m_long>(0u - static_cast<m_long>(static_cast<m_word>(r)) - __x); \
        m_word __o = static_cast<m_word>(__f); bool __bw = (__f & 0x10000u) != 0; \
        if (__o != 0) M68K_SET_FLAG_Z(false); M68K_SET_FLAG_N((__o & 0x8000u) != 0); \
        M68K_SET_FLAG_V((((r) & __o) & 0x8000u) != 0); M68K_SET_FLAG_C(__bw); M68K_SET_FLAG_X(__bw); \
        return __o; }())

#define M68K_NEGX_L(r) ((r) = [&]() -> m_long { \
        int __x = M68K_FLAG_X ? 1 : 0; \
        uint64_t __f = 0ull - static_cast<uint64_t>(static_cast<m_long>(r)) - __x; \
        m_long __o = static_cast<m_long>(__f); bool __bw = (__f & 0x100000000ull) != 0; \
        if (__o != 0) M68K_SET_FLAG_Z(false); M68K_SET_FLAG_N((__o & 0x80000000u) != 0); \
        M68K_SET_FLAG_V((((r) & __o) & 0x80000000u) != 0); M68K_SET_FLAG_C(__bw); M68K_SET_FLAG_X(__bw); \
        return __o; }())

#define M68K_MOVE_TO_SR(v) (M68K_SR = static_cast<m_word>(v))
#define M68K_MOVE_FROM_SR() (M68K_SR)
#define M68K_MOVE_TO_CCR(v) (M68K_SR = static_cast<m_word>((M68K_SR & 0xFF00u) | (static_cast<m_word>(v) & 0x00FFu)))
#define M68K_MOVE_TO_USP(v) (cpu().usp = static_cast<m_long>(v))
