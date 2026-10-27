"""Host mode flags (``GET_FLAGS``): decoding and when ``ObserverApp`` reads them."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "MegaDriveEnvironment" / "python" / "src"))

from megadrive_remote import ServerError  # noqa: E402
from megadrive_remote.exceptions import ErrorCode  # noqa: E402

from sor_autoplay.app import ObserverApp  # noqa: E402
from sor_autoplay.host_flags import (  # noqa: E402
    FLAG_SIX_BUTTON,
    FLAG_WIDESCREEN,
    HostModes,
    decode_host_modes,
)


def _flags(*indices: int) -> bytes:
    data = bytearray(128)
    for index in indices:
        data[index // 8] |= 1 << (index % 8)
    return bytes(data)


class _Client:
    def __init__(self, flags: bytes | Exception) -> None:
        self.flags = flags
        self.reads = 0

    def get_flags(self) -> bytes:
        self.reads += 1
        if isinstance(self.flags, Exception):
            raise self.flags
        return self.flags


class DecodeTests(unittest.TestCase):
    def test_defaults_are_off(self):
        self.assertEqual(decode_host_modes(bytes(128)), HostModes(False, False))

    def test_each_flag_is_its_own_bit(self):
        self.assertEqual(decode_host_modes(_flags(FLAG_WIDESCREEN)), HostModes(True, False))
        self.assertEqual(decode_host_modes(_flags(FLAG_SIX_BUTTON)), HostModes(False, True))
        self.assertEqual(
            decode_host_modes(_flags(FLAG_WIDESCREEN, FLAG_SIX_BUTTON)), HostModes(True, True)
        )

    def test_wrong_size_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_host_modes(bytes(127))


class ObserverAppModeTests(unittest.TestCase):
    def _app(self, **kwargs) -> ObserverApp:
        return ObserverApp(host="127.0.0.1", port=0, **kwargs)

    def test_widescreen_is_read_on_connect(self):
        app = self._app()
        client = _Client(_flags(FLAG_WIDESCREEN))
        app._read_widescreen(client)
        self.assertTrue(app.widescreen)
        self.assertFalse(app.six_button)

    def test_buttons_wait_for_the_ai(self):
        app = self._app()
        client = _Client(_flags(FLAG_SIX_BUTTON))
        app._read_widescreen(client)
        app._refresh_button_mode(client)
        self.assertFalse(app.six_button)
        self.assertEqual(client.reads, 1)  # only the connect read

        app.set_agent_enabled(1, True)
        app._refresh_button_mode(client)
        self.assertTrue(app.six_button)
        self.assertEqual(client.reads, 2)

    def test_the_layout_reaches_both_agent_loops(self):
        app = self._app(agent_p2=True)
        app._refresh_button_mode(_Client(_flags(FLAG_SIX_BUTTON)))
        self.assertTrue(all(loop.six_button for loop in app._agent_loops.values()))

    def test_buttons_are_read_once_per_turn_on(self):
        app = self._app(agent_p1=True)
        client = _Client(_flags())
        app._read_widescreen(client)
        app._refresh_button_mode(client)
        app._refresh_button_mode(client)
        self.assertEqual(client.reads, 2)
        client.flags = _flags(FLAG_SIX_BUTTON)
        app.set_agent_enabled(1, False)
        app.set_agent_enabled(1, True)
        app._refresh_button_mode(client)
        self.assertTrue(app.six_button)

    def test_a_host_without_the_command_keeps_the_defaults(self):
        app = self._app(agent_p1=True)
        client = _Client(ServerError(ErrorCode.UNKNOWN_COMMAND, "unknown command", command=7, request_id=1))
        app._read_widescreen(client)
        app._refresh_button_mode(client)
        self.assertFalse(app.widescreen)
        self.assertFalse(app.six_button)


if __name__ == "__main__":
    unittest.main()
