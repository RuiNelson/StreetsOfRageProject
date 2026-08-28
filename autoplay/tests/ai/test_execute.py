import inspect
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from sor_autoplay.ai import execute as execute_module
from sor_autoplay.ai import loop as loop_module
from sor_autoplay.ai import priority as priority_module
from sor_autoplay.ai.tokens import (
    Antonio,
    CounterGrab,
    DodgeAntonioKick,
    DodgeSoutherSlash,
    GrabEnemy,
    HitAntonioBoomerang,
    JumpAttack,
    MeleeWeaponAttack,
    OpenBreakable,
    Punch,
    RearAttack,
    ReleaseGrab,
    Supplex,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
)
from sor_autoplay.ai.tokens import PUNCH_RANGE_Y
from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import (
    AttackRange,
    Enemy,
    Nora,
    Souther,
    punch_outer_x,
    punch_usable_inner_x,
)
from sor_autoplay.ai.tokens import CameraRange, Stage
from sor_autoplay.ai.execute import (
    BREAKABLE_STOP_BUFFER,
    MOVE_DEADBAND_X,
    PICKUP_RANGE_X,
    PICKUP_RANGE_Y,
    ANTONIO_APPROACH_LANE_Y,
    WALK_TO_ENEMY_LANE_SAFETY_Y,
    _find_safe_spot,
    _safe_spot_candidates,
    _walk_to_breakable_target,
    _walk_to_near_enemy_target,
    execute_tick,
    execute_verb,
    press_no_button,
)
from sor_autoplay.ai.decide import (
    BREAKABLE_PUNCH_X,
    breakable_smash_outer_x,
    in_smash_range,
)
from sor_autoplay.ai.pathfind import Rect
from sor_autoplay.ai.reach import PIT_AVOID_MARGIN, SOUTHER_SLASH_DIST_MIN, pit_endangers
from sor_autoplay.ai.gamepad import AXIS_RAMP_TICKS, SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.tokens import Breakable, Pit, Projectile
from sor_autoplay.hitboxes import Hitbox
from sor_autoplay import prop_solids
from sor_autoplay.ai.tokens import HealthPickup, Weapon
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import (
    HandleContinueMenu,
    HandleMrXDialog,
    InContinueMenu,
    InMrXDialog,
)
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
START = 0x0080


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


class BreakableFacingNudgeAtTheCameraClampTests(unittest.TestCase):
    """In smash range, facing away, and pinned against the walk clamp.

    Recorded live on round 1 (``tools/breakable_diag.py``): the actor stood
    at world x=2458 beside a type-``$11`` booth at 2472 for **6919
    consecutive ticks** with the gamepad mask ``0x0`` on every one of them,
    ``OpenBreakable`` winning every tick and the prop untouched.

    The facing nudge prefers to back *away* first (it buys room for a clean
    toward-step), but ``$43AA`` clamps the player to ``camera_x + $20``, so
    at the edge that step is a vector ``_clamp_mask`` strips -- after
    ``_routed_mask`` has already decided not to use its fallback, because
    what failed was the mask and not the goal. The branch has to end in a
    held direction or facing can never change.
    """

    def _prop(self):
        return Breakable(
            slot="obj02",
            world_x=2472,
            world_y=32,
            type_id=0x11,
            hitbox=Hitbox(x0=2456, x1=2488, y0=22, y1=42, z0=0, z1=32),
        )

    def _run(self, camera_left: int) -> int:
        prop = self._prop()
        actor = _myself(world_x=2458, world_y=48, facing_left=True)
        context = {
            actor,
            prop,
            CameraRange(left=camera_left, right=camera_left + 256, top=0, bottom=112),
            Stage(level_index=0, direction="right"),
        }
        gamepad, _client = _gamepad()
        _settle(OpenBreakable(actor_slot="P1", target_slot="obj02"), context, gamepad)
        return gamepad.held

    def test_commands_something_while_pinned_at_the_clamp(self) -> None:
        mask = self._run(camera_left=2455)

        self.assertTrue(mask & (LEFT | RIGHT), f"frozen at the clamp (mask {hex(mask)})")
        self.assertTrue(mask & RIGHT, "the prop is to the right; facing it is the point")

    def test_still_backs_away_first_with_room_to_do_it(self) -> None:
        # Unchanged away from the clamp: the headroom trick is the preferred
        # half of the nudge and only the blocked case now overrides it.
        mask = self._run(camera_left=2300)

        self.assertTrue(mask & LEFT)


class AntonioLaneBreakTests(unittest.TestCase):
    """The uncommitted half of ``DodgeAntonioKick``: walk out of his gate.

    Also the regression test for the class of bug that only showed live --
    the executor's uncommitted branch had never been driven by a unit test,
    so a missing import in it reached a real fight before anything caught it.
    """

    def test_steps_away_from_his_lane(self) -> None:
        actor = _myself(world_x=100, world_y=60)
        antonio = _live_antonio(world_x=140, world_y=54)
        verb = DodgeAntonioKick(
            actor_slot="P1", target_slot="obj00", committed=False
        )
        gamepad, _client = _gamepad()

        context = {actor, antonio, CameraRange(left=0, right=320, top=0, bottom=112)}
        _settle(verb, context, gamepad)

        # Actor is below him, so it steps further down, and never jumps.
        self.assertTrue(gamepad.held & DOWN)
        self.assertFalse(gamepad.held & C)

    def test_a_committed_kick_still_jumps(self) -> None:
        actor = _myself(world_x=100, world_y=60)
        antonio = _live_antonio(world_x=140, world_y=54)
        verb = DodgeAntonioKick(actor_slot="P1", target_slot="obj00", committed=True)
        gamepad, client = _gamepad()

        execute_verb(
            verb,
            {actor, antonio, CameraRange(left=0, right=320, top=0, bottom=112)},
            gamepad,
        )

        self.assertTrue(client.press_buttons.called or client.hold_buttons.called)


