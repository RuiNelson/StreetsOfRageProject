"""EngageAbadede and the Abadede hold loop, wired through the pipeline.

``test_abadede`` pins the ROM model and the plan; this pins who owns him in
``decide``, how he ranks in ``priority`` -- including the round's grunt, which
the street keeps alive behind the actor through the whole fight (user:
"existe sempre um Grunt atrás da personagem controlada ... a AI deve-se
proteger desse inimigo, sem se desviar o objetivo principal, o boss") -- and
what ``execute`` presses.
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import abadede as abadede_plan
from sor_autoplay.ai.decide import (
    could_engage_abadede,
    could_grab_enemy,
    could_hold_actions,
    could_jump_attack,
    could_punch,
    could_walk_to_near_enemy,
    could_walk_to_weapon,
)
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    Abadede,
    AttackHeldEnemy,
    CameraRange,
    EngageAbadede,
    Garcia,
    Myself,
    Punch,
    ReleaseToRegrab,
    Verb,
    Weapon,
    find_all,
)
from sor_autoplay.memory_map import PLAYER_KNEE_CHAIN_BIT
from sor_autoplay.phases import CombatPhase

CAMERA = CameraRange(left=32, right=288, top=0, bottom=112)
UP, DOWN, LEFT, RIGHT, B = 0x0001, 0x0002, 0x0004, 0x0008, 0x0020


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


def _abadede(world_x: int = 200, world_y: int = 60, **overrides) -> Abadede:
    fields = dict(
        slot="obj00", type_id=0x30, world_x=world_x, world_y=world_y, health=32,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        primary_state=abadede_plan.PRIMARY_APPROACH, substate=abadede_plan.SUB_RUN,
        screen_x=world_x + 0x80, anim=0x06, boss_vel_x=-6.0, boss_vel_lane=6.0,
        fine_x=float(world_x), fine_y=float(world_y),
    )
    fields.update(overrides)
    return Abadede(**fields)


def _run(world_x: int, world_y: int = 60) -> Abadede:
    return _abadede(
        world_x, world_y, primary_state=abadede_plan.PRIMARY_CHARGE,
        substate=abadede_plan.SUB_RUN, anim=0x0A, boss_vel_x=-12.0, boss_vel_lane=0.0,
        combat_phase=CombatPhase.CHARGE,
    )


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
    """Every generic verb stands down for him; EngageAbadede is the fight."""

    def test_the_engage_is_offered_armed_or_not(self) -> None:
        for weapon in (0, 0x0B):
            with self.subTest(weapon=weapon):
                verbs = _infer(could_engage_abadede)({_myself(held_weapon_type=weapon), _abadede()})
                self.assertEqual({type(v) for v in verbs}, {EngageAbadede})

    def test_not_while_holding_airborne_or_once_dying(self) -> None:
        holding = _myself(action_state=0x60, held_enemy_slot="obj00")
        self.assertEqual(_infer(could_engage_abadede)({holding, _abadede()}), set())
        airborne = _myself(action_state=0x12, is_airborne=True)
        self.assertEqual(_infer(could_engage_abadede)({airborne, _abadede()}), set())
        dying = _abadede(primary_state=abadede_plan.PRIMARY_DYING, combat_phase=CombatPhase.DEATH)
        self.assertEqual(_infer(could_engage_abadede)({_myself(), dying}), set())

    def test_no_strike_grab_hop_or_walk_aims_at_him(self) -> None:
        me = _myself(140, 60)
        near = _abadede(170, 60, primary_state=abadede_plan.PRIMARY_PAUSE, timer_54=4)
        for generator in (could_punch, could_grab_enemy, could_walk_to_near_enemy, could_jump_attack):
            with self.subTest(generator=generator.__name__):
                verbs = _infer(generator)({me, near, CAMERA})
                self.assertFalse(
                    [v for v in verbs if getattr(v, "target_slot", None) == near.slot],
                    f"{generator.__name__} aimed at him: {verbs}",
                )

    def test_no_weapon_detour_while_he_lives(self) -> None:
        pipe = Weapon(slot="obj07", world_x=120, world_y=60, weapon_type=0x0B, wear=0)
        verbs = _infer(could_walk_to_weapon)({_myself(), _abadede(), pipe, CAMERA})
        self.assertEqual(verbs, set())


class HoldLoopTests(unittest.TestCase):
    """A held Abadede runs Souther's loop, on the updates his hold reads."""

    def _holding(self, knees: int) -> Myself:
        last = {0: 0, 1: 0x6A, 2: 0x6C}[knees]
        return _myself(
            action_state=0x60,
            combat_phase=CombatPhase.HOLDING,
            held_enemy_slot="obj00",
            action_flags=PLAYER_KNEE_CHAIN_BIT if knees else 0,
            knee_chain_last=last,
        )

    def _held(self, substate: int = abadede_plan.HELD_READING) -> Abadede:
        return _abadede(
            184, 60, combat_phase=CombatPhase.GRABBED,
            primary_state=abadede_plan.PRIMARY_HELD, substate=substate, timer_54=40,
        )

    def test_a_hold_he_reads_is_kneed(self) -> None:
        verbs = _infer(could_hold_actions)({self._holding(0), self._held()})
        self.assertEqual({type(v) for v in verbs}, {AttackHeldEnemy})

    def test_while_he_shakes_off_a_knee_nothing_is_pressed(self) -> None:
        verbs = _infer(could_hold_actions)(
            {self._holding(1), self._held(abadede_plan.HELD_KNEE_SHAKING)}
        )
        self.assertEqual(verbs, set())

    def test_after_two_knees_it_lets_him_go_to_take_him_again(self) -> None:
        verbs = _infer(could_hold_actions)({self._holding(2), self._held()})
        self.assertEqual({type(v) for v in verbs}, {ReleaseToRegrab})


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
            me, _abadede(260, 60), grunt,
            EngageAbadede(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageAbadede)

    def test_a_grunts_committed_strike_is_punched_first(self) -> None:
        me = _myself(140, 60)
        grunt = _grunt(160, 60, combat_phase=CombatPhase.ATTACKING)
        winner = self._winner({
            me, _abadede(260, 60), grunt,
            EngageAbadede(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, Punch)

    def test_not_while_his_run_is_pressing(self) -> None:
        me = _myself(140, 60)
        grunt = _grunt(160, 60, combat_phase=CombatPhase.ATTACKING)
        winner = self._winner({
            me, _run(260, 60), grunt,
            EngageAbadede(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageAbadede)


class ExecuteTests(unittest.TestCase):
    def test_it_holds_the_plans_stick(self) -> None:
        me = _myself(100, 60)
        boss = _abadede(200, 20)
        context = {me, boss, CAMERA}
        plan = abadede_plan.plan_engage(me, boss, camera=CAMERA)
        self.assertFalse(plan.punch)
        gamepad, _ = _gamepad()
        execute_verb(EngageAbadede(actor_slot="P1", target_slot="obj00"), context, gamepad)
        expected = (
            (RIGHT if plan.dir_x > 0 else LEFT if plan.dir_x < 0 else 0)
            | (DOWN if plan.dir_y > 0 else UP if plan.dir_y < 0 else 0)
        )
        self.assertEqual(gamepad.held, expected)

    def test_a_close_run_on_the_lane_is_punched_toward_him(self) -> None:
        me = _myself(100, 60)
        boss = _run(200, 60)
        gamepad, client = _gamepad()
        execute_verb(EngageAbadede(actor_slot="P1", target_slot="obj00"), {me, boss, CAMERA}, gamepad)
        pressed = [
            call.kwargs.get("player1", 0) for call in client.press_buttons.call_args_list
        ]
        self.assertTrue(any(mask & B and mask & RIGHT for mask in pressed), pressed)

    def test_armed_it_never_presses_b_at_him(self) -> None:
        me = _myself(100, 60, held_weapon_type=0x0B)
        boss = _run(200, 60)
        gamepad, client = _gamepad()
        execute_verb(EngageAbadede(actor_slot="P1", target_slot="obj00"), {me, boss, CAMERA}, gamepad)
        pressed = [
            call.kwargs.get("player1", 0) for call in client.press_buttons.call_args_list
        ]
        self.assertFalse(any(mask & B for mask in pressed), pressed)


if __name__ == "__main__":
    unittest.main()
