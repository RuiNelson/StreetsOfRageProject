import inspect
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from sor_autoplay.ai import execute as execute_module
from sor_autoplay.ai import loop as loop_module
from sor_autoplay.ai import priority as priority_module
from sor_autoplay.ai.tokens import (
    CounterGrab,
    GrabEnemy,
    JumpAttack,
    OpenBreakable,
    Punch,
    RearAttack,
    ReleaseGrab,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
)
from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import AttackRange, Enemy, Nora, punch_usable_inner_x
from sor_autoplay.ai.tokens import CameraRange, Stage
from sor_autoplay.ai.execute import (
    BREAKABLE_STOP_BUFFER,
    MOVE_DEADBAND_X,
    WALK_TO_ENEMY_LANE_SAFETY_Y,
    _walk_to_breakable_target,
    _walk_to_near_enemy_target,
    execute_tick,
    execute_verb,
    press_no_button,
)
from sor_autoplay.ai.decide import BREAKABLE_PUNCH_X, in_smash_range
from sor_autoplay.ai.gamepad import AXIS_RAMP_TICKS, SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.tokens import Breakable, Pit, Projectile, SafeSpot
from sor_autoplay.ai.tokens import HealthPickup, Weapon
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import (
    ProjectileSidestep,
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008
A = 0x0010
B = 0x0020
C = 0x0040


def _myself(
    *,
    world_x: int = 0,
    world_y: int = 0,
    action_state: int = 0,
    is_airborne: bool = False,
    facing_left: bool = False,
) -> Myself:
    return Myself(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=world_x,
        world_y=world_y,
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=facing_left,
        combat_phase=CombatPhase.NORMAL,
        action_state=action_state,
        is_airborne=is_airborne,
    )


def _enemy(*, world_x: int = 0, world_y: int = 0) -> Enemy:
    return Enemy(
        slot="obj01",
        type_id=0x20,
        world_x=world_x,
        world_y=world_y,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    state = SharedGamepadState(client)
    return VirtualGamepad(state, player_index=1), client


def _settle(verb, context, gamepad, ticks: int = AXIS_RAMP_TICKS) -> None:
    """Execute ``verb`` enough consecutive ticks for the gamepad's virtual
    left/right axis to reach full deflection on a steady command -- i.e. as
    many ticks as a real sustained direction needs before it actually
    presses a D-pad button (see ``VirtualGamepad.steer_x``). Static
    single-tick fixtures like these would otherwise never move the axis off
    center."""

    for _ in range(ticks):
        execute_verb(verb, context, gamepad)


class PressNoButtonTests(unittest.TestCase):
    def test_press_no_button_releases(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        press_no_button(gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)
        self.assertEqual(gamepad.held, 0)


class BreakableApproachSideTests(unittest.TestCase):
    """Standing on a prop, which side to step to cannot be decided by
    anything the AI itself flips every tick."""

    def _prop(self, x: int, y: int = 100):
        from sor_autoplay.ai.tokens import Breakable

        return Breakable(slot="prop", world_x=x, world_y=y, type_id=0x11)

    def _stage(self, direction: str = "right"):
        return Stage(level_index=0, direction=direction)

    def test_the_side_is_stable_however_the_actor_faces(self) -> None:
        # Reading it off facing is a feedback loop: a prop, unlike an enemy,
        # never moves to break the symmetry. Measured live as 107 seconds at
        # one prop with LEFT held on 244 ticks and RIGHT on 240, the steering
        # axis cancelling almost all of it.
        prop = self._prop(200)
        context = {self._stage("right")}

        left = _walk_to_breakable_target(
            _myself(world_x=200, world_y=100, facing_left=True), prop, context
        )
        right = _walk_to_breakable_target(
            _myself(world_x=200, world_y=100, facing_left=False), prop, context
        )

        self.assertEqual(left, right)

    def test_it_stops_on_the_side_it_is_coming_from(self) -> None:
        prop = self._prop(200)

        going_right = _walk_to_breakable_target(
            _myself(world_x=200, world_y=100), prop, {self._stage("right")}
        )
        going_left = _walk_to_breakable_target(
            _myself(world_x=200, world_y=100), prop, {self._stage("left")}
        )

        self.assertLess(going_right[0], prop.world_x)
        self.assertGreater(going_left[0], prop.world_x)

    def test_a_prop_clearly_to_one_side_still_uses_that_side(self) -> None:
        prop = self._prop(300)
        actor = _myself(world_x=100, world_y=100)

        target_x, _ = _walk_to_breakable_target(actor, prop, {self._stage("right")})

        self.assertLess(target_x, prop.world_x)

    def test_stage_seven_side_is_stable_however_the_actor_faces(self) -> None:
        # Stage 7 (AI.md: "progression does not require lateral movement")
        # reports Stage.direction == "none", which has no lateral anchor to
        # read -- the same "standing on the prop" case as the facing test
        # above, just with no stage direction to fall back on. Falling back
        # to actor.facing_left there reintroduces the identical live-measured
        # oscillation this whole class guards against.
        prop = self._prop(200)
        context = {self._stage("none")}

        left = _walk_to_breakable_target(
            _myself(world_x=200, world_y=100, facing_left=True), prop, context
        )
        right = _walk_to_breakable_target(
            _myself(world_x=200, world_y=100, facing_left=False), prop, context
        )

        self.assertEqual(left, right)


class DeadZoneApproachTests(unittest.TestCase):
    """Nora's whip (shape $22) reaches 32..80px, so the pocket between her
    body and 32 is the one place she cannot hit at all. Reported from play:
    the AI could not deal with Noras -- it stopped at its own punch edge, 46px
    for Axel, which is squarely inside the whip band."""

    NORA_WHIP = AttackRange(
        shape_id=0x22,
        animation=10,
        forward_min=32,
        forward_max=80,
        lane_min=-12,
        lane_max=10,
        height_min=-44,
        height_max=-20,
    )

    def _nora(self, **overrides):
        fields = dict(
            slot="obj01",
            type_id=0x26,
            world_x=200,
            world_y=100,
            health=11,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
            attack_ranges=(self.NORA_WHIP,),
        )
        fields.update(overrides)
        return Nora(**fields)

    def test_stops_inside_the_whips_dead_zone(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        nora = self._nora(world_x=200, world_y=100)

        target_x, _ = _walk_to_near_enemy_target(actor, nora, set())

        # Approaching from the left, so the stop point is short of her.
        stop_dx = nora.world_x - target_x
        self.assertLess(stop_dx, nora.min_reach, "still inside the whip band")
        self.assertGreaterEqual(
            stop_dx, punch_usable_inner_x(0), "too close for Axel's own punch"
        )

    def test_waits_outside_her_reach_rather_than_crossing_a_live_swing(self) -> None:
        # 9 of the 10 hits a live Nora landed came at ~80px -- the far edge of
        # her whip -- catching the actor as it set off across the band. Her
        # engage-and-swing is stationary, so waiting it out costs nothing.
        actor = _myself(world_x=100, world_y=100)
        swinging = self._nora(world_x=200, world_y=100, combat_phase=CombatPhase.ATTACKING)

        target_x, target_y = _walk_to_near_enemy_target(actor, swinging, set())

        self.assertEqual((target_x, target_y), (actor.world_x, actor.world_y))

    def test_crosses_anyway_once_already_inside_the_band(self) -> None:
        # Standing in the band is the worst place to be: press on to the
        # pocket rather than waiting there.
        actor = _myself(world_x=100, world_y=100)
        swinging = self._nora(world_x=160, world_y=100, combat_phase=CombatPhase.ATTACKING)

        target_x, _ = _walk_to_near_enemy_target(actor, swinging, set())

        self.assertLess(swinging.world_x - target_x, swinging.min_reach)

    def test_does_not_wait_out_a_swing_in_another_lane(self) -> None:
        # Her whip sweeps a lane band; a swing the actor is nowhere near the
        # line of is not a reason to stop. Gating on the X gap alone cost half
        # the AI's stage progress in a live recording.
        actor = _myself(world_x=100, world_y=100)
        off_lane = self._nora(world_x=200, world_y=160, combat_phase=CombatPhase.ATTACKING)

        target_x, _ = _walk_to_near_enemy_target(actor, off_lane, set())

        self.assertNotEqual(target_x, actor.world_x)

    def test_an_ordinary_enemy_is_never_waited_out(self) -> None:
        # An enemy whose reach starts at its own feet has no distance that is
        # both safe and useful, so holding ground is simply passivity -- it
        # walks up and hits you anyway while you have stopped attacking.
        actor = _myself(world_x=100, world_y=100)
        garcia = _enemy(world_x=200, world_y=100)
        garcia = replace(garcia, combat_phase=CombatPhase.ATTACKING)

        target_x, _ = _walk_to_near_enemy_target(actor, garcia, set())

        self.assertNotEqual(target_x, actor.world_x)

    def test_an_enemy_without_a_dead_zone_is_unaffected(self) -> None:
        # Garcia's punch covers his own feet, so there is no pocket and the
        # stop distance stays the actor's own punch edge.
        actor = _myself(world_x=100, world_y=100)
        garcia = _enemy(world_x=200, world_y=100)

        target_x, _ = _walk_to_near_enemy_target(actor, garcia, set())

        self.assertEqual(garcia.world_x - target_x, 46)  # punch_outer 50 - buffer

    def test_the_pocket_is_still_reached_from_the_other_side(self) -> None:
        actor = _myself(world_x=300, world_y=100, facing_left=True)
        nora = self._nora(world_x=200, world_y=100, facing_left=False)

        target_x, _ = _walk_to_near_enemy_target(actor, nora, set())

        stop_dx = target_x - nora.world_x
        self.assertLess(stop_dx, nora.min_reach)
        self.assertGreaterEqual(stop_dx, punch_usable_inner_x(0))


class ExecuteWalkToNearEnemyTests(unittest.TestCase):
    def test_walks_toward_enemy_to_the_right_and_below(self) -> None:
        # Enemy far enough right that the stopping point (its x minus Axel's
        # stop_dx of 46) is still well outside MOVE_DEADBAND_X -- otherwise
        # the actor has effectively arrived on X and only the lane component
        # should be held.
        actor = _myself(world_x=0, world_y=0)
        target = _enemy(world_x=100, world_y=50)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT | DOWN, player2=0)

    def test_walks_toward_enemy_to_the_left_and_above(self) -> None:
        # dx=44 is inside Axel's stop_dx (46), so the walk has arrived on X
        # and converges onto the enemy's lane -- the only branch that aims at
        # the enemy's own Y. Further out it holds its own lane instead, so
        # that the lane aim cannot depend on the enemy's combat phase (see
        # _walk_to_near_enemy_target).
        actor = _myself(world_x=44, world_y=50)
        target = _enemy(world_x=0, world_y=0)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT | UP, player2=0)

    def test_holds_its_own_lane_while_still_far_out_on_x(self) -> None:
        # Regression: the lane aim must not depend on the enemy's combat
        # phase. It used to converge onto the enemy's lane while far and
        # sidestep off it while the enemy was committed, so every phase
        # change flipped the aim by 2*WALK_TO_ENEMY_LANE_SAFETY_Y and the
        # approach alternated UP/DOWN the whole way in. Same actor and enemy
        # in both phases here; the commanded lane must match.
        target_calm = _enemy(world_x=200, world_y=0)
        target_committed = replace(target_calm, combat_phase=CombatPhase.ATTACKING)
        masks = []
        for target in (target_calm, target_committed):
            actor = _myself(world_x=0, world_y=50)
            gamepad, _ = _gamepad()
            _settle(
                WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertEqual(
            masks[0], masks[1], f"lane aim changed with the enemy's phase: {masks}"
        )
        self.assertFalse(
            masks[0] & (UP | DOWN),
            f"converged onto the enemy's lane while still far out: {hex(masks[0])}",
        )

    def test_turns_toward_an_enemy_at_the_actors_back(self) -> None:
        # Holding a direction is what sets facing, so walking *toward* a
        # behind enemy is the turn-around. Stopping on the near side (the
        # front-enemy rule) would instead hold RIGHT here -- backing away
        # while still facing the wrong way, which leaves the slow $322A
        # chord as the only thing that can reach it. Actor faces right
        # (facing_left=False), enemy sits to its left, so: behind.
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=70, world_y=100)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)

    def test_standing_on_the_enemy_steps_back_to_punch_range(self) -> None:
        # Never walk onto the enemy — stop just inside punch_outer_x.
        actor = _myself(world_x=10, world_y=10)
        target = _enemy(world_x=10, world_y=10)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)

    def test_stops_just_inside_punch_range_instead_of_overlapping_enemy(self) -> None:
        # Axel: punch_outer_x=50, stop buffer 4 -> stop_dx=46. Placing the
        # actor exactly at that stopping x (relative to the enemy at x=50)
        # means it has already arrived and should hold no further movement.
        actor = _myself(world_x=4, world_y=50)
        target = _enemy(world_x=50, world_y=50)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # start non-zero so a hold(0) call is observable
        client.hold_buttons.reset_mock()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_enemy()}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_not_called()

    def test_sidesteps_a_dangerous_enemys_exact_lane_while_still_far_away(self) -> None:
        actor = _myself(world_x=0, world_y=50)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        # Same lane (dy=0) and far away (dx=200) from an actively attacking
        # enemy -> step off its lane instead of walking straight down it.
        # Side picked from target.world_y=50 against the lane's fixed
        # midpoint (57 with no CameraRange in context) -> below it -> UP.
        client.hold_buttons.assert_called_with(player1=RIGHT | UP, player2=0)

    def test_does_not_sidestep_a_dangerous_enemy_once_close_enough_to_punch(self) -> None:
        # dx=46 == stop_dx: already at the stopping point, so the actor
        # aligns for the punch instead of sidestepping.
        actor = _myself(world_x=-6, world_y=50)
        target = replace(_enemy(world_x=40, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # start non-zero so a hold(0) call is observable
        client.hold_buttons.reset_mock()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)

    def test_leaves_the_line_of_attack_of_a_committed_enemy(self) -> None:
        # Regression (live-diagnosed): gating the offset on already sitting
        # on the enemy's exact lane reacted too late -- the approach used to
        # converge onto that lane over several ticks regardless, so by the
        # time the old gate opened the enemy had often already reached
        # ATTACKING and landed a hit. Nothing converges the lane while far
        # any more, but standing *in* a committed enemy's line still has to
        # be actively left, which is what this covers: actor 10px off the
        # enemy's lane, inside WALK_TO_ENEMY_LANE_SAFETY_Y (28).
        #
        # The offset side is picked from the target's own position against
        # the lane's fixed midpoint, not from actor.world_y vs
        # target.world_y (see _walk_to_near_enemy_target's docstring): with
        # no CameraRange in context, _lane_bounds defaults to lo=8, hi=106,
        # midpoint=57 -- target.world_y=50 sits below that, so the offset
        # pushes further up (-WALK_TO_ENEMY_LANE_SAFETY_Y), independent of
        # which side of it the actor stands on.
        actor = _myself(world_x=0, world_y=60)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}

        target_x, target_y = _walk_to_near_enemy_target(actor, target, context)

        self.assertEqual(target_y, 50 - WALK_TO_ENEMY_LANE_SAFETY_Y)

    def test_does_not_keep_sidestepping_once_clear_of_the_line_of_attack(self) -> None:
        # The sidestep aims at a *fixed* lane, so once the actor is already
        # clear (dy >= WALK_TO_ENEMY_LANE_SAFETY_Y) there is nothing left to
        # do and it holds its lane -- rather than stepping away again from
        # wherever it now stands, which would walk it off the screen edge.
        actor = _myself(world_x=0, world_y=90)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}

        _, target_y = _walk_to_near_enemy_target(actor, target, context)

        self.assertEqual(target_y, 90)

    def test_does_not_sidestep_an_enemy_that_is_not_dangerous(self) -> None:
        actor = _myself(world_x=0, world_y=50)
        target = _enemy(world_x=200, world_y=50)  # NORMAL phase
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_close_range_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression (live-diagnosed): the old side pick combined a strict
        # enemy_behind_actor() sign test with an *inclusive* <= elsewhere, so
        # for a left-facing actor dx=0 exactly picked the opposite side from
        # dx=+-1 right next to it -- a single-tick, full 2*stop_dx jump to
        # the far side of the enemy whenever an approach's integer rounding
        # briefly landed exactly on alignment. That flip is what set facing
        # the next tick, so it read back as the AI reversing direction
        # against a single, barely-moving enemy. Adjacent ticks a pixel
        # apart, straddling dx=0, must now agree.
        target = _enemy(world_x=100, world_y=40)
        masks = []
        for actor_x in (99, 100, 101):
            actor = replace(_myself(world_x=actor_x, world_y=40), facing_left=True)
            gamepad, _ = _gamepad()
            _settle(
                WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands straddling exact alignment: {masks}",
        )

    def test_close_range_lane_offset_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression (live-diagnosed): the sidestep-lane offset picked its
        # up/down side from actor.world_y >= target.world_y -- a raw compare
        # between two bodies converging onto the same lane. While still far
        # away on X (is_dangerous and dx > stop_dx both still hold), dy == 0
        # gets crossed on essentially every tick of ordinary walk jitter, and
        # each crossing swung target_y by a full
        # 2*WALK_TO_ENEMY_LANE_SAFETY_Y -- read live as the actor darting
        # up/down against a single, barely-moving enemy. Adjacent ticks a
        # pixel apart, straddling dy=0, must now agree.
        target = replace(_enemy(world_x=300, world_y=40), combat_phase=CombatPhase.ATTACKING)
        masks = []
        for actor_y in (39, 40, 41):
            actor = _myself(world_x=0, world_y=actor_y)
            gamepad, _ = _gamepad()
            _settle(
                WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & UP for m in masks) and any(m & DOWN for m in masks),
            f"opposite vertical commands straddling exact lane alignment: {masks}",
        )