def _live_antonio(*, world_x: int, world_y: int) -> Antonio:
    return Antonio(
        slot="obj00",
        type_id=0x56,
        world_x=world_x,
        world_y=world_y,
        health=24,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        primary_state=1,
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


# Roughly a ground walk's travel per AI tick (a couple of px per 60 Hz frame,
# ~2 frames per poll). Only the trajectory's *shape* depends on it.
WALK_PX_PER_TICK = 3


def _walk(verb, actor, others, *, ticks: int = 80):
    """Run the executor in a loop and let the actor actually move.

    A single tick's mask says very little now that the route is replanned
    every tick: what matters is where the actor ends up and what it walked
    through on the way. These tests therefore drive the real handler, apply
    its mask to the actor's position, and inspect the whole trail.
    """

    gamepad, _client = _gamepad()
    trail = [actor]
    for _ in range(ticks):
        execute_verb(verb, {actor, *others}, gamepad)
        mask = gamepad.held
        dx = (WALK_PX_PER_TICK if mask & RIGHT else 0) - (WALK_PX_PER_TICK if mask & LEFT else 0)
        dy = (WALK_PX_PER_TICK if mask & DOWN else 0) - (WALK_PX_PER_TICK if mask & UP else 0)
        actor = replace(actor, world_x=actor.world_x + dx, world_y=actor.world_y + dy)
        if dx:
            actor = replace(actor, facing_left=dx < 0)
        trail.append(actor)
    return trail


def _body_of(actor) -> Rect:
    from sor_autoplay.ai import navigation as nav

    return nav.body_rect(actor)


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


class SoutherPocketApproachTests(unittest.TestCase):
    """reach.SOUTHER_SLASH_DIST_MIN (24px) is where $15EDA cannot begin the
    slash at all. Measured live: 220 of 240 health lost across a full fight
    went in during the wind-up that follows his state-1 commit, which the
    punch's own outer edge (46px for Axel) sits squarely inside."""

    def _souther(self, **overrides) -> Souther:
        fields = dict(
            slot="obj11",
            type_id=0x55,
            world_x=200,
            world_y=100,
            health=32,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
            primary_state=1,
            tactical=0,
        )
        fields.update(overrides)
        return Souther(**fields)

    def test_stops_inside_the_inner_abort(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        souther = self._souther(world_x=200, world_y=100)

        target_x, _ = _walk_to_near_enemy_target(actor, souther, set())

        stop_dx = souther.world_x - target_x
        self.assertLess(stop_dx, SOUTHER_SLASH_DIST_MIN, "still outside the commit gate")
        self.assertGreaterEqual(
            stop_dx, punch_usable_inner_x(0), "too close for Axel's own punch"
        )

    def test_committed_souther_is_not_pocketed(self) -> None:
        # Once the claw is out, 24px is where $161C6 resolves the dash, not a
        # pocket -- DodgeSoutherSlash owns that window, not the approach.
        actor = _myself(world_x=100, world_y=100)
        committed = self._souther(
            world_x=200,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            tactical=2,
        )

        target_x, _ = _walk_to_near_enemy_target(actor, committed, set())

        stop_dx = committed.world_x - target_x
        self.assertGreaterEqual(stop_dx, SOUTHER_SLASH_DIST_MIN)

    def test_pocket_is_reached_from_the_other_side(self) -> None:
        actor = _myself(world_x=300, world_y=100, facing_left=True)
        souther = self._souther(world_x=200, world_y=100, facing_left=False)

        target_x, _ = _walk_to_near_enemy_target(actor, souther, set())

        stop_dx = target_x - souther.world_x
        self.assertLess(stop_dx, SOUTHER_SLASH_DIST_MIN)
        self.assertGreaterEqual(stop_dx, punch_usable_inner_x(0))

    def test_every_character_stays_above_their_own_punch_floor(self) -> None:
        for cid in (0, 1, 2):
            actor = replace(_myself(world_x=100, world_y=100), character_id=cid)
            souther = self._souther(world_x=200, world_y=100)

            target_x, _ = _walk_to_near_enemy_target(actor, souther, set())

            stop_dx = souther.world_x - target_x
            self.assertGreaterEqual(stop_dx, punch_usable_inner_x(cid), f"character {cid}")
            self.assertLess(stop_dx, SOUTHER_SLASH_DIST_MIN, f"character {cid}")


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

    def test_the_approach_leaves_a_dangerous_enemys_attack_band_alone(self) -> None:
        # The approach must not walk down the ground a committed enemy is
        # swinging through. It used to sidestep the enemy's *lane* on sight,
        # 200px out, because a lane was all it could see; now the swing's own
        # box is an obstacle, so the route stays out of the box itself and
        # only bends around it where it actually is.
        swing = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=0,
            forward_max=48,
            lane_min=-8,
            lane_max=8,
            height_min=0,
            height_max=32,
        )
        target = replace(
            _enemy(world_x=200, world_y=50),
            combat_phase=CombatPhase.ATTACKING,
            attack_ranges=(swing,),
            facing_left=True,
        )
        band = Rect(200 - 48, 50 - 8, 48, 16)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")

        trail = _walk(verb, _myself(world_x=0, world_y=50), {target})

        stop_dx = execute_module._enemy_stop_dx(trail[0], target)
        crossed = [
            (a.world_x, a.world_y)
            for a in trail
            if abs(target.world_x - a.world_x) > stop_dx and _body_of(a).overlaps(band)
        ]
        self.assertFalse(crossed, f"walked through the swing at {crossed[:3]}")
        self.assertGreater(
            trail[-1].world_x, trail[0].world_x + 100, "never closed the distance"
        )

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
        # For an ordinary enemy the offset side is still the lane band's own
        # midpoint, which does not move tick to tick: with no CameraRange,
        # _lane_bounds defaults to lo=8, hi=106 (midpoint 57), and a target at
        # 50 sits below it, so the offset pushes up regardless of which side
        # the actor stands on. Reading the actor's own side instead is scoped
        # to Antonio -- see the tests below and _approach_lane_y.
        actor = _myself(world_x=0, world_y=60)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}

        target_x, target_y = _walk_to_near_enemy_target(actor, target, context)

        self.assertEqual(target_y, 50 - WALK_TO_ENEMY_LANE_SAFETY_Y)

    def test_an_antonio_approach_never_crosses_his_lane(self) -> None:
        # Actor at 60 against an Antonio at 50 steps further down, not up
        # through his own lane. Measured over the real executor with the
        # midpoint rule: an approach starting 20px clear crossed to 5px and
        # then 2px of his kick lane while still 130px away on X.
        actor = _myself(world_x=0, world_y=60)
        antonio = _live_antonio(world_x=200, world_y=50)

        _, target_y = _walk_to_near_enemy_target(actor, antonio, {actor, antonio})

        self.assertEqual(target_y, 50 + ANTONIO_APPROACH_LANE_Y)

    def test_an_antonio_approach_picks_the_side_with_room_when_on_his_lane(self) -> None:
        # Practically on his lane: the raw compare is walk jitter, so the
        # room in the band decides instead (lo=8, hi=106, midpoint 57; a
        # target at 20 has the room below it).
        actor = _myself(world_x=0, world_y=22)
        antonio = _live_antonio(world_x=200, world_y=20)

        _, target_y = _walk_to_near_enemy_target(actor, antonio, {actor, antonio})

        self.assertEqual(target_y, 20 + ANTONIO_APPROACH_LANE_Y)

    def test_an_antonio_approach_crosses_only_with_no_room_on_its_own_side(self) -> None:
        # Actor above an Antonio near the top of the band: stepping further
        # up leaves the playable lanes entirely, so crossing is forced rather
        # than chosen.
        actor = _myself(world_x=0, world_y=12)
        antonio = _live_antonio(world_x=200, world_y=30)

        _, target_y = _walk_to_near_enemy_target(actor, antonio, {actor, antonio})

        self.assertEqual(target_y, 30 + ANTONIO_APPROACH_LANE_Y)

    def test_an_antonio_approach_aims_wider_than_his_kick_gate(self) -> None:
        # The routed goal carries PUNCH_RANGE_Y of lane slack, so an aim of
        # WALK_TO_ENEMY_LANE_SAFETY_Y is satisfied by arriving 16px out --
        # his $10 kick gate, satisfied. ANTONIO_APPROACH_LANE_Y adds the
        # slack back so the nearest acceptable arrival is 28px clear.
        self.assertGreaterEqual(
            ANTONIO_APPROACH_LANE_Y - PUNCH_RANGE_Y, WALK_TO_ENEMY_LANE_SAFETY_Y
        )

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


