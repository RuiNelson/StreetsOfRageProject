"""EngageBongo and the Bongo hold loop, wired through the pipeline.

``test_bongo`` pins the ROM model and the plan; this pins who owns him in
``decide``, how he ranks in ``priority`` -- including the round's grunt, which
the street keeps alive through the whole fight (user: "não se focar nesse
inimigo, mas prevenir ataques iminentes") -- and what ``execute`` presses.
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import bongo as bongo_plan
from sor_autoplay.ai.decide import (
    could_engage_bongo,
    could_grab_enemy,
    could_hold_actions,
    could_jump_attack,
    could_projectile_sidestep,
    could_punch,
    could_walk_to_near_enemy,
    could_walk_to_weapon,
)
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    Bongo,
    CameraRange,
    EngageBongo,
    Garcia,
    Myself,
    Projectile,
    Punch,
    ReleaseToRegrab,
    ThrowHeldEnemy,
    Verb,
    Weapon,
    find_all,
)
from sor_autoplay.memory_map import PLAYER_KNEE_CHAIN_BIT
from sor_autoplay.phases import CombatPhase

CAMERA = CameraRange(left=32, right=288, top=0, bottom=112)
UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008


def _infer(generator):
    return lambda context: generator(generate_inference_tokens(set(context)))


def _myself(world_x: int = 160, world_y: int = 60, **overrides) -> Myself:
    fields = dict(
        slot="P1", player_index=1, character_id=2, character_name="Blaze",
        world_x=world_x, world_y=world_y, health=80, health_percent=100.0, lives=3,
        specials=1, held_weapon_type=0, facing_left=False,
        combat_phase=CombatPhase.NORMAL, action_state=0x02, is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def _bongo(world_x: int = 200, world_y: int = 60, **overrides) -> Bongo:
    fields = dict(
        slot="obj00", type_id=0x57, world_x=world_x, world_y=world_y, health=30,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        primary_state=1, screen_x=world_x + 0x80, anim=0x02, anim_countdown=10,
        body_box_id=0x94,
    )
    fields.update(overrides)
    return Bongo(**fields)


def _grunt(world_x: int, world_y: int = 60, **overrides) -> Garcia:
    fields = dict(
        slot="obj05", type_id=0x20, world_x=world_x, world_y=world_y, health=20,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
    )
    fields.update(overrides)
    return Garcia(**fields)


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    return VirtualGamepad(SharedGamepadState(client), player_index=1), client


class OwnershipTests(unittest.TestCase):
    """Every generic verb stands down for him; EngageBongo is the fight."""

    def test_the_engage_is_offered_armed_or_not(self) -> None:
        for weapon in (0, 0x0B):
            with self.subTest(weapon=weapon):
                verbs = _infer(could_engage_bongo)({_myself(held_weapon_type=weapon), _bongo()})
                self.assertEqual({type(v) for v in verbs}, {EngageBongo})

    def test_not_while_holding_or_airborne(self) -> None:
        holding = _myself(action_state=0x60, held_enemy_slot="obj00")
        self.assertEqual(_infer(could_engage_bongo)({holding, _bongo()}), set())
        airborne = _myself(action_state=0x12, is_airborne=True)
        self.assertEqual(_infer(could_engage_bongo)({airborne, _bongo()}), set())

    def test_no_strike_grab_hop_or_walk_aims_at_him(self) -> None:
        me = _myself(140, 60)
        near = _bongo(170, 60)
        for generator in (could_punch, could_grab_enemy, could_walk_to_near_enemy, could_jump_attack):
            with self.subTest(generator=generator.__name__):
                verbs = _infer(generator)({me, near, CAMERA})
                self.assertFalse(
                    [v for v in verbs if getattr(v, "target_slot", None) == near.slot],
                    f"{generator.__name__} aimed at him: {verbs}",
                )

    def test_his_flame_is_never_sidestepped_on_its_own(self) -> None:
        flame = Projectile(
            slot="obj01", world_x=170, world_y=64, vel_x=-4.0, vel_z=0.0,
            type_id=bongo_plan.FLAME_TYPE, state=1,
        )
        verbs = _infer(could_projectile_sidestep)({_myself(150, 60), _bongo(190, 60), flame})
        self.assertEqual(verbs, set())

    def test_no_weapon_detour_while_he_lives(self) -> None:
        pipe = Weapon(slot="obj07", world_x=120, world_y=60, weapon_type=0x0B, wear=0)
        verbs = _infer(could_walk_to_weapon)({_myself(), _bongo(), pipe, CAMERA})
        self.assertEqual(verbs, set())


class HoldLoopTests(unittest.TestCase):
    """A held Bongo runs Souther's loop: knee, knee, release, walk back in."""

    def _holding(self, knees: int) -> Myself:
        last = {0: 0, 1: 0x6A, 2: 0x6C}[knees]
        return _myself(
            action_state=0x60,
            held_enemy_slot="obj00",
            action_flags=PLAYER_KNEE_CHAIN_BIT if knees else 0,
            knee_chain_last=last,
        )

    def _held(self) -> Bongo:
        return _bongo(192, 60, combat_phase=CombatPhase.RECOVERY, primary_state=4, body_box_id=0x99)

    def test_a_fresh_hold_knees(self) -> None:
        verbs = _infer(could_hold_actions)({self._holding(0), self._held()})
        self.assertEqual({type(v) for v in verbs}, {AttackHeldEnemy})

    def test_after_two_knees_it_lets_him_go_to_take_him_again(self) -> None:
        verbs = _infer(could_hold_actions)({self._holding(2), self._held()})
        self.assertEqual({type(v) for v in verbs}, {ReleaseToRegrab})

    def test_a_grunt_striking_from_behind_gets_him_thrown_into_it(self) -> None:
        # The round's grunt behind the holder, its strike committed and about
        # to land: sooner than a knee, so the body in hand goes back into it.
        holder = self._holding(0)
        grunt = _grunt(144, 60, facing_left=False, combat_phase=CombatPhase.ATTACKING)
        verbs = _infer(could_hold_actions)({holder, self._held(), grunt})
        self.assertEqual({type(v) for v in verbs}, {ThrowHeldEnemy})

    def test_a_quiet_grunt_leaves_the_loop_alone(self) -> None:
        holder = self._holding(0)
        grunt = _grunt(100, 60, facing_left=False)
        verbs = _infer(could_hold_actions)({holder, self._held(), grunt})
        self.assertEqual({type(v) for v in verbs}, {AttackHeldEnemy})


