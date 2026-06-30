#pragma once

#include "data_types.hpp"

/**
 * @file CPU68K.hpp
 * @brief Motorola 68000 register file — storage only.
 *
 * All instruction semantics live in M68KMacros.hpp. Generated cartridge code
 * reads and writes these fields exclusively through those macros.
 */
struct CPU68K {
    m_long d[8]{}; ///< D0–D7
    m_long a[7]{}; ///< A0–A6
    m_long ssp{};  ///< A7 (supervisor stack pointer)
    m_long usp{};  ///< A7 (user stack pointer; inactive in SoR)
    m_long pc{};   ///< Program counter (24-bit effective, stored in 32)
    m_word sr{};   ///< Status register (system byte + CCR)
};
