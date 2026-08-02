"""Mathematical jump-kick solver unit tests (ROM physics)."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.enemies import attack_mix, plan_for
from sor_autoplay.agent.jump_kick import (
    CROUCH_FRAMES,
    VZ0,
    can_jump_kick_solved,
    damage_on_kick_frame,
    solve_jump_kick,
)
from sor_autoplay.phases import CombatPhase
from sor_autoplay.world_map import MapEntity


def _e(**kwargs) -> MapEntity:
    d = dict(
        kind="enemy",
        family="Garcia",
        symbol="G",
        color="#fff",
        label="Garcia",
        type_id=0x20,
        world_x=100,
        world_y=64,
        world_z=0xA0,
        map_x=100.0,
        map_y=64.0,
        health=10,
        slot="E0",
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
    )
    d.update(kwargs)
    if "map_x" in kwargs and "world_x" not in kwargs:
        d["world_x"] = int(kwargs["map_x"])
        d["map_x"] = float(kwargs["map_x"])
    if "map_y" in kwargs and "world_y" not in kwargs:
        d["world_y"] = int(kwargs["map_y"])
        d["map_y"] = float(kwargs["map_y"])
    if "world_x" in kwargs and "map_x" not in kwargs:
        d["map_x"] = float(kwargs["world_x"])
    if "world_y" in kwargs and "map_y" not in kwargs:
        d["map_y"] = float(kwargs["world_y"])
    return MapEntity(**d)  # type: ignore[arg-type]


class JumpKickPhysicsTests(unittest.TestCase):
    def test_crouch_and_launch_constants(self) -> None:
        self.assertEqual(CROUCH_FRAMES, 5)
        self.assertEqual(VZ0[0], -7.5)
        self.assertEqual(VZ0[1], -8.5)
        self.assertEqual(VZ0[2], -9.5)

    def test_axel_damage_constant(self) -> None:
        for age in range(0, 12):
            self.assertEqual(damage_on_kick_frame(0, age), 3)

    def test_blaze_damage_window(self) -> None:
        # f0,f1 zero; f2+ damage 2 (3-frame durations).
        self.assertEqual(damage_on_kick_frame(2, 0), 0)
        self.assertEqual(damage_on_kick_frame(2, 2), 0)
        self.assertEqual(damage_on_kick_frame(2, 3), 0)
        self.assertEqual(damage_on_kick_frame(2, 6), 2)
        self.assertEqual(damage_on_kick_frame(2, 9), 2)

    def test_single_enemy_mid_range_blaze(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            world_x=100,
            world_y=64,
            world_z=0xA0,
            type_id=1,
        )
        foe = _e(world_x=145, world_y=64, world_z=0xA0, slot="E0", label="G1")
        ok, plan = can_jump_kick_solved(
            me, foe, PROFILES[2], entities=(foe,), loose_lane=False
        )
        self.assertTrue(ok)
        assert plan is not None
        self.assertTrue(plan.primary_hit)
        self.assertGreaterEqual(plan.hit_count, 1)
        self.assertGreater(plan.range_x, 40.0)

    def test_multi_enemy_pack_scores_higher(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            world_x=100,
            world_y=64,
            world_z=0xA0,
            type_id=1,
        )
        e1 = _e(world_x=140, world_y=64, world_z=0xA0, slot="E0", label="G1")
        e2 = _e(world_x=155, world_y=66, world_z=0xA0, slot="E1", label="G2")
        e3 = _e(world_x=168, world_y=62, world_z=0xA0, slot="E2", label="G3")
        single = solve_jump_kick(me, (e1,), PROFILES[0], primary=e1)
        pack = solve_jump_kick(me, (e1, e2, e3), PROFILES[0], primary=e1)
        assert single is not None and pack is not None
        self.assertGreaterEqual(pack.hit_count, 2)
        self.assertGreater(pack.score, single.score)
        self.assertTrue(pack.multi_hit)

    def test_off_lane_not_hit(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            world_x=100,
            world_y=64,
            world_z=0xA0,
            type_id=1,
        )
        foe = _e(world_x=145, world_y=100, world_z=0xA0, slot="E0")
        ok, plan = can_jump_kick_solved(
            me, foe, PROFILES[2], entities=(foe,)
        )
        self.assertFalse(ok)
        if plan is not None:
            self.assertFalse(plan.primary_hit)

    def test_attack_mix_prefers_multi_jump(self) -> None:
        plan = plan_for(_e(type_id=0x20, family="Garcia"))
        mix = attack_mix(
            plan,
            PROFILES[0],
            in_range=False,
            crowd=3,
            phase_name="normal",
            band="jump",
            lane_ok=True,
            facing_ok=True,
            can_jump=True,
            jump_hits=3,
            jump_score=4.0,
        )
        self.assertEqual(mix, "jump")


if __name__ == "__main__":
    unittest.main()
