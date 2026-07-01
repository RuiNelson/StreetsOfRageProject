#include "Z80.hpp"

#include "system/MegaDriveEnvironment.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

extern "C" {
void         z80_init(const void *config, int (*irqcallback)(int));
void         z80_reset(void);
void         z80_run(unsigned int cycles);
void         z80_set_cycle_counter(unsigned int cycles);
unsigned int z80_get_cycle_counter(void);
void         z80_set_irq_line(unsigned int state);
void         z80_set_nmi_line(unsigned int state);

extern void (*z80_writemem)(unsigned int address, unsigned char data);
extern unsigned char (*z80_readmem)(unsigned int address);
extern void (*z80_writeport)(unsigned int port, unsigned char data);
extern unsigned char (*z80_readport)(unsigned int port);
}

namespace {
constexpr uint64_t kZ80Clock = 3'579'545;
// The GPX-derived core's cycle tables are premultiplied by 15 (e.g. `4*15`),
// so Z80.cycles counts Mega Drive MASTER cycles, not T-states. Convert at the
// boundary: ×15 when feeding T-states in, and the counter maps 1:1 onto the
// shared master-cycle timeline.
constexpr uint32_t kMasterCyclesPerZ80TState = 15;
constexpr uint32_t kMaxRunChunkTStates       = 512;
constexpr uint64_t kCycleCounterWrapNear     = 0x70000000u;
// Genesis Plus GX asserts the Z80 INT at VBlank and clears it at the end of
// that scanline; hold it for one scanline of emulated time (~228 T-states).
constexpr uint64_t kIRQHoldTStates = 228;
// After a host stall, don't try to catch up more than ~2 frames of Z80 time:
// real hardware doesn't catch up either, and a large burst would stamp sound
// events far ahead of the shared wall clock.
constexpr double  kMaxBacklogTStates = 120'000.0;
constexpr uint8_t CLEAR_LINE         = 0;
constexpr uint8_t ASSERT_LINE        = 1;

Z80 *gActiveZ80 = nullptr;
} // namespace

Z80::Z80(MegaDriveEnvironment *env) : env_(env), mutex_(SDL_CreateMutex()) {
    installCallbacks();
    SDL_LockMutex(mutex_);
    resetCPU();
    SDL_UnlockMutex(mutex_);
}

Z80::~Z80() {
    stop();
    if (gActiveZ80 == this)
        gActiveZ80 = nullptr;
    if (mutex_) {
        SDL_DestroyMutex(mutex_);
        mutex_ = nullptr;
    }
}

void Z80::start() {
    if (running_.exchange(true))
        return;
    installCallbacks();
    thread_ = SDL_CreateThread(threadEntry, "Z80", this);
}

void Z80::stop() {
    running_.store(false);
    if (thread_) {
        SDL_WaitThread(thread_, nullptr);
        thread_ = nullptr;
    }
}

void Z80::installCallbacks() {
    gActiveZ80    = this;
    z80_readmem   = staticRead8;
    z80_writemem  = staticWrite8;
    z80_readport  = staticReadPort;
    z80_writeport = staticWritePort;
}

void Z80::setBusRequest(bool requested) {
    busRequested_.store(requested, std::memory_order_release);
    if (requested) {
        busAcked_.store(true, std::memory_order_release);
    } else if (!resetHeld_.load(std::memory_order_acquire)) {
        busAcked_.store(false, std::memory_order_release);
    }
}

bool Z80::busRequestAcked() const {
    return busAcked_.load(std::memory_order_acquire);
}

void Z80::setReset(bool held) {
    const bool wasHeld = resetHeld_.exchange(held, std::memory_order_acq_rel);
    if (held) {
        busAcked_.store(true, std::memory_order_release);
        return;
    }

    if (wasHeld) {
        SDL_LockMutex(mutex_);
        resetCPU();
        SDL_UnlockMutex(mutex_);
    }

    if (!busRequested_.load(std::memory_order_acquire))
        busAcked_.store(false, std::memory_order_release);
}

void Z80::pulseVBlankIRQ() {
    irqPending_.store(true, std::memory_order_release);
}

