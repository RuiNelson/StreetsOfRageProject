/**
 * @file Z80.cpp
 * @brief Z80 sub-CPU subsystem, backed by the vendored MAME Z80 core.
 */

#include "Z80.hpp"

#include "system/MegaDriveEnvironment.hpp"
#include "system/sound/Sound.hpp"

#include "gpgx_z80/z80.h"

namespace {
// The vendored core is single-instance global state (one `Z80_Regs Z80;`,
// four global callback pointers) — this project only ever owns one Z80, so a
// single back-pointer is sufficient to bridge the C callbacks to the
// instance's member functions. `class Z80` (elaborated-type-specifier) is
// required here: z80.h's global `Z80_Regs Z80;` is also in scope and would
// otherwise hide our class name at namespace scope.
class Z80 *g_activeZ80 = nullptr;

// Opcode fetch (cpu_readop/cpu_readop_arg in z80.c) reads directly through
// z80_readmap, bypassing our read callback. Pages outside Z80 RAM (the
// YM2612/bank/VDP-passthrough regions) aren't expected to contain code for
// any driver this project runs, so they're backed by a shared all-zero page
// — opcode 0x00 is NOP, so straying into one is a harmless infinite NOP
// rather than a null-pointer fetch.
m_byte g_dummyPage[1024]{};
} // namespace

m_byte z80TrampolineReadMem(unsigned int address) {
    return g_activeZ80 ? g_activeZ80->readMem(static_cast<m_word>(address)) : 0xFF;
}

void z80TrampolineWriteMem(unsigned int address, unsigned char data) {
    if (g_activeZ80)
        g_activeZ80->writeMem(static_cast<m_word>(address), data);
}

m_byte z80TrampolineReadPort(unsigned int port) {
    return g_activeZ80 ? g_activeZ80->readPort(static_cast<m_byte>(port)) : 0xFF;
}

void z80TrampolineWritePort(unsigned int port, unsigned char data) {
    if (g_activeZ80)
        g_activeZ80->writePort(static_cast<m_byte>(port), data);
}

namespace {
int z80TrampolineIrqCallback(int /*irqLine*/) {
    // Mega Drive only uses IM1 (RST 38h) — the vector returned here is only
    // consulted in IM2, so this is never reached in practice.
    return 0;
}
} // namespace

Z80::Z80(MegaDriveEnvironment *env) : env_(env) {
    g_activeZ80 = this;
}

Z80::~Z80() {
    stop();
    if (g_activeZ80 == this)
        g_activeZ80 = nullptr;
}

void Z80::start() {
    if (thread_) {
        return;
    }
    if (!runMutex_)
        runMutex_ = SDL_CreateMutex();
    running_ = true;
    thread_  = SDL_CreateThread(threadEntry, "Z80", this);
}

void Z80::stop() {
    running_ = false;
    if (thread_) {
        SDL_WaitThread(thread_, nullptr);
        thread_ = nullptr;
    }
    if (runMutex_) {
        SDL_DestroyMutex(runMutex_);
        runMutex_ = nullptr;
    }
}

void Z80::setBusRequest(bool requested) {
    busRequested_.store(requested, std::memory_order_relaxed);
    // Grant the bus synchronously on request. In this HLE model the 68000 only
    // takes the Z80 bus to copy into Z80 RAM (a plain array), so there is nothing
    // to wait for. Acking here — instead of waiting for the 60 Hz-paced Z80 thread
    // to notice the request on its next iteration — stops the 68000 from spinning
    // on $A11100 (the bus-request handshake at $01062C) for up to a frame. The
    // thread still observes busRequested_ and parks itself; on release it clears
    // busAcked_ when it next runs.
    if (requested) {
        // Sync point: wait for any in-progress z80_run() to finish before
        // granting the bus, so the 68K never races ram_[] with the Z80 thread.
        SDL_LockMutex(runMutex_);
        SDL_UnlockMutex(runMutex_);
        busAcked_.store(true, std::memory_order_relaxed);
        ram_[0x1FFD] &= ~static_cast<m_byte>(0x80); // ponytail: HLE clear Z80 driver busy flag; avoids frame-level stall in sub_073298
    }
}

bool Z80::busRequestAcked() const {
    return busAcked_.load(std::memory_order_relaxed);
}

void Z80::setReset(bool asserted) {
    resetAsserted_.store(asserted, std::memory_order_relaxed);
}

void Z80::pulseVBlankIRQ() {
    irqPending_.store(true, std::memory_order_relaxed);
}

void Z80::buildReadMap() {
    for (int page = 0; page < 64; ++page) {
        if (page < 16) {
            // $0000-$3FFF: 8 KiB RAM mirrored twice (16 pages of 1 KiB / 8 = mod 8).
            z80_readmap[page] = ram_ + (page % 8) * 1024;
        } else {
            z80_readmap[page] = g_dummyPage;
        }
    }
}

