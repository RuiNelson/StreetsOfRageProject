// Draws the disk image's background: a "drop into" arrow from the Builder (left) to the helper app (right).
// Run once: `swift background.swift` writes background.tiff (a 1x + 2x multi-resolution TIFF); commit it.
import AppKit

let width = 720, height = 440

func render(scale: Int) -> Data {
    let w = width * scale, h = height * scale
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: width, height: height)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: width, height: height).fill()

    // Window coordinates are top-left based in Finder; AppKit's are bottom-left.
    let midY = CGFloat(height) - 200          // icon centres are at y = 200 from the top
    let x0: CGFloat = 295, x1: CGFloat = 425  // arrow runs between the two icons
    let colour = NSColor(calibratedWhite: 0.45, alpha: 1)
    colour.setStroke(); colour.setFill()

    let shaft = NSBezierPath()
    shaft.lineWidth = 7
    shaft.lineCapStyle = .round
    shaft.move(to: NSPoint(x: x0, y: midY))
    shaft.line(to: NSPoint(x: x1 - 14, y: midY))
    shaft.stroke()

    let head = NSBezierPath()
    head.move(to: NSPoint(x: x1, y: midY))
    head.line(to: NSPoint(x: x1 - 30, y: midY + 20))
    head.line(to: NSPoint(x: x1 - 30, y: midY - 20))
    head.close()
    head.fill()

    let text = "drop into" as NSString
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 20, weight: .semibold),
        .foregroundColor: colour,
    ]
    let size = text.size(withAttributes: attrs)
    text.draw(at: NSPoint(x: (x0 + x1) / 2 - size.width / 2, y: midY + 26), withAttributes: attrs)

    // The order matters: the helper must be opened first, then the Builder dropped into its window.
    let steps = ["1. Open \u{201C}I am sure I want to open this App\u{201D} first", "2. Then drag Streets of Rage Builder into its window"] as [NSString]
    let stepAttrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 17, weight: .medium),
        .foregroundColor: NSColor(calibratedWhite: 0.25, alpha: 1),
    ]
    for (i, line) in steps.enumerated() {
        let sz = line.size(withAttributes: stepAttrs)
        line.draw(at: NSPoint(x: CGFloat(width) / 2 - sz.width / 2, y: CGFloat(height) - 52 - CGFloat(i) * 28), withAttributes: stepAttrs)
    }

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

try! render(scale: 1).write(to: URL(fileURLWithPath: "background.png"))
try! render(scale: 2).write(to: URL(fileURLWithPath: "background@2x.png"))
