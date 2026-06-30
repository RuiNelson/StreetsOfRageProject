/**
 * @file VDPState.cpp
 * @brief VDP internal state implementation.
 */

#include "VDPState.hpp"

/// Clears all video memory (VRAM, CRAM, VSRAM), registers, and status flags to initial state.
void VDPState::reset() {
    std::memset(regs_, 0, sizeof(regs_));
    std::memset(vram_, 0, sizeof(vram_));
    std::memset(cram_, 0, sizeof(cram_));
    std::memset(vsram_, 0, sizeof(vsram_));
    std::memset(sat_, 0, sizeof(sat_));

    pendingSecondWord_ = false;
    firstWord_         = 0;
    code_              = 0;
    address_           = 0;
    dmaFillPending_    = false;
    status_            = 0x34C0;
    vCounter_          = 0;
    hCounter_          = 0;
    readBuffer_        = 0;
}

/// Returns plane A base address from register $02 bits 5–3 shifted to VRAM offset.
int VDPState::planeABase() const {
    return (regs_[0x02] & 0x38) << 10;
}

/// Returns plane B base address from register $04 bits 2–0 shifted to VRAM offset.
int VDPState::planeBBase() const {
    return (regs_[0x04] & 0x07) << 13;
}

/// Returns window plane base address from register $03. H40 enforces 4 KB alignment (mask 0xF000);
/// H32 allows 2 KB alignment (mask 0xF800), matching hardware behaviour.
int VDPState::windowBase() const {
    int raw = regs_[0x03] << 10;
    return (regs_[0x0C] & 0x01) ? (raw & 0xF000) : (raw & 0xF800);
}

/// Returns sprite attribute table base address from register $05 bits 6–0 shifted to VRAM offset.
/// H40 ignores bit 0 of the register (mask 0xFC00); H32 keeps it (mask 0xFE00) — matches hardware.
int VDPState::satBase() const {
    int base = (regs_[0x05] & 0x7F) << 9;
    return (regs_[0x0C] & 0x01) ? (base & 0xFC00) : (base & 0xFE00);
}

/// Returns horizontal scroll table base address from register $0D bits 5–0 shifted to VRAM offset.
int VDPState::hscrollBase() const {
    return (regs_[0x0D] & 0x3F) << 10;
}

/// Returns plane width in cells (32, 64, or 128) from register $10 bits 1–0.
int VDPState::planeWidthCells() const {
    switch (regs_[0x10] & 0x03) {
        case 0x01:
            return 64;
        case 0x03:
            return 128;
        default:
            return 32;
    }
}

/// Returns plane height in cells (32, 64, or 128) from register $10 bits 5–4.
int VDPState::planeHeightCells() const {
    switch ((regs_[0x10] >> 4) & 0x03) {
        case 0x01:
            return 64;
        case 0x03:
            return 128;
        default:
            return 32;
    }
}

/// Returns auto-increment value added to address register after each data port access (from register $0F).
int VDPState::autoIncrement() const {
    return regs_[0x0F];
}

/// Returns background color palette (0–3) from register $07 bits 5–4.
int VDPState::bgColorPalette() const {
    return (regs_[0x07] >> 4) & 0x03;
}

/// Returns background color index (0–15) from register $07 bits 3–0.
int VDPState::bgColorIndex() const {
    return regs_[0x07] & 0x0F;
}

/// Returns horizontal scroll mode (0=full, 2=per-8-line, 3=per-scanline) from register $0B bits 1–0.
int VDPState::hscrollMode() const {
    return regs_[0x0B] & 0x03;
}

/// Returns vertical scroll mode (0=full screen, 1=per-2-cell) from register $0B bit 2.
int VDPState::vscrollMode() const {
    return (regs_[0x0B] >> 2) & 0x01;
}

/// Returns true if display is enabled from register $01 bit 6.
bool VDPState::displayEnabled() const {
    return (regs_[0x01] & 0x40) != 0;
}

/// Returns true if DMA is enabled from register $01 bit 4.
bool VDPState::dmaEnabled() const {
    return (regs_[0x01] & 0x10) != 0;
}

/// Returns true if VBlank IRQ is enabled from register $01 bit 5.
bool VDPState::vblankIRQEnabled() const {
    return (regs_[0x01] & 0x20) != 0;
}

/// Returns true if HBlank IRQ is enabled from register $00 bit 4.
bool VDPState::hintEnabled() const {
    return (regs_[0x00] & 0x10) != 0;
}

/// Returns reload value for the horizontal interrupt down-counter from register $0A.
int VDPState::hintReloadValue() const {
    return static_cast<int>(regs_[0x0A]);
}

/// Returns window plane horizontal position in cells (0–31) from register $11 bits 4–0.
int VDPState::windowHPos() const {
    return regs_[0x11] & 0x1F;
}

/// Returns window plane vertical position in cells (0–31) from register $12 bits 4–0.
int VDPState::windowVPos() const {
    return regs_[0x12] & 0x1F;
}

/// Returns true if window is positioned on right side of screen from register $11 bit 7.
bool VDPState::windowRight() const {
    return (regs_[0x11] & 0x80) != 0;
}

/// Returns true if window is positioned on bottom of screen from register $12 bit 7.
bool VDPState::windowDown() const {
    return (regs_[0x12] & 0x80) != 0;
}