m_byte Z80::readMem(m_word address) {
    if (address < 0x4000) {
        return ram_[address & 0x1FFF];
    }
    if (address < 0x6000) {
        return env_->sound().readYM2612(address & 3);
    }
    if (address < 0x8000) {
        if ((address & 0xFF00) == 0x7F00) {
            // $7F00-$7FFF: passthrough to the 68k's $C00000 VDP/PSG bus.
            return env_->memory().readByte(0xC00000u | (address & 0x1Fu));
        }
        return 0xFF; // $6000-$7EFF (bank register region): write-only, unused read
    }
    // $8000-$FFFF: 32 KiB window into the 68k address space, relocated by zbank_.
    return env_->memory().readByte(zbank_ | (address & 0x7FFFu));
}

void Z80::writeMem(m_word address, m_byte value) {
    if (address < 0x4000) {
        ram_[address & 0x1FFF] = value;
        return;
    }
    if (address < 0x6000) {
        env_->sound().writeYM2612(address & 3, value);
        return;
    }
    if (address < 0x8000) {
        if ((address & 0xFF00) == 0x6000) {
            // Bank register: one bit shifted in per write, MSB-first into bits 23-15.
            zbank_ = ((zbank_ >> 1) | (static_cast<m_long>(value & 1) << 23)) & 0xFF8000u;
            return;
        }
        if ((address & 0xFF00) == 0x7F00) {
            env_->memory().writeByte(0xC00000u | (address & 0x1Fu), value);
        }
        return;
    }
    env_->memory().writeByte(zbank_ | (address & 0x7FFFu), value);
}

m_byte Z80::readPort(m_byte /*port*/) {
    // Z80 port I/O is an SMS/Game Gear concept; the Mega Drive's Z80 never
    // uses IN/OUT, so this is unreachable in practice.
    return 0xFF;
}

void Z80::writePort(m_byte /*port*/, m_byte /*value*/) {
}

int Z80::threadEntry(void *data) {
    return static_cast<Z80 *>(data)->run();
}

int Z80::run() {
    constexpr double   kClockHz        = 3579545.0; // NTSC Z80/PSG master clock
    constexpr double   kFrameSeconds   = 1.0 / 59.94;
    constexpr unsigned kCyclesPerFrame = static_cast<unsigned>(kClockHz * kFrameSeconds);
    const Uint64       frameNs         = static_cast<Uint64>(kFrameSeconds * 1e9);

    buildReadMap();
    z80_init(nullptr, z80TrampolineIrqCallback);
    z80_readmem   = z80TrampolineReadMem;
    z80_writemem  = z80TrampolineWriteMem;
    z80_readport  = z80TrampolineReadPort;
    z80_writeport = z80TrampolineWritePort;

    bool needsReset = true;

    while (running_) {
        Uint64 frameStart = SDL_GetTicksNS();

        if (resetAsserted_.load(std::memory_order_relaxed)) {
            needsReset = true;
            if (busRequested_.load(std::memory_order_relaxed))
                busAcked_.store(true, std::memory_order_relaxed);
            SDL_DelayNS(100'000);
            continue;
        }
        if (needsReset) {
            z80_reset();
            needsReset = false;
        }
        if (busRequested_.load(std::memory_order_relaxed)) {
            busAcked_.store(true, std::memory_order_relaxed);
            SDL_DelayNS(100'000);
            continue;
        }
        busAcked_.store(false, std::memory_order_relaxed);

        bool vblank = irqPending_.exchange(false, std::memory_order_relaxed);
        if (vblank)
            z80_set_irq_line(ASSERT_LINE);

        SDL_LockMutex(runMutex_);
        z80_run(kCyclesPerFrame);
        SDL_UnlockMutex(runMutex_);
        // z80_run()'s argument is an absolute target against the core's
        // free-running Z80.cycles counter, not a per-call increment — carry
        // any overshoot into the next frame instead of letting Z80.cycles
        // grow unboundedly (it's a UINT32, ~20 minutes of headroom at this
        // clock) or re-passing the same constant and starving the core after
        // its first frame. `::Z80` (global) is needed here, not `Z80`
        // (this class) — see the injected-class-name note on g_activeZ80.
        ::Z80.cycles -= kCyclesPerFrame;

        if (vblank)
            z80_set_irq_line(CLEAR_LINE);

        Uint64 elapsed = SDL_GetTicksNS() - frameStart;
        if (elapsed < frameNs) {
            SDL_DelayNS(frameNs - elapsed);
        }
    }
    return 0;
}
