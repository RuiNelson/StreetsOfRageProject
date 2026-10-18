#!/usr/bin/env python3
"""Launch the autoplay HUD and symbolic AI against a running SoR host."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _common import META_ROOT, find_tk_python, prepend_pythonpath


def main() -> int:
    autoplay_src = META_ROOT / "autoplay" / "src"
    remote_src = META_ROOT / "MegaDriveEnvironment" / "python" / "src"
    if not (autoplay_src / "sor_autoplay").is_dir():
        print(f"autoplay package not found: {autoplay_src / 'sor_autoplay'}", file=sys.stderr)
        return 1
    if not (remote_src / "megadrive_remote").is_dir():
        print(f"megadrive_remote not found: {remote_src / 'megadrive_remote'}", file=sys.stderr)
        print("Ensure MegaDriveEnvironment is checked out as a sibling submodule.", file=sys.stderr)
        return 1

    python = find_tk_python()
    if python is None:
        print("No Python with Tk (_tkinter) found.", file=sys.stderr)
        print("Install a Python build with Tk and retry.", file=sys.stderr)
        return 1

    arguments = sys.argv[1:]
    if not any(arg == "--host" or arg.startswith("--host=") for arg in arguments):
        arguments[0:0] = ["--host", "127.0.0.1"]
    if not any(arg == "--port" or arg.startswith("--port=") for arg in arguments):
        arguments[0:0] = ["--port", "6969"]

    environment = os.environ.copy()
    environment["SOR_AUTOPLAY_PROG"] = Path(sys.argv[0]).name
    prepend_pythonpath(environment, autoplay_src, remote_src)
    os.execve(python, [python, "-m", "sor_autoplay", *arguments], environment)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
