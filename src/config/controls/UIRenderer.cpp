#include "UIRenderer.hpp"
#include "util/font/Font.hpp"

UIRenderer::UIRenderer(SDL_Renderer *renderer) : m_renderer(renderer) {
}

UIRenderer::~UIRenderer() {
    for (auto &t : m_cache) {
        if (t) {
            SDL_DestroyTexture(t);
            t = nullptr;
        }
    }
}

// ─── private ─────────────────────────────────────────────────────────────────

SDL_Texture *UIRenderer::getCharTex(uint8_t ch) {
    if (ch < 0x20 || ch > 0x7E)
        ch = 0x20;
    if (!m_cache[ch]) {
        m_cache[ch] = Font::fontCharToTexture(m_renderer, ch, {255, 255, 255, 255}, {0, 0, 0, 0});
    }
    return m_cache[ch];
}

// ─── Text ────────────────────────────────────────────────────────────────────

void UIRenderer::drawText(int x, int y, std::string_view text, SDL_Color color, int scale) {
    const float cw = static_cast<float>(8 * scale);
    const float ch = static_cast<float>(8 * scale);
    for (size_t i = 0; i < text.size(); ++i) {
        uint8_t      ascii = static_cast<uint8_t>(text[i]);
        SDL_Texture *t     = getCharTex(ascii);
        if (!t)
            continue;
        SDL_SetTextureColorMod(t, color.r, color.g, color.b);
        SDL_SetTextureAlphaMod(t, color.a);
        SDL_FRect dst{static_cast<float>(x) + static_cast<float>(i) * cw, static_cast<float>(y), cw, ch};
        SDL_RenderTexture(m_renderer, t, nullptr, &dst);
    }
}

void UIRenderer::drawCenteredText(int cx, int y, std::string_view text, SDL_Color color, int scale) {
    int tw = textWidth(text, scale);
    drawText(cx - tw / 2, y, text, color, scale);
}

int UIRenderer::textWidth(std::string_view text, int scale) const {
    return static_cast<int>(text.size()) * 8 * scale;
}

// ─── Shapes ──────────────────────────────────────────────────────────────────

void UIRenderer::fillRect(int x, int y, int w, int h, SDL_Color color) {
    SDL_SetRenderDrawColor(m_renderer, color.r, color.g, color.b, color.a);
    SDL_SetRenderDrawBlendMode(m_renderer, color.a < 255 ? SDL_BLENDMODE_BLEND : SDL_BLENDMODE_NONE);
    SDL_FRect r{static_cast<float>(x), static_cast<float>(y), static_cast<float>(w), static_cast<float>(h)};
    SDL_RenderFillRect(m_renderer, &r);
    SDL_SetRenderDrawBlendMode(m_renderer, SDL_BLENDMODE_NONE);
}

void UIRenderer::drawRect(int x, int y, int w, int h, SDL_Color color) {
    SDL_SetRenderDrawColor(m_renderer, color.r, color.g, color.b, color.a);
    SDL_FRect r{static_cast<float>(x), static_cast<float>(y), static_cast<float>(w), static_cast<float>(h)};
    SDL_RenderRect(m_renderer, &r);
}

void UIRenderer::drawHLine(int x1, int x2, int y, SDL_Color color) {
    SDL_SetRenderDrawColor(m_renderer, color.r, color.g, color.b, color.a);
    SDL_RenderLine(
        m_renderer, static_cast<float>(x1), static_cast<float>(y), static_cast<float>(x2), static_cast<float>(y));
}

// ─── Composite widgets ───────────────────────────────────────────────────────

void UIRenderer::drawButton(int x, int y, int w, int h, std::string_view text, bool selected) {
    SDL_Color bg     = selected ? CC_COL_BTN_SEL : CC_COL_BTN_NORMAL;
    SDL_Color border = selected ? CC_COL_BORDER_SEL : CC_COL_BORDER;
    SDL_Color fg     = selected ? CC_COL_TEXT_WHITE : CC_COL_TEXT_GRAY;

    fillRect(x, y, w, h, bg);
    drawRect(x, y, w, h, border);

    int tw = textWidth(text, CC_SCALE_NORM);
    int tx = x + (w - tw) / 2;
    int ty = y + (h - CC_CHAR_H) / 2;
    drawText(tx, ty, text, fg, CC_SCALE_NORM);
}

void UIRenderer::drawCenteredButton(int y, int w, int h, std::string_view text, bool selected) {
    drawButton((CC_WIN_W - w) / 2, y, w, h, text, selected);
}

void UIRenderer::drawHintSeparator() {
    drawHLine(CC_PAD, CC_WIN_W - CC_PAD, CC_HINT_SEP_Y, CC_COL_HINT_SEP);
}

void UIRenderer::drawHint(std::string_view text) {
    drawHintSeparator();
    // Left-align hint, small scale
    drawText(CC_PAD, CC_HINT_Y, text, CC_COL_TEXT_GRAY, CC_SCALE_HINT);
}

void UIRenderer::clear() {
    SDL_Color bg = CC_COL_BG;
    SDL_SetRenderDrawColor(m_renderer, bg.r, bg.g, bg.b, bg.a);
    SDL_RenderClear(m_renderer);
}
