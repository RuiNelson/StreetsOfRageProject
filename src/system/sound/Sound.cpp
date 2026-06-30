/**
 * @file Sound.cpp
 * @brief Mega Drive sound hardware implementation (YM2612 + SN76489).
 */

#include "Sound.hpp"

#include "gpgx_sound/psg.h"
#include "gpgx_sound/psg_shared.h"

#include <algorithm>

namespace {
// psg.c timestamps writes in NTSC *master* clock cycles (53.693175 MHz), not
// the divided 3.579545 MHz PSG/Z80 input clock — see original comment for why.
constexpr double kPsgMasterClockHz = 53693175.0;
} // namespace

// Storage for globals psg.c expects from GPGX's "shared.h"
gpgx_config_t config{};
gpgx_snd_t    snd{};

Sound::Sound(MegaDriveEnvironment *env) : env_(env) {
}

Sound::~Sound() {
    stop();
}

void Sound::start() {
    if (audioStream_)
        return;

    SDL_InitSubSystem(SDL_INIT_AUDIO);

    queueMutex_ = SDL_CreateMutex();
    chipMutex_  = SDL_CreateMutex();

    OPN2_SetChipType(ym3438_mode_ym2612);
    OPN2_Reset(&chip_);
    ymCycle_     = 0;
    ymSample_[0] = ymSample_[1] = 0;

    psg_init(PSG_INTEGRATED);
    psg_reset();
    if (!snd.blips[0])
        snd.blips[0] = blip_new(kSampleRate / 10);
    blip_set_rates(snd.blips[0], kPsgMasterClockHz, kSampleRate);
    blip_clear(snd.blips[0]);
    config.hq_psg = 1;
    psg_config(0, 150, 0xFF);

    fmRenderBuf_.assign(kBatchSize * 2, 0);
    psgRenderBuf_.assign(kBatchSize * 2, 0);
    mixRenderBuf_.resize(kBatchSize * 2);

    SDL_AudioSpec spec{SDL_AUDIO_S16, 2, kSampleRate};
    audioStream_ = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec,
                                              sdlAudioCallback, this);
    if (audioStream_)
        SDL_ResumeAudioDevice(SDL_GetAudioStreamDevice(audioStream_));

    renderRunning_ = true;
    renderThread_  = SDL_CreateThread(renderThreadEntry, "AudioRender", this);
}

void Sound::stop() {
    renderRunning_ = false;
    if (renderThread_) {
        SDL_WaitThread(renderThread_, nullptr);
        renderThread_ = nullptr;
    }
    if (audioStream_) {
        SDL_DestroyAudioStream(audioStream_);
        audioStream_ = nullptr;
    }
    if (queueMutex_) {
        SDL_DestroyMutex(queueMutex_);
        queueMutex_ = nullptr;
    }
    if (chipMutex_) {
        SDL_DestroyMutex(chipMutex_);
        chipMutex_ = nullptr;
    }
}

// ── Ring buffer (SPSC: render thread writes, callback reads) ─────────────────

int Sound::ringAvailToRead() const {
    int w = ringWrite_.load(std::memory_order_acquire);
    int r = ringRead_ .load(std::memory_order_acquire);
    return (w - r + kRingCapacity) % kRingCapacity;
}

int Sound::ringAvailToWrite() const {
    return kRingCapacity - 1 - ringAvailToRead();
}

void Sound::ringPush(const int16_t *src, int count) {
    int w = ringWrite_.load(std::memory_order_relaxed);
    for (int i = 0; i < count; ++i) {
        auto slot = static_cast<size_t>(w % kRingCapacity) * 2;
        ringData_[slot    ] = src[i * 2    ];
        ringData_[slot + 1] = src[i * 2 + 1];
        w = (w + 1) % kRingCapacity;
    }
    ringWrite_.store(w, std::memory_order_release);
}

int Sound::ringPop(int16_t *dst, int count) {
    int n = std::min(count, ringAvailToRead());
    int r = ringRead_.load(std::memory_order_relaxed);
    for (int i = 0; i < n; ++i) {
        auto slot  = static_cast<size_t>(r % kRingCapacity) * 2;
        dst[i * 2    ] = ringData_[slot    ];
        dst[i * 2 + 1] = ringData_[slot + 1];
        r = (r + 1) % kRingCapacity;
    }
    ringRead_.store(r, std::memory_order_release);
    return n;
}

// ── Chip tick helpers (called under chipMutex_) ───────────────────────────────

void Sound::tickFM(int ticks) {
    for (int i = 0; i < ticks; ++i) {
        OPN2_Clock(&chip_, ymAccm_[ymCycle_]);
        ymCycle_ = (ymCycle_ + 1) % 24;
        if (ymCycle_ == 0) {
            ymSample_[0] = ymSample_[1] = 0;
            for (auto &tick : ymAccm_) {
                ymSample_[0] += tick[0];
                ymSample_[1] += tick[1];
            }
        }
    }
}

