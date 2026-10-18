#!/usr/bin/env python3
"""Put autoplay in front of a stage's boss with non-boss enemies swept."""

from __future__ import annotations

import sys
from pathlib import Path

from _session import run_session


NO_FOOD_LEVELS = {2, 3, 4, 5, 8}


def main() -> int:
    arguments = sys.argv[1:]
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(f"Usage: {Path(sys.argv[0]).name} <level 1-8> [extra autoplay args...]")
        return 0 if arguments else 2
    try:
        level = int(arguments.pop(0))
    except ValueError:
        level = 0
    if level not in range(1, 9):
        print(f"{Path(sys.argv[0]).name}: level must be 1-8", file=sys.stderr)
        return 2
    sweep = "--kill-until-mr-x" if level == 8 else "--kill-street-enemies"
    no_food = ["--no-food"] if level in NO_FOOD_LEVELS else []
    return run_session(
        ["--turbo", "2", "--lang", "en", "--debugUtils", "--port", "7777", "--silent"],
        ["--poll-ms", "16", "--port", "7777", "--agent-p1", "--reach-gameplay", "blaze",
         "--start-level", str(level), sweep, "--no-police", *no_food, *arguments],
        7777,
    )


if __name__ == "__main__":
    raise SystemExit(main())
