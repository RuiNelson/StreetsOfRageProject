#!/usr/bin/env python3
"""Launch the standalone Tk path-finding viewer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _common import META_ROOT, find_tk_python, prepend_pythonpath


def main() -> int:
    autoplay_src = META_ROOT / "autoplay" / "src"
    if not (autoplay_src / "sor_autoplay" / "ai" / "pathfind").is_dir():
        print(f"pathfind package not found: {autoplay_src / 'sor_autoplay' / 'ai' / 'pathfind'}", file=sys.stderr)
        return 1
    python = find_tk_python()
    if python is None:
        print("No Python with Tk (_tkinter) found.", file=sys.stderr)
        print("Install a Python build with Tk and retry.", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["SOR_PATHFIND_PROG"] = Path(sys.argv[0]).name
    prepend_pythonpath(environment, autoplay_src)
    os.execve(python, [python, "-m", "sor_autoplay.ai.pathfind.viewer", *sys.argv[1:]], environment)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
