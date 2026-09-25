"""EngageJack and the Jack hold loop, wired through the pipeline.

``test_jack`` pins the ROM model and the plan; this pins who owns him in
``decide``, how he ranks in ``priority`` and what ``execute`` presses.
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import jack as jack_plan
from sor_autoplay.ai.decide import (
    could_engage_jack,
    could_hold_actions,
    could_projectile_sidestep,
)
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    CameraRange,
    EngageJack,
    Garcia,
    Jack,
    Myself,
    Projectile,
    ProjectileSidestep,
    Punch,
    Verb,
    WalkToNearEnemy,
    find_all,
)
from sor_autoplay.phases import CombatPhase

CAM_X = 2700
CAMERA = CameraRange(left=CAM_X + 0x20, right=CAM_X + 0x120, top=0, bottom=112)
UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008


def _infer(generator):
    return lambda context: generator(generate_inference_tokens(set(context)))


def _myself(world_x: int = 2760, world_y: int = 60, **overrides) -> Myself:
    fields = dict(
        slot="P1", player_index=1, character_id=2, character_name="Blaze",
        world_x=world_x, world_y=world_y, health=80, health_percent=100.0, lives=3,
        specials=1, held_weapon_type=0, facing_left=False,
        combat_phase=CombatPhase.NORMAL, action_state=0x02, is_airborne=False, world_z=160,
    )
    fields.update(overrides)
    return Myself(**fields)


def _jack(world_x: int = 2850, world_y: int = 60, **overrides) -> Jack:
    fields = dict(
        slot="obj00", type_id=0x27, world_x=world_x, world_y=world_y, health=9,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        has_projectile=True, state=jack_plan.ST_APPROACH, flags_31=0x01, stun_timer=100,
        world_z=160, animating=True, anim=0x02, approach_x=world_x, approach_y=world_y,
        approach_speed=0x200, screen_x=world_x - CAM_X + 0x80,
    )
    fields.update(overrides)
    return Jack(**fields)


def _grunt(world_x: int, world_y: int = 60, **overrides) -> Garcia:
    fields = dict(
        slot="obj05", type_id=0x20, world_x=world_x, world_y=world_y, health=20,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
    )
    fields.update(overrides)
    return Garcia(**fields)


def _released(world_x: int, world_y: int, owner: str = "obj00") -> Projectile:
    return Projectile(
        slot="obj06", world_x=world_x, world_y=world_y, vel_x=-10.0, vel_z=0.0,
        type_id=jack_plan.AXE_TYPE, state=jack_plan.AXE_THROWN, world_z=112, fine_z=112.0,
        owner_slot=owner, flags_31=0x03, attack_box_id=0x2B,
    )


class OwnershipTests(unittest.TestCase):
    def test_the_engage_is_offered_armed_or_not(self) -> None:
        for weapon in (0, 0x0B):
            with self.subTest(weapon=weapon):
                verbs = _infer(could_engage_jack)({_myself(held_weapon_type=weapon), _jack(), CAMERA})
                self.assertEqual({type(v) for v in verbs}, {EngageJack})

    def test_not_while_holding_or_airborne(self) -> None:
        holding = _myself(action_state=0x60, held_enemy_slot="obj05")
        self.assertEqual(_infer(could_engage_jack)({holding, _jack(), CAMERA}), set())
        airborne = _myself(action_state=0x12, is_airborne=True)
        self.assertEqual(_infer(could_engage_jack)({airborne, _jack(), CAMERA}), set())

    def test_a_jack_at_zero_health_is_still_his(self) -> None:
        # Only a negative health word kills an ordinary enemy: the first live
        # run dropped him at 0 and produced no verb while he threw.
        verbs = _infer(could_engage_jack)({_myself(), _jack(health=0), CAMERA})
        self.assertEqual({type(v) for v in verbs}, {EngageJack})

    def test_not_for_a_dead_or_dying_jack(self) -> None:
        self.assertEqual(_infer(could_engage_jack)({_myself(), _jack(health=0xFFFF), CAMERA}), set())
        dying = _jack(state=jack_plan.ST_DYING)
        self.assertEqual(_infer(could_engage_jack)({_myself(), dying, CAMERA}), set())

    def test_a_live_jacks_throw_is_the_plans_not_the_sidesteps(self) -> None:
        axe = _released(2800, 59)
        verbs = _infer(could_projectile_sidestep)({_myself(2760, 60), _jack(), axe})
        self.assertEqual(verbs, set())

    def test_an_orphaned_throw_is_still_sidestepped(self) -> None:
        axe = _released(2800, 60, owner="obj09")
        verbs = _infer(could_projectile_sidestep)({_myself(2760, 60), axe})
        self.assertEqual({type(v) for v in verbs}, {ProjectileSidestep})


class HoldLoopTests(unittest.TestCase):
    def _holder(self, base: int) -> Myself:
        return _myself(2800, 60, action_state=base, held_enemy_slot="obj00")

    def _held(self) -> Jack:
        return _jack(2832, 60, state=jack_plan.ST_HELD, combat_phase=CombatPhase.GRABBED)

    def test_a_clean_front_hold_knees(self) -> None:
        verbs = _infer(could_hold_actions)({self._holder(0x60), self._held()})
        self.assertEqual({type(v) for v in verbs}, {AttackHeldEnemy})

    def test_a_back_hold_waits_while_his_axes_are_up(self) -> None:
        axe = Projectile(
            slot="obj03", world_x=2870, world_y=68, vel_x=-1.0, vel_z=-4.5,
            type_id=jack_plan.AXE_TYPE, state=jack_plan.AXE_JUGGLED, world_z=103,
            fine_z=103.25, owner_slot="obj00", flags_31=0x01, offset=38.0, attack_box_id=0x2B,
        )
        verbs = _infer(could_hold_actions)({self._holder(0x66), self._held(), axe})
        self.assertEqual(verbs, set())


class RankingTests(unittest.TestCase):
    def _winner(self, context) -> Verb:
        verbs = find_all(determine_priority_verb(set(context)), Verb)
        self.assertEqual(len(verbs), 1)
        return verbs[0]

    def test_he_outranks_walking_to_a_farther_grunt(self) -> None:
        me = _myself(2760, 60)
        grunt = _grunt(2640)
        winner = self._winner({
            me, _jack(), grunt, CAMERA,
            EngageJack(actor_slot="P1", target_slot="obj00"),
            WalkToNearEnemy(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageJack)

    def test_a_nearer_grunt_in_the_fight_comes_first(self) -> None:
        # User: "A IA dá muita prioridade ao EngageJack, mesmo quando tem
        # muitos mais outros inimigos mais iminentes que o Jack". A grunt 40 px
        # off, Jack 90: walking to the grunt (and anything aimed at it) wins.
        me = _myself(2760, 60)
        grunt = _grunt(2720)
        winner = self._winner({
            me, _jack(), grunt, CAMERA,
            EngageJack(actor_slot="P1", target_slot="obj00"),
            WalkToNearEnemy(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, WalkToNearEnemy)

    def test_a_nearer_grunt_down_on_the_floor_does_not_hold_him_up(self) -> None:
        me = _myself(2760, 60)
        grunt = _grunt(2720, combat_phase=CombatPhase.KNOCKDOWN)
        winner = self._winner({
            me, _jack(), grunt, CAMERA,
            EngageJack(actor_slot="P1", target_slot="obj00"),
            WalkToNearEnemy(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageJack)

    def test_a_throw_out_at_the_actor_takes_the_tick(self) -> None:
        me = _myself(2760, 60)
        grunt = _grunt(2790)
        winner = self._winner({
            me, _jack(2900), grunt, _released(2840, 59), CAMERA,
            EngageJack(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, EngageJack)

    def test_a_grunts_committed_strike_is_punched_first(self) -> None:
        me = _myself(2760, 60)
        grunt = _grunt(2780, combat_phase=CombatPhase.ATTACKING)
        winner = self._winner({
            me, _jack(2900), grunt, CAMERA,
            EngageJack(actor_slot="P1", target_slot="obj00"),
            Punch(actor_slot="P1", target_slot=grunt.slot),
        })
        self.assertIsInstance(winner, Punch)


class ExecuteTests(unittest.TestCase):
    def test_it_holds_the_plans_stick(self) -> None:
        me = _myself(2760, 60)
        jack = _jack()
        context = {me, jack, CAMERA}
        plan = jack_plan.plan_engage(me, jack, camera=CAMERA)
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        execute_verb(EngageJack(actor_slot="P1", target_slot="obj00"), context, gamepad)
        expected = (
            (RIGHT if plan.dir_x > 0 else LEFT if plan.dir_x < 0 else 0)
            | (DOWN if plan.dir_y > 0 else UP if plan.dir_y < 0 else 0)
        )
        self.assertEqual(gamepad.held, expected)


if __name__ == "__main__":
    unittest.main()
