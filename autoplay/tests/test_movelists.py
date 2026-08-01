"""GameFAQs-derived character move-list preferences."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.combat import engagement_band
from sor_autoplay.agent.enemies import attack_mix, plan_for
from sor_autoplay.world_map import MapEntity
from sor_autoplay.phases import CombatPhase


def _foe() -> MapEntity:
    return MapEntity(
        kind="enemy",
        family="Garcia",
        symbol="G",
        color="#fff",
        label="G",
        type_id=0x20,
        world_x=0,
        world_y=0,
        world_z=0,
        map_x=0.0,
        map_y=0.0,
        health=10,
        slot="E0",
        combat_phase=CombatPhase.NORMAL,
    )


class MoveListProfileTests(unittest.TestCase):
    def test_ids(self) -> None:
        self.assertEqual(PROFILES[0].name, "Axel")
        self.assertEqual(PROFILES[1].name, "Adam")
        self.assertEqual(PROFILES[2].name, "Blaze")

    def test_adam_rear_starts_farther_than_axel(self) -> None:
        self.assertGreater(PROFILES[1].rear_range_max, PROFILES[0].rear_range_max)
        self.assertGreater(PROFILES[1].rear_range_min, PROFILES[0].rear_range_min)

    def test_blaze_jump_longer_axel_shorter(self) -> None:
        self.assertGreater(PROFILES[2].jump_kick_max, PROFILES[0].jump_kick_max)
        self.assertLess(PROFILES[2].combo_bias, PROFILES[0].combo_bias)

    def test_blaze_prefers_throw_and_vault(self) -> None:
        self.assertTrue(PROFILES[2].prefer_throw)
        self.assertTrue(PROFILES[2].prefer_vault)
        self.assertEqual(PROFILES[2].grab_knees, 0)

    def test_axel_rear_band_is_close_only(self) -> None:
        ax = PROFILES[0]
        self.assertEqual(engagement_band(24, 4, ax), "close")
        self.assertEqual(engagement_band(40, 4, ax), "close")

    def test_rear_only_when_behind(self) -> None:
        from sor_autoplay.agent.combat import rear_in_band

        self.assertTrue(rear_in_band(24, PROFILES[0]))
        self.assertFalse(rear_in_band(48, PROFILES[0]))
        self.assertTrue(rear_in_band(48, PROFILES[1]))
        plan = plan_for(_foe())
        # Distance alone must NOT force rear.
        self.assertNotEqual(
            attack_mix(
                plan,
                PROFILES[1],
                tick=0,
                in_range=True,
                crowd=1,
                band="close",
                lane_ok=True,
                facing_ok=True,
            ),
            "rear",
        )
        self.assertEqual(
            attack_mix(
                plan,
                PROFILES[1],
                tick=0,
                in_range=True,
                crowd=1,
                band="close",
                behind=True,
            ),
            "rear",
        )

    def test_blaze_jump_reach_does_not_force_a_jump(self) -> None:
        bl = PROFILES[2]
        self.assertEqual(engagement_band(70, 4, bl), "jump")
        plan = plan_for(_foe())
        self.assertEqual(
            attack_mix(
                plan,
                bl,
                tick=1,
                in_range=False,
                crowd=1,
                band="jump",
                can_jump=True,
                lane_ok=True,
                facing_ok=True,
            ),
            "wait",
        )
        haku_plan = plan_for(replace(_foe(), family="Haku-Ro", type_id=0x25))
        self.assertEqual(
            attack_mix(
                haku_plan,
                bl,
                in_range=False,
                band="jump",
                can_jump=True,
                lane_ok=True,
                facing_ok=True,
            ),
            "jump",
        )

    def test_no_random_jump_when_out_of_range(self) -> None:
        plan = plan_for(_foe())
        # Old bug: attack_mix returned "jump" for any not-in-range case.
        for t in range(20):
            self.assertEqual(
                attack_mix(
                    plan,
                    PROFILES[0],
                    tick=t,
                    in_range=False,
                    band="approach",
                    can_jump=False,
                    lane_ok=True,
                    facing_ok=True,
                ),
                "wait",
            )


if __name__ == "__main__":
    unittest.main()
