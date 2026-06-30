#pragma once

#include <cstdint>

/**
 * @brief Motorola 68000-inspired type aliases for cross-platform consistency.
 *
 * The original Streets of Rage was developed for the Sega Genesis/Mega Drive,
 * which featured a Motorola 68000 CPU. These type aliases provide a clear
 * mapping between the hardware data widths and the C++ types used throughout
 * the codebase.
 *
 * - m_byte: 8-bit unsigned (data bus width)
 * - m_word: 16-bit unsigned (word width on 68K)
 * - m_long: 32-bit unsigned (long word on 68K)
 */
using m_byte = uint8_t;  ///< 8-bit unsigned integer (byte)
using m_word = uint16_t; ///< 16-bit unsigned integer (word)
using m_long = uint32_t; ///< 32-bit unsigned integer (long word)
