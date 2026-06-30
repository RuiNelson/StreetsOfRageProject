#pragma once

#include "ControlsConfig.hpp"
#include <SDL3/SDL.h>
#include <string_view>

/// @brief SDL3 drawing utility for the controls configuration UI.
///
/// Provides text rendering, shape primitives, and composite widgets.
/// Maintains a texture cache for ASCII characters (0x20–0x7E) rendered as
/// white-on-transparent from the font bitmap. Colour is applied at render time
/// via SDL texture colour modulation.
/// @note Owns SDL resources; not copyable.
class UIRenderer {
    public:
    /// @brief Construct the renderer wrapper.
    /// @param renderer Pointer to an SDL_Renderer created by the caller.
    ///                 Must remain valid for the lifetime of this UIRenderer.
    explicit UIRenderer(SDL_Renderer *renderer);

    /// @brief Destructor: cleans up cached character textures.
    ~UIRenderer();

    // Prevent copying — owns SDL texture resources
    /// @cond
    UIRenderer(const UIRenderer &)            = delete;
    UIRenderer &operator=(const UIRenderer &) = delete;
    /// @endcond

    // ── Text rendering ───────────────────────────────────────────────────────
    /// @brief Draw left-aligned text at a position.
    /// @param x Pixel x-coordinate of text start.
    /// @param y Pixel y-coordinate of text baseline.
    /// @param text String to render.
    /// @param color Text colour (RGBA).
    /// @param scale Scaling factor: 1 = 8×8 px/char, 2 = 16×16 px/char.
    ///              Default is CC_SCALE_NORM (usually 2).
    void drawText(int x, int y, std::string_view text, SDL_Color color, int scale = CC_SCALE_NORM);

    /// @brief Draw horizontally-centred text.
    /// @param cx Pixel x-coordinate of text centre.
    /// @param y Pixel y-coordinate of text baseline.
    /// @param text String to render.
    /// @param color Text colour (RGBA).
    /// @param scale Scaling factor (see drawText()).
    void drawCenteredText(int cx, int y, std::string_view text, SDL_Color color, int scale = CC_SCALE_NORM);

    /// @brief Calculate the pixel width of a string.
    /// @param text String to measure.
    /// @param scale Scaling factor (see drawText()).
    /// @return Width in pixels at the given scale.
    int textWidth(std::string_view text, int scale = CC_SCALE_NORM) const;

    // ── Shape primitives ─────────────────────────────────────────────────────
    /// @brief Draw a filled rectangle.
    /// @param x Left edge in pixels.
    /// @param y Top edge in pixels.
    /// @param w Width in pixels.
    /// @param h Height in pixels.
    /// @param color Fill colour (RGBA); blend mode set based on alpha.
    void fillRect(int x, int y, int w, int h, SDL_Color color);

    /// @brief Draw a rectangle outline.
    /// @param x Left edge in pixels.
    /// @param y Top edge in pixels.
    /// @param w Width in pixels.
    /// @param h Height in pixels.
    /// @param color Border colour (RGBA).
    void drawRect(int x, int y, int w, int h, SDL_Color color);

    /// @brief Draw a horizontal line.
    /// @param x1 Left x-coordinate.
    /// @param x2 Right x-coordinate.
    /// @param y Y-coordinate (vertical position).
    /// @param color Line colour (RGBA).
    void drawHLine(int x1, int x2, int y, SDL_Color color);

    // ── Composite widgets ────────────────────────────────────────────────────
    /// @brief Draw an interactive button.
    /// @param x Left edge in pixels.
    /// @param y Top edge in pixels.
    /// @param w Width in pixels.
    /// @param h Height in pixels.
    /// @param text Label text (centred within button).
    /// @param selected If true, renders with highlight colours; else normal colours.
    /// @note Background, border, and text colours vary based on selection state.
    void drawButton(int x, int y, int w, int h, std::string_view text, bool selected);

    /// @brief Draw a horizontally-centred button.
    /// @param y Top edge in pixels.
    /// @param w Width in pixels.
    /// @param h Height in pixels.
    /// @param text Label text.
    /// @param selected Selection state (see drawButton()).
    /// @note Button is centred on screen width (CC_WIN_W).
    void drawCenteredButton(int y, int w, int h, std::string_view text, bool selected);

    /// @brief Draw the separator line above the hint area.
    /// @note Drawn from left to right edge, excluding padding.
    void drawHintSeparator();

    /// @brief Draw hint text at the bottom of the screen.
    /// @param text Hint message (left-aligned, small scale).
    /// @note Calls drawHintSeparator() first.
    void drawHint(std::string_view text);

    /// @brief Clear the screen to background colour.
    void clear();

    /// @brief Get the underlying SDL_Renderer pointer.
    /// @return Pointer to SDL_Renderer (for direct SDL calls if needed).
    SDL_Renderer *renderer() const {
        return m_renderer;
    }

    private:
    SDL_Renderer *m_renderer;     ///< Pointer to SDL renderer (owned by caller)
    SDL_Texture  *m_cache[128]{}; ///< Character texture cache (ASCII 0x20–0x7E)

    /// @brief Get or create a cached texture for a character.
    /// @param ch Character code (0–255; out-of-range maps to space).
    /// @return Pointer to SDL_Texture, or nullptr if creation failed.
    /// @note Lazily creates and caches texture on first use.
    SDL_Texture *getCharTex(uint8_t ch);
};
