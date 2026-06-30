/**
 * @file TestFontSDL.cpp
 * @brief Runtime test — font rendering and 3D cube.
 *
 * @see TestFontSDL.hpp for the full specification.
 */

#include "runtime_tests/TestFontSDL.hpp"
#include "util/font/Font.hpp"
#include <algorithm>
#include <cmath>
#include <cstdlib>

// ─── math primitives ─────────────────────────────────────────────────────────

struct Vec3 {
    float x, y, z;
};

struct Face {
    Vec3    verts[4];      // CCW when viewed from outside the cube
    uint8_t ascii;         // character displayed on this face
    uint8_t bgR, bgG, bgB; // face background colour
    uint8_t glR, glG, glB; // glyph colour
};

// ─── module-level state ─────────────────────────────────────────────────────

static SDL_Window   *g_win  = nullptr;
static SDL_Renderer *g_rend = nullptr;
static bool          g_quit = false;

// ─── cube geometry ───────────────────────────────────────────────────────────

static constexpr float H  = 100.f;    // half-size → 200×200×200 cube
static constexpr float GS = H * 0.6f; // glyph half-size in world units (120px)

static uint8_t rndChannel() {
    return static_cast<uint8_t>(rand() % 200 + 55);
}

static void initCube(Face faces[6], uint32_t seed) {
    srand(seed);

    // Front (+Z)
    faces[0].verts[0] = {-H, -H, H};
    faces[0].verts[1] = {H, -H, H};
    faces[0].verts[2] = {H, H, H};
    faces[0].verts[3] = {-H, H, H};
    // Back (-Z)
    faces[1].verts[0] = {H, -H, -H};
    faces[1].verts[1] = {-H, -H, -H};
    faces[1].verts[2] = {-H, H, -H};
    faces[1].verts[3] = {H, H, -H};
    // Top (+Y)
    faces[2].verts[0] = {-H, H, H};
    faces[2].verts[1] = {H, H, H};
    faces[2].verts[2] = {H, H, -H};
    faces[2].verts[3] = {-H, H, -H};
    // Bottom (-Y)
    faces[3].verts[0] = {-H, -H, -H};
    faces[3].verts[1] = {H, -H, -H};
    faces[3].verts[2] = {H, -H, H};
    faces[3].verts[3] = {-H, -H, H};
    // Right (+X)
    faces[4].verts[0] = {H, -H, H};
    faces[4].verts[1] = {H, -H, -H};
    faces[4].verts[2] = {H, H, -H};
    faces[4].verts[3] = {H, H, H};
    // Left (-X)
    faces[5].verts[0] = {-H, -H, -H};
    faces[5].verts[1] = {-H, -H, H};
    faces[5].verts[2] = {-H, H, H};
    faces[5].verts[3] = {-H, H, -H};

    for (int i = 0; i < 6; ++i) {
        faces[i].ascii = static_cast<uint8_t>(rand() % 95 + 0x20);
        faces[i].bgR   = rndChannel();
        faces[i].bgG   = rndChannel();
        faces[i].bgB   = rndChannel();
        faces[i].glR   = rndChannel();
        faces[i].glG   = rndChannel();
        faces[i].glB   = rndChannel();
    }
}

/** Re-randomises glyph characters and glyph colours; background colours unchanged. */
static void randomizeGlyphs(Face faces[6], uint32_t seed) {
    srand(seed);
    for (int i = 0; i < 6; ++i) {
        faces[i].ascii = static_cast<uint8_t>(rand() % 95 + 0x20);
        faces[i].glR   = rndChannel();
        faces[i].glG   = rndChannel();
        faces[i].glB   = rndChannel();
    }
}

// ─── 3D transforms ─────────────────────────────────────────────────────────

static Vec3 rotX(Vec3 v, float a) {
    float c = cosf(a), s = sinf(a);
    return {v.x, v.y * c - v.z * s, v.y * s + v.z * c};
}
static Vec3 rotY(Vec3 v, float a) {
    float c = cosf(a), s = sinf(a);
    return {v.x * c + v.z * s, v.y, -v.x * s + v.z * c};
}

