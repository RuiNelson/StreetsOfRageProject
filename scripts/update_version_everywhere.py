#!/usr/bin/env python3
"""Set the version of StreetsOfRageRecompilation and StreetsOfRageBuilder.

Usage: update_version_everywhere.py X.Y.Z [--dry-run]

Edits the files in place as text (formatting and line endings are kept):

- StreetsOfRageRecompilation/main.cpp (`sor --version`)
- StreetsOfRageBuilder/Backend/tauri.conf.json
- StreetsOfRageBuilder/Backend/Cargo.toml and the `streets-of-rage-builder`
  entry of Backend/Cargo.lock
- StreetsOfRageBuilder/Frontend/package.json and the two top entries of
  package-lock.json
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from _common import META_ROOT

RECOMPILATION = META_ROOT / "StreetsOfRageRecompilation"
BUILDER = META_ROOT / "StreetsOfRageBuilder"

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


@dataclass(frozen=True)
class Edit:
    path: Path
    # Group 1 is the text before the version, group 2 the version, group 3 what follows.
    pattern: str
    count: int = 1
    flags: int = re.MULTILINE


EDITS = (
    Edit(
        RECOMPILATION / "main.cpp",
        r'(set_version_flag\("-V,--version",\s*")([^"]+)(")',
    ),
    Edit(
        BUILDER / "Backend" / "tauri.conf.json",
        r'(^  "version":\s*")([^"]+)(")',
    ),
    Edit(
        BUILDER / "Backend" / "Cargo.toml",
        r'(\A.*?^\[package\].*?^version\s*=\s*")([^"]+)(")',
        flags=re.MULTILINE | re.DOTALL,
    ),
    Edit(
        BUILDER / "Backend" / "Cargo.lock",
        r'(^name = "streets-of-rage-builder"\r?\nversion = ")([^"]+)(")',
    ),
    Edit(
        BUILDER / "Frontend" / "package.json",
        r'(^  "version":\s*")([^"]+)(")',
    ),
    # Root "version" and packages[""].version; dependencies' own entries are indented deeper.
    Edit(
        BUILDER / "Frontend" / "package-lock.json",
        r'(^(?:  |      )"version":\s*")([^"]+)(")',
        count=2,
    ),
)


def apply(edit: Edit, version: str) -> tuple[str, str, str]:
    """Return (old text, new text, previous version) for one file."""
    text = edit.path.read_text(encoding="utf-8", newline="")
    matches = list(re.finditer(edit.pattern, text, edit.flags))
    if len(matches) < edit.count:
        raise SystemExit(f"{edit.path.relative_to(META_ROOT)}: version not found")
    chosen = matches[: edit.count]
    previous = chosen[0].group(2)
    # Rebuild from the end so earlier offsets stay valid.
    new_text = text
    for match in reversed(chosen):
        start, end = match.span(2)
        new_text = new_text[:start] + version + new_text[end:]
    return text, new_text, previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="new version, e.g. 0.3.0")
    parser.add_argument("--dry-run", action="store_true", help="show the changes without writing")
    args = parser.parse_args()

    if not VERSION_PATTERN.fullmatch(args.version):
        parser.error(f"{args.version!r} is not a version like X.Y.Z")

    results = [(edit, *apply(edit, args.version)) for edit in EDITS]
    for edit, old, new, previous in results:
        relative = edit.path.relative_to(META_ROOT)
        print(f"{relative}: {previous} -> {args.version}")
        if not args.dry_run and new != old:
            edit.path.write_text(new, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
