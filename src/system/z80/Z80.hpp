#pragma once

#include "data_types.hpp"

#include <SDL3/SDL.h>
#include <atomic>

class MegaDriveEnvironment;

/**
 * @file Z80.hpp
 * @brief Z80 sub-CPU subsystem.
 *
 * On real hardware the Z80 drives the sound chips and owns 8 KiB of RAM
 * (0xA00000-0xA01FFF). The interpreter itself is the vendored MAME Z80 core
 * (`gpgx_z80/z80.c`, ported from Genesis-Plus-GX); this class wraps that
 * single-instance, function-pointer-based C API with the per-subsystem
 * thread/lifecycle shape used by the rest of the platform.
 *
 * The Z80 core only has ONE global register file (`Z80_Regs Z80;`) and four
 * global memory/port callback pointers, so only one Z80 instance may exist
 * per process — acceptable here since MegaDriveEnvironment owns exactly one.
 */
class Z80 {
    public:
    /// Stores the back-reference to the owning environment. Does not start the thread.
    explicit Z80(MegaDriveEnvironment *env);
    ~Z80();

    Z80(const Z80 &)            = delete;
    Z80 &operator=(const Z80 &) = delete;

    /// Spawns the Z80 thread (held in reset until setReset(false) is called).
    void start();

    /// Signals the Z80 thread to exit and joins it.
    void stop();

    /// Z80 RAM size in bytes (8 KiB).
    static constexpr int RAM_SIZE = 0x2000;

    /// Raw access to Z80 RAM (0xA00000-0xA01FFF on the 68k bus).
    m_byte *ram() {
        return ram_;
    }

    /// 68k-side bus request line ($A11100 bit 0). While requested, the Z80
    /// thread parks so the 68k can access Z80 RAM/YM2612 without racing the
    /// interpreter.
    void setBusRequest(bool requested);

    /// True once the Z80 has actually parked in response to a bus request
    /// (the bit the 68k boot code polls before touching Z80 RAM).
    bool busRequestAcked() const;

    /// 68k-side reset line ($A11200 bit 0, active-low on real hardware —
    /// callers pass the logical "asserted" state, not the raw bit).
    void setReset(bool asserted);

    /// Pulses the Z80's maskable interrupt line for one frame, mirroring the
    /// real hardware's vblank-driven IM1 interrupt. Call once per vSync.
    void pulseVBlankIRQ();

    private:
    static int threadEntry(void *data);
    int        run();

    m_byte readMem(m_word address);
    void   writeMem(m_word address, m_byte value);
    m_byte readPort(m_byte port);
    void   writePort(m_byte port, m_byte value);

    void buildReadMap();

    MegaDriveEnvironment *env_ = nullptr;
    m_byte                ram_[RAM_SIZE]{};
    m_long                zbank_ = 0;

    SDL_Thread *thread_  = nullptr;
    bool        running_ = false;

    std::atomic<bool> busRequested_{false};
    std::atomic<bool> busAcked_{false};
    std::atomic<bool> resetAsserted_{true};
    std::atomic<bool> irqPending_{false};

    SDL_Mutex *runMutex_ = nullptr; // held during z80_run(); setBusRequest syncs on it

    friend m_byte z80TrampolineReadMem(unsigned int address);
    friend void   z80TrampolineWriteMem(unsigned int address, unsigned char data);
    friend m_byte z80TrampolineReadPort(unsigned int port);
    friend void   z80TrampolineWritePort(unsigned int port, unsigned char data);
};
