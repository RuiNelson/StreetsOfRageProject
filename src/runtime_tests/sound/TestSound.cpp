/**
 * @file TestSound.cpp
 * @brief Runtime test — YM2612/PSG audio output + Z80 CPU correctness.
 */

#include "runtime_tests/sound/TestSound.hpp"
#include "util/font/Font.hpp"

#include <SDL3/SDL.h>
#include <cstdio>

// ── VRAM / layout constants (same convention as TestControllers) ───────────────

static constexpr uint16_t VRAM_PLANEA = 0xC000;
static constexpr uint16_t TILE_FONT   = 1;
static constexpr int      PLANE_W     = 64;
static constexpr uint32_t RAM_DMA_BUF = 0xFF0000;

static constexpr uint8_t PAL_GRAY   = 0;
static constexpr uint8_t PAL_YELLOW = 1;
static constexpr uint8_t PAL_GREEN  = 2;
static constexpr uint8_t PAL_RED    = 3;

static constexpr uint16_t CLR_BLACK  = 0x0000;
static constexpr uint16_t CLR_GRAY   = 0x0888;
static constexpr uint16_t CLR_YELLOW = 0x00EE;
static constexpr uint16_t CLR_GREEN  = 0x00E0;
static constexpr uint16_t CLR_RED    = 0x000E;

static uint16_t word1(uint8_t cd, uint16_t addr) {
    return static_cast<uint16_t>(((cd & 0x03u) << 14) | (addr & 0x3FFFu));
}
static uint16_t word2(uint8_t cd, uint16_t addr) {
    return static_cast<uint16_t>(((cd & 0x3Cu) << 2) | ((addr >> 14) & 0x03u));
}
static uint16_t nametableWord(uint16_t tile, uint8_t pal, bool priority) {
    return static_cast<uint16_t>((priority ? 0x8000u : 0u) | ((pal & 3u) << 13) | (tile & 0x7FFu));
}

static void writeReg(VDP &vdp, uint8_t reg, uint8_t val) {
    vdp.writeControlPort(static_cast<uint16_t>(0x8000u | (reg << 8) | val));
}
static void setVRAMWrite(VDP &vdp, uint16_t addr) {
    vdp.writeControlPort(word1(0x01, addr));
    vdp.writeControlPort(word2(0x01, addr));
}
static void setCRAMWrite(VDP &vdp, uint16_t addr) {
    vdp.writeControlPort(word1(0x03, addr));
    vdp.writeControlPort(word2(0x03, addr));
}
static void dmaFromRAM(VDP &vdp, uint32_t src, uint16_t dst, uint16_t words) {
    uint32_t srcWord = src >> 1;
    writeReg(vdp, 0x13, static_cast<uint8_t>(words & 0xFF));
    writeReg(vdp, 0x14, static_cast<uint8_t>((words >> 8) & 0xFF));
    writeReg(vdp, 0x15, static_cast<uint8_t>(srcWord & 0xFF));
    writeReg(vdp, 0x16, static_cast<uint8_t>((srcWord >> 8) & 0xFF));
    writeReg(vdp, 0x17, static_cast<uint8_t>((srcWord >> 16) & 0x7F));
    uint8_t cd = 0x01u | 0x20u;
    vdp.writeControlPort(word1(cd, dst));
    vdp.writeControlPort(word2(cd, dst));
}
static void dmaFill(VDP &vdp, uint16_t dst, uint16_t words, uint8_t fill) {
    writeReg(vdp, 0x13, static_cast<uint8_t>(words & 0xFF));
    writeReg(vdp, 0x14, static_cast<uint8_t>((words >> 8) & 0xFF));
    writeReg(vdp, 0x17, 0x80);
    uint8_t cd = 0x01u | 0x20u;
    vdp.writeControlPort(word1(cd, dst));
    vdp.writeControlPort(word2(cd, dst));
    vdp.writeDataPort(static_cast<uint16_t>(fill | (fill << 8)));
}
static void writeText(VDP &vdp, int col, int row, const char *text, uint8_t pal, bool priority = true) {
    for (int i = 0; text[i]; ++i) {
        uint8_t  ch   = static_cast<uint8_t>(text[i]);
        uint16_t tile = (ch >= 0x20 && ch <= 0x7E) ? static_cast<uint16_t>(TILE_FONT + (ch - 0x20)) : 0u;
        uint16_t addr = static_cast<uint16_t>(VRAM_PLANEA + (row * PLANE_W + col + i) * 2);
        setVRAMWrite(vdp, addr);
        vdp.writeDataPort(nametableWord(tile, pal, priority));
    }
}
static void loadPalette(VDP &vdp, uint8_t pal, const uint16_t *colors, int count) {
    setCRAMWrite(vdp, static_cast<uint16_t>(pal * 16 * 2));
    for (int i = 0; i < count; ++i) {
        vdp.writeDataPort(colors[i]);
    }
}
static void loadFont(VDP &vdp, SystemMemory &mem) {
    static constexpr int N = 0x7E - 0x20 + 1;
    for (int i = 0; i < N; ++i) {
        Font::fontCharToVDPTile(mem, static_cast<uint8_t>(0x20 + i), 1, 0, RAM_DMA_BUF + static_cast<uint32_t>(i * 32));
    }
    dmaFromRAM(vdp, RAM_DMA_BUF, static_cast<uint16_t>(TILE_FONT * 32), static_cast<uint16_t>(N * 16));
}
static void clearPlaneA(VDP &vdp) {
    setVRAMWrite(vdp, VRAM_PLANEA);
    for (int i = 0; i < PLANE_W * 32; ++i) {
        vdp.writeDataPort(0x0000);
    }
}

