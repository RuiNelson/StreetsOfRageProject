#include "Font.hpp"
#include "FontData.hpp"
#include "system/memory/SystemMemory.hpp"
#include <SDL3/SDL.h>
#include <cstdlib>

FontPixelBuffer Font::fontCharToPixels(uint8_t ascii, bool withAlpha, Color foreground, Color background) {
    if (ascii < 0x20 || ascii > 0x7E) {
        ascii = 0x20;
    }

    constexpr int W             = 8;
    constexpr int H             = 8;
    int           bytesPerPixel = withAlpha ? 4 : 3;
    size_t        size          = W * H * bytesPerPixel;

    uint8_t *data = static_cast<uint8_t *>(malloc(size));
    if (!data) {
        return {nullptr, 0, 0, 0};
    }

    const auto &glyph = font8x8_basic[ascii - 0x20];

    for (int row = 0; row < H; ++row) {
        uint8_t bits = glyph[row];
        for (int col = 0; col < W; ++col) {
            uint8_t bit   = (bits >> col) & 1;
            Color   c     = bit ? foreground : background;
            size_t  idx   = (row * W + col) * bytesPerPixel;
            data[idx + 0] = c.r;
            data[idx + 1] = c.g;
            data[idx + 2] = c.b;
            if (withAlpha) {
                data[idx + 3] = c.a;
            }
        }
    }

    return {data, size, W, H};
}

SDL_Texture *Font::fontCharToTexture(SDL_Renderer *renderer, uint8_t ascii, Color foreground, Color background) {
    if (ascii < 0x20 || ascii > 0x7E) {
        ascii = 0x20;
    }

    SDL_Texture *tex = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA8888, SDL_TEXTUREACCESS_STATIC, 8, 8);
    if (!tex) {
        return nullptr;
    }

    uint32_t    pixels[8 * 8];
    const auto &glyph = font8x8_basic[ascii - 0x20];

    for (int row = 0; row < 8; ++row) {
        uint8_t bits = static_cast<uint8_t>(glyph[row]);
        for (int col = 0; col < 8; ++col) {
            uint8_t bit           = (bits >> col) & 1;
            Color   c             = bit ? foreground : background;
            pixels[row * 8 + col] = (c.a << 24) | (c.b << 16) | (c.g << 8) | c.r;
        }
    }

    SDL_UpdateTexture(tex, nullptr, pixels, 8 * sizeof(uint32_t));
    SDL_SetTextureBlendMode(tex, SDL_BLENDMODE_BLEND);
    SDL_SetTextureScaleMode(tex, SDL_SCALEMODE_NEAREST);
    return tex;
}

void Font::fontCharToVDPTile(
    SystemMemory &memory, uint8_t ascii, uint8_t fgIndex, uint8_t bgIndex, uint32_t ramAddress) {
    if (ascii < 0x20 || ascii > 0x7E) {
        ascii = 0x20;
    }
    fgIndex &= 0x0F;
    bgIndex &= 0x0F;

    const auto &glyph = font8x8_basic[ascii - 0x20];

    for (int row = 0; row < 8; ++row) {
        uint8_t bits = glyph[row];
        for (int col = 0; col < 8; col += 2) {
            uint8_t left  = ((bits >> col) & 1) ? fgIndex : bgIndex;
            uint8_t right = ((bits >> (col + 1)) & 1) ? fgIndex : bgIndex;
            memory.writeByte(ramAddress + row * 4 + col / 2, static_cast<uint8_t>((left << 4) | right));
        }
    }
}