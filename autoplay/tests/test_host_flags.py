"""Host mode flags (``GET_FLAGS``) and each player's scheme: decoding and when
``ObserverApp`` reads them."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "MegaDriveEnvironment" / "python" / "src"))

from megadrive_remote import ServerError  # noqa: E402
from megadrive_remote.exceptions import ErrorCode  # noqa: E402

from sor_autoplay.app import HOST_FLAGS_REFRESH_S, ObserverApp  # noqa: E402
from sor_autoplay.host_flags import (  # noqa: E402
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
    """GET_FLAGS plus SoRClient's scheme reads."""

    def ai_assist(self):
        return False

    def __init__(self, flags: bytes | Exception, enhanced: dict[int, bool] | None = None) -> None:
        self.flags = flags
        self.enhanced_by_player = dict(enhanced or {1: False, 2: False})
        self.reads = 0
        self.scheme_reads = 0

    def get_flags(self) -> bytes:
        self.reads += 1
        if isinstance(self.flags, Exception):
            raise self.flags
        return self.flags

    def refresh_schemes(self) -> None:
        self.scheme_reads += 1

    def enhanced(self, player: int) -> bool:
        return self.enhanced_by_player[player]


class DecodeTests(unittest.TestCase):
    def test_defaults_are_off(self):
        self.assertEqual(decode_host_modes(bytes(128)), HostModes(False))

    def test_widescreen_is_its_own_bit(self):
        self.assertEqual(decode_host_modes(_flags(FLAG_WIDESCREEN)), HostModes(True))
        # Flag 1 (the old --altControls) means nothing any more.
        self.assertEqual(decode_host_modes(_flags(1)), HostModes(False))

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
        self.assertEqual(app.six_button, {1: False, 2: False})

    def test_widescreen_follows_the_host_while_connected(self):
        # OPTIONS > VIDEO can change it under a running host.
        app = self._app()
        client = _Client(_flags())
        app._read_widescreen(client)
        self.assertFalse(app.widescreen)
        client.flags = _flags(FLAG_WIDESCREEN)
        app._refresh_widescreen(client)
        self.assertFalse(app.widescreen)  # not due yet
        self.assertEqual(client.reads, 1)
        app._host_flags_read_at -= HOST_FLAGS_REFRESH_S
        app._refresh_widescreen(client)
        self.assertTrue(app.widescreen)
        self.assertEqual(client.reads, 2)
        self.assertEqual(client.scheme_reads, 0)

    def test_schemes_wait_for_the_ai(self):
        app = self._app()
        client = _Client(_flags(), {1: True, 2: False})
        app._read_widescreen(client)
        app._refresh_button_mode(client)
        self.assertEqual(client.scheme_reads, 0)
        self.assertFalse(app.six_button[1])

        app.set_agent_enabled(1, True)
        app._refresh_button_mode(client)
        self.assertEqual(client.scheme_reads, 1)
        self.assertTrue(app.six_button[1])

    def test_each_agent_loop_gets_its_own_players_scheme(self):
        app = self._app(agent_p2=True)
        app._refresh_button_mode(_Client(_flags(), {1: False, 2: True}))
        self.assertFalse(app._agent_loops[1].six_button)
        self.assertTrue(app._agent_loops[2].six_button)

    def test_schemes_are_read_once_per_turn_on(self):
        app = self._app(agent_p1=True)
        client = _Client(_flags())
        app._read_widescreen(client)
        app._refresh_button_mode(client)
        app._refresh_button_mode(client)
        self.assertEqual(client.scheme_reads, 1)
        client.enhanced_by_player[1] = True
        app.set_agent_enabled(1, False)
        app.set_agent_enabled(1, True)
        app._refresh_button_mode(client)
        self.assertTrue(app.six_button[1])

    def test_a_host_without_get_flags_keeps_narrow(self):
        app = self._app(agent_p1=True)
        client = _Client(ServerError(ErrorCode.UNKNOWN_COMMAND, "unknown command", command=7, request_id=1))
        app._read_widescreen(client)
        self.assertFalse(app.widescreen)


if __name__ == "__main__":
    unittest.main()
