#pragma once

#include "ControlsConfig.hpp"
#include "Screen.hpp"
#include <SDL3/SDL.h>
#include <vector>

/// @brief Third screen: interactive key and button binding with live tester.
///
/// Two-phase workflow:
/// - **Binding Phase**: Prompts for each Mega Drive button one at a time.
///   User presses a key (keyboard) or button (gamepad) to assign.
///   Directional buttons are auto-assigned on gamepads (not prompted).
/// - **Testing Phase**: Displays all buttons in a grid. Buttons turn red when
///   pressed (live state), yellow when released. User verifies bindings before saving.
///
/// Flow:
/// 1. reset() called before screen shown; creates working copy of config
/// 2. Binding phase: iterate through m_buttons, prompt for each one
/// 3. Testing phase: display tester grid, poll button states, allow save/cancel
/// 4. On save: write working copy back to m_config
/// 5. On cancel: discard working copy, return to PlayerConfigScreen
///
/// Esc or SDL_GAMEPAD_BUTTON_BACK at any time cancels (discards all changes).
/// Enter/East in tester phase saves and exits.
/// @see Screen, PlayerConfig
class KeyBindScreen : public Screen {
    public:
    /// @brief Construct the key binding screen.
    /// @param playerNum The player number (1 or 2) for display labels.
    /// @param config Reference to the PlayerConfig to edit.
    KeyBindScreen(int playerNum, PlayerConfig &config);

    /// @brief Destructor: closes any open gamepad.
    ~KeyBindScreen() override;

    /// @brief Render the current binding/testing screen.
    /// @param ui Reference to UIRenderer for drawing.
    void render(UIRenderer &ui) override;

    /// @brief Handle keyboard and gamepad input events.
    /// @param e The SDL event to process.
    void handleEvent(const SDL_Event &e) override;

    /// @brief Check if user cancelled (pressed Esc/Back instead of saving).
    /// @return true if binding was cancelled and discarded.
    bool wasCancelled() const {
        return m_cancelled;
    }

    /// @brief Reset the screen state before showing.
    /// @note Creates working copy of m_config, initializes phase/index,
    ///       builds button list, applies auto-directions for gamepad.
    void reset();

    /// @brief Reset directly to the testing phase, skipping binding.
    /// @note Working copy of m_config is made; no binding prompts are shown.
    void resetToTest();

    private:
    /// @brief Internal phase enumeration.
    enum class Phase {
        Binding, ///< Prompting for individual button input
        Testing  ///< Displaying tester grid
    };

    int           m_playerNum; ///< Player number (1 or 2)
    PlayerConfig &m_config;    ///< Authoritative config (read-only during screen)
    PlayerConfig  m_temp;      ///< Working copy; only saved on successful exit

    Phase                 m_phase     = Phase::Binding; ///< Current phase
    bool                  m_cancelled = false;          ///< Whether binding was cancelled
    int                   m_bindIdx   = 0;              ///< Index into m_buttons list
    std::vector<MDButton> m_buttons;                    ///< Buttons to bind (order matters)

    SDL_Gamepad *m_gamepad = nullptr; ///< Open gamepad for polling (if gamepad device)

    /// @brief Build the list of buttons to bind based on device type.
    /// For keyboard: all 8 buttons. For gamepad: only face buttons (A, B, C, Start).
    void buildButtonList();

    /// @brief Auto-assign direction buttons for gamepad devices.
    /// Marks Up/Down/Left/Right with isAutoDir=true; user won't be prompted.
    void applyAutoDirections();

    /// @brief Open the assigned gamepad for input polling.
    void openGamepad();

    /// @brief Close any open gamepad.
    void closeGamepad();

    /// @brief Advance binding index; transition to Testing when all buttons done.
    void advance();

    /// @brief Cancel binding without saving; mark as cancelled and done.
    void cancelOut();

    /// @brief Save working copy to authoritative config and exit.
    void saveAndExit();

    // ── Rendering helpers ────────────────────────────────────────────────────
    /// @brief Render binding phase UI (prompt for current button).
    /// @param ui Reference to UIRenderer for drawing.
    void renderBinding(UIRenderer &ui);

    /// @brief Render testing phase UI (button grid with live state).
    /// @param ui Reference to UIRenderer for drawing.
    void renderTester(UIRenderer &ui);

    /// @brief Information for one button box in the tester grid.
    struct BoxInfo {
        int         x, y, w, h; ///< Position and dimensions of the box
        MDButton    btn;        ///< Which button this box represents
        const char *label;      ///< Display label for the button
    };

    /// @brief Build layout information for all 8 button boxes in tester grid.
    /// @return Vector of BoxInfo structures with computed positions.
    std::vector<BoxInfo> buildTesterLayout() const;

    /// @brief Check if a button is currently pressed.
    /// @param btn The Mega Drive button to check.
    /// @return true if the button's assigned physical input is currently pressed.
    /// @note Queries keyboard state or gamepad buttons/axes in real-time.
    bool isPressed(MDButton btn) const;
};
