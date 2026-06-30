#pragma once

#include <SDL3/SDL.h>
#include <array>
#include <string>

// ─── Colour defines ───────────────────────────────────────────────────────────
#define CC_COL_BG            (SDL_Color{0, 0, 0, 255})
#define CC_COL_BTN_NORMAL    (SDL_Color{45, 45, 45, 255})
#define CC_COL_BTN_SEL       (SDL_Color{100, 100, 100, 255})
#define CC_COL_BORDER        (SDL_Color{75, 75, 75, 255})
#define CC_COL_BORDER_SEL    (SDL_Color{160, 160, 160, 255})
#define CC_COL_TEXT_WHITE    (SDL_Color{255, 255, 255, 255})
#define CC_COL_TEXT_GRAY     (SDL_Color{170, 170, 170, 255})
#define CC_COL_TEXT_YELLOW   (SDL_Color{255, 220, 0, 255})
#define CC_COL_TEXT_RED      (SDL_Color{220, 50, 50, 255})
#define CC_COL_MODAL_BG      (SDL_Color{18, 18, 18, 245})
#define CC_COL_MODAL_BORDER  (SDL_Color{130, 130, 130, 255})
#define CC_COL_OVERLAY       (SDL_Color{0, 0, 0, 180})
#define CC_COL_BTN_DISABLED  (SDL_Color{22, 22, 22, 255})
#define CC_COL_TEXT_DISABLED (SDL_Color{65, 65, 65, 255})
#define CC_COL_HINT_SEP      (SDL_Color{55, 55, 55, 255})

// ─── Layout defines ───────────────────────────────────────────────────────────
#define CC_WIN_W             640
#define CC_WIN_H             480
#define CC_SCALE_NORM        2
#define CC_SCALE_HINT        1
#define CC_CHAR_W            (8 * CC_SCALE_NORM) // 16
#define CC_CHAR_H            (8 * CC_SCALE_NORM) // 16
#define CC_HINT_CH_W         (8 * CC_SCALE_HINT) // 8
#define CC_HINT_CH_H         (8 * CC_SCALE_HINT) // 8
#define CC_HINT_SEP_Y        (CC_WIN_H - CC_HINT_CH_H - 6)
#define CC_HINT_Y            (CC_WIN_H - CC_HINT_CH_H - 2)
#define CC_PAD               10
#define CC_BTN_H             30
#define CC_BTN_W_MAIN        260
#define CC_BTN_W_FULL        (CC_WIN_W - 2 * CC_PAD)
#define CC_ROW_H             30

/// @defgroup Controls Controls Configuration Module
/// @{

/// @brief Enumerates the 8 physical buttons on a Mega Drive joypad.
///
/// Used as indices into the DeviceBinding array within PlayerConfig.
/// Directional buttons (Up, Down, Left, Right) may be auto-mapped for gamepads.
enum class MDButton : int {
    Up    = 0, ///< Directional button: up
    Down  = 1, ///< Directional button: down
    Left  = 2, ///< Directional button: left
    Right = 3, ///< Directional button: right
    A     = 4, ///< Face button: A
    B     = 5, ///< Face button: B
    C     = 6, ///< Face button: C
    Start = 7, ///< Action button: Start
    COUNT = 8  ///< Total button count; used for array sizing
};

/// @brief Returns the human-readable name for an MDButton value.
/// @param b The button enumeration value.
/// @return Pointer to a string literal (e.g., "Up", "A", "Start").
///         Returns "?" for invalid/unknown button values.
/// @note Used in UI prompts, key binding display, and tester labels.
inline const char *mdButtonName(MDButton b) {
    switch (b) {
        case MDButton::Up:
            return "Up";
        case MDButton::Down:
            return "Down";
        case MDButton::Left:
            return "Left";
        case MDButton::Right:
            return "Right";
        case MDButton::A:
            return "A";
        case MDButton::B:
            return "B";
        case MDButton::C:
            return "C";
        case MDButton::Start:
            return "Start";
        default:
            return "?";
    }
}

/// @brief Input device type selection for a player.
/// @see PlayerConfig::deviceType
enum class DeviceType {
    Keyboard, ///< Player uses keyboard input
    Gamepad   ///< Player uses gamepad/joystick input
};

