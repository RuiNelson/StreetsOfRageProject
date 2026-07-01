#include "Sound.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace {

constexpr uint32_t kYM2612Clock   = 53'693'175u / 7u;
constexpr uint64_t kMasterClockHz = 53'693'175ull;
constexpr double   kMasterClock   = 53'693'175.0;
constexpr double   kPSGClock      = 3'579'545.0;
// The renderer trails the producers' wall clock by this margin so queued
// events are still in its future and play at their exact timestamps.
constexpr double   kEventLatencyCycles = 0.040 * kMasterClock;
constexpr double   kSnapCycles         = 0.250 * kMasterClock; // resync hard beyond this drift
constexpr double   kMaxRateTrim        = 0.005;                // ±0.5% render-rate trim toward the latency target
constexpr int      kRenderChunkFrames  = 256;
constexpr int      kRingBufferFrames   = 4096;
constexpr int      kFmPreampPercent    = 100;
constexpr int      kPsgPreampPercent   = 150;
constexpr uint32_t kLowpassRange       = 0x9999;
constexpr double   kDCBlockR           = 0.995;

// Temporary diagnostics: SOR_SND_TAP=<path> dumps rendered s16 stereo frames,
// SOR_YM_LOG=<path> logs every enqueued chip write with its producer thread.
FILE *sndTapFile() {
    static FILE *f = [] {
        const char *p = std::getenv("SOR_SND_TAP");
        return p ? std::fopen(p, "wb") : nullptr;
    }();
    return f;
}

FILE *ymLogFile() {
    static FILE *f = [] {
        const char *p = std::getenv("SOR_YM_LOG");
        return p ? std::fopen(p, "w") : nullptr;
    }();
    return f;
}

int16_t clamp16(int value) {
    return static_cast<int16_t>(std::clamp(value, -32768, 32767));
}

uint64_t ymClocksToMasterCycles(uint32_t clocks) {
    return static_cast<uint64_t>(clocks) * 7ull;
}

int applyPreamp(int value, int percent) {
    return (value * percent) / 100;
}

int psgVolume(uint8_t attenuation) {
    static constexpr std::array<int, 16> kVolume = {
        2800,
        2224,
        1767,
        1403,
        1115,
        886,
        704,
        559,
        444,
        353,
        280,
        222,
        177,
        140,
        111,
        0,
    };
    return kVolume[attenuation & 0x0F];
}

} // namespace

Sound::Sound(MegaDriveEnvironment *env) : env_(env), mutex_(SDL_CreateMutex()), ym_(ymInterface_) {
    baseTimeNS_   = SDL_GetTicksNS();
    fmSampleRate_ = ym_.sample_rate(kYM2612Clock);
    psg_.reset();
}

uint64_t Sound::masterCyclesNow() const {
    const uint64_t ns  = SDL_GetTicksNS() - baseTimeNS_;
    const uint64_t s   = ns / 1'000'000'000ull;
    const uint64_t rem = ns % 1'000'000'000ull;
    return (s * kMasterClockHz) + ((rem * kMasterClockHz) / 1'000'000'000ull);
}

Sound::~Sound() {
    stop();
    if (mutex_) {
        SDL_DestroyMutex(mutex_);
        mutex_ = nullptr;
    }
}

void Sound::start() {
    if (disabled())
        return;

    SDL_LockMutex(mutex_);
    resetChipState();
    SDL_UnlockMutex(mutex_);

    if (stream_)
        return;

    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        std::fprintf(stderr, "Sound: could not initialize SDL audio: %s\n", SDL_GetError());
        return;
    }
    audioInitialized_ = true;

    SDL_AudioSpec spec{};
    spec.format   = SDL_AUDIO_S16;
    spec.channels = 2;
    spec.freq     = kSampleRate;

    stream_ = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, audioCallback, this);
    if (!stream_) {
        std::fprintf(stderr, "Sound: could not open SDL audio stream: %s\n", SDL_GetError());
        return;
    }
    SDL_ResumeAudioStreamDevice(stream_);
}

void Sound::stop() {
    if (stream_) {
        SDL_DestroyAudioStream(stream_);
        stream_ = nullptr;
    }
    if (audioInitialized_) {
        SDL_QuitSubSystem(SDL_INIT_AUDIO);
        audioInitialized_ = false;
    }
}

m_byte Sound::readYM2612(int port) {
    return readYM2612At(masterCyclesNow(), port);
}

