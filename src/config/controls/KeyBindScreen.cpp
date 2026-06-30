#include "KeyBindScreen.hpp"
#include <cstring>

// ─── Construction / lifecycle ─────────────────────────────────────────────────

KeyBindScreen::KeyBindScreen(int playerNum, PlayerConfig &config) : m_playerNum(playerNum), m_config(config) {
}

KeyBindScreen::~KeyBindScreen() {
    closeGamepad();
}

void KeyBindScreen::openGamepad() {
    closeGamepad();
    if (m_temp.deviceType == DeviceType::Gamepad && m_temp.gamepadId != 0) {
        m_gamepad = SDL_OpenGamepad(m_temp.gamepadId);
    }
}

void KeyBindScreen::closeGamepad() {
    if (m_gamepad) {
        SDL_CloseGamepad(m_gamepad);
        m_gamepad = nullptr;
    }
}

// ─── Setup ───────────────────────────────────────────────────────────────────

void KeyBindScreen::buildButtonList() {
    m_buttons.clear();
    if (m_temp.deviceType == DeviceType::Keyboard) {
        m_buttons = {MDButton::Up,
                     MDButton::Down,
                     MDButton::Left,
                     MDButton::Right,
                     MDButton::A,
                     MDButton::B,
                     MDButton::C,
                     MDButton::Start};
    } else {
        // Directions auto-assigned; only ask for face buttons
        m_buttons = {MDButton::A, MDButton::B, MDButton::C, MDButton::Start};
    }
}

void KeyBindScreen::applyAutoDirections() {
    if (m_temp.deviceType != DeviceType::Gamepad)
        return;
    for (MDButton dir : {MDButton::Up, MDButton::Down, MDButton::Left, MDButton::Right}) {
        m_temp.bindings[int(dir)].isAutoDir = true;
        m_temp.bindings[int(dir)].gpButton  = SDL_GAMEPAD_BUTTON_INVALID;
        m_temp.bindings[int(dir)].key       = SDLK_UNKNOWN;
    }
}

void KeyBindScreen::reset() {
    m_done      = false;
    m_cancelled = false;
    m_phase     = Phase::Binding;
    m_bindIdx   = 0;
    m_temp      = m_config;
    buildButtonList();
    applyAutoDirections();
    openGamepad();
}

void KeyBindScreen::resetToTest() {
    m_done      = false;
    m_cancelled = false;
    m_phase     = Phase::Testing;
    m_bindIdx   = 0;
    m_temp      = m_config;
    buildButtonList();
    openGamepad();
}

// ─── Flow control ────────────────────────────────────────────────────────────

void KeyBindScreen::advance() {
    ++m_bindIdx;
    if (m_bindIdx >= (int)m_buttons.size()) {
        m_phase   = Phase::Testing;
        m_bindIdx = 0;
    }
}

void KeyBindScreen::cancelOut() {
    m_cancelled = true;
    m_done      = true;
    closeGamepad();
}

void KeyBindScreen::saveAndExit() {
    m_config    = m_temp;
    m_cancelled = false;
    m_done      = true;
    closeGamepad();
}

// ─── Input ───────────────────────────────────────────────────────────────────

void KeyBindScreen::handleEvent(const SDL_Event &e) {
    // ── Esc always cancels ────────────────────────────────────────────────────
    if (e.type == SDL_EVENT_KEY_DOWN && e.key.key == SDLK_ESCAPE) {
        cancelOut();
        return;
    }

    if (m_phase == Phase::Binding) {
        // In binding phase, gamepad Back also cancels
        if (e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN && e.gbutton.button == SDL_GAMEPAD_BUTTON_BACK) {
            cancelOut();
            return;
        }

        MDButton target = m_buttons[m_bindIdx];

        if (m_temp.deviceType == DeviceType::Keyboard) {
            if (e.type == SDL_EVENT_KEY_DOWN) {
                m_temp.bindings[int(target)].key       = e.key.key;
                m_temp.bindings[int(target)].isAutoDir = false;
                advance();
            }
        } else {
            if (e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
                if (e.gbutton.button == SDL_GAMEPAD_BUTTON_BACK)
                    return; // already handled above
                m_temp.bindings[int(target)].gpButton  = static_cast<SDL_GamepadButton>(e.gbutton.button);
                m_temp.bindings[int(target)].isAutoDir = false;
                advance();
            }
        }
    } else {
        // Testing phase: Enter, East, or Back all save
        if (e.type == SDL_EVENT_KEY_DOWN) {
            if (e.key.key == SDLK_RETURN || e.key.key == SDLK_KP_ENTER)
                saveAndExit();
        }
        if (e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
            if (e.gbutton.button == SDL_GAMEPAD_BUTTON_BACK)
                saveAndExit();
        }
    }
}

