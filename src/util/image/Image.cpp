#include "Image.hpp"
#include "util/font/Font.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <png.h>

Image::Image() : size{0, 0} {
    rawBuffer = nullptr;
}

Image::Image(ImageSize size_, Color background) : size(size_) {
    if (size.width <= 0 || size.height <= 0) {
        rawBuffer = nullptr;
        size      = {0, 0};
        return;
    }
    rawBuffer    = malloc(size.width * size.height * 3);
    uint8_t *buf = static_cast<uint8_t *>(rawBuffer);
    for (int i = 0; i < size.width * size.height; ++i) {
        buf[i * 3 + 0] = background.r;
        buf[i * 3 + 1] = background.g;
        buf[i * 3 + 2] = background.b;
    }
}

Image::Image(std::string text, Color background, Color foreground) : size{0, 0} {
    if (text.empty()) {
        text = " ";
    }
    int charCount = static_cast<int>(text.size());
    int imgWidth  = charCount * 8;
    int imgHeight = 8;
    size.width    = imgWidth;
    size.height   = imgHeight;

    rawBuffer    = malloc(imgWidth * imgHeight * 3);
    uint8_t *buf = static_cast<uint8_t *>(rawBuffer);

    for (int i = 0; i < imgWidth * imgHeight * 3; ++i) {
        buf[i] = background.g;
    }

    for (int c = 0; c < charCount; ++c) {
        FontPixelBuffer glyph = Font::fontCharToPixels(static_cast<uint8_t>(text[c]),
                                                       false,
                                                       {foreground.r, foreground.g, foreground.b, 255},
                                                       {background.r, background.g, background.b, 255});
        if (!glyph.data) {
            continue;
        }
        for (int y = 0; y < 8; ++y) {
            for (int x = 0; x < 8; ++x) {
                int dstX        = c * 8 + x;
                int dstY        = y;
                int srcIdx      = y * 8 + x;
                int dstIdx      = (dstY * imgWidth + dstX) * 3;
                buf[dstIdx + 0] = glyph.data[srcIdx * 3 + 0];
                buf[dstIdx + 1] = glyph.data[srcIdx * 3 + 1];
                buf[dstIdx + 2] = glyph.data[srcIdx * 3 + 2];
            }
        }
        free(glyph.data);
    }
}

Image::Image(const Image &other) : size(other.size) {
    if (!other.rawBuffer) {
        rawBuffer = nullptr;
        return;
    }
    rawBuffer = malloc(size.width * size.height * 3);
    memcpy(rawBuffer, other.rawBuffer, size.width * size.height * 3);
}

Image &Image::operator=(const Image &other) {
    if (this == &other) {
        return *this;
    }
    free(rawBuffer);
    size = other.size;
    if (!other.rawBuffer) {
        rawBuffer = nullptr;
        return *this;
    }
    rawBuffer = malloc(size.width * size.height * 3);
    memcpy(rawBuffer, other.rawBuffer, size.width * size.height * 3);
    return *this;
}

Image::~Image() {
    free(rawBuffer);
}

void *Image::getRawBuffer() {
    return rawBuffer;
}

ImageSize Image::getSize() {
    return size;
}

int Image::byteCount() {
    return size.width * size.height * 3;
}

void Image::printToPNG(std::string fileName) {
    if (!rawBuffer) {
        return;
    }
    FILE *f = fopen(fileName.c_str(), "wb");
    if (!f) {
        return;
    }

    png_structp png = png_create_write_struct(PNG_LIBPNG_VER_STRING, nullptr, nullptr, nullptr);
    if (!png) {
        fclose(f);
        return;
    }

    png_infop info = png_create_info_struct(png);
    if (!info) {
        png_destroy_write_struct(&png, nullptr);
        fclose(f);
        return;
    }

    if (setjmp(png_jmpbuf(png))) {
        png_destroy_write_struct(&png, &info);
        fclose(f);
        return;
    }

    png_init_io(png, f);
    png_set_IHDR(png,
                 info,
                 size.width,
                 size.height,
                 8,
                 PNG_COLOR_TYPE_RGB,
                 PNG_INTERLACE_NONE,
                 PNG_COMPRESSION_TYPE_DEFAULT,
                 PNG_FILTER_TYPE_DEFAULT);
    png_write_info(png, info);

    uint8_t *buf = static_cast<uint8_t *>(rawBuffer);
    for (int y = 0; y < size.height; ++y) {
        png_bytep row = static_cast<png_bytep>(png_malloc(png, size.width * 3));
        for (int x = 0; x < size.width; ++x) {
            row[x * 3 + 0] = buf[(y * size.width + x) * 3 + 0];
            row[x * 3 + 1] = buf[(y * size.width + x) * 3 + 1];
            row[x * 3 + 2] = buf[(y * size.width + x) * 3 + 2];
        }
        png_write_row(png, row);
        png_free(png, row);
    }

    png_write_end(png, info);
    png_destroy_write_struct(&png, &info);
    fclose(f);
}