class FindSafeSpotTests(unittest.TestCase):
    """``execute._find_safe_spot`` -- where to back off to, for an actor with
    a live incoming-melee threat."""

    def _threatened(self):
        myself = _myself(world_x=100, world_y=60, facing_left=False)
        enemy = replace(
            _enemy(world_x=160, world_y=60), combat_phase=CombatPhase.ATTACKING
        )
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        return {myself, enemy, camera}

    def test_no_threat_no_safe_spot(self) -> None:
        myself = _myself()
        enemy = _enemy()

        self.assertIsNone(_find_safe_spot(myself, {myself, enemy}))

    def test_backs_away_from_the_threat(self) -> None:
        context = self._threatened()
        myself = next(t for t in context if isinstance(t, Myself))

        spot = _find_safe_spot(myself, context)

        self.assertIsNotNone(spot)
        self.assertLess(spot[0], 100)

    def test_sidesteps_instead_of_backing_into_a_pit(self) -> None:
        # The straight retreat lands at x=68 (RETREAT_FROM_DANGER_DISTANCE
        # back from 100); a pit spanning that column, at every lane, must
        # rule out all three of its candidates and leave only the two pure
        # sidesteps.
        context = self._threatened() | {Pit(world_x=40, lane_y=0, width=40, height=112)}
        myself = next(t for t in context if isinstance(t, Myself))

        spot = _find_safe_spot(myself, context)

        self.assertIsNotNone(spot)
        self.assertEqual(spot[0], 100)
        self.assertNotEqual(spot[1], 60)

    def test_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression (live-diagnosed, same shape as execute.py's other X
        # picks): the old "away" sign was a raw compare between actor and
        # threat X, so a couple of px of jitter right around alignment
        # flipped every candidate here -- including the sidesteps -- to the
        # opposite side.
        actor = _myself(world_x=100, world_y=60, facing_left=True)
        xs = []
        for threat_x in (99, 100, 101):
            threat = _enemy(world_x=threat_x, world_y=60)
            xs.append(_safe_spot_candidates(actor, threat)[0][0])

        self.assertEqual(len(set(xs)), 1, f"away side flipped across alignment: {xs}")

    def test_prefers_the_plain_retreat_over_a_near_tied_sidestep(self) -> None:
        # Regression: candidates used to be picked by raw max clearance, so
        # two candidates within a couple of px of each other on ordinary
        # jitter flipped which one won -- and since the candidates differ in
        # whether they add a Y step, that flip read live as the actor
        # darting into a vertical dash instead of holding a steady retreat
        # line. Pits carve away every candidate except the plain retreat
        # (index 0, x=68,y=60) and the X-away-plus-Y-up sidestep (x=68,
        # y=36), and a bystander enemy at (68, 51) is placed so the
        # sidestep's *raw* clearance (15px) edges out the plain retreat's
        # (9px) by less than SAFE_SPOT_PREFERENCE_MARGIN -- old code picked
        # the sidestep; the anchor bias must keep picking the plain retreat.
        myself = _myself(world_x=100, world_y=60, facing_left=False)
        threat = replace(
            _enemy(world_x=160, world_y=60), combat_phase=CombatPhase.ATTACKING
        )
        bystander = replace(
            _enemy(world_x=68, world_y=51), slot="obj02", combat_phase=CombatPhase.NORMAL
        )
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        context = {myself, threat, bystander, camera}
        context = context | {
            Pit(world_x=0, lane_y=76, width=400, height=8),
            Pit(world_x=90, lane_y=28, width=20, height=8),
        }

        spot = _find_safe_spot(myself, context)

        self.assertEqual(spot, (68, 60))

    def test_rejects_a_candidate_whose_route_is_blocked_by_a_breakable(self) -> None:
        # The plain retreat (index 0) lands at (68, 60) -- straight line
        # from the actor's (100, 60). A prop whose push-back box (x 38..98,
        # lane 48..80 for one standing at (68, 76)) covers exactly that spot
        # makes the candidate unreachable, even though it survives every
        # pre-existing filter (in lane, in camera, not a pit). The two
        # sidesteps that also step to x=68 clear the box's lane range and
        # must win instead.
        context = self._threatened() | {
            Breakable(slot="crate1", world_x=68, world_y=76, type_id=0x1D)
        }
        myself = next(t for t in context if isinstance(t, Myself))

        spot = _find_safe_spot(myself, context)

        self.assertIsNotNone(spot)
        self.assertNotEqual(spot, (68, 60))
        self.assertEqual(spot[0], 68)
        self.assertIn(spot[1], (84, 36))

    def test_threats_own_presence_does_not_reject_every_candidate(self) -> None:
        # The threat being fled sits close enough (12px) that, if its own
        # body/reach were counted as danger for this reachability gate, it
        # would sit on or near several candidates by construction. With no
        # other obstacles at all, a plausible candidate (the plain retreat)
        # is still produced.
        myself = _myself(world_x=100, world_y=60, facing_left=False)
        threat = replace(
            _enemy(world_x=112, world_y=60), combat_phase=CombatPhase.ATTACKING
        )
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        context = {myself, threat, camera}

        spot = _find_safe_spot(myself, context)

        self.assertEqual(spot, (68, 60))

    def test_no_safe_spot_when_every_candidate_is_boxed_in(self) -> None:
        # Every candidate step _safe_spot_candidates offers is walled off by
        # crates on all four sides, tight enough that the actor's own 16x16
        # body has no room to move at all -- not even the plain retreat can
        # find a route. _find_safe_spot must fall back to producing no spot
        # at all (today's existing "no candidate survives" outcome, `best is
        # None`), rather than handing the executor a destination that
        # cannot actually be walked to.
        # Rows of wide round-6 props (push-back box x +/-36, lane -20..+4)
        # tile the lanes above and below, overlapping so no one-pixel line
        # between two boxes is left standable, and a deep prop (lane -28..+4)
        # seals the actor's own lane on the side it would retreat toward.
        # The actor's lane is the one gap none of them reach into.
        context = (
            self._threatened()
            | {
                Breakable(slot=f"wall{x}_{y}", world_x=x, world_y=y, type_id=0x41)
                for x in (40, 76, 112)
                for y in (40, 52, 88, 104)
            }
            | {Breakable(slot="wall_w", world_x=68, world_y=76, type_id=0x1D)}
        )
        myself = next(t for t in context if isinstance(t, Myself))

        self.assertIsNone(_find_safe_spot(myself, context))


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

    def test_prefers_a_found_safe_spot(self) -> None:
        # _find_safe_spot already weighs the sidesteps against the straight
        # retreat (clearance from every live enemy, lane/camera bounds,
        # pits). A pit spanning the whole lane at the straight-retreat X
        # rules out every X-away candidate, leaving only the two pure
        # Y-sidesteps -- the executor must steer there rather than
        # re-deciding "straight back on X".
        actor = _myself(world_x=100, world_y=60)
        target = replace(_enemy(world_x=160, world_y=60), combat_phase=CombatPhase.ATTACKING)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        pit = Pit(world_x=40, lane_y=0, width=40, height=112)
        context = {actor, target, camera, pit}
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

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_enemy()}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_not_called()

    def test_routes_around_another_enemy_on_the_straight_retreat_line(self) -> None:
        """`_movement_mask`'s straight-line fallback only ever dodges pits
        and breakables -- it has no idea a *third* enemy's body sits on the
        way to safety, exactly the geometry `navigation.py`'s obstacle sets
        exist to avoid. Put one squarely on the second retreat step's line
        (`RETREAT_FROM_DANGER_DISTANCE` alone is too short for any body to
        fit between two 16px-wide actors without touching one of them, so
        the multi-tick harness has to take two steps before the blocker is
        actually in the way) and check the whole trail steers clear of it
        while still ending up farther from the fleeing threat than it
        started.
        """

        from sor_autoplay.ai import navigation as nav

        actor = _myself(world_x=100, world_y=50)
        threat = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        blocker = replace(_enemy(world_x=60, world_y=50), slot="obj02")
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")

        trail = _walk(verb, actor, [threat, blocker])

        blocker_rect = nav.enemy_rects(blocker)[0]
        for state in trail:
            self.assertFalse(
                _body_of(state).overlaps(blocker_rect),
                f"retreat walked through the blocker at {state.world_x},{state.world_y}",
            )
        self.assertLess(trail[-1].world_x, trail[0].world_x)
        self.assertGreater(
            abs(trail[-1].world_x - threat.world_x),
            abs(trail[0].world_x - threat.world_x),
        )


