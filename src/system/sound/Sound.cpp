#include "Sound.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace {

constexpr uint32_t kYM2612Clock       = 53'693'175u / 7u;
constexpr double   kPSGClock          = 3'579'545.0;
constexpr int      kRenderChunkFrames = 256;
constexpr int      kRingBufferFrames  = 4096;

int16_t clamp16(int value) {
    return static_cast<int16_t>(std::clamp(value, -32768, 32767));
}

uint64_t clocksToNanoseconds(uint32_t clocks) {
    return (static_cast<uint64_t>(clocks) * 1'000'000'000ull) / kYM2612Clock;
}

int psgVolume(uint8_t attenuation) {
    if ((attenuation & 0x0F) == 0x0F)
        return 0;
    return static_cast<int>(1600.0 * std::pow(10.0, -static_cast<double>(attenuation & 0x0F) / 10.0));
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
    SDL_LockMutex(mutex_);
    ymInterface_.syncTimersToNow();
    m_byte result = ym_.read(static_cast<uint32_t>(port & 3));
    SDL_UnlockMutex(mutex_);
    return result;
}

void Sound::writeYM2612(int port, m_byte value) {
    SDL_LockMutex(mutex_);
    ymInterface_.syncTimersToNow();
    ym_.write(static_cast<uint32_t>(port & 3), value);
    SDL_UnlockMutex(mutex_);
}

void Sound::writePSG(m_byte value) {
    SDL_LockMutex(mutex_);
    ymInterface_.syncTimersToNow();
    psg_.write(value);
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
    fmAccumulator_ = 0.0;
    ringBuffer_.assign(kRingBufferFrames * 2, 0);
    ringReadFrame_      = 0;
    ringWriteFrame_     = 0;
    ringBufferedFrames_ = 0;
    audioFramesRendered_ = 0;
    underrunCount_      = 0;
    overrunCount_       = 0;
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
        ymInterface_.syncTimersToNow();
        for (int i = 0; i < chunkFrames; ++i) {
            const int frame    = base + i;
            const auto fm      = renderFM();
            const int psg      = psg_.render();
            dst[frame * 2 + 0] = clamp16(fm[0] + psg);
            dst[frame * 2 + 1] = clamp16(fm[1] + psg);
        }
        audioFramesRendered_ += static_cast<uint64_t>(chunkFrames);
        SDL_UnlockMutex(mutex_);
    }
}

std::array<int, 2> Sound::renderFM() {
    if (fmSampleRate_ == 0)
        return {0, 0};
    fmAccumulator_ += static_cast<double>(fmSampleRate_);
    while (fmAccumulator_ >= static_cast<double>(kSampleRate)) {
        ym_.generate(&lastFM_, 1);
        fmAccumulator_ -= static_cast<double>(kSampleRate);
    }
    return {
        std::clamp(lastFM_.data[0] / 4, -24000, 24000),
        std::clamp(lastFM_.data[1] / 4, -24000, 24000),
    };
}

void Sound::YMInterface::resetTiming() {
    timerDeadlineNS_.fill(0);
    timerActive_.fill(false);
    busyUntilNS_   = 0;
    timerExpirations_ = 0;
    irq_           = false;
    syncingTimers_ = false;
}

void Sound::YMInterface::syncTimersToNow() {
    if (syncingTimers_)
        return;

    syncingTimers_ = true;
    for (int expiredCount = 0; expiredCount < 16; ++expiredCount) {
        const uint64_t now          = SDL_GetTicksNS();
        int            expiredTimer = -1;
        uint64_t       expiredAt    = 0;
        for (size_t t = 0; t < timerActive_.size(); ++t) {
            if (!timerActive_[t] || timerDeadlineNS_[t] > now)
                continue;
            if (expiredTimer < 0 || timerDeadlineNS_[t] < expiredAt) {
                expiredTimer = static_cast<int>(t);
                expiredAt    = timerDeadlineNS_[t];
            }
        }

        if (expiredTimer < 0)
            break;

        timerActive_[static_cast<size_t>(expiredTimer)]     = false;
        timerDeadlineNS_[static_cast<size_t>(expiredTimer)] = 0;
        ++timerExpirations_;
        if (m_engine)
            m_engine->engine_timer_expired(static_cast<uint32_t>(expiredTimer));
    }
    syncingTimers_ = false;
}

