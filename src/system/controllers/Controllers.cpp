#include "Controllers.hpp"

#include <optional>
#include <string>
#include <unordered_map>
#include <utility>

// ─── Module constants ─────────────────────────────────────────────────────────

namespace {

/// Left-stick deadzone threshold (≈ 25 % of the full ±32767 range).
constexpr Sint16 kAxisDeadzone = 8000;

// ─── Utility helpers ──────────────────────────────────────────────────────────

/// @brief Splits @p s at the first occurrence of @p sep.
/// @return Pair {before, after}, or nullopt when @p sep is not present.
std::optional<std::pair<std::string, std::string>> splitOnce(const std::string &s, char sep) {
    const auto pos = s.find(sep);
    if (pos == std::string::npos)
        return std::nullopt;
    return std::pair{s.substr(0, pos), s.substr(pos + 1)};
}

/// @brief Converts an SDL_GUID to its canonical 32-character hex string.
std::string guidToString(SDL_GUID guid) {
    char buf[33] = {};
    SDL_GUIDToString(guid, buf, static_cast<int>(sizeof(buf)));
    return buf;
}

/// @brief Returns true when both states describe identical button presses.
bool statesEqual(const PlayerControlsState &a, const PlayerControlsState &b) noexcept {
    return a.connected == b.connected && a.up == b.up && a.down == b.down && a.left == b.left && a.right == b.right &&
           a.a == b.a && a.b == b.b && a.c == b.c && a.start == b.start;
}

} // namespace

// ─── Construction / destruction ───────────────────────────────────────────────

Controllers::Controllers(MegaDriveEnvironment *env) : Controllers(env, ControlsConfigStore{}) {
}

Controllers::Controllers(MegaDriveEnvironment *env, const ControlsConfigStore &configuration) : env_(env) {
    SDL_InitSubSystem(SDL_INIT_GAMEPAD);

    stateMutex_    = SDL_CreateMutex();
    delegateMutex_ = SDL_CreateMutex();

    player1Slot_ = buildSlot(configuration.player1);
    player2Slot_ = buildSlot(configuration.player2);

    tryOpenGamepad(player1Slot_);
    tryOpenGamepad(player2Slot_);

    state1_.connected = configuration.player1.enabled &&
                        ((player1Slot_.device == InputDevice::Keyboard) || (player1Slot_.gamepad != nullptr));
    state2_.connected = configuration.player2.enabled &&
                        ((player2Slot_.device == InputDevice::Keyboard) || (player2Slot_.gamepad != nullptr));

    SDL_AddEventWatch(sdlEventFilter, this);
}

Controllers::~Controllers() {
    SDL_RemoveEventWatch(sdlEventFilter, this);

    if (player1Slot_.gamepad)
        SDL_CloseGamepad(player1Slot_.gamepad);
    if (player2Slot_.gamepad)
        SDL_CloseGamepad(player2Slot_.gamepad);

    if (stateMutex_) {
        SDL_DestroyMutex(stateMutex_);
        stateMutex_ = nullptr;
    }
    if (delegateMutex_) {
        SDL_DestroyMutex(delegateMutex_);
        delegateMutex_ = nullptr;
    }
}

// ─── Public API ───────────────────────────────────────────────────────────────

PlayersControlState Controllers::getCurrentState() const {
    SDL_LockMutex(stateMutex_);
    PlayersControlState snapshot{state1_, state2_};
    SDL_UnlockMutex(stateMutex_);
    return snapshot;
}

void Controllers::setDelegate(ControllersDelegate *delegate) {
    SDL_LockMutex(delegateMutex_);
    delegate_ = delegate;
    SDL_UnlockMutex(delegateMutex_);
}

void Controllers::writePlayer1ControlPort(m_byte value) {
    SDL_LockMutex(stateMutex_);
    player1Slot_.controlPort = value;
    SDL_UnlockMutex(stateMutex_);
}

void Controllers::writePlayer2ControlPort(m_byte value) {
    SDL_LockMutex(stateMutex_);
    player2Slot_.controlPort = value;
    SDL_UnlockMutex(stateMutex_);
}

m_byte Controllers::readPlayer1DataPort() {
    SDL_LockMutex(stateMutex_);
    const bool   thHigh = (player1Slot_.dataPortOut & 0x40u) != 0;
    const m_byte result = encodeDataPort(state1_, thHigh);
    SDL_UnlockMutex(stateMutex_);
    return result;
}

m_byte Controllers::readPlayer2DataPort() {
    SDL_LockMutex(stateMutex_);
    const bool   thHigh = (player2Slot_.dataPortOut & 0x40u) != 0;
    const m_byte result = encodeDataPort(state2_, thHigh);
    SDL_UnlockMutex(stateMutex_);
    return result;
}

