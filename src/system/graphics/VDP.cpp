/**
 * @file VDP.cpp
 * @brief Sega Mega Drive VDP emulator — composite implementation.
 */

#include "VDP.hpp"
#include "system/MegaDriveEnvironment.hpp"
#include <cstdio>
#include <cstring>
#include <png.h>

// ── Construction / Destruction ──────────────────────────────────────────────

/// Initializes SDL, creates window and renderer, and resets VDP state. The
/// render thread is not spawned here — call start() once the environment is
/// fully constructed.
VDP::VDP(MegaDriveEnvironment *env, Synchronization synchronization, Scaling scaling)
    : state_(), tile_(state_), port_(state_), renderer_(state_, tile_, framebuffer_),
      rendererDebug_(state_, tile_, framebuffer_), syncMode_(synchronization), scalingMode_(scaling), env_(env) {
    SDL_Init(SDL_INIT_VIDEO);
    mutex_    = SDL_CreateMutex();
    irqMutex_ = SDL_CreateMutex();
    port_.setEnvironment(env);
    state_.reset();

    int winW = VDPState::SCREEN_W;
    int winH = VDPState::SCREEN_H;
    if (scalingMode_ > 0) {
        winW *= scalingMode_;
        winH *= scalingMode_;
    } else if (scalingMode_ == Integer) {
        SDL_Rect      usable{};
        SDL_DisplayID display = SDL_GetPrimaryDisplay();
        if (display && SDL_GetDisplayUsableBounds(display, &usable)) {
            int scaleX = usable.w / VDPState::SCREEN_W;
            int scaleY = usable.h / VDPState::SCREEN_H;
            int scale  = std::max(1, std::min(scaleX, scaleY));
            winW *= scale;
            winH *= scale;
            SDL_Log("[VDP] Display usable: %dx%d  scaleX=%d scaleY=%d  chosen scale=%d  window=%dx%d",
                    usable.w,
                    usable.h,
                    scaleX,
                    scaleY,
                    scale,
                    winW,
                    winH);
        } else {
            winW *= 3;
            winH *= 3;
            SDL_Log("[VDP] SDL_GetDisplayUsableBounds failed, falling back to 3x: window=%dx%d", winW, winH);
        }
    } else {
        winW *= 3;
        winH *= 3;
    }

    window_ = SDL_CreateWindow("VDP", winW, winH, SDL_WINDOW_RESIZABLE);
    if (window_) {
        sdlRenderer_ = SDL_CreateRenderer(window_, nullptr);
        if (sdlRenderer_) {
            if (syncMode_ != InternalTimer) {
                SDL_SetRenderVSync(sdlRenderer_, 1);
            }
            texture_ = SDL_CreateTexture(sdlRenderer_,
                                         SDL_PIXELFORMAT_BGR24,
                                         SDL_TEXTUREACCESS_STREAMING,
                                         VDPState::SCREEN_W,
                                         VDPState::SCREEN_H);
            if (texture_) {
                SDL_SetTextureScaleMode(texture_, (scalingMode_ == Fit) ? SDL_SCALEMODE_LINEAR : SDL_SCALEMODE_NEAREST);
            }
        }
    }
}

VDP::~VDP() {
    shutdown();
}

// ── Threading ──────────────────────────────────────────────────────────────

/// Spawns the render thread. No-op if it is already running.
void VDP::start() {
    if (thread_) {
        return;
    }
    running_ = true;
    thread_  = SDL_CreateThread(renderThreadEntry, "VDP", this);
}

/// Stops the render thread, keeping the SDL window/renderer alive for a later start().
void VDP::stop() {
    running_ = false;
    if (thread_) {
        SDL_Event e;
        while (SDL_GetThreadState(thread_) != SDL_THREAD_COMPLETE) {
            SDL_PollEvent(&e);
            SDL_Delay(1);
        }
        SDL_WaitThread(thread_, nullptr);
        thread_ = nullptr;
    }
}

// ── Port I/O ─────────────────────────────────────────────────────────────────

/// Thread-safe: Acquires mutex_, delegates to port_.writeControlPort(), releases mutex_.
void VDP::writeControlPort(m_word value) {
    SDL_LockMutex(mutex_);
    port_.writeControlPort(value);
    SDL_UnlockMutex(mutex_);
}

/// Thread-safe: Acquires mutex_, reads status from port_, releases mutex_.
m_word VDP::readControlPort() {
    SDL_LockMutex(mutex_);
    m_word result = port_.readControlPort();
    SDL_UnlockMutex(mutex_);
    return result;
}

/// Thread-safe: Acquires mutex_, delegates to port_.writeDataPort(), releases mutex_.
void VDP::writeDataPort(m_word value) {
    SDL_LockMutex(mutex_);
    port_.writeDataPort(value);
    SDL_UnlockMutex(mutex_);
}

