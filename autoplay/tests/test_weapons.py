"""ROM-backed weapon model and weapon-tree geometry."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.combat import is_weapon_upgrade, weapon_value
from sor_autoplay.agent.grabs import GrabContext, _weapon_tree
from sor_autoplay.agent import weapons as W
from sor_autoplay.phases import CombatPhase
from sor_autoplay.world_map import MapEntity


def _entity(
    *,
    kind: str = "enemy",
    map_x: float,
    map_y: float,
    slot: str = "E0",
    label: str = "Garcia",
    family: str = "Garcia",
    health: int | None = 10,
    type_id: int = 0x20,
    action_state: int = 0,
    held_type: int = 0,
    combat_phase: CombatPhase = CombatPhase.NORMAL,
) -> MapEntity:
    return MapEntity(
        kind=kind,
        family=family,
        symbol="G" if kind == "enemy" else "1",
        color="#fff",
        label=label,
        type_id=type_id,
        world_x=int(map_x),
        world_y=int(map_y),
        world_z=160,
        map_x=map_x,
        map_y=map_y,
        health=health,
        slot=slot,
        action_state=action_state,
        held_type=held_type,
        combat_phase=combat_phase,
    )


def _player(*, held: int, x: float = 100.0, y: float = 64.0, act: int = 0x30) -> MapEntity:
    return _entity(
        kind="player",
        map_x=x,
        map_y=y,
        slot="P1",
        label="P1 Axel",
        family="Player",
        type_id=1,
        action_state=act,
        held_type=held,
        combat_phase=CombatPhase.NORMAL,
    )


def _ctx(me: MapEntity) -> GrabContext:
    held = me.held_type & 0xFF
    return GrabContext(
        holding=held != 0,
        weapon=0x08 <= held <= 0x0C,
        enemy_grab=False,
        partner_grab=False,
        held_type=held,
        action_base=me.action_base,
        airborne=me.is_airborne,
        hurt=False,
    )


class WeaponMathTests(unittest.TestCase):
    def test_damage_and_hits_to_kill(self) -> None:
        self.assertEqual(W.damage_of(W.WEAPON_KNIFE), 5)
        self.assertEqual(W.damage_of(W.WEAPON_PIPE), 4)
        self.assertEqual(W.damage_of(W.WEAPON_BOTTLE), 3)
        self.assertEqual(W.damage_of(W.WEAPON_PEPPER), 2)
        self.assertEqual(W.hits_to_kill(6, W.WEAPON_KNIFE), 2)
        self.assertEqual(W.hits_to_kill(6, W.WEAPON_PIPE), 2)
        self.assertEqual(W.hits_to_kill(6, W.WEAPON_PEPPER), 3)
        self.assertEqual(W.hits_to_kill(9, W.WEAPON_KNIFE), 2)
        self.assertEqual(W.hits_to_kill(9, W.WEAPON_BOTTLE), 3)

    def test_utility_ranks_pipe_above_bottle(self) -> None:
        axel = PROFILES[0]
        self.assertGreater(
            W.weapon_utility(W.WEAPON_PIPE, axel),
            W.weapon_utility(W.WEAPON_BOTTLE, axel),
        )
        self.assertGreater(
            W.weapon_utility(W.WEAPON_KNIFE, axel),
            W.weapon_utility(W.WEAPON_BOTTLE, axel),
        )

    def test_utility_equation_bounds(self) -> None:
        for tid in W.WEAPON_TYPES:
            u = W.weapon_utility(tid)
            self.assertGreaterEqual(u, 0.0)
            self.assertLessEqual(u, 1.0)

    def test_upgrade_margin(self) -> None:
        self.assertTrue(is_weapon_upgrade(W.WEAPON_BOTTLE, W.WEAPON_PIPE, PROFILES[0]))
        self.assertFalse(is_weapon_upgrade(W.WEAPON_PIPE, W.WEAPON_BOTTLE, PROFILES[0]))

    def test_combat_reexports_weapon_value(self) -> None:
        self.assertAlmostEqual(
            weapon_value(W.WEAPON_KNIFE),
            W.weapon_utility(W.WEAPON_KNIFE),
        )


class WeaponTreeGeometryTests(unittest.TestCase):
    def test_pipe_swings_only_within_36(self) -> None:
        me = _player(held=W.WEAPON_PIPE, x=100)
        near = _entity(map_x=130, map_y=64)  # dx=30
        far = _entity(map_x=150, map_y=64)  # dx=50
        profile = PROFILES[0]
        intent = _weapon_tree(me, _ctx(me), tick=0, foe=near, profile=profile)
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertIn("swing", intent.note)

        intent_far = _weapon_tree(me, _ctx(me), tick=0, foe=far, profile=profile)
        self.assertIsNone(intent_far)

    def test_knife_throws_at_far_hittable_range(self) -> None:
        me = _player(held=W.WEAPON_KNIFE, x=100, act=0x30)
        foe = _entity(map_x=100 + 120, map_y=64, health=6)
        intent = _weapon_tree(me, _ctx(me), tick=0, foe=foe, profile=PROFILES[0])
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertIn("throw knife", intent.note)
        self.assertTrue(intent.right)
        self.assertFalse(intent.left)

    def test_knife_does_not_throw_beyond_envelope(self) -> None:
        me = _player(held=W.WEAPON_KNIFE, x=100, act=0x30)
        foe = _entity(map_x=100 + 200, map_y=64)
        intent = _weapon_tree(me, _ctx(me), tick=0, foe=foe, profile=PROFILES[0])
        self.assertIsNone(intent)

    def test_knife_faces_before_throwing_wrong_way(self) -> None:
        me = _player(held=W.WEAPON_KNIFE, x=100, act=0x30)
        foe = _entity(map_x=40, map_y=64)  # dx=-60
        intent = _weapon_tree(me, _ctx(me), tick=0, foe=foe, profile=PROFILES[0])
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertFalse(intent.attack)
        self.assertTrue(intent.left)
        self.assertIn("face", intent.note)

    def test_bottle_not_thrown_at_mid_range(self) -> None:
        me = _player(held=W.WEAPON_BOTTLE, x=100, act=0x30)
        mid = _entity(map_x=100 + 70, map_y=64)
        intent = _weapon_tree(me, _ctx(me), tick=0, foe=mid, profile=PROFILES[0])
        self.assertIsNone(intent)
        close = _entity(map_x=100 + 20, map_y=64)
        intent_c = _weapon_tree(me, _ctx(me), tick=0, foe=close, profile=PROFILES[0])
        self.assertIsNotNone(intent_c)
        assert intent_c is not None
        self.assertTrue(intent_c.attack)
        self.assertIn("bottle", intent_c.note)

    def test_lane_filter(self) -> None:
        me = _player(held=W.WEAPON_KNIFE, x=100, act=0x30)
        off = _entity(map_x=160, map_y=64 + 20)
        self.assertIsNone(
            _weapon_tree(me, _ctx(me), tick=0, foe=off, profile=PROFILES[0])
        )

    def test_pepper_notes_stun_frames(self) -> None:
        me = _player(held=W.WEAPON_PEPPER, x=100, act=0x30)
        foe = _entity(map_x=150, map_y=64)
        intent = _weapon_tree(me, _ctx(me), tick=0, foe=foe, profile=PROFILES[0])
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertIn("160", intent.note)


if __name__ == "__main__":
    unittest.main()
