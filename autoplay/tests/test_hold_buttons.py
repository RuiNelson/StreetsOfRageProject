"""Smoke tests for sticky hold_buttons client API (protocol pack only)."""

from __future__ import annotations

import unittest
from struct import unpack
from unittest.mock import MagicMock

from megadrive_remote.client import MegaDriveClient
from megadrive_remote._protocol import Command


class HoldButtonsClientTests(unittest.TestCase):
    def test_hold_buttons_sends_command_14(self) -> None:
        client = MegaDriveClient.__new__(MegaDriveClient)
        client._request = MagicMock()
        MegaDriveClient.hold_buttons(client, player1=0x0008, player2=0x0004)
        client._request.assert_called_once()
        cmd, payload = client._request.call_args[0][0], client._request.call_args[0][1]
        self.assertEqual(cmd, Command.HOLD_BUTTONS)
        p1, p2 = unpack(">HH", payload)
        self.assertEqual(p1, 0x0008)  # RIGHT
        self.assertEqual(p2, 0x0004)  # LEFT


if __name__ == "__main__":
    unittest.main()
