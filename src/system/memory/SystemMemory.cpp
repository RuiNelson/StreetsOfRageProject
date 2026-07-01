/**
 * @file SystemMemory.cpp
 * @brief 68K address-space memory implementation (ported from memory.cpp).
 */

#include "SystemMemory.hpp"

#include "system/MegaDriveEnvironment.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <format>
#include <fstream>
#include <ios>
#include <iostream>
#include <string>

#define ROM_SIZE      0x400000
#define Z80_RAM_SIZE  0x2000
#define WORK_RAM_SIZE 0x10000

#define ROM_BASE      0x000000u
#define ROM_END       (ROM_BASE + ROM_SIZE)
#define Z80_BASE      0xA00000u
#define Z80_END       (Z80_BASE + Z80_RAM_SIZE)
#define WORK_RAM_BASE 0xFF0000u
#define WORK_RAM_END  (WORK_RAM_BASE + WORK_RAM_SIZE)

// Control RAM is on the `Controllers` instance, VDP RAM is on the `VDP`
// instance, and Z80 RAM is on the `Z80` instance — all reached through the
// owning MegaDriveEnvironment.

SystemMemory::SystemMemory(MegaDriveEnvironment *env) : env_(env) {
    rom_   = malloc(ROM_SIZE);
    wram_  = malloc(WORK_RAM_SIZE);
    mutex_ = SDL_CreateMutex();
    initRAM();
}

SystemMemory::~SystemMemory() {
    if (mutex_) {
        SDL_DestroyMutex(mutex_);
        mutex_ = nullptr;
    }
    free(rom_);
    free(wram_);
    rom_  = nullptr;
    wram_ = nullptr;
}

void SystemMemory::initRAM() {
    std::memset(rom_, 0, ROM_SIZE);
    std::memset(wram_, 0, WORK_RAM_SIZE);
}

void SystemMemory::loadROM(const std::string &path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        std::cerr << std::format("SystemMemory: cannot open ROM file '{}'\n", path);
        return;
    }

    const std::streamoff size = file.tellg();
    if (size < 0) {
        std::cerr << std::format("SystemMemory: cannot determine size of ROM file '{}'\n", path);
        return;
    }
    file.seekg(0, std::ios::beg);

    // Never read past the ROM region; a larger image is truncated to 4 MiB.
    auto toRead = static_cast<std::streamsize>(size);
    if (static_cast<unsigned long long>(size) > ROM_SIZE) {
        std::cerr << std::format("SystemMemory: ROM file '{}' is {} bytes, larger than the {} byte ROM "
                                 "region; truncating to {} bytes\n",
                                 path,
                                 static_cast<unsigned long long>(size),
                                 ROM_SIZE,
                                 ROM_SIZE);
        toRead = static_cast<std::streamsize>(ROM_SIZE);
    }

    file.read(static_cast<char *>(rom_), toRead);
    if (!file && !file.eof()) {
        std::cerr << std::format("SystemMemory: error reading ROM file '{}'\n", path);
    }
}

// Mega Drive physical memory map (24-bit address bus):
//   0x000000 – 0x3FFFFF  →  Cartridge ROM       (4 MiB)
//   0xA00000 – 0xA01FFF  →  Z80 RAM             (8 KiB)
//   0xFF0000 – 0xFFFFFF  →  68000 Work RAM       (64 KiB)
//
// The 68000 has 32-bit address registers but only a 24-bit bus, so every
// address is normalized to 24 bits before dispatch. This makes the high
// sign-extended mirrors fold correctly (e.g. FFFF8000 → FF8000, FFFF0000 →
// FF0000 lands in work RAM) and lets register-derived addresses with stray
// high bits map without each caller having to mask first.
char *SystemMemory::convertAddress(m_long address) {
    constexpr m_long ADDRESS_MASK_24 = 0x00FFFFFFu;

    address &= ADDRESS_MASK_24;

    if (address >= ROM_BASE && address < ROM_END) {
        auto offset = address - ROM_BASE;
        return static_cast<char *>(rom_) + offset;
    }
    if (address >= Z80_BASE && address < Z80_END) {
        // Unreachable via the public read*/write* API: isHardware() (below)
        // catches this range first and routes it through hwReadByte/hwWriteByte
        // to the Z80 subsystem's RAM. Only the unlocked copy*() helpers (currently
        // unused anywhere in the codebase) could reach here, bypassing that routing.
    }
    if (address >= WORK_RAM_BASE && address < WORK_RAM_END) {
        auto offset = address - WORK_RAM_BASE;
        return static_cast<char *>(wram_) + offset;
    }

    std::cerr << std::format("SystemMemory: unmapped address 0x{:06X}\n", address);
    std::terminate();
}

