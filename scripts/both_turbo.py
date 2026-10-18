#!/usr/bin/env python3
"""Run the canonical measured turbo session for P1 Blaze autoplay."""

from __future__ import annotations

import sys

from _session import help_requested, run_session


if __name__ == "__main__":
    if help_requested(sys.argv[1:], "Usage: both_turbo.py [extra autoplay args...]"):
        raise SystemExit(0)
    raise SystemExit(run_session(
        ["--turbo", "2", "--lang", "en", "--debugUtils", "--port", "7777", "--silent"],
        ["--poll-ms", "16", "--port", "7777", "--agent-p1", "--reach-gameplay", "blaze", *sys.argv[1:]],
        7777,
    ))
