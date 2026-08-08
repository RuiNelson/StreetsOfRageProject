"""Symbolic AI that plays Streets of Rage through controller input only.

Per ``AI.md``: this package may read RAM (via the snapshot already fetched
for the HUD) but must never write to RAM. All actions are issued through
:mod:`sor_autoplay.ai.gamepad`, which only calls the remote client's
``hold_buttons`` / ``press_buttons`` / ``release_buttons``. Nothing under
this package may import ``write_memory`` or ``write_value``.
"""

from __future__ import annotations
