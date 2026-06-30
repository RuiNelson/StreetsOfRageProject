#pragma once

#include "util/font/Font.hpp"
#include <string>

struct ImageSize {
    int width, height;
};

/**
 * @brief A raw image with an RGB buffer.
 *
 * Image data is stored as 3 bytes per pixel (RGB order).
 * The image owns its rawBuffer and frees it on destruction.
 */
class Image {
    private:
    void     *rawBuffer;
    ImageSize size;

    public:
    /**
     * @brief Creates an empty Image with no pixels.
     */
    Image();

    /**
     * @brief Creates an empty Image filled with one color.
     * @param size Image dimensions in pixels.
     * @param background Fill color for all pixels.
     */
    Image(ImageSize size, Color background);

    /**
     * @brief Renders text as an image using the 8×8 bitmap font.
     * @param text String to render (characters 0x20–0x7E).
     * @param background Fill color for background pixels.
     * @param foreground Color for foreground (text) pixels.
     */
    Image(std::string text, Color background, Color foreground);

    /**
     * @brief Copy constructor.
     * @param other Image to copy.
     */
    Image(const Image &other);

    /**
     * @brief Copy assignment operator.
     * @param other Image to copy.
     * @return Reference to this image.
     */
    Image &operator=(const Image &other);

    /**
     * @brief Destructor. Frees the raw RGB buffer.
     */
    virtual ~Image();

    /**
     * @brief Returns the raw RGB buffer pointer.
     * @return Pointer to width×height×3 bytes.
     */
    void *getRawBuffer();

    /**
     * @brief Returns the image dimensions.
     * @return ImageSize with width and height in pixels.
     */
    ImageSize getSize();

    /**
     * @brief Returns the buffer size in bytes.
     * @return width × height × 3.
     */
    int byteCount();

    /**
     * @brief Writes the image to a PNG file.
     * @param fileName Output file name.
     */
    void printToPNG(std::string fileName);

    // static
    /**
     * @brief Stacks two images vertically with a gap between them.
     * @param top Image placed at the top.
     * @param bottom Image placed at the bottom.
     * @param gap Number of pixels between the two images (filled with background).
     * @param background Fill color for the gap and any unused area.
     * @return A new image with width = max(top.width, bottom.width) and
     *         height = top.height + gap + bottom.height.
     */
    static Image joinVertically(Image top, Image bottom, int gap, Color background);

    /**
     * @brief Places two images side by side with a gap between them.
     * @param left Image placed on the left.
     * @param right Image placed on the right.
     * @param gap Number of pixels between the two images (filled with background).
     * @param background Fill color for the gap and any unused area.
     * @return A new image with width = left.width + gap + right.width and
     *         height = max(left.height, right.height).
     */
    static Image joinHorizontally(Image left, Image right, int gap, Color background);

    /**
     * @brief Appends a text label below an image.
     * @param label Text string to render as the label.
     * @param img Image to place above the label.
     * @param gap Number of pixels between the image and the label.
     * @param background Fill color for the gap and label background.
     * @param foreground Color for label text pixels.
     * @return A new image with img stacked above the label.
     */
    static Image addLabel(std::string label, Image img, int gap, Color background, Color foreground);

    /**
     * @brief Places a text label above this image.
     * @param label Text string to render as the label.
     * @param gap Number of pixels between the image and the label.
     * @param background Fill color for the gap and label background.
     * @param foreground Color for label text pixels.
     * @return A new image with the label stacked above this image.
     */
    Image addLabelOnTop(std::string label, int gap, Color background, Color foreground);

    /**
     * @brief Places a text label below this image.
     * @param label Text string to render as the label.
     * @param gap Number of pixels between the image and the label.
     * @param background Fill color for the gap and label background.
     * @param foreground Color for label text pixels.
     * @return A new image with the label stacked below this image.
     */
    Image addLabelOnBottom(std::string label, int gap, Color background, Color foreground);

    /**
     * @brief Places a text label to the left of this image.
     * @param label Text string to render as the label.
     * @param gap Number of pixels between the image and the label.
     * @param background Fill color for the gap and label background.
     * @param foreground Color for label text pixels.
     * @return A new image with the label to the left of this image.
     */
    Image addLabelOnLeft(std::string label, int gap, Color background, Color foreground);

    /**
     * @brief Places a text label to the right of this image.
     * @param label Text string to render as the label.
     * @param gap Number of pixels between the image and the label.
     * @param background Fill color for the gap and label background.
     * @param foreground Color for label text pixels.
     * @return A new image with the label to the right of this image.
     */
    Image addLabelOnRight(std::string label, int gap, Color background, Color foreground);

    // Mutating functions

    /**
     * @brief Places another image on top of this image.
     * @param otherImage Image to place above.
     * @param gap Number of pixels between the two images (filled with background).
     * @param background Fill color for the gap.
     */
    void addOnTop(Image otherImage, int gap, Color background);

    /**
     * @brief Places another image below this image.
     * @param otherImage Image to place below.
     * @param gap Number of pixels between the two images (filled with background).
     * @param background Fill color for the gap.
     */
    void addOnBottom(Image otherImage, int gap, Color background);

    /**
     * @brief Places another image to the left of this image.
     * @param otherImage Image to place on the left.
     * @param gap Number of pixels between the two images (filled with background).
     * @param background Fill color for the gap.
     */
    void addOnLeft(Image otherImage, int gap, Color background);

    /**
     * @brief Places another image to the right of this image.
     * @param otherImage Image to place on the right.
     * @param gap Number of pixels between the two images (filled with background).
     * @param background Fill color for the gap.
     */
    void addOnRight(Image otherImage, int gap, Color background);
};