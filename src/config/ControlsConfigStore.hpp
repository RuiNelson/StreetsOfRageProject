#pragma once
#include <string>
#include <vector>

/// @brief Input device type for a player slot.
enum class InputDevice : int { Keyboard = 0, Gamepad = 1 };

/// @brief Persistent configuration for a single player.
///
/// Bindings are encoded as strings of the form "MdButton@SDLCode",
/// e.g. "A@Z", "Up@Up", "B@south", "Up@auto" (auto-direction).
/// The caller is responsible for parsing these strings and resolving
/// SDL key/button codes at runtime.
///
/// SDL_JoystickID is omitted — it is runtime-assigned and must be resolved
/// from gamepadGuid by the caller after loading.
struct PlayerConfiguration {
    bool                     enabled    = false;
    InputDevice              deviceType = InputDevice::Keyboard;
    std::string              gamepadGuid; ///< SDL_GUIDToString of the assigned gamepad.
    std::string              gamepadName; ///< Human-readable gamepad name (for display).
    std::vector<std::string> bindings;    ///< "MdButton@SDLCode" tuples.
};

/// @brief Persistence layer for controls configuration.
///
/// Loads from and saves to @c controls.yaml in the current working directory.
/// Falls back to built-in defaults if the file is absent or malformed.
class ControlsConfigStore {
    public:
    ControlsConfigStore(); ///< Loads from controls.yaml; applies defaults on failure.
    void save();           ///< Saves to controls.yaml.

    PlayerConfiguration player1;
    PlayerConfiguration player2;
};