class FaceTowardMaskHysteresisTests(unittest.TestCase):
    """``_face_toward_mask`` sets the facing bit pressed alongside an attack.
    Right at melee range the actor and target sit almost on top of each
    other, so a raw, unmargined sign test on their dx flips on every pixel of
    ordinary jitter; adjacent ticks a pixel apart must not command opposite
    facing."""

    def test_straddling_alignment_never_commands_opposite_facing(self) -> None:
        target = _enemy(world_x=100, world_y=40)
        masks = []
        for actor_x in (99, 100, 101):
            actor = _myself(world_x=actor_x, world_y=40)
            gamepad, client = _gamepad()

            execute_verb(Punch(actor_slot="P1", target_slot="obj01"), {actor, target}, gamepad)

            masks.append(client.press_buttons.call_args.kwargs["player1"])

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite facing commands straddling exact alignment: {masks}",
        )


class ExecuteRetreatFromDangerTests(unittest.TestCase):
    def test_steps_away_from_a_target_to_the_right(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)

    def test_steps_away_from_a_target_to_the_left(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=50, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_holds_the_current_lane_while_retreating(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=90), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        # Backing away moves on X only -- never toward the enemy's lane too.
        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)

    def test_prefers_the_inferred_safe_spot(self) -> None:
        # inference.check_for_safe_spots already weighed the sidesteps
        # against the straight retreat (clearance from every live enemy,
        # lane/camera bounds, pits). When it produced one, the executor must
        # steer there rather than re-deciding "straight back on X".
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target, SafeSpot(actor_slot="P1", world_x=100, world_y=74)}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        # Pure sidestep: down the lane, no lateral component.
        client.hold_buttons.assert_called_once_with(player1=DOWN, player2=0)

    def test_fallback_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression, same shape as the walk-to-enemy X pick: with no
        # SafeSpot in context, the fallback picked "away" from a raw compare
        # on actor.world_x vs target.world_x, so a couple of px of jitter
        # right at alignment flipped the full 2*RETREAT_FROM_DANGER_DISTANCE
        # retreat direction.
        masks = []
        for actor_x in (99, 100, 101):
            actor = replace(_myself(world_x=actor_x, world_y=50), facing_left=True)
            target = replace(_enemy(world_x=100, world_y=50), combat_phase=CombatPhase.ATTACKING)
            gamepad, _ = _gamepad()
            _settle(
                RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands straddling exact alignment: {masks}",
        )

    def test_ignores_a_safe_spot_belonging_to_the_partner(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target, SafeSpot(actor_slot="P2", world_x=100, world_y=74)}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_enemy()}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_not_called()


