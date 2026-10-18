#!/usr/bin/env python3
"""Run an English debug host with sound and P1 Blaze autoplay."""

from __future__ import annotations

import sys

from _session import help_requested, run_session


if __name__ == "__main__":
    if help_requested(sys.argv[1:], "Usage: both_sound.py [extra autoplay args...]"):
        raise SystemExit(0)
    raise SystemExit(run_session(
        ["--lang", "en", "--debugUtils", "--port", "7777"],
        ["--port", "7777", "--reach-gameplay", "blaze", "--agent-p1", *sys.argv[1:]],
        7777,
    ))
