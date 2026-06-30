#pragma once
#include "VDPState.hpp"

class MegaDriveEnvironment;

/**
 * @file VDPPort.hpp
 * @brief VDP I/O port emulation — control port, data port, HV counter.
 *
 * Handles the two-word write protocol, DMA execution, and memory read/write
 * operations for the VDP's external bus interface.
 */

class VDPPort {
    public:
    /// Initializes port handler with reference to VDP state.
    explicit VDPPort(VDPState &state) : state_(&state) {
    }

    /// Sets the owning environment, used to reach system memory for 68K→VRAM DMA.
    void setEnvironment(MegaDriveEnvironment *env) {
        env_ = env;
    }

    // ── Port I/O ────────────────────────────────────────────────────────────

    /// Writes to control port ($C00004). Handles two-word address set and register writes.
    void writeControlPort(m_word value);

    /// Reads status register. Returns VDP status and clears pending second word flag.
    m_word readControlPort();

    /// Writes to data port ($C00000). Routes to VRAM/CRAM/VSRAM based on code register.
    void writeDataPort(m_word value);

    /// Reads from data port. Returns read-ahead value; prefetches next value from current address.
    m_word readDataPort();

    /// Reads H and V counter. V counter in high byte, H counter in low byte.
    m_word readHVCounter();

    // ── DMA ─────────────────────────────────────────────────────────────────

    /// Executes DMA operation based on mode in register $17 bits 7–6 (copy, fill, or VRAM copy).
    void executeDMA();

    private:
    /// Pointer to VDP state for register, memory, and counter access.
    VDPState *state_;

    /// Owning environment, used to read 68K system memory during DMA.
    MegaDriveEnvironment *env_ = nullptr;

    // ── Control port processing ──────────────────────────────────────────────

    /// Decodes and writes VDP control register value.
    void processRegisterWrite(m_word value);

    /// Finalizes address set and triggers DMA if enabled.
    void processAddressSet();

    // ── DMA operations ──────────────────────────────────────────────────────

    /// DMA copy: transfers data from 68000 RAM to VRAM/CRAM/VSRAM.
    void executeDMACopy();

    /// DMA fill: fills VRAM with a single word (triggered by data port write).
    void executeDMAFill(m_word fillWord);

    /// DMA VRAM copy: transfers data from VRAM to VRAM.
    void executeDMAVRAMCopy();

    // ── Memory access ───────────────────────────────────────────────────────

    /// Writes word to VRAM at current address; increments address by auto-increment value.
    void writeVRAM(m_word value);

    /// Writes word to CRAM at current address; increments address.
    void writeCRAM(m_word value);

    /// Writes word to VSRAM at current address; increments address.
    void writeVSRAM(m_word value);

    /// Reads word from VRAM at current address; increments address.
    m_word readVRAM();

    /// Reads word from CRAM at current address; increments address.
    m_word readCRAM();

    /// Reads word from VSRAM at current address; increments address.
    m_word readVSRAM();

    /// Mirrors one byte from vram_[] into sat_[] if byteAddr falls within the SAT region.
    void updateSATShadow(m_word byteAddr);
};