// ── Constructor ───────────────────────────────────────────────────────────────

TestSound::TestSound() : MegaDriveEnvironment(VDP::InternalTimer, VDP::Integer) {
    VDP &v = vdp();
    v.reset();

    writeReg(v, 0x00, 0x00);
    writeReg(v, 0x01, 0x74); // display on, VBlank IRQ, DMA, Mode 5
    writeReg(v, 0x0B, 0x00);
    writeReg(v, 0x0C, 0x81); // H40
    writeReg(v, 0x02, 0x30); // Plane A at 0xC000
    writeReg(v, 0x03, 0x2C); // Window at 0xB000
    writeReg(v, 0x04, 0x07); // Plane B at 0xE000
    writeReg(v, 0x05, 0x68); // SAT at 0xD000
    writeReg(v, 0x0D, 0x3C); // HScroll at 0xF000
    writeReg(v, 0x07, 0x00); // background: palette 0, entry 0 (black)
    writeReg(v, 0x0F, 0x02); // auto-increment 2
    writeReg(v, 0x10, 0x01); // plane 64x32

    writeReg(v, 0x0F, 0x01);
    dmaFill(v, 0x0000, 32, 0x00); // blank tile 0
    writeReg(v, 0x0F, 0x02);

    const uint16_t pal0[2] = {CLR_BLACK, CLR_GRAY};
    const uint16_t pal1[2] = {CLR_BLACK, CLR_YELLOW};
    const uint16_t pal2[2] = {CLR_BLACK, CLR_GREEN};
    const uint16_t pal3[2] = {CLR_BLACK, CLR_RED};
    loadPalette(v, PAL_GRAY, pal0, 2);
    loadPalette(v, PAL_YELLOW, pal1, 2);
    loadPalette(v, PAL_GREEN, pal2, 2);
    loadPalette(v, PAL_RED, pal3, 2);

    loadFont(v, memory());
    clearPlaneA(v);

    writeText(v, 1, 1, "SOUND TEST", PAL_YELLOW);
    writeText(v, 1, 17, "Press Esc to quit", PAL_GRAY, false);
}

// ── Frame synchronisation ────────────────────────────────────────────────────

void TestSound::vSync() {
    frameReady_ = true;
}

void TestSound::waitVBlank() {
    VDP::Interrupt discard;
    while (vdp().popInterrupt(discard)) {
    }
    frameReady_     = false;
    const Uint64 t0 = SDL_GetTicks();
    while (!frameReady_ && !shouldQuit() && (SDL_GetTicks() - t0) < 200) {
        runVDPInterrupts();
        if (frameReady_) {
            break;
        }
        SDL_Delay(1);
    }
}

void TestSound::holdFrames(int frames) {
    for (int i = 0; i < frames && !shouldQuit(); ++i) {
        const bool *keys = SDL_GetKeyboardState(nullptr);
        if (keys && keys[SDL_SCANCODE_ESCAPE]) {
            return;
        }
        waitVBlank();
    }
}

// ── Note tables ───────────────────────────────────────────────────────────────