// ─── isPressed (for tester) ──────────────────────────────────────────────────

bool KeyBindScreen::isPressed(MDButton btn) const {
    const DeviceBinding &b = m_temp.bindings[int(btn)];

    if (m_temp.deviceType == DeviceType::Keyboard) {
        if (b.key == SDLK_UNKNOWN)
            return false;
        const bool  *ks = SDL_GetKeyboardState(nullptr);
        SDL_Scancode sc = SDL_GetScancodeFromKey(b.key, nullptr);
        return sc != SDL_SCANCODE_UNKNOWN && ks[sc];
    }

    // Gamepad
    if (b.isAutoDir) {
        if (!m_gamepad)
            return false;
        switch (btn) {
            case MDButton::Up:
                return SDL_GetGamepadButton(m_gamepad, SDL_GAMEPAD_BUTTON_DPAD_UP) ||
                       SDL_GetGamepadAxis(m_gamepad, SDL_GAMEPAD_AXIS_LEFTY) < -8000;
            case MDButton::Down:
                return SDL_GetGamepadButton(m_gamepad, SDL_GAMEPAD_BUTTON_DPAD_DOWN) ||
                       SDL_GetGamepadAxis(m_gamepad, SDL_GAMEPAD_AXIS_LEFTY) > 8000;
            case MDButton::Left:
                return SDL_GetGamepadButton(m_gamepad, SDL_GAMEPAD_BUTTON_DPAD_LEFT) ||
                       SDL_GetGamepadAxis(m_gamepad, SDL_GAMEPAD_AXIS_LEFTX) < -8000;
            case MDButton::Right:
                return SDL_GetGamepadButton(m_gamepad, SDL_GAMEPAD_BUTTON_DPAD_RIGHT) ||
                       SDL_GetGamepadAxis(m_gamepad, SDL_GAMEPAD_AXIS_LEFTX) > 8000;
            default:
                return false;
        }
    }

    if (b.gpButton == SDL_GAMEPAD_BUTTON_INVALID || !m_gamepad)
        return false;
    return SDL_GetGamepadButton(m_gamepad, b.gpButton) != 0;
}

// ─── Tester layout ───────────────────────────────────────────────────────────

std::vector<KeyBindScreen::BoxInfo> KeyBindScreen::buildTesterLayout() const {
    // Box size  (min 88px so "RIGHT" and "START" fit at 2× scale)
    constexpr int BW = 88; // box width
    constexpr int BH = 28; // box height
    constexpr int GX = 8;  // horizontal gap
    constexpr int GY = 10; // vertical gap

    // Direction cross centre
    constexpr int CX = CC_WIN_W / 2;
    constexpr int CY = 200;

    // Face buttons row y
    constexpr int BY = CY + BH + GY + 20;

    std::vector<BoxInfo> boxes;

    // Directions
    boxes.push_back({CX - BW / 2, CY - BH - GY, BW, BH, MDButton::Up, "UP"});
    boxes.push_back({CX - BW / 2, CY, BW, BH, MDButton::Down, "DOWN"});
    boxes.push_back({CX - BW - GX - BW / 2, CY, BW, BH, MDButton::Left, "LEFT"});
    boxes.push_back({CX + BW / 2 + GX, CY, BW, BH, MDButton::Right, "RIGHT"});

    // Face buttons — 4 in a row
    constexpr int faceW     = 4 * BW + 3 * GX;
    int           faceStart = (CC_WIN_W - faceW) / 2;
    boxes.push_back({faceStart + 0 * (BW + GX), BY, BW, BH, MDButton::A, "A"});
    boxes.push_back({faceStart + 1 * (BW + GX), BY, BW, BH, MDButton::B, "B"});
    boxes.push_back({faceStart + 2 * (BW + GX), BY, BW, BH, MDButton::C, "C"});
    boxes.push_back({faceStart + 3 * (BW + GX), BY, BW, BH, MDButton::Start, "START"});

    return boxes;
}

// ─── Render ──────────────────────────────────────────────────────────────────

