"""Canonical hex-address file helpers used by disasm/recompile/discovery tools."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


def parse_address_lines(path: str | Path, *, code_only: bool = False,
                        warn_prefix: str | None = None) -> list[int]:
    """Load hex addresses from a text file.

    Blank lines and comments beginning with ``;`` or ``#`` are ignored. Inline
    comments after either marker are stripped. When *code_only* is true, vector
    table/header addresses and odd addresses are skipped because they cannot be
    68000 code entry points in this ROM.
    """
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []

    out: list[int] = []
    with p.open() as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.split(';')[0].split('#')[0].strip()
            if not line:
                continue
            try:
                addr = int(line, 16) & 0x00FFFFFF
            except ValueError:
                if warn_prefix:
                    print(f'{warn_prefix} bad address on line {lineno} of {p}: '
                          f'{raw.rstrip()!r}', file=sys.stderr)
                continue
            if code_only and (addr < 0x000200 or (addr & 1)):
                if warn_prefix:
                    print(f'{warn_prefix} ignoring invalid code address ${addr:06X}',
                          file=sys.stderr)
                continue
            out.append(addr)
    return out


def format_address(addr: int) -> str:
    return f'{addr & 0x00FFFFFF:06X}'


def write_address_file(addresses: Iterable[int], path: str | Path,
                       *, header: str | None = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w') as f:
        if header:
            f.write(header.rstrip() + '\n')
        for addr in addresses:
            f.write(format_address(addr) + '\n')

