"""Unit tests for the standard-controls agent policy."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.agent.controls import ATTACK, JUMP, SPECIAL, Intent, mask_from_intent
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.agent.pressure import PressureReport, should_call_police
from sor_autoplay.agent.stage import (
    is_mr_x_offer,
    point_in_hole,
    stage_advice,
    steer_away_from_holes,
)
from sor_autoplay.hazards import FloorHole
from sor_autoplay.memory_map import (
    MAX_HEALTH,
    OBJ_CHARACTER_ID,
    OBJ_HEALTH,
    OBJ_POS_X,
    OBJ_POS_Y,
    OBJ_TYPE,
    OBJECT_SLOT_SIZE,
)
from sor_autoplay.phases import CombatPhase
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import MapEntity, WorldMap


def _put_u8(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF


def _put_u16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def _entity(
    *,
    kind: str,
    map_x: float,
    map_y: float,
    world_x: int | None = None,
    world_y: int | None = None,
    world_z: int = 0,
    slot: str = "E0",
    label: str = "Garcia",
    family: str = "Garcia",
    health: int | None = 10,
    type_id: int = 0x20,
    action_state: int = 0,
) -> MapEntity:
    wx = int(world_x if world_x is not None else map_x)
    wy = int(world_y if world_y is not None else map_y)
    return MapEntity(
        kind=kind,
        family=family,
        symbol="G" if kind == "enemy" else kind[0].upper(),
        color="#fff",
        label=label,
        type_id=type_id,
        world_x=wx,
        world_y=wy,
        world_z=world_z,
        map_x=map_x,
        map_y=map_y,
        health=health,
        slot=slot,
        action_state=action_state,
    )


def _base_ingame_blocks() -> tuple[bytearray, bytearray, bytearray]:
    globals_block = bytearray(0x40)
    timer_block = bytearray(4)
    objects = bytearray(0x100)
    _put_u16(globals_block, 0x00, 0x0016)
    _put_u16(globals_block, 0x02, 0x0000)
    _put_u16(globals_block, 0x04, 0x0001)
    _put_u8(globals_block, 0x18, 0x01)  # P1 only
    _put_u8(globals_block, 0x1E, 0x00)  # Axel
    _put_u8(globals_block, 0x20, 0x03)
    _put_u8(globals_block, 0x21, 0x02)  # 2 specials
    _put_u16(timer_block, 0, 0x0040)
    _put_u8(objects, OBJ_TYPE, 0x01)
    _put_u16(objects, OBJ_HEALTH, MAX_HEALTH)
    _put_u8(objects, OBJ_CHARACTER_ID, 0x00)
    _put_u16(objects, OBJ_POS_X, 100)
    _put_u16(objects, OBJ_POS_Y, 0x40)
    return globals_block, timer_block, objects


def _snapshot_with_map(
    entities: tuple[MapEntity, ...],
    *,
    level_index: int = 0,
    specials: int = 2,
    health: int = MAX_HEALTH,
    paused: bool = False,
    police: bool = False,
    mr_x: int = 0,
    holes: tuple[FloorHole, ...] = (),
    p2: bool = False,
) -> object:
    from dataclasses import replace

    globals_block, timer_block, objects = _base_ingame_blocks()
    _put_u16(globals_block, 0x02, level_index)
    # specials packed BCD nibble byte: value 2 -> 0x02
    _put_u8(globals_block, 0x21, specials & 0xFF)
    _put_u16(objects, OBJ_HEALTH, health)
    if p2:
        _put_u8(globals_block, 0x18, 0x03)
        _put_u8(globals_block, 0x1F, 0x02)
        _put_u8(globals_block, 0x23, 0x03)
        _put_u8(globals_block, 0x24, 0x01)
        p2b = OBJECT_SLOT_SIZE
        _put_u8(objects, p2b + OBJ_TYPE, 0x01)
        _put_u16(objects, p2b + OBJ_HEALTH, MAX_HEALTH // 2)
        _put_u8(objects, p2b + OBJ_CHARACTER_ID, 0x02)
        _put_u16(objects, p2b + OBJ_POS_X, 140)
        _put_u16(objects, p2b + OBJ_POS_Y, 0x40)

    snap = snapshot_from_memory_blocks(
        globals_block=bytes(globals_block),
        timer_block=bytes(timer_block),
        objects_block=bytes(objects),
        stop_clock=1 if mr_x else 0,
        pause_text_flag=3 if paused else 0,
        police_special_active_byte=1 if police else 0,
        mr_x_offer_flag=mr_x,
        mr_x_offer_state=0x0A if mr_x else 0,
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
    return replace(snap, world_map=world, floor_holes=holes)


class ControlsTests(unittest.TestCase):
    def test_standard_masks(self) -> None:
        self.assertEqual(mask_from_intent(Intent(attack=True)), int(ATTACK))
        self.assertEqual(mask_from_intent(Intent(jump=True)), int(JUMP))
        self.assertEqual(mask_from_intent(Intent(special=True)), int(SPECIAL))
        # B + C for rear attack chord
        self.assertEqual(
            mask_from_intent(Intent(rear_attack=True)),
            int(ATTACK) | int(JUMP),
        )


class StageTests(unittest.TestCase):
    def test_stage8_goes_left(self) -> None:
        self.assertFalse(stage_advice(7).progress_right)
        self.assertTrue(stage_advice(0).progress_right)

    def test_hole_steering_cancels_into_pit(self) -> None:
        holes = (FloorHole(world_x=100, lane_y=40, width=32, height=24),)
        dx, dy = steer_away_from_holes(90, 50, 1.0, 0.0, holes, level_index=3)
        self.assertLessEqual(dx, 0.0)


class PressureTests(unittest.TestCase):
    def test_police_threshold(self) -> None:
        high = PressureReport(5.0, 5, False, "pack")
        self.assertTrue(should_call_police(high, specials=1))
        self.assertFalse(should_call_police(high, specials=0))
        self.assertFalse(should_call_police(high, specials=1, level_index=7))

    def test_special_is_saved_during_small_full_health_skirmish(self) -> None:
        trigger_happy = PressureReport(
            9.0,
            2,
            False,
            "two active attackers",
            charging=2,
            health_percent=100.0,
        )
        self.assertFalse(should_call_police(trigger_happy, specials=2))

    def test_low_health_or_boss_unlocks_special_spending(self) -> None:
        low_health = PressureReport(
            5.0,
            1,
            False,
            "hurt",
            health_percent=35.0,
        )
        boss = PressureReport(
            10.0,
            0,
            True,
            "boss-immediate",
            health_percent=100.0,
        )
        self.assertTrue(should_call_police(low_health, specials=1))
        self.assertTrue(should_call_police(boss, specials=1))


class PolicyTests(unittest.TestCase):
    def test_disabled_agents_emit_zero(self) -> None:
        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        snap = _snapshot_with_map((p1,))
        decision = decide_actions(snap, AgentConfig(p1_enabled=False))
        self.assertEqual(decision.p1_mask, 0)
        self.assertEqual(decision.p2_mask, 0)

    def test_progress_right_when_no_enemies(self) -> None:
        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        snap = _snapshot_with_map((p1,))
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        # Buttons.RIGHT = 1 << 3
        self.assertTrue(decision.p1_mask & 0x08, msg=f"expected RIGHT, got {decision.p1_mask:#x}")
        self.assertIn("progress", decision.p1_note)

    def test_stage8_progress_left(self) -> None:
        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        snap = _snapshot_with_map((p1,), level_index=7)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & 0x04, msg=f"expected LEFT, got {decision.p1_mask:#x}")

    def test_stage7_elevator_clear_screen_centers_without_horizontal_input(self) -> None:
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
        )
        fake_hole = FloorHole(world_x=80, lane_y=48, width=96, height=64)
        snap = _snapshot_with_map((p1,), level_index=6, holes=(fake_hole,))
        memory = AgentState()
        # A corridor-progress latch from the preceding wave must be discarded.
        memory.p1_walk.set_goal(p1, 260.0, 64.0, reason="old progress")
        decision = decide_actions(
            snap,
            AgentConfig(p1_enabled=True),
            memory,
        )
        self.assertEqual(decision.p1_mask & 0x0C, 0, decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x02, decision.p1_note)  # DOWN
        self.assertIn("elevator", decision.p1_note)

    def test_stage4_progress_routes_around_pit_then_resumes_right(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=32, height=24)
        memory = AgentState()
        x, y = 90, 50
        notes: list[str] = []
        for _ in range(10):
            p1 = _entity(
                kind="player",
                map_x=x,
                map_y=y,
                world_x=x,
                world_y=y,
                slot="P1",
                label="P1 Axel",
                family="Player",
                action_state=0x02,
            )
            snap = _snapshot_with_map((p1,), level_index=3, holes=(hole,))
            decision = decide_actions(
                snap,
                AgentConfig(p1_enabled=True),
                memory,
            )
            notes.append(decision.p1_note)
            x += 12 * bool(decision.p1_mask & 0x08)
            x -= 12 * bool(decision.p1_mask & 0x04)
            y += 12 * bool(decision.p1_mask & 0x02)
            y -= 12 * bool(decision.p1_mask & 0x01)
            self.assertIsNone(
                point_in_hole(x, y, (hole,), margin=0.0),
                notes,
            )
        self.assertGreater(x, hole.world_x_end, notes)
        self.assertLess(abs(y - 64), 8, notes)

    def test_attacks_nearby_enemy(self) -> None:
        # Face right in grounded idle toward a foe inside strike range.
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        foe = _entity(kind="enemy", map_x=124, map_y=64, slot="E0", label="Garcia")
        snap = _snapshot_with_map((p1, foe))
        memory = AgentState()
        saw_attack = False
        notes: list[str] = []
        for _ in range(8):
            decision = decide_actions(snap, AgentConfig(p1_enabled=True), memory)
            notes.append(decision.p1_note)
            if decision.p1_mask & int(ATTACK):
                saw_attack = True
                break
        self.assertTrue(saw_attack, f"agent should punch when enemy is in range: {notes}")
        self.assertTrue(
            any(
                k in decision.p1_note
                for k in ("punch", "punish", "combo", "intercept")
            ),
            msg=decision.p1_note,
        )

    def test_souther_committed_claw_uses_boss_lane_tactic(self) -> None:
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        souther = replace(
            _entity(
                kind="boss",
                map_x=155,
                map_y=64,
                slot="B0",
                label="Souther",
                family="Souther",
                type_id=0x55,
                action_state=0x02,
            ),
            combat_phase=CombatPhase.ATTACKING,
        )
        snap = _snapshot_with_map((p1, souther), level_index=1, specials=0)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & 0x03, decision.p1_note)
        self.assertIn("sidestep Souther", decision.p1_note)

    def test_steady_when_paused(self) -> None:
        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        snap = _snapshot_with_map((p1,), paused=True)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.steady)
        self.assertEqual(decision.p1_mask, 0)

    def test_steady_during_police_special(self) -> None:
        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        snap = _snapshot_with_map((p1,), police=True)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.steady)
        self.assertEqual(decision.p1_mask, 0)

    def test_police_under_pressure(self) -> None:
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        foes = tuple(
            _entity(
                kind="enemy",
                map_x=100 + i * 12,
                map_y=64,
                slot=f"E{i}",
                label="Garcia",
            )
            for i in range(6)
        )
        snap = _snapshot_with_map((p1, *foes), health=MAX_HEALTH // 5, specials=2)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & int(SPECIAL), msg=f"mask={decision.p1_mask:#x} note={decision.p1_note}")

    def test_offscreen_enemies_do_not_trigger_police_or_chase(self) -> None:
        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        foes = tuple(
            _entity(kind="enemy", map_x=321 + i, map_y=64, slot=f"E{i}")
            for i in range(6)
        )
        snap = _snapshot_with_map((p1, *foes), health=MAX_HEALTH // 5, specials=2)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertFalse(decision.p1_mask & int(SPECIAL), decision.p1_note)
        self.assertIn("progress", decision.p1_note)

    def test_continue_ui_confirms_yes(self) -> None:
        """Type-$0F continue with YES selected → B confirm."""

        globals_block, timer_block, objects = _base_ingame_blocks()
        _put_u8(globals_block, 0x18, 0x00)  # mode bit cleared on death
        _put_u16(globals_block, 0x1A, 0x0003)  # continues remain
        _put_u8(globals_block, 0x20, 0x00)  # lives exhausted
        _put_u8(objects, OBJ_TYPE, 0x0F)
        # +$4B bit7 clear (not name entry); +$63 = 0 (YES)
        _put_u8(objects, 0x4B, 0x00)
        _put_u8(objects, 0x63, 0x00)
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        self.assertTrue(snap.p1.is_continue_ui)
        self.assertFalse(snap.p1.name_entry_active)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & int(ATTACK), msg=decision.p1_note)
        self.assertIn("continue confirm YES", decision.p1_note)

    def test_continue_ui_selects_yes_when_no_highlighted(self) -> None:
        globals_block, timer_block, objects = _base_ingame_blocks()
        _put_u8(globals_block, 0x18, 0x00)
        _put_u16(globals_block, 0x1A, 0x0002)
        _put_u8(objects, OBJ_TYPE, 0x0F)
        _put_u8(objects, 0x4B, 0x00)
        _put_u8(objects, 0x63, 0x01)  # NO selected
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & 0x01, msg=decision.p1_note)  # UP
        self.assertIn("continue select YES", decision.p1_note)

    def test_name_entry_places_with_c_not_b(self) -> None:
        """Name entry ($57D2): C/A place glyphs; B is backspace and stalls."""

        globals_block, timer_block, objects = _base_ingame_blocks()
        _put_u8(globals_block, 0x18, 0x00)
        _put_u16(globals_block, 0x1A, 0x0003)
        _put_u8(objects, OBJ_TYPE, 0x0F)
        _put_u8(objects, 0x4B, 0x80)  # name-entry path
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        self.assertTrue(snap.p1.name_entry_active)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & int(JUMP), msg=decision.p1_note)
        self.assertFalse(
            decision.p1_mask & int(ATTACK),
            msg=f"B is backspace on name entry: {decision.p1_note}",
        )
        self.assertIn("name entry", decision.p1_note)

    def test_continue_ui_idles_when_no_continues(self) -> None:
        globals_block, timer_block, objects = _base_ingame_blocks()
        _put_u8(globals_block, 0x18, 0x00)
        _put_u16(globals_block, 0x1A, 0x0000)
        _put_u8(objects, OBJ_TYPE, 0x0F)
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertEqual(decision.p1_mask, 0)
        self.assertIn("game over", decision.p1_note)

    def test_mr_x_refuses_with_down_and_a(self) -> None:
        """Always DOWN+A while offer is live — never idle on bit4 clear."""

        from dataclasses import replace

        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        # bit4 clear used to force "mr.x wait" and stuck the agent forever.
        snap = _snapshot_with_map((p1,), level_index=7, mr_x=1)
        raw = dict(snap.raw)
        raw["p1_obj59"] = 0x00
        snap = replace(snap, raw=raw)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & 0x02, msg=decision.p1_note)  # DOWN
        self.assertTrue(
            decision.p1_mask & int(SPECIAL),
            msg=f"expected A with DOWN, got {decision.p1_mask:#x} {decision.p1_note}",
        )
        self.assertFalse(decision.p1_mask & int(ATTACK), msg=decision.p1_note)
        self.assertIn("refuse NO", decision.p1_note)
        self.assertNotIn("wait", decision.p1_note)

    def test_mr_x_refuses_when_choice_bits_already_set(self) -> None:
        from dataclasses import replace

        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        snap = _snapshot_with_map((p1,), level_index=7, mr_x=1)
        raw = dict(snap.raw)
        raw["p1_obj59"] = 0x18  # bit4 + NO
        snap = replace(snap, raw=raw)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertTrue(decision.p1_mask & 0x02, msg=decision.p1_note)
        self.assertTrue(decision.p1_mask & int(SPECIAL), msg=decision.p1_note)
        self.assertIn("refuse NO", decision.p1_note)

    def test_mr_x_dialog_ends_when_enemies_spawn(self) -> None:
        """Offer flag can stay set after refuse; live threats leave DIALOG."""

        p1 = _entity(kind="player", map_x=100, map_y=64, slot="P1", label="P1 Axel", family="Player")
        foe = _entity(
            kind="enemy",
            map_x=160,
            map_y=64,
            slot="E1",
            label="Galsia",
            family="Galsia",
            type_id=0x20,
        )
        snap = _snapshot_with_map((p1, foe), level_index=7, mr_x=1)
        self.assertFalse(is_mr_x_offer(snap))
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertNotIn("mr.x", decision.p1_note)
        self.assertNotIn("refuse NO", decision.p1_note)

    def test_coop_yields_health_to_hurt_partner(self) -> None:
        from sor_autoplay.agent.coop import CoopContext, should_take_health_pickup
        from sor_autoplay.state import PlayerSnapshot

        me = PlayerSnapshot(
            index=1,
            mode_active=True,
            object_type=1,
            character_id=0,
            character_name="Axel",
            health=MAX_HEALTH,
            health_percent=100.0,
            lives=3,
            specials=1,
            score=0,
            score_text="000000",
            continues=3,
            out_flag=0,
            is_playable=True,
        )
        partner = PlayerSnapshot(
            index=2,
            mode_active=True,
            object_type=1,
            character_id=2,
            character_name="Blaze",
            health=MAX_HEALTH // 4,
            health_percent=25.0,
            lives=3,
            specials=1,
            score=0,
            score_text="000000",
            continues=3,
            out_flag=0,
            is_playable=True,
        )
        ctx = CoopContext(partner=None, partner_snap=partner, both_agents=True, partner_hp=25.0)
        self.assertFalse(should_take_health_pickup(me, ctx))

    def test_never_punches_through_partner_at_enemy(self) -> None:
        """SoR1 friendly fire: do not emit B when the partner is in the strike cone."""

        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        # Partner stands between P1 and the foe in the same lane.
        p2 = _entity(
            kind="player",
            map_x=130,
            map_y=64,
            slot="P2",
            label="P2 Blaze",
            family="Player",
            action_state=0x02,
        )
        foe = _entity(
            kind="enemy",
            map_x=150,
            map_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
            type_id=0x20,
            action_state=0x00,
        )
        snap = _snapshot_with_map((p1, p2, foe), p2=True)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertEqual(
            decision.p1_mask & int(ATTACK),
            0,
            msg=f"attacked through partner: {decision.p1_note} mask={decision.p1_mask:#x}",
        )
        self.assertTrue(
            "ally" in decision.p1_note or "clear" in decision.p1_note,
            msg=decision.p1_note,
        )

    def test_punches_enemy_when_partner_is_clear(self) -> None:
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        # Partner is off-lane so punches cannot hit them.
        p2 = _entity(
            kind="player",
            map_x=130,
            map_y=20,
            slot="P2",
            label="P2 Blaze",
            family="Player",
            action_state=0x02,
        )
        foe = _entity(
            kind="enemy",
            map_x=140,
            map_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
            type_id=0x20,
            action_state=0x00,
        )
        snap = _snapshot_with_map((p1, p2, foe), p2=True)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertEqual(
            decision.p1_mask & int(ATTACK),
            int(ATTACK),
            msg=f"expected punch with clear partner: {decision.p1_note}",
        )

    def test_never_swings_weapon_through_partner(self) -> None:
        from dataclasses import replace

        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x30,
        )
        p1 = replace(p1, held_type=0x0A)  # bat
        p2 = _entity(
            kind="player",
            map_x=120,
            map_y=64,
            slot="P2",
            label="P2 Blaze",
            family="Player",
            action_state=0x02,
        )
        foe = _entity(
            kind="enemy",
            map_x=130,
            map_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
            type_id=0x20,
        )
        snap = _snapshot_with_map((p1, p2, foe), p2=True)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertEqual(
            decision.p1_mask & int(ATTACK),
            0,
            msg=f"weapon swing through partner: {decision.p1_note}",
        )


class AllySafetyUnitTests(unittest.TestCase):
    def test_rear_range_covers_blazes_measured_chord_box(self) -> None:
        # Blaze's own +$64 rear box reaches -53..-5; the ally exclusion zone
        # must cover it plus an ally body width or a Blaze chord can clear an
        # ally standing just past the old (undersized) 48 px cutoff.
        from sor_autoplay.agent.coop import attack_would_hit_ally

        me = _entity(kind="player", map_x=100, map_y=64, slot="P1", action_state=0x02)
        ally = _entity(kind="player", map_x=45, map_y=64, slot="P2", action_state=0x02)
        self.assertTrue(
            attack_would_hit_ally(me, ally, face_left=False, rear=True)
        )

    def test_directional_hit_and_body_range(self) -> None:
        from sor_autoplay.agent.coop import (
            ally_in_body_range,
            attack_would_hit_ally,
        )

        me = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            action_state=0x02,  # facing right
        )
        ally_front = _entity(
            kind="player", map_x=130, map_y=64, slot="P2", action_state=0x02
        )
        ally_rear = _entity(
            kind="player", map_x=70, map_y=64, slot="P2", action_state=0x02
        )
        ally_offlane = _entity(
            kind="player", map_x=130, map_y=20, slot="P2", action_state=0x02
        )
        ally_body = _entity(
            kind="player", map_x=110, map_y=64, slot="P2", action_state=0x02
        )
        self.assertTrue(
            attack_would_hit_ally(me, ally_front, face_left=False)
        )
        self.assertFalse(
            attack_would_hit_ally(me, ally_rear, face_left=False)
        )
        self.assertTrue(
            attack_would_hit_ally(me, ally_rear, face_left=False, rear=True)
        )
        self.assertFalse(
            attack_would_hit_ally(me, ally_offlane, face_left=False)
        )
        self.assertTrue(ally_in_body_range(me, ally_body))
        # Body-close partner is risky regardless of facing.
        self.assertTrue(
            attack_would_hit_ally(me, ally_body, face_left=False)
        )

    def test_standing_partner_is_not_air_assist(self) -> None:
        """world_z is always large for standing players; only jump actions count."""
        from dataclasses import replace

        from sor_autoplay.agent.coop import partner_throw_opportunity

        me = _entity(kind="player", map_x=100, map_y=64, slot="P1", action_state=0x02)
        standing = _entity(
            kind="player", map_x=110, map_y=64, slot="P2", action_state=0x02
        )
        standing = replace(standing, world_z=160)
        airborne = _entity(
            kind="player", map_x=110, map_y=64, slot="P2", action_state=0x12
        )
        airborne = replace(airborne, world_z=160)
        self.assertFalse(partner_throw_opportunity(me, standing))
        self.assertTrue(partner_throw_opportunity(me, airborne))

    def test_final_guard_strips_attack_near_partner(self) -> None:
        from sor_autoplay.agent.controls import Intent
        from sor_autoplay.agent.coop import guard_attack_intent

        me = _entity(kind="player", map_x=100, map_y=64, slot="P1", action_state=0x02)
        ally = _entity(kind="player", map_x=120, map_y=64, slot="P2", action_state=0x02)
        raw = Intent(attack=True, note="punch Garcia")
        safe = guard_attack_intent(me, ally, raw, both_agents=False)
        self.assertFalse(safe.attack)
        self.assertIn("ally safe", safe.note)

    def test_both_agents_do_not_rear_attack_standing_partner(self) -> None:
        """Regression: false air-assist used jump+attack (= B+C) on standing allies."""
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        p2 = _entity(
            kind="player",
            map_x=120,
            map_y=64,
            slot="P2",
            label="P2 Blaze",
            family="Player",
            action_state=0x02,
        )
        foe = _entity(
            kind="enemy",
            map_x=160,
            map_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
            type_id=0x20,
        )
        snap = _snapshot_with_map((p1, p2, foe), p2=True)
        decision = decide_actions(
            snap, AgentConfig(p1_enabled=True, p2_enabled=True)
        )
        # P1 has P2 between them and the foe — must not attack through P2.
        self.assertEqual(decision.p1_mask & int(ATTACK), 0, decision.p1_note)
        self.assertNotIn("2P air assist", decision.p1_note)
        self.assertNotIn("2P air assist", decision.p2_note)

    def test_agent_can_punch_when_partner_stands_behind(self) -> None:
        p1 = _entity(
            kind="player",
            map_x=120,
            map_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
            action_state=0x02,
        )
        p2 = _entity(
            kind="player",
            map_x=80,
            map_y=64,
            slot="P2",
            label="P2 Blaze",
            family="Player",
            action_state=0x02,
        )
        foe = _entity(
            kind="enemy",
            map_x=155,
            map_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
            type_id=0x20,
        )
        snap = _snapshot_with_map((p1, p2, foe), p2=True)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertEqual(
            decision.p1_mask & int(ATTACK),
            int(ATTACK),
            msg=f"expected punch with partner behind: {decision.p1_note}",
        )

    def test_throw_direction_avoids_ally(self) -> None:
        from sor_autoplay.agent.coop import throw_direction_away_from_ally

        me = _entity(kind="player", map_x=100, map_y=64, slot="P1")
        ally = _entity(kind="player", map_x=140, map_y=64, slot="P2")
        self.assertEqual(
            throw_direction_away_from_ally(me, ally, default_dir=1), -1
        )


if __name__ == "__main__":
    unittest.main()