def _projectile(*, world_x: int = 0, world_y: int = 0, vel_x: float = -5.0) -> Projectile:
    return Projectile(
        slot="obj10", world_x=world_x, world_y=world_y, vel_x=vel_x, vel_z=0.0, type_id=0x1E
    )


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

    def test_routes_around_a_committed_enemys_reach_on_the_straight_lane(self) -> None:
        # The straight-line sidestep is blind to anything but the crate/pit
        # dodges baked into _movement_mask, so a swing sitting on the 40px
        # lane it steps through used to be walked straight into. The routed
        # version treats every live enemy's *committed* reach as danger
        # (navigation.enemy_rects: "only committed enemies contribute
        # reach"), same as WalkToNearEnemy/OpenBreakable already do, so it
        # must bend around this one instead.
        #
        # Enemy body sits off to the side (x=140) so only its projected
        # AttackRange -- not its body -- covers the straight path at x=100.
        swing = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=0,
            forward_max=48,
            lane_min=-8,
            lane_max=8,
            height_min=0,
            height_max=32,
        )
        enemy = replace(
            _enemy(world_x=140, world_y=70),
            combat_phase=CombatPhase.ATTACKING,
            attack_ranges=(swing,),
            facing_left=True,
        )
        # facing_left=True projects the swing behind (to smaller x than) the
        # enemy's own origin: x in [140-48, 140-0] = [92, 140], y in [62, 78]
        # -- squarely across the actor's straight vertical path at x=100.
        reach_band = Rect(92, 62, 48, 16)

        actor = _myself(world_x=100, world_y=50)
        projectile = _projectile(world_x=150, world_y=50)
        verb = ProjectileSidestep(actor_slot="P1", target_slot="obj10")

        # A short window, not a run to convergence: _projectile_sidestep_
        # target recomputes its aim from the actor's *current* position every
        # tick (unchanged by this routing work -- see its own docstring), so
        # driven long enough it settles the actor near the lane's midpoint
        # regardless of routing, the same way the unrouted straight-line
        # version already does. That is this verb's existing, out-of-scope
        # behaviour; what belongs to this change is only that the first
        # several ticks -- the window a real incoming throw is actually
        # judged a threat in -- both clear real distance off the lane and
        # never cross the swing while doing it.
        trail = _walk(verb, actor, {projectile, enemy}, ticks=15)

        crossed = [
            (a.world_x, a.world_y) for a in trail if _body_of(a).overlaps(reach_band)
        ]
        self.assertFalse(crossed, f"walked into the swing at {crossed[:3]}")
        # Still clears the lane: upper half at world_y=50 steps toward larger
        # y, same direction the straight line would have picked, and the
        # detour around the swing does not erase that progress.
        cleared = max(a.world_y for a in trail) - trail[0].world_y
        self.assertGreaterEqual(cleared, 8, "never made real progress off the lane")
        # And it actually routed -- stepped off the straight vertical line to
        # get around the swing -- rather than being blocked in place on X.
        self.assertTrue(any(a.world_x != trail[0].world_x for a in trail))


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

    def test_pure_lateral_advance_with_nothing_in_the_way(self) -> None:
        # Routed through the path finder now, but with an empty playfield
        # ahead the route is a straight RIGHT vector and no accidental
        # Up/Down should appear -- this is the actor-present counterpart of
        # test_direction_right_holds_right above (which never resolves an
        # actor at all).
        actor = _myself(world_x=100, world_y=64)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        _settle(verb, {actor}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)

    def test_sidesteps_a_pit_on_the_current_lane_instead_of_walking_in(self) -> None:
        # Live-reported: the AI walked into a pit it had room to go around.
        # A 40px PointGoal on the current Y sat inside the hole, the route
        # was best-effort RIGHT, and the actor stepped in. The lookahead is
        # now a vertical strip, so the walk must leave that lane and pass
        # the hole without the origin ever sitting in it.
        pit = Pit(world_x=400, lane_y=40, width=96, height=40)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        trail = _walk(
            verb,
            _myself(world_x=360, world_y=60),
            {pit, Stage(level_index=3, direction="right")},
            ticks=80,
        )

        entered = [
            (a.world_x, a.world_y)
            for a in trail
            if pit_endangers(pit, a.world_x, a.world_y)
        ]
        self.assertFalse(entered, f"walked into the pit at {entered[:3]}")
        self.assertGreater(trail[-1].world_x, pit.world_x + pit.width)
        self.assertTrue(
            any(a.world_y != 60 for a in trail),
            "stayed on the pit's lane the whole way",
        )

    def test_hops_when_the_pathfinder_cannot_walk_around_a_pit(self) -> None:
        # Full-width pit, landing in Axel's 60px kick range. Walking cannot
        # go around, so the executor must launch (C + RIGHT), not walk in.
        pit = Pit(world_x=120, lane_y=0, width=24, height=130)
        actor = _myself(world_x=100, world_y=64)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, _client = _gamepad()
        context = {
            actor,
            pit,
            Stage(level_index=3, direction="right"),
            CameraRange(left=0, right=400, top=0, bottom=112),
        }

        execute_verb(verb, context, gamepad)

        # Launch is a press (C + RIGHT), then hold keeps only the direction
        # -- same shape as JumpAttack. gamepad.held is the sticky latch,
        # so the hop is visible on press_buttons.
        _client.press_buttons.assert_called_once_with(player1=C | RIGHT, player2=0, frames=3)

    def test_does_not_walk_into_an_unjumpable_full_width_pit(self) -> None:
        # 96px gap, wider than Axel's kick. Pathfinder cannot walk around
        # and cannot hop. The old `or RIGHT` fallback walked in.
        pit = Pit(world_x=400, lane_y=0, width=96, height=130)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        trail = _walk(
            verb,
            _myself(world_x=360, world_y=60),
            {
                pit,
                Stage(level_index=3, direction="right"),
                CameraRange(left=200, right=560, top=0, bottom=112),
            },
            ticks=40,
        )

        entered = [
            (a.world_x, a.world_y)
            for a in trail
            if pit_endangers(pit, a.world_x, a.world_y)
        ]
        self.assertFalse(entered, f"walked into the pit at {entered[:3]}")
        self.assertFalse(
            any(a.world_x > pit.world_x for a in trail),
            "advanced past the pit wall without hopping",
        )

    def test_routes_around_a_breakable_on_the_lookahead_line(self) -> None:
        # Breakables are still solid obstacles for this verb's router (the
        # same set the pre-routing ad-hoc dodge avoided), so a crate sitting
        # squarely on the 40px lookahead point must be routed around on Y,
        # never walked through -- and the lateral bit must never disappear
        # while doing it, since nothing here freezes X the way the pit dodge
        # does.
        prop = Breakable(slot="obj09", world_x=200, world_y=64, type_id=0x40)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")

        # Starts well clear of the solid's own push-back rect: a body that
        # already overlaps a solid at
        # the start has that obstacle dropped from the whole search (the
        # path finder's "already stuck in it" rule), which would make this
        # test pass by construction rather than by actually routing around
        # it.
        trail = _walk(verb, _myself(world_x=100, world_y=64), {prop}, ticks=60)

        wall = prop_solids.solid_box(prop.type_id, prop.world_x, prop.world_y)
        overlapped = [(a.world_x, a.world_y) for a in trail if wall.blocks(a.world_x, a.world_y)]
        self.assertFalse(overlapped, f"walked into the breakable at {overlapped[:3]}")
        self.assertGreater(
            trail[-1].world_x, prop.world_x + 40, "never advanced past the crate"
        )

    def test_lateral_bit_survives_a_dangerous_enemy_on_the_lookahead_line(self) -> None:
        # Live enemy reach is deliberately *not* routed around by this verb
        # (see the comment in state_machine_walk_to_advance_stage on why --
        # a lookahead goal that lands inside a nearby enemy's own reach box
        # makes nav.plan_route's danger-aware pass unable to ever "reach",
        # which falls through to the danger-blind solids-only pass and is
        # worse than doing nothing). So this is a guard against a future
        # change reintroducing danger obstacles here without also fixing
        # that failure mode: the direction bit must never drop, tick after
        # tick, even with a committed enemy sitting directly in the way.
        swing = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=0,
            forward_max=48,
            lane_min=-8,
            lane_max=8,
            height_min=0,
            height_max=32,
        )
        enemy = replace(
            _enemy(world_x=180, world_y=64),
            combat_phase=CombatPhase.ATTACKING,
            attack_ranges=(swing,),
            facing_left=True,
        )
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, _client = _gamepad()
        # Settle the virtual steering axis first -- a brand new gamepad needs
        # AXIS_RAMP_TICKS of a steady command before it reports an edge at
        # all (see gamepad.py), which is orthogonal to what this test is
        # checking and would otherwise read as a spurious "lost the lateral
        # bit" at tick 0.
        _settle(verb, {_myself(world_x=100, world_y=64), enemy}, gamepad)
        x = 100
        for _ in range(40):
            actor = _myself(world_x=x, world_y=64)
            execute_verb(verb, {actor, enemy}, gamepad)
            held = gamepad.held
            self.assertTrue(held & RIGHT, f"lost the lateral bit at x={x} (mask {hex(held)})")
            x += WALK_PX_PER_TICK

    def test_does_not_hold_into_the_camera_walk_clamp(self) -> None:
        # Live level-1 wave gate: actor at world x=1504, camera.right=1504,
        # WalkToAdvanceStage held RIGHT and the ROM undid every step. The
        # sidewalk trash can in frame is not even an object.
        actor = _myself(world_x=1504, world_y=64)
        camera = CameraRange(left=1248, right=1504, top=0, bottom=112)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        _settle(verb, {actor, camera, Stage(level_index=0, direction="right")}, gamepad)

        held = gamepad.held
        self.assertFalse(held & RIGHT, f"pushed into the camera clamp: {held:#x}")

    def test_still_advances_when_the_camera_has_room(self) -> None:
        actor = _myself(world_x=1400, world_y=64)
        camera = CameraRange(left=1216, right=1472, top=0, bottom=112)
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        _settle(verb, {actor, camera, Stage(level_index=0, direction="right")}, gamepad)

        client.hold_buttons.assert_called_with(player1=RIGHT, player2=0)


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
        # could_melee_weapon_attack's job now), but execution itself is
        # unconditional on whatever Verb it's given.
        actor = replace(_myself(), held_weapon_type=0x0A)  # baseball bat
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteMeleeWeaponAttackTests(unittest.TestCase):
    def test_presses_button_b_for_bat_or_pipe(self) -> None:
        verb = MeleeWeaponAttack(actor_slot="P1", target_slot="obj01", weapon_type=0x0A)
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_presses_button_b_for_knife_or_bottle(self) -> None:
        verb = MeleeWeaponAttack(actor_slot="P1", target_slot="obj01", weapon_type=0x08)
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_presses_button_b_for_pepper(self) -> None:
        verb = MeleeWeaponAttack(actor_slot="P1", target_slot="obj01", weapon_type=0x0C)
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteCallPoliceTests(unittest.TestCase):
    def test_call_police_presses_button_a(self) -> None:
        verb = CallPolice(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=A, player2=0, frames=4)