m_byte SystemMemory::_readByte(m_long address) {
    auto *ptr = convertAddress(address);
    return static_cast<m_byte>(ptr[0]);
}

m_word SystemMemory::_readWord(m_long address) {
    auto *ptr = convertAddress(address);
    return static_cast<m_word>(static_cast<unsigned char>(ptr[0])) * 0x100 +
           static_cast<m_word>(static_cast<unsigned char>(ptr[1]));
}

m_long SystemMemory::_readLong(m_long address) {
    auto *ptr = convertAddress(address);
    return static_cast<m_long>(static_cast<unsigned char>(ptr[0])) * 0x1000000 +
           static_cast<m_long>(static_cast<unsigned char>(ptr[1])) * 0x10000 +
           static_cast<m_long>(static_cast<unsigned char>(ptr[2])) * 0x100 +
           static_cast<m_long>(static_cast<unsigned char>(ptr[3]));
}

void SystemMemory::_writeByte(m_long address, m_byte value) {
    auto *ptr = convertAddress(address);
    ptr[0]    = static_cast<char>(value);
}

void SystemMemory::_writeWord(m_long address, m_word value) {
    auto *ptr = convertAddress(address);
    ptr[0]    = static_cast<char>((value / 0x100) & 0xFF);
    ptr[1]    = static_cast<char>(value & 0xFF);
}

void SystemMemory::_writeLong(m_long address, m_long value) {
    const m_long a = address & 0x00FFFFFFu;

    auto *ptr = convertAddress(address);
    ptr[0]    = static_cast<char>((value / 0x1000000) & 0xFF);
    ptr[1]    = static_cast<char>((value / 0x10000) & 0xFF);
    ptr[2]    = static_cast<char>((value / 0x100) & 0xFF);
    ptr[3]    = static_cast<char>(value & 0xFF);
}

// ── Memory-mapped hardware (VDP / I/O / Z80 / TMSS) ─────────────────────────────
//
// Everything between the ROM (< 0x400000) and work RAM (>= 0xFF0000) is the
// hardware region. VDP ports and the controller I/O ports route to the matching
// subsystem; the remaining areas (Z80, TMSS, PSG, control) are safe stubs —
// reads return 0, writes are ignored — enough to let the recompiled boot run.

bool SystemMemory::isHardware(m_long address) {
    address &= 0x00FFFFFFu;
    return address >= 0x400000u && address < WORK_RAM_BASE;
}

bool SystemMemory::isROM(m_long address) {
    return (address & 0x00FFFFFFu) < ROM_END;
}

m_byte SystemMemory::hwReadByte(m_long address) {
    m_long a = address & 0x00FFFFFFu;
    if (env_ == nullptr)
        return 0;
    if (a >= 0xA00000u && a < 0xA02000u) {
        return env_->z80().readRAMFor68K(static_cast<uint16_t>(a));
    }
    switch (a) {
        case 0xA10001u:
            return env_->hardwareVersionRegister();
        case 0xA10003u:
            return env_->controllers().readPlayer1DataPort();
        case 0xA10005u:
            return env_->controllers().readPlayer2DataPort();
        case 0xA11100u:
            // Convention: bit 0 = 1 while the Z80 hasn't relinquished the bus
            // yet (matches the commonly documented real-hardware meaning).
            return (env_->z80().busRequestAcked()) ? 0x00u : 0x01u;
        default:
            break;
    }
    if (a >= 0xA04000u && a <= 0xA04003u) {
        // readYM2612 stamps the access with the shared wall clock; the 68K
        // instruction counter is not wall-time paced and must not be used here.
        return env_->sound().readYM2612(static_cast<int>(a - 0xA04000u));
    }
    if (a >= 0xC00000u && a < 0xC00010u) {
        m_word w = hwReadWord(a & ~1u);
        return static_cast<m_byte>((a & 1u) ? (w & 0xFFu) : (w >> 8));
    }
    return 0;
}

