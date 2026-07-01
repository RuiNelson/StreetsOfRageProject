#pragma once

#include "data_types.hpp"
#include "system/sound/mame_ymfm/ymfm.h"
#include "system/sound/mame_ymfm/ymfm_opn.h"

#include <SDL3/SDL.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <deque>
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

    /// Disables the sound subsystem entirely (--silent): start() opens no
    /// audio device, chip writes are dropped, and status reads return 0.
    void disable() {
        disabled_.store(true, std::memory_order_release);
    }
    bool disabled() const {
        return disabled_.load(std::memory_order_acquire);
    }

    m_byte readYM2612(int port);
    m_byte readYM2612At(uint64_t masterCycles, int port);
    void   writeYM2612(int port, m_byte value);
    void   writeYM2612At(uint64_t masterCycles, int port, m_byte value);
    void   writePSG(m_byte value);
    void   writePSGAt(uint64_t masterCycles, m_byte value);

    /// Shared audio timeline: master cycles elapsed on the wall clock since
    /// this Sound was constructed. Every producer (Z80, 68K) stamps its
    /// port writes with this clock and the renderer chases it, so event
    /// timestamps and rendered samples stay on one timeline.
    uint64_t masterCyclesNow() const;

    struct Diagnostics {
        uint64_t audioFramesRendered = 0;
        uint64_t underruns           = 0;
        uint64_t overruns            = 0;
        uint64_t ymTimerExpirations  = 0;
        uint64_t queuedEvents        = 0;
        uint64_t lateEvents          = 0;
        uint64_t clippedSamples      = 0;
        int32_t  peakLeft            = 0;
        int32_t  peakRight           = 0;
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
        void     resetTiming();
        void     setMasterCycle(uint64_t masterCycle);
        void     syncTimersToMasterCycle(uint64_t masterCycle);
        void     ymfm_sync_mode_write(uint8_t data) override;
        void     ymfm_sync_check_interrupts() override;
        void     ymfm_set_timer(uint32_t tnum, int32_t duration_in_clocks) override;
        void     ymfm_set_busy_end(uint32_t clocks) override;
        bool     ymfm_is_busy() override;
        void     ymfm_update_irq(bool asserted) override;
        bool     irqAsserted() const;
        uint64_t timerExpirationCount() const;

        private:
        std::array<uint64_t, 2> timerDeadlineMasterCycles_{};
        std::array<bool, 2>     timerActive_{};
        uint64_t                busyUntilMasterCycle_ = 0;
        uint64_t                currentMasterCycle_   = 0;
        uint64_t                timerExpirations_     = 0;
        bool                    irq_                  = false;
        bool                    syncingTimers_        = false;
    };

    struct PSG {
        void               reset();
        void               write(m_byte value);
        std::array<int, 2> render();
        void               setPanning(uint8_t mask);

        std::array<uint16_t, 3> tonePeriod{};
        std::array<uint16_t, 4> volume{};
        std::array<double, 4>   counter{};
        std::array<int, 3>      tonePolarity{};
        std::array<int, 4>      leftAmp{};
        std::array<int, 4>      rightAmp{};
        uint8_t                 latchedRegister = 3;
        uint8_t                 noiseControl    = 0;
        uint16_t                noiseLFSR       = 0x8000;
        int                     noiseOutput     = 0;
    };

    enum class EventType : uint8_t {
        YMWrite,
        PSGWrite,
    };

    struct TimedEvent {
        uint64_t  masterCycle   = 0;
        EventType type          = EventType::YMWrite;
        uint8_t   port          = 0;
        uint8_t   value         = 0;
        bool      timerRegister = false; ///< YM data write hitting $24–$27 (affects polled status)
    };

    static void        audioCallback(void *userdata, SDL_AudioStream *stream, int additionalAmount, int totalAmount);
    void               resetChipState();
    void               renderToStream(SDL_AudioStream *stream, int bytesRequested);
    void               ensureRingFrames(int frames);
    void               pushRingFrames(const int16_t *src, int frames);
    void               popRingFrames(int16_t *dst, int frames);
    void               renderSamples(int16_t *dst, int frames);
    void               enqueueEvent(TimedEvent event);
    void               processEventsUntil(uint64_t masterCycle);
    void               applyEvent(const TimedEvent &event);
    std::array<int, 2> renderFM();
    std::array<int, 2> filterOutput(std::array<int, 2> sample);
    int16_t            clampMixedSample(int value, size_t channel);

    // Threading model while streaming: producers (68K/Z80 threads) only touch
    // the event queue under mutex_ (short critical sections) and read the
    // atomic cachedStatus_; the chip state (ym_, psg_, ymInterface_, filters,
    // render clock) is owned exclusively by the audio render thread. Headless
    // (!stream_) everything runs on the caller's thread.
    MegaDriveEnvironment *env_              = nullptr;
    SDL_Mutex            *mutex_            = nullptr; ///< guards pendingEvents_ + enqueue bookkeeping
    SDL_AudioStream      *stream_           = nullptr;
    bool                  audioInitialized_ = false;
    std::atomic<bool>     disabled_{false};
    std::atomic<uint8_t>  cachedStatus_{0}; ///< last YM status published by the render thread

    YMInterface                         ymInterface_;
    ymfm::ym2612                        ym_;
    PSG                                 psg_;
    ymfm::ym2612::output_data           lastFM_{};
    ymfm::ym2612::output_data           previousFM_{};
    ymfm::ym2612::output_data           nextFM_{};
    double                              fmAccumulator_     = 1.0;
    uint32_t                            fmSampleRate_      = 0;
    double                              renderMasterCycle_ = 0.0;
    std::atomic<uint64_t>               lastRenderedMasterCycle_{0};
    uint64_t                            baseTimeNS_      = 0;
    uint8_t                             queuedYMAddress_ = 0; ///< enqueue-time shadow of the port-0 address latch
    uint64_t                            lateEventCount_  = 0;
    std::atomic<uint64_t>               clippedSampleCount_{0};
    std::array<std::atomic<int32_t>, 2> peakSample_{};
    std::array<double, 2>               dcPrevInput_{};
    std::array<double, 2>               dcPrevOutput_{};
    std::array<double, 2>               lowpassState_{};
    std::deque<TimedEvent>              pendingEvents_;
    std::vector<int16_t>                callbackBuffer_;
    std::vector<int16_t>                renderBuffer_;
    std::vector<int16_t>                ringBuffer_;
    size_t                              ringReadFrame_      = 0;
    size_t                              ringWriteFrame_     = 0;
    size_t                              ringBufferedFrames_ = 0;
    std::atomic<uint64_t>               audioFramesRendered_{0};
    std::atomic<uint64_t>               underrunCount_{0};
    std::atomic<uint64_t>               overrunCount_{0};
};
