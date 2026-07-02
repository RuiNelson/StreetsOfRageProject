#!/usr/bin/env python3
"""Unified CLI for the repository's reverse-engineering tools.

The individual modules remain importable libraries; this file is the single
operator-facing entry point:

    python3 -m tools disassemble rom/SOR.bin -o output/sor.asm
    python3 -m tools recompile rom/SOR.bin -o src/generated
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable


Command = tuple[str, str, str]


_COMMANDS: dict[str, Command] = {
    'disassemble': (
        'tools.disassembler.main',
        'main',
        'Recursive-descent 68000 disassembler; writes .asm and optional .map.',
    ),
    'recompile': (
        'tools.recompiler.main',
        'main',
        'Static 68000-to-C++ recompiler; writes Sor.hpp / Sor.cpp.',
    ),
    'speculative-scan': (
        'tools.speculative_scan.main',
        'main',
        'Scan unmapped ROM regions for plausible function entry points.',
    ),
    'remove-data': (
        'tools.remove_data_locations.__main__',
        'main',
        'Strip assembly label blocks that contain dc.b/dc.w/dc.l data.',
    ),
    'label-diff': (
        'tools.label_diff.script',
        'main',
        'Print labels present in the second assembly file but not the first.',
    ),
    'map-label-gaps': (
        'tools.label_diff.map_label_gaps',
        'main',
        'Print reference labels whose addresses are still X in a ROM map.',
    ),
    'iterative-disasm': (
        'tools.iterative_disasm.script',
        'main',
        'Iteratively add missing labels to an aux address file.',
    ),
}

_ALIASES = {
    'disasm': 'disassemble',
    'recompiler': 'recompile',
    'specscan': 'speculative-scan',
    'strip-data': 'remove-data',
    'labels-missing': 'label-diff',
}


def _load_callable(module_name: str, attr: str) -> Callable[[list[str] | None], int | None]:
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _print_help() -> None:
    print('Usage: python3 -m tools <command> [args...]')
    print()
    print('Commands:')
    width = max(len(name) for name in _COMMANDS)
    for name, (_, _, desc) in sorted(_COMMANDS.items()):
        print(f'  {name:<{width}}  {desc}')
    print()
    print('Run "python3 -m tools <command> --help" for command-specific help.')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        _print_help()
        return 0

    raw_command = argv.pop(0)
    command = _ALIASES.get(raw_command, raw_command)
    spec = _COMMANDS.get(command)
    if spec is None:
        print(f'Unknown tools command: {raw_command}', file=sys.stderr)
        print('Run "python3 -m tools --help" to see available commands.',
              file=sys.stderr)
        return 2

    func = _load_callable(spec[0], spec[1])
    old_argv = sys.argv
    sys.argv = [f'python3 -m tools {command}', *argv]
    try:
        result = func(argv)
    finally:
        sys.argv = old_argv
    return 0 if result is None else int(result)


if __name__ == '__main__':
    sys.exit(main())
