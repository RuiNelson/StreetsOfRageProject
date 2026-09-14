"""EngageAntonio and the Antonio hold loop, wired through the pipeline.

``test_antonio`` pins the ROM model and the plan; this pins who owns him in
``decide``, how he ranks in ``priority``, what ``execute`` presses, and the
police rule that came with the plan (user: "A AI está a depender muito da
chamada da polícia!").
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai.decide import (
    could_call_police,
    could_engage_antonio,
    could_hold_actions,
    generate_verb_tokens,
)
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    Antonio,
    AttackHeldEnemy,
    Bongo,
    CallPolice,
    CameraRange,
    DebugNoPolice,
    EngageAntonio,
    FlipHold,
    Garcia,
    HitAntonioBoomerang,
    Myself,
    Projectile,
    Punch,
    ReleaseToRegrab,
    ScorePickup,
    Souther,
    Verb,
    WalkToNearEnemy,
    WalkToPickup,
    find_all,
)
from sor_autoplay.memory_map import PLAYER_KNEE_CHAIN_BIT
from sor_autoplay.phases import CombatPhase, boss_phase

CAMERA = CameraRange(left=32, right=288, top=0, bottom=112)
UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008


def _infer(generator):
    return lambda context: generator(generate_inference_tokens(set(context)))


def _myself(world_x: int = 160, world_y: int = 60, **overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=2,
        character_name="Blaze",
        world_x=world_x,
        world_y=world_y,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def _antonio(world_x: int = 200, world_y: int = 60, **overrides) -> Antonio:
    fields = dict(
        slot="obj09",
        type_id=0x56,
        world_x=world_x,
        world_y=world_y,
        health=24,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        primary_state=1,
        screen_x=world_x + 0x80,
        anim=0x02,
        anim_countdown=6,
        body_box_id=0x77,
    )
    fields.update(overrides)
    return Antonio(**fields)


def _held_antonio(**overrides) -> Antonio:
    return _antonio(
        combat_phase=CombatPhase.RECOVERY, primary_state=4, body_box_id=0x79, **overrides
    )


def _holding(knees: int) -> Myself:
    last = {0: 0, 1: 0x6A, 2: 0x6C}[knees]
    return _myself(
        action_state=0x60,
        held_enemy_slot="obj09",
        action_flags=PLAYER_KNEE_CHAIN_BIT if knees else 0,
        knee_chain_last=last,
    )


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    return VirtualGamepad(SharedGamepadState(client), player_index=1), client


class OwnershipTests(unittest.TestCase):
    """Every generic verb stands down for him; EngageAntonio is the fight."""

    def test_one_engage_per_live_antonio_for_a_free_actor(self) -> None:
        result = _infer(could_engage_antonio)({_myself(), _antonio()})
        self.assertEqual(result, {EngageAntonio(actor_slot="P1", target_slot="obj09")})

    def test_he_is_engaged_from_a_lane_the_actor_cannot_stand_in(self) -> None:
        # $17AB8 clamps him to lane 0, the player's floor is 2: the lane the
        # old approach dropped him from live_enemies over, 21% of a fight.
        result = _infer(could_engage_antonio)({_myself(world_y=30), _antonio(world_y=0)})
        self.assertEqual(len(result), 1)

    def test_not_while_holding_airborne_or_against_a_dead_antonio(self) -> None:
        engage = _infer(could_engage_antonio)
        self.assertEqual(engage({_holding(0), _held_antonio()}), set())
        self.assertEqual(engage({_myself(is_airborne=True, action_state=0x12), _antonio()}), set())
        self.assertEqual(engage({_myself(), _antonio(health=0xFFFF)}), set())

    def test_nothing_else_is_aimed_at_him(self) -> None:
        # Punch, grab, hop, walk-in, chord and retreat all had a claim on him
        # from here once; none may now.
        context = {_myself(world_x=170, world_y=60), _antonio(), CAMERA}
        verbs = _infer(generate_verb_tokens)(context)
        aimed = {
            type(verb)
            for verb in verbs
            if isinstance(verb, Verb) and getattr(verb, "target_slot", None) == "obj09"
        }
        self.assertEqual(aimed, {EngageAntonio})


class HoldLoopTests(unittest.TestCase):
    def test_knees_while_the_chain_is_short(self) -> None:
        verbs = _infer(could_hold_actions)({_holding(1), _held_antonio()})
        self.assertEqual({type(v) for v in verbs}, {AttackHeldEnemy})

    def test_releases_to_regrab_after_two_knees(self) -> None:
        verbs = _infer(could_hold_actions)({_holding(2), _held_antonio()})
        self.assertEqual({type(v) for v in verbs}, {ReleaseToRegrab})

    def test_the_third_knee_when_it_kills(self) -> None:
        verbs = _infer(could_hold_actions)({_holding(2), _held_antonio(health=3)})
        self.assertEqual({type(v) for v in verbs}, {AttackHeldEnemy})


class RankingTests(unittest.TestCase):
    def _winner(self, context) -> Verb:
        return find_all(determine_priority_verb(generate_inference_tokens(set(context))), Verb)[0]

    def test_the_engage_outranks_detours_and_grunts(self) -> None:
        grunt = Garcia(
            slot="obj01",
            type_id=0x20,
            world_x=140,
            world_y=60,
            health=10,
            combat_phase=CombatPhase.RECOVERY,
            targets_player=1,
            facing_left=True,
        )
        pickup = ScorePickup(slot="obj02", world_x=120, world_y=60, pickup_type=0x3F, points=3000)
        context = {
            _myself(),
            _antonio(),
            grunt,
            pickup,
            CAMERA,
            EngageAntonio(actor_slot="P1", target_slot="obj09"),
            Punch(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }
        self.assertIsInstance(self._winner(context), EngageAntonio)

    def test_an_incoming_boomerang_is_punched_first(self) -> None:
        boomerang = Projectile(
            slot="obj10", world_x=180, world_y=60, vel_x=-8.0, vel_z=0.0, type_id=0x96
        )
        context = {
            _myself(),
            _antonio(world_x=280),
            boomerang,
            EngageAntonio(actor_slot="P1", target_slot="obj09"),
            HitAntonioBoomerang(actor_slot="P1", target_slot="obj10"),
        }
        self.assertIsInstance(self._winner(context), HitAntonioBoomerang)

    def test_the_release_tops_the_hold_family_on_him(self) -> None:
        context = {
            _holding(2),
            _held_antonio(),
            ReleaseToRegrab(actor_slot="P1", target_slot="obj09"),
            FlipHold(actor_slot="P1", target_slot="obj09"),
        }
        self.assertIsInstance(self._winner(context), ReleaseToRegrab)

    def test_police_no_longer_outranks_a_combo_at_half_health(self) -> None:
        souther = Souther(
            slot="obj11",
            type_id=0x55,
            world_x=190,
            world_y=60,
            health=32,
            combat_phase=CombatPhase.KNOCKDOWN,
            targets_player=1,
            facing_left=True,
        )
        context = {
            _myself(health_percent=50.0),
            souther,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj11"),
        }
        self.assertIsInstance(self._winner(context), Punch)


class ExecuteTests(unittest.TestCase):
    def test_the_engage_holds_the_planned_stick(self) -> None:
        # The regrab: released 40 px in front of him on his lane, facing away.
        actor = _myself(world_x=160, facing_left=True, action_state=0x03)
        gamepad, _client = _gamepad()
        execute_verb(
            EngageAntonio(actor_slot="P1", target_slot="obj09"),
            {actor, _antonio(), CAMERA},
            gamepad,
        )
        self.assertTrue(gamepad.held & RIGHT)
        self.assertFalse(gamepad.held & LEFT)

    def test_the_engage_presses_into_the_camera_edge(self) -> None:
        # The round-1 arena: the actor pinned at the right of the locked
        # camera, released facing away, and him 40 px on, past the screen edge
        # and walking back in. The press is the walking box; stripped at the
        # walk clamp, the actor stood still and took the kick.
        actor = _myself(world_x=288, facing_left=True, action_state=0x03)
        antonio = _antonio(world_x=328, screen_x=328 + 0x80)
        gamepad, _client = _gamepad()
        execute_verb(
            EngageAntonio(actor_slot="P1", target_slot="obj09"),
            {actor, antonio, CAMERA},
            gamepad,
        )
        self.assertTrue(gamepad.held & RIGHT)

    def test_release_to_regrab_works_on_him(self) -> None:
        actor = _myself(action_state=0x60, held_enemy_slot="obj09", hold_release_countdown=3)
        gamepad, client = _gamepad()
        execute_verb(
            ReleaseToRegrab(actor_slot="P1", target_slot="obj09"),
            {actor, _held_antonio(), CAMERA},
            gamepad,
        )
        self.assertTrue(client.press_buttons.called)
        self.assertTrue(gamepad.held & RIGHT)


class PoliceIsTheLastResortTests(unittest.TestCase):
    """User: "A AI está a depender muito da chamada da polícia!"."""

    def _crowd(self, health_percent: float):
        myself = _myself(world_x=100, world_y=60, health_percent=health_percent)
        front = Garcia(
            slot="obj01", type_id=0x20, world_x=130, world_y=60, health=10,
            combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        )
        back = Garcia(
            slot="obj02", type_id=0x20, world_x=70, world_y=60, health=10,
            combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=False,
        )
        return {myself, front, back}

    def test_a_crowd_is_not_a_reason_on_its_own(self) -> None:
        self.assertEqual(_infer(could_call_police)(self._crowd(50.0)), set())

    def test_a_crowd_at_the_panic_threshold_still_calls_it(self) -> None:
        self.assertEqual(
            _infer(could_call_police)(self._crowd(10.0)), {CallPolice(actor_slot="P1")}
        )

    def test_a_live_boss_is_not_a_reason_on_its_own(self) -> None:
        bongo = Bongo(
            slot="obj05", type_id=0x57, world_x=200, world_y=60, health=30,
            combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        )
        self.assertEqual(_infer(could_call_police)({_myself(health_percent=50.0), bongo}), set())

    def test_against_antonio_only_at_the_panic_threshold(self) -> None:
        # User: "The police is allowed for Souther/Antonio, just don't test
        # with the police on" -- the last resort there as anywhere else.
        for health_percent, lives, fires in ((50.0, 3, False), (10.0, 3, True), (20.0, 1, True)):
            with self.subTest(health_percent=health_percent, lives=lives):
                actor = _myself(health_percent=health_percent, lives=lives)
                expected = {CallPolice(actor_slot="P1")} if fires else set()
                self.assertEqual(_infer(could_call_police)({actor, _antonio()}), expected)

    def test_the_harness_switch_removes_it(self) -> None:
        actor = _myself(health_percent=10.0)
        self.assertEqual(
            _infer(could_call_police)({actor, _antonio(), DebugNoPolice()}), set()
        )


class PhaseTests(unittest.TestCase):
    def test_his_primary_one_is_never_an_attack(self) -> None:
        for tactical in (0, 1, 2, 5, 6, 7, 9):
            with self.subTest(tactical=tactical):
                self.assertIs(
                    boss_phase(type_id=0x56, primary_byte=0x01, tactical=tactical),
                    CombatPhase.NORMAL,
                )

    def test_his_dash_is_a_charge_and_his_kick_an_attack(self) -> None:
        self.assertIs(boss_phase(type_id=0x56, primary_byte=0x01, tactical=0x08), CombatPhase.CHARGE)
        self.assertIs(boss_phase(type_id=0x56, primary_byte=0x02, tactical=0x00), CombatPhase.ATTACKING)


if __name__ == "__main__":
    unittest.main()
