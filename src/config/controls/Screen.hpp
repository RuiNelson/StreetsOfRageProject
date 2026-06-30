#pragma once

#include "UIRenderer.hpp"
#include <SDL3/SDL.h>

/// @brief Abstract base class for all UI screens in the controls configuration UI.
///
/// The controls UI is organized as a state machine of Screen implementations.
/// Each screen manages its own rendering and input handling.
/// @see MainMenuScreen, PlayerConfigScreen, KeyBindScreen
class Screen {
    protected:
    /// @brief Completion flag, set by derived class when user action is complete.
    /// When true, the main loop transitions to the next screen.
    bool m_done = false;

    public:
    virtual ~Screen() = default;

    /// @brief Render the current screen state.
    /// @param ui Reference to UIRenderer for drawing primitives and text.
    /// @note Called once per frame in the main event loop.
    virtual void render(UIRenderer &ui) = 0;

    /// @brief Handle an SDL input event.
    /// @param e The SDL_Event to process (keyboard, gamepad, etc.).
    /// @note Derived classes should update internal state and set m_done when
    ///       a navigation action is complete.
    virtual void handleEvent(const SDL_Event &e) = 0;

    /// @brief Check if this screen is complete and ready to transition.
    /// @return true if m_done is set, indicating the main loop should transition.
    bool isDone() const {
        return m_done;
    }

    /// @brief Reset the done flag for screen reuse.
    /// @note Called by the main loop before re-entering the screen.
    void resetDone() {
        m_done = false;
    }
};