/** Perspective projection (camera at origin looking down +Z). */
static void proj(Vec3 v, float *sx, float *sy, float fl, float cx, float cy) {
    float d = fl / (fl + v.z);
    *sx     = v.x * d + cx;
    *sy     = -v.y * d + cy;
}

// ─── face geometry (object space) ────────────────────────────────────────────

static const Vec3 kFaceNormal[6] = {
    {0, 0, 1},
    {0, 0, -1},
    {0, 1, 0},
    {0, -1, 0},
    {1, 0, 0},
    {-1, 0, 0},
};

static const Vec3 kFaceCentre[6] = {
    {0, 0, H},
    {0, 0, -H},
    {0, H, 0},
    {0, -H, 0},
    {H, 0, 0},
    {-H, 0, 0},
};

// Tangent (U) and bitangent (V) vectors per face.
// V points "up" (world +Y) where possible so glyphs appear upright.
// U is chosen so that (U × V) points outward (consistent with the normal).
static const Vec3 kFaceU[6] = {
    {1, 0, 0},  // Front  (+Z): right = +X
    {-1, 0, 0}, // Back   (-Z): right = -X  (avoids mirror when seen from outside)
    {1, 0, 0},  // Top    (+Y): right = +X
    {1, 0, 0},  // Bottom (-Y): right = +X
    {0, 0, -1}, // Right  (+X): right = -Z
    {0, 0, 1},  // Left   (-X): right = +Z
};

static const Vec3 kFaceV[6] = {
    {0, 1, 0},  // Front:  up = +Y
    {0, 1, 0},  // Back:   up = +Y
    {0, 0, -1}, // Top:    up = -Z  (points toward camera when looking down)
    {0, 0, 1},  // Bottom: up = +Z
    {0, 1, 0},  // Right:  up = +Y
    {0, 1, 0},  // Left:   up = +Y
};

// ─── cube rendering ──────────────────────────────────────────────────────────

/** Fills a projected quad (screen-space vertices, CCW) with a solid colour. */
static void fillQuad(const float sx[4], const float sy[4], uint8_t r, uint8_t g, uint8_t b, uint8_t a) {
    SDL_Vertex verts[4];
    for (int i = 0; i < 4; ++i) {
        verts[i].position  = {sx[i], sy[i]};
        verts[i].color     = {r / 255.f, g / 255.f, b / 255.f, a / 255.f};
        verts[i].tex_coord = {0.f, 0.f};
    }
    const int indices[] = {0, 1, 2, 0, 2, 3};
    SDL_RenderGeometry(g_rend, nullptr, verts, 4, indices, 6);
}

/**
 * Renders the glyph "printed" on a face by computing its corners in 3D object
 * space using the face tangent frame (U, V), applying the same pitch/yaw as
 * the cube, and drawing a textured quad via SDL_RenderGeometry.
 *
 * Texture UV mapping:
 *   (0,0) TL ── TR (1,0)
 *          │    │
 *   (0,1) BL ── BR (1,1)
 */
