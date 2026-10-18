#!/usr/bin/env python3
"""Run an English debug host with P2 autoplay."""

from __future__ import annotations

import sys

from _session import help_requested, run_session


if __name__ == "__main__":
    if help_requested(sys.argv[1:], "Usage: both_second_player_ai.py [extra autoplay args...]"):
        raise SystemExit(0)
    raise SystemExit(run_session(
        ["--lang", "en", "--debugUtils", "--port", "7777", "--vsync", "2", "--silent"],
        ["--port", "7777", "--agent-p2", *sys.argv[1:]],
        7777,
    ))
