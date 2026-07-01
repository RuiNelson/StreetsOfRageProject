#pragma once

#include "data_types.hpp"
#include "system/sound/mame_ymfm/ymfm.h"
#include "system/sound/mame_ymfm/ymfm_opn.h"

#include <SDL3/SDL.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

class MegaDriveEnvironment;

class Sound {
    public:
    static constexpr int kSampleRate = 48000;

    explicit Sound(MegaDriveEnvironment *env);
    ~Sound();

    Sound(const Sound &)            = delete;
    Sound &operator=(const Sound &) = delete;

    void start();
    void stop();

    m_byte readYM2612(int port);
    void   writeYM2612(int port, m_byte value);
    void   writePSG(m_byte value);

    struct Diagnostics {
        uint64_t audioFramesRendered = 0;
        uint64_t underruns           = 0;
        uint64_t overruns            = 0;
        uint64_t ymTimerExpirations  = 0;
        size_t   ringBufferedFrames  = 0;
        uint32_t fmSourceSampleRate  = 0;
    };

    void        resetForDiagnostics();
    void        renderForDiagnostics(int16_t *dst, int frames);
    Diagnostics diagnostics() const;

    // Kept for old callers; audio production is driven by the 48 kHz audio timer.
    void endFrame() {
    }

    private:
    class YMInterface : public ymfm::ymfm_interface {
        public:
        void resetTiming();
        void syncTimersToNow();
        void ymfm_sync_mode_write(uint8_t data) override;
        void ymfm_sync_check_interrupts() override;
        void ymfm_set_timer(uint32_t tnum, int32_t duration_in_clocks) override;
        void ymfm_set_busy_end(uint32_t clocks) override;
        bool ymfm_is_busy() override;
        void ymfm_update_irq(bool asserted) override;
        bool irqAsserted() const;
        uint64_t timerExpirationCount() const;

        private:
        std::array<uint64_t, 2> timerDeadlineNS_{};
        std::array<bool, 2>     timerActive_{};
        uint64_t                busyUntilNS_   = 0;
        uint64_t                timerExpirations_ = 0;
        bool                    irq_           = false;
        bool                    syncingTimers_ = false;
    };

    struct PSG {
        void reset();
        void write(m_byte value);
        int  render();

        std::array<uint16_t, 3> tonePeriod{};
        std::array<uint8_t, 4>  volume{};
        std::array<double, 3>   tonePhase{};
        std::array<int, 3>      toneLevel{};
        uint8_t                 latchedChannel = 0;
        bool                    latchedVolume  = false;
        uint8_t                 noiseControl   = 0;
        double                  noisePhase     = 0.0;
        uint16_t                noiseLFSR      = 0x8000;
        int                     noiseLevel     = 1;
    };

    static void audioCallback(void *userdata, SDL_AudioStream *stream, int additionalAmount, int totalAmount);
    void        resetChipState();
    void        renderToStream(SDL_AudioStream *stream, int bytesRequested);
    void        ensureRingFrames(int frames);
    void        pushRingFrames(const int16_t *src, int frames);
    void        popRingFrames(int16_t *dst, int frames);
    void        renderSamples(int16_t *dst, int frames);
    std::array<int, 2> renderFM();

    MegaDriveEnvironment *env_              = nullptr;
    SDL_Mutex            *mutex_            = nullptr;
    SDL_AudioStream      *stream_           = nullptr;
    bool                  audioInitialized_ = false;

    YMInterface               ymInterface_;
    ymfm::ym2612              ym_;
    PSG                       psg_;
    ymfm::ym2612::output_data lastFM_{};
    double                    fmAccumulator_ = 0.0;
    uint32_t                  fmSampleRate_  = 0;
    std::vector<int16_t>      callbackBuffer_;
    std::vector<int16_t>      renderBuffer_;
    std::vector<int16_t>      ringBuffer_;
    size_t                    ringReadFrame_      = 0;
    size_t                    ringWriteFrame_     = 0;
    size_t                    ringBufferedFrames_ = 0;
    uint64_t                  audioFramesRendered_ = 0;
    uint64_t                  underrunCount_      = 0;
    uint64_t                  overrunCount_       = 0;
};