/// Thread-safe: Acquires mutex_, reads from port_, releases mutex_.
m_word VDP::readDataPort() {
    SDL_LockMutex(mutex_);
    m_word result = port_.readDataPort();
    SDL_UnlockMutex(mutex_);
    return result;
}

/// Thread-safe: Acquires mutex_, reads H/V counter, releases mutex_.
m_word VDP::readHVCounter() {
    SDL_LockMutex(mutex_);
    m_word result = port_.readHVCounter();
    SDL_UnlockMutex(mutex_);
    return result;
}

// ── Lifecycle ────────────────────────────────────────────────────────────────

/// Thread-safe: Resets VDP state and clears framebuffer under mutex protection.
void VDP::reset() {
    SDL_LockMutex(mutex_);
    state_.reset();
    framebuffer_.clear();
    SDL_UnlockMutex(mutex_);
}

/// Signals render thread to exit, waits for completion, then releases all SDL resources.
void VDP::shutdown() {
    stop();
    if (texture_) {
        SDL_DestroyTexture(texture_);
        texture_ = nullptr;
    }
    if (sdlRenderer_) {
        SDL_DestroyRenderer(sdlRenderer_);
        sdlRenderer_ = nullptr;
    }
    if (window_) {
        SDL_DestroyWindow(window_);
        window_ = nullptr;
    }
    if (mutex_) {
        SDL_DestroyMutex(mutex_);
        mutex_ = nullptr;
    }
    if (irqMutex_) {
        SDL_DestroyMutex(irqMutex_);
        irqMutex_ = nullptr;
    }
}

// ── Interrupt scheduling ───────────────────────────────────────────────────

/// Appends an interrupt to the queue, dropping the oldest entries past IRQ_QUEUE_MAX.
void VDP::scheduleInterrupt(Interrupt::Type type, int line) {
    SDL_LockMutex(irqMutex_);
    if (irqQueue_.size() >= IRQ_QUEUE_MAX) {
        irqQueue_.pop_front();
    }
    irqQueue_.push_back(Interrupt{type, line});
    SDL_UnlockMutex(irqMutex_);

    // Also raise the lock-free pending-interrupt flag consulted by recompiled
    // code before each instruction (the queue above drives the cooperative
    // hSync()/vSync() path used by hand-written programs). VBlank is autovector
    // level 6, HBlank level 4. Unlike the queue, this honours the VDP's own
    // interrupt-enable bits, exactly as the 68000 IRQ line does on hardware: a
    // VBlank IRQ is only asserted when reg $01 bit 5 (IE0) is set, so the game's
    // handler never runs before the game has enabled it (and set up its data).
    // HBlank is already gated by the caller (hintEnabled()).
    if (env_) {
        if (type == Interrupt::VSync) {
            SDL_LockMutex(mutex_);
            bool vintOn = state_.vblankIRQEnabled();
            SDL_UnlockMutex(mutex_);
            if (vintOn) {
                env_->z80().pulseVBlankIRQ();
                env_->raiseInterrupt(6);
            }
        } else {
            env_->raiseInterrupt(4);
        }
    }
}

/// Pops the oldest scheduled interrupt. Returns false when the queue is empty.
bool VDP::popInterrupt(Interrupt &out) {
    SDL_LockMutex(irqMutex_);
    bool has = !irqQueue_.empty();
    if (has) {
        out = irqQueue_.front();
        irqQueue_.pop_front();
    }
    SDL_UnlockMutex(irqMutex_);
    return has;
}

// ── Debug Dump ───────────────────────────────────────────────────────────────

/// Thread-safe: Exports framebuffer to PNG under mutex. fullRange=true uses 8-bit color; false uses native 3-bit.
void VDP::dumpFrameBufferToPNG(std::string path, bool fullRange) {
    SDL_LockMutex(mutex_);
    rendererDebug_.dumpFrameBufferToPNG(path, fullRange);
    SDL_UnlockMutex(mutex_);
}

/// Thread-safe: Exports combined debug image (framebuffer + tiles + planes) to PNG under mutex.
void VDP::dumpEverythingToPNG(std::string path, bool fullRange) {
    SDL_LockMutex(mutex_);
    rendererDebug_.dumpEverythingToPNG(path, fullRange);
    SDL_UnlockMutex(mutex_);
}

// ── Render Thread ────────────────────────────────────────────────────────────

/// Static thread entry point. Casts userdata to VDP* and delegates to renderLoop().
int VDP::renderThreadEntry(void *data) {
    return static_cast<VDP *>(data)->renderLoop();
}

/// SDL main-thread callback to update and present framebuffer texture to screen.
void VDP::sdlPresentCallback(void *userdata) {
    static_cast<VDP *>(userdata)->presentToScreen();
}

