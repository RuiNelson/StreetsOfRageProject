"""Smoke tests for sticky hold_buttons client API and ObserverApp lifecycle."""

from __future__ import annotations

import threading
import unittest
from struct import unpack
from unittest.mock import MagicMock

from megadrive_remote.client import MegaDriveClient
from megadrive_remote._protocol import Command
from sor_autoplay.app import ObserverApp


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


class StopClientHandoffTests(unittest.TestCase):
    """stop() must clear self._client under the same lock the poll thread
    uses, and never close a client twice (regression: unlocked read of
    self._client raced the poll thread's own close/None handling)."""

    def test_stop_closes_client_exactly_once_and_clears_it(self) -> None:
        app = ObserverApp.__new__(ObserverApp)
        app._stop = threading.Event()
        app._lock = threading.Lock()
        app._client = MagicMock()
        client = app._client

        app.stop()

        client.close.assert_called_once()
        self.assertIsNone(app._client)
        self.assertTrue(app._stop.is_set())

    def test_stop_on_already_clientless_app_is_a_noop(self) -> None:
        app = ObserverApp.__new__(ObserverApp)
        app._stop = threading.Event()
        app._lock = threading.Lock()
        app._client = None

        app.stop()  # must not raise

        self.assertIsNone(app._client)


if __name__ == "__main__":
    unittest.main()
