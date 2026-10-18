#!/usr/bin/env python3
"""Shared implementation for wrappers that run a host and foreground autoplay."""

from __future__ import annotations

import subprocess
import sys
from typing import Sequence

from _common import script_command, stop_process, wait_for_tcp_listener


def help_requested(arguments: Sequence[str], usage: str) -> bool:
    if arguments and arguments[0] in {"-h", "--help"}:
        print(usage)
        return True
    return False


def run_session(host_arguments: Sequence[str], autoplay_arguments: Sequence[str], port: int) -> int:
    host = subprocess.Popen(script_command("run.py", *host_arguments))
    try:
        wait_for_tcp_listener(host, port)
        return subprocess.run(script_command("autoplay.py", *autoplay_arguments)).returncode
    except RuntimeError as error:
        print(f"{__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        stop_process(host)
