#pragma once

#include "Sound.hpp"
#include "SystemMemory.hpp"
#include "Z80.hpp"
#include "controllers/Controllers.hpp"
#include "cpu/CPU68K.hpp"
#include "graphics/VDP.hpp"

#include <atomic>
#include <bit>
#include <cstdint>
#include <string>
#include <thread>
#include <unordered_set>

/**
 * @file MegaDriveEnvironment.hpp
 * @brief Root object that owns a Mega Drive's subsystems.
 *
 * A MegaDriveEnvironment models one Sega Mega Drive: it owns the system
 * memory, the VDP, the controllers, the Z80 and the sound hardware. The CPU
 * is not emulated — instead, games and programs are written as **subclasses**
 * of this type and provide the cartridge's start-up code by overriding run().
 *
 * Each subsystem holds a back-reference to its environment and reaches the
 * others through it (for example the VDP performs DMA via
 * `environment->memory()`). Subsystems run on their own threads; the
 * environment starts and stops them with powerOn() / powerOff().
 *
 * ## Lifecycle and the interrupt model
 *
 * Construction only wires the subsystems together; nothing runs yet. The host
 * program drives everything through boot():
 *
 *  - boot() powers the subsystems on, launches run() on a dedicated "CPU"
 *    thread, and pumps SDL events on the calling (main) thread until run()
 *    returns. The SDL event pump on the main thread is required so the VDP can
 *    present frames (it uses SDL_RunOnMainThread).
 *
 *  - run() is the cartridge entry point, overridden by the game. It executes
 *    on the CPU thread.
 *
 * The VDP does **not** call vSync()/hSync() directly. Instead its render thread
 * *schedules* interrupts; the program drains and dispatches them by calling
 * runVDPInterrupts() from its run() loop. The handlers therefore run on the
 * **same thread as run()** and suspend it while they execute.
 *
 * @note This is deliberately not a 1:1 emulation of the Mega Drive: real
 *       interrupts preempt the CPU at any instruction boundary, whereas here
 *       they are delivered cooperatively when the program calls
 *       runVDPInterrupts(). Programs must account for that difference.
 *
 * ```cpp
 * class MyGame : public MegaDriveEnvironment {
 *   public:
 *     MyGame() : MegaDriveEnvironment(VDP::VSync, VDP::Integer) {}
 *   protected:
 *     void run() override {
 *         while (!shouldQuit()) {
 *             // ... cartridge work ...
 *             runVDPInterrupts();   // dispatch scheduled vSync/hSync here
 *         }
 *     }
 *     void vSync() override { ... }          // runs on the run() thread
 *     void hSync(int line) override { ... }  // runs on the run() thread
 * };
 *
 * int main() { MyGame{}.boot(); }
 * ```
 */
class MegaDriveEnvironment {
    friend class SystemMemory;

    public:
    /// Wires the subsystems together. Does not start any threads (see boot()).
    MegaDriveEnvironment(VDP::Synchronization sync, VDP::Scaling scaling);

    virtual ~MegaDriveEnvironment();

    MegaDriveEnvironment(const MegaDriveEnvironment &)            = delete;
    MegaDriveEnvironment &operator=(const MegaDriveEnvironment &) = delete;

    /// Powers the system on, runs run() on the CPU thread, and pumps SDL events
    /// on the calling (main) thread until run() returns. Blocks until then.
    void boot();

    /// Dispatches every interrupt the VDP has scheduled since the last call,
    /// invoking vSync()/hSync() on the calling thread. Intended to be called
    /// from run(); it suspends run() while each handler executes.
    void runVDPInterrupts();

    /// True once the host requested a quit (e.g. the window was closed). The
    /// program should observe this to leave its run() loop.
    bool shouldQuit() const {
        return quitRequested_.load(std::memory_order_acquire);
    }

    /// Enables once-per-second debug logging (called by the VDP every 60 frames
    /// via logFrame()). Off by default; turned on with the `--debug` CLI flag.
    void setDebugLog(bool on) {
        debugLog_.store(on, std::memory_order_relaxed);
    }
    bool debugLog() const {
        return debugLog_.load(std::memory_order_relaxed);
    }

    /// Skip per-instruction pacing entirely (validation / bring-up). The VDP
    /// still runs on its own thread; use when hunting logic bugs, not for
    /// timing-accurate play.
    void setFastMode(bool on) {
        fastMode_.store(on, std::memory_order_relaxed);
    }
    bool fastMode() const {
        return fastMode_.load(std::memory_order_relaxed);
    }

    /// When set, an indirect dispatch to an address with no recompiled handler
    /// (a jump-table target the static analysis missed) appends that address to
    /// @p path and exits, instead of aborting — so a discovery loop can re-seed
    /// the recompiler. Empty (default) keeps the abort-on-unknown behaviour.
    void setAuxAddrFile(const std::string &path) {
        auxAddrFile_ = path;
    }

    /// Called by generated code at the entry of a speculative function. Active
    /// only when an aux file is configured, so normal runs stay silent.
    void confirmSpeculative(m_long addr);

    /// Logs one line of recompiled-CPU state — invoked once per ~second from the
    /// VDP render thread (frame = VBlank count, plus the VDP's display state).
    void logFrame(unsigned frame, bool displayEnabled);