static void drawGlyphOnFace(
    int fi, float pitch, float yaw, float CX, float CY, float FL, const Face &f, SDL_Texture *charCache[128]) {
    static constexpr float Z_OFFSET = 200.f;

    const Vec3 &c = kFaceCentre[fi];
    const Vec3 &u = kFaceU[fi];
    const Vec3 &v = kFaceV[fi];

    // Glyph quad corners in object space:
    //   TL = centre - GS*U + GS*V
    //   TR = centre + GS*U + GS*V
    //   BR = centre + GS*U - GS*V
    //   BL = centre - GS*U - GS*V
    Vec3 obj[4] = {
        {c.x - GS * u.x + GS * v.x, c.y - GS * u.y + GS * v.y, c.z - GS * u.z + GS * v.z},
        {c.x + GS * u.x + GS * v.x, c.y + GS * u.y + GS * v.y, c.z + GS * u.z + GS * v.z},
        {c.x + GS * u.x - GS * v.x, c.y + GS * u.y - GS * v.y, c.z + GS * u.z - GS * v.z},
        {c.x - GS * u.x - GS * v.x, c.y - GS * u.y - GS * v.y, c.z - GS * u.z - GS * v.z},
    };

    static const SDL_FPoint kTexCoords[4] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};

    SDL_Vertex verts[4];
    for (int j = 0; j < 4; ++j) {
        Vec3 r = rotX(obj[j], pitch);
        r      = rotY(r, yaw);
        r.z += Z_OFFSET;
        float sx, sy;
        proj(r, &sx, &sy, FL, CX, CY);
        verts[j].position  = {sx, sy};
        verts[j].color     = {f.glR / 255.f, f.glG / 255.f, f.glB / 255.f, 1.f};
        verts[j].tex_coord = kTexCoords[j];
    }

    uint8_t ch = f.ascii;
    Color   fg{f.glR, f.glG, f.glB, 255};
    Color   bg{0, 0, 0, 0};
    if (!charCache[ch])
        charCache[ch] = Font::fontCharToTexture(g_rend, ch, fg, bg);
    const int indices[] = {0, 1, 2, 0, 2, 3};
    SDL_RenderGeometry(g_rend, charCache[ch], verts, 4, indices, 6);
}

/**
 * Draws the solid cube:
 *  - Backface culls invisible faces.
 *  - Sorts visible faces back-to-front (painter's algorithm).
 *  - Fills each face with its background colour.
 *  - Renders the face glyph as a textured quad printed onto the face surface.
 *
 * @param alpha  0–255 fade value applied to background fills.
 */
static void drawCube(
    Face faces[6], float pitch, float yaw, float CX, float CY, float FL, uint8_t alpha, SDL_Texture *charCache[128]) {
    static constexpr float Z_OFFSET = 200.f;

    struct FaceProj {
        float sx[4], sy[4];
        float avgZ;
        int   idx;
        bool  visible;
    } fp[6];

    for (int i = 0; i < 6; ++i) {
        fp[i].idx = i;

        // Backface culling — transformed normal z >= 0 → face points away
        Vec3 n        = rotX(kFaceNormal[i], pitch);
        n             = rotY(n, yaw);
        fp[i].visible = (n.z < 0.f);
        if (!fp[i].visible)
            continue;

        Vec3  rv[4];
        float sumZ = 0.f;
        for (int j = 0; j < 4; ++j) {
            rv[j] = rotX(faces[i].verts[j], pitch);
            rv[j] = rotY(rv[j], yaw);
            rv[j].z += Z_OFFSET;
            proj(rv[j], &fp[i].sx[j], &fp[i].sy[j], FL, CX, CY);
            sumZ += rv[j].z;
        }
        fp[i].avgZ = sumZ * 0.25f;
    }

    // Painter's algorithm: visible faces sorted back-to-front (highest avgZ first)
    std::sort(fp, fp + 6, [](const FaceProj &a, const FaceProj &b) {
        if (!a.visible)
            return false;
        if (!b.visible)
            return true;
        return a.avgZ > b.avgZ;
    });

    for (int i = 0; i < 6; ++i) {
        if (!fp[i].visible)
            continue;
        const Face &f = faces[fp[i].idx];

        // 1. Solid background fill
        fillQuad(fp[i].sx, fp[i].sy, f.bgR, f.bgG, f.bgB, alpha);

        // 2. Glyph printed onto the face (skip when fully transparent)
        if (alpha > 0)
            drawGlyphOnFace(fp[i].idx, pitch, yaw, CX, CY, FL, f, charCache);
    }
}

// ─── entry point ────────────────────────────────────────────────────────────

