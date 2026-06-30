#pragma once

#include "ControlsConfigStore.hpp"
#include <data_types.hpp>

#include <string>
#include <vector>

#include <SDL3/SDL.h>

class MegaDriveEnvironment;

// ─── Input state ──────────────────────────────────────────────────────────────

/// @brief Instantaneous digital input state for a single player.
struct PlayerControlsState {
    bool connected = false; ///< True if the player's input device is present.
    bool up        = false;
    bool down      = false;
    bool left      = false;
    bool right     = false;
    bool a         = false;
    bool b         = false;
    bool c         = false;
    bool start     = false;
};

/// @brief Combined input state for both players.
struct PlayersControlState {
    PlayerControlsState player1; ///< State for player 1.
    PlayerControlsState player2; ///< State for player 2.
};

// ─── Delegate ─────────────────────────────────────────────────────────────────

/// @brief Observer interface for controller state changes.
///
/// Register an instance with Controllers::setDelegate() to receive a callback
/// whenever the digital input state of either player changes.
///
/// @warning Callbacks are invoked from the thread that calls SDL_PumpEvents
///          (typically the main loop).  Any shared state accessed inside the
///          callback must be protected by the caller.
class ControllersDelegate {
    public:
    virtual ~ControllersDelegate() = default;

    /// @brief Called each time the digital state of a player changes.
    ///
    /// @param newState  Updated state for the player whose input changed.
    virtual void controllersStateDidUpdate(PlayerControlsState newState) = 0;
};

// ─── Controllers ──────────────────────────────────────────────────────────────

/// @brief Manages SDL input and exposes a Mega Drive–compatible joypad interface.
///
/// On construction the configuration is read **once**, any gamepad GUIDs are
/// resolved to their current SDL session IDs, and an SDL event watch is
/// registered.  The configuration object is not referenced after construction.
///
/// Input state is updated via SDL's event system: no background thread or
/// polling loop is required.  The registered event watch is automatically
/// removed on destruction.
///
/// ### Mega Drive joypad protocol
///
/// The original hardware exposes two I/O ports per player:
///
/// | Port    | P1 address | P2 address | Purpose                     |
/// |---------|------------|------------|-----------------------------|
/// | Control | `$A10009`  | `$A1000B`  | Pin-direction register (TH) |
/// | Data    | `$A10003`  | `$A10005`  | Button read / TH write      |
///
/// The game selects the active button group by driving the **TH** line (bit 6
/// of the data port) via the control-port direction register:
///
/// | TH | Bit 5  | Bit 4 | Bit 3  | Bit 2 | Bit 1 | Bit 0 |
/// |----|--------|-------|--------|-------|-------|-------|
/// | 1  | /C     | /B    | /Right | /Left | /Down | /Up   |
/// | 0  | /Start | /A    | 0      | 0     | /Down | /Up   |
///
/// All data-port button bits are **active-low** (0 = pressed, 1 = released).
///
/// All public methods are **thread-safe**.
class Controllers {
    public:
    // ── Lifecycle ─────────────────────────────────────────────────────────

    /// @brief Constructs the controller manager.
    ///
    /// Reads @p configuration, resolves gamepad GUIDs to runtime SDL IDs,
    /// opens any matching gamepads, and registers an SDL event watch.
    ///
    /// @param configuration  Controls configuration for this session.
    ///                       Not retained after construction.
    /// @brief Constructs the controller manager using default configuration.
    ///
    /// Reads the controls.yaml file via ControlsConfigStore; falls back to
    /// built-in defaults if the file is absent or malformed.
    ///
    /// @param env  Owning environment (back-reference). May be nullptr in
    ///             standalone use.
    explicit Controllers(MegaDriveEnvironment *env);

    /// @brief Constructs the controller manager.
    ///
    /// Reads @p configuration, resolves gamepad GUIDs to runtime SDL IDs,
    /// opens any matching gamepads, and registers an SDL event watch.
    ///
    /// @param env            Owning environment (back-reference).
    /// @param configuration  Controls configuration for this session.
    ///                       Not retained after construction.
    Controllers(MegaDriveEnvironment *env, const ControlsConfigStore &configuration);