m_byte Sound::readYM2612At(uint64_t masterCycles, int port) {
    (void)port; // every YM2612 port reads back the status register
    if (disabled())
        return 0;

    // While streaming, the chip belongs to the render thread; status reads
    // must never block gameplay on it, so they return the last status the
    // renderer published (a few ms stale at worst — the busy-wait loops in
    // the drivers only need "not busy").
    if (stream_)
        return cachedStatus_.load(std::memory_order_relaxed);

    SDL_LockMutex(mutex_);
    processEventsUntil(masterCycles);
    ymInterface_.syncTimersToMasterCycle(masterCycles);
    m_byte result = ym_.read(0);
    SDL_UnlockMutex(mutex_);
    return result;
}

void Sound::writeYM2612(int port, m_byte value) {
    writeYM2612At(masterCyclesNow(), port, value);
}

void Sound::writeYM2612At(uint64_t masterCycles, int port, m_byte value) {
    if (disabled())
        return;
    SDL_LockMutex(mutex_);
    enqueueEvent(TimedEvent{
        .masterCycle = masterCycles,
        .type        = EventType::YMWrite,
        .port        = static_cast<uint8_t>(port & 3),
        .value       = value,
    });
    if (!stream_)
        processEventsUntil(masterCycles);
    SDL_UnlockMutex(mutex_);
}

void Sound::writePSG(m_byte value) {
    writePSGAt(masterCyclesNow(), value);
}

void Sound::writePSGAt(uint64_t masterCycles, m_byte value) {
    if (disabled())
        return;
    SDL_LockMutex(mutex_);
    enqueueEvent(TimedEvent{
        .masterCycle = masterCycles,
        .type        = EventType::PSGWrite,
        .port        = 0,
        .value       = value,
    });
    if (!stream_)
        processEventsUntil(masterCycles);
    SDL_UnlockMutex(mutex_);
}

void Sound::resetForDiagnostics() {
    SDL_LockMutex(mutex_);
    resetChipState();
    SDL_UnlockMutex(mutex_);
}

void Sound::renderForDiagnostics(int16_t *dst, int frames) {
    renderSamples(dst, frames);
}

Sound::Diagnostics Sound::diagnostics() const {
    SDL_LockMutex(mutex_);
    const size_t   queued = pendingEvents_.size();
    const uint64_t late   = lateEventCount_;
    SDL_UnlockMutex(mutex_);
    // The remaining counters are owned by the render thread; reading them
    // unlocked is fine for diagnostics.
    return Diagnostics{
        .audioFramesRendered = audioFramesRendered_.load(std::memory_order_relaxed),
        .underruns           = underrunCount_.load(std::memory_order_relaxed),
        .overruns            = overrunCount_.load(std::memory_order_relaxed),
        .ymTimerExpirations  = ymInterface_.timerExpirationCount(),
        .queuedEvents        = queued,
        .lateEvents          = late,
        .clippedSamples      = clippedSampleCount_.load(std::memory_order_relaxed),
        .peakLeft            = peakSample_[0].load(std::memory_order_relaxed),
        .peakRight           = peakSample_[1].load(std::memory_order_relaxed),
        .ringBufferedFrames  = ringBufferedFrames_,
        .fmSourceSampleRate  = fmSampleRate_,
    };
}

void Sound::audioCallback(void *userdata, SDL_AudioStream *stream, int additionalAmount, int totalAmount) {
    (void)totalAmount;
    static_cast<Sound *>(userdata)->renderToStream(stream, additionalAmount);
}

void Sound::resetChipState() {
    ymInterface_.resetTiming();
    ym_.reset();
    psg_.reset();
    lastFM_.clear();
    previousFM_.clear();
    nextFM_.clear();
    ym_.generate(&previousFM_, 1);
    ym_.generate(&nextFM_, 1);
    fmAccumulator_     = 1.0;
    renderMasterCycle_ = std::max(0.0, static_cast<double>(masterCyclesNow()) - kEventLatencyCycles);
    lastRenderedMasterCycle_.store(0, std::memory_order_relaxed);
    queuedYMAddress_ = 0;
    lateEventCount_  = 0;
    clippedSampleCount_.store(0, std::memory_order_relaxed);
    peakSample_[0].store(0, std::memory_order_relaxed);
    peakSample_[1].store(0, std::memory_order_relaxed);
    cachedStatus_.store(0, std::memory_order_relaxed);
    dcPrevInput_.fill(0.0);
    dcPrevOutput_.fill(0.0);
    lowpassState_.fill(0.0);
    pendingEvents_.clear();
    ringBuffer_.assign(kRingBufferFrames * 2, 0);
    ringReadFrame_      = 0;
    ringWriteFrame_     = 0;
    ringBufferedFrames_ = 0;
    audioFramesRendered_.store(0, std::memory_order_relaxed);
    underrunCount_.store(0, std::memory_order_relaxed);
    overrunCount_.store(0, std::memory_order_relaxed);
    ymInterface_.resetTiming();
}

