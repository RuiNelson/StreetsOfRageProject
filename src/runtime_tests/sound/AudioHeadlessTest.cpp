#include "runtime_tests/sound/AudioHeadlessTest.hpp"

#include "system/sound/Sound.hpp"
#include "system/z80/Z80.hpp"

#include <SDL3/SDL.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

namespace {

struct StereoEnergy {
    uint64_t left  = 0;
    uint64_t right = 0;
};

void ymWrite(Sound &sound, uint8_t reg, uint8_t value) {
    sound.writeYM2612(0, reg);
    sound.writeYM2612(1, value);
}

struct YM2612Pitch {
    int      block;
    unsigned fnum;
};

YM2612Pitch ym2612Pitch(double freq) {
    constexpr double ymClock = 53'693'175.0 / 7.0;
    constexpr double ymRate  = ymClock / 144.0;
    for (int block = 1; block <= 7; ++block) {
        const double scale = static_cast<double>(1u << (block - 1));
        const auto   fnum  = static_cast<unsigned>((freq * 1'048'576.0 / (ymRate * scale)) + 0.5);
        if (fnum <= 0x3FF)
            return {block, fnum};
    }
    return {7, 0x3FF};
}

void setupDiagnosticFM(Sound &sound, uint8_t pan) {
    sound.resetForDiagnostics();
    ymWrite(sound, 0x22, 0x00);
    ymWrite(sound, 0x27, 0x00);
    ymWrite(sound, 0x28, 0x00);

    ymWrite(sound, 0xB0, 0x07);
    ymWrite(sound, 0xB4, pan);

    ymWrite(sound, 0x30, 0x01);
    ymWrite(sound, 0x40, 0x00);
    ymWrite(sound, 0x50, 0x1F);
    ymWrite(sound, 0x60, 0x00);
    ymWrite(sound, 0x70, 0x00);
    ymWrite(sound, 0x80, 0x0F);

    for (uint8_t reg : {uint8_t{0x34}, uint8_t{0x38}, uint8_t{0x3C}})
        ymWrite(sound, reg, 0x01);
    for (uint8_t reg : {uint8_t{0x44}, uint8_t{0x48}, uint8_t{0x4C}})
        ymWrite(sound, reg, 0x7F);
}

void keyOnA4(Sound &sound) {
    const YM2612Pitch pitch = ym2612Pitch(440.0);
    ymWrite(sound, 0xA4, static_cast<uint8_t>((pitch.block << 3) | ((pitch.fnum >> 8) & 0x07)));
    ymWrite(sound, 0xA0, static_cast<uint8_t>(pitch.fnum & 0xFF));
    ymWrite(sound, 0x28, 0xF0);
}

void keyOff(Sound &sound) {
    ymWrite(sound, 0x28, 0x00);
}

StereoEnergy energyOf(const std::vector<int16_t> &samples) {
    StereoEnergy energy;
    for (size_t i = 0; i + 1 < samples.size(); i += 2) {
        energy.left += static_cast<uint64_t>(std::abs(static_cast<int>(samples[i])));
        energy.right += static_cast<uint64_t>(std::abs(static_cast<int>(samples[i + 1])));
    }
    return energy;
}

uint64_t monoEnergy(const std::vector<int16_t> &samples) {
    const StereoEnergy e = energyOf(samples);
    return e.left + e.right;
}

void render(Sound &sound, std::vector<int16_t> &samples, int frames) {
    samples.assign(static_cast<size_t>(frames) * 2, 0);
    sound.renderForDiagnostics(samples.data(), frames);
}

void reportCheck(const char *name, bool pass) {
    std::fprintf(stderr, "[AudioHeadless] %-32s %s\n", name, pass ? "PASS" : "FAIL");
}

void reportEnergy(const char *name, StereoEnergy energy) {
    std::fprintf(stderr,
                 "[AudioHeadless]   %-30s L=%llu R=%llu\n",
                 name,
                 static_cast<unsigned long long>(energy.left),
                 static_cast<unsigned long long>(energy.right));
}

bool testYMStereoAndKeyOff() {
    Sound                sound(nullptr);
    std::vector<int16_t> samples;

    setupDiagnosticFM(sound, 0x80);
    keyOnA4(sound);
    render(sound, samples, 4096);
    const StereoEnergy leftOnly = energyOf(samples);
    const bool         leftPan  = leftOnly.left > 40'000 && leftOnly.left > (leftOnly.right * 4 + 1);
    reportCheck("YM2612 pan left", leftPan);
    if (!leftPan)
        reportEnergy("left pan energy", leftOnly);

    keyOff(sound);
    render(sound, samples, 4096);
    const bool released = monoEnergy(samples) < ((leftOnly.left + leftOnly.right) / 3);
    reportCheck("YM2612 key off/release", released);
    if (!released)
        reportEnergy("release energy", energyOf(samples));

    setupDiagnosticFM(sound, 0x40);
    keyOnA4(sound);
    render(sound, samples, 4096);
    const StereoEnergy rightOnly = energyOf(samples);
    const bool         rightPan  = rightOnly.right > 40'000 && rightOnly.right > (rightOnly.left * 4 + 1);
    reportCheck("YM2612 pan right", rightPan);
    if (!rightPan)
        reportEnergy("right pan energy", rightOnly);

    const Sound::Diagnostics diag     = sound.diagnostics();
    const bool               counters = diag.audioFramesRendered >= 4096 && diag.fmSourceSampleRate > 0 &&
                                        std::max(diag.peakLeft, diag.peakRight) > 0 && diag.clippedSamples == 0;
    reportCheck("audio diagnostics counters", counters);

    return leftPan && released && rightPan && counters;
}

bool testYMTimerStatus() {
    Sound sound(nullptr);
    sound.resetForDiagnostics();

    const uint8_t initial = sound.readYM2612(0);
    ymWrite(sound, 0x24, 0xFF);
    ymWrite(sound, 0x25, 0x03);
    ymWrite(sound, 0x27, 0x05);

    uint8_t status = 0;
    for (int i = 0; i < 20; ++i) {
        SDL_Delay(1);
        status = sound.readYM2612(0);
        if (status & 0x01)
            break;
    }

    const Sound::Diagnostics expiredDiag = sound.diagnostics();
    ymWrite(sound, 0x27, 0x10);
    const uint8_t cleared = sound.readYM2612(0);

    const bool pass = ((initial & 0x03) == 0) && ((status & 0x01) != 0) && ((cleared & 0x01) == 0) &&
                      expiredDiag.ymTimerExpirations > 0;
    reportCheck("YM2612 timer A/status", pass);
    return pass;
}

bool testPSGToneAndVolume() {
    Sound                sound(nullptr);
    std::vector<int16_t> loud;
    std::vector<int16_t> silent;
    sound.resetForDiagnostics();

    constexpr double a4 = 440.0;
    const unsigned   n  = static_cast<unsigned>(3'579'545.0 / (32.0 * a4) + 0.5);
    sound.writePSG(static_cast<m_byte>(0x80 | (n & 0x0F)));
    sound.writePSG(static_cast<m_byte>((n >> 4) & 0x3F));
    sound.writePSG(0x90);
    render(sound, loud, 4096);

    sound.writePSG(0x9F);
    render(sound, silent, 4096);

    const uint64_t loudEnergy   = monoEnergy(loud);
    const uint64_t silentEnergy = monoEnergy(silent);
    const bool     pass         = loudEnergy > 100'000 && silentEnergy < (loudEnergy / 8);
    reportCheck("PSG tone/volume", pass);
    return pass;
}

bool testZ80SelfTest() {
    Z80 z80(nullptr);
    z80.start();
    z80.setBusRequest(true);

    const Uint64 t0 = SDL_GetTicks();
    while (!z80.busRequestAcked() && (SDL_GetTicks() - t0) < 500)
        SDL_Delay(1);

    static constexpr m_byte kProgram[] = {0x3E, 0x42, 0x32, 0x10, 0x00, 0x76};
    for (size_t i = 0; i < sizeof(kProgram); ++i)
        z80.ram()[i] = kProgram[i];
    z80.ram()[0x10] = 0x00;

    z80.setBusRequest(false);
    z80.setReset(false);
    SDL_Delay(20);

    z80.setBusRequest(true);
    const Uint64 t1 = SDL_GetTicks();
    while (!z80.busRequestAcked() && (SDL_GetTicks() - t1) < 500)
        SDL_Delay(1);

    const m_byte result = z80.ram()[0x10];
    z80.stop();

    const bool pass = result == 0x42;
    reportCheck("Z80 reset/bus/self-test", pass);
    return pass;
}

void writeLE16(std::ofstream &out, uint16_t value) {
    out.put(static_cast<char>(value & 0xFF));
    out.put(static_cast<char>((value >> 8) & 0xFF));
}

void writeLE32(std::ofstream &out, uint32_t value) {
    writeLE16(out, static_cast<uint16_t>(value & 0xFFFF));
    writeLE16(out, static_cast<uint16_t>((value >> 16) & 0xFFFF));
}

bool writeWav(const std::string &path, const std::vector<int16_t> &samples) {
    std::ofstream out(path, std::ios::binary);
    if (!out)
        return false;

    const uint32_t dataBytes = static_cast<uint32_t>(samples.size() * sizeof(int16_t));
    out.write("RIFF", 4);
    writeLE32(out, 36 + dataBytes);
    out.write("WAVE", 4);
    out.write("fmt ", 4);
    writeLE32(out, 16);
    writeLE16(out, 1);
    writeLE16(out, 2);
    writeLE32(out, Sound::kSampleRate);
    writeLE32(out, Sound::kSampleRate * 2u * sizeof(int16_t));
    writeLE16(out, 2u * sizeof(int16_t));
    writeLE16(out, 16);
    out.write("data", 4);
    writeLE32(out, dataBytes);
    for (int16_t sample : samples)
        writeLE16(out, static_cast<uint16_t>(sample));
    return static_cast<bool>(out);
}

bool writeDiagnosticWav(const std::string &path) {
    Sound sound(nullptr);
    setupDiagnosticFM(sound, 0xC0);
    keyOnA4(sound);

    constexpr double c4 = 261.63;
    const unsigned   n  = static_cast<unsigned>(3'579'545.0 / (32.0 * c4) + 0.5);
    sound.writePSG(static_cast<m_byte>(0x80 | (n & 0x0F)));
    sound.writePSG(static_cast<m_byte>((n >> 4) & 0x3F));
    sound.writePSG(0x92);

    std::vector<int16_t> samples;
    render(sound, samples, Sound::kSampleRate * 2);
    const bool pass = writeWav(path, samples);
    std::fprintf(stderr, "[AudioHeadless] WAV %s: %s\n", pass ? "written" : "failed", path.c_str());
    return pass;
}

} // namespace

int runAudioHeadlessTest(const AudioHeadlessOptions &options) {
    bool pass = true;
    pass &= testYMStereoAndKeyOff();
    pass &= testYMTimerStatus();
    pass &= testPSGToneAndVolume();
    pass &= testZ80SelfTest();

    if (!options.wavPath.empty())
        pass &= writeDiagnosticWav(options.wavPath);

    return pass ? 0 : 1;
}