def _projectile(*, world_x: int = 0, world_y: int = 0, vel_x: float = -5.0) -> Projectile:
    return Projectile(slot="obj10", world_x=world_x, world_y=world_y, vel_x=vel_x, vel_z=0.0)


class ExecuteProjectileSidestepTests(unittest.TestCase):
    def test_steps_down_from_the_upper_half_of_the_lane(self) -> None:
        # No CameraRange in context -> _lane_bounds' own fallback (2..112,
        # minus LANE_EDGE_MARGIN each side) puts the midpoint at 57; world_y
        # 50 sits above it, so the dodge steps toward larger Y ("down").
        actor = _myself(world_x=100, world_y=50)
        projectile = _projectile(world_x=150, world_y=50)
        context = {actor, projectile}
        verb = ProjectileSidestep(actor_slot="P1", target_slot="obj10")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        # Lateral only: no L/R component, since the dodge never moves X.
        client.hold_buttons.assert_called_with(player1=DOWN, player2=0)

    def test_steps_up_from_the_lower_half_of_the_lane(self) -> None:
        actor = _myself(world_x=100, world_y=90)
        projectile = _projectile(world_x=150, world_y=90)
        context = {actor, projectile}
        verb = ProjectileSidestep(actor_slot="P1", target_slot="obj10")
        gamepad, client = _gamepad()

        _settle(verb, context, gamepad)

        client.hold_buttons.assert_called_with(player1=UP, player2=0)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_projectile()}
        verb = ProjectileSidestep(actor_slot="P1", target_slot="obj10")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_not_called()


