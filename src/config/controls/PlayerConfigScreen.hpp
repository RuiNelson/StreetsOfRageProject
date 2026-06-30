#pragma once

#include "ControlsConfig.hpp"
#include "Screen.hpp"
#include <string>
#include <vector>

/// @brief Result enum for PlayerConfigScreen.
/// @see PlayerConfigScreen::getResult()
enum class PlayerConfigResult {
    BindKeys,   ///< User proceeded to key/button binding
    TestInputs, ///< User proceeded to input tester (skips binding phase)
    Back        ///< User returned to main menu
};

/// @brief Entry in the gamepad device list.
/// @see PlayerConfigScreen
struct GamepadEntry {
    SDL_JoystickID id;   ///< SDL joystick ID for this gamepad
    std::string    name; ///< Human-readable device name
};

/// @brief Second screen: configure one player's input device and launch key binding.
///
/// Presents a four-item menu:
/// 1. Connected toggle — Enable/disable player
/// 2. Select Device — Open modal to choose keyboard or gamepad
/// 3. Bind Keys / Buttons — Launch KeyBindScreen (disabled if not connected)
/// 4. Back — Return to main menu
///
/// Disabled items (2, 3) are grayed out and non-selectable when connected is false.
/// A modal dialog overlays when device selection is active, listing all connected gamepads.
/// @see Screen, PlayerConfig
class PlayerConfigScreen : public Screen {
    public:
    /// @brief Construct the player configuration screen.
    /// @param playerNum The player number (1 or 2) for display labels.
    /// @param config Reference to the PlayerConfig to edit.
    explicit PlayerConfigScreen(int playerNum, PlayerConfig &config);

    /// @brief Render the player configuration menu.
    /// @param ui Reference to UIRenderer for drawing.
    void render(UIRenderer &ui) override;

    /// @brief Handle keyboard and gamepad input events.
    /// @param e The SDL event to process.
    /// @note May dispatch to handleModalEvent() if device modal is open.
    void handleEvent(const SDL_Event &e) override;

    /// @brief Get the user's action result.
    /// @return PlayerConfigResult indicating next action (bind keys or back).
    PlayerConfigResult getResult() const {
        return m_result;
    }

    /// @brief Reset the screen state for reuse.
    /// @note Clears m_done flag, closes modal, and resets selection.
    void reset();

    private:
    int           m_playerNum; ///< Player number (1 or 2)
    PlayerConfig &m_config;    ///< Reference to the configuration being edited

    /// @brief Current menu selection (0=connected, 1=device, 2=bind, 3=back).
    int                m_sel    = 0;
    PlayerConfigResult m_result = PlayerConfigResult::Back;

    // ── Device selection modal ────────────────────────────────────────────────
    /// @brief Whether the device selection modal is currently open.
    bool m_modalOpen = false;

    /// @brief Currently selected item in modal (0=keyboard, 1+=gamepad index).
    int m_modalSel = 0;

    /// @brief List of connected gamepads retrieved at modal open time.
    std::vector<GamepadEntry> m_gamepads;

    /// @brief Open the device selection modal and populate gamepad list.
    void openModal();

    /// @brief Apply the selected device from the modal to m_config.
    void applyModal();

    /// @brief Render the device selection modal overlay.
    /// @param ui Reference to UIRenderer for drawing.
    void renderModal(UIRenderer &ui);

    /// @brief Handle events while device modal is open.
    /// @param e The SDL event to process.
    void handleModalEvent(const SDL_Event &e);

    // ── Navigation and confirmation ───────────────────────────────────────────
    /// @brief Navigate menu up or down, skipping disabled items.
    /// @param delta Movement direction (-1 up, +1 down). Wraps around at bounds.
    void navigate(int delta);

    /// @brief Handle confirmation of current menu item.
    void confirm();

    /// @brief Check if a menu item is currently enabled.
    /// @param item Menu item index (0-3).
    /// @return true if item is selectable (items 1, 2 require connected==true).
    bool isItemEnabled(int item) const;

    /// @brief Get the display name for the current device.
    /// @return String describing device (e.g., "Keyboard", "Xbox Controller").
    std::string deviceDisplayName() const;
};
