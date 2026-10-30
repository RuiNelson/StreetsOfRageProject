#!/usr/bin/env python3
"""Launch the standalone Tk path-finding viewer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _common import META_ROOT, find_tk_python, prepend_pythonpath


def main() -> int:
    autoplay_src = META_ROOT / "autoplay" / "src"
    ai_code = META_ROOT / "autoplay" / "ai-code"
    if not (ai_code / "sor_ai" / "ai" / "pathfind").is_dir():
        print(f"pathfind package not found: {ai_code / 'sor_ai' / 'ai' / 'pathfind'}", file=sys.stderr)
        return 1
    python = find_tk_python()
    if python is None:
        print("No Python with Tk (_tkinter) found.", file=sys.stderr)
        print("Install a Python build with Tk and retry.", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["SOR_PATHFIND_PROG"] = Path(sys.argv[0]).name
    prepend_pythonpath(environment, autoplay_src, ai_code)
    os.execve(python, [python, "-m", "sor_autoplay.pathfind_viewer", *sys.argv[1:]], environment)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