class ExecuteWalkToAdvanceStageTests(unittest.TestCase):
    def test_direction_right_holds_right(self) -> None:
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        _settle(verb, set(), gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_direction_left_holds_left(self) -> None:
        verb = WalkToAdvanceStage(actor_slot="P1", direction="left")
        gamepad, client = _gamepad()

        _settle(verb, set(), gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)


class MovementDeadbandTests(unittest.TestCase):
    """The controller is a bang-bang actuator sampled every ~33 ms while the
    game walks the actor a couple of px per frame, so an exact-coordinate
    target is stepped over rather than landed on. Without a deadband the
    residual flips sign every tick and the actor vibrates left/right instead
    of travelling -- worst while moving vertically, where the X residual is
    the only thing still oscillating."""

    def test_does_not_steer_for_a_sub_step_x_residual(self) -> None:
        # Actor sits 3px from its stopping point on X (Axel stop_dx=46, enemy
        # at 143 -> stop at 97) but a full lane away: it should travel purely
        # down the lane, with no horizontal component at all.
        #
        # dx=43 is inside stop_dx, which is what puts _walk_to_near_enemy_target
        # in its converge-onto-the-enemy's-lane branch -- while still further
        # out on X it holds its own lane instead (see that function), and the
        # tick would command nothing at all, testing nothing.
        actor = _myself(world_x=100, world_y=40)
        target = _enemy(world_x=143, world_y=100)
        gamepad, client = _gamepad()

        execute_verb(
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), {actor, target}, gamepad
        )

        client.hold_buttons.assert_called_once_with(player1=DOWN, player2=0)

    def test_straddling_the_stop_point_never_commands_opposite_directions(self) -> None:
        # The shake itself: two ticks a few px either side of the same
        # stopping point must not ask for LEFT then RIGHT.
        target = _enemy(world_x=149, world_y=40)
        masks = []
        for actor_x in (101, 105):
            actor = _myself(world_x=actor_x, world_y=40)
            gamepad, _ = _gamepad()
            _settle(
                WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands across adjacent ticks: {masks}",
        )


