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

    def test_measured_rear_boxes(self) -> None:
        # Live +$64 trace: Axel -40..-8, Adam -42..+14, Blaze -53..-5.
        self.assertGreater(PROFILES[1].rear_range_max, PROFILES[0].rear_range_max)
        self.assertGreater(PROFILES[2].rear_range_max, PROFILES[1].rear_range_max)
        # Adam pays for that reach in wind-up, not in geometry.
        self.assertGreater(PROFILES[1].rear_startup, PROFILES[2].rear_startup)
        self.assertGreater(PROFILES[2].rear_startup, PROFILES[0].rear_startup)

    def test_blaze_jump_longer_axel_shorter(self) -> None:
        self.assertGreater(PROFILES[2].jump_kick_max, PROFILES[0].jump_kick_max)
        self.assertLess(PROFILES[2].combo_bias, PROFILES[0].combo_bias)

    def test_blaze_prefers_throw_and_vault(self) -> None:
        self.assertTrue(PROFILES[2].prefer_throw)
        self.assertTrue(PROFILES[2].prefer_vault)
        self.assertEqual(PROFILES[2].grab_knees, 0)

    def test_hold_tree_uses_prefer_vault(self) -> None:
        """Adam/Blaze front hold should emit C for vault→suplex, not knee spam."""

        from sor_autoplay.agent.grabs import GrabMemory, context_from_player, decide_held

        me = MapEntity(
            kind="player",
            family="Player",
            symbol="1",
            color="#fff",
            label="P1",
            type_id=1,
            world_x=100,
            world_y=64,
            world_z=160,
            map_x=100.0,
            map_y=64.0,
            health=80,
            slot="P1",
            action_state=0x60,
            contact_ptr=0xB900,
            combat_phase=CombatPhase.HOLDING,
        )
        foe = _foe()
        foe = replace(
            foe,
            world_x=120,
            map_x=120.0,
            primary_state=0x0500,
            combat_phase=CombatPhase.GRABBED,
            attacker_ptr=0xB800,
        )
        entities = (me, foe)
        intent = decide_held(
            me,
            context_from_player(me, entities),
            GrabMemory(),
            tick=1,
            foe=foe,
            profile=PROFILES[2],
        )
        assert intent is not None
        self.assertTrue(intent.jump, intent.note)
        self.assertFalse(intent.attack, intent.note)
        self.assertIn("vault", intent.note)

    def test_hold_tree_uses_prefer_throw(self) -> None:
        """Axel (prefer_throw, no vault) throws B+back on the first pulse."""

        from sor_autoplay.agent.grabs import GrabMemory, context_from_player, decide_held

        me = MapEntity(
            kind="player",
            family="Player",
            symbol="1",
            color="#fff",
            label="P1",
            type_id=1,
            world_x=100,
            world_y=64,
            world_z=160,
            map_x=100.0,
            map_y=64.0,
            health=80,
            slot="P1",
            action_state=0x60,  # facing right (bit0 clear) → throw left
            contact_ptr=0xB900,
            combat_phase=CombatPhase.HOLDING,
        )
        foe = replace(
            _foe(),
            world_x=120,
            map_x=120.0,
            primary_state=0x0500,
            combat_phase=CombatPhase.GRABBED,
            attacker_ptr=0xB800,
        )
        entities = (me, foe)
        intent = decide_held(
            me,
            context_from_player(me, entities),
            GrabMemory(),
            tick=1,
            foe=foe,
            profile=PROFILES[0],
        )
        assert intent is not None
        self.assertTrue(intent.attack, intent.note)
        self.assertTrue(intent.left, intent.note)
        self.assertIn("throw", intent.note)

    def test_axel_rear_band_is_close_only(self) -> None:
        ax = PROFILES[0]
        self.assertEqual(engagement_band(24, 4, ax), "close")
        self.assertEqual(engagement_band(40, 4, ax), "close")

    def test_rear_only_when_behind(self) -> None:
        from sor_autoplay.agent.combat import rear_in_band

        self.assertTrue(rear_in_band(24, PROFILES[0]))
        self.assertFalse(rear_in_band(48, PROFILES[0]))
        self.assertTrue(rear_in_band(40, PROFILES[1]))
        plan = plan_for(_foe())
        # Distance alone must NOT force rear.
        self.assertNotEqual(
            attack_mix(
                plan,
                PROFILES[0],
                tick=0,
                in_range=True,
                crowd=1,
                band="close",
                lane_ok=True,
                facing_ok=True,
            ),
            "rear",
        )
        # Axel's chord is cheap (3/10/17 startup/active/recover) — take it on
        # sight when actually behind.
        self.assertEqual(
            attack_mix(
                plan,
                PROFILES[0],
                tick=0,
                in_range=True,
                crowd=1,
                band="close",
                behind=True,
            ),
            "rear",
        )

    def test_adam_does_not_auto_chord_despite_being_behind(self) -> None:
        """Adam's chord is a 21-frame startup / 39-frame recover commit for 3
        damage (rear_attack_bias=0.12, "last resort" per characters.py). Real
        play showed the agent taking it on every "behind" geometry hit
        regardless of cost; the bias field existed but was never read."""

        plan = plan_for(_foe())
        self.assertNotEqual(
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


class RearChordTimingTests(unittest.TestCase):
    """Measured B+C timeline (ai-analysis/controls-and-input.md)."""

    def _pair(self, gap: float, *, closing: bool = True) -> tuple[MapEntity, MapEntity]:
        me = replace(_foe(), kind="player", slot="P1", map_x=100.0, map_y=64.0)
        # Foe behind a right-facing player; facing_left False = walking at us.
        foe = replace(
            _foe(),
            map_x=100.0 - gap,
            map_y=64.0,
            facing_left=not closing,
        )
        return me, foe

    def test_stationary_foe_only_hit_inside_the_measured_box(self) -> None:
        from sor_autoplay.agent.combat import BODY_HALF_X, rear_hit_window

        me, foe = self._pair(40.0, closing=False)
        near, far = rear_hit_window(me, foe, PROFILES[0])
        # Axel's box is -40..-8; no closing lead when the foe stands still.
        self.assertEqual(near, PROFILES[0].rear_range_min - BODY_HALF_X)
        self.assertEqual(far, PROFILES[0].rear_range_max + BODY_HALF_X)

    def test_closing_foe_extends_the_window_by_startup_plus_active(self) -> None:
        from sor_autoplay.agent.combat import can_rear_hit, rear_hit_window

        me, foe = self._pair(60.0)
        _, far = rear_hit_window(me, foe, PROFILES[0])
        self.assertGreater(far, PROFILES[0].rear_range_max)
        self.assertTrue(can_rear_hit(me, foe, PROFILES[0], face_right=True))
        # Past the box, a foe that never walks in is never hit.
        me, still = self._pair(60.0, closing=False)
        self.assertFalse(can_rear_hit(me, still, PROFILES[0], face_right=True))

    def test_adam_never_chords_a_foe_already_on_his_back(self) -> None:
        from sor_autoplay.agent.combat import can_rear_hit

        me, foe = self._pair(14.0)
        self.assertTrue(can_rear_hit(me, foe, PROFILES[0], face_right=True))
        # 21-frame startup loses the race at contact range.
        self.assertFalse(can_rear_hit(me, foe, PROFILES[1], face_right=True))
        me, far_foe = self._pair(50.0)
        self.assertTrue(can_rear_hit(me, far_foe, PROFILES[1], face_right=True))

    def test_lane_band_matches_the_attack_box(self) -> None:
        from sor_autoplay.agent.combat import can_rear_hit

        me, foe = self._pair(24.0)
        off_lane = replace(foe, map_y=foe.map_y + 14.0)
        self.assertFalse(can_rear_hit(me, off_lane, PROFILES[0], face_right=True))

    def test_point_blank_foe_still_connects(self) -> None:
        """Axel's box starts at -8 (near = 1px); a generic 10px dead zone
        used to override the measured near bound and swallow this hit."""
        from sor_autoplay.agent.combat import can_rear_hit

        me, foe = self._pair(3.0)
        self.assertTrue(can_rear_hit(me, foe, PROFILES[0], face_right=True))


class PunchBoxTests(unittest.TestCase):
    """Measured punch attack box +$64 (facing right, Y ±8)."""

    def test_measured_outer_reach(self) -> None:
        self.assertEqual(
            [(p.punch_inner, p.punch_outer) for p in PROFILES.values()],
            [(16.0, 57.0), (8.0, 54.0), (18.0, 68.0)],
        )
        # Policy strike ranges stay inside the measured outer edge.
        for profile in PROFILES.values():
            self.assertLess(profile.strike_range, profile.punch_outer)

    def test_body_inside_the_inner_edge_is_not_punchable(self) -> None:
        from sor_autoplay.agent.combat import can_punch

        me = replace(_foe(), kind="player", slot="P1", map_x=100.0, map_y=64.0)
        for profile in PROFILES.values():
            close = replace(_foe(), map_x=100.0 + profile.punch_inner - 8.0, map_y=64.0)
            ok = replace(_foe(), map_x=100.0 + profile.punch_inner + 8.0, map_y=64.0)
            self.assertFalse(can_punch(me, close, profile, require_facing=False))
            self.assertTrue(can_punch(me, ok, profile, require_facing=False))