/// SDL main-thread callback to re-present the same texture (for VSync2/VSync3 frame hold).
void VDP::sdlRepeatCallback(void *userdata) {
    auto *self = static_cast<VDP *>(userdata);
    if (self->sdlRenderer_ && self->texture_) {
        SDL_RenderClear(self->sdlRenderer_);
        SDL_RenderTexture(self->sdlRenderer_, self->texture_, nullptr, nullptr);
        SDL_RenderPresent(self->sdlRenderer_);
    }
}

/// Uploads framebuffer to the long-lived texture and presents to window (must be called on SDL main thread).
void VDP::presentToScreen() {
    if (!texture_)
        return;
    framebuffer_.uploadToTexture(texture_);
    SDL_RenderClear(sdlRenderer_);
    SDL_RenderTexture(sdlRenderer_, texture_, nullptr, nullptr);
    SDL_RenderPresent(sdlRenderer_);
}

/// Main render thread loop: renders the frame scanline by scanline (scheduling an HSync interrupt after each line),
/// sets the VBlank flag, schedules a VSync interrupt, presents to display, and manages frame timing based on sync mode.
/// Interrupts are dispatched on the program thread via MegaDriveEnvironment::runVDPInterrupts().
int VDP::renderLoop() {
    while (running_) {
        const uint64_t frameTimeNs = (env_ != nullptr && env_->isPal50Hz()) ? 20'000'000ull : 16'715'000ull;
        uint64_t       frameStart  = SDL_GetTicksNS();

        // Render the frame one scanline at a time so a per-line interrupt can be
        // scheduled (raster effects). Mirrors VDPRenderer::renderFrame().
        SDL_LockMutex(mutex_);
        bool displayEnabled = state_.displayEnabled();
        if (!displayEnabled) {
            framebuffer_.clear();
        }
        SDL_UnlockMutex(mutex_);

        if (displayEnabled) {
            // ponytail: single lock for the full frame instead of per-scanline;
            // reduces ~448 mutex ops to 1. CPU thread is blocked from VDP writes
            // during active display, which mirrors real hardware behaviour.
            // scheduleInterrupt(HSync) is safe under mutex_: it only touches
            // irqMutex_ + a raiseInterrupt atomic, never mutex_ itself.
            SDL_LockMutex(mutex_);
            int hintCountdown = state_.hintReloadValue();
            for (int line = 0; line < VDPState::SCREEN_H; ++line) {
                state_.vCounter_ = static_cast<m_word>(line);
                renderer_.renderScanline(line);
                --hintCountdown;
                if (hintCountdown < 0) {
                    hintCountdown = state_.hintReloadValue();
                    if (state_.hintEnabled()) {
                        scheduleInterrupt(Interrupt::HSync, line);
                    }
                }
            }
            SDL_UnlockMutex(mutex_);
        }

        SDL_LockMutex(mutex_);
        state_.status_ |= 0x0008; // VBlank flag
        SDL_UnlockMutex(mutex_);

        scheduleInterrupt(Interrupt::VSync, 0);

        // Debug (under --debug): once per second (60 frames), dump the frame
        // (composited output) and the full debug view (registers + tile
        // sheets + plane nametables, via dumpEverythingToPNG) and log
        // recompiled-CPU state, to watch boot/render progress.
        if (env_ != nullptr && env_->debugLog()) {
            static unsigned debugFrame = 0;
            ++debugFrame;
            if (debugFrame % 20 == 0) {
                env_->logFrame(debugFrame, displayEnabled);
            }
            if (debugFrame % 60 == 0) {
                dumpFrameBufferToPNG("sor_frame.png", true);
                dumpEverythingToPNG("sor_everything.png", true);
            }
        }

        if (sdlRenderer_) {
            SDL_RunOnMainThread(sdlPresentCallback, this, /*wait=*/true);

            // VSync2 / VSync3: hold the same frame for (N-1) extra monitor refreshes
            // so the game runs at monitorHz / N (e.g. 120 Hz / 2 = 60 Hz).
            int extraPresentCount = 0;
            if (syncMode_ == VSync2)
                extraPresentCount = 1;
            else if (syncMode_ == VSync3)
                extraPresentCount = 2;
            for (int i = 0; i < extraPresentCount; ++i) {
                SDL_RunOnMainThread(sdlRepeatCallback, this, /*wait=*/true);
            }
        }

        SDL_LockMutex(mutex_);
        state_.status_ &= ~0x0008;
        state_.vCounter_ = 0;
        SDL_UnlockMutex(mutex_);

        if (syncMode_ == InternalTimer) {
            uint64_t elapsed = SDL_GetTicksNS() - frameStart;
            if (elapsed < frameTimeNs) {
                SDL_DelayNS(frameTimeNs - elapsed);
            }
        }
    }

    return 0;
}
