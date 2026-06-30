"""ROM accessor — reads the Mega Drive ROM binary with bounds checking."""

import struct


class ROMError(Exception):
    """Raised when an out-of-bounds or unaligned access is attempted."""


class ROM:
    """Reads the Streets of Rage ROM with big-endian (68000) word access.

    The Mega Drive ROM is mapped at address 0x000000–0x07FFFF (512 KB).
    All multi-byte reads are big-endian because the 68000 is a big-endian
    CPU — the ROM data is stored in the same byte order the 68000 expects.

    Bounds checking
    ---------------
    Every read is checked against ``START``/``END`` before accessing
    ``self._data``.  Unaligned accesses (``addr & 1 != 0``) also raise
    :exc:`ROMError` because the 68000 cannot fetch odd-aligned words.

    Subclasses
    ----------
    The same interface can wrap a memory-mapped region (for the transpiler's
    live interpreter) or a flat binary file (for the disassembler).
    """

    START = 0x000000   #: First valid byte address
    END   = 0x07FFFF   #: Last valid byte address (inclusive)

    def __init__(self, data: bytes) -> None:
        self._data = data

    @classmethod
    def from_file(cls, path: str) -> 'ROM':
        with open(path, 'rb') as f:
            data = f.read()
        return cls(data)

    # ------------------------------------------------------------------
    # Bounds helpers
    # ------------------------------------------------------------------

    def in_bounds(self, address: int, length: int = 1) -> bool:
        return 0 <= address and (address + length - 1) <= self.END

    def _check(self, address: int, length: int) -> None:
        if not self.in_bounds(address, length):
            raise ROMError(f'Address out of bounds: ${address:08X}')

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_byte(self, address: int) -> int:
        self._check(address, 1)
        return self._data[address]

    def read_word(self, address: int) -> int:
        """Unsigned big-endian 16-bit word."""
        if address & 1:
            raise ROMError(f'Unaligned word read at ${address:06X}')
        self._check(address, 2)
        return struct.unpack_from('>H', self._data, address)[0]

    def read_word_signed(self, address: int) -> int:
        """Signed big-endian 16-bit word."""
        if address & 1:
            raise ROMError(f'Unaligned word read at ${address:06X}')
        self._check(address, 2)
        return struct.unpack_from('>h', self._data, address)[0]

    def read_long(self, address: int) -> int:
        """Unsigned big-endian 32-bit longword."""
        if address & 1:
            raise ROMError(f'Unaligned long read at ${address:06X}')
        self._check(address, 4)
        return struct.unpack_from('>I', self._data, address)[0]

    @property
    def size(self) -> int:
        return len(self._data)