void Sound::renderToStream(SDL_AudioStream *stream, int bytesRequested) {
    if (bytesRequested <= 0)
        return;
    const int frames =
        (bytesRequested + static_cast<int>(sizeof(int16_t) * 2) - 1) / static_cast<int>(sizeof(int16_t) * 2);
    callbackBuffer_.resize(static_cast<size_t>(frames) * 2);
    ensureRingFrames(frames);
    popRingFrames(callbackBuffer_.data(), frames);
    SDL_PutAudioStreamData(stream, callbackBuffer_.data(), static_cast<int>(callbackBuffer_.size() * sizeof(int16_t)));
}

void Sound::ensureRingFrames(int frames) {
    if (frames <= 0)
        return;

    if (ringBuffer_.empty()) {
        ringBuffer_.assign(std::max(kRingBufferFrames, frames) * 2, 0);
        ringReadFrame_      = 0;
        ringWriteFrame_     = 0;
        ringBufferedFrames_ = 0;
    }

    const size_t capacityFrames = ringBuffer_.size() / 2;
    while (ringBufferedFrames_ < static_cast<size_t>(frames)) {
        const size_t freeFrames = capacityFrames - ringBufferedFrames_;
        if (freeFrames == 0) {
            ++overrunCount_;
            break;
        }

        const int chunkFrames = std::min<int>(kRenderChunkFrames, static_cast<int>(freeFrames));
        renderBuffer_.resize(static_cast<size_t>(chunkFrames) * 2);
        renderSamples(renderBuffer_.data(), chunkFrames);
        pushRingFrames(renderBuffer_.data(), chunkFrames);
    }
}

void Sound::pushRingFrames(const int16_t *src, int frames) {
    const size_t capacityFrames = ringBuffer_.size() / 2;
    for (int frame = 0; frame < frames; ++frame) {
        if (ringBufferedFrames_ >= capacityFrames) {
            ++overrunCount_;
            return;
        }

        const size_t dstFrame         = ringWriteFrame_;
        ringBuffer_[dstFrame * 2 + 0] = src[frame * 2 + 0];
        ringBuffer_[dstFrame * 2 + 1] = src[frame * 2 + 1];
        ringWriteFrame_               = (ringWriteFrame_ + 1) % capacityFrames;
        ++ringBufferedFrames_;
    }
}

void Sound::popRingFrames(int16_t *dst, int frames) {
    const size_t capacityFrames = ringBuffer_.size() / 2;
    for (int frame = 0; frame < frames; ++frame) {
        if (ringBufferedFrames_ == 0 || capacityFrames == 0) {
            ++underrunCount_;
            dst[frame * 2 + 0] = 0;
            dst[frame * 2 + 1] = 0;
            continue;
        }

        const size_t srcFrame = ringReadFrame_;
        dst[frame * 2 + 0]    = ringBuffer_[srcFrame * 2 + 0];
        dst[frame * 2 + 1]    = ringBuffer_[srcFrame * 2 + 1];
        ringReadFrame_        = (ringReadFrame_ + 1) % capacityFrames;
        --ringBufferedFrames_;
    }
}