m_word SystemMemory::hwReadWord(m_long address) {
    m_long a = address & 0x00FFFFFFu;
    if (env_ == nullptr)
        return 0;
    if (a >= 0xA00000u && a < 0xA02000u) {
        m_byte hi = env_->z80().readRAMFor68K(static_cast<uint16_t>(a));
        m_byte lo = env_->z80().readRAMFor68K(static_cast<uint16_t>(a + 1));
        return static_cast<m_word>((static_cast<m_word>(hi) << 8) | lo);
    }
    if (a == 0xA11100u) {
        // The 68k always touches this register with word instructions
        // (e.g. `move.w #$0100,$A11100`); the meaningful bit lives in the
        // high byte, matching the byte-access convention above.
        return static_cast<m_word>(hwReadByte(a)) << 8;
    }
    if (a >= 0xA04000u && a <= 0xA04003u) {
        m_word hi = env_->sound().readYM2612(static_cast<int>(a - 0xA04000u));
        m_word lo = (a + 1 <= 0xA04003u) ? env_->sound().readYM2612(static_cast<int>(a + 1 - 0xA04000u)) : 0u;
        return static_cast<m_word>((hi << 8) | lo);
    }
    if (a >= 0xC00000u && a < 0xC00010u) {
        if (a < 0xC00004u)
            return env_->vdp().readDataPort();
        if (a < 0xC00008u)
            return env_->vdp().readControlPort();
        return env_->vdp().readHVCounter();
    }
    // I/O ports are byte-wide; a word read takes the low (odd) byte.
    return static_cast<m_word>(hwReadByte(a + 1));
}

m_long SystemMemory::hwReadLong(m_long address) {
    return (static_cast<m_long>(hwReadWord(address)) << 16) | static_cast<m_long>(hwReadWord(address + 2));
}

void SystemMemory::hwWriteByte(m_long address, m_byte value) {
    m_long a = address & 0x00FFFFFFu;
    if (env_ == nullptr)
        return;
    if (a >= 0xA00000u && a < 0xA02000u) {
        env_->z80().writeRAMFor68K(static_cast<uint16_t>(a), value);
        return;
    }
    switch (a) {
        case 0xA10003u:
            env_->controllers().writePlayer1DataPort(value);
            return;
        case 0xA10005u:
            env_->controllers().writePlayer2DataPort(value);
            return;
        case 0xA10009u:
            env_->controllers().writePlayer1ControlPort(value);
            return;
        case 0xA1000Bu:
            env_->controllers().writePlayer2ControlPort(value);
            return;
        case 0xA11100u:
            env_->z80().setBusRequest((value & 1u) != 0);
            return;
        case 0xA11200u:
            env_->z80().setReset((value & 1u) == 0); // active-low on real hardware
            return;
        default:
            break;
    }
    if (a >= 0xA04000u && a <= 0xA04003u) {
        env_->sound().writeYM2612(static_cast<int>(a - 0xA04000u), value);
        return;
    }
    if (a >= 0xC00010u && a < 0xC00018u && (a & 1u) != 0) {
        env_->sound().writePSG(value);
        return;
    }
    if (a >= 0xC00000u && a < 0xC00008u) {
        // A byte write to a VDP port puts the byte on both halves of the bus.
        m_word w = static_cast<m_word>((value << 8) | value);
        if ((a & 4u) != 0)
            env_->vdp().writeControlPort(w);
        else
            env_->vdp().writeDataPort(w);
    }
    // TMSS and other control regions: no-op stub.
}

void SystemMemory::hwWriteWord(m_long address, m_word value) {
    m_long a = address & 0x00FFFFFFu;
    if (env_ == nullptr)
        return;
    if (a >= 0xA00000u && a < 0xA02000u) {
        env_->z80().writeRAMFor68K(static_cast<uint16_t>(a), static_cast<m_byte>(value >> 8));
        env_->z80().writeRAMFor68K(static_cast<uint16_t>(a + 1), static_cast<m_byte>(value & 0xFFu));
        return;
    }
    if (a == 0xA11100u) {
        // See hwReadWord: the 68k always uses word access here, with the
        // meaningful bit in the high byte.
        env_->z80().setBusRequest(((value >> 8) & 1u) != 0);
        return;
    }
    if (a == 0xA11200u) {
        env_->z80().setReset(((value >> 8) & 1u) == 0);
        return;
    }
    if (a >= 0xA04000u && a <= 0xA04003u) {
        env_->sound().writeYM2612(static_cast<int>(a - 0xA04000u), static_cast<m_byte>(value >> 8));
        if (a + 1 <= 0xA04003u)
            env_->sound().writeYM2612(static_cast<int>(a + 1 - 0xA04000u), static_cast<m_byte>(value & 0xFFu));
        return;
    }
    if (a >= 0xC00000u && a < 0xC00008u) {
        if ((a & 4u) != 0)
            env_->vdp().writeControlPort(value);
        else
            env_->vdp().writeDataPort(value);
        return;
    }
    hwWriteByte(a + 1, static_cast<m_byte>(value & 0xFFu)); // I/O low byte
}