    // ── Subsystem accessors ──────────────────────────────────────────────────
    SystemMemory &memory() {
        return memory_;
    }
    VDP &vdp() {
        return vdp_;
    }
    Controllers &controllers() {
        return controllers_;
    }
    Z80 &z80() {
        return z80_;
    }
    Sound &sound() {
        return sound_;
    }

    /// Marks an interrupt of the given autovector @p level (e.g. 6 = VBlank,
    /// 4 = HBlank) as pending. Called from the VDP render thread; lock-free.
    void raiseInterrupt(int level) {
        pendingIRQMask_.fetch_or(1u << level, std::memory_order_release);
    }

    protected:
    /// Highest pending interrupt level (0 when none). A single relaxed atomic
    /// load — cheap enough to consult before every recompiled instruction.
    int irqLevel() const {
        std::uint32_t m = pendingIRQMask_.load(std::memory_order_acquire);
        return m == 0 ? 0 : (31 - std::countl_zero(m));
    }

    /// Clears the pending bit for @p level (after the handler has been entered).
    void clearInterrupt(int level) {
        pendingIRQMask_.fetch_and(~(1u << level), std::memory_order_release);
    }

    /// Per-instruction pacing. Native code would otherwise outrun the VDP render
    /// thread and spin on SDL mutexes. Yield every 64 instructions so other
    /// threads make progress without paying sleep_for() syscall overhead on every
    /// opcode (which is ~100× slower than 68000 timing and made boot/decompression
    /// look frozen). Disabled entirely when fastMode() is set (--fast).
    void pace() {
        if (fastMode_.load(std::memory_order_relaxed))
            return;
        if ((++paceCounter_ & 0x3Fu) == 0)
            std::this_thread::yield();
    }

    /// Records the entry address of the function currently executing. Cheap
    /// (one relaxed store per call) and the only PC-like breadcrumb the
    /// recompiled code keeps — used to locate faults (see lastFunction()).
    void traceEnter(m_long addr) {
        traceHistory_[traceHistoryPos_++ & 0x0Fu] = addr;
        traceFn_.store(addr, std::memory_order_relaxed);
    }
    /// Entry address of the most recently entered recompiled function.
    m_long lastFunction() const {
        return traceFn_.load(std::memory_order_relaxed);
    }

    /// Called by the generated unhandledDispatch() when a computed jump lands on
    /// an address with no recompiled handler. Logs the address; if an aux file
    /// was set (setAuxAddrFile), appends it and exits so a discovery loop can
    /// re-seed and regenerate, otherwise aborts. Never returns.
    [[noreturn]] void reportUnhandledDispatch(m_long addr);

    /// 68000 register file: D0–D7, A0–A6, SSP, USP, PC and SR.
    ///
    /// Intended exclusively for mechanically-generated cartridge code inside
    /// run(). Hand-written subclasses (tests, tools) should not use this —
    /// they interact with the hardware through the public subsystem accessors
    /// (vdp(), memory(), controllers(), etc.).
    CPU68K &cpu() {
        return cpu_;
    }

    /// Loads a cartridge ROM image from @p path into the system memory's ROM
    /// region. Intended for game subclasses to make their cartridge resident
    /// (e.g. before run()); the reset vector is read from the loaded image by
    /// the cartridge boot code later.
    void loadROM(const std::string &path) {
        memory_.loadROM(path);
    }

    /// Cartridge entry point, overridden by the game subclass. Runs on the CPU thread.
    virtual void run() = 0;

    /// Called by runVDPInterrupts() once per frame (vertical blank).
    virtual void vSync() {
        sound_.endFrame();
    }

    /// Called by runVDPInterrupts() per scanline @p line (0-based, horizontal blank).
    virtual void hSync(int line) {
    }

    private:
    /// Starts every subsystem's thread.
    void powerOn();

    /// Stops every subsystem's thread. Idempotent.
    void powerOff();

    /// CPU-thread entry: runs run() then flags completion.
    static int cpuThreadEntry(void *data);

    // Declaration order is construction order.
    // cpu_ first: the register file is plain data, no dependencies.
    // memory_ before vdp_: VDP DMA reads system memory.
    CPU68K       cpu_;
    SystemMemory memory_;
    Z80          z80_;
    Sound        sound_;
    Controllers  controllers_;
    VDP          vdp_;

    SDL_Thread       *cpuThread_ = nullptr;
    std::atomic<bool> cpuDone_{false};
    std::atomic<bool> quitRequested_{false};

    /// Bit L set ⇒ an autovector interrupt of level L is pending. Set by the
    /// VDP render thread (raiseInterrupt), consumed on the run() thread.
    std::atomic<std::uint32_t>   pendingIRQMask_{0};
    std::atomic<m_long>          traceFn_{0}; ///< entry of the running recompiled fn
    m_long                       traceHistory_[16]{};
    unsigned                     traceHistoryPos_{0};
    std::atomic<bool>            debugLog_{false};
    std::atomic<bool>            fastMode_{false};
    std::uint32_t                paceCounter_{0};       ///< CPU thread only
    std::string                  auxAddrFile_;          ///< append unknown dispatch targets here (if set)
    std::unordered_set<unsigned> confirmedSpeculative_; ///< guards against duplicate confirmSpeculative logs
};
