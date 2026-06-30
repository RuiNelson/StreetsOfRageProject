#pragma once

#include "data_types.hpp"

#include "gpgx_sound/ym3438.h"

#include <SDL3/SDL.h>
#include <array>
#include <atomic>
#include <deque>
#include <vector>

class MegaDriveEnvironment;

/**
 * @file Sound.hpp
 * @brief Mega Drive sound hardware: YM2612 FM synth + SN76489 PSG.
 *
 * Three-layer architecture:
 *   game/Z80 threads  →  event queue (queueMutex_)
 *   render thread     →  reads events, advances chips, fills sample ring buffer
 *   SDL callback      →  memcpy from ring buffer (no chip access, no blocking)
 *
 * endFrame() is a no-op retained for compatibility with generated cartridge code.
 */
class Sound {
    public:
    explicit Sound(MegaDriveEnvironment *env);
    ~Sound();

    Sound(const Sound &)            = delete;
    Sound &operator=(const Sound &) = delete;

    /// Opens the audio output device and resets both chips.
    void start();

    /// Closes the audio output device.
    void stop();

    /// YM2612 port access: ports 0-3 match $A04000-$A04003 (68k side) and
    /// $4000-$5FFF & 3 (Z80 side) — both meanings of "port 0/1/2/3" coincide.
    void   writeYM2612(int port, m_byte value);
    m_byte readYM2612(int port);

    /// PSG data port (write-only). Reached from $C00011 (68k side) and via the
    /// Z80's $7F00-$7FFF passthrough to the same 68k address.
    void writePSG(m_byte value);

    /// No-op: audio is rendered continuously by the dedicated render thread.
    void endFrame();

    static constexpr int kSampleRate = 44100;

    private:
    void tickFM(int ticks);
    void renderFM(int16_t *out, int sampleCount);

    static void sdlAudioCallback(void *userdata, SDL_AudioStream *stream,
                                  int additional_amount, int total_amount);

    // ── Event queue (game/Z80 → render thread) ──────────────────────────────
    struct AudioEvent {
        enum class Type { FM, PSG } type;
        int    port;
        m_byte value;
    };
    SDL_Mutex              *queueMutex_ = nullptr;
    std::deque<AudioEvent>  writeQueue_;

    // ── Chip ownership (render thread only, plus readYM2612 drain) ──────────
    SDL_Mutex *chipMutex_ = nullptr;

    // ── Dedicated audio render thread ────────────────────────────────────────
    SDL_Thread *renderThread_  = nullptr;
    bool        renderRunning_ = false;
    static int  renderThreadEntry(void *data);
    void        renderLoop();

    // ── Lock-free sample ring buffer (render thread writes, callback reads) ──
    // ponytail: power-of-two capacity so % is cheap; ~185 ms of headroom at 44100 Hz
    static constexpr int kRingCapacity = 8192;
    static constexpr int kBatchSize    = 256;  // stereo pairs per render iteration (~5.8 ms)
    std::array<int16_t, kRingCapacity * 2> ringData_{};
    std::atomic<int> ringWrite_{0};
    std::atomic<int> ringRead_{0};

    int  ringAvailToRead()  const;
    int  ringAvailToWrite() const;
    void ringPush(const int16_t *src, int count);
    int  ringPop(int16_t *dst, int count);

    // ── Hardware state ───────────────────────────────────────────────────────
    MegaDriveEnvironment *env_ = nullptr;

    ym3438_t chip_{};
    short    ymAccm_[24][2]{};
    int      ymCycle_ = 0;
    int      ymSample_[2]{};

    SDL_AudioStream      *audioStream_ = nullptr;
    std::vector<int16_t>  fmRenderBuf_;
    std::vector<int16_t>  psgRenderBuf_;
    std::vector<int16_t>  mixRenderBuf_;
};
