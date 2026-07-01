#pragma once
#include "system/MegaDriveEnvironment.hpp"

/**
 * @file TestSound.hpp
 * @brief Runtime test — YM2612/PSG audio output + Z80 CPU correctness.
 */

/**
 * @class TestSound
 * @brief Exercises the sound hardware and the Z80 interpreter end to end.
 *
 * Two independent checks, run back to back:
 *
 *  1. **Audio**: writes directly to the YM2612 and PSG ports (the same
 *     `Sound` methods the 68k/Z80 hardware ports forward to) to play a short
 *     retro "power-up" arpeggio on FM, then "Twinkle Twinkle Little Star" on
 *     PSG, then the same tune again on FM — deliberately recognizable rather
 *     than a single sustained test tone, so a human listener can actually
 *     judge whether the chips sound right. Doesn't require any Z80 firmware.
 *
 *  2. **Z80 CPU**: loads a 6-byte hand-assembled Z80 program into Z80 RAM
 *     (`LD A,$42` / `LD ($0010),A` / `HALT`), releases the bus/reset lines,
 *     lets the interpreter run it, then reads back Z80 RAM address $0010 and
 *     checks it became $42 — proving the ported core actually executes
 *     instructions, independent of the audio path.
 *
 * Both results are written to the VDP display as PASS/FAIL and held until
 * the user quits (Esc or window close).
 *
 * ## VDP Configuration
 *
 * | Parameter  | Value                          |
 * |------------|--------------------------------|
 * | Sync       | Internal 59.94 Hz timer        |
 * | Scaling    | Integer (max fit in display)   |
 */
class TestSound : public MegaDriveEnvironment {
    private:
    bool frameReady_ = false;

    void vSync() override;

    /// Waits for the next VBlank, dispatching VDP interrupts.
    void waitVBlank();

    /// Holds the current state for ~seconds frames, calling waitVBlank() each time.
    void holdFrames(int frames);

    /// One-time YM2612 channel-0 voice setup: algorithm 7 (all operators are
    /// independent carriers, no FM modulation chain to get wrong), operator 1
    /// as a clean, fully-sustained sine tone, operators 2-4 muted via TL. Any
    /// note can then be played by just setting FNUM/BLOCK and key on/off.
    void setupFMVoice();

    /// Plays a short retro "power-up" arpeggio (C4-E4-G4-C5) on FM.
    void playFMArpeggio();

    /// Plays "Twinkle Twinkle Little Star" (opening phrase) on the YM2612.
    void playFMMelody();

    /// Plays "Twinkle Twinkle Little Star" (opening phrase) on the PSG.
    void playPSGMelody();

    /// Loads and runs the Z80 correctness program; returns true on success.
    bool runZ80SelfTest();

    protected:
    void run() override;

    public:
    TestSound();
};