void Sound::renderSamples(int16_t *dst, int frames) {
    for (int base = 0; base < frames; base += kRenderChunkFrames) {
        const int chunkFrames = std::min(kRenderChunkFrames, frames - base);
        // Keep the render clock kEventLatencyCycles behind the producers'
        // wall clock: snap on gross drift (startup, host stalls), otherwise
        // trim the per-sample step so the pitch shift stays inaudible.
        const double target = static_cast<double>(masterCyclesNow()) - kEventLatencyCycles;
        double       error  = renderMasterCycle_ - target;
        if (std::abs(error) > kSnapCycles) {
            renderMasterCycle_ = std::max(target, 0.0);
            error              = 0.0;
        }
        const double step = (kMasterClock / static_cast<double>(kSampleRate)) *
                            (1.0 - std::clamp(error / kSnapCycles, -kMaxRateTrim, kMaxRateTrim));
        for (int i = 0; i < chunkFrames; ++i) {
            const int      frame       = base + i;
            const uint64_t masterCycle = static_cast<uint64_t>(renderMasterCycle_);
            // Only the queue drain takes the lock; the chip is owned by this
            // thread, so generation never blocks the producer (game) threads.
            SDL_LockMutex(mutex_);
            processEventsUntil(masterCycle);
            SDL_UnlockMutex(mutex_);
            ymInterface_.syncTimersToMasterCycle(masterCycle);
            const auto fm       = renderFM();
            const auto psg      = psg_.render();
            const auto filtered = filterOutput({fm[0] + psg[0], fm[1] + psg[1]});
            dst[frame * 2 + 0]  = clampMixedSample(filtered[0], 0);
            dst[frame * 2 + 1]  = clampMixedSample(filtered[1], 1);
            lastRenderedMasterCycle_.store(masterCycle, std::memory_order_relaxed);
            renderMasterCycle_ += step;
        }
        cachedStatus_.store(ym_.read(0), std::memory_order_relaxed);
        audioFramesRendered_.fetch_add(static_cast<uint64_t>(chunkFrames), std::memory_order_relaxed);
        if (FILE *tap = sndTapFile())
            std::fwrite(
                dst + static_cast<size_t>(base) * 2, sizeof(int16_t), static_cast<size_t>(chunkFrames) * 2, tap);
    }
}

void Sound::enqueueEvent(TimedEvent event) {
    if (FILE *log = ymLogFile()) {
        std::fprintf(log,
                     "%c %llu tid=%llu port=%u val=%02X\n",
                     event.type == EventType::YMWrite ? 'Y' : 'P',
                     static_cast<unsigned long long>(event.masterCycle),
                     static_cast<unsigned long long>(SDL_GetCurrentThreadID()),
                     event.port,
                     event.value);
    }
    const uint64_t lastRendered = lastRenderedMasterCycle_.load(std::memory_order_relaxed);
    if (event.masterCycle < lastRendered) {
        event.masterCycle = lastRendered;
        ++lateEventCount_;
    }

    if (event.type == EventType::YMWrite) {
        if ((event.port & 1u) == 0) {
            if (event.port == 0)
                queuedYMAddress_ = event.value;
        } else if (event.port == 1 && queuedYMAddress_ >= 0x24 && queuedYMAddress_ <= 0x27) {
            // Optimistically clear the timer flags in the published status so
            // a driver that just wrote $27 to reset them doesn't re-read the
            // stale set flags before the renderer applies the write.
            event.timerRegister = true;
            cachedStatus_.fetch_and(static_cast<uint8_t>(~0x03u), std::memory_order_relaxed);
        }
    }

    auto it = pendingEvents_.end();
    while (it != pendingEvents_.begin() && (it - 1)->masterCycle > event.masterCycle)
        --it;
    pendingEvents_.insert(it, event);
}

void Sound::processEventsUntil(uint64_t masterCycle) {
    while (!pendingEvents_.empty() && pendingEvents_.front().masterCycle <= masterCycle) {
        TimedEvent event = pendingEvents_.front();
        pendingEvents_.pop_front();
        applyEvent(event);
    }
}

void Sound::applyEvent(const TimedEvent &event) {
    ymInterface_.syncTimersToMasterCycle(event.masterCycle);
    if (event.type == EventType::YMWrite) {
        ym_.write(event.port & 3u, event.value);
    } else {
        psg_.write(event.value);
    }
}

std::array<int, 2> Sound::renderFM() {
    if (fmSampleRate_ == 0)
        return {0, 0};
    fmAccumulator_ += static_cast<double>(fmSampleRate_);
    while (fmAccumulator_ >= static_cast<double>(kSampleRate)) {
        previousFM_ = nextFM_;
        ym_.generate(&nextFM_, 1);
        fmAccumulator_ -= static_cast<double>(kSampleRate);
    }
    const double frac = fmAccumulator_ / static_cast<double>(kSampleRate);
    lastFM_.data[0]   = static_cast<int32_t>((static_cast<double>(previousFM_.data[0]) * (1.0 - frac)) +
                                             (static_cast<double>(nextFM_.data[0]) * frac));
    lastFM_.data[1]   = static_cast<int32_t>((static_cast<double>(previousFM_.data[1]) * (1.0 - frac)) +
                                             (static_cast<double>(nextFM_.data[1]) * frac));
    return {
        applyPreamp(std::clamp(lastFM_.data[0], -24000, 24000), kFmPreampPercent),
        applyPreamp(std::clamp(lastFM_.data[1], -24000, 24000), kFmPreampPercent),
    };
}