class RankingTests(unittest.TestCase):
    """The engage's tier, and the grunt the round never runs out of."""

    def _winner(self, context) -> Verb:
        verbs = find_all(determine_priority_verb(set(context)), Verb)
        self.assertEqual(len(verbs), 1)
        return verbs[0]

    def test_the_engage_outranks_a_punch_on_a_quiet_grunt(self) -> None:
        me = _myself(140, 60)
        grunt = _grunt(170, 60)
        winner = self._winner({
            me, _bongo(260, 60), grunt,
            EngageBongo(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageBongo)

    def test_a_grunts_committed_strike_is_punched_first(self) -> None:
        me = _myself(140, 60)
        grunt = _grunt(160, 60, combat_phase=CombatPhase.ATTACKING)
        winner = self._winner({
            me, _bongo(260, 60), grunt,
            EngageBongo(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, Punch)

    def test_not_while_his_charge_is_pressing(self) -> None:
        me = _myself(140, 60)
        grunt = _grunt(160, 60, combat_phase=CombatPhase.ATTACKING)
        charging = _bongo(260, 60, primary_state=2, tactical=3)
        winner = self._winner({
            me, charging, grunt,
            EngageBongo(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageBongo)


class ExecuteTests(unittest.TestCase):
    def test_it_holds_the_plans_stick(self) -> None:
        me = _myself(100, 60)
        bongo = _bongo(200, 60)
        context = {me, bongo, CAMERA}
        plan = bongo_plan.plan_engage(me, bongo, camera=CAMERA, projectiles=[])
        gamepad, client = _gamepad()
        execute_verb(EngageBongo(actor_slot="P1", target_slot="obj00"), context, gamepad)
        expected = (
            (RIGHT if plan.dir_x > 0 else LEFT if plan.dir_x < 0 else 0)
            | (DOWN if plan.dir_y > 0 else UP if plan.dir_y < 0 else 0)
        )
        self.assertEqual(gamepad.held, expected)


if __name__ == "__main__":
    unittest.main()
