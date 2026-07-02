/**
 * @file MegaDriveEnvironment.cpp
 * @brief Root environment implementation.
 */

#include "MegaDriveEnvironment.hpp"

#include <cstdio>
#include <cstdlib>

namespace {

bool auxFileContainsAddress(const std::string &path, unsigned addr) {
    if (FILE *in = std::fopen(path.c_str(), "r")) {
        char line[64];
        while (std::fgets(line, sizeof line, in)) {
            char *p = line;
            while (*p == ' ' || *p == '\t')
                ++p;
            if (*p == ';' || *p == '#' || *p == '\r' || *p == '\n' || *p == '\0')
                continue;
            if ((static_cast<unsigned>(std::strtoul(p, nullptr, 16)) & 0x00FFFFFFu) == addr) {
                std::fclose(in);
                return true;
            }
        }
        std::fclose(in);
    }
    return false;
}

} // namespace

MegaDriveEnvironment::MegaDriveEnvironment(VDP::Synchronization sync, VDP::Scaling scaling)
    : memory_(this), z80_(this), sound_(this), controllers_(this), vdp_(this, sync, scaling) {
}

MegaDriveEnvironment::~MegaDriveEnvironment() {
    // Safety net in case boot() did not run to completion.
    if (cpuThread_) {
        SDL_WaitThread(cpuThread_, nullptr);
        cpuThread_ = nullptr;
    }
    powerOff();
}

