#!/usr/bin/env python3
"""Synchronize and update all workspace submodules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import META_ROOT


def main() -> int:
    if sys.argv[1:] and sys.argv[1] in {"-h", "--help"}:
        print(f"Usage: {Path(sys.argv[0]).name}")
        return 0
    for command in (
        ["git", "submodule", "sync", "--recursive"],
        ["git", "submodule", "update", "--init", "--remote", "--recursive"],
        ["git", "submodule", "status", "--recursive"],
    ):
        result = subprocess.run(command, cwd=META_ROOT)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
