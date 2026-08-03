"""On-screen targeting, hit geometry, and face-then-hit behaviour."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.combat import (
    can_collect_pickup,
    can_jump_kick,
    can_punch,
    can_queue_normal_combo,
    closest_behind,
    enemy_attack_committed,
    engagement_band,
    face_intent_dirs,
    facing_toward,
    is_on_screen,
    player_facing_left,
    player_airborne_action,
    player_can_start_ground_action,
    select_target,
)
from sor_autoplay.agent.enemies import attack_mix, plan_for
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.memory_map import MAX_HEALTH, OBJ_CHARACTER_ID, OBJ_HEALTH, OBJ_POS_X, OBJ_POS_Y, OBJ_TYPE
from sor_autoplay.phases import CombatPhase
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import MapEntity, WorldMap  # noqa: F401 — MapEntity used in breakable test


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
        world_z=0,
        map_x=100.0,
        map_y=64.0,
        health=10,
        slot="E0",
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,  # even = face right
    )
    d.update(kwargs)
    if "map_x" in kwargs and "world_x" not in kwargs:
        d["world_x"] = int(kwargs["map_x"])
    if "map_y" in kwargs and "world_y" not in kwargs:
        d["world_y"] = int(kwargs["map_y"])
    return MapEntity(**d)  # type: ignore[arg-type]


class ScreenAndBandTests(unittest.TestCase):
    def test_off_screen_not_selected(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, type_id=1)
        far = _e(map_x=500, label="Off", slot="E0")  # two screens ahead
        near = _e(map_x=140, label="On", slot="E1")
        choice = select_target(me, (far, near), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "On")
        self.assertFalse(is_on_screen(far, soft=True))

    def test_actor_beyond_camera_edge_is_not_selected(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, type_id=1)
        waiting = _e(map_x=321, label="Waiting", slot="E0")
        self.assertTrue(is_on_screen(waiting, soft=True))  # ROM activation margin
        self.assertFalse(is_on_screen(waiting))
        self.assertIsNone(select_target(me, (waiting,), PROFILES[0], my_seat=1))

    def test_jump_band(self) -> None:
        self.assertEqual(engagement_band(65, 4, PROFILES[1]), "jump")
        self.assertEqual(engagement_band(20, 4, PROFILES[0]), "close")
        self.assertEqual(engagement_band(120, 4, PROFILES[0]), "far")

    def test_off_lane_is_not_close(self) -> None:
        # |dy| > 12 must not count as close — air-punch prevention.
        self.assertEqual(engagement_band(20, 20, PROFILES[0]), "approach")

    def test_attack_mix_jump_only_when_can_jump(self) -> None:
        plan = plan_for(_e())
        self.assertEqual(
            attack_mix(
                plan,
                PROFILES[0],
                tick=0,
                in_range=False,
                crowd=1,
                band="jump",
                can_jump=False,
            ),
            "wait",
        )
        # Reach alone is not a tactical reason to jump.
        self.assertEqual(
            attack_mix(
                plan,
                PROFILES[2],
                tick=0,
                in_range=False,
                crowd=1,
                band="jump",
                can_jump=True,
                lane_ok=True,
                facing_ok=True,
            ),
            "wait",
        )
        haku = plan_for(_e(family="Haku-Ro", type_id=0x25))
        self.assertEqual(
            attack_mix(
                haku,
                PROFILES[2],
                in_range=False,
                band="jump",
                can_jump=True,
                lane_ok=True,
                facing_ok=True,
            ),
            "jump",
        )

    def test_attack_mix_never_punches_off_lane(self) -> None:
        plan = plan_for(_e())
        self.assertEqual(
            attack_mix(
                plan,
                PROFILES[0],
                in_range=True,
                band="close",
                lane_ok=False,
                facing_ok=True,
            ),
            "wait",
        )

    def test_attack_mix_rear_when_behind(self) -> None:
        plan = plan_for(_e())
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

    def test_closest_behind(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, type_id=1)
        back = _e(map_x=70, label="Back", slot="E0")
        front = _e(map_x=130, label="Front", slot="E1")
        # Facing right → behind is left.
        hit = closest_behind(me, (back, front), face_right=True)
        assert hit is not None
        self.assertEqual(hit.label, "Back")


class GeometryTests(unittest.TestCase):
    def test_player_facing_bit0(self) -> None:
        right = _e(kind="player", family="Player", slot="P1", action_state=0x02)
        left = _e(kind="player", family="Player", slot="P1", action_state=0x03)
        self.assertFalse(player_facing_left(right))
        self.assertTrue(player_facing_left(left))

    def test_can_punch_requires_lane_and_range(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            action_state=0x02,
            type_id=1,
        )
        near = _e(map_x=122, map_y=64)  # within Axel's measured strike range
        off_lane = _e(map_x=122, map_y=90)
        far = _e(map_x=160, map_y=64)
        self.assertTrue(can_punch(me, near, PROFILES[0], require_facing=True))
        self.assertFalse(can_punch(me, off_lane, PROFILES[0], require_facing=False))
        self.assertFalse(can_punch(me, far, PROFILES[0], require_facing=False))

    def test_can_punch_requires_facing(self) -> None:
        # Face right (even action) but foe on the left.
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            action_state=0x02,
            type_id=1,
        )
        left_foe = _e(map_x=82, map_y=64)
        self.assertFalse(facing_toward(me, left_foe))
        self.assertFalse(can_punch(me, left_foe, PROFILES[0], require_facing=True))
        self.assertTrue(can_punch(me, left_foe, PROFILES[0], require_facing=False))

    def test_face_intent_always_picks_a_side(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, action_state=0x02)
        foe = _e(map_x=120)
        fl, fr = face_intent_dirs(me, foe)
        self.assertTrue(fr and not fl)
        foe_l = _e(map_x=80)
        fl, fr = face_intent_dirs(me, foe_l)
        self.assertTrue(fl and not fr)

    def test_jump_kick_window(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64)
        mid = _e(map_x=145, map_y=64)
        self.assertTrue(can_jump_kick(me, mid, PROFILES[2]))  # Blaze long jump
        off = _e(map_x=145, map_y=90)
        self.assertFalse(can_jump_kick(me, off, PROFILES[2]))

    def test_held_weapon_ground_and_jump_action_families(self) -> None:
        ready = _e(kind="player", family="Player", slot="P1", action_state=0x32)
        airborne = _e(kind="player", family="Player", slot="P1", action_state=0x3E)
        self.assertTrue(player_can_start_ground_action(ready))
        self.assertFalse(player_airborne_action(ready))
        self.assertTrue(player_airborne_action(airborne))
        self.assertTrue(airborne.is_airborne)

    def test_combo_queue_uses_rom_pending_flag(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            action_state=0x18,
            action_flags=0,
            type_id=1,
        )
        foe = _e(map_x=128)
        self.assertTrue(can_queue_normal_combo(me, foe, PROFILES[0]))
        pending = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            action_state=0x18,
            action_flags=0x20,
            type_id=1,
        )
        self.assertFalse(can_queue_normal_combo(pending, foe, PROFILES[0]))

    def test_pickup_uses_safe_three_axis_rom_box(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            world_x=100,
            world_y=64,
            world_z=160,
        )
        safe = _e(kind="pickup", world_x=116, world_y=76, world_z=166)
        one_pixel_too_far = _e(kind="pickup", world_x=121, world_y=64, world_z=160)
        still_falling = _e(kind="weapon", world_x=110, world_y=64, world_z=167)
        self.assertTrue(can_collect_pickup(me, safe))
        self.assertFalse(can_collect_pickup(me, one_pixel_too_far))
        self.assertFalse(can_collect_pickup(me, still_falling))

    def test_committed_attack_is_recognized_inside_reaction_distance(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            world_x=100,
            world_y=64,
            map_x=100,
            map_y=64,
        )
        foe = _e(
            type_id=0x22,
            world_x=170,
            world_y=64,
            map_x=170,
            map_y=64,
            combat_phase=CombatPhase.CHARGE,
        )
        self.assertTrue(enemy_attack_committed(me, foe))


class PolicyAggressionTests(unittest.TestCase):
    def _snap(
        self,
        entities: tuple[MapEntity, ...],
        *,
        char_id: int = 0,
        level: int = 0,
    ):
        from dataclasses import replace

        def put_u8(b: bytearray, o: int, v: int) -> None:
            b[o] = v & 0xFF

        def put_u16(b: bytearray, o: int, v: int) -> None:
            b[o : o + 2] = (v & 0xFFFF).to_bytes(2, "big")

        g, t, o = bytearray(0x40), bytearray(4), bytearray(0x100)
        put_u16(g, 0x00, 0x0016)
        put_u16(g, 0x02, level)
        put_u8(g, 0x18, 0x01)
        put_u8(g, 0x1E, char_id)
        put_u8(g, 0x20, 0x03)
        put_u8(g, 0x21, 0x02)
        put_u16(t, 0, 0x0040)
        put_u8(o, OBJ_TYPE, 0x01)
        put_u16(o, OBJ_HEALTH, MAX_HEALTH)
        put_u8(o, OBJ_CHARACTER_ID, char_id)
        put_u16(o, OBJ_POS_X, 100)
        put_u16(o, OBJ_POS_Y, 0x40)
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(g), timer_block=bytes(t), objects_block=bytes(o)
        )
        world = WorldMap(
            camera_x=0,
            camera_y=0,
            camera_left=0.0,
            camera_right=320.0,
            camera_top=0.0,
            camera_bottom=112.0,
            view_left=-40.0,
            view_right=360.0,
            view_top=-16.0,
            view_bottom=128.0,
            entities=entities,
        )
        return replace(snap, world_map=world)

    def test_rear_attacks_basic_enemy_on_back_arc(self) -> None:
        # A sole foe on the rear arc uses B+C; do not turn-and-punch into it.
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(map_x=82, world_x=82, map_y=64, label="Lefty")
        snap = self._snap((p1, foe))
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertTrue(
            "rear" in d.p1_note or "back atk" in d.p1_note,
            d.p1_note,
        )
        self.assertEqual(d.p1_mask & 0x60, 0x60, msg=hex(d.p1_mask))

    def test_punches_when_facing_and_in_range(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,  # face right
        )
        foe = _e(map_x=124, world_x=124, map_y=64, label="Garcia")
        snap = self._snap((p1, foe))
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertTrue(d.p1_mask & 0x20, msg=f"expected attack: {d.p1_note}")
        self.assertTrue(d.p1_mask & 0x08, msg=f"expected RIGHT face: {d.p1_mask:#x}")
        self.assertTrue(
            "punch" in d.p1_note or "intercept" in d.p1_note,
            d.p1_note,
        )

    def test_does_not_park_chest_to_chest(self) -> None:
        """Stand goal stays near approach_offset, not body-grab range."""
        from sor_autoplay.agent.policy import _stand_point
        from sor_autoplay.agent.combat import TargetChoice
        from sor_autoplay.agent.enemies import plan_for

        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
        )
        foe = _e(map_x=140, world_x=140, map_y=64, label="Garcia")
        choice = TargetChoice(
            entity=foe, score=0, dx=40, dy=0, dist=40, plan=plan_for(foe)
        )
        sx, sy = _stand_point(me, choice, PROFILES[0], low_health=False)
        gap = abs(sx - foe.world_x)
        self.assertGreaterEqual(gap, 22.0, msg=f"stand gap {gap} too close")
        self.assertLessEqual(gap, PROFILES[0].strike_range)
        self.assertEqual(sy, float(foe.world_y))

    def test_armed_stand_keeps_weapon_reach(self) -> None:
        """Knife stand-off is deep in the stab cone, not unarmed punch range."""
        from sor_autoplay.agent.policy import _stand_point
        from sor_autoplay.agent.combat import TargetChoice
        from sor_autoplay.agent.enemies import plan_for
        from sor_autoplay.agent import weapons as W

        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            held_type=W.WEAPON_KNIFE,
        )
        foe = _e(map_x=200, world_x=200, map_y=64, label="Garcia")
        choice = TargetChoice(
            entity=foe, score=0, dx=100, dy=0, dist=100, plan=plan_for(foe)
        )
        sx, sy = _stand_point(me, choice, PROFILES[0], low_health=False)
        gap = abs(sx - foe.world_x)
        self.assertGreaterEqual(gap, W.WEAPON_APPROACH_DX[W.WEAPON_KNIFE] - 1.0)
        self.assertGreater(gap, PROFILES[0].strike_range)
        self.assertEqual(sy, float(foe.world_y))

    def test_approach_does_not_stop_just_outside_strike_range(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        # Axel's measured safe strike range is 52. The stand goal/tolerance
        # must not consider dx=56 "arrived" outside that hit box.
        foe = _e(map_x=156, world_x=156, map_y=64, label="Garcia")
        d = decide_actions(
            self._snap((p1, foe)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertTrue(d.p1_mask & 0x08, d.p1_note)
        self.assertNotIn("walk idle", d.p1_note)

    def test_walks_inside_pickup_box_before_pressing_b(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            world_z=160,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        apple = _e(
            kind="pickup",
            family="Score",
            slot="I0",
            label="Apple",
            type_id=0x3F,
            map_x=121,
            world_x=121,
            map_y=64,
            world_y=64,
            world_z=160,
            health=None,
        )
        far = decide_actions(
            self._snap((p1, apple)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertFalse(far.p1_mask & 0x20, far.p1_note)
        self.assertTrue(far.p1_mask & 0x08, far.p1_note)
        self.assertIn("loot", far.p1_note)

        close_apple = _e(
            kind="pickup",
            family="Score",
            slot="I0",
            label="Apple",
            type_id=0x3F,
            map_x=116,
            world_x=116,
            map_y=64,
            world_y=64,
            world_z=160,
            health=None,
        )
        close = decide_actions(
            self._snap((p1, close_apple)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertTrue(close.p1_mask & 0x20, close.p1_note)

    def test_does_not_press_pickup_during_reaction_state(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            world_z=160,
            type_id=1,
            label="P1",
            action_state=0x74,
        )
        apple = _e(
            kind="pickup",
            family="Score",
            slot="I0",
            label="Apple",
            type_id=0x3F,
            map_x=110,
            world_x=110,
            map_y=64,
            world_y=64,
            world_z=160,
            health=None,
        )
        decision = decide_actions(
            self._snap((p1, apple)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertEqual(decision.p1_mask, 0, decision.p1_note)
        self.assertIn("await loot", decision.p1_note)

    def test_preemptively_punches_round1_garcia_windup(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(
            type_id=0x22,
            map_x=170,
            world_x=170,
            map_y=64,
            world_y=64,
            label="Garcia",
            primary_state=0x0901,
            action_state=0x09,
            combat_phase=CombatPhase.CHARGE,
            target_ptr=0xB800,
        )
        decision = decide_actions(
            self._snap((p1, foe)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertIn("interrupt", decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x20, decision.p1_note)
        self.assertFalse(decision.p1_mask & 0x40, decision.p1_note)

    def test_escapes_enemy_lane_during_garcia_windup(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(
            type_id=0x22,
            map_x=170,
            world_x=170,
            map_y=84,
            world_y=84,
            label="Garcia",
            primary_state=0x0901,
            action_state=0x09,
            combat_phase=CombatPhase.CHARGE,
            target_ptr=0xB800,
        )
        decision = decide_actions(
            self._snap((p1, foe)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertTrue(decision.p1_mask & 0x01, decision.p1_note)
        self.assertFalse(decision.p1_mask & 0x20, decision.p1_note)
        self.assertIn("escape lane", decision.p1_note)

    def test_retreats_horizontally_when_lane_escape_hits_stage_edge(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=2,
            world_y=2,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(
            type_id=0x24,
            family="Signal",
            map_x=140,
            world_x=140,
            map_y=22,
            world_y=22,
            label="Signal",
            primary_state=0x0901,
            action_state=0x09,
            combat_phase=CombatPhase.ATTACKING,
            target_ptr=0xB800,
        )
        decision = decide_actions(
            self._snap((p1, foe)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertEqual(decision.p1_mask & 0x0F, 0x04, decision.p1_note)
        self.assertIn("retreat edge", decision.p1_note)

    def test_turns_and_interrupts_in_one_decision(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(
            type_id=0x22,
            map_x=45,
            world_x=45,
            map_y=64,
            world_y=64,
            label="Garcia",
            primary_state=0x0A01,
            action_state=0x0A,
            combat_phase=CombatPhase.ATTACKING,
            target_ptr=0xB800,
        )
        decision = decide_actions(
            self._snap((p1, foe)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertTrue(decision.p1_mask & 0x20, decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x04, decision.p1_note)
        self.assertIn("interrupt", decision.p1_note)

    def test_intercepts_signal_before_unsampled_slide_attack(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(
            type_id=0x24,
            family="Signal",
            map_x=170,
            world_x=170,
            map_y=64,
            world_y=64,
            label="Signal",
            primary_state=0x0101,
            action_state=0x01,
            combat_phase=CombatPhase.NORMAL,
            target_ptr=0xB800,
        )
        decision = decide_actions(
            self._snap((p1, foe)), AgentConfig(p1_enabled=True), AgentState()
        )
        # Signal counters prefer mid/far jump-ins over grounded intercept punches.
        self.assertFalse(decision.p1_mask & 0x20, decision.p1_note)
        self.assertTrue(
            "jump" in decision.p1_note or decision.p1_mask & 0x40,
            decision.p1_note,
        )

    def test_jumps_signal_sweep_then_attacks_in_free_flight(self) -> None:
        for state, phase in (
            (0x08, CombatPhase.CHARGE),
            (0x0B, CombatPhase.ATTACKING),
        ):
            with self.subTest(state=state):
                p1 = _e(
                    kind="player",
                    family="Player",
                    slot="P1",
                    map_x=100,
                    world_x=100,
                    map_y=64,
                    world_y=64,
                    type_id=1,
                    label="P1",
                    action_state=0x32,
                    # A held weapon must not pre-empt the sweep counter.
                    held_type=0x0A,
                    held_ptr=0xBA00,
                )
                signal = _e(
                    type_id=0x24,
                    family="Signal",
                    map_x=160,
                    world_x=160,
                    map_y=64,
                    world_y=64,
                    label="Signal",
                    primary_state=state << 8,
                    action_state=state,
                    combat_phase=phase,
                    target_ptr=0xB800,
                )
                decision = decide_actions(
                    self._snap((p1, signal)),
                    AgentConfig(p1_enabled=True),
                    AgentState(),
                )
                self.assertTrue(decision.p1_mask & 0x40, decision.p1_note)
                self.assertFalse(decision.p1_mask & 0x20, decision.p1_note)
                self.assertIn("jump Signal sweep", decision.p1_note)

                airborne = _e(
                    kind="player",
                    family="Player",
                    slot="P1",
                    map_x=100,
                    world_x=100,
                    map_y=64,
                    world_y=64,
                    type_id=1,
                    label="P1",
                    action_state=0x3E,
                    held_type=0x0A,
                    held_ptr=0xBA00,
                )
                follow = decide_actions(
                    self._snap((airborne, signal)),
                    AgentConfig(p1_enabled=True),
                    AgentState(),
                )
                self.assertFalse(follow.p1_mask & 0x20, follow.p1_note)
                self.assertFalse(follow.p1_mask & 0x40, follow.p1_note)
                self.assertIn("air air Signal", follow.p1_note)

        # Unarmed free flight accepts B, so the counter becomes a jump attack.
        airborne = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x12,
        )
        signal = _e(
            type_id=0x24,
            family="Signal",
            map_x=160,
            world_x=160,
            map_y=64,
            world_y=64,
            label="Signal",
            primary_state=0x0B00,
            action_state=0x0B,
            combat_phase=CombatPhase.ATTACKING,
            target_ptr=0xB800,
        )
        follow = decide_actions(
            self._snap((airborne, signal)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertTrue(follow.p1_mask & 0x20, follow.p1_note)
        self.assertIn("air attack Signal", follow.p1_note)

    def test_no_punch_off_lane(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(map_x=118, world_x=118, map_y=90, label="OffLane")
        snap = self._snap((p1, foe))
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertFalse(d.p1_mask & 0x20, msg=f"air punch: {d.p1_note}")
        self.assertTrue(
            "lane" in d.p1_note or "walk" in d.p1_note or "close" in d.p1_note,
            d.p1_note,
        )

    def test_jump_start_is_c_only_not_rear(self) -> None:
        """Jump-kick is C then B later — never B+C (rear) on the same tick."""

        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        foe = _e(
            map_x=170,
            world_x=170,
            map_y=64,
            label="Haku-Ro",
            family="Haku-Ro",
            type_id=0x25,
        )
        snap = self._snap((p1, foe), char_id=2)  # Blaze
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertIn("jump start", d.p1_note)
        self.assertTrue(d.p1_mask & 0x40, msg=f"needs C: {d.p1_mask:#x} {d.p1_note}")
        self.assertFalse(
            d.p1_mask & 0x20,
            msg=f"must NOT attack on jump start (B+C=rear): {d.p1_mask:#x}",
        )

    def test_armed_jack_is_ground_attackable(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        jack = _e(
            family="Jack",
            type_id=0x27,
            label="Jack",
            map_x=140,
            world_x=140,
            map_y=64,
            world_y=64,
            primary_state=0x0C00,
            family_state=0x01,
        )
        d = decide_actions(
            self._snap((p1, jack)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertTrue(d.p1_mask & 0x20, d.p1_note)
        self.assertFalse(d.p1_mask & 0x40, d.p1_note)
        self.assertIn("punch Jack", d.p1_note)

    def test_armed_jack_remains_attackable_at_close_range(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        jack = _e(
            family="Jack",
            type_id=0x27,
            label="Jack",
            map_x=118,
            world_x=118,
            map_y=64,
            world_y=64,
            primary_state=0x0C00,
            family_state=0x01,
        )
        d = decide_actions(
            self._snap((p1, jack)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertTrue(d.p1_mask & 0x20, d.p1_note)
        self.assertFalse(d.p1_mask & 0x40, d.p1_note)
        self.assertIn("punch Jack", d.p1_note)

    def test_throwing_jack_is_ground_attackable_even_if_latch_sample_is_stale(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        jack = _e(
            family="Jack",
            type_id=0x27,
            label="Jack",
            map_x=140,
            world_x=140,
            map_y=64,
            world_y=64,
            primary_state=0x0E00,
            family_state=0x01,
            combat_phase=CombatPhase.NORMAL,
        )
        d = decide_actions(
            self._snap((p1, jack)), AgentConfig(p1_enabled=True), AgentState()
        )
        # Throw window: prefer close-for-grab (or punch if already body-close).
        self.assertFalse(d.p1_mask & 0x40, d.p1_note)
        self.assertTrue(
            d.p1_mask & 0x20 or "grab" in d.p1_note,
            d.p1_note,
        )
        self.assertTrue(
            "grab" in d.p1_note or "punch" in d.p1_note or "close" in d.p1_note,
            d.p1_note,
        )

    def test_airborne_fires_b_only(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x13,  # free flight; ROM accepts B here
        )
        foe = _e(map_x=150, world_x=150, map_y=64, label="Garcia")
        snap = self._snap((p1, foe), char_id=2)
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertIn("air attack", d.p1_note)
        self.assertTrue(d.p1_mask & 0x20, msg=f"needs B: {d.p1_mask:#x}")
        self.assertFalse(d.p1_mask & 0x40, msg=f"no C while air attacking: {d.p1_mask:#x}")

    def test_jump_launch_landing_and_attack_states_do_not_repress_b(self) -> None:
        foe = _e(map_x=150, world_x=150, map_y=64, label="Garcia")
        for action, expected in ((0x11, "launch"), (0x15, "land"), (0x17, "kick")):
            p1 = _e(
                kind="player",
                family="Player",
                slot="P1",
                map_x=100,
                world_x=100,
                map_y=64,
                type_id=1,
                label="P1",
                action_state=action,
            )
            d = decide_actions(
                self._snap((p1, foe), char_id=2),
                AgentConfig(p1_enabled=True),
                AgentState(),
            )
            self.assertIn(expected, d.p1_note)
            self.assertFalse(d.p1_mask & 0x20, d.p1_note)

    def test_busy_normal_attack_queues_combo_against_live_foe(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x18,
            action_flags=0,
        )
        foe = _e(map_x=128, world_x=128, map_y=64, label="Garcia")
        d = decide_actions(
            self._snap((p1, foe)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertIn("combo queue", d.p1_note)
        self.assertTrue(d.p1_mask & 0x20, d.p1_note)

    def test_smashes_breakable(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        crate = MapEntity(
            kind="breakable",
            family="Breakable",
            symbol="#",
            color="#aaa",
            label="Phone booth",
            type_id=0x11,
            world_x=120,
            world_y=64,
            world_z=0,
            map_x=120.0,
            map_y=64.0,
            health=None,
            slot="B0",
        )
        snap = self._snap((p1, crate))
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertTrue(
            "smash" in d.p1_note or "break" in d.p1_note or "jump-break" in d.p1_note,
            d.p1_note,
        )
        if "smash" in d.p1_note:
            self.assertTrue(d.p1_mask & 0x20, d.p1_note)

    def test_smashes_round8_moving_breakable(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        moving_prop = _e(
            kind="breakable",
            family="Breakable",
            symbol="◆",
            label="Moving prop",
            type_id=0x45,
            map_x=120,
            world_x=120,
            map_y=64,
            health=None,
            slot="B0",
            outgoing_damage=3,
            script_param=2,
            combat_phase=CombatPhase.ATTACKING,
        )

        decision = decide_actions(
            self._snap((p1, moving_prop), level=7),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )

        self.assertIn("smash Moving prop", decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x20, decision.p1_note)

    def test_evades_midrange_round8_moving_breakable_instead_of_chasing(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=160,
            world_x=160,
            map_y=64,
            world_y=64,
            type_id=1,
            label="P1",
            action_state=0x03,
        )
        moving_prop = _e(
            kind="breakable",
            family="Breakable",
            symbol="◆",
            label="Moving prop",
            type_id=0x45,
            map_x=47,
            world_x=47,
            map_y=64,
            world_y=64,
            health=None,
            slot="B0",
            outgoing_damage=3,
            script_param=2,
            combat_phase=CombatPhase.ATTACKING,
        )

        decision = decide_actions(
            self._snap((p1, moving_prop), level=7),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )

        self.assertIn("evade moving threat Moving prop", decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x01, decision.p1_note)
        self.assertFalse(decision.p1_mask & 0x0C, decision.p1_note)
        self.assertFalse(decision.p1_mask & 0x20, decision.p1_note)

    def test_avoids_round6_moving_stage_hazard(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        hazard = _e(
            kind="projectile",
            family="Stage hazard",
            symbol="!",
            label="Press",
            type_id=0x42,
            map_x=130,
            world_x=130,
            map_y=64,
            health=None,
            slot="H0",
            outgoing_damage=0x14,
            combat_phase=CombatPhase.ATTACKING,
        )

        decision = decide_actions(
            self._snap((p1, hazard), level=5),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )

        # Same-lane approach: leave the press lane (UP or DOWN), never smash.
        self.assertTrue(
            "avoid press" in decision.p1_note or "leave press" in decision.p1_note,
            decision.p1_note,
        )
        self.assertTrue(decision.p1_mask & 0x03, decision.p1_note)  # UP or DOWN
        self.assertFalse(decision.p1_mask & 0x0C, decision.p1_note)  # no LEFT/RIGHT into frame
        self.assertFalse(decision.p1_mask & 0x20, decision.p1_note)

    def test_leaves_press_when_standing_under_it(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=160,
            world_x=160,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        hazard = _e(
            kind="projectile",
            family="Stage hazard",
            symbol="!",
            label="Press",
            type_id=0x42,
            map_x=160,
            world_x=160,
            map_y=64,
            health=None,
            slot="H0",
            outgoing_damage=0x14,
            combat_phase=CombatPhase.ATTACKING,
        )

        decision = decide_actions(
            self._snap((p1, hazard), level=5),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )

        self.assertIn("leave press", decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x03, decision.p1_note)
        self.assertFalse(decision.p1_mask & 0x20, decision.p1_note)

    def test_routes_progress_around_press_solid_body(self) -> None:
        """Progress right must detour on Y instead of holding into the frame."""

        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        # Press just ahead on the same lane, outside same-lane react (|dx|>100)
        # so the early leave-lane branch does not fire — solid routing must.
        hazard = _e(
            kind="projectile",
            family="Stage hazard",
            symbol="!",
            label="Press",
            type_id=0x42,
            map_x=220,
            world_x=220,
            map_y=64,
            health=None,
            slot="H0",
            outgoing_damage=0x14,
            combat_phase=CombatPhase.ATTACKING,
        )

        decision = decide_actions(
            self._snap((p1, hazard), level=5),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )

        # Navigator should detour around the solid AABB rather than only RIGHT.
        note = decision.p1_note
        self.assertTrue(
            "nav" in note or "detour" in note or "progress" in note or "unstuck" in note,
            note,
        )
        # Must not treat the press as a combat projectile target.
        self.assertNotIn("dodge", note)
        self.assertFalse(decision.p1_mask & 0x20, note)

    def test_rear_when_enemy_behind(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,  # face right
        )
        # Only a rear threat (no grabbable front target): use rear B+C.
        back = _e(map_x=78, world_x=78, map_y=64, label="Backstab", slot="E1")
        snap = self._snap((p1, back))
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        self.assertTrue(
            "rear" in d.p1_note or "back atk" in d.p1_note,
            d.p1_note,
        )
        self.assertEqual(d.p1_mask & 0x60, 0x60, msg=hex(d.p1_mask))

    def test_back_exposed_prefers_grab_shield_on_front(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            world_x=100,
            map_y=64,
            type_id=1,
            label="P1",
            action_state=0x02,
        )
        front = _e(map_x=118, world_x=118, map_y=64, label="Front", slot="E0")
        back = _e(map_x=70, world_x=70, map_y=64, label="Backstab", slot="E1")
        d = decide_actions(
            self._snap((p1, front, back)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertIn("grab shield", d.p1_note)
        self.assertNotIn("back atk", d.p1_note)


if __name__ == "__main__":
    unittest.main()