void Sound::renderFM(int16_t *out, int sampleCount) {
    for (int i = 0; i < sampleCount; ++i) {
        tickFM(24);
        out[i * 2 + 0] = static_cast<int16_t>(std::clamp(ymSample_[0] * 11, -32768, 32767));
        out[i * 2 + 1] = static_cast<int16_t>(std::clamp(ymSample_[1] * 11, -32768, 32767));
    }
}

// ── Public interface ─────────────────────────────────────────────────────────

void Sound::writeYM2612(int port, m_byte value) {
    // ponytail: just a queue push — no chip access, no tickFM; chip stays on render thread
    SDL_LockMutex(queueMutex_);
    writeQueue_.push_back({AudioEvent::Type::FM, port, value});
    SDL_UnlockMutex(queueMutex_);
}

m_byte Sound::readYM2612(int port) {
    // Lock ordering: chipMutex_ → queueMutex_ (always; never reversed)
    SDL_LockMutex(chipMutex_);

    // Drain pending events so the chip reflects current state before reading.
    // PSG events are returned to the queue front to preserve ordering.
    std::deque<AudioEvent> local;
    SDL_LockMutex(queueMutex_);
    local.swap(writeQueue_);
    SDL_UnlockMutex(queueMutex_);

    std::deque<AudioEvent> psgBack;
    for (auto &e : local) {
        if (e.type == AudioEvent::Type::FM) {
            OPN2_Write(&chip_, static_cast<Bit32u>(e.port), e.value);
            tickFM(40);
        } else {
            psgBack.push_back(e);
        }
    }
    if (!psgBack.empty()) {
        SDL_LockMutex(queueMutex_);
        for (auto &e : psgBack)
            writeQueue_.push_front(e);
        SDL_UnlockMutex(queueMutex_);
    }

    // Advance busy counter before reading status (same rationale as before)
    tickFM(40);
    m_byte result = OPN2_Read(&chip_, static_cast<Bit32u>(port));

    SDL_UnlockMutex(chipMutex_);
    return result;
}

void Sound::writePSG(m_byte value) {
    SDL_LockMutex(queueMutex_);
    writeQueue_.push_back({AudioEvent::Type::PSG, 0, value});
    SDL_UnlockMutex(queueMutex_);
}

void Sound::endFrame() {
    // No-op: audio is rendered continuously by the dedicated render thread.
}

// ── Render thread ─────────────────────────────────────────────────────────────

int Sound::renderThreadEntry(void *data) {
    static_cast<Sound *>(data)->renderLoop();
    return 0;
}

void Sound::renderLoop() {
    unsigned psgClock = 0;

    while (renderRunning_) {
        if (ringAvailToWrite() < kBatchSize) {
            SDL_DelayNS(500'000); // ring full — back off 0.5 ms
            continue;
        }

        SDL_LockMutex(chipMutex_);

        // Drain write queue (lock ordering: chipMutex_ → queueMutex_)
        std::deque<AudioEvent> local;
        SDL_LockMutex(queueMutex_);
        local.swap(writeQueue_);
        SDL_UnlockMutex(queueMutex_);

        for (auto &e : local) {
            if (e.type == AudioEvent::Type::FM) {
                OPN2_Write(&chip_, static_cast<Bit32u>(e.port), e.value);
                tickFM(40);
            } else {
                psg_write(psgClock++, e.value);
            }
        }

        renderFM(fmRenderBuf_.data(), kBatchSize);

        unsigned batchClocks =
            static_cast<unsigned>(kBatchSize * (kPsgMasterClockHz / kSampleRate));
        batchClocks = std::max(batchClocks, psgClock);
        psg_end_frame(batchClocks);
        blip_end_frame(snd.blips[0], batchClocks);
        std::fill_n(psgRenderBuf_.begin(), kBatchSize * 2, int16_t{0});
        int psgToRead = std::min(kBatchSize, blip_samples_avail(snd.blips[0]));
        if (psgToRead > 0)
            blip_read_samples(snd.blips[0], psgRenderBuf_.data(), psgToRead);
        psgClock = 0;

        for (int i = 0; i < kBatchSize * 2; ++i) {
            int m        = static_cast<int>(fmRenderBuf_[i]) + static_cast<int>(psgRenderBuf_[i]);
            mixRenderBuf_[i] = static_cast<int16_t>(std::clamp(m, -32768, 32767));
        }

        SDL_UnlockMutex(chipMutex_);

        ringPush(mixRenderBuf_.data(), kBatchSize);
    }
}

// ── SDL audio callback (no chip access, no blocking) ─────────────────────────

void Sound::sdlAudioCallback(void *userdata, SDL_AudioStream *stream,
                              int additional_amount, int /*total_amount*/) {
    auto *self        = static_cast<Sound *>(userdata);
    int   sampleCount = additional_amount / static_cast<int>(2 * sizeof(int16_t));
    if (sampleCount <= 0)
        return;

    // ponytail: stack VLA via vector; callback batch is typically 256-1024 samples
    std::vector<int16_t> buf(static_cast<size_t>(sampleCount) * 2, int16_t{0});
    self->ringPop(buf.data(), sampleCount); // zeros already fill any underflow
    SDL_PutAudioStreamData(stream, buf.data(),
                           sampleCount * 2 * static_cast<int>(sizeof(int16_t)));
}