void MegaDriveEnvironment::boot() {
    powerOn();

    cpuDone_.store(false, std::memory_order_release);
    cpuThread_ = SDL_CreateThread(cpuThreadEntry, "CPU", this);

    // Pump SDL events on the main thread so the VDP can present frames
    // (SDL_RunOnMainThread) and so window-close requests are observed.
    SDL_Event event;
    while (!cpuDone_.load(std::memory_order_acquire)) {
        while (SDL_PollEvent(&event)) {
            // Window close or CTRL+Q both request a shutdown.
            if (event.type == SDL_EVENT_QUIT) {
                quitRequested_.store(true, std::memory_order_release);
            } else if (event.type == SDL_EVENT_KEY_DOWN && event.key.key == SDLK_Q && (event.key.mod & SDL_KMOD_CTRL)) {
                quitRequested_.store(true, std::memory_order_release);
            } else if (event.type == SDL_EVENT_KEY_DOWN && event.key.key == SDLK_P && (event.key.mod & SDL_KMOD_CTRL)) {
                // CTRL+P: capture the composited frame to a numbered PNG.
                static unsigned shot = 0;
                char            path[64];
                std::snprintf(path, sizeof path, "sor_screenshot_%03u.png", shot++);
                vdp_.dumpFrameBufferToPNG(path, /*fullRange=*/true);
                std::fprintf(stderr, "[capture] frame -> %s\n", path);
                std::fflush(stderr);
            } else if (event.type == SDL_EVENT_KEY_DOWN && event.key.key == SDLK_S && (event.key.mod & SDL_KMOD_CTRL)) {
                // CTRL+S: capture the full VDP debug view (frame + tile sheets +
                // plane nametables + registers) to a numbered PNG.
                static unsigned shot = 0;
                char            path[64];
                std::snprintf(path, sizeof path, "sor_vdp_%03u.png", shot++);
                vdp_.dumpEverythingToPNG(path, /*fullRange=*/true);
                std::fprintf(stderr, "[capture] VDP debug view -> %s\n", path);
                std::fflush(stderr);
            }
        }
        if (quitRequested_.load(std::memory_order_acquire)) {
            // Give a cooperative run() — one that polls shouldQuit() — a brief
            // window to leave its loop and return for an orderly shutdown, while
            // still pumping events so the VDP can present.
            for (int i = 0; i < 100 && !cpuDone_.load(std::memory_order_acquire); ++i) {
                while (SDL_PollEvent(&event)) {
                }
                SDL_DelayNS(500'000);
            }
            if (!cpuDone_.load(std::memory_order_acquire)) {
                // run() did not return — e.g. the mechanically-generated SoR main
                // loop is an unbounded `bra` that never polls shouldQuit(). Force
                // the process down: returning from main() does not reliably end it
                // on macOS, where SDL parks the real main thread in its own run
                // loop to service SDL_RunOnMainThread (the VDP's frame
                // presentation). _Exit() tears every thread down immediately and
                // lets the OS reclaim the window.
                std::_Exit(0);
            }
            break;
        }
        SDL_DelayNS(250'000);
    }

    // run() returned (on its own, or cooperatively after a quit request): clean up.
    SDL_WaitThread(cpuThread_, nullptr);
    cpuThread_ = nullptr;
    powerOff();
}

m_byte MegaDriveEnvironment::hardwareVersionRegister() const {
    m_byte value = 0x00; // Model 1, no TMSS, JP + 60 Hz by default.
    if (languagePin() == LanguagePin::Overseas)
        value |= 0x80;
    if (videoStandard() == VideoStandard::Hz50)
        value |= 0x40;
    return value;
}

void MegaDriveEnvironment::logFrame(unsigned frame, bool displayEnabled) {
    // Progression-state probe: which game mode the state machine is in ($FF00),
    // the VBlank-routine / palette-upload requests ($FA00/$FA01), the intro
    // counter the title build polls ($FA30), the VBlank jump-table index ($FF06),
    // and two samples of the master palette buffer ($FFF400) so a stuck fade
    // shows up as palette words that never brighten frame to frame.
    m_word mode = memory_.readWord(0xFFFFFF00u);
    m_byte fa30 = memory_.readByte(0xFFFFFA30u);
    m_word fb06 = memory_.readWord(0xFFFFFB06u); // story-step frame delay

    // Palette pipeline: city palette -> $DD80 (master) -> fade by $FA61 -> $F400
    // (live CRAM buffer) -> DMA to CRAM. Sample the master and the live buffer at
    // the same offset, plus the fade level, to see where the chain breaks.
    m_word mst08 = memory_.readWord(0xFFFFDD90u); // master palette, entry 8
    m_word mst18 = memory_.readWord(0xFFFFDDA0u); // master palette, entry 16
    m_word liv08 = memory_.readWord(0xFFFFF410u); // live buffer, entry 8
    m_byte fa61  = memory_.readByte(0xFFFFFA61u); // fade level
    m_byte fa63  = memory_.readByte(0xFFFFFA63u); // fade flag
    m_byte fa05  = memory_.readByte(0xFFFFFA05u); // fade mode flags

    std::fprintf(stderr,
                 "[sor] t=%2us frame=%u  IPL=%d  fn=$%06X  mode($FF00)=%04X cnt($FA30)=%02X gate($FB06)=%04X  "
                 "master[$DD90]=%04X master[$DDA0]=%04X  live[$F410]=%04X  fade($FA61)=%02X f63=%02X f05=%02X\n",
                 frame / 60,
                 frame,
                 cpu_.interruptMask(),
                 traceFn_.load(std::memory_order_relaxed),
                 mode,
                 fa30,
                 fb06,
                 mst08,
                 mst18,
                 liv08,
                 fa61,
                 fa63,
                 fa05);

    const Sound::Diagnostics snd = sound_.diagnostics();
    std::fprintf(stderr,
                 "[snd] frames=%llu queued=%llu late=%llu under=%llu over=%llu clip=%llu timers=%llu peakL=%d "
                 "peakR=%d\n",
                 static_cast<unsigned long long>(snd.audioFramesRendered),
                 static_cast<unsigned long long>(snd.queuedEvents),
                 static_cast<unsigned long long>(snd.lateEvents),
                 static_cast<unsigned long long>(snd.underruns),
                 static_cast<unsigned long long>(snd.overruns),
                 static_cast<unsigned long long>(snd.clippedSamples),
                 static_cast<unsigned long long>(snd.ymTimerExpirations),
                 snd.peakLeft,
                 snd.peakRight);
    std::fflush(stderr);
}

void MegaDriveEnvironment::confirmSpeculative(m_long addr) {
    if (auxAddrFile_.empty())
        return;

    unsigned a = static_cast<unsigned>(addr & 0x00FFFFFFu);
    if (!confirmedSpeculative_.insert(a).second)
        return; // already logged this run
    if (auxFileContainsAddress(auxAddrFile_, a))
        return; // already known; not a newly confirmed speculative candidate
    std::fprintf(stderr, "[speculative] confirmed: %06X\n", a);
    if (FILE *out = std::fopen(auxAddrFile_.c_str(), "a")) {
        std::fprintf(out, "%06X\n", a);
        std::fclose(out);
    }
}

void MegaDriveEnvironment::reportUnhandledDispatch(m_long addr) {
    unsigned a  = static_cast<unsigned>(addr & 0x00FFFFFFu);
    unsigned fn = static_cast<unsigned>(lastFunction() & 0x00FFFFFFu);

    std::fprintf(stderr, "indirect dispatch to unknown address $%06X (in fn $%06X)\n", a, fn);

    std::fprintf(stderr,
                 "[dispatch] SR=$%04X SSP=$%06X USP=$%06X PC=$%06X\n",
                 static_cast<unsigned>(cpu_.status()),
                 static_cast<unsigned>(cpu_.ssp & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.usp & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.pc & 0x00FFFFFFu));
    std::fprintf(stderr,
                 "[dispatch] D0=$%08X D1=$%08X D2=$%08X D3=$%08X "
                 "D4=$%08X D5=$%08X D6=$%08X D7=$%08X\n",
                 static_cast<unsigned>(cpu_.d[0]),
                 static_cast<unsigned>(cpu_.d[1]),
                 static_cast<unsigned>(cpu_.d[2]),
                 static_cast<unsigned>(cpu_.d[3]),
                 static_cast<unsigned>(cpu_.d[4]),
                 static_cast<unsigned>(cpu_.d[5]),
                 static_cast<unsigned>(cpu_.d[6]),
                 static_cast<unsigned>(cpu_.d[7]));
    std::fprintf(stderr,
                 "[dispatch] A0=$%06X A1=$%06X A2=$%06X A3=$%06X "
                 "A4=$%06X A5=$%06X A6=$%06X\n",
                 static_cast<unsigned>(cpu_.a[0] & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.a[1] & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.a[2] & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.a[3] & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.a[4] & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.a[5] & 0x00FFFFFFu),
                 static_cast<unsigned>(cpu_.a[6] & 0x00FFFFFFu));
    std::fprintf(stderr,
                 "[dispatch] RAM FF00=%04X FB15=%02X FB06=%04X FA1A=%02X "
                 "FA30=%02X F904=%02X F905=%02X\n",
                 static_cast<unsigned>(memory_.readWord(0xFFFFFF00u)),
                 static_cast<unsigned>(memory_.readByte(0xFFFFFB15u)),
                 static_cast<unsigned>(memory_.readWord(0xFFFFFB06u)),
                 static_cast<unsigned>(memory_.readByte(0xFFFFFA1Au)),
                 static_cast<unsigned>(memory_.readByte(0xFFFFFA30u)),
                 static_cast<unsigned>(memory_.readByte(0xFFFFF904u)),
                 static_cast<unsigned>(memory_.readByte(0xFFFFF905u)));
    std::fprintf(stderr, "[dispatch] trace history:");
    unsigned firstTrace = traceHistoryPos_ > 16 ? traceHistoryPos_ - 16 : 0;
    for (unsigned i = firstTrace; i < traceHistoryPos_; ++i) {
        std::fprintf(stderr, " $%06X", static_cast<unsigned>(traceHistory_[i & 0x0Fu] & 0x00FFFFFFu));
    }
    std::fprintf(stderr, "\n");
    const m_long a0 = cpu_.a[0] & 0x00FFFFFFu;
    std::fprintf(stderr,
                 "[dispatch] object@A0 type=%02X flags=%02X state30=%02X next31=%02X "
                 "ptr4=%08X anim8=%04X timerE=%04X stack=%08X %08X %08X\n",
                 static_cast<unsigned>(memory_.readByte(a0 + 0)),
                 static_cast<unsigned>(memory_.readByte(a0 + 1)),
                 static_cast<unsigned>(memory_.readByte(a0 + 0x30)),
                 static_cast<unsigned>(memory_.readByte(a0 + 0x31)),
                 static_cast<unsigned>(memory_.readLong(a0 + 4)),
                 static_cast<unsigned>(memory_.readWord(a0 + 8)),
                 static_cast<unsigned>(memory_.readWord(a0 + 0x0E)),
                 static_cast<unsigned>(memory_.readLong(cpu_.ssp)),
                 static_cast<unsigned>(memory_.readLong(cpu_.ssp + 4)),
                 static_cast<unsigned>(memory_.readLong(cpu_.ssp + 8)));

    const bool invalidCodeTarget = (a < 0x000200u) || ((a & 1u) != 0);
    if (invalidCodeTarget) {
        std::fprintf(stderr,
                     "[aux] refusing to seed invalid code address $%06X "
                     "(68K code starts at $000200 and must be word-aligned)\n",
                     a);
        if (!auxAddrFile_.empty()) {
            std::_Exit(44);
        }
    }

    if (auxAddrFile_.empty()) {
        std::abort(); // default: no aux file configured
    }

    // Already seeded? Then a previous pass added it but regenerating produced no
    // handler — stop the discovery loop (exit 43) instead of spinning forever.
    if (auxFileContainsAddress(auxAddrFile_, a)) {
        std::fprintf(
            stderr, "[aux] $%06X already seeded in %s — seeding did not help; stopping\n", a, auxAddrFile_.c_str());
        std::_Exit(43);
    }

    // Record the new target and exit (42) so the discovery loop re-seeds and
    // regenerates. _Exit avoids the unreliable SDL/global teardown on this path.
    if (FILE *out = std::fopen(auxAddrFile_.c_str(), "a")) {
        std::fprintf(out, "%06X\n", a);
        std::fclose(out);
        std::fprintf(stderr, "[aux] recorded $%06X to %s\n", a, auxAddrFile_.c_str());
        std::_Exit(42);
    }
    std::fprintf(stderr, "[aux] could not write %s\n", auxAddrFile_.c_str());
    std::abort();
}

int MegaDriveEnvironment::cpuThreadEntry(void *data) {
    auto *self = static_cast<MegaDriveEnvironment *>(data);
    self->run();
    self->cpuDone_.store(true, std::memory_order_release);
    return 0;
}

void MegaDriveEnvironment::runVDPInterrupts() {
    VDP::Interrupt irq;
    while (vdp_.popInterrupt(irq)) {
        switch (irq.type) {
            case VDP::Interrupt::HSync:
                hSync(irq.line);
                break;
            case VDP::Interrupt::VSync:
                vSync();
                break;
        }
    }
}

void MegaDriveEnvironment::powerOn() {
    cpu_ = CPU68K{};
    cpu_.setStatus(0x2700);
    m68kMasterCycles_.store(0, std::memory_order_release);
    vdp_.start();
    z80_.start();
    sound_.start();
}

void MegaDriveEnvironment::powerOff() {
    sound_.stop();
    z80_.stop();
    vdp_.stop();
}