std::array<int, 2> Sound::filterOutput(std::array<int, 2> sample) {
    constexpr uint32_t kLowpassInput = 0x10000u - kLowpassRange;
    std::array<int, 2> out{};
    for (size_t ch = 0; ch < 2; ++ch) {
        const double input = static_cast<double>(sample[ch]);
        const double hp    = input - dcPrevInput_[ch] + (kDCBlockR * dcPrevOutput_[ch]);
        dcPrevInput_[ch]   = input;
        dcPrevOutput_[ch]  = hp;
        lowpassState_[ch] =
            ((lowpassState_[ch] * static_cast<double>(kLowpassRange)) + (hp * static_cast<double>(kLowpassInput))) /
            65536.0;
        out[ch] = static_cast<int>(lowpassState_[ch]);
    }
    return out;
}

int16_t Sound::clampMixedSample(int value, size_t channel) {
    const int32_t absValue = static_cast<int32_t>(std::abs(value));
    if (channel < peakSample_.size() && absValue > peakSample_[channel].load(std::memory_order_relaxed))
        peakSample_[channel].store(absValue, std::memory_order_relaxed); // single writer: render thread
    if (value < -32768 || value > 32767)
        ++clippedSampleCount_;
    return clamp16(value);
}

void Sound::YMInterface::resetTiming() {
    timerDeadlineMasterCycles_.fill(0);
    timerActive_.fill(false);
    busyUntilMasterCycle_ = 0;
    currentMasterCycle_   = 0;
    timerExpirations_     = 0;
    irq_                  = false;
    syncingTimers_        = false;
}

void Sound::YMInterface::setMasterCycle(uint64_t masterCycle) {
    currentMasterCycle_ = masterCycle;
}

void Sound::YMInterface::syncTimersToMasterCycle(uint64_t masterCycle) {
    if (syncingTimers_)
        return;

    currentMasterCycle_ = std::max(currentMasterCycle_, masterCycle);
    syncingTimers_      = true;
    for (int expiredCount = 0; expiredCount < 16; ++expiredCount) {
        int      expiredTimer = -1;
        uint64_t expiredAt    = 0;
        for (size_t t = 0; t < timerActive_.size(); ++t) {
            if (!timerActive_[t] || timerDeadlineMasterCycles_[t] > currentMasterCycle_)
                continue;
            if (expiredTimer < 0 || timerDeadlineMasterCycles_[t] < expiredAt) {
                expiredTimer = static_cast<int>(t);
                expiredAt    = timerDeadlineMasterCycles_[t];
            }
        }

        if (expiredTimer < 0)
            break;

        timerActive_[static_cast<size_t>(expiredTimer)]               = false;
        timerDeadlineMasterCycles_[static_cast<size_t>(expiredTimer)] = 0;
        ++timerExpirations_;
        if (m_engine)
            m_engine->engine_timer_expired(static_cast<uint32_t>(expiredTimer));
    }
    syncingTimers_ = false;
}

void Sound::YMInterface::ymfm_sync_mode_write(uint8_t data) {
    syncTimersToMasterCycle(currentMasterCycle_);
    if (m_engine)
        m_engine->engine_mode_write(data);
}

void Sound::YMInterface::ymfm_sync_check_interrupts() {
    syncTimersToMasterCycle(currentMasterCycle_);
    if (m_engine)
        m_engine->engine_check_interrupts();
}

void Sound::YMInterface::ymfm_set_timer(uint32_t tnum, int32_t duration_in_clocks) {
    if (tnum >= timerActive_.size())
        return;

    if (duration_in_clocks < 0) {
        timerActive_[tnum]               = false;
        timerDeadlineMasterCycles_[tnum] = 0;
        return;
    }

    timerActive_[tnum] = true;
    timerDeadlineMasterCycles_[tnum] =
        currentMasterCycle_ + ymClocksToMasterCycles(static_cast<uint32_t>(duration_in_clocks));
}

