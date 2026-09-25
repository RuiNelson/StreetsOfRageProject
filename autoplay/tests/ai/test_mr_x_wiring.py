"""EngageMrX, wired through the pipeline.

``test_mr_x`` pins the ROM model and the plan; this pins who owns Mr. X in
``decide`` (every generic verb stands down for him), what is refused while he
lives (the twins' rules -- "Do not call the police. Do not use recovery
items" -- kept for "o mesmo tipo de optimização"), his bullets left to the
engage, the hold loop's verbs, and what ``execute`` presses.
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import mr_x as model
from sor_autoplay.ai.decide import (
    could_call_police,
    could_engage_mr_x,
    could_grab_enemy,
    could_hold_actions,
    could_jump_attack,
    could_projectile_sidestep,
    could_punch,
    could_rear_attack,
    could_walk_to_near_enemy,
    could_walk_to_pickup,
    live_mr_x,
)
from sor_autoplay.ai.execute import engage_mr_x_plan, execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    CameraRange,
    EngageMrX,
    FightMrXOffice,
    HealthPickup,
    Garcia,
    Myself,
    MrX,
    MrXOffice,
    Projectile,
    ReleaseToRegrab,
    ThrowHeldEnemy,
    Verb,
    find_all,
)
from sor_autoplay.phases import CombatPhase

CAM_X = 128
CAMERA = CameraRange(left=CAM_X + 0x20, right=CAM_X + 0x120, top=0, bottom=112)
FLOOR = model.FLOOR_ROUND_8
UP, DOWN, LEFT, RIGHT, A, B, C = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040


def _fixed(value: float) -> bytes:
    return int(round(value * 65536)).to_bytes(4, "big", signed=True)


def _mr_x_raw(x: float, y: float, *, primary: int = model.PRIMARY_DECIDE, sub: int = 1,
              t54: int = 10, anim: int = model.ANIM_WALK, hp: int = 50) -> bytes:
    raw = bytearray(128)
    raw[0] = model.MR_X_TYPE
    raw[0x02], raw[0x03] = 0, 0x38
    raw[0x08:0x0A] = anim.to_bytes(2, "big")
    raw[0x10:0x14] = _fixed(x)
    raw[0x14:0x18] = _fixed(y)
    raw[0x18:0x1C] = _fixed(FLOOR)
    raw[0x28:0x2A] = (int(x) - CAM_X + 0x80).to_bytes(2, "big")
    raw[0x30] = primary
    raw[0x32:0x34] = hp.to_bytes(2, "big")
    raw[0x34] = 34
    raw[0x54:0x56] = t54.to_bytes(2, "big")
    raw[0x5B] = sub
    return bytes(raw)


def _player_raw(x: float, y: float, *, action: int = 0x02, facing_left: bool = False) -> bytes:
    raw = bytearray(128)
    raw[0] = 1
    raw[0x09] = 0x02 if facing_left else 0
    raw[0x10:0x14] = _fixed(x)
    raw[0x14:0x18] = _fixed(y)
    raw[0x18:0x1A] = FLOOR.to_bytes(2, "big")
    raw[0x30] = action | (1 if facing_left else 0)
    raw[0x50] = 2  # Blaze
    # +$70: the idle body $4F/$50 where it stands.
    body = (2, 12) if not facing_left else (-12, -2)
    for i, v in enumerate((int(x) + body[0], int(x) + body[1], int(y) - 8, int(y) + 8, FLOOR - 48, FLOOR)):
        raw[0x70 + 2 * i : 0x72 + 2 * i] = v.to_bytes(2, "big", signed=True)
    return bytes(raw)


def _myself(x: float = 300.0, y: float = 60.0, **overrides) -> Myself:
    facing_left = overrides.pop("facing_left", False)
    action = overrides.pop("action_state", 0x02)
    fields = dict(
        slot="P1", player_index=1, character_id=2, character_name="Blaze",
        world_x=int(x), world_y=int(y), world_z=FLOOR, ground_z=FLOOR, health=80,
        health_percent=100.0, lives=3, specials=1, held_weapon_type=0, facing_left=facing_left,
        combat_phase=CombatPhase.NORMAL, action_state=action, is_airborne=False,
        fine_x=float(x), fine_y=float(y), raw=_player_raw(x, y, action=action, facing_left=facing_left),
    )
    fields.update(overrides)
    return Myself(**fields)


def _mr_x(x: float, y: float = 60.0, **raw_fields) -> MrX:
    raw = _mr_x_raw(x, y, **raw_fields)
    return MrX(
        slot="obj04", type_id=model.MR_X_TYPE, world_x=int(x), world_y=int(y),
        health=raw_fields.get("hp", 50), combat_phase=CombatPhase.NORMAL, targets_player=1,
        facing_left=True, primary_state=raw[0x30], substate=raw[0x5B], raw=raw,
        fine_x=float(x), fine_y=float(y),
    )


def _garcia(x: float, y: float, *, slot: str = "obj06", state: int = 0x09, hp: int = 9) -> Garcia:
    """A type-$22 Garcia whose bytes start his approach (state 9, entry)."""

    raw = bytearray(128)
    raw[0] = 0x22
    raw[0x01] = 0x04
    raw[0x03] = 0x01
    raw[0x0C], raw[0x0D] = 5, 1
    raw[0x10:0x14] = _fixed(x)
    raw[0x14:0x18] = _fixed(y)
    raw[0x18:0x1C] = _fixed(FLOOR)
    raw[0x28:0x2A] = (int(x) - CAM_X + 0x80).to_bytes(2, "big")
    raw[0x30] = state
    raw[0x32:0x34] = hp.to_bytes(2, "big")
    return Garcia(
        slot=slot, type_id=0x22, world_x=int(x), world_y=int(y), health=hp,
        combat_phase=CombatPhase.GRABBED if state == 0x05 else CombatPhase.NORMAL, targets_player=1,
        facing_left=True, raw=bytes(raw),
    )


def _infer(generator):
    return lambda context: generator(generate_inference_tokens(set(context)))


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    return VirtualGamepad(SharedGamepadState(client), player_index=1), client


class OwnershipTests(unittest.TestCase):
    def test_one_engage_for_him(self) -> None:
        verbs = _infer(could_engage_mr_x)({_myself(), _mr_x(420.0), CAMERA})
        self.assertEqual([type(v) for v in verbs], [EngageMrX])

    def test_no_engage_on_mr_x_without_him(self) -> None:
        # The office's first waves (user: "A IA emite EngageMrX, mesmo quando
        # o Mr. X não está no contexto"): his helpers are the office verb's,
        # aimed at the nearest of them, and no EngageMrX names a boss who is
        # not there.
        near, far = _garcia(340.0, 60.0, slot="obj06"), _garcia(460.0, 60.0, slot="obj07")
        verbs = _infer(could_engage_mr_x)({_myself(), near, far, MrXOffice(), CAMERA})
        self.assertEqual([type(v) for v in verbs], [FightMrXOffice])
        self.assertEqual(next(iter(verbs)).target_slot, "obj06")

    def test_nothing_outside_his_office(self) -> None:
        # A type-$22 Garcia anywhere else is an ordinary grunt.
        verbs = _infer(could_engage_mr_x)({_myself(), _garcia(340.0, 60.0), CAMERA})
        self.assertEqual(verbs, set())

    def test_with_him_in_the_room_only_the_engage(self) -> None:
        verbs = _infer(could_engage_mr_x)({_myself(), _mr_x(420.0), _garcia(340.0, 60.0), MrXOffice(), CAMERA})
        self.assertEqual([type(v) for v in verbs], [EngageMrX])

    def test_not_when_he_is_dying(self) -> None:
        dying = _mr_x(420.0, primary=model.PRIMARY_DYING)
        self.assertEqual(live_mr_x({dying}), [])

    def test_no_generic_verb_aims_at_him(self) -> None:
        me = _myself(300.0, 60.0)
        him = _mr_x(330.0, 60.0)
        for generator in (could_punch, could_grab_enemy, could_walk_to_near_enemy, could_jump_attack, could_rear_attack):
            with self.subTest(generator=generator.__name__):
                verbs = _infer(generator)({me, him, CAMERA})
                self.assertFalse([v for v in verbs if getattr(v, "target_slot", None) == "obj04"])

    def test_no_police_and_no_food_while_he_lives(self) -> None:
        dying = _myself(health=4, health_percent=5.0, lives=1)
        self.assertEqual(_infer(could_call_police)({dying, _mr_x(420.0), CAMERA}), set())
        food = HealthPickup(slot="obj10", world_x=290, world_y=60, pickup_type=0x47, health_delta=80)
        verbs = _infer(could_walk_to_pickup)({_myself(health=20, health_percent=25.0), _mr_x(420.0), food, CAMERA})
        self.assertEqual(verbs, set())

    def test_his_bullets_are_the_engages(self) -> None:
        bullet = Projectile(
            slot="obj13", world_x=330, world_y=60, vel_x=-24.0, vel_z=0.0,
            type_id=model.BULLET_TYPE, state=1, raw=bytes(128),
        )
        verbs = _infer(could_projectile_sidestep)({_myself(), _mr_x(420.0), bullet, CAMERA})
        self.assertEqual(verbs, set())


class RankingTests(unittest.TestCase):
    def test_the_engage_wins_the_tick(self) -> None:
        from sor_autoplay.ai.decide import generate_verb_tokens

        context = generate_verb_tokens(generate_inference_tokens({_myself(), _mr_x(420.0), CAMERA}))
        verbs = find_all(determine_priority_verb(set(context)), Verb)
        self.assertEqual([type(v) for v in verbs], [EngageMrX])


class HoldTests(unittest.TestCase):
    def _holding(self, *, knees: int, sub: int) -> set:
        me = _myself(300.0, 60.0, action_state=0x60, held_enemy_slot="obj04",
                     combat_phase=CombatPhase.HOLDING, knee_chain_last=knees)
        him = _mr_x(324.0, 60.0, primary=model.PRIMARY_HELD, sub=sub, t54=40)
        return _infer(could_hold_actions)({me, him, CAMERA})

    def test_a_knee_on_his_read(self) -> None:
        verbs = self._holding(knees=0, sub=1)
        self.assertEqual([type(v) for v in verbs], [AttackHeldEnemy])

    def test_nothing_while_he_shakes(self) -> None:
        self.assertEqual(self._holding(knees=0, sub=3), set())

    def test_a_garcia_over_him_before_a_knee_is_spent_lets_him_go(self) -> None:
        # Holding him on his read, a Garcia walks up from beyond him: his jab
        # lands before a knee, the release and a step fit -- no knee.
        me = _myself(300.0, 60.0, action_state=0x60, held_enemy_slot="obj04",
                     combat_phase=CombatPhase.HOLDING, knee_chain_last=0)
        him = _mr_x(324.0, 60.0, primary=model.PRIMARY_HELD, sub=1, t54=40)
        verbs = _infer(could_hold_actions)({me, him, _garcia(390.0, 60.0), MrXOffice(), CAMERA})
        self.assertEqual([type(v) for v in verbs], [ReleaseToRegrab])

    def test_far_off_the_knee_stands(self) -> None:
        me = _myself(300.0, 60.0, action_state=0x60, held_enemy_slot="obj04",
                     combat_phase=CombatPhase.HOLDING, knee_chain_last=0)
        him = _mr_x(324.0, 60.0, primary=model.PRIMARY_HELD, sub=1, t54=40)
        verbs = _infer(could_hold_actions)({me, him, _garcia(460.0, 100.0), MrXOffice(), CAMERA})
        self.assertEqual([type(v) for v in verbs], [AttackHeldEnemy])

    def test_a_garcia_in_hand_while_he_lives_is_thrown(self) -> None:
        me = _myself(300.0, 60.0, action_state=0x60, held_enemy_slot="obj06",
                     combat_phase=CombatPhase.HOLDING)
        held = _garcia(324.0, 60.0, state=0x05)
        verbs = _infer(could_hold_actions)({me, held, _mr_x(150.0, 60.0), MrXOffice(), CAMERA})
        self.assertEqual([type(v) for v in verbs], [ThrowHeldEnemy])

    def test_not_thrown_with_him_walking_in(self) -> None:
        # He walks in from 70 px on the holder's lane: the throw's 23 updates
        # would stand the actor in his lunge (measured live: 34, three times).
        me = _myself(300.0, 60.0, action_state=0x60, held_enemy_slot="obj06",
                     combat_phase=CombatPhase.HOLDING)
        held = _garcia(324.0, 60.0, state=0x05)
        him = _mr_x(230.0, 60.0, primary=model.PRIMARY_WALK_IN, sub=0)
        verbs = _infer(could_hold_actions)({me, held, him, MrXOffice(), CAMERA})
        self.assertEqual(len(verbs), 1)
        self.assertNotIsInstance(next(iter(verbs)), ThrowHeldEnemy)


class ExecuteTests(unittest.TestCase):
    def test_the_office_waves_play_the_plan(self) -> None:
        me = _myself(250.0, 60.0)
        verb = FightMrXOffice(actor_slot="P1", target_slot="obj06")
        context = {me, _garcia(400.0, 60.0), MrXOffice(), CAMERA}
        self.assertIsNotNone(engage_mr_x_plan(verb, context))
        gamepad, client = _gamepad()
        execute_verb(verb, context, gamepad)
        self.assertTrue(client.hold_buttons.called or client.press_buttons.called)

    def test_the_gun_is_walked_into(self) -> None:
        # He waits at the top lane for his gun: nothing of his is out, and the
        # stick walks the actor at him.
        me = _myself(250.0, 20.0)
        him = _mr_x(300.0, model.GUN_LANE, primary=model.PRIMARY_GUN, sub=2, t54=20, anim=model.ANIM_GUN_UP)
        verb = EngageMrX(actor_slot="P1", target_slot="obj04")
        gamepad, client = _gamepad()
        execute_verb(verb, {me, him, CAMERA}, gamepad)
        held = client.hold_buttons.call_args.kwargs["player1"]
        self.assertEqual(held & RIGHT, RIGHT)


if __name__ == "__main__":
    unittest.main()
