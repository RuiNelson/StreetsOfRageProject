/**
 * @file TestFontPNG.cpp
 * @brief Runtime test — renders a 640×480 PNG with artistic font effects.
 */

#include "runtime_tests/TestFontPNG.hpp"
#include "util/font/Font.hpp"
#include <cmath>
#include <cstdlib>
#include <ctime>
#include <png.h>

// ─── helpers ────────────────────────────────────────────────────────────────

static void writePng(const char *filename, int width, int height, const uint8_t *rgba) {
    FILE *f = fopen(filename, "wb");
    if (!f)
        return;

    png_structp png  = png_create_write_struct(PNG_LIBPNG_VER_STRING, nullptr, nullptr, nullptr);
    png_infop   info = png_create_info_struct(png);
    if (setjmp(png_jmpbuf(png))) {
        fclose(f);
        return;
    }

    png_init_io(png, f);
    png_set_IHDR(png,
                 info,
                 width,
                 height,
                 8,
                 PNG_COLOR_TYPE_RGB_ALPHA,
                 PNG_INTERLACE_NONE,
                 PNG_COMPRESSION_TYPE_DEFAULT,
                 PNG_FILTER_TYPE_DEFAULT);
    png_write_info(png, info);

    // PNG is RGB — convert from RGBA by stripping alpha channel
    for (int y = 0; y < height; ++y) {
        png_bytep row = static_cast<png_bytep>(png_malloc(png, width * 4));
        for (int x = 0; x < width; ++x) {
            row[x * 4 + 0] = rgba[(y * width + x) * 4 + 0];
            row[x * 4 + 1] = rgba[(y * width + x) * 4 + 1];
            row[x * 4 + 2] = rgba[(y * width + x) * 4 + 2];
            row[x * 4 + 3] = rgba[(y * width + x) * 4 + 3];
        }
        png_write_row(png, row);
        png_free(png, row);
    }

    png_write_end(png, info);
    fclose(f);
    png_destroy_write_struct(&png, &info);
}

/** Draws one 8×8 glyph into a RGBA buffer at (ox, oy). */
static void
drawGlyph(uint8_t *buf, int bufW, int bufH, int ox, int oy, uint8_t ascii, uint8_t r, uint8_t g, uint8_t b, uint8_t a) {
    FontPixelBuffer fb = Font::fontCharToPixels(ascii, true, {r, g, b, a}, {0, 0, 0, 0});
    if (!fb.data)
        return;

    for (int dy = 0; dy < 8 && (oy + dy) < bufH; ++dy) {
        for (int dx = 0; dx < 8 && (ox + dx) < bufW; ++dx) {
            int     srcIdx = (dy * 8 + dx) * 4;
            int     dstIdx = ((oy + dy) * bufW + (ox + dx)) * 4;
            uint8_t sa     = fb.data[srcIdx + 3];
            if (sa == 0)
                continue;
            float t         = sa / 255.f;
            buf[dstIdx + 0] = static_cast<uint8_t>(fb.data[srcIdx + 0] * t);
            buf[dstIdx + 1] = static_cast<uint8_t>(fb.data[srcIdx + 1] * t);
            buf[dstIdx + 2] = static_cast<uint8_t>(fb.data[srcIdx + 2] * t);
            buf[dstIdx + 3] = 255;
        }
    }

    free(fb.data);
}

/** Horizontal gradient across the full 640px. */
static void
horizGradient(uint8_t *buf, int w, int h, uint8_t r0, uint8_t g0, uint8_t b0, uint8_t r1, uint8_t g1, uint8_t b1) {
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            float t      = x / static_cast<float>(w - 1);
            int   idx    = (y * w + x) * 4;
            buf[idx + 0] = static_cast<uint8_t>(r0 + (r1 - r0) * t);
            buf[idx + 1] = static_cast<uint8_t>(g0 + (g1 - g0) * t);
            buf[idx + 2] = static_cast<uint8_t>(b0 + (b1 - b0) * t);
            buf[idx + 3] = 255;
        }
    }
}

// ─── entry point ────────────────────────────────────────────────────────────