void testFontSDL() {
    SDL_Init(SDL_INIT_VIDEO);
    g_win  = SDL_CreateWindow("Font + Cube Test", 640, 480, 0);
    g_rend = SDL_CreateRenderer(g_win, nullptr);
    SDL_SetRenderDrawBlendMode(g_rend, SDL_BLENDMODE_BLEND);

    const float CX = 320.f, CY = 240.f, FL = 350.f;
    float       pitch = 0.4f, yaw = 0.3f;

    Face faces[6];
    initCube(faces, SDL_GetTicks());

    SDL_Texture *charCache[128] = {};

    uint32_t lastReveal   = SDL_GetTicks();
    uint32_t showDuration = 10000; // ms fully visible
    uint32_t fadeDuration = 2000;  // ms per fade transition
    bool     fullyGone    = false;

    SDL_Event e;
    while (!g_quit) {
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_EVENT_KEY_DOWN && e.key.key == SDLK_ESCAPE)
                g_quit = true;
            if (e.type == SDL_EVENT_QUIT)
                g_quit = true;
        }

        const float dt = 0.016f;
        pitch += 0.008f * dt * 60;
        yaw += 0.012f * dt * 60;

        // ── fade cycle ────────────────────────────────────────────────────────
        uint32_t now     = SDL_GetTicks();
        uint32_t elapsed = now - lastReveal;
        uint8_t  alpha   = 255;

        if (elapsed < showDuration) {
            alpha     = 255;
            fullyGone = false;
        } else if (elapsed < showDuration + fadeDuration) {
            alpha = static_cast<uint8_t>(
                255.f * (1.f - static_cast<float>(elapsed - showDuration) / static_cast<float>(fadeDuration)));
            fullyGone = false;
        } else if (elapsed < showDuration + fadeDuration * 2) {
            if (!fullyGone) {
                fullyGone = true;
                randomizeGlyphs(faces, now);
            }
            alpha = 0;
        } else if (elapsed < showDuration + fadeDuration * 3) {
            alpha     = static_cast<uint8_t>(255.f * static_cast<float>(elapsed - (showDuration + fadeDuration * 2)) /
                                             static_cast<float>(fadeDuration));
            fullyGone = false;
        } else {
            lastReveal = now;
            alpha      = 255;
        }

        // ── render ───────────────────────────────────────────────────────────
        SDL_SetRenderDrawColor(g_rend, 20, 20, 30, 255);
        SDL_RenderClear(g_rend);

        drawCube(faces, pitch, yaw, CX, CY, FL, alpha, charCache);

        // Hello World — scale 2× (yellow), always fully opaque
        const char *hw = "Hello World";
        for (int i = 0; hw[i]; ++i) {
            uint8_t ch = static_cast<uint8_t>(hw[i]);
            if (!charCache[ch])
                charCache[ch] = Font::fontCharToTexture(g_rend, ch, {255, 255, 255, 255}, {0, 0, 0, 0});
            SDL_Texture *t = charCache[ch];
            SDL_SetTextureColorMod(t, 255, 255, 100);
            SDL_SetTextureAlphaMod(t, 255);
            SDL_FRect dst{20.f + static_cast<float>(i) * 16.f, 20.f, 16.f, 16.f};
            SDL_RenderTexture(g_rend, t, nullptr, &dst);
        }

        // Hello World — scale 4× (cyan), always fully opaque
        for (int i = 0; hw[i]; ++i) {
            uint8_t ch = static_cast<uint8_t>(hw[i]);
            if (!charCache[ch])
                charCache[ch] = Font::fontCharToTexture(g_rend, ch, {255, 255, 255, 255}, {0, 0, 0, 0});
            SDL_Texture *t = charCache[ch];
            SDL_SetTextureColorMod(t, 100, 255, 255);
            SDL_SetTextureAlphaMod(t, 255);
            SDL_FRect dst{20.f + static_cast<float>(i) * 32.f, 60.f, 32.f, 32.f};
            SDL_RenderTexture(g_rend, t, nullptr, &dst);
        }

        SDL_RenderPresent(g_rend);
        SDL_Delay(16);
    }

    for (auto &t : charCache) {
        SDL_DestroyTexture(t);
        t = nullptr;
    }
    SDL_DestroyRenderer(g_rend);
    SDL_DestroyWindow(g_win);
    SDL_Quit();
}
