#pragma once

#include "Screen.hpp"

/// @brief Result enum for MainMenuScreen.
/// @see MainMenuScreen::getResult()
enum class MainMenuResult {
    Player1, ///< User selected Player 1 configuration
    Player2, ///< User selected Player 2 configuration
    Exit     ///< User selected Exit (or window closed)
};

/// @brief First screen of the controls configuration UI.
///
/// Presents a menu with three options: "Player 1", "Player 2", and "Exit".
/// User navigates with arrow keys or gamepad D-Pad, confirms with Enter or East button.
/// Esc/Backspace returns to main application.
/// @see Screen
class MainMenuScreen : public Screen {
    public:
    /// @brief Construct the main menu screen.
    MainMenuScreen();

    /// @brief Render the main menu display.
    /// @param ui Reference to UIRenderer for drawing.
    void render(UIRenderer &ui) override;

    /// @brief Handle keyboard and gamepad input events.
    /// @param e The SDL event to process.
    void handleEvent(const SDL_Event &e) override;

    /// @brief Get the user's menu selection result.
    /// @return MainMenuResult indicating which option was selected.
    /// @note Only valid after isDone() returns true.
    MainMenuResult getResult() const {
        return m_result;
    }

    /// @brief Reset the screen state for reuse.
    /// @note Clears m_done flag and resets selection to Player 1.
    void reset();

    private:
    int            m_sel    = 0;                    ///< Current selection index (0=P1, 1=P2, 2=Exit)
    MainMenuResult m_result = MainMenuResult::Exit; ///< Result to return when done

    /// @brief Handle selection confirmation.
    void confirm();

    /// @brief Navigate menu up or down.
    /// @param delta Movement direction (-1 up, +1 down). Wraps around at bounds.
    void navigate(int delta);
};
