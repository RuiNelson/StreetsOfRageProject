#!/usr/bin/env python3
"""Shared, standard-library helpers for the workspace command-line scripts."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
META_ROOT = SCRIPT_DIR.parent


def script_path(name: str) -> Path:
    return SCRIPT_DIR / name


def script_command(name: str, *args: object, python: str | None = None) -> list[str]:
    """Return a command that runs a sibling Python entry point."""
    return [python or sys.executable, str(script_path(name)), *(str(arg) for arg in args)]


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def executable_path(directory: Path, name: str) -> Path:
    """Find a host executable, including the .exe form used by Windows."""
    names = (f"{name}.exe", name) if os.name == "nt" else (name, f"{name}.exe")
    for candidate in names:
        path = directory / candidate
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return directory / names[0]


def built_executable(build_dir: Path, name: str) -> Path:
    """Find the newest build of a host executable in a CMake build tree.

    Single-configuration generators (Makefiles, Ninja) put it in the build
    directory itself; Visual Studio, CMake's default on Windows, puts it in a
    per-configuration subdirectory such as Release.
    """
    directories = [build_dir, *(build_dir / config for config in ("Debug", "Release", "RelWithDebInfo", "MinSizeRel"))]
    candidates = [executable_path(directory, name) for directory in directories]
    existing = [path for path in candidates if path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime) if existing else candidates[0]


def absolute_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def prepend_pythonpath(environment: dict[str, str], *paths: Path) -> None:
    existing = environment.get("PYTHONPATH")
    entries = [str(path) for path in paths]
    if existing:
        entries.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(entries)


def find_tk_python() -> str | None:
    """Return an installed Python interpreter that can create Tk windows."""
    candidates = [sys.executable, "python3.11", "python3.12", "python3", "python"]
    seen: set[str] = set()
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).is_file() else candidate
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        if subprocess.run(
            [resolved, "-c", "import tkinter"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return resolved
    return None


def wait_for_tcp_listener(process: subprocess.Popen[object], port: int, *, timeout: float = 30) -> None:
    """Wait until a child process accepts local TCP connections or fails."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("host exited before it started listening")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"host did not start listening on port {port} within {timeout:g} seconds")


def stop_process(process: subprocess.Popen[object] | None) -> None:
    """Stop a process started by a wrapper, without touching unrelated hosts."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_checked(command: Sequence[str | Path], **kwargs: object) -> None:
    subprocess.run([str(item) for item in command], check=True, **kwargs)
