"""Tests for enemy counters and grab/throw trees."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.agent.controls import ATTACK, JUMP, Intent, mask_from_intent
from sor_autoplay.agent.enemies import ThreatKind, attack_mix, plan_for
from sor_autoplay.agent.grabs import (
    GrabMemory,
    context_from_player,
    decide_held,
    is_grab_family,
    want_grab_approach,
)
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.agent.controls import ATTACK
from sor_autoplay.world_map import MapEntity, WorldMap


def _e(
    *,
    kind: str = "enemy",
    family: str = "Garcia",
    map_x: float = 100,
    map_y: float = 64,
    world_z: int = 0,
    type_id: int = 0x20,
    health: int | None = 10,
    slot: str = "E0",
    label: str | None = None,
    action_state: int = 0x02,
    action_flags: int = 0,
    held_type: int = 0,
    held_ptr: int = 0,
) -> MapEntity:
    return MapEntity(
        kind=kind,
        family=family,
        symbol="X",
        color="#fff",
        label=label or family,
        type_id=type_id,
        world_x=int(map_x),
        world_y=int(map_y),
        world_z=world_z,
        map_x=map_x,
        map_y=map_y,
        health=health,
        slot=slot,
        action_state=action_state,
        action_flags=action_flags,
        held_type=held_type,
        held_ptr=held_ptr,
    )


class EnemyCounterTests(unittest.TestCase):
    def test_signal_is_flanker(self) -> None:
        plan = plan_for(_e(family="Signal", type_id=0x24))
        self.assertEqual(plan.kind, ThreatKind.FLANKER)
        self.assertGreater(plan.rear_bias, 0.2)
        self.assertTrue(plan.sidestep)

    def test_jack_projectile_is_dodge(self) -> None:
        plan = plan_for(_e(kind="projectile", family="Jack", type_id=0x28, health=None))
        self.assertEqual(plan.kind, ThreatKind.PROJECTILE)

    def test_souther_no_jump(self) -> None:
        plan = plan_for(_e(kind="boss", family="Souther", type_id=0x55))
        self.assertTrue(plan.no_jump)

    def test_abadede_sidestep_charge(self) -> None:
        plan = plan_for(_e(kind="boss", family="Abadede", type_id=0x30))
        self.assertEqual(plan.kind, ThreatKind.CHARGER)
        self.assertTrue(plan.sidestep)

    def test_nora_distrusts_downed(self) -> None:
        plan = plan_for(_e(family="Nora", type_id=0x26, health=1))
        self.assertTrue(plan.distrust_downed)

    def test_attack_mix_respects_no_jump(self) -> None:
        from sor_autoplay.agent.characters import PROFILES

        plan = plan_for(_e(kind="boss", family="Souther", type_id=0x55))
        # Souther plan.no_jump: never jump even if geometry allows.
        mixes = {
            attack_mix(
                plan,
                PROFILES[0],
                tick=t,
                in_range=True,
                crowd=1,
                band="jump",
                can_jump=True,
                lane_ok=True,
                facing_ok=True,
            )
            for t in range(20)
        }
        self.assertNotIn("jump", mixes)
        self.assertIn("punch", mixes)


class GrabTreeTests(unittest.TestCase):
    def test_throw_is_b_plus_back(self) -> None:
        """A ready hold emits a guarded B+back throw input."""

        from sor_autoplay.agent.characters import PROFILES
        from sor_autoplay.agent.grabs import throw_back_direction

        # Face right (even action) → back = left.
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x20,
            action_state=0x28,  # grab family, face right
            map_x=100,
            map_y=64,
        )
        self.assertEqual(throw_back_direction(me), -1)
        me_l = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x20,
            action_state=0x29,
            map_x=100,
            map_y=64,
        )
        self.assertEqual(throw_back_direction(me_l), 1)

        ctx = context_from_player(me)
        self.assertTrue(ctx.enemy_grab)
        mem = GrabMemory()
        # Foe behind must not flip throw dir (facing-only).
        foe_behind = _e(map_x=70, map_y=64, family="Garcia")
        notes: list[str] = []
        saw_throw = False
        attack_pulses = 0
        for t in range(10):
            intent = decide_held(
                me,
                ctx,
                mem,
                tick=t,
                foe=foe_behind,
                progress_right=True,
                crowd=1,
                profile=PROFILES[2],
            )
            assert intent is not None
            notes.append(intent.note)
            if intent.attack:
                attack_pulses += 1
            if "throw" in intent.note:
                saw_throw = True
                self.assertTrue(intent.left, msg=notes)
                self.assertFalse(intent.right)
        self.assertTrue(saw_throw, notes)
        self.assertEqual(attack_pulses, 3, notes)
        self.assertTrue(any("await grab input" in note for note in notes), notes)

    def test_hold_latch_survives_brief_ram_drop(self) -> None:
        from sor_autoplay.agent.characters import PROFILES

        me_hold = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x20,
            action_state=0x28,
            map_x=100,
            map_y=64,
        )
        me_drop = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0,
            action_state=0x02,
            map_x=100,
            map_y=64,
        )
        mem = GrabMemory()
        a = decide_held(
            me_hold,
            context_from_player(me_hold),
            mem,
            tick=0,
            profile=PROFILES[0],
        )
        assert a is not None and a.attack
        # One dropped sample keeps ownership but must not inject B from idle.
        b = decide_held(
            me_drop,
            context_from_player(me_drop),
            mem,
            tick=1,
            profile=PROFILES[0],
        )
        assert b is not None
        self.assertFalse(b.attack)
        self.assertTrue(mem.latched)

    def test_live_hold_action_60_without_held_type(self) -> None:
        """Regression: live Axel hold was action $60, held_type 0, enemy GRABBED."""

        from sor_autoplay.agent.characters import PROFILES
        from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
        from sor_autoplay.phases import CombatPhase, player_phase
        from sor_autoplay.world_map import WorldMap
        from dataclasses import replace
        from sor_autoplay.memory_map import (
            MAX_HEALTH,
            OBJ_CHARACTER_ID,
            OBJ_HEALTH,
            OBJ_POS_X,
            OBJ_POS_Y,
            OBJ_TYPE,
        )
        from sor_autoplay.state import snapshot_from_memory_blocks

        self.assertEqual(player_phase(action_byte=0x60, held_type=0).name, "HOLDING")
        self.assertTrue(is_grab_family(0x60))

        me = MapEntity(
            kind="player",
            family="Player",
            symbol="1",
            color="#fff",
            label="P1",
            type_id=1,
            world_x=1295,
            world_y=64,
            world_z=0,
            map_x=176,
            map_y=64,
            health=72,
            slot="P1",
            action_state=0x60,
            held_type=0,
            held_ptr=0,
            contact_ptr=0xBA00,
            combat_phase=CombatPhase.HOLDING,
        )
        foe = MapEntity(
            kind="enemy",
            family="Signal",
            symbol="S",
            color="#fff",
            label="Signal",
            type_id=0x24,
            world_x=1327,
            world_y=64,
            world_z=0,
            map_x=208,
            map_y=64,
            health=4,
            slot="E2",
            primary_state=0x0500,
            combat_phase=CombatPhase.GRABBED,
            attacker_ptr=0xB800,
            target_ptr=0xB800,
        )
        ctx = context_from_player(me, (me, foe), player_index=1)
        self.assertTrue(ctx.holding)
        self.assertTrue(ctx.enemy_grab)
        intent = decide_held(me, ctx, GrabMemory(), tick=0, profile=PROFILES[0])
        assert intent is not None
        self.assertTrue(intent.attack)

        def put_u8(b, o, v):
            b[o] = v & 0xFF

        def put_u16(b, o, v):
            b[o : o + 2] = (v & 0xFFFF).to_bytes(2, "big")

        g, t, o = bytearray(0x40), bytearray(4), bytearray(0x100)
        put_u16(g, 0x00, 0x0016)
        put_u8(g, 0x18, 0x01)
        put_u8(g, 0x1E, 0x00)
        put_u8(g, 0x20, 0x03)
        put_u8(g, 0x21, 0x01)
        put_u16(t, 0, 0x0040)
        put_u8(o, OBJ_TYPE, 0x01)
        put_u16(o, OBJ_HEALTH, MAX_HEALTH)
        put_u8(o, OBJ_CHARACTER_ID, 0x00)
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
            entities=(me, foe),
        )
        d = decide_actions(
            replace(snap, world_map=world),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertTrue(d.p1_mask & int(ATTACK), d.p1_note)
        self.assertTrue(
            "knee" in d.p1_note or "throw" in d.p1_note,
            d.p1_note,
        )

    def test_grab_always_throws(self) -> None:
        from sor_autoplay.agent.characters import PROFILES

        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x20,
            action_state=0x28,
            map_x=100,
            map_y=64,
        )
        ctx = context_from_player(me)
        mem = GrabMemory()
        notes = []
        saw_atk = False
        for t in range(12):
            intent = decide_held(
                me,
                ctx,
                mem,
                tick=t,
                foe=None,
                progress_right=True,
                crowd=0,
                profile=PROFILES[0],
            )
            assert intent is not None
            notes.append(intent.note)
            if intent.attack:
                saw_atk = True
        self.assertTrue(saw_atk, notes)
        self.assertTrue(any("throw" in n for n in notes), notes)

    def test_weapon_bat_swings(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x0A,  # bat
            action_state=0x32,
            map_x=100,
            map_y=64,
        )
        foe = _e(map_x=120, map_y=64, family="Garcia")
        ctx = context_from_player(me)
        self.assertTrue(ctx.weapon)
        mem = GrabMemory()
        # Pulse: one of two consecutive ticks must swing with attack.
        a = decide_held(me, ctx, mem, tick=1, foe=foe, crowd=1)
        b = decide_held(me, ctx, mem, tick=2, foe=foe, crowd=1)
        assert a is not None and b is not None
        self.assertTrue(a.attack or b.attack)
        self.assertTrue("swing" in a.note or "swing" in b.note)

    def test_weapon_without_foe_does_not_attack_or_latch_as_grab(self) -> None:
        for held_type in (0x08, 0x0A):  # throwable and melee
            with self.subTest(held_type=held_type):
                me = _e(
                    kind="player",
                    family="Player",
                    slot="P1",
                    held_type=held_type,
                    held_ptr=0xBA00,
                    action_state=0x32,
                )
                memory = GrabMemory()
                self.assertFalse(me.is_grabbing)
                self.assertIsNone(
                    decide_held(
                        me,
                        context_from_player(me),
                        memory,
                        tick=1,
                        foe=None,
                    )
                )
                self.assertFalse(memory.latched)

    def test_throwable_weapon_waits_for_live_usable_range(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x08,
            action_state=0x32,
            map_x=100,
            map_y=64,
        )
        far = _e(map_x=230, map_y=64)
        off_lane = _e(map_x=150, map_y=90)
        for foe in (far, off_lane):
            with self.subTest(foe=foe.map_x, lane=foe.map_y):
                self.assertIsNone(
                    decide_held(
                        me,
                        context_from_player(me),
                        GrabMemory(),
                        tick=1,
                        foe=foe,
                    )
                )

    def test_weapon_does_not_repeat_attack_during_weapon_animation(self) -> None:
        foe = _e(map_x=120, map_y=64)
        for action in (0x44, 0x6A):
            with self.subTest(action=action):
                me = _e(
                    kind="player",
                    family="Player",
                    slot="P1",
                    held_type=0x0A,
                    held_ptr=0xBA00,
                    action_state=action,
                    map_x=100,
                    map_y=64,
                )
                intent = decide_held(
                    me,
                    context_from_player(me),
                    GrabMemory(),
                    tick=1,
                    foe=foe,
                )
                assert intent is not None
                self.assertFalse(intent.attack, intent.note)
                self.assertIn("weapon anim", intent.note)

    def test_released_weapon_pointer_is_not_an_enemy_grab(self) -> None:
        # Live pepper spray clears +$60 while action $45 still leaves +$5E
        # pointing at its projectile. That pointer previously latched the
        # knee/throw tree and generated hundreds of B presses into empty air.
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0,
            held_ptr=0xCD00,
            action_state=0x45,
        )
        ctx = context_from_player(me)
        self.assertFalse(ctx.weapon)
        self.assertFalse(ctx.enemy_grab)
        self.assertFalse(ctx.holding)
        self.assertFalse(me.is_holding)
        self.assertFalse(me.is_grabbing)
        self.assertIsNone(decide_held(me, ctx, GrabMemory(), tick=1))

    def test_grab_throws_immediately_when_an_enemy_can_interrupt(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x20,
            action_state=0x60,
            map_x=100,
            map_y=64,
        )
        intent = decide_held(
            me,
            context_from_player(me),
            GrabMemory(),
            tick=1,
            foe=_e(map_x=140, map_y=64),
            crowd=2,
        )
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertIn("throw", intent.note)

    def test_knife_throw_at_midrange(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x08,
            map_x=100,
            map_y=64,
        )
        foe = _e(map_x=150, map_y=64)
        mem = GrabMemory()
        a = decide_held(me, context_from_player(me), mem, tick=1, foe=foe, crowd=1)
        b = decide_held(me, context_from_player(me), mem, tick=2, foe=foe, crowd=1)
        assert a is not None and b is not None
        self.assertTrue(a.right and b.right)
        self.assertTrue(a.attack or b.attack)
        self.assertTrue(
            any(k in a.note or k in b.note for k in ("weapon", "dump", "use"))
        )

    def test_action_family_alone_is_not_a_hold(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0,
            held_ptr=0,
            action_state=0x28,
            map_x=100,
            map_y=64,
        )
        ctx = context_from_player(me)
        self.assertFalse(ctx.holding)
        self.assertFalse(ctx.enemy_grab)

    def test_stale_contact_pointer_alone_is_not_a_hold(self) -> None:
        me = MapEntity(
            kind="player",
            family="Player",
            symbol="1",
            color="#fff",
            label="P1",
            type_id=1,
            world_x=100,
            world_y=64,
            world_z=0,
            map_x=100,
            map_y=64,
            health=80,
            slot="P1",
            action_state=0x60,
            contact_ptr=0xBA00,
        )
        ctx = context_from_player(me)
        self.assertFalse(ctx.holding)
        self.assertFalse(ctx.enemy_grab)

        intent = decide_held(me, ctx, GrabMemory(), tick=0)
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertIn("release stale contact", intent.note)

        transitioning = replace(me, action_state=0x6A)
        self.assertIsNone(
            decide_held(
                transitioning,
                context_from_player(transitioning),
                GrabMemory(),
                tick=1,
            )
        )

    def test_hold_latch_expires_even_if_reaction_action_persists(self) -> None:
        from sor_autoplay.agent.characters import PROFILES

        strong = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0x20,
            action_state=0x60,
        )
        stale = _e(
            kind="player",
            family="Player",
            slot="P1",
            held_type=0,
            action_state=0x6E,
        )
        mem = GrabMemory()
        self.assertIsNotNone(
            decide_held(strong, context_from_player(strong), mem, tick=0, profile=PROFILES[0])
        )
        self.assertIsNotNone(
            decide_held(stale, context_from_player(stale), mem, tick=1, profile=PROFILES[0])
        )
        self.assertIsNone(
            decide_held(stale, context_from_player(stale), mem, tick=2, profile=PROFILES[0])
        )
        self.assertFalse(mem.latched)

    def test_want_grab_when_close(self) -> None:
        me = _e(kind="player", family="Player", map_x=100, map_y=64)
        foe = _e(map_x=120, map_y=64)  # 20px in band 18..26
        self.assertTrue(want_grab_approach(me, foe, grab_bias=0.4))
        self.assertFalse(want_grab_approach(me, foe, grab_bias=0.05))
        self.assertFalse(want_grab_approach(me, foe, grab_bias=0.3))  # threshold 0.35


class PolicyIntegrationTests(unittest.TestCase):
    def _snap(self, entities: tuple[MapEntity, ...], **kwargs: object):
        # Reuse test helpers from test_agent via minimal local construction.
        from dataclasses import replace

        from sor_autoplay.memory_map import (
            MAX_HEALTH,
            OBJ_CHARACTER_ID,
            OBJ_HEALTH,
            OBJ_POS_X,
            OBJ_POS_Y,
            OBJ_TYPE,
        )
        from sor_autoplay.state import snapshot_from_memory_blocks

        def put_u8(buf: bytearray, off: int, v: int) -> None:
            buf[off] = v & 0xFF

        def put_u16(buf: bytearray, off: int, v: int) -> None:
            buf[off : off + 2] = (v & 0xFFFF).to_bytes(2, "big")

        g = bytearray(0x40)
        t = bytearray(4)
        o = bytearray(0x100)
        put_u16(g, 0x00, 0x0016)
        put_u8(g, 0x18, 0x01)
        put_u8(g, 0x1E, 0x00)
        put_u8(g, 0x20, 0x03)
        put_u8(g, 0x21, 0x02)
        put_u16(t, 0, 0x0040)
        put_u8(o, OBJ_TYPE, 0x01)
        put_u16(o, OBJ_HEALTH, MAX_HEALTH)
        put_u8(o, OBJ_CHARACTER_ID, 0x00)
        put_u16(o, OBJ_POS_X, 100)
        put_u16(o, OBJ_POS_Y, 0x40)
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(g),
            timer_block=bytes(t),
            objects_block=bytes(o),
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

    def test_dodges_jack_projectile(self) -> None:
        p1 = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64, label="P1")
        proj = _e(
            kind="projectile",
            family="Jack",
            type_id=0x28,
            map_x=120,
            map_y=64,
            health=None,
            label="axe",
        )
        snap = self._snap((p1, proj))
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertIn("dodge", decision.p1_note)
        # Should move, not special.
        self.assertFalse(decision.p1_mask & 0x10)  # not A alone as special priority

    def test_grab_hold_throws(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            held_type=0x20,
            action_state=0x28,
            label="P1",
        )
        snap = self._snap((p1,))
        mem = AgentState()
        notes = []
        saw_attack = False
        for _ in range(12):
            decision = decide_actions(snap, AgentConfig(p1_enabled=True), mem)
            notes.append(decision.p1_note)
            if decision.p1_mask & int(ATTACK):
                saw_attack = True
        self.assertTrue(saw_attack, notes)
        self.assertTrue(any("throw" in n for n in notes), notes)

    def test_holding_weapon_on_clear_screen_progresses_without_attacking(self) -> None:
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            held_type=0x0A,
            held_ptr=0xBA00,
            action_state=0x32,
            label="P1",
        )
        decision = decide_actions(
            self._snap((p1,)), AgentConfig(p1_enabled=True), AgentState()
        )
        self.assertFalse(decision.p1_mask & int(ATTACK), decision.p1_note)
        self.assertTrue(decision.p1_mask & 0x08, decision.p1_note)

    def test_signal_priority_over_far_garcia(self) -> None:
        from sor_autoplay.agent.combat import select_target
        from sor_autoplay.agent.characters import PROFILES

        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64)
        far_g = _e(family="Garcia", map_x=200, map_y=64, slot="E0")
        near_s = _e(family="Signal", type_id=0x24, map_x=130, map_y=64, slot="E1")
        choice = select_target(me, (far_g, near_s), PROFILES[0])
        assert choice is not None
        self.assertEqual(choice.entity.family, "Signal")


if __name__ == "__main__":
    unittest.main()