namespace {
struct Note {
    double freq;   // Hz; 0 = rest
    int    frames; // duration at 59.94 Hz
};

constexpr double C4 = 261.63, D4 = 293.66, E4 = 329.63, F4 = 349.23, G4 = 392.00, A4 = 440.00, C5 = 523.25;

// "Twinkle Twinkle Little Star" (public domain, melody from "Ah! vous
// dirai-je, maman", 1761) — opening phrase. Universally recognizable, so a
// listener can actually judge pitch/timing correctness instead of just
// hearing "a tone."
constexpr Note kTwinkle[] = {
    {C4, 20},
    {C4, 20},
    {G4, 20},
    {G4, 20},
    {A4, 20},
    {A4, 20},
    {G4, 40},
    {0, 14},
    {F4, 20},
    {F4, 20},
    {E4, 20},
    {E4, 20},
    {D4, 20},
    {D4, 20},
    {C4, 40},
    {0, 14},
};

// Classic ascending "power-up" arpeggio — recognizable as a retro game sound
// effect rather than a melody.
constexpr Note kArpeggio[] = {
    {C4, 9},
    {E4, 9},
    {G4, 9},
    {C5, 16},
};

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
} // namespace

// ── YM2612 (FM) ───────────────────────────────────────────────────────────────

void TestSound::setupFMVoice() {
    sound().writeYM2612(0, 0x22);
    sound().writeYM2612(1, 0x00); // LFO off
    sound().writeYM2612(0, 0x27);
    sound().writeYM2612(1, 0x00); // ch3 normal mode, timers off
    sound().writeYM2612(0, 0x28);
    sound().writeYM2612(1, 0x00); // key off, channel 0

    // Algorithm 7: all four operators are independent carriers (no FM
    // modulation chain to get wrong) — operator 1 is a plain sine tone at
    // full volume and fully sustained while keyed on; operators 2-4 are
    // muted via Total Level so only operator 1 is actually heard.
    sound().writeYM2612(0, 0xB0);
    sound().writeYM2612(1, 0x07); // feedback 0, algorithm 7
    sound().writeYM2612(0, 0xB4);
    sound().writeYM2612(1, 0xC0); // pan: both channels

    sound().writeYM2612(0, 0x30);
    sound().writeYM2612(1, 0x01); // op1: DT=0, MUL=1 (fundamental)
    sound().writeYM2612(0, 0x40);
    sound().writeYM2612(1, 0x00); // op1: TL=0 (loudest)
    sound().writeYM2612(0, 0x50);
    sound().writeYM2612(1, 0x1F); // op1: AR=31 (fastest attack)
    sound().writeYM2612(0, 0x60);
    sound().writeYM2612(1, 0x00); // op1: D1R=0 (no decay while held)
    sound().writeYM2612(0, 0x70);
    sound().writeYM2612(1, 0x00); // op1: D2R=0
    sound().writeYM2612(0, 0x80);
    sound().writeYM2612(1, 0x0F); // op1: SL=0, RR=15 (fast, clean release)

    for (m_byte opBase : {0x34, 0x38, 0x3C}) { // operators 2-4: muted
        sound().writeYM2612(0, opBase);
        sound().writeYM2612(1, 0x01);
    }
    for (m_byte opBase : {0x44, 0x48, 0x4C}) {
        sound().writeYM2612(0, opBase);
        sound().writeYM2612(1, 0x7F); // TL=127: full attenuation (silent)
    }
}

void TestSound::playFMArpeggio() {
    writeText(vdp(), 1, 4, "FM  (YM2612): power-up arpeggio...", PAL_GRAY, false);
    setupFMVoice();
    for (const Note &n : kArpeggio) {
        if (n.freq > 0) {
            const YM2612Pitch pitch = ym2612Pitch(n.freq);
            sound().writeYM2612(0, 0xA4);
            sound().writeYM2612(1, static_cast<m_byte>((pitch.block << 3) | ((pitch.fnum >> 8) & 0x07)));
            sound().writeYM2612(0, 0xA0);
            sound().writeYM2612(1, static_cast<m_byte>(pitch.fnum & 0xFF));
            sound().writeYM2612(0, 0x28);
            sound().writeYM2612(1, 0xF0); // key on, all operators, channel 0
        }
        holdFrames(n.frames);
        sound().writeYM2612(0, 0x28);
        sound().writeYM2612(1, 0x00); // key off
        holdFrames(2);
    }
}