void Controllers::writePlayer1DataPort(m_byte value) {
    SDL_LockMutex(stateMutex_);
    player1Slot_.dataPortOut = value;
    SDL_UnlockMutex(stateMutex_);
}

void Controllers::writePlayer2DataPort(m_byte value) {
    SDL_LockMutex(stateMutex_);
    player2Slot_.dataPortOut = value;
    SDL_UnlockMutex(stateMutex_);
}

// ─── Slot building ────────────────────────────────────────────────────────────

Controllers::PlayerSlot Controllers::buildSlot(const PlayerConfiguration &cfg) {
    if (!cfg.enabled)
        return {};

    static const std::unordered_map<std::string, MdButton> kMdButtonByName = {
        {"Up", MdButton::Up},
        {"Down", MdButton::Down},
        {"Left", MdButton::Left},
        {"Right", MdButton::Right},
        {"A", MdButton::A},
        {"B", MdButton::B},
        {"C", MdButton::C},
        {"Start", MdButton::Start},
    };

    PlayerSlot slot;
    slot.device      = cfg.deviceType;
    slot.gamepadGuid = cfg.gamepadGuid;

    for (const auto &raw : cfg.bindings) {
        const auto parts = splitOnce(raw, '@');
        if (!parts) {
            SDL_Log("[Controllers] Malformed binding '%s' — missing '@'.", raw.c_str());
            continue;
        }
        const auto &[mdName, sdlName] = *parts;

        const auto mdIt = kMdButtonByName.find(mdName);
        if (mdIt == kMdButtonByName.end()) {
            SDL_Log("[Controllers] Unknown MD button '%s' in binding '%s'.", mdName.c_str(), raw.c_str());
            continue;
        }

        Binding binding{};
        binding.mdButton = mdIt->second;

        if (sdlName == "auto") {
            // "auto" maps a directional button to the left analogue stick axis.
            binding.sourceKind   = SourceKind::GamepadAxis;
            slot.hasAxisBindings = true;
        } else if (cfg.deviceType == InputDevice::Keyboard) {
            binding.sourceKind = SourceKind::Keyboard;
            binding.scancode   = SDL_GetScancodeFromName(sdlName.c_str());
            if (binding.scancode == SDL_SCANCODE_UNKNOWN) {
                SDL_Log("[Controllers] Unknown key name '%s' in binding '%s'.", sdlName.c_str(), raw.c_str());
                continue;
            }
        } else {
            binding.sourceKind = SourceKind::GamepadButton;
            binding.gpadButton = SDL_GetGamepadButtonFromString(sdlName.c_str());
            if (binding.gpadButton == SDL_GAMEPAD_BUTTON_INVALID) {
                SDL_Log("[Controllers] Unknown gamepad button '%s' in binding '%s'.", sdlName.c_str(), raw.c_str());
                continue;
            }
        }

        slot.bindings.push_back(std::move(binding));
    }

    return slot;
}

// ─── Gamepad resolution ───────────────────────────────────────────────────────

void Controllers::tryOpenGamepad(PlayerSlot &slot) {
    if (slot.device != InputDevice::Gamepad || slot.gamepadGuid.empty())
        return;

    if (slot.gamepad) {
        SDL_CloseGamepad(slot.gamepad);
        slot.gamepad   = nullptr;
        slot.gamepadId = 0;
    }

    int             count = 0;
    SDL_JoystickID *ids   = SDL_GetGamepads(&count);
    if (!ids)
        return;

    for (int i = 0; i < count; ++i) {
        const SDL_GUID    guid    = SDL_GetJoystickGUIDForID(ids[i]);
        const std::string guidStr = guidToString(guid);
        if (guidStr == slot.gamepadGuid) {
            slot.gamepadId = ids[i];
            slot.gamepad   = SDL_OpenGamepad(ids[i]);
            break;
        }
    }

    SDL_free(ids);
}

// ─── SDL event watch ──────────────────────────────────────────────────────────

bool Controllers::sdlEventFilter(void *userdata, SDL_Event *event) {
    static_cast<Controllers *>(userdata)->handleEvent(*event);
    return true; // return value is ignored for event watches
}

