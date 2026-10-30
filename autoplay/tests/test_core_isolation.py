"""``sor_ai`` must load with no HUD, no sockets and no remote client.

The ``sor`` host runs this package in its own process, on a Python that has
neither Tk nor ``megadrive_remote``. A fresh interpreter, because this one has
already imported those.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

AI_CODE = Path(__file__).resolve().parents[1] / "ai-code"

SCRIPT = """
import importlib, pkgutil, sys

BLOCKED = {"tkinter", "_tkinter", "socket", "_socket", "megadrive_remote", "sor_autoplay"}


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] in BLOCKED:
            raise ImportError(f"sor_ai must not import {name}")
        return None


sys.meta_path.insert(0, Blocker())
sys.path.insert(0, sys.argv[1])
import sor_ai

for module in pkgutil.walk_packages(sor_ai.__path__, "sor_ai."):
    importlib.import_module(module.name)
"""


class CoreIsolationTests(unittest.TestCase):
    def test_every_module_imports_without_hud_sockets_or_client(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT, str(AI_CODE)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
