#pragma once

#include "data_types.hpp"

#include <SDL3/SDL.h>

#include <string>

class MegaDriveEnvironment;

/**
 * @file SystemMemory.hpp
 * @brief 68K address-space memory for a MegaDriveEnvironment.
 *
 * Owns the cartridge ROM (0x000000-0x3FFFFF) and the 68000 work RAM
 * (0xFF0000-0xFFFFFF) and exposes a unified read/write interface over the
 * 24-bit address space. This was previously a set of global free functions
 * in memory.cpp; it is now an instance owned by MegaDriveEnvironment so that
 * each environment has its own address space and subsystems reach it through
 * the parent (e.g. `env->memory()`).
 *
 * All multi-byte values are read/written in big-endian (Motorola) byte order,
 * matching the native format of the 68000 CPU. All public operations are
 * thread-safe, serialized by an SDL_Mutex for portability.
 */
class SystemMemory {
    public:
    /// Allocates and zero-initializes ROM and work RAM, and creates the mutex.
    /// @p env (optional) lets memory-mapped hardware accesses (VDP, I/O ports,
    /// Z80, TMSS) route to the owning environment's subsystems; when null those
    /// regions read as 0 and ignore writes.
    explicit SystemMemory(MegaDriveEnvironment *env = nullptr);

    /// Releases ROM, work RAM, and the mutex.
    ~SystemMemory();

    SystemMemory(const SystemMemory &)            = delete;
    SystemMemory &operator=(const SystemMemory &) = delete;

    /// Re-zeroes ROM and work RAM. Kept for parity with the old initRAM() entry point.
    void initRAM();

    /// Loads a cartridge ROM image from @p path into the ROM region
    /// (0x000000-0x3FFFFF). Reads at most ROM_SIZE (4 MiB) bytes; a larger file
    /// is truncated to that limit. On a missing or unreadable file, writes a
    /// clear error to stderr and leaves the ROM region unchanged (it is not a
    /// silent success).
    void loadROM(const std::string &path);

    /// Reads a single byte from the given 68K address.
    m_byte readByte(m_long address);

    /// Reads a 16-bit word (big-endian) from the given 68K address.
    m_word readWord(m_long address);

    /// Reads a 32-bit long word (big-endian) from the given 68K address.
    m_long readLong(m_long address);

    /// Writes a single byte to the given 68K address.
    void writeByte(m_long address, m_byte value);

    /// Writes a 16-bit word (big-endian) to the given 68K address.
    void writeWord(m_long address, m_word value);

    /// Writes a 32-bit long word (big-endian) to the given 68K address.
    void writeLong(m_long address, m_long value);

    /// Copies one byte from @p from to @p to within the 68K address space.
    void copyByte(m_long from, m_long to);

    /// Copies @p count bytes from @p from to @p to within the 68K address space.
    void copyBytes(m_long from, m_long to, int count);

    /// Copies one word from @p from to @p to within the 68K address space.
    void copyWord(m_long from, m_long to);

    /// Copies one long word from @p from to @p to within the 68K address space.
    void copyLong(m_long from, m_long to);

    /// Copies @p count bytes from emulated memory into a host buffer.
    void copyToBuffer(m_long address, void *ptr, int count);

    /// Copies @p count bytes from a host buffer into emulated memory.
    void writeFromBuffer(void *ptr, m_long address, int count);

    private:
    /// Maps a 68K address to a host pointer (handles 32-bit sign-extended mirrors).
    char *convertAddress(m_long address);

    // ── Unlocked primitives (caller holds mutex_) ───────────────────────────
    m_byte _readByte(m_long address);
    m_word _readWord(m_long address);
    m_long _readLong(m_long address);
    void   _writeByte(m_long address, m_byte value);
    void   _writeWord(m_long address, m_word value);
    void   _writeLong(m_long address, m_long value);
    void   _copyByte(m_long from, m_long to);
    void   _copyToBuffer(m_long address, void *ptr, int count);
    void   _writeFromBuffer(void *ptr, m_long address, int count);

    // ── Memory-mapped hardware (VDP / I/O / Z80 / TMSS) ──────────────────────
    // Routed outside mutex_ (each subsystem self-locks; the VDP's DMA reads back
    // through this memory, so holding mutex_ here would deadlock).
    static bool isHardware(m_long address);
    static bool isROM(m_long address);
    m_byte      hwReadByte(m_long address);
    m_word      hwReadWord(m_long address);
    m_long      hwReadLong(m_long address);
    void        hwWriteByte(m_long address, m_byte value);
    void        hwWriteWord(m_long address, m_word value);
    void        hwWriteLong(m_long address, m_long value);

    MegaDriveEnvironment *env_ = nullptr; ///< For memory-mapped hardware routing.

    void *rom_  = nullptr; ///< 0x000000-0x3FFFFF (4 MiB)
    void *wram_ = nullptr; ///< 0xFF0000-0xFFFFFF (64 KiB)

    SDL_Mutex *mutex_ = nullptr; ///< Serializes ROM/work-RAM access.
};
