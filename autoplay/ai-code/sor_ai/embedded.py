"""What the ``sor`` host runs in its own process (``SoRPython.cpp``).

``host`` is the ``sor_host`` module the game provides. It is handed in rather
than imported so that this package still loads anywhere else.
"""

from __future__ import annotations

import sys
import time

STOP_POLL_S = 1.0


def run(host) -> None:
    """Load the AI and stay until the game asks it to end."""

    started = time.perf_counter()
    from .ai import loop  # noqa: F401 -- the whole pipeline

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    version = ".".join(str(part) for part in sys.version_info[:3])
    host.log(f"Python {version}, AI loaded in {elapsed_ms:.0f} ms")
    while not host.wait_stop(STOP_POLL_S):
        pass
    host.log("ended")