void Controllers::handleEvent(const SDL_Event &event) {
    PlayerControlsState newState1;
    PlayerControlsState newState2;

    PlayerControlsState oldState1;
    PlayerControlsState oldState2;

    {
        SDL_LockMutex(stateMutex_);
        oldState1 = state1_;
        oldState2 = state2_;
        newState1 = state1_;
        newState2 = state2_;

        switch (event.type) {

            case SDL_EVENT_KEY_DOWN:
            case SDL_EVENT_KEY_UP: {
                const bool pressed = (event.type == SDL_EVENT_KEY_DOWN);
                handleKeyEvent(player1Slot_, event.key.scancode, pressed, newState1);
                handleKeyEvent(player2Slot_, event.key.scancode, pressed, newState2);
                break;
            }

            case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
            case SDL_EVENT_GAMEPAD_BUTTON_UP: {
                const bool pressed = (event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN);
                const auto button  = static_cast<SDL_GamepadButton>(event.gbutton.button);
                if (player1Slot_.gamepadId == event.gbutton.which)
                    handleGamepadButtonEvent(player1Slot_, button, pressed, newState1);
                if (player2Slot_.gamepadId == event.gbutton.which)
                    handleGamepadButtonEvent(player2Slot_, button, pressed, newState2);
                break;
            }

            case SDL_EVENT_GAMEPAD_AXIS_MOTION: {
                const auto   axis = static_cast<SDL_GamepadAxis>(event.gaxis.axis);
                const Sint16 val  = event.gaxis.value;
                if (player1Slot_.gamepadId == event.gaxis.which)
                    handleGamepadAxisEvent(player1Slot_, axis, val, newState1);
                if (player2Slot_.gamepadId == event.gaxis.which)
                    handleGamepadAxisEvent(player2Slot_, axis, val, newState2);
                break;
            }

            case SDL_EVENT_GAMEPAD_ADDED: {
                // A new gamepad connected — try to match it to an unclaimed slot.
                if (!player1Slot_.gamepad)
                    tryOpenGamepad(player1Slot_);
                if (!player2Slot_.gamepad)
                    tryOpenGamepad(player2Slot_);
                // Only update connected for gamepad slots; keyboard slots are always
                // connected when enabled and must not be overwritten here.
                if (player1Slot_.device == InputDevice::Gamepad)
                    newState1.connected = (player1Slot_.gamepad != nullptr);
                if (player2Slot_.device == InputDevice::Gamepad)
                    newState2.connected = (player2Slot_.gamepad != nullptr);
                break;
            }

            case SDL_EVENT_GAMEPAD_REMOVED: {
                const SDL_JoystickID removed = event.gdevice.which;
                if (player1Slot_.gamepadId == removed) {
                    SDL_CloseGamepad(player1Slot_.gamepad);
                    player1Slot_.gamepad   = nullptr;
                    player1Slot_.gamepadId = 0;
                    newState1              = {}; // clear all buttons; connected becomes false
                }
                if (player2Slot_.gamepadId == removed) {
                    SDL_CloseGamepad(player2Slot_.gamepad);
                    player2Slot_.gamepad   = nullptr;
                    player2Slot_.gamepadId = 0;
                    newState2              = {};
                }
                break;
            }

            default:
                SDL_UnlockMutex(stateMutex_);
                return; // unrelated event — skip delegate notification
        }

        // Cancel opposite directions; this also guarantees at most 2 active directions.
        if (newState1.left && newState1.right) {
            newState1.left = newState1.right = false;
        }
        if (newState1.up && newState1.down) {
            newState1.up = newState1.down = false;
        }
        if (newState2.left && newState2.right) {
            newState2.left = newState2.right = false;
        }
        if (newState2.up && newState2.down) {
            newState2.up = newState2.down = false;
        }

        state1_ = newState1;
        state2_ = newState2;
        SDL_UnlockMutex(stateMutex_);
    }

    // Notify the delegate outside the state mutex to avoid re-entrancy issues.
    ControllersDelegate *delegate = nullptr;
    {
        SDL_LockMutex(delegateMutex_);
        delegate = delegate_;
        SDL_UnlockMutex(delegateMutex_);
    }

    if (delegate) {
        if (!statesEqual(newState1, oldState1))
            delegate->controllersStateDidUpdate(newState1);
        if (!statesEqual(newState2, oldState2))
            delegate->controllersStateDidUpdate(newState2);
    }
}

// ─── Per-event input handlers ─────────────────────────────────────────────────

void Controllers::handleKeyEvent(const PlayerSlot    &slot,
                                 SDL_Scancode         scancode,
                                 bool                 pressed,
                                 PlayerControlsState &state) {
    if (slot.device != InputDevice::Keyboard)
        return;

    for (const auto &b : slot.bindings) {
        if (b.sourceKind == SourceKind::Keyboard && b.scancode == scancode)
            setButton(state, b.mdButton, pressed);
    }
}

