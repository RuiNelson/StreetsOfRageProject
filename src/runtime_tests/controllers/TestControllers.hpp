#pragma once
#include "system/MegaDriveEnvironment.hpp"

/**
 * @file TestControllers.hpp
 * @brief Runtime test — Mega Drive controller readout via VDP display.
 */

/**
 * @class TestControllers
 * @brief Interactive controller readout test using the VDP emulator.
 *
 * Displays the current state of Player 1 and Player 2 controllers on the
 * VDP framebuffer.
 *
 * Controller state is obtained by exercising the real Mega Drive joypad
 * protocol via the emulated hardware ports — the same I/O that the 68k
 * CPU would perform during gameplay. This is not a debug accessor; it
 * tests the full port-emulation path.
 *
 * ## VDP Configuration
 *
 * | Parameter  | Value                          |
 * |------------|--------------------------------|
 * | Sync       | VSync 1:1 (monitor refresh)    |
 * | Scaling    | Integer (max fit in display)    |
 *
 * ## UI Layout
 *
 *  Player 1              Connected
 *
 *         Up               Start
 *   Left Down Right      A   B   C
 *
 *  Player 2              Disconnected
 *
 *         Up               Start
 *   Left Down Right      A   B   C
 *
 *           Press Esc to quit
 *
 * ----------------------------------------------
 *  "Player 1" and "Player 2" should appear in bright yellow
 *  "Connected" should appear in bright green, "Disconnected" in bright red
 *  Gamepad keys should appear in gray when not pressed, light up in bright yellow when pressed
 *  Background should be Black
 *
 *
 * @note Frame synchronisation uses the VDP interrupt queue: run() drives
 *       runVDPInterrupts() until a vSync arrives before updating the display.
 */
class TestControllers : public MegaDriveEnvironment {
    private:
    /// Set by vSync() (on the run() thread) to signal a fresh frame is ready.
    bool frameReady_ = false;

    /// Waits for the next fresh VBlank by dispatching VDP interrupts.
    void waitVBlank();

    void vSync() override;

    protected:
    /**
     * @brief Runs the interactive controller readout test (on the CPU thread).
     *
     * Exits when Esc is pressed or the window is closed.
     */
    void run() override;

    public:
    /**
     * @brief Constructs the test and initialises VDP + controller state.
     *
     * Performs VDP reset and loads the 8×8 font, palettes and static labels.
     */
    TestControllers();
};