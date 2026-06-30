"""
Recursive-descent disassembler for the Streets of Rage Mega Drive ROM.

Architecture
============
The disassembler walks all 68000 code reachable from a set of seed
addresses using recursive descent, following JSR/BSR/JMP/BRA/Bcc paths.
It outputs 68000 assembly and a ROM coverage map.

Outputs
-------
- ``.asm``  — 68000 assembly source
- ``.map``  — ROM coverage map showing code/data classification

Seed addresses
--------------
- ``ENTRY_POINT = 0x000208``    — reset vector (ROM offset 0x004)
- ``VBLANK_ENTRY = 0x019D16``   — level-6 IRQ / VBlank handler (ROM offset 0x078)

Additional entry points can be supplied via an auxiliary address file
(one hex address per line, e.g. ``000300``).

ROM map legend
--------------
:X  data / unknown  (word not reached by any code path)
:S  subroutine entry  (first word entered via JSR/BSR)
:s  subroutine end  (first word of RTS/RTE/RTR/ILLEGAL)
:L  label  (first word of a branch/jump target)
:C  plain code  (first word of any other decoded instruction)
:c  continuation  (extension word inside a multi-word instruction)

68000 opcode coverage
====================
The decoder handles all instructions defined by the Exodus emulator
(``Exodus/Devices/M68000/M68000Opcodes.pkg``).  Any opcode not natively
supported is emitted as a ``dc.w`` macro so the output remains byte-exact.

Module overview
---------------
:mod:`rom`          — ROM binary reader (big-endian, bounds-checked)
:mod:`instruction` — data classes: ``Instruction``, ``Addr``, ``FlowType``
:mod:`decoder`      — one-pass 68000 decoder (all 16 opcode groups)
:mod:`disassembler` — recursive-descent engine (seed → trace → classify)
:mod:`formatter`     — ``AsmFormatter`` → ``.asm`` text
:mod:`rom_map`      — ``RomMap`` → text coverage map
:mod:`main`         — CLI entry point
"""

from .disassembler import Disassembler
from .decoder import DecodeError, InstructionDecoder
from .formatter import AsmFormatter
from .instruction import Addr, FlowType, Instruction
from .rom import ROM, ROMError
from .rom_map import RomMap

__all__ = [
    'Addr',
    'AsmFormatter',
    'DecodeError',
    'Disassembler',
    'FlowType',
    'Instruction',
    'InstructionDecoder',
    'ROM',
    'ROMError',
    'RomMap',
]