int Z80::threadEntry(void *data) {
    static_cast<Z80 *>(data)->runThread();
    return 0;
}

void Z80::runThread() {
    uint64_t last        = SDL_GetTicksNS();
    double   cycleCredit = 0.0;

    const bool traceRate    = std::getenv("SOR_Z80_TRACE") != nullptr;
    uint64_t   traceLastNS  = last;
    uint64_t   traceTStates = 0;
    uint64_t   traceStalls  = 0;

    while (running_.load(std::memory_order_acquire)) {
        const uint64_t now = SDL_GetTicksNS();
        cycleCredit += (static_cast<double>(now - last) * static_cast<double>(kZ80Clock)) / 1'000'000'000.0;
        cycleCredit = std::min(cycleCredit, kMaxBacklogTStates);
        last        = now;

        if (traceRate && now - traceLastNS >= 1'000'000'000ull) {
            std::fprintf(stderr,
                         "[z80] tstates/s=%llu stallPolls/s=%llu\n",
                         static_cast<unsigned long long>(traceTStates),
                         static_cast<unsigned long long>(traceStalls));
            traceTStates = 0;
            traceStalls  = 0;
            traceLastNS  = now;
        }

        if (resetHeld_.load(std::memory_order_acquire) || busRequested_.load(std::memory_order_acquire)) {
            busAcked_.store(true, std::memory_order_release);
            ++traceStalls;
            SDL_DelayNS(500'000);
            cycleCredit = std::min(cycleCredit, 256.0);
            continue;
        }

        busAcked_.store(false, std::memory_order_release);

        int guard = 0;
        while (cycleCredit >= 4.0 && guard++ < 64 && !busRequested_.load(std::memory_order_acquire) &&
               !resetHeld_.load(std::memory_order_acquire)) {
            const uint32_t tStates = static_cast<uint32_t>(std::min<double>(cycleCredit, kMaxRunChunkTStates));

            SDL_LockMutex(mutex_);
            installCallbacks();
            runCoreForTStates(tStates);
            SDL_UnlockMutex(mutex_);

            cycleCredit -= tStates;
            traceTStates += tStates;
        }

        SDL_DelayNS(100'000);
    }
}

void Z80::resetCPU() {
    installCallbacks();
    z80_init(nullptr, nullptr);
    z80_reset();
    z80_set_irq_line(CLEAR_LINE);
    z80_set_nmi_line(CLEAR_LINE);
    executedCoreMasterCycles_ = 0;
    cycleEpochMasterCycles_   = 0;
    bankRegister_             = 0;
    irqClearAtMasterCycles_   = 0;
    irqLineAsserted_          = false;
    irqPending_.store(false, std::memory_order_release);
}

void Z80::runCoreForTStates(uint32_t tStates) {
    if (tStates == 0)
        return;

    if (executedCoreMasterCycles_ > kCycleCounterWrapNear) {
        cycleEpochMasterCycles_ += executedCoreMasterCycles_;
        irqClearAtMasterCycles_ = (irqClearAtMasterCycles_ > executedCoreMasterCycles_)
                                    ? irqClearAtMasterCycles_ - executedCoreMasterCycles_
                                    : 0;
        z80_set_cycle_counter(0);
        executedCoreMasterCycles_ = 0;
    }

    // Re-anchor this core's master-cycle timeline to the shared audio wall
    // clock (forward only), so sound-event timestamps stay aligned with the
    // renderer across 68K-driven resets and bus-request stalls.
    if (env_) {
        const uint64_t nowMaster = env_->sound().masterCyclesNow();
        if (cycleEpochMasterCycles_ + executedCoreMasterCycles_ < nowMaster)
            cycleEpochMasterCycles_ = nowMaster - executedCoreMasterCycles_;
    }

    if (irqPending_.exchange(false, std::memory_order_acq_rel)) {
        z80_set_irq_line(ASSERT_LINE);
        irqLineAsserted_        = true;
        irqClearAtMasterCycles_ = executedCoreMasterCycles_ + (kIRQHoldTStates * kMasterCyclesPerZ80TState);
    }

    const uint64_t targetMasterCycles =
        executedCoreMasterCycles_ + (static_cast<uint64_t>(tStates) * kMasterCyclesPerZ80TState);
    if (irqLineAsserted_ && irqClearAtMasterCycles_ < targetMasterCycles) {
        if (irqClearAtMasterCycles_ > executedCoreMasterCycles_)
            z80_run(static_cast<unsigned int>(irqClearAtMasterCycles_));
        z80_set_irq_line(CLEAR_LINE);
        irqLineAsserted_ = false;
    }
    z80_run(static_cast<unsigned int>(targetMasterCycles));
    executedCoreMasterCycles_ = static_cast<uint64_t>(z80_get_cycle_counter());
}

uint64_t Z80::currentMasterCyclesForCore() const {
    return cycleEpochMasterCycles_ + static_cast<uint64_t>(z80_get_cycle_counter());
}

m_byte Z80::readRAMFor68K(uint16_t address) {
    SDL_LockMutex(mutex_);
    const m_byte value = ram_[address & 0x1FFFu];
    SDL_UnlockMutex(mutex_);
    return value;
}

void Z80::writeRAMFor68K(uint16_t address, m_byte value) {
    SDL_LockMutex(mutex_);
    ram_[address & 0x1FFFu] = value;
    SDL_UnlockMutex(mutex_);
}

uint8_t Z80::read8ForCore(uint16_t address) {
    if (address < 0x4000)
        return ram_[address & 0x1FFFu];

    if (address >= 0x4000 && address < 0x6000)
        return env_->sound().readYM2612At(currentMasterCyclesForCore(), address & 3u);

    if ((address & 0xFF00u) == 0x7F00u)
        return env_->memory().readByte(0x00C00000u | (address & 0x00FFu));

    if (address >= 0x8000) {
        const uint32_t m68kAddress = ((bankRegister_ << 15) + (address & 0x7FFFu)) & 0x00FFFFFFu;
        return env_->memory().readByte(m68kAddress);
    }

    return 0xFF;
}

void Z80::write8ForCore(uint16_t address, uint8_t value) {
    if (address < 0x4000) {
        ram_[address & 0x1FFFu] = value;
        return;
    }

    if (address >= 0x4000 && address < 0x6000) {
        env_->sound().writeYM2612At(currentMasterCyclesForCore(), address & 3u, value);
        return;
    }

    if ((address & 0xFF00u) == 0x6000u) {
        bankRegister_ = ((bankRegister_ >> 1) | ((value & 1u) << 8)) & 0x1FFu;
        return;
    }

    if ((address & 0xFF00u) == 0x7F00u) {
        const uint32_t vdpAddress = 0x00C00000u | (address & 0x00FFu);
        if (vdpAddress >= 0x00C00010u && vdpAddress < 0x00C00018u && (vdpAddress & 1u) != 0)
            env_->sound().writePSGAt(currentMasterCyclesForCore(), value);
        else
            env_->memory().writeByte(vdpAddress, value);
        return;
    }

    if (address >= 0x8000) {
        const uint32_t m68kAddress = ((bankRegister_ << 15) + (address & 0x7FFFu)) & 0x00FFFFFFu;
        env_->memory().writeByte(m68kAddress, value);
    }
}

uint8_t Z80::readPortForCore(uint16_t port) {
    (void)port;
    return 0xFF;
}

void Z80::writePortForCore(uint16_t port, uint8_t value) {
    (void)port;
    (void)value;
}

uint8_t Z80::staticRead8(unsigned int address) {
    return gActiveZ80 ? gActiveZ80->read8ForCore(static_cast<uint16_t>(address)) : 0xFF;
}

void Z80::staticWrite8(unsigned int address, uint8_t value) {
    if (gActiveZ80)
        gActiveZ80->write8ForCore(static_cast<uint16_t>(address), value);
}

uint8_t Z80::staticReadPort(unsigned int port) {
    return gActiveZ80 ? gActiveZ80->readPortForCore(static_cast<uint16_t>(port)) : 0xFF;
}

void Z80::staticWritePort(unsigned int port, uint8_t value) {
    if (gActiveZ80)
        gActiveZ80->writePortForCore(static_cast<uint16_t>(port), value);
}