void Sound::YMInterface::ymfm_set_busy_end(uint32_t clocks) {
    busyUntilMasterCycle_ = currentMasterCycle_ + ymClocksToMasterCycles(clocks);
}

bool Sound::YMInterface::ymfm_is_busy() {
    return currentMasterCycle_ < busyUntilMasterCycle_;
}

void Sound::YMInterface::ymfm_update_irq(bool asserted) {
    irq_ = asserted;
}

bool Sound::YMInterface::irqAsserted() const {
    return irq_;
}

uint64_t Sound::YMInterface::timerExpirationCount() const {
    return timerExpirations_;
}

void Sound::PSG::reset() {
    tonePeriod.fill(1);
    volume.fill(0);
    counter.fill(0.0);
    tonePolarity.fill(-1);
    latchedRegister = 3;
    noiseControl    = 0;
    noiseLFSR       = 0x8000;
    noiseOutput     = 0;
    setPanning(0xFF);
}

void Sound::PSG::write(m_byte value) {
    uint8_t reg = latchedRegister;
    if (value & 0x80) {
        reg             = static_cast<uint8_t>((value >> 4) & 0x07);
        latchedRegister = reg;
    }

    switch (reg) {
        case 0:
        case 2:
        case 4: {
            const int ch = reg >> 1;
            uint16_t  period;
            if (value & 0x80)
                period = static_cast<uint16_t>((tonePeriod[ch] & 0x03F0u) | (value & 0x0Fu));
            else
                period = static_cast<uint16_t>((tonePeriod[ch] & 0x000Fu) | ((value & 0x3Fu) << 4));
            tonePeriod[ch] = std::max<uint16_t>(period, 1);
            break;
        }
        case 1:
        case 3:
        case 5: {
            const int ch = reg >> 1;
            volume[ch]   = static_cast<uint16_t>(applyPreamp(psgVolume(value & 0x0F), kPsgPreampPercent));
            leftAmp[ch]  = volume[ch];
            rightAmp[ch] = volume[ch];
            break;
        }
        case 6:
            noiseControl = value & 0x07;
            noiseLFSR    = 0x8000;
            noiseOutput  = 0;
            break;
        case 7:
            volume[3]   = static_cast<uint16_t>(applyPreamp(psgVolume(value & 0x0F), kPsgPreampPercent));
            leftAmp[3]  = volume[3];
            rightAmp[3] = volume[3];
            break;
        default:
            break;
    }
}

void Sound::PSG::setPanning(uint8_t mask) {
    for (int ch = 0; ch < 4; ++ch) {
        leftAmp[ch]  = (mask & (1u << (ch + 4))) ? volume[ch] : 0;
        rightAmp[ch] = (mask & (1u << ch)) ? volume[ch] : 0;
    }
}

std::array<int, 2> Sound::PSG::render() {
    const double step  = kPSGClock / static_cast<double>(Sound::kSampleRate);
    int          left  = 0;
    int          right = 0;

    for (int ch = 0; ch < 3; ++ch) {
        const double halfPeriod = static_cast<double>(std::max<uint16_t>(tonePeriod[ch], 1)) * 16.0;
        counter[ch] -= step;
        while (counter[ch] <= 0.0) {
            counter[ch] += halfPeriod;
            tonePolarity[ch] = -tonePolarity[ch];
        }
        if (tonePolarity[ch] > 0) {
            left += leftAmp[ch];
            right += rightAmp[ch];
        }
    }

    const uint8_t rate        = noiseControl & 0x03;
    const double  noisePeriod = (rate == 3) ? static_cast<double>(std::max<uint16_t>(tonePeriod[2], 1)) * 16.0
                                            : static_cast<double>(512u << rate);
    counter[3] -= step;
    while (counter[3] <= 0.0) {
        counter[3] += noisePeriod;
        const int oldOutput = noiseLFSR & 1u;
        if (noiseControl & 0x04) {
            const uint16_t feedback = static_cast<uint16_t>(((noiseLFSR >> 0) ^ (noiseLFSR >> 3)) & 1u);
            noiseLFSR               = static_cast<uint16_t>((noiseLFSR >> 1) | (feedback << 15));
        } else {
            noiseLFSR = static_cast<uint16_t>((noiseLFSR >> 1) | (oldOutput << 15));
        }
        noiseOutput = noiseLFSR & 1u;
    }

    if (noiseOutput) {
        left += leftAmp[3];
        right += rightAmp[3];
    }

    return {left, right};
}