void testFontPNG() {
    constexpr int    W         = 640;
    constexpr int    H         = 480;
    constexpr size_t RGBA_SIZE = W * H * 4;

    uint8_t *buf = static_cast<uint8_t *>(malloc(RGBA_SIZE));
    if (!buf)
        return;

    // ── background: deep violet-to-cyan gradient ─────────────────────────────
    horizGradient(buf, W, H, 20, 5, 45, 5, 30, 50);

    // ── decorative grid lines ─────────────────────────────────────────────────
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            bool line = (y % 32 == 0) || (x % 32 == 0);
            if (line) {
                int idx      = (y * W + x) * 4;
                buf[idx + 0] = static_cast<uint8_t>(buf[idx + 0] * 0.5f);
                buf[idx + 1] = static_cast<uint8_t>(buf[idx + 1] * 0.5f);
                buf[idx + 2] = static_cast<uint8_t>(buf[idx + 2] * 0.5f);
            }
        }
    }

    // ── all printable chars 0x20–0x7E in a grid ──────────────────────────────
    int px = 20, py = 20;
    for (uint8_t ch = 0x20; ch <= 0x7E; ++ch) {
        int r = 100 + (ch * 37) % 155;
        int g = 100 + (ch * 73) % 155;
        int b = 100 + (ch * 97) % 155;
        drawGlyph(
            buf, W, H, px, py, ch, static_cast<uint8_t>(r), static_cast<uint8_t>(g), static_cast<uint8_t>(b), 255);
        px += 24;
        if (px + 8 > W) {
            px = 20;
            py += 24;
        }
    }

    // ── Hello World — large, centered, with colour cycle ──────────────────────
    const char *hw    = "Hello World";
    const int   scale = 5;
    int         hwW   = 11 * 8 * scale;
    int         hwX   = (W - hwW) / 2;
    int         hwY   = (H - 8 * scale) / 2;

    for (int i = 0; hw[i]; ++i) {
        uint8_t ch = static_cast<uint8_t>(hw[i]);
        // Hue rotation across the string
        float   hue = (i * 360.f / 11.f);
        float   rad = hue * 3.14159f / 180.f;
        uint8_t r   = static_cast<uint8_t>(128.f + 127.f * sinf(rad));
        uint8_t g   = static_cast<uint8_t>(128.f + 127.f * sinf(rad + 2.094f));
        uint8_t b   = static_cast<uint8_t>(128.f + 127.f * sinf(rad + 4.188f));

        // Draw glyph scaled with a shadow
        int gx = hwX + i * 8 * scale;
        int gy = hwY;

        // Shadow pass
        for (int dy = 0; dy < 8 * scale; ++dy) {
            for (int dx = 0; dx < 8 * scale; ++dx) {
                int sx = gx + dx + 3;
                int sy = gy + dy + 3;
                if (sx < 0 || sx >= W || sy < 0 || sy >= H)
                    continue;
                FontPixelBuffer fb = Font::fontCharToPixels(ch, true, {0, 0, 0, 128}, {0, 0, 0, 0});
                if (!fb.data)
                    continue;
                int     srcX   = dx / scale;
                int     srcY   = dy / scale;
                int     srcIdx = (srcY * 8 + srcX) * 4;
                uint8_t sa     = fb.data[srcIdx + 3];
                if (sa == 0) {
                    free(fb.data);
                    continue;
                }
                int dstIdx      = (sy * W + sx) * 4;
                buf[dstIdx + 0] = 0;
                buf[dstIdx + 1] = 0;
                buf[dstIdx + 2] = 0;
                buf[dstIdx + 3] = 180;
                free(fb.data);
            }
        }

        // Foreground pass
        for (int dy = 0; dy < 8 * scale; ++dy) {
            for (int dx = 0; dx < 8 * scale; ++dx) {
                int sx = gx + dx;
                int sy = gy + dy;
                if (sx < 0 || sx >= W || sy < 0 || sy >= H)
                    continue;
                FontPixelBuffer fb = Font::fontCharToPixels(ch, true, {r, g, b, 255}, {0, 0, 0, 0});
                if (!fb.data)
                    continue;
                int     srcX   = dx / scale;
                int     srcY   = dy / scale;
                int     srcIdx = (srcY * 8 + srcX) * 4;
                uint8_t sa     = fb.data[srcIdx + 3];
                if (sa == 0) {
                    free(fb.data);
                    continue;
                }
                int dstIdx      = (sy * W + sx) * 4;
                buf[dstIdx + 0] = fb.data[srcIdx + 0];
                buf[dstIdx + 1] = fb.data[srcIdx + 1];
                buf[dstIdx + 2] = fb.data[srcIdx + 2];
                buf[dstIdx + 3] = 255;
                free(fb.data);
            }
        }
    }

    // ── subtitle text ─────────────────────────────────────────────────────────
    const char *sub  = "8x8 bitmap font  |  libpng output  |  SoR Recompiled";
    int         subX = (W - 11 * 8 * 2) / 2;
    int         subY = hwY + 8 * scale + 16;
    for (int i = 0; sub[i]; ++i) {
        uint8_t ch = static_cast<uint8_t>(sub[i]);
        drawGlyph(buf, W, H, subX + i * 16, subY, ch, 200, 200, 200, 180);
    }

    // ── file name: UNIX_TIMESTAMP.png ─────────────────────────────────────────
    char filename[256];
    snprintf(filename, sizeof(filename), "%lu.png", static_cast<unsigned long>(time(nullptr)));

    writePng(filename, W, H, buf);
    printf("[testFontPNG] wrote %s (%dx%d)\n", filename, W, H);

    free(buf);
}