class VirtualAxisSmoothingTests(unittest.TestCase):
    """The reported bug this whole feature exists for: a per-tick direction
    decision that itself flips (target swap, a pixel of jitter crossing a
    threshold, whatever) used to reach the controller as an immediate
    physical L/R flip every time. Now the walk handlers only ever *request*
    a side each tick; _hold_steered's virtual axis (gamepad.AXIS_RAMP_TICKS)
    must see the same request AXIS_RAMP_TICKS ticks in a row before it
    actually presses that side."""

    def test_a_single_tick_reversal_never_reaches_the_controller(self) -> None:
        # Two ticks toward the right enemy, one stray tick toward a left one
        # (as if the target had briefly swapped), then back to the right
        # enemy -- the kind of single-tick flip that used to flip the D-pad
        # immediately. The axis should still be short of any edge, so no
        # LEFT should ever have been commanded.
        gamepad, client = _gamepad()
        right_enemy = _enemy(world_x=200, world_y=0)
        left_enemy = _enemy(world_x=-200, world_y=0)
        actor = _myself(world_x=0, world_y=0)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")

        execute_verb(verb, {actor, right_enemy}, gamepad)
        execute_verb(verb, {actor, right_enemy}, gamepad)
        execute_verb(verb, {actor, left_enemy}, gamepad)
        execute_verb(verb, {actor, right_enemy}, gamepad)

        for call_args in client.hold_buttons.call_args_list:
            self.assertFalse(
                call_args.kwargs["player1"] & LEFT,
                "a single-tick target flip pressed the opposite D-pad button",
            )

    def test_a_sustained_direction_does_eventually_press(self) -> None:
        # Confirms the smoothing only delays, rather than swallowing, a
        # direction that is actually requested every tick.
        gamepad, client = _gamepad()
        actor = _myself(world_x=0, world_y=0)
        target = _enemy(world_x=200, world_y=0)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")

        _settle(verb, {actor, target}, gamepad)

        self.assertTrue(gamepad.held & RIGHT)


class StaleMovementHoldTests(unittest.TestCase):
    """``hold_buttons`` is a sticky latch and ``SharedGamepadState.press``
    re-arms it after the press, so a walk tick followed by an attack tick
    used to leave the actor still walking through the strike -- straight
    past the enemy and out of its own punch band, or over the pickup it had
    just pressed B to collect. Every press-only handler must drop the hold
    first (``execute._press``)."""

    def _assert_clears_hold(self, verb, context) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # leftover from a previous walk tick
        client.hold_buttons.reset_mock()

        execute_verb(verb, context, gamepad)

        self.assertEqual(gamepad.held, 0)
        # The cleared latch also has to reach the host, not just the cache.
        self.assertIn(
            ((), {"player1": 0, "player2": 0}), client.hold_buttons.call_args_list
        )

    def test_punch_clears_a_leftover_walk_hold(self) -> None:
        self._assert_clears_hold(Punch(actor_slot="P1", target_slot="obj01"), set())

    def test_rear_attack_clears_a_leftover_walk_hold(self) -> None:
        self._assert_clears_hold(RearAttack(actor_slot="P1", target_slot="obj01"), set())

    def test_call_police_clears_a_leftover_walk_hold(self) -> None:
        self._assert_clears_hold(CallPolice(actor_slot="P1"), set())

    def test_collecting_a_pickup_clears_a_leftover_walk_hold(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        pickup = HealthPickup(
            slot="item01", world_x=100, world_y=100, pickup_type=0x01, health_delta=40
        )
        self._assert_clears_hold(
            WalkToPickup(actor_slot="P1", target_slot="item01"), {actor, pickup}
        )

    def test_a_walk_whose_target_vanished_releases_instead_of_coasting(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        # Target no longer in the context (killed between verb and
        # execution) -- the handler must stop the actor, not let the stale
        # hold carry it onward indefinitely.
        execute_verb(
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), set(), gamepad
        )

        self.assertEqual(gamepad.held, 0)
        client.hold_buttons.assert_called_once_with(player1=0, player2=0)


class ExecutePunchTests(unittest.TestCase):
    def test_punch_presses_button_b(self) -> None:
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_punch_is_unconditional_even_while_holding_an_enemy(self) -> None:
        # Supplex now owns the "already holding" case (see priority.py /
        # execute.py's state_machine_supplex); Punch always just presses B.
        actor = replace(_myself(), held_weapon_type=0x20)  # Garcia's type id
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_still_punches_while_holding_a_weapon(self) -> None:
        # could_punch no longer produces Punch while armed (that's
        # SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper's job now), but
        # execution itself is unconditional on whatever Verb it's given.
        actor = replace(_myself(), held_weapon_type=0x0A)  # baseball bat
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteSwingBatOrPipeTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        verb = SwingBatOrPipe(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteStabWithKnifeOrBottleTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        verb = StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteSprayPepperTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        verb = SprayPepper(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteCallPoliceTests(unittest.TestCase):
    def test_call_police_presses_button_a(self) -> None:
        verb = CallPolice(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=A, player2=0, frames=4)


class ExecuteJumpAttackTests(unittest.TestCase):
    def test_presses_jump_with_direction_when_grounded(self) -> None:
        actor = _myself(world_x=0, world_y=0, is_airborne=False)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C | RIGHT, player2=0, frames=3)

    def test_presses_a_clean_punch_edge_in_free_flight(self) -> None:
        # Free flight ($12): B on its own -- $3914 needs a rising edge, and
        # the direction is re-held afterwards for air steer rather than being
        # baked into the press.
        actor = _myself(world_x=0, world_y=0, is_airborne=True, action_state=0x12)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_presses_nothing_during_the_launch_crouch(self) -> None:
        # $10 is the 5-frame crouch. A B pressed here is still *held* when
        # free flight begins, so $3914 never sees an edge and the kick never
        # fires -- the reported "jumps at an enemy and never attacks". The
        # direction is held directly (not through the axis ramp, which needs
        # more ticks than the crouch lasts) so $384E reads it at launch.
        actor = _myself(world_x=0, world_y=0, is_airborne=True, action_state=0x10)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_not_called()
        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_presses_nothing_on_the_landing_frame(self) -> None:
        # $14 is the landing, and `is_airborne` covers the whole $10-$17
        # family including it -- so a handler keyed on that property pressed
        # B here, and by the time the ROM read it the actor was grounded, so
        # it came out as a plain punch aimed at wherever the kick had been
        # heading. Seen live: a kick at a knocked-down enemy sliding away
        # finished with a punch thrown at empty air on touchdown.
        actor = _myself(world_x=0, world_y=0, is_airborne=True, action_state=0x14)
        enemy = _enemy(world_x=100, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_not_called()

    def test_presses_nothing_once_the_kick_is_already_running(self) -> None:
        # $16 stays active for the rest of the airtime; a second edge buys
        # nothing and risks being read on landing.
        actor = _myself(world_x=0, world_y=0, is_airborne=True, action_state=0x16)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_not_called()

    def test_missing_actor_does_nothing(self) -> None:
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_not_called()

    def test_no_target_does_not_hop_in_place(self) -> None:
        actor = _myself(is_airborne=False)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_not_called()


class ExecuteGrabEnemyTests(unittest.TestCase):
    def test_walks_into_the_target_without_pressing_a_button(self) -> None:
        # $AAA0 only reports the grab contact code while the actor's outgoing
        # damage is zero, so pressing B here would produce a hit instead.
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=130, world_y=100)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)
        client.press_buttons.assert_not_called()

    def test_aims_at_the_enemy_itself_including_the_lane(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=130, world_y=108)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT | DOWN, player2=0)

    def test_keeps_walking_in_once_inside_the_movement_deadband(self) -> None:
        # The contact test also needs the actor's *walking* attack box: an
        # actor standing still on top of the enemy never takes the hold, so
        # the deadband must fall back to the facing direction, not release.
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=102, world_y=100)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_releases_when_the_target_is_gone(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        execute_verb(verb, {actor}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)


class ExecuteReleaseGrabTests(unittest.TestCase):
    def test_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression, same shape as the other side picks in this file: the
        # two bodies are still overlapping right after a release, so a raw
        # compare on actor.world_x vs target.world_x flipped which way was
        # "away" on ordinary jitter.
        target = _enemy(world_x=100, world_y=100)
        masks = []
        for actor_x in (99, 100, 101):
            actor = replace(_myself(world_x=actor_x, world_y=100), facing_left=True)
            gamepad, _ = _gamepad()
            _settle(
                ReleaseGrab(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands straddling exact alignment: {masks}",
        )


class ExecuteSupplexTests(unittest.TestCase):
    def test_presses_jump_from_front_hold(self) -> None:
        actor = _myself(action_state=0x60)
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=4)

    def test_presses_punch_from_back_hold(self) -> None:
        actor = _myself(action_state=0x66)
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_presses_punch_as_fallback_for_other_action_state(self) -> None:
        actor = _myself(action_state=0x10)
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_facing_bit_is_cleared_before_comparison(self) -> None:
        actor = _myself(action_state=0x67)  # back hold, facing bit set
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteThrowKnifeTests(unittest.TestCase):
    def test_throw_knife_presses_button_b(self) -> None:
        verb = ThrowKnife(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteThrowPepperTests(unittest.TestCase):
    def test_throw_pepper_presses_button_b(self) -> None:
        verb = ThrowPepper(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteRearAttackTests(unittest.TestCase):
    def test_presses_b_and_c_together(self) -> None:
        verb = RearAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B | C, player2=0, frames=4)


class ExecuteCounterGrabTests(unittest.TestCase):
    def test_presses_c_from_held_state(self) -> None:
        actor = replace(
            _myself(),
            action_state=0x7A,
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_flags=0,
        )
        verb = CounterGrab(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=3)

    def test_presses_b_when_counter_window_open(self) -> None:
        actor = replace(
            _myself(),
            action_state=0x7A,
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_flags=0x80,
        )
        verb = CounterGrab(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=3)


class ExecuteTechRecoverTests(unittest.TestCase):
    def test_presses_c_and_up_together(self) -> None:
        verb = TechRecover(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=C | UP, player2=0, frames=3)


class ExecuteOpenBreakableTests(unittest.TestCase):
    """One verb spanning the approach and the strike, switching on
    decide.in_smash_range.

    While still approaching: a Breakable is itself a solid obstacle, so
    walking to its exact center means walking into it from whatever angle a
    straight line happens to be, which can mean approaching from directly
    above/below and getting stuck. Stop just inside smash range on whichever
    side the actor already occupies instead."""

    def test_stops_short_of_the_breakables_exact_position(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        _settle(verb, {actor, prop}, gamepad)

        # BREAKABLE_PUNCH_X=36, BREAKABLE_STOP_BUFFER=12 -> stop_dx=24, so
        # the actor approaches to x=76, never reaching the prop's x=100.
        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_approaches_from_whichever_side_the_actor_is_already_on(self) -> None:
        actor = _myself(world_x=200, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        _settle(verb, {actor, prop}, gamepad)

        client.hold_buttons.assert_called_with(player1=LEFT, player2=0)

    def test_presses_b_once_inside_smash_range(self) -> None:
        # dx=32 is inside BREAKABLE_PUNCH_X (36). Under the old split verbs
        # this was where WalkToBreakable stopped holding and the actor had to
        # wait for SmashBreakable to win a later tick; one verb hits now.
        actor = _myself(world_x=68, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B | RIGHT, player2=0, frames=4)

    def test_faces_the_prop_before_hitting_it(self) -> None:
        actor = _myself(world_x=120, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B | LEFT, player2=0, frames=4)

    def test_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression, same shape as the enemy/retreat/release-grab side
        # picks: dy=40 keeps the actor outside smash range on Y (in_smash_
        # range requires BREAKABLE_PUNCH_Y=16) so the walk-in target,
        # not the punch, is what's under test. A raw compare on
        # actor.world_x vs the prop's flipped which side to stop on for a
        # couple of px of jitter right at alignment.
        actor_x = 100
        masks = []
        for prop_x in (99, 100, 101):
            actor = replace(_myself(world_x=actor_x, world_y=50), facing_left=True)
            prop = Breakable(slot="obj09", world_x=prop_x, world_y=90, type_id=0x40)
            gamepad, _ = _gamepad()
            _settle(
                OpenBreakable(actor_slot="P1", target_slot="obj09"), {actor, prop}, gamepad
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands straddling exact alignment: {masks}",
        )

    def test_missing_actor_or_target_does_nothing(self) -> None:
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {prop}, gamepad)

        client.hold_buttons.assert_not_called()

    def test_worst_case_deadband_stop_still_lands_in_smash_range(self) -> None:
        # Regression: _movement_mask releases the walk-in hold as soon as the
        # actor is within MOVE_DEADBAND_X of the approach's stop point, not
        # only once it has actually reached it -- so the real resting
        # distance from the prop can be (BREAKABLE_PUNCH_X -
        # BREAKABLE_STOP_BUFFER) + MOVE_DEADBAND_X. A buffer smaller than the
        # deadband (the old value, 4 < 5) let that worst case land one pixel
        # outside BREAKABLE_PUNCH_X: in_smash_range then stayed false
        # forever against a target that never moves to close the gap itself,
        # so the actor arrived and never threw a punch.
        worst_case_dx = (BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER) + MOVE_DEADBAND_X
        actor = _myself(world_x=100 - worst_case_dx, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)

        self.assertTrue(in_smash_range(actor, prop))


class ExecuteMovementBreakableAvoidanceTests(unittest.TestCase):
    """Regression: _movement_mask must only dodge on-screen breakables.

    world_map tracks entities up to two screens beyond each camera edge for
    hunt-target lookahead, far past what's actually walkable. Without a
    camera filter, any breakable in that huge tracked radius could trip the
    dodge on a pure horizontal walk -- and since the dodge always steers
    toward smaller Y ("up") when the actor is in the lane's lower half (the
    common case), that made the AI drift up for reasons unrelated to
    anything on screen.
    """

    def test_dodges_a_breakable_that_is_actually_on_screen(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target, prop, camera}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT | UP, player2=0)

    def test_ignores_a_breakable_far_outside_the_camera(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        camera = CameraRange(left=200, right=400, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target, prop, camera}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)


class ExecuteMovementPitAvoidanceTests(unittest.TestCase):
    """A Pit sitting on the walk path must be dodged, mirroring the existing
    Breakable-avoidance behavior above -- falling in costs a full life
    (player-health-lives-and-combat.md), so this must never be a no-op.

    Unlike the Breakable dodge, a Pit is a rectangle wide/tall enough that
    nudging Y while still closing X *at the same time* is not sufficient to
    clear it -- a diagonal command can still cut through the footprint
    before Y finishes moving. So X is held (no L/R bit) for as long as the
    actor's own current Y still sits inside the pit's band; only once it has
    actually cleared does X resume toward the original target."""

    def test_dodges_a_pit_that_is_actually_on_screen(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_with(player1=UP, player2=0)

    def test_resumes_x_once_actually_clear_of_the_pit_on_y(self) -> None:
        # Same pit and target, but the actor's *current* Y already sits
        # outside the pit's band (plus margin) -- safe to keep closing X.
        actor = _myself(world_x=0, world_y=60)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=60)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_ignores_a_pit_far_outside_the_camera(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=200, right=400, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_ignores_a_pit_not_on_the_path(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        # Pit is behind the actor, not between actor and target.
        pit = Pit(world_x=-50, lane_y=84, width=10, height=12)
        camera = CameraRange(left=-100, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        _settle(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)


class ExecuteTickPitEscapeTests(unittest.TestCase):
    """``execute_tick`` -- not ``_movement_mask``'s incidental path dodge --
    is what reacts to the actor already *standing* in a pit's danger zone,
    regardless of which verb (if any) won this tick. This is the executor's
    own responsibility, deliberately not a ``Verb`` decide.py/priority.py
    would have to rank against everything else."""

    def _settle_tick(self, verb, context, gamepad, ticks: int = AXIS_RAMP_TICKS) -> None:
        for _ in range(ticks):
            execute_tick(verb, context, gamepad)

    def test_escapes_a_pit_even_with_no_winning_verb(self) -> None:
        # Actor sits inside the pit, in the lower half of the lane -- the
        # escape must stop X dead (no L/R bit at all) and clear Y first,
        # never a diagonal that could still cut through the rectangle.
        actor = _myself(world_x=53, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        gamepad, client = _gamepad()

        self._settle_tick(None, {actor, pit}, gamepad)

        client.hold_buttons.assert_called_with(player1=UP, player2=0)

    def test_pit_escape_overrides_a_winning_attack_verb(self) -> None:
        # A Punch verb won this tick, but the actor is standing in a pit --
        # escaping it must still take over the controller.
        actor = _myself(world_x=53, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        target = _enemy(world_x=53, world_y=90)
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        self._settle_tick(verb, {actor, target, pit}, gamepad)

        client.hold_buttons.assert_called_with(player1=UP, player2=0)

    def test_escapes_downward_from_the_upper_half_of_the_lane(self) -> None:
        # Same shape pit, now sitting in the upper half of the lane --
        # the dodge direction must flip to match (down, not up).
        actor = _myself(world_x=53, world_y=15)
        pit = Pit(world_x=45, lane_y=10, width=10, height=12)
        gamepad, client = _gamepad()

        self._settle_tick(None, {actor, pit}, gamepad)

        client.hold_buttons.assert_called_with(player1=DOWN, player2=0)

    def test_never_freezes_a_few_pixels_short_of_the_danger_boundary(self) -> None:
        # Regression: aiming the dodge exactly at the danger boundary
        # (pit.lane_y - PIT_AVOID_MARGIN) meant that once from_y drifted to
        # within MOVE_DEADBAND_Y of that same point -- reachable well before
        # from_y actually crosses it -- the Y mask bits went quiet on a
        # from_y still short of "cleared" *and* X was still frozen (both
        # checks share the one boundary), so the whole mask went to 0 and
        # the actor froze in place, convinced it was still in danger.
        # world_y=78 is exactly that near-boundary gap (2px inside the old
        # target, comfortably inside the old MOVE_DEADBAND_Y=3 window) for
        # this pit's danger_top of 76.
        actor = _myself(world_x=53, world_y=78)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        gamepad, client = _gamepad()

        self._settle_tick(None, {actor, pit}, gamepad)

        client.hold_buttons.assert_called_with(player1=UP, player2=0)

    def test_never_stays_stuck_anywhere_inside_the_margin(self) -> None:
        # Broader sweep of the same regression: for every from_y across the
        # pit's full margin-expanded band, settling execute_tick must always
        # end up commanding some movement, never permanent silence --
        # whatever numeric coincidence might produce a 0 mask on a given
        # tick, either _movement_mask's own overshoot or _pit_escape_mask's
        # fallback must still resolve to real movement once settled (a
        # single tick's L/R bit can still read 0 while the virtual axis is
        # ramping up -- see gamepad.py -- so this settles first).
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        for world_y in range(76, 105):
            with self.subTest(world_y=world_y):
                actor = _myself(world_x=53, world_y=world_y)
                gamepad, client = _gamepad()

                self._settle_tick(None, {actor, pit}, gamepad)

                self.assertNotEqual(gamepad.held, 0)

    def test_no_override_when_not_near_any_pit(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        pit = Pit(world_x=500, lane_y=84, width=10, height=12)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        self._settle_tick(verb, {actor, target, pit}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_no_verb_and_no_pit_presses_no_button(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        execute_tick(None, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)
        self.assertEqual(gamepad.held, 0)

    def test_missing_actor_falls_through_to_the_winning_verb(self) -> None:
        # No Myself token at all (e.g. between polls) must not crash --
        # execute_tick still hands off to the normal verb dispatch.
        target = _enemy(world_x=100, world_y=90)
        pit = Pit(world_x=500, lane_y=84, width=10, height=12)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        self._settle_tick(verb, {target, pit}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)


class ExecuteWalkToWeaponTests(unittest.TestCase):
    def test_holds_movement_when_far_from_weapon(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=100, world_y=100, weapon_type=0x08)
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        _settle(verb, {actor, weapon}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT | DOWN, player2=0)

    def test_presses_punch_when_adjacent(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=10, world_y=5, weapon_type=0x08)
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, weapon}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.hold_buttons.assert_not_called()
        client.press_buttons.assert_not_called()


class ExecuteWalkToPickupTests(unittest.TestCase):
    def test_presses_punch_when_adjacent(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        food = HealthPickup(
            slot="obj06", world_x=10, world_y=5, pickup_type=0x4B, health_delta=20
        )
        verb = WalkToPickup(actor_slot="P1", target_slot="obj06")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, food}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class NoRawMemoryWritesTests(unittest.TestCase):
    """execute.py / loop.py / priority.py must only ever steer the gamepad —
    never touch raw RAM writes."""

    def test_forbidden_symbols_absent_from_source(self) -> None:
        for module in (execute_module, loop_module, priority_module):
            source = inspect.getsource(module)
            self.assertNotIn("write_memory", source)
            self.assertNotIn("write_value", source)


if __name__ == "__main__":
    unittest.main()