void SystemMemory::hwWriteLong(m_long address, m_long value) {
    // 32-bit port access = two word accesses (high word first), matching the
    // VDP control/data port protocol (e.g. address-set + register commands).
    hwWriteWord(address, static_cast<m_word>(value >> 16));
    hwWriteWord(address + 2, static_cast<m_word>(value & 0xFFFFu));
}

m_byte SystemMemory::readByte(m_long address) {
    if (isHardware(address))
        return hwReadByte(address);
    if (isROM(address))
        return _readByte(address); // ROM is immutable after loadROM(): lock-free
    SDL_LockMutex(mutex_);
    auto val = _readByte(address);
    SDL_UnlockMutex(mutex_);
    return val;
}

m_word SystemMemory::readWord(m_long address) {
    if (isHardware(address))
        return hwReadWord(address);
    if (isROM(address))
        return _readWord(address); // ROM is immutable after loadROM(): lock-free
    SDL_LockMutex(mutex_);
    auto val = _readWord(address);
    SDL_UnlockMutex(mutex_);
    return val;
}

m_long SystemMemory::readLong(m_long address) {
    if (isHardware(address))
        return hwReadLong(address);
    if (isROM(address))
        return _readLong(address); // ROM is immutable after loadROM(): lock-free
    SDL_LockMutex(mutex_);
    auto val = _readLong(address);
    SDL_UnlockMutex(mutex_);
    return val;
}

void SystemMemory::writeByte(m_long address, m_byte value) {
    if (isHardware(address)) {
        hwWriteByte(address, value);
        return;
    }
    if (isROM(address))
        return; // cartridge ROM is read-only — writes are ignored on hardware
    SDL_LockMutex(mutex_);
    _writeByte(address, value);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::writeWord(m_long address, m_word value) {
    if (isHardware(address)) {
        hwWriteWord(address, value);
        return;
    }
    if (isROM(address))
        return;
    SDL_LockMutex(mutex_);
    _writeWord(address, value);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::writeLong(m_long address, m_long value) {
    if (isHardware(address)) {
        hwWriteLong(address, value);
        return;
    }
    if (isROM(address))
        return;
    SDL_LockMutex(mutex_);
    _writeLong(address, value);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::_copyByte(m_long from, m_long to) {
    auto val = _readByte(from);
    _writeByte(to, val);
}

void SystemMemory::copyByte(m_long from, m_long to) {
    SDL_LockMutex(mutex_);
    _copyByte(from, to);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::copyBytes(m_long from, m_long to, int count) {
    SDL_LockMutex(mutex_);
    for (int i = 0; i < count; i++) {
        _copyByte(from + i, to + i);
    }
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::copyWord(m_long from, m_long to) {
    SDL_LockMutex(mutex_);
    auto val = _readWord(from);
    _writeWord(to, val);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::copyLong(m_long from, m_long to) {
    SDL_LockMutex(mutex_);
    auto val = _readLong(from);
    _writeLong(to, val);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::_copyToBuffer(m_long address, void *ptr, int count) {
    auto *src  = convertAddress(address);
    auto *dest = static_cast<char *>(ptr);
    std::memcpy(dest, src, count);
}

void SystemMemory::copyToBuffer(m_long address, void *ptr, int count) {
    SDL_LockMutex(mutex_);
    _copyToBuffer(address, ptr, count);
    SDL_UnlockMutex(mutex_);
}

void SystemMemory::_writeFromBuffer(void *ptr, m_long address, int count) {
    auto *src  = static_cast<char *>(ptr);
    auto *dest = convertAddress(address);
    std::memcpy(dest, src, count);
}

void SystemMemory::writeFromBuffer(void *ptr, m_long address, int count) {
    SDL_LockMutex(mutex_);
    _writeFromBuffer(ptr, address, count);
    SDL_UnlockMutex(mutex_);
}
