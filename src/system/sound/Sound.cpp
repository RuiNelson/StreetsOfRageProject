#include "Sound.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace {

constexpr uint32_t kYM2612Clock       = 53'693'175u / 7u;
constexpr double   kMasterClock       = 53'693'175.0;
constexpr double   kPSGClock          = 3'579'545.0;
constexpr int      kRenderChunkFrames = 256;
constexpr int      kRingBufferFrames  = 4096;
constexpr double   kOutputLowpass     = 0.58;
constexpr double   kDCBlockR          = 0.995;

int16_t clamp16(int value) {
    return static_cast<int16_t>(std::clamp(value, -32768, 32767));
}

uint64_t ymClocksToMasterCycles(uint32_t clocks) {
    return static_cast<uint64_t>(clocks) * 7ull;
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
    fmSampleRate_ = ym_.sample_rate(kYM2612Clock);
    psg_.reset();
}

Sound::~Sound() {
    stop();
    if (mutex_) {
        SDL_DestroyMutex(mutex_);
        mutex_ = nullptr;
    }
}

void Sound::start() {
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
    return readYM2612At(untimedMasterCycle_ += 64, port);
}

m_byte Sound::readYM2612At(uint64_t masterCycles, int port) {
    SDL_LockMutex(mutex_);
    processEventsUntil(masterCycles);
    ymInterface_.syncTimersToMasterCycle(masterCycles);
    m_byte result = ym_.read(static_cast<uint32_t>(port & 3));
    SDL_UnlockMutex(mutex_);
    return result;
}

void Sound::writeYM2612(int port, m_byte value) {
    writeYM2612At(untimedMasterCycle_ += 64, port, value);
}

void Sound::writeYM2612At(uint64_t masterCycles, int port, m_byte value) {
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
    writePSGAt(untimedMasterCycle_ += 64, value);
}

void Sound::writePSGAt(uint64_t masterCycles, m_byte value) {
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
    const Diagnostics result{
        .audioFramesRendered = audioFramesRendered_,
        .underruns           = underrunCount_,
        .overruns            = overrunCount_,
        .ymTimerExpirations  = ymInterface_.timerExpirationCount(),
        .queuedEvents        = pendingEvents_.size(),
        .lateEvents          = lateEventCount_,
        .clippedSamples      = clippedSampleCount_,
        .peakLeft            = peakSample_[0],
        .peakRight           = peakSample_[1],
        .ringBufferedFrames  = ringBufferedFrames_,
        .fmSourceSampleRate  = fmSampleRate_,
    };
    SDL_UnlockMutex(mutex_);
    return result;
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
    fmAccumulator_           = 1.0;
    renderMasterCycle_       = 0.0;
    lastRenderedMasterCycle_ = 0;
    untimedMasterCycle_      = 0;
    lateEventCount_          = 0;
    clippedSampleCount_      = 0;
    peakSample_.fill(0);
    dcPrevInput_.fill(0.0);
    dcPrevOutput_.fill(0.0);
    lowpassState_.fill(0.0);
    pendingEvents_.clear();
    ringBuffer_.assign(kRingBufferFrames * 2, 0);
    ringReadFrame_       = 0;
    ringWriteFrame_      = 0;
    ringBufferedFrames_  = 0;
    audioFramesRendered_ = 0;
    underrunCount_       = 0;
    overrunCount_        = 0;
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
        SDL_LockMutex(mutex_);
        for (int i = 0; i < chunkFrames; ++i) {
            const int      frame       = base + i;
            const uint64_t masterCycle = static_cast<uint64_t>(renderMasterCycle_);
            processEventsUntil(masterCycle);
            ymInterface_.syncTimersToMasterCycle(masterCycle);
            const auto fm            = renderFM();
            const auto psg           = psg_.render();
            const auto filtered      = filterOutput({fm[0] + psg[0], fm[1] + psg[1]});
            dst[frame * 2 + 0]       = clampMixedSample(filtered[0], 0);
            dst[frame * 2 + 1]       = clampMixedSample(filtered[1], 1);
            lastRenderedMasterCycle_ = masterCycle;
            renderMasterCycle_ += kMasterClock / static_cast<double>(kSampleRate);
        }
        audioFramesRendered_ += static_cast<uint64_t>(chunkFrames);
        SDL_UnlockMutex(mutex_);
    }
}

void Sound::enqueueEvent(TimedEvent event) {
    if (event.masterCycle < lastRenderedMasterCycle_) {
        event.masterCycle = lastRenderedMasterCycle_;
        ++lateEventCount_;
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
        std::clamp(lastFM_.data[0] / 4, -24000, 24000),
        std::clamp(lastFM_.data[1] / 4, -24000, 24000),
    };
}

std::array<int, 2> Sound::filterOutput(std::array<int, 2> sample) {
    std::array<int, 2> out{};
    for (size_t ch = 0; ch < 2; ++ch) {
        const double input = static_cast<double>(sample[ch]);
        const double hp    = input - dcPrevInput_[ch] + (kDCBlockR * dcPrevOutput_[ch]);
        dcPrevInput_[ch]   = input;
        dcPrevOutput_[ch]  = hp;
        lowpassState_[ch] += kOutputLowpass * (hp - lowpassState_[ch]);
        out[ch] = static_cast<int>(lowpassState_[ch]);
    }
    return out;
}

int16_t Sound::clampMixedSample(int value, size_t channel) {
    const int32_t absValue = static_cast<int32_t>(std::abs(value));
    if (channel < peakSample_.size())
        peakSample_[channel] = std::max(peakSample_[channel], absValue);
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
            volume[ch]   = static_cast<uint16_t>(psgVolume(value & 0x0F));
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
            volume[3]   = static_cast<uint16_t>(psgVolume(value & 0x0F));
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