Image Image::joinVertically(Image top, Image bottom, int gap, Color background) {
    if (!top.rawBuffer && !bottom.rawBuffer) {
        return Image();
    }
    if (!top.rawBuffer) {
        return bottom;
    }
    if (!bottom.rawBuffer) {
        return top;
    }
    int      width = top.size.width > bottom.size.width ? top.size.width : bottom.size.width;
    Image    result{{width, top.size.height + gap + bottom.size.height}, background};
    uint8_t *dst = static_cast<uint8_t *>(result.rawBuffer);

    // top
    uint8_t *srcTop = static_cast<uint8_t *>(top.rawBuffer);
    int      copyW  = top.size.width < result.size.width ? top.size.width : result.size.width;
    for (int y = 0; y < top.size.height; ++y) {
        for (int x = 0; x < copyW; ++x) {
            int dstIdx      = (y * result.size.width + x) * 3;
            int srcIdx      = (y * top.size.width + x) * 3;
            dst[dstIdx + 0] = srcTop[srcIdx + 0];
            dst[dstIdx + 1] = srcTop[srcIdx + 1];
            dst[dstIdx + 2] = srcTop[srcIdx + 2];
        }
    }

    // bottom
    uint8_t *srcBot   = static_cast<uint8_t *>(bottom.rawBuffer);
    int      botY     = top.size.height + gap;
    int      botCopyW = bottom.size.width < result.size.width ? bottom.size.width : result.size.width;
    for (int y = 0; y < bottom.size.height; ++y) {
        for (int x = 0; x < botCopyW; ++x) {
            int dstIdx      = ((botY + y) * result.size.width + x) * 3;
            int srcIdx      = (y * bottom.size.width + x) * 3;
            dst[dstIdx + 0] = srcBot[srcIdx + 0];
            dst[dstIdx + 1] = srcBot[srcIdx + 1];
            dst[dstIdx + 2] = srcBot[srcIdx + 2];
        }
    }

    return result;
}

Image Image::joinHorizontally(Image left, Image right, int gap, Color background) {
    if (!left.rawBuffer && !right.rawBuffer) {
        return Image();
    }
    if (!left.rawBuffer) {
        return right;
    }
    if (!right.rawBuffer) {
        return left;
    }
    int      height = left.size.height > right.size.height ? left.size.height : right.size.height;
    Image    result{{left.size.width + gap + right.size.width, height}, background};
    uint8_t *dst = static_cast<uint8_t *>(result.rawBuffer);

    // left
    uint8_t *srcLeft = static_cast<uint8_t *>(left.rawBuffer);
    int      copyH   = left.size.height < result.size.height ? left.size.height : result.size.height;
    for (int y = 0; y < copyH; ++y) {
        for (int x = 0; x < left.size.width; ++x) {
            int dstIdx      = (y * result.size.width + x) * 3;
            int srcIdx      = (y * left.size.width + x) * 3;
            dst[dstIdx + 0] = srcLeft[srcIdx + 0];
            dst[dstIdx + 1] = srcLeft[srcIdx + 1];
            dst[dstIdx + 2] = srcLeft[srcIdx + 2];
        }
    }

    // right
    uint8_t *srcRight   = static_cast<uint8_t *>(right.rawBuffer);
    int      rightX     = left.size.width + gap;
    int      rightCopyH = right.size.height < result.size.height ? right.size.height : result.size.height;
    for (int y = 0; y < rightCopyH; ++y) {
        for (int x = 0; x < right.size.width; ++x) {
            int dstIdx      = (y * result.size.width + rightX + x) * 3;
            int srcIdx      = (y * right.size.width + x) * 3;
            dst[dstIdx + 0] = srcRight[srcIdx + 0];
            dst[dstIdx + 1] = srcRight[srcIdx + 1];
            dst[dstIdx + 2] = srcRight[srcIdx + 2];
        }
    }

    return result;
}

Image Image::addLabel(std::string label, Image img, int gap, Color background, Color foreground) {
    if (!img.rawBuffer) {
        return Image(label, background, foreground);
    }
    Image labelImg(label, background, foreground);
    return joinVertically(labelImg, img, gap, background);
}

Image Image::addLabelOnTop(std::string label, int gap, Color background, Color foreground) {
    Image labelImg(label, background, foreground);
    return joinVertically(labelImg, *this, gap, background);
}

Image Image::addLabelOnBottom(std::string label, int gap, Color background, Color foreground) {
    Image labelImg(label, background, foreground);
    return joinVertically(*this, labelImg, gap, background);
}

Image Image::addLabelOnLeft(std::string label, int gap, Color background, Color foreground) {
    Image labelImg(label, background, foreground);
    return joinHorizontally(labelImg, *this, gap, background);
}

Image Image::addLabelOnRight(std::string label, int gap, Color background, Color foreground) {
    Image labelImg(label, background, foreground);
    return joinHorizontally(*this, labelImg, gap, background);
}

void Image::addOnTop(Image otherImage, int gap, Color background) {
    *this = joinVertically(otherImage, *this, gap, background);
}

void Image::addOnBottom(Image otherImage, int gap, Color background) {
    *this = joinVertically(*this, otherImage, gap, background);
}

void Image::addOnLeft(Image otherImage, int gap, Color background) {
    *this = joinHorizontally(otherImage, *this, gap, background);
}

void Image::addOnRight(Image otherImage, int gap, Color background) {
    *this = joinHorizontally(*this, otherImage, gap, background);
}