/// @brief Maps a single Mega Drive button to a physical input source.
///
/// Each button in a PlayerConfig::bindings array is a DeviceBinding,
/// specifying either a keyboard key or gamepad button (mutually exclusive).
/// Directional buttons on gamepads may be auto-mapped from analog sticks.
/// @see PlayerConfig
struct DeviceBinding {
    /// @brief Keyboard input for this button (SDL_Keycode).
    /// Valid only when parent PlayerConfig::deviceType is Keyboard.
    /// Example values: SDLK_UP, SDLK_Z, SDLK_SPACE.
    SDL_Keycode key = SDLK_UNKNOWN;

    /// @brief Gamepad button for this button (SDL_GamepadButton).
    /// Valid only when parent PlayerConfig::deviceType is Gamepad.
    /// Ignored if isAutoDir is true (directional buttons auto-mapped).
    /// Cannot be SDL_GAMEPAD_BUTTON_BACK (reserved for cancel action).
    SDL_GamepadButton gpButton = SDL_GAMEPAD_BUTTON_INVALID;

    /// @brief Auto-direction flag for gamepad Up/Down/Left/Right buttons.
    /// When true, this direction button is automatically mapped to:
    /// - D-Pad buttons (SDL_GAMEPAD_BUTTON_DPAD_UP, etc.), OR
    /// - Analog stick axes (AXIS_LEFTX, AXIS_LEFTY) with ±8000 threshold.
    /// Fields @c key and @c gpButton are unused when this flag is set.
    bool isAutoDir = false;
};
;

/// @brief Complete input configuration for a single player.
///
/// Holds the device type (keyboard or gamepad), connection state, and an array
/// of DeviceBindings mapping each Mega Drive button to a physical input.
/// Used by KeyBindScreen and the main application to poll and configure input.
struct PlayerConfig {
    /// @brief Whether this player is active/connected.
    /// When false, device selection and key binding are disabled in the UI.
    bool connected = false;

    /// @brief Input device type (keyboard or gamepad).
    /// Determines which fields in each DeviceBinding are used.
    DeviceType deviceType = DeviceType::Keyboard;

    /// @brief SDL joystick ID for the assigned gamepad.
    /// Valid only when deviceType is Gamepad. Zero means no gamepad.
    SDL_JoystickID gamepadId = 0;

    /// @brief Human-readable name of the assigned gamepad.
    /// Retrieved from SDL_GetGamepadNameForID(). Empty if deviceType is Keyboard.
    std::string gamepadName;

    /// @brief Array of button bindings, indexed by MDButton enum values.
    /// Example: bindings[static_cast<int>(MDButton::A)] is the binding for the A button.
    std::array<DeviceBinding, static_cast<int>(MDButton::COUNT)> bindings{};
};

/// @brief Initializes two PlayerConfig structures with default key bindings.
/// @param p1 (output) Player 1 configuration.
///           Set to connected, keyboard device, with arrow keys + ZXCV binding.
/// @param p2 (output) Player 2 configuration.
///           Set to not connected (disabled until configured).
/// @note Default bindings for P1:
///       Up→Up, Down→Down, Left→Left, Right→Right,
///       A→Z, B→X, C→C, Start→V
/// @see PlayerConfig
inline void setDefaultConfigs(PlayerConfig &p1, PlayerConfig &p2) {
    p1.connected                          = true;
    p1.deviceType                         = DeviceType::Keyboard;
    p1.bindings[int(MDButton::Up)].key    = SDLK_UP;
    p1.bindings[int(MDButton::Down)].key  = SDLK_DOWN;
    p1.bindings[int(MDButton::Left)].key  = SDLK_LEFT;
    p1.bindings[int(MDButton::Right)].key = SDLK_RIGHT;
    p1.bindings[int(MDButton::A)].key     = SDLK_Z;
    p1.bindings[int(MDButton::B)].key     = SDLK_X;
    p1.bindings[int(MDButton::C)].key     = SDLK_C;
    p1.bindings[int(MDButton::Start)].key = SDLK_V;

    p2.connected  = false;
    p2.deviceType = DeviceType::Keyboard;
}

/// @}  // end of Controls group
