"""``DebugScenario``'s sweeps, and ``--kill-until-mr-x``'s end.

Round 8 is long and runs the boss rush before Mr. X, so reaching him is the
host's ``X`` hotkey pressed twice a second -- every enemy and every boss dies
-- and then nothing at all once his scene is up: the Garcias sent into his
fight are his helpers (user: the flag must not kill "esses ajudantes nem o Mr
X"). The host refuses on its own once types ``$33``-``$35`` are in the object
table; these pin the client side, which stops asking.
"""

import unittest
from types import SimpleNamespace

from sor_autoplay.debug_scenario import DebugScenario


class _Client:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def trigger_option_hotkey(self, key: str) -> None:
        self.keys.append(key)


def _snapshot(*types: int, offer: int = 0) -> SimpleNamespace:
    entities = [SimpleNamespace(type_id=t) for t in types]
    return SimpleNamespace(mr_x_offer_flag=offer, world_map=SimpleNamespace(entities=entities))


class KillUntilMrXTests(unittest.TestCase):
    def test_it_presses_x_and_no_family_key(self) -> None:
        scenario = DebugScenario(start_level=8, kill_until_mr_x=True)
        client = _Client()
        self.assertTrue(scenario.sweep_other_families(client, force=True))
        self.assertEqual(client.keys, ["X"])
        # Rate-limited like the family sweep.
        self.assertFalse(scenario.sweep_other_families(client))

    def test_it_stops_for_good_once_mr_x_is_up(self) -> None:
        scenario = DebugScenario(kill_until_mr_x=True)
        client = _Client()
        scenario.note_snapshot(_snapshot(0x20, 0x57))  # the rush: keep going
        self.assertTrue(scenario.sweep_other_families(client, force=True))
        scenario.note_snapshot(_snapshot(0x35, 0x20))
        self.assertFalse(scenario.sweep_other_families(client, force=True))
        scenario.note_snapshot(_snapshot())  # and it stays stopped
        self.assertFalse(scenario.sweep_other_families(client, force=True))
        self.assertEqual(client.keys, ["X"])

    def test_his_offer_ends_it_too(self) -> None:
        scenario = DebugScenario(kill_until_mr_x=True)
        scenario.note_snapshot(_snapshot(offer=1))
        self.assertFalse(scenario.sweep_other_families(_Client(), force=True))

    def test_no_other_sweep_alongside(self) -> None:
        # Either would go on killing his Garcias.
        with self.assertRaises(ValueError):
            DebugScenario(kill_until_mr_x=True, kill_street_enemies=True)
        with self.assertRaises(ValueError):
            DebugScenario(kill_until_mr_x=True, only_enemy="garcia")

    def test_the_street_sweep_is_unchanged(self) -> None:
        scenario = DebugScenario(kill_street_enemies=True)
        client = _Client()
        scenario.note_snapshot(_snapshot(0x35))
        self.assertTrue(scenario.sweep_other_families(client, force=True))
        self.assertEqual(sorted(client.keys), ["B", "G", "J", "N", "U"])


if __name__ == "__main__":
    unittest.main()