void Sound::YMInterface::ymfm_sync_mode_write(uint8_t data) {
    syncTimersToNow();
    if (m_engine)
        m_engine->engine_mode_write(data);
}

void Sound::YMInterface::ymfm_sync_check_interrupts() {
    syncTimersToNow();
    if (m_engine)
        m_engine->engine_check_interrupts();
}

void Sound::YMInterface::ymfm_set_timer(uint32_t tnum, int32_t duration_in_clocks) {
    if (tnum >= timerActive_.size())
        return;

    if (duration_in_clocks < 0) {
        timerActive_[tnum]     = false;
        timerDeadlineNS_[tnum] = 0;
        return;
    }

    timerActive_[tnum]     = true;
    timerDeadlineNS_[tnum] = SDL_GetTicksNS() + clocksToNanoseconds(static_cast<uint32_t>(duration_in_clocks));
}

void Sound::YMInterface::ymfm_set_busy_end(uint32_t clocks) {
    busyUntilNS_ = SDL_GetTicksNS() + clocksToNanoseconds(clocks);
}

bool Sound::YMInterface::ymfm_is_busy() {
    return SDL_GetTicksNS() < busyUntilNS_;
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
    tonePeriod.fill(0x03FF);
    volume.fill(0x0F);
    tonePhase.fill(0.0);
    toneLevel.fill(1);
    latchedChannel = 0;
    latchedVolume  = false;
    noiseControl   = 0;
    noisePhase     = 0.0;
    noiseLFSR      = 0x8000;
    noiseLevel     = 1;
}

void Sound::PSG::write(m_byte value) {
    if (value & 0x80) {
        latchedChannel = static_cast<uint8_t>((value >> 5) & 0x03);
        latchedVolume  = (value & 0x10) != 0;
        if (latchedVolume) {
            volume[latchedChannel] = value & 0x0F;
        } else if (latchedChannel == 3) {
            noiseControl = value & 0x07;
            noiseLFSR    = 0x8000;
        } else {
            tonePeriod[latchedChannel] = static_cast<uint16_t>((tonePeriod[latchedChannel] & 0x03F0) | (value & 0x0F));
        }
    } else if (latchedVolume) {
        volume[latchedChannel] = value & 0x0F;
    } else if (latchedChannel < 3) {
        tonePeriod[latchedChannel] =
            static_cast<uint16_t>((tonePeriod[latchedChannel] & 0x000F) | ((value & 0x3F) << 4));
    } else {
        noiseControl = value & 0x07;
    }
}

int Sound::PSG::render() {
    int sample = 0;
    for (int ch = 0; ch < 3; ++ch) {
        const uint16_t period = std::max<uint16_t>(tonePeriod[ch], 1);
        const double   freq   = kPSGClock / (32.0 * static_cast<double>(period));
        tonePhase[ch] += freq / static_cast<double>(Sound::kSampleRate);
        if (tonePhase[ch] >= 1.0) {
            tonePhase[ch] -= std::floor(tonePhase[ch]);
            toneLevel[ch] = -toneLevel[ch];
        }
        sample += toneLevel[ch] * psgVolume(volume[ch]);
    }

    const uint8_t rate = noiseControl & 0x03;
    const double  freq = (rate == 3) ? (kPSGClock / (32.0 * std::max<uint16_t>(tonePeriod[2], 1)))
                                     : (kPSGClock / (512.0 * (1u << rate)));
    noisePhase += freq / static_cast<double>(Sound::kSampleRate);
    if (noisePhase >= 1.0) {
        noisePhase -= std::floor(noisePhase);
        const bool     white = (noiseControl & 0x04) != 0;
        const uint16_t feedback =
            white ? static_cast<uint16_t>((noiseLFSR ^ (noiseLFSR >> 3)) & 1u) : static_cast<uint16_t>(noiseLFSR & 1u);
        noiseLFSR  = static_cast<uint16_t>((noiseLFSR >> 1) | (feedback << 15));
        noiseLevel = (noiseLFSR & 1u) ? 1 : -1;
    }
    sample += noiseLevel * psgVolume(volume[3]);
    return sample;
}
