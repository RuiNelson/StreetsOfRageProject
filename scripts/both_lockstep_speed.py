#!/usr/bin/env python3
"""Run an AI-clocked, frame-exact autoplay session."""

from __future__ import annotations

import sys

from _session import help_requested, run_session


if __name__ == "__main__":
    if help_requested(sys.argv[1:], "Usage: both_lockstep_speed.py [extra autoplay args...]"):
        raise SystemExit(0)
    raise SystemExit(run_session(
        ["--turbo", "10", "--lang", "en", "--debugUtils", "--port", "6767", "--silent"],
        ["--lockstep", "--port", "6767", "--agent-p1", "--reach-gameplay", "blaze", *sys.argv[1:]],
        6767,
    ))