    /// @brief Destructor.  Removes the SDL event watch and closes any open gamepads.
    ~Controllers();

    Controllers(const Controllers &)            = delete;
    Controllers &operator=(const Controllers &) = delete;

    // ── Polling / debug ───────────────────────────────────────────────────

    /// @brief Returns a snapshot of the current input state for both players.
    ///
    /// Primarily intended for debug overlays and the controls-configuration UI.
    /// Game emulation should use the port-emulation methods below.
    ///
    /// @return A copy of the most recently received @c PlayersControlState.
    PlayersControlState getCurrentState() const;

    /// @brief Registers an observer for input-state changes.
    ///
    /// The delegate is invoked whenever the state of either player changes.
    /// Pass @c nullptr to unregister.
    ///
    /// @param delegate  Observer to register, or @c nullptr.
    ///                  Ownership is **not** transferred.
    void setDelegate(ControllersDelegate *delegate);

    // ── Mega Drive port emulation ─────────────────────────────────────────

    /// @brief Writes to Player 1's control (pin-direction) port — `$A10009`.
    /// @param value  Written byte; bit 6 controls the direction of the TH pin.
    void writePlayer1ControlPort(m_byte value);

    /// @brief Writes to Player 2's control (pin-direction) port — `$A1000B`.
    /// @param value  Written byte; bit 6 controls the direction of the TH pin.
    void writePlayer2ControlPort(m_byte value);

    /// @brief Reads Player 1's data port — `$A10003`.
    ///
    /// Returns active-low button bits for the group selected by the current
    /// TH-line state of Player 1.
    ///
    /// @return 8-bit active-low button byte.
    m_byte readPlayer1DataPort();

    /// @brief Reads Player 2's data port — `$A10005`.
    ///
    /// Returns active-low button bits for the group selected by the current
    /// TH-line state of Player 2.
    ///
    /// @return 8-bit active-low button byte.
    m_byte readPlayer2DataPort();

    /// @brief Writes to Player 1's data port — `$A10003`.
    ///
    /// Bit 6 of the written value drives the TH line, selecting which button
    /// group is exposed on the next read.
    ///
    /// @param value  Byte written by the game; bit 6 = TH output level.
    void writePlayer1DataPort(m_byte value);

    /// @brief Writes to Player 2's data port — `$A10005`.
    ///
    /// Bit 6 of the written value drives the TH line, selecting which button
    /// group is exposed on the next read.
    ///
    /// @param value  Byte written by the game; bit 6 = TH output level.
    void writePlayer2DataPort(m_byte value);

    private:
    // ── Internal types ────────────────────────────────────────────────────

    /// @brief Mega Drive logical buttons.
    enum class MdButton { Up, Down, Left, Right, A, B, C, Start };

    /// @brief SDL source type for a resolved binding.
    enum class SourceKind {
        Keyboard,      ///< SDL keyboard scancode.
        GamepadButton, ///< SDL gamepad digital button.
        GamepadAxis,   ///< SDL gamepad left-stick axis (directional).
    };

    /// @brief One resolved binding: a single MD button mapped to an SDL input source.
    struct Binding {
        MdButton          mdButton;
        SourceKind        sourceKind;
        SDL_Scancode      scancode;   ///< Used when sourceKind == Keyboard.
        SDL_GamepadButton gpadButton; ///< Used when sourceKind == GamepadButton.
        ///< GamepadAxis infers axis and sign from mdButton (Up/Down → Y, Left/Right → X).
    };

    /// @brief Runtime state for one player's input slot.
    struct PlayerSlot {
        InputDevice          device    = InputDevice::Keyboard;
        SDL_JoystickID       gamepadId = 0;       ///< 0 when not yet resolved.
        SDL_Gamepad         *gamepad   = nullptr; ///< nullptr when not open.
        std::string          gamepadGuid;         ///< Target GUID string (from config).
        std::vector<Binding> bindings;
        bool                 hasAxisBindings = false; ///< True if any binding uses GamepadAxis.

