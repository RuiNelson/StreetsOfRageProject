"""Static 68000 → C++ recompiler for Streets of Rage.

Consumes the disassembler's structured ``Instruction`` / ``EA`` stream (see
``tools/disassembler/instruction.py``) and emits a ``MegaDriveEnvironment``
subclass whose ``run()`` is the recompiled cartridge code.

Pipeline
--------
``ea_codegen``   EA  → C++ read/write/address expressions (with temporaries).
``opcodes``      Instruction → C++ statement(s) (operation + CCR flags).
``regions``      Partition instructions into functions; loops stay as loops.
``generator``    Orchestrate emission of the Sor.hpp / Sor.cpp pair.
``main``         CLI entry point.
"""
