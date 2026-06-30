"""ROM coverage map.

Produces a raw binary file where every byte of the ROM is represented
by one byte.

Character key (ASCII byte values)
---------------------------------
  X  data / unknown  (byte not reached by any code path)
  S  subroutine      (first byte of an instruction entered via JSR/BSR)
  s  subroutine end  (first byte of RTS / RTE / RTR)
  L  label           (first byte of an instruction that is a branch target)
  C  code            (first byte of any other decoded instruction)
  c  continuation    (extra byte inside a multi-word instruction)
"""

from .instruction import Instruction


# Instructions that end a subroutine or exception handler.
# ILLEGAL triggers the illegal-instruction exception, which like
# RTS/RTE/RTR permanently transfers control away — treating it as
# a terminal instruction lets the disassembler mark it 's' rather
# than misclassifying it as a subroutine entry ('S').
_RETURN_MNEMS = frozenset(['rts', 'rte', 'rtr', 'illegal'])


class RomMap:
    """Builds and serialises the ROM coverage map.

    Parameters
    ----------
    rom_size:
        Size of the ROM in bytes.
    instructions:
        ``{addr: Instruction}`` from the Disassembler.
    subroutines:
        Set of subroutine-entry addresses.
    labels:
        Set of branch-target addresses.
    """

    def __init__(self, rom_size: int,
                 instructions: dict,
                 subroutines: set[int],
                 labels: set[int]) -> None:
        self.rom_size     = rom_size
        self.instructions = instructions
        self.subroutines  = subroutines
        self.labels       = labels

        self._num_bytes = rom_size
        # One byte per ROM byte
        self._map: list[int] = [ord('X')] * self._num_bytes

        self._build()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def format(self) -> bytes:
        """Return the raw map as binary — one byte per ROM byte."""
        return bytes(self._map)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set(self, addr: int, ch: str) -> None:
        """Mark a byte at addr with classification ch."""
        if 0 <= addr < self.rom_size:
            self._map[addr] = ord(ch)

    def _build(self) -> None:
        for addr, instr in self.instructions.items():
            # Classify the first byte
            if instr.mnemonic in _RETURN_MNEMS:
                first_ch = 's'
            elif addr in self.subroutines:
                first_ch = 'S'
            elif addr in self.labels:
                first_ch = 'L'
            else:
                first_ch = 'C'

            self._set(addr, first_ch)

            # Mark extension bytes as continuation
            for ext_off in range(1, instr.byte_length):
                self._set(addr + ext_off, 'c')