void KeyBindScreen::renderBinding(UIRenderer &ui) {
    // Title
    std::string title = "Player ";
    title += std::to_string(m_playerNum);
    title += " - Bind ";
    title += (m_temp.deviceType == DeviceType::Keyboard ? "Keys" : "Buttons");
    ui.drawCenteredText(CC_WIN_W / 2, 20, title, CC_COL_TEXT_YELLOW);

    // Progress
    std::string progress = std::to_string(m_bindIdx + 1) + " / " + std::to_string((int)m_buttons.size());
    ui.drawCenteredText(CC_WIN_W / 2, 55, progress, CC_COL_TEXT_GRAY);

    // Prompt
    MDButton    target = m_buttons[m_bindIdx];
    std::string prompt = "Press ";
    if (m_temp.deviceType == DeviceType::Keyboard)
        prompt += "key";
    else
        prompt += "button";
    prompt += " for:";
    ui.drawCenteredText(CC_WIN_W / 2, CC_WIN_H / 2 - CC_CHAR_H * 3, prompt, CC_COL_TEXT_WHITE);

    // Button name — large, centred
    std::string btnName = mdButtonName(target);
    ui.drawCenteredText(CC_WIN_W / 2, CC_WIN_H / 2 - CC_CHAR_H / 2, btnName, CC_COL_TEXT_YELLOW);

    // Already-bound buttons (small list above bottom)
    if (m_bindIdx > 0) {
        int listY = CC_WIN_H / 2 + CC_CHAR_H * 2;
        ui.drawCenteredText(CC_WIN_W / 2, listY, "Bound so far:", CC_COL_TEXT_GRAY);
        listY += CC_CHAR_H + 4;
        for (int i = 0; i < m_bindIdx && i < 8; ++i) {
            MDButton    b    = m_buttons[i];
            std::string line = std::string(mdButtonName(b)) + ": ";
            const auto &bd   = m_temp.bindings[int(b)];
            if (m_temp.deviceType == DeviceType::Keyboard) {
                const char *kn = SDL_GetKeyName(bd.key);
                line += kn ? kn : "?";
            } else {
                const char *gn = SDL_GetGamepadStringForButton(bd.gpButton);
                line += gn ? gn : "?";
            }
            ui.drawCenteredText(CC_WIN_W / 2, listY + i * (CC_HINT_CH_H + 2), line, CC_COL_TEXT_GRAY, CC_SCALE_HINT);
        }
    }

    if (m_temp.deviceType == DeviceType::Keyboard)
        ui.drawHint("Press a key to bind  |  Esc: Cancel (discard)");
    else
        ui.drawHint("Press a button to bind  |  Gamepad Back: Cancel (discard)");
}

void KeyBindScreen::renderTester(UIRenderer &ui) {
    // Title
    std::string title = "Player ";
    title += std::to_string(m_playerNum);
    title += " - Button Tester";
    ui.drawCenteredText(CC_WIN_W / 2, 20, title, CC_COL_TEXT_YELLOW);

    ui.drawCenteredText(CC_WIN_W / 2, 50, "Test your bindings", CC_COL_TEXT_GRAY);

    // Exit instructions — normal scale, visible in content area
    ui.drawCenteredText(
        CC_WIN_W / 2, CC_HINT_SEP_Y - CC_CHAR_H - 8, "Enter / Back: Save    Esc: Cancel", CC_COL_TEXT_GRAY);

    auto gameFunction = [](MDButton btn) -> const char * {
        switch (btn) {
            case MDButton::A:
                return "Special";
            case MDButton::B:
                return "Attack";
            case MDButton::C:
                return "Jump";
            default:
                return nullptr;
        }
    };

    auto boxes = buildTesterLayout();
    for (auto &box : boxes) {
        bool      pressed = isPressed(box.btn);
        SDL_Color fg      = pressed ? CC_COL_TEXT_RED : CC_COL_TEXT_YELLOW;
        SDL_Color border  = pressed ? CC_COL_TEXT_RED : CC_COL_BORDER;
        SDL_Color bg      = pressed ? (SDL_Color{50, 0, 0, 255}) : CC_COL_BTN_NORMAL;

        ui.fillRect(box.x, box.y, box.w, box.h, bg);
        ui.drawRect(box.x, box.y, box.w, box.h, border);

        int tw = ui.textWidth(box.label);
        int tx = box.x + (box.w - tw) / 2;
        int ty = box.y + (box.h - CC_CHAR_H) / 2;
        ui.drawText(tx, ty, box.label, fg);

        // Game function label below the box (small scale)
        const char *fn = gameFunction(box.btn);
        if (fn) {
            int fw = ui.textWidth(fn, CC_SCALE_HINT);
            int fx = box.x + (box.w - fw) / 2;
            ui.drawText(fx, box.y + box.h + 4, fn, CC_COL_TEXT_GRAY, CC_SCALE_HINT);
        }
    }

    ui.drawHint("Enter/Back: Save & exit  |  Esc: Cancel (discard)");
}

void KeyBindScreen::render(UIRenderer &ui) {
    ui.clear();
    if (m_phase == Phase::Binding)
        renderBinding(ui);
    else
        renderTester(ui);
}