void TestSound::playFMMelody() {
    writeText(vdp(), 1, 4, "FM  (YM2612): Twinkle Twinkle...   ", PAL_GRAY, false);
    setupFMVoice();
    for (const Note &n : kTwinkle) {
        if (n.freq > 0) {
            const YM2612Pitch pitch = ym2612Pitch(n.freq);
            sound().writeYM2612(0, 0xA4);
            sound().writeYM2612(1, static_cast<m_byte>((pitch.block << 3) | ((pitch.fnum >> 8) & 0x07)));
            sound().writeYM2612(0, 0xA0);
            sound().writeYM2612(1, static_cast<m_byte>(pitch.fnum & 0xFF));
            sound().writeYM2612(0, 0x28);
            sound().writeYM2612(1, 0xF0);
            holdFrames(n.frames - 3);
            sound().writeYM2612(0, 0x28);
            sound().writeYM2612(1, 0x00);
            holdFrames(3);
        } else {
            holdFrames(n.frames);
        }
    }
}

// ── PSG ───────────────────────────────────────────────────────────────────────

void TestSound::playPSGMelody() {
    writeText(vdp(), 1, 5, "PSG (SN76489): Twinkle Twinkle...  ", PAL_GRAY, false);
    for (const Note &n : kTwinkle) {
        if (n.freq > 0) {
            // N = clock / (32 * f), a 10-bit tone register value.
            unsigned n10 = static_cast<unsigned>(3579545.0 / (32.0 * n.freq) + 0.5);
            sound().writePSG(static_cast<m_byte>(0x80 | (n10 & 0x0Fu)));
            sound().writePSG(static_cast<m_byte>((n10 >> 4) & 0x3Fu));
            sound().writePSG(0x90); // channel 0 volume: loudest
            holdFrames(n.frames - 3);
            sound().writePSG(0x9F); // channel 0 volume: silent
            holdFrames(3);
        } else {
            holdFrames(n.frames);
        }
    }
}

// ── Z80 CPU correctness ──────────────────────────────────────────────────────

bool TestSound::runZ80SelfTest() {
    writeText(vdp(), 1, 7, "Z80 CPU: running...", PAL_GRAY, false);

    z80().setBusRequest(true);
    const Uint64 t0 = SDL_GetTicks();
    while (!z80().busRequestAcked() && (SDL_GetTicks() - t0) < 500) {
        SDL_Delay(1);
    }

    // LD A,$42 ; LD ($0010),A ; HALT
    static constexpr m_byte kProgram[] = {0x3E, 0x42, 0x32, 0x10, 0x00, 0x76};
    m_byte                 *ram        = z80().ram();
    for (size_t i = 0; i < sizeof(kProgram); ++i) {
        ram[i] = kProgram[i];
    }
    ram[0x10] = 0x00; // clear the result slot before releasing the CPU

    z80().setBusRequest(false);
    z80().setReset(false);

    holdFrames(3); // give the interpreter a few frames to reach HALT

    z80().setBusRequest(true);
    const Uint64 t1 = SDL_GetTicks();
    while (!z80().busRequestAcked() && (SDL_GetTicks() - t1) < 500) {
        SDL_Delay(1);
    }
    m_byte result = z80().ram()[0x10];
    z80().setBusRequest(false);

    bool pass = (result == 0x42);
    std::fprintf(
        stderr, "[TestSound] Z80 self-test: wrote $0010=$%02X (expected $42) -> %s\n", result, pass ? "PASS" : "FAIL");
    return pass;
}

// ── Run loop ──────────────────────────────────────────────────────────────────

void TestSound::run() {
    holdFrames(5);

    playFMArpeggio();
    holdFrames(15);
    playPSGMelody();
    holdFrames(15);
    playFMMelody();
    bool z80Pass = runZ80SelfTest();

    writeText(vdp(), 1, 4, "FM  (YM2612): done            ", PAL_GRAY, false);
    writeText(vdp(), 1, 5, "PSG (SN76489): done           ", PAL_GRAY, false);
    writeText(vdp(),
              1,
              7,
              z80Pass ? "Z80 CPU: PASS              " : "Z80 CPU: FAIL              ",
              z80Pass ? PAL_GREEN : PAL_RED,
              false);

    while (!shouldQuit()) {
        const bool *keys = SDL_GetKeyboardState(nullptr);
        if (keys && keys[SDL_SCANCODE_ESCAPE]) {
            break;
        }
        waitVBlank();
    }
}