void Controllers::handleGamepadButtonEvent(PlayerSlot          &slot,
                                           SDL_GamepadButton    button,
                                           bool                 pressed,
                                           PlayerControlsState &state) {
    // Explicit button bindings
    for (const auto &b : slot.bindings) {
        if (b.sourceKind == SourceKind::GamepadButton && b.gpadButton == button)
            setButton(state, b.mdButton, pressed);
    }

    // Track D-pad state for "auto" (GamepadAxis) direction bindings.
    // D-pad buttons arrive as button events, not axis events, so they must be
    // handled here and combined with the analogue-stick state.
    if (!slot.hasAxisBindings)
        return;
    switch (button) {
        case SDL_GAMEPAD_BUTTON_DPAD_UP:
            slot.dpadUp = pressed;
            break;
        case SDL_GAMEPAD_BUTTON_DPAD_DOWN:
            slot.dpadDown = pressed;
            break;
        case SDL_GAMEPAD_BUTTON_DPAD_LEFT:
            slot.dpadLeft = pressed;
            break;
        case SDL_GAMEPAD_BUTTON_DPAD_RIGHT:
            slot.dpadRight = pressed;
            break;
        default:
            return;
    }
    for (const auto &b : slot.bindings) {
        if (b.sourceKind != SourceKind::GamepadAxis)
            continue;
        bool p = false;
        switch (b.mdButton) {
            case MdButton::Up:
                p = (slot.axisY < -kAxisDeadzone) || slot.dpadUp;
                break;
            case MdButton::Down:
                p = (slot.axisY > kAxisDeadzone) || slot.dpadDown;
                break;
            case MdButton::Left:
                p = (slot.axisX < -kAxisDeadzone) || slot.dpadLeft;
                break;
            case MdButton::Right:
                p = (slot.axisX > kAxisDeadzone) || slot.dpadRight;
                break;
            default:
                break;
        }
        setButton(state, b.mdButton, p);
    }
}

void Controllers::handleGamepadAxisEvent(PlayerSlot          &slot,
                                         SDL_GamepadAxis      axis,
                                         Sint16               value,
                                         PlayerControlsState &state) {
    if (!slot.hasAxisBindings)
        return;

    if (axis == SDL_GAMEPAD_AXIS_LEFTX)
        slot.axisX = value;
    if (axis == SDL_GAMEPAD_AXIS_LEFTY)
        slot.axisY = value;

    // Recompute all axis-bound directions — analogue stick OR D-pad.
    for (const auto &b : slot.bindings) {
        if (b.sourceKind != SourceKind::GamepadAxis)
            continue;
        bool pressed = false;
        switch (b.mdButton) {
            case MdButton::Up:
                pressed = (slot.axisY < -kAxisDeadzone) || slot.dpadUp;
                break;
            case MdButton::Down:
                pressed = (slot.axisY > kAxisDeadzone) || slot.dpadDown;
                break;
            case MdButton::Left:
                pressed = (slot.axisX < -kAxisDeadzone) || slot.dpadLeft;
                break;
            case MdButton::Right:
                pressed = (slot.axisX > kAxisDeadzone) || slot.dpadRight;
                break;
            default:
                break;
        }
        setButton(state, b.mdButton, pressed);
    }
}

// ─── State helpers ────────────────────────────────────────────────────────────

void Controllers::setButton(PlayerControlsState &state, MdButton button, bool pressed) {
    switch (button) {
        case MdButton::Up:
            state.up = pressed;
            break;
        case MdButton::Down:
            state.down = pressed;
            break;
        case MdButton::Left:
            state.left = pressed;
            break;
        case MdButton::Right:
            state.right = pressed;
            break;
        case MdButton::A:
            state.a = pressed;
            break;
        case MdButton::B:
            state.b = pressed;
            break;
        case MdButton::C:
            state.c = pressed;
            break;
        case MdButton::Start:
            state.start = pressed;
            break;
    }
}

// ─── MD port encoding ─────────────────────────────────────────────────────────

m_byte Controllers::encodeDataPort(const PlayerControlsState &s, bool thHigh) {
    // Start with all input bits high: active-low means 1 = released.
    // Bit 7: unused (always 0).
    // Bit 6: TH line state.
    // Bits 5:0: button inputs, active-low.
    m_byte result = 0x3Fu; // bits 5:0 high (all released)
    if (thHigh)
        result |= 0x40u;

    // Clears one bit when the corresponding button is pressed (active-low).
    const auto press = [&](bool isPressed, unsigned bit) {
        if (isPressed)
            result &= static_cast<m_byte>(~(1u << bit));
    };

    // Up and Down are available regardless of TH.
    press(s.up, 0);
    press(s.down, 1);

    if (thHigh) {
        // TH=1 → bits 5:4:3:2 map to /C, /B, /Right, /Left.
        press(s.left, 2);
        press(s.right, 3);
        press(s.b, 4);
        press(s.c, 5);
    } else {
        // TH=0 → bits 3:2 are grounded (always 0); bits 5:4 map to /Start, /A.
        result &= ~0x0Cu; // force bits 3:2 low (grounded pins)
        press(s.a, 4);
        press(s.start, 5);
    }

    return result;
}