        /// @brief Last known left-stick axis values, updated on SDL_EVENT_GAMEPAD_AXIS_MOTION.
        Sint16 axisX = 0;
        Sint16 axisY = 0;

        /// @brief D-pad button state for "auto" direction bindings.
        /// Tracked separately so D-pad and analogue stick can both drive directions.
        bool dpadUp    = false;
        bool dpadDown  = false;
        bool dpadLeft  = false;
        bool dpadRight = false;

        /// @name Mega Drive port shadow registers
        /// @{
        m_byte controlPort = 0x00; ///< Last value written to the control port.
        m_byte dataPortOut = 0x40; ///< Last value written to the data port (TH defaults high).
        /// @}
    };

    // ── Private methods ───────────────────────────────────────────────────

    /// @brief Builds a PlayerSlot by parsing all bindings in a PlayerConfiguration.
    ///
    /// Unrecognised binding strings are logged and skipped.
    static PlayerSlot buildSlot(const PlayerConfiguration &cfg);

    /// @brief Scans connected gamepads and opens the one matching slot.gamepadGuid.
    ///
    /// Does nothing when no matching gamepad is found or the device type is Keyboard.
    static void tryOpenGamepad(PlayerSlot &slot);

    /// @brief Dispatches an SDL event to the appropriate input handler.
    ///
    /// Called from the SDL event watch on every SDL event.  Acquires the state
    /// mutex internally; must not be called while the mutex is held.
    void handleEvent(const SDL_Event &event);

    /// @brief Handles a key-down or key-up event for a keyboard slot.
    ///
    /// @param slot     Player slot to update (must use Keyboard device).
    /// @param scancode Scancode of the key that changed.
    /// @param pressed  True on key-down, false on key-up.
    /// @param state    State struct to update in place.
    static void handleKeyEvent(const PlayerSlot &slot, SDL_Scancode scancode, bool pressed, PlayerControlsState &state);

    /// @brief Handles a gamepad button-down or button-up event.
    ///
    /// @param slot    Player slot to update (must own the gamepad that fired the event).
    /// @param button  Button that changed.
    /// @param pressed True on button-down, false on button-up.
    /// @param state   State struct to update in place.
    static void
    handleGamepadButtonEvent(PlayerSlot &slot, SDL_GamepadButton button, bool pressed, PlayerControlsState &state);

    /// @brief Handles a gamepad axis-motion event and recomputes axis-bound directions.
    ///
    /// @param slot  Player slot to update (axis values are stored here).
    /// @param axis  Axis that moved.
    /// @param value New axis value.
    /// @param state State struct to update in place.
    static void
    handleGamepadAxisEvent(PlayerSlot &slot, SDL_GamepadAxis axis, Sint16 value, PlayerControlsState &state);

    /// @brief Sets one MD button in @p state to @p pressed.
    static void setButton(PlayerControlsState &state, MdButton button, bool pressed);

    /// @brief Encodes a button state as a Mega Drive data-port read byte (active-low).
    ///
    /// @param state   Current button state for the player.
    /// @param thHigh  True when the TH output line is driven high (bit 6 of
    ///                the last data-port write = 1).
    /// @return Active-low 8-bit byte suitable for returning to the game loop.
    static m_byte encodeDataPort(const PlayerControlsState &state, bool thHigh);

    /// @brief SDL event watch callback — delegates to handleEvent().
    static bool sdlEventFilter(void *userdata, SDL_Event *event);

    // ── Data members ──────────────────────────────────────────────────────

    /// Owning environment (back-reference). May be nullptr in standalone use.
    MegaDriveEnvironment *env_ = nullptr;

    PlayerSlot player1Slot_;
    PlayerSlot player2Slot_;

    /// @name Button state and port registers — shared between event callback and game thread
    /// @{
    mutable SDL_Mutex  *stateMutex_ = nullptr;
    PlayerControlsState state1_     = {};
    PlayerControlsState state2_     = {};
    /// @}

    /// @name Delegate
    /// @{
    mutable SDL_Mutex   *delegateMutex_ = nullptr;
    ControllersDelegate *delegate_      = nullptr;
    /// @}
};
