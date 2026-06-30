#include "MainMenuScreen.hpp"

static constexpr int kItemCount = 3;

static const char *kLabels[kItemCount] = {"Player 1", "Player 2", "Exit"};

MainMenuScreen::MainMenuScreen() {
}

void MainMenuScreen::reset() {
    m_done   = false;
    m_sel    = 0;
    m_result = MainMenuResult::Exit;
}

// ─── Input ───────────────────────────────────────────────────────────────────

void MainMenuScreen::navigate(int delta) {
    m_sel = (m_sel + delta + kItemCount) % kItemCount;
}

void MainMenuScreen::confirm() {
    switch (m_sel) {
        case 0:
            m_result = MainMenuResult::Player1;
            break;
        case 1:
            m_result = MainMenuResult::Player2;
            break;
        default:
            m_result = MainMenuResult::Exit;
            break;
    }
    m_done = true;
}

void MainMenuScreen::handleEvent(const SDL_Event &e) {
    if (e.type == SDL_EVENT_KEY_DOWN) {
        switch (e.key.key) {
            case SDLK_UP:
                navigate(-1);
                break;
            case SDLK_DOWN:
                navigate(+1);
                break;
            case SDLK_RETURN:
            case SDLK_KP_ENTER:
                confirm();
                break;
            case SDLK_ESCAPE:
            case SDLK_BACKSPACE:
                m_result = MainMenuResult::Exit;
                m_done   = true;
                break;
            default:
                break;
        }
    }
    if (e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
        switch (e.gbutton.button) {
            case SDL_GAMEPAD_BUTTON_DPAD_UP:
                navigate(-1);
                break;
            case SDL_GAMEPAD_BUTTON_DPAD_DOWN:
                navigate(+1);
                break;
            case SDL_GAMEPAD_BUTTON_EAST:
                confirm();
                break;
            case SDL_GAMEPAD_BUTTON_SOUTH:
            case SDL_GAMEPAD_BUTTON_BACK:
                m_result = MainMenuResult::Exit;
                m_done   = true;
                break;
            default:
                break;
        }
    }
}

// ─── Render ──────────────────────────────────────────────────────────────────

void MainMenuScreen::render(UIRenderer &ui) {
    ui.clear();

    // Title
    ui.drawCenteredText(CC_WIN_W / 2, 30, "Controls Configuration", CC_COL_TEXT_YELLOW);

    // Buttons — centred vertically in the content area
    constexpr int spacing = CC_BTN_H + 16;
    const int     totalH  = kItemCount * CC_BTN_H + (kItemCount - 1) * 16;
    int           startY  = (CC_HINT_SEP_Y - totalH) / 2 - CC_BTN_H / 2;

    for (int i = 0; i < kItemCount; ++i) {
        ui.drawCenteredButton(startY + i * spacing, CC_BTN_W_MAIN, CC_BTN_H, kLabels[i], m_sel == i);
    }

    ui.drawHint("Up/Down:Navigate  Enter/East:Select  Esc/Bksp:Exit");
}