class ExecuteHandleContinueMenuTests(unittest.TestCase):
    def test_confirms_yes_with_a_face_button(self) -> None:
        verb = HandleContinueMenu(actor_slot="P1")
        menu = InContinueMenu(slot="P1", name_entry=False, selects_no=False)
        gamepad, client = _gamepad()

        execute_verb(verb, {menu}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_toggles_off_no_with_up(self) -> None:
        verb = HandleContinueMenu(actor_slot="P1")
        menu = InContinueMenu(slot="P1", name_entry=False, selects_no=True)
        gamepad, client = _gamepad()

        execute_verb(verb, {menu}, gamepad)

        client.press_buttons.assert_called_once_with(player1=UP, player2=0, frames=4)

    def test_name_entry_confirms_a_when_already_on_a(self) -> None:
        # $57D2 confirms on +$55 bits 5+6 (C/A). B is bit 4 -- backspace --
        # and a no-op on slot 0, which is how the AI sat on the first
        # initial forever pressing the attack button.
        verb = HandleContinueMenu(actor_slot="P1")
        menu = InContinueMenu(
            slot="P1",
            name_entry=True,
            selects_no=False,
            name_slot=0,
            name_letter_index=0,
        )
        gamepad, client = _gamepad()

        execute_verb(verb, {menu}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=4)

    def test_name_entry_confirms_i_with_c_not_b(self) -> None:
        verb = HandleContinueMenu(actor_slot="P1")
        menu = InContinueMenu(
            slot="P1",
            name_entry=True,
            selects_no=False,
            name_slot=2,
            name_letter_index=8,
        )
        gamepad, client = _gamepad()

        execute_verb(verb, {menu}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=4)

    def test_name_entry_steps_right_toward_i(self) -> None:
        verb = HandleContinueMenu(actor_slot="P1")
        menu = InContinueMenu(
            slot="P1",
            name_entry=True,
            selects_no=False,
            name_slot=2,
            name_letter_index=0,
        )
        gamepad, client = _gamepad()

        execute_verb(verb, {menu}, gamepad)

        client.press_buttons.assert_called_once_with(player1=RIGHT, player2=0, frames=4)

    def test_name_entry_finishes_with_start_after_two_letters(self) -> None:
        verb = HandleContinueMenu(actor_slot="P1")
        menu = InContinueMenu(
            slot="P1",
            name_entry=True,
            selects_no=False,
            name_slot=4,
            name_letter_index=0,
        )
        gamepad, client = _gamepad()

        execute_verb(verb, {menu}, gamepad)

        client.press_buttons.assert_called_once_with(player1=START, player2=0, frames=4)


class ExecuteHandleMrXDialogTests(unittest.TestCase):
    def test_holds_down_until_no_is_selected(self) -> None:
        verb = HandleMrXDialog(actor_slot="P1")
        dialog = InMrXDialog(slot="P1", selects_no=False)
        gamepad, client = _gamepad()

        execute_verb(verb, {dialog}, gamepad)

        client.hold_buttons.assert_called_with(player1=DOWN, player2=0)

    def test_confirms_no_with_a_face_button(self) -> None:
        verb = HandleMrXDialog(actor_slot="P1")
        dialog = InMrXDialog(slot="P1", selects_no=True)
        gamepad, client = _gamepad()

        execute_verb(verb, {dialog}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteJumpAttackTests(unittest.TestCase):
    def test_presses_jump_with_direction_when_grounded(self) -> None:
        actor = _myself(world_x=0, world_y=0, is_airborne=False)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C | RIGHT, player2=0, frames=3)

    def test_hops_in_place_on_antonio_inside_punch_range(self) -> None:
        # A directed hop from dx=40 (Axel punch outer 50) carries ~3 px/frame
        # past him; the actor lands facing away and grab_would_connect fails.
        # Measured live: 374 JumpAttack, 0 GrabEnemy. C with no direction
        # is the hop that lands in grab range.
        actor = _myself(world_x=120, world_y=100)
        antonio = Antonio(
            slot="obj09",
            type_id=0x56,
            world_x=160,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
            primary_state=1,
        )
        verb = JumpAttack(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, antonio}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=3)

    def test_still_hops_toward_antonio_outside_punch_range(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        antonio = Antonio(
            slot="obj09",
            type_id=0x56,
            world_x=155,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
            primary_state=1,
        )
        verb = JumpAttack(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, antonio}, gamepad)

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

    def test_pit_override_does_not_steal_an_airborne_actor(self) -> None:
        # Mid-jump, X overlaps the pit and pit_endangers is true (it is a
        # lane-plane test). The override used to freeze X and drop the kick
        # -- which is how a hop that would have cleared the gap fell in.
        pit = Pit(world_x=20, lane_y=0, width=80, height=40)
        actor = _myself(world_x=50, world_y=20, is_airborne=True, action_state=0x12)
        enemy = _enemy(world_x=100, world_y=20)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_tick(verb, {actor, enemy, pit}, gamepad)

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
        # In range (dx=-20) but facing right when the prop needs left: never
        # combine the turn with the punch on the same press (see
        # OpenBreakableFacingTests for why -- the ROM samples facing at the
        # start of the swing, so a same-tick turn+B is a committed miss).
        # No press yet; walk toward the correct side first.
        actor = _myself(world_x=120, world_y=90, facing_left=False)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        client.press_buttons.assert_not_called()

    def test_eventually_faces_and_hits_the_prop(self) -> None:
        # Same start as above, driven to completion: walking toward the
        # correct side (never a bare one-frame turn press -- measured live,
        # that left the actor frozen at the same position and action byte
        # for 60 seconds, see BREAKABLE_FACE_NUDGE_X) flips facing as a side
        # effect, and only then does the punch fire, facing the prop.
        actor = _myself(world_x=120, world_y=90, facing_left=False)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        for _ in range(30):
            execute_verb(verb, {actor, prop}, gamepad)
            if client.press_buttons.called:
                break
            mask = gamepad.held
            dx = (WALK_PX_PER_TICK if mask & RIGHT else 0) - (
                WALK_PX_PER_TICK if mask & LEFT else 0
            )
            dy = (WALK_PX_PER_TICK if mask & DOWN else 0) - (
                WALK_PX_PER_TICK if mask & UP else 0
            )
            actor = replace(actor, world_x=actor.world_x + dx, world_y=actor.world_y + dy)
            if dx:
                actor = replace(actor, facing_left=dx < 0)
        else:
            self.fail("never punched the prop")
        client.press_buttons.assert_called_once_with(player1=B | LEFT, player2=0, frames=4)

    def test_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression, same shape as the enemy/retreat/release-grab side
        # picks: dy=40 keeps the actor outside smash range on Y (in_smash_
        # range requires BREAKABLE_PUNCH_Y=8) so the walk-in target,
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
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        worst_case_dx = (
            breakable_smash_outer_x(prop) - BREAKABLE_STOP_BUFFER
        ) + MOVE_DEADBAND_X
        actor = _myself(world_x=100 - worst_case_dx, world_y=90)

        self.assertTrue(in_smash_range(actor, prop))

    def _assert_reaches_the_smash_pocket(self, actor, prop) -> None:
        """Arrives somewhere it can actually hit the crate, without ever
        standing inside it.

        This used to be asserted as "no vertical bit on this tick": the
        straight-line approach had to walk out to the crate's side *first*,
        because a diagonal to the smash pocket cut through the solid. The
        route now has the crate's own push-back box, so the shape of the path
        is its business -- what must hold is that the actor's own position is
        never inside that box (which is what the ROM tests) and that the walk
        ends somewhere ``in_smash_range``.
        """

        wall = prop_solids.solid_box(prop.type_id, prop.world_x, prop.world_y)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")

        trail = _walk(verb, actor, {prop, Stage(level_index=0, direction="right")})

        inside = [(a.world_x, a.world_y) for a in trail if wall.blocks(a.world_x, a.world_y)]
        self.assertFalse(inside, f"walked into the crate at {inside[:3]}")
        self.assertTrue(
            any(in_smash_range(a, prop) for a in trail),
            f"never reached smash range; ended at "
            f"{(trail[-1].world_x, trail[-1].world_y)}",
        )

    def test_above_the_prop_reaches_the_smash_pocket_without_entering_it(self) -> None:
        self._assert_reaches_the_smash_pocket(
            _myself(world_x=100, world_y=50),
            Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40),
        )

    def test_below_the_prop_reaches_the_smash_pocket_without_entering_it(self) -> None:
        # Inside the default lane clamp (LANE_Y_MIN+6 .. 0x70-6), so nothing
        # here depends on the clamp dragging an off-lane target back in.
        self._assert_reaches_the_smash_pocket(
            _myself(world_x=100, world_y=100),
            Breakable(slot="obj09", world_x=100, world_y=70, type_id=0x40),
        )

    def test_already_beside_the_prop_then_converges_on_its_lane(self) -> None:
        # Once X has reached the smash pocket, Y is allowed to move -- that
        # is the second half of the around-path.
        stop_dx = BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER
        actor = _myself(world_x=100 - stop_dx, world_y=50)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        _settle(verb, {actor, prop, Stage(level_index=0, direction="right")}, gamepad)

        held = client.hold_buttons.call_args.kwargs["player1"]
        self.assertTrue(held & DOWN, f"expected to walk onto the smash lane, got {held:#x}")
        self.assertFalse(held & (LEFT | RIGHT), f"X has arrived; must not wander, got {held:#x}")

    def test_wide_hitbox_still_walks_around_rather_than_through(self) -> None:
        # Different props have different footprints. The around-path must
        # read the real body, not assume every crate is a point at world_x.
        box = Hitbox(x0=80, x1=120, y0=70, y1=110, z0=0, z1=40)
        actor = _myself(world_x=100, world_y=50)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x11, hitbox=box)
        target_x, target_y = _walk_to_breakable_target(
            actor, prop, {Stage(level_index=0, direction="right")}
        )

        self.assertLess(target_x, box.x0)
        self.assertEqual(target_y, actor.world_y)

    def test_approach_does_not_dodge_the_prop_it_is_trying_to_smash(self) -> None:
        # _movement_mask's incidental dodge treats any breakable on the
        # walk's X span as an obstacle. The smash target *is* on that span
        # (from near-center to the side pocket), so dodging it pushed Y off
        # the punch band every tick of the walk-in and never closed X.
        # dx=5 is inside the punch inner edge, so this is a walk, not a smash
        # -- and still close enough that the prop's origin sits between the
        # actor and the smash pocket, which is what used to trip the dodge.
        actor = _myself(world_x=95, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        _settle(verb, {actor, prop, Stage(level_index=0, direction="right")}, gamepad)

        held = client.hold_buttons.call_args.kwargs["player1"]
        self.assertTrue(held & LEFT, f"expected to walk out to the smash pocket, got {held:#x}")


class OpenBreakableFacingTests(unittest.TestCase):
    """A prop cannot move, so "which way is it" never needs hysteresis --
    and answering "no direction" there is a hard stall.

    Measured live on stage 5: the actor came to rest 10px from a round-5
    prop, exactly DIRECTION_HYSTERESIS_X, facing away from it after walking
    in from the far side. Every tick it asked for a punch with no direction
    bit, so it never turned, and it threw ~2,300 of them into empty air over
    76 seconds. The same run had already broken an identical prop from 11px
    while facing it, so the position was fine; only the facing was not.

    The fix is never a same-tick turn+punch (the ROM samples facing at the
    start of the swing, so that is a committed miss) and never a bare
    one-frame turn press either (measured live: an isolated press did not
    reliably register at all, freezing the actor for as long as 60 seconds
    with no enemy nearby to jostle it loose). ``_drive_to_punch`` runs the
    real executor tick by tick, applying its own mask back to the actor's
    position the way the game would, until it actually punches.
    """

    def _drive_to_punch(self, actor_x: int, prop_x: int) -> int:
        prop = Breakable(slot="obj09", world_x=prop_x, world_y=48, type_id=0x1F)
        actor = _myself(world_x=actor_x, world_y=56, facing_left=True)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()
        stage = Stage(level_index=4, direction="right")

        for _ in range(30):
            execute_verb(verb, {actor, prop, stage}, gamepad)
            if client.press_buttons.called:
                return client.press_buttons.call_args.kwargs["player1"]
            mask = gamepad.held
            dx = (WALK_PX_PER_TICK if mask & RIGHT else 0) - (
                WALK_PX_PER_TICK if mask & LEFT else 0
            )
            dy = (WALK_PX_PER_TICK if mask & DOWN else 0) - (
                WALK_PX_PER_TICK if mask & UP else 0
            )
            actor = replace(actor, world_x=actor.world_x + dx, world_y=actor.world_y + dy)
            if dx:
                actor = replace(actor, facing_left=dx < 0)
        self.fail("never punched the prop")

    def test_turns_toward_a_prop_inside_the_hysteresis_band(self) -> None:
        # dx of exactly DIRECTION_HYSTERESIS_X: the live stall's geometry.
        mask = self._drive_to_punch(actor_x=2870, prop_x=2880)

        self.assertTrue(mask & B, f"expected a punch, got {mask:#x}")
        self.assertTrue(mask & RIGHT, f"expected to turn toward the prop, got {mask:#x}")

    def test_turns_the_other_way_for_a_prop_on_the_other_side(self) -> None:
        mask = self._drive_to_punch(actor_x=2890, prop_x=2880)

        self.assertTrue(mask & LEFT, f"expected to turn toward the prop, got {mask:#x}")

    def test_dead_centre_still_commits_to_a_side(self) -> None:
        # No sign to read: the stage's own direction decides, the same fixed
        # anchor the approach uses, so it cannot flip tick to tick. Standing
        # dead centre is short of smash range, so this asks the helper
        # directly rather than through a punch that would not be thrown.
        prop = Breakable(slot="obj09", world_x=2880, world_y=48, type_id=0x1F)
        actor = _myself(world_x=2880, world_y=57, facing_left=True)

        for direction, expected in (("right", RIGHT), ("left", LEFT)):
            with self.subTest(direction=direction):
                mask = execute_module._face_prop_mask(
                    actor, prop, {Stage(level_index=4, direction=direction)}
                )
                self.assertEqual(mask, expected)


class Stage5PropFenceTests(unittest.TestCase):
    """The live stall this whole push-back model exists for.

    Stage 5 stands its round-5 props ($1F) in a 2x2 fence: two at lane 56 and
    two at lane 96, 64px apart on x. Their *sprite* boxes leave a comfortable
    24px gap on x and a 20px corridor on lane. Their push-back boxes leave a
    3px gap on x and a 16px corridor on lane -- so an AI planning against the
    sprites walks confidently into ground it cannot occupy.

    Recorded live before the fix: the actor reached (1625, 74), was told by
    its own route to step down to lane 94, held DOWN into the fence and did
    not move for the remaining 2,500 ticks of the run.
    """

    STALL = (1625, 74)

    def _fence(self):
        return {
            Breakable(slot=f"obj{i:02d}", world_x=x, world_y=y, type_id=0x1F)
            for i, (x, y) in enumerate(
                ((1584, 56), (1648, 56), (1584, 96), (1648, 96))
            )
        }

    def _scene(self):
        return self._fence() | {
            CameraRange(left=1454, right=1710, top=0, bottom=112),
            Stage(level_index=4, direction="right"),
        }

    def _walls(self, scene):
        return [
            prop_solids.solid_box(p.type_id, p.world_x, p.world_y)
            for p in scene
            if isinstance(p, Breakable)
        ]

    def test_the_corridor_between_the_two_rows_is_where_it_walks(self) -> None:
        scene = self._scene()
        target = next(
            p for p in scene if isinstance(p, Breakable) and (p.world_x, p.world_y) == (1648, 96)
        )
        verb = OpenBreakable(actor_slot="P1", target_slot=target.slot)
        actor = _myself(world_x=self.STALL[0], world_y=self.STALL[1])

        trail = _walk(verb, actor, scene)

        walls = self._walls(scene)
        inside = [
            (a.world_x, a.world_y)
            for a in trail
            if any(w.blocks(a.world_x, a.world_y) for w in walls)
        ]
        self.assertFalse(inside, f"walked into the fence at {inside[:3]}")
        self.assertTrue(
            any(in_smash_range(a, target) for a in trail),
            f"never reached smash range; ended at "
            f"{(trail[-1].world_x, trail[-1].world_y)}",
        )

    def test_it_does_not_stand_still_against_the_fence(self) -> None:
        # The symptom, stated directly: the old model produced a mask that
        # commanded a move the game refused, forever. Whatever the route
        # decides, the actor must actually get somewhere.
        scene = self._scene()
        target = next(
            p for p in scene if isinstance(p, Breakable) and (p.world_x, p.world_y) == (1648, 96)
        )
        verb = OpenBreakable(actor_slot="P1", target_slot=target.slot)

        trail = _walk(verb, _myself(world_x=self.STALL[0], world_y=self.STALL[1]), scene)

        self.assertNotEqual((trail[-1].world_x, trail[-1].world_y), self.STALL)


class ExecuteMovementBreakableAvoidanceTests(unittest.TestCase):
    """Regression: the straight-line fallback must only dodge on-screen props.

    world_map tracks entities up to two screens beyond each camera edge for
    hunt-target lookahead, far past what's actually walkable. Without a
    camera filter, any breakable in that huge tracked radius could trip the
    dodge on a pure horizontal walk -- and since the dodge steers toward
    smaller Y when the actor is in the lane's lower half (the common case),
    that made the AI drift up for reasons unrelated to anything on screen.

    Tested against ``_movement_mask`` itself rather than through a walk verb:
    the filter lives there, and every routed verb reaches it only when the
    path finder comes back with nothing -- which, for one prop on an
    otherwise empty screen, it never does.
    """

    # Standing on the lane its push-back box covers (a round-6 prop at lane
    # 90 walls lane 70..94), 50px to the actor's left of the walk's target.
    ACTOR = (0, 90)
    TARGET = (100, 90)

    def _mask(self, camera: CameraRange) -> int:
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        return execute_module._movement_mask(
            {prop, camera}, *self.ACTOR, *self.TARGET
        )

    def test_dodges_a_breakable_that_is_actually_on_screen(self) -> None:
        mask = self._mask(CameraRange(left=0, right=200, top=0, bottom=112))

        self.assertEqual(mask, RIGHT | UP)

    def test_ignores_a_breakable_far_outside_the_camera(self) -> None:
        mask = self._mask(CameraRange(left=200, right=400, top=0, bottom=112))

        self.assertEqual(mask, RIGHT)

    def test_the_dodge_aims_clear_of_the_push_back_box(self) -> None:
        # The dodge used to aim at a fixed margin around the prop's *origin*,
        # which is not where its wall is: the ROM's boxes run up to 28px
        # behind an origin and only 4px in front of it. On stage 5's stacked
        # fence that aimed one prop's dodge into the prop below it.
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        wall = prop_solids.solid_box(prop.type_id, prop.world_x, prop.world_y)

        trail = _walk(
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            _myself(world_x=self.ACTOR[0], world_y=self.ACTOR[1]),
            {_enemy(world_x=self.TARGET[0], world_y=self.TARGET[1]), prop, camera},
        )

        inside = [(a.world_x, a.world_y) for a in trail if wall.blocks(a.world_x, a.world_y)]
        self.assertFalse(inside, f"walked into the prop at {inside[:3]}")


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

    def test_walks_around_a_pit_that_is_actually_on_screen(self) -> None:
        # The straight-line approach froze X until Y had cleared the pit,
        # because a diagonal it could not see the footprint of might still
        # cut the corner. The route has the footprint (grown by
        # PIT_AVOID_MARGIN, the same clearance every other pit check uses),
        # so the shape of the detour is its business -- what must hold is
        # that the actor never enters the danger zone and still arrives.
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")

        trail = _walk(verb, _myself(world_x=0, world_y=90), {target, pit, camera})

        # Judged by the AI's own predicate, on the actor's origin -- the
        # same sentence reach/inference/_pit_escape_mask all use.
        fell_in = [
            (a.world_x, a.world_y)
            for a in trail
            if pit_endangers(pit, a.world_x, a.world_y)
        ]
        self.assertFalse(fell_in, f"walked into the pit at {fell_in[:3]}")
        arrived = trail[-1]
        self.assertLessEqual(
            abs(target.world_x - arrived.world_x),
            punch_outer_x(arrived.character_id, arrived.held_weapon_type),
            f"never got in range: ended at {(arrived.world_x, arrived.world_y)}",
        )

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


class PitDodgeSideStabilityTests(unittest.TestCase):
    """Which side of a pit to escape to must come from the pit's own danger
    edges, never from the lane midpoint.

    The pit dodge *freezes X*, so nothing else is moving to break a tie --
    an unstable side pick here is permanent, unlike the Breakable dodge
    above (which keeps closing X and walks past the prop regardless). The
    lane midpoint has nothing to do with the pit and routinely falls inside
    its danger band, and the old rule steered the actor *toward* it (upper
    half aimed below, lower half aimed above): the actor crossed the
    midpoint, the pick flipped, and it crossed back forever.
    """

    def _sim(self, pit, start_y, ticks=60):
        """Drive WalkToAdvanceStage past ``pit`` and report the path.

        ~6px/tick on X and ~4px on Y -- ground walk (3.0/2.375 px per 60Hz
        frame) over the default 33ms poll's ~2 frames.
        """

        gamepad, _ = _gamepad()
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        x, y = 340, start_y
        reversals, last = 0, 0
        for _ in range(ticks):
            actor = _myself(world_x=x, world_y=y)
            camera = CameraRange(left=x - 128, right=x + 128, top=0, bottom=112)
            stage = Stage(level_index=3, direction="right")
            execute_tick(verb, {actor, camera, stage, pit}, gamepad)
            held = gamepad.held
            step = 1 if held & RIGHT else (-1 if held & LEFT else 0)
            if step and last and step != last:
                reversals += 1
            if step:
                last = step
            x += step * 6
            if held & DOWN:
                y += 4
            elif held & UP:
                y -= 4
        return x, y, reversals

    def test_advance_stage_gets_past_a_pit_without_oscillating(self) -> None:
        # The reported failure: "no Pit, a AI falha em WalkToAdvanceStage,
        # fica a alternar direção no Pit". Reproduced on this harness with a
        # 96x40 pit at lane 40..80 -- danger band 32..88, lane midpoint 57,
        # inside it -- the actor stopped dead at the pit's edge and
        # alternated UP/DOWN between y=56 and y=60 forever, X frozen at 394,
        # never advancing.
        pit = Pit(world_x=400, lane_y=40, width=96, height=40)

        x, _, reversals = self._sim(pit, start_y=60)

        self.assertEqual(reversals, 0, "reversed direction at the pit")
        self.assertGreater(x, pit.world_x + pit.width, "never got past the pit")

    def test_escape_side_does_not_flip_across_the_lane_midpoint(self) -> None:
        # Straddling the lane midpoint is what used to flip the pick. Both
        # sides of it must choose the same escape direction, since the pit --
        # the only thing the choice should depend on -- is identical.
        pit = Pit(world_x=400, lane_y=40, width=96, height=40)
        camera = CameraRange(left=300, right=560, top=0, bottom=112)
        stage = Stage(level_index=3, direction="right")

        sides = []
        for y in (56, 60):
            gamepad, _ = _gamepad()
            actor = _myself(world_x=394, world_y=y)
            execute_tick(
                WalkToAdvanceStage(actor_slot="P1", direction="right"),
                {actor, camera, stage, pit},
                gamepad,
            )
            sides.append(gamepad.held & (UP | DOWN))

        self.assertEqual(sides[0], sides[1], f"escape side flipped: {sides}")

    def test_takes_the_nearer_way_out_of_the_pits_band(self) -> None:
        # Self-reinforcing, and the shortest escape: an actor near the top of
        # the band leaves upward, one near the bottom leaves downward.
        pit = Pit(world_x=400, lane_y=30, width=96, height=50)
        camera = CameraRange(left=300, right=560, top=0, bottom=112)
        stage = Stage(level_index=3, direction="right")

        masks = {}
        for label, y in (("near top", 30), ("near bottom", 78)):
            gamepad, _ = _gamepad()
            actor = _myself(world_x=394, world_y=y)
            execute_tick(
                WalkToAdvanceStage(actor_slot="P1", direction="right"),
                {actor, camera, stage, pit},
                gamepad,
            )
            masks[label] = gamepad.held

        self.assertTrue(masks["near top"] & UP, masks)
        self.assertTrue(masks["near bottom"] & DOWN, masks)

    def test_never_walks_laterally_into_the_pit_while_still_in_its_band(self) -> None:
        # state_machine_walk_to_advance_stage falls back to the raw lateral
        # direction whenever _movement_mask returns 0 (`or mask`), so a dodge
        # that produces an empty mask does not merely stall -- it commands
        # the actor straight into the pit. Every Y inside the band must
        # therefore yield a non-empty, purely vertical command.
        pit = Pit(world_x=400, lane_y=20, width=96, height=60)
        camera = CameraRange(left=300, right=560, top=0, bottom=112)
        stage = Stage(level_index=3, direction="right")

        for y in range(12, 89, 4):
            gamepad, _ = _gamepad()
            actor = _myself(world_x=394, world_y=y)
            execute_tick(
                WalkToAdvanceStage(actor_slot="P1", direction="right"),
                {actor, camera, stage, pit},
                gamepad,
            )
            held = gamepad.held
            self.assertFalse(
                held & RIGHT,
                f"walked laterally into the pit at y={y} (mask {held})",
            )
            self.assertTrue(held & (UP | DOWN), f"empty command at y={y}")


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


def _swinging_enemy_ahead(world_x: int, world_y: int) -> Enemy:
    """A committed enemy whose swing extends further along the actor's own
    direction of travel -- the shape ``ExecuteWalkToNearEnemyTests``' own
    routing test uses, reused here so the two verb families are held to the
    same obstacle. ``facing_left=False`` projects ``AttackRange.projected``'s
    reach to ``world_x + forward_min .. world_x + forward_max`` (see
    ``attack_ranges.AttackRange.projected``), i.e. onto the ground between
    the enemy and wherever the actor is walking past it to -- not merely the
    enemy's own body, which the old straight line never saw either way."""

    swing = AttackRange(
        shape_id=0x22,
        animation=0,
        forward_min=0,
        forward_max=48,
        lane_min=-8,
        lane_max=8,
        height_min=0,
        height_max=32,
    )
    return replace(
        _enemy(world_x=world_x, world_y=world_y),
        combat_phase=CombatPhase.ATTACKING,
        attack_ranges=(swing,),
        facing_left=False,
    )


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

    def test_routes_around_a_dangerous_enemys_swing_on_the_way_to_the_weapon(
        self,
    ) -> None:
        # The bug this fixes: the old straight-line walk had no enemy
        # awareness at all, so grabbing a weapon could cross straight through
        # a live enemy's active attack band. Put the enemy's swing squarely
        # on the direct line between the actor and the weapon and require
        # the whole trail to stay out of it, the same standard
        # ExecuteWalkToNearEnemyTests already holds the enemy approach to.
        target = _swinging_enemy_ahead(world_x=150, world_y=50)
        band = Rect(150, 50 - 8, 48, 16)
        weapon = Weapon(slot="obj05", world_x=300, world_y=50, weapon_type=0x08)
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")

        trail = _walk(verb, _myself(world_x=0, world_y=50), {target, weapon}, ticks=140)

        crossed = [
            (a.world_x, a.world_y) for a in trail if _body_of(a).overlaps(band)
        ]
        self.assertFalse(crossed, f"walked through the swing at {crossed[:3]}")
        self.assertTrue(
            any(
                abs(weapon.world_x - a.world_x) <= PICKUP_RANGE_X
                and abs(weapon.world_y - a.world_y) <= PICKUP_RANGE_Y
                for a in trail
            ),
            "never got within pickup range of the weapon",
        )


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

    def test_routes_around_a_dangerous_enemys_swing_on_the_way_to_the_pickup(
        self,
    ) -> None:
        # Same obstacle, same standard, for the health-pickup sibling: a
        # slightly longer route around a live swing beats walking through it
        # mid-fight to grab health.
        target = _swinging_enemy_ahead(world_x=150, world_y=50)
        band = Rect(150, 50 - 8, 48, 16)
        food = HealthPickup(
            slot="obj06", world_x=300, world_y=50, pickup_type=0x4B, health_delta=20
        )
        verb = WalkToPickup(actor_slot="P1", target_slot="obj06")

        trail = _walk(verb, _myself(world_x=0, world_y=50), {target, food}, ticks=140)

        crossed = [
            (a.world_x, a.world_y) for a in trail if _body_of(a).overlaps(band)
        ]
        self.assertFalse(crossed, f"walked through the swing at {crossed[:3]}")
        self.assertTrue(
            any(
                abs(food.world_x - a.world_x) <= PICKUP_RANGE_X
                and abs(food.world_y - a.world_y) <= PICKUP_RANGE_Y
                for a in trail
            ),
            "never got within pickup range of the food",
        )


class NoRawMemoryWritesTests(unittest.TestCase):
    """execute.py / loop.py / priority.py must only ever steer the gamepad —
    never touch raw RAM writes."""

    def test_forbidden_symbols_absent_from_source(self) -> None:
        for module in (execute_module, loop_module, priority_module):
            source = inspect.getsource(module)
            self.assertNotIn("write_memory", source)
            self.assertNotIn("write_value", source)


class HitAntonioBoomerangExecuteTests(unittest.TestCase):
    def test_presses_b_toward_the_boomerang(self) -> None:
        actor = _myself(world_x=100, world_y=100, facing_left=False)
        boomerang = Projectile(
            slot="obj10", world_x=130, world_y=100, vel_x=-8.0, vel_z=0.0, type_id=0x96
        )
        client = MagicMock()
        gamepad = VirtualGamepad(
            SharedGamepadState(client), player_index=1
        )
        execute_verb(
            HitAntonioBoomerang(actor_slot="P1", target_slot="obj10"),
            {actor, boomerang},
            gamepad,
        )
        client.press_buttons.assert_called_once_with(
            player1=B | RIGHT, player2=0, frames=4
        )


class DodgeAntonioKickExecuteTests(unittest.TestCase):
    def test_jumps_over_the_kick(self) -> None:
        actor = _myself(world_x=120, world_y=100)
        antonio = Antonio(
            slot="obj09",
            type_id=0x56,
            world_x=160,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            primary_state=2,
        )
        client = MagicMock()
        gamepad = VirtualGamepad(
            SharedGamepadState(client), player_index=1
        )
        execute_verb(
            DodgeAntonioKick(actor_slot="P1", target_slot="obj09"),
            {actor, antonio},
            gamepad,
        )
        client.press_buttons.assert_called_once()
        pressed = client.press_buttons.call_args.kwargs["player1"]
        self.assertTrue(pressed & C)
        self.assertFalse(pressed & (LEFT | RIGHT))

    def test_hops_even_when_overlapping_on_x(self) -> None:
        # JumpAttack's generic fallback punches when overlapping on X.
        # Against Antonio that is the $16EAE kick trigger, and this dodge
        # reuses that handler, so the fallback would turn a dodge into a
        # standing punch. Hop in place instead.
        actor = _myself(world_x=160, world_y=100)
        antonio = Antonio(
            slot="obj09",
            type_id=0x56,
            world_x=160,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            primary_state=2,
        )
        client = MagicMock()
        gamepad = VirtualGamepad(
            SharedGamepadState(client), player_index=1
        )
        execute_verb(
            DodgeAntonioKick(actor_slot="P1", target_slot="obj09"),
            {actor, antonio},
            gamepad,
        )
        client.press_buttons.assert_called_once()
        pressed = client.press_buttons.call_args.kwargs["player1"]
        self.assertTrue(pressed & C)
        self.assertFalse(pressed & B)
        self.assertFalse(pressed & (LEFT | RIGHT))


class DodgeSoutherSlashExecuteTests(unittest.TestCase):
    def _souther(self, **overrides) -> Souther:
        fields = dict(
            slot="obj11",
            type_id=0x55,
            world_x=160,
            world_y=100,
            health=32,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            primary_state=2,
            tactical=2,
        )
        fields.update(overrides)
        return Souther(**fields)

    def _run(self, actor, souther_y=None):
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        lane = actor.world_y if souther_y is None else souther_y
        execute_verb(
            DodgeSoutherSlash(actor_slot="P1", target_slot="obj11"),
            {actor, self._souther(world_y=lane)},
            gamepad,
        )
        return client

    def test_steps_off_the_lane_and_never_jumps(self) -> None:
        # $16234 (souther_counter_jump_attack) punishes the jump-attack action
        # states, so this dodge must never press C -- the exact opposite of
        # DodgeAntonioKick, which delegates to the jump state machine.
        client = self._run(_myself(world_x=120, world_y=40))
        client.press_buttons.assert_not_called()
        held = client.hold_buttons.call_args.kwargs["player1"]
        self.assertTrue(held & (UP | DOWN), f"expected a lane step, got {held:#06x}")
        self.assertFalse(held & C)
        self.assertFalse(held & B)

    def test_side_is_picked_from_southers_own_lane(self) -> None:
        # Self-reinforcing, like _pit_dodge_target_y: the flip point is his
        # lane and the chosen direction always moves further from it, so the
        # pick cannot undo itself while X is frozen. Reading it off the lane
        # midpoint instead reversed 18 times in 40 ticks on the tick harness.
        above = self._run(_myself(world_x=120, world_y=50), souther_y=60)
        self.assertTrue(above.hold_buttons.call_args.kwargs["player1"] & UP)
        below = self._run(_myself(world_x=120, world_y=70), souther_y=60)
        self.assertTrue(below.hold_buttons.call_args.kwargs["player1"] & DOWN)

    def test_clears_the_lane_gate_the_rom_actually_reads(self) -> None:
        # $1C (28px) is the wider of Souther's two lane gates and the one the
        # inference deliberately assumes, so the aim point has to clear it --
        # and clear it by more than the executor's own Y deadband.
        from sor_autoplay.ai.execute import (
            MOVE_DEADBAND_Y,
            SOUTHER_SLASH_LANE_CLEARANCE,
        )

        self.assertGreater(SOUTHER_SLASH_LANE_CLEARANCE, 0x1C + MOVE_DEADBAND_Y)

    def test_a_side_with_no_lane_room_is_not_chosen(self) -> None:
        # An aim point the lane clamp would drag back inside the band is worse
        # than useless: the Y bits go quiet while X stays frozen.
        actor = _myself(world_x=120, world_y=4)
        client = self._run(actor, souther_y=8)
        held = client.hold_buttons.call_args.kwargs["player1"]
        self.assertTrue(held & DOWN, f"expected the roomier side, got {held:#06x}")

    def test_releases_when_the_souther_is_gone(self) -> None:
        actor = _myself(world_x=120, world_y=40)
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        execute_verb(
            DodgeSoutherSlash(actor_slot="P1", target_slot="obj11"),
            {actor},
            gamepad,
        )
        client.press_buttons.assert_not_called()


if __name__ == "__main__":
    unittest.main()
