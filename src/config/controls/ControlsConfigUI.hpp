#pragma once

/// @brief Entry point for the interactive controls configuration UI.
///
/// Initializes SDL3 video and gamepad subsystems, creates a 640×480 window,
/// and runs a state machine-based UI for configuring player input devices and key bindings.
/// Intended to be called when the application detects the `--configControls` runtime flag.
///
/// The UI flow:
/// 1. MainMenuScreen: User selects Player 1, Player 2, or Exit
/// 2. PlayerConfigScreen: Configure device type (keyboard or gamepad) and connection state
/// 3. KeyBindScreen: Bind individual buttons, then test bindings
/// 4. Return to step 2 or exit
///
/// @note The function blocks until the user exits the UI or closes the window.
/// @note Configuration changes are stored in-memory; the caller must serialize
///       PlayerConfig structures if persistence is needed.
/// @note Font system must be initialized before calling (for UIRenderer text rendering).
/// @see PlayerConfig, setDefaultConfigs()
void runControlsConfig();
