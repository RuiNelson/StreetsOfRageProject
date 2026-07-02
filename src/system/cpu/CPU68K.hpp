#pragma once

#include "data_types.hpp"

/**
 * @file CPU68K.hpp
 * @brief Motorola 68000 register file.
 *
 * Generated cartridge code reads and writes the general registers directly,
 * while SR/CCR access goes through helpers so flag and interrupt-mask code stays
 * readable at the call site.
 */
struct CPU68K {
    static constexpr m_word FlagC = 0x0001u;
    static constexpr m_word FlagV = 0x0002u;
    static constexpr m_word FlagZ = 0x0004u;
    static constexpr m_word FlagN = 0x0008u;
    static constexpr m_word FlagX = 0x0010u;

    static constexpr m_word CcrFlagMask    = FlagC | FlagV | FlagZ | FlagN | FlagX;
    static constexpr m_word CcrMask        = 0x00FFu;
    static constexpr m_word SupervisorFlag = 0x2000u;
    static constexpr m_word InterruptMask  = 0x0700u;
    static constexpr m_word SystemByteMask = 0xFF00u;

    m_long d[8]{}; ///< D0–D7
    m_long a[7]{}; ///< A0–A6
    m_long ssp{};  ///< A7 (supervisor stack pointer)
    m_long usp{};  ///< A7 (user stack pointer; inactive in SoR)
    m_long pc{};   ///< Program counter (24-bit effective, stored in 32)
    m_word sr{};   ///< Status register (system byte + CCR)

    m_word status() const {
        return sr;
    }
    void setStatus(m_word value) {
        sr = value;
    }

    m_word ccr() const {
        return static_cast<m_word>(sr & CcrMask);
    }
    void setCCR(m_word value) {
        sr = static_cast<m_word>((sr & SystemByteMask) | (value & CcrMask));
    }

    int interruptMask() const {
        return static_cast<int>((sr >> 8) & 0x07u);
    }
    void setInterruptMask(int level) {
        sr = static_cast<m_word>((sr & ~InterruptMask) | ((level & 0x07) << 8));
    }
    bool supervisor() const {
        return (sr & SupervisorFlag) != 0;
    }
    void setSupervisor(bool enabled) {
        setFlag(SupervisorFlag, enabled);
    }
    void enterInterrupt(int level) {
        sr = static_cast<m_word>((sr & ~InterruptMask) | SupervisorFlag | ((level & 0x07) << 8));
    }

    bool flag(m_word bit) const {
        return (sr & bit) != 0;
    }
    void setFlag(m_word bit, bool enabled) {
        sr = static_cast<m_word>((sr & ~bit) | (enabled ? bit : 0u));
    }
    void setCCRFlags(unsigned clearMask, unsigned values) {
        sr = static_cast<m_word>((sr & ~clearMask) | (values & clearMask));
    }
    void setNZ(m_long value, m_long signBit) {
        setCCRFlags(FlagN | FlagZ, nzFlags(value, signBit));
    }
    void setNZClearVC(m_long value, m_long signBit) {
        setCCRFlags(FlagN | FlagZ | FlagV | FlagC, nzFlags(value, signBit));
    }
    void setNZVC(m_long value, m_long signBit, bool overflow, bool carry) {
        setCCRFlags(FlagN | FlagZ | FlagV | FlagC,
                    nzFlags(value, signBit) | boolFlag(FlagV, overflow) | boolFlag(FlagC, carry));
    }
    void setNZVCX(m_long value, m_long signBit, bool overflow, bool carry, bool extend) {
        setCCRFlags(CcrFlagMask,
                    nzFlags(value, signBit) | boolFlag(FlagV, overflow) | boolFlag(FlagC, carry) |
                        boolFlag(FlagX, extend));
    }
    void setVC(bool overflow, bool carry) {
        setCCRFlags(FlagV | FlagC, boolFlag(FlagV, overflow) | boolFlag(FlagC, carry));
    }
    void setVCX(bool overflow, bool carry, bool extend) {
        setCCRFlags(FlagV | FlagC | FlagX,
                    boolFlag(FlagV, overflow) | boolFlag(FlagC, carry) | boolFlag(FlagX, extend));
    }

    bool flagC() const {
        return flag(FlagC);
    }
    bool flagV() const {
        return flag(FlagV);
    }
    bool flagZ() const {
        return flag(FlagZ);
    }
    bool flagN() const {
        return flag(FlagN);
    }
    bool flagX() const {
        return flag(FlagX);
    }

    void setFlagC(bool enabled) {
        setFlag(FlagC, enabled);
    }
    void setFlagV(bool enabled) {
        setFlag(FlagV, enabled);
    }
    void setFlagZ(bool enabled) {
        setFlag(FlagZ, enabled);
    }
    void setFlagN(bool enabled) {
        setFlag(FlagN, enabled);
    }
    void setFlagX(bool enabled) {
        setFlag(FlagX, enabled);
    }

    static m_word boolFlag(m_word bit, bool enabled) {
        return enabled ? bit : 0u;
    }
    static m_word nzFlags(m_long value, m_long signBit) {
        return static_cast<m_word>(((value & signBit) != 0 ? FlagN : 0u) | (value == 0 ? FlagZ : 0u));
    }

    bool condition(int cc) const {
        switch (cc & 0x0F) {
            case 0:
                return true; // T
            case 1:
                return false; // F
            case 2:
                return !flagC() && !flagZ(); // HI
            case 3:
                return flagC() || flagZ(); // LS
            case 4:
                return !flagC(); // CC
            case 5:
                return flagC(); // CS
            case 6:
                return !flagZ(); // NE
            case 7:
                return flagZ(); // EQ
            case 8:
                return !flagV(); // VC
            case 9:
                return flagV(); // VS
            case 10:
                return !flagN(); // PL
            case 11:
                return flagN(); // MI
            case 12:
                return flagN() == flagV(); // GE
            case 13:
                return flagN() != flagV(); // LT
            case 14:
                return !flagZ() && flagN() == flagV(); // GT
            default:
                return flagZ() || flagN() != flagV(); // LE
        }
    }
};
