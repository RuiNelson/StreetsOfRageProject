"""Round 6, the factory floor: its machine housings and its drop presses.

The geometry is round 6's own, from the live trace (``tools/stage_walk_diag.py
--level 6``): the first housing past Bongo's arena runs x 2512..2680 over lanes
0-63, its left edge 8 px further right per 8-lane row, and every press stands
on lane 112. The walker below plays Blaze's walk the way the ROM does -- her
per-update speeds, ``$43AA``'s clamps and ``$3C92``'s wall probe, which undoes
the whole step -- so a stall shows up as a stall.
"""

import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from sor_autoplay.ai import navigation as nav
from sor_autoplay.ai import press as press_model
from sor_autoplay.ai.decide import could_hold_actions
from sor_autoplay.ai.execute import execute_tick
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.kinematics import walk_speeds
from sor_autoplay.ai.pathfind import Rect
from sor_autoplay.hitboxes import Hitbox
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    CameraRange,
    FlipHold,
    Garcia,
    Myself,
    Press,
    Stage,
    Wall,
    WalkToAdvanceStage,
)
from sor_autoplay.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008

BLAZE = 2
ROUND_6 = 5
LANE_MIN, LANE_MAX = 2, 112

# The housing, as hazards.find_collision_barriers reports it: one row each.
HOUSING = tuple(
    Wall(world_x=2512 + 8 * row, lane_y=8 * row, width=2680 - 2512 - 8 * row, height=8)
    for row in range(8)
)
ADVANCE = WalkToAdvanceStage(actor_slot="P1", direction="right")


def _blaze(x: float, y: float) -> Myself:
    return Myself(
        slot="P1",
        player_index=1,
        character_id=BLAZE,
        character_name="Blaze",
        world_x=round(x),
        world_y=round(y),
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )


def _press(*, x: int = 1832, lane: int = 112, state: int = press_model.STATE_ARMED) -> Press:
    return Press(slot="obj06", world_x=x, world_y=lane, world_z=64, state=state)


def _gamepad() -> VirtualGamepad:
    return VirtualGamepad(SharedGamepadState(MagicMock()), player_index=1)


def _probe_hits(walls, x: float, y: float, vx: float) -> bool:
    """``$3C92``: the point 8 px ahead of the origin, on its lane, in a wall cell."""

    probe = x + (8 if vx >= 0 else -8)
    return any(
        w.world_x <= probe < w.world_x + w.width and w.lane_y <= y < w.lane_y + w.height
        for w in walls
    )


# Blaze's body box (+$70) by frame, X relative to her origin, lanes +-8: idle
# facing right and left (controls-and-input.md), and walking (measured live).
BLAZE_IDLE_RIGHT = (2, 12)
BLAZE_IDLE_LEFT = (-12, -2)
BLAZE_WALK = (-5, 5)


def _blaze_box(x: float, y: float, span: tuple[int, int]) -> Hitbox:
    return Hitbox(round(x) + span[0], round(x) + span[1], round(y) - 8, round(y) + 8, -48, 0)


class _Walker:
    """Blaze's walk, one update per tick: ``$2D00``'s speeds, the clamps, the probe.

    With ``boxes`` the actor also carries the ROM's body box for the frame --
    the walk's, or the idle one for the way she faces -- and that box is the
    one the press hits.
    """

    def __init__(self, x: float, y: float, *, walls, camera: CameraRange, boxes: bool = False) -> None:
        self.x, self.y = float(x), float(y)
        self.walls = walls
        self.camera = camera
        self.refused = 0
        self.boxes = boxes
        self.facing_left = False
        self.walking = False

    @property
    def span(self) -> tuple[int, int]:
        if self.walking:
            return BLAZE_WALK
        return BLAZE_IDLE_LEFT if self.facing_left else BLAZE_IDLE_RIGHT

    @property
    def actor(self) -> Myself:
        actor = _blaze(self.x, self.y)
        if not self.boxes:
            return actor
        return replace(actor, facing_left=self.facing_left, hitbox=_blaze_box(self.x, self.y, self.span))

    @property
    def body(self) -> Rect:
        return nav.body_rect(self.actor)

    def step(self, mask: int) -> None:
        straight_x, diagonal_x, diagonal_y, straight_y = walk_speeds(BLAZE)
        step_x = 1 if mask & RIGHT else -1 if mask & LEFT else 0
        step_y = 1 if mask & DOWN else -1 if mask & UP else 0
        if step_x:
            self.facing_left = step_x < 0
        self.walking = bool(step_x or step_y)
        vx = step_x * (diagonal_x if step_y else straight_x)
        vy = step_y * (diagonal_y if step_x else straight_y)
        x = min(max(self.x + vx, self.camera.left), self.camera.right)
        y = min(max(self.y + vy, LANE_MIN), LANE_MAX)
        if (vx or vy) and _probe_hits(self.walls, x, y, vx):
            self.refused += 1
            return
        self.x, self.y = x, y


def _body(x: float, y: float) -> Rect:
    return nav.body_rect(_blaze(x, y))


class HousingTests(unittest.TestCase):
    """The 70 s stall at X 2557: a walk on lanes 56-63 into the housing's last row."""

    CAMERA = CameraRange(left=2400, right=2760, top=0, bottom=112)

    def _walk(self, *, ticks: int, walls_seen: bool) -> _Walker:
        walker = _Walker(2530, 60, walls=HOUSING, camera=self.CAMERA)
        gamepad = _gamepad()
        for _ in range(ticks):
            context = {walker.actor, self.CAMERA, Stage(level_index=ROUND_6, direction="right")}
            if walls_seen:
                context |= set(HOUSING)
            execute_tick(ADVANCE, context, gamepad)
            walker.step(gamepad.held)
        return walker

    def test_blind_to_the_housing_the_walk_stalls_where_the_live_run_did(self) -> None:
        # The router planned straight RIGHT and $3C92 undid every step.
        walker = self._walk(ticks=120, walls_seen=False)

        self.assertTrue(2550 <= walker.x < 2560, walker.x)
        self.assertGreater(walker.refused, 100)

    def test_with_the_housing_it_goes_under_it(self) -> None:
        walker = self._walk(ticks=120, walls_seen=True)

        self.assertGreater(walker.x, 2700)
        self.assertGreaterEqual(walker.y, 64)

    def test_wall_obstacles_keep_the_origin_off_the_probe(self) -> None:
        # One row (lanes 56-63, cells from 2568): walking right the probe
        # meets it from x 2560, so no body position there may be open.
        actor = _blaze(2540, 60)
        body, origin = nav.actor_footprint(actor)
        context = {actor, HOUSING[7]}
        obstacles = nav.wall_obstacles(context, body=body, origin=origin)

        for x in (2560, 2600, 2687):
            self.assertTrue(
                any(_body(x, 60).overlaps(o) for o in obstacles), f"open at x={x}"
            )
        self.assertFalse(any(_body(2540, 60).overlaps(o) for o in obstacles))
        self.assertFalse(any(_body(2600, 76).overlaps(o) for o in obstacles))


class PressModelTests(unittest.TestCase):
    def test_the_trigger_window(self) -> None:
        press = _press(x=1832)

        self.assertFalse(press_model.in_trigger_window(press, 1784))
        self.assertTrue(press_model.in_trigger_window(press, 1785))
        self.assertTrue(press_model.in_trigger_window(press, 1928))
        self.assertFalse(press_model.in_trigger_window(press, 1929))

    def test_committed_from_the_trigger_until_it_lands(self) -> None:
        self.assertFalse(press_model.is_committed(_press(), [1700]))
        self.assertTrue(press_model.is_committed(_press(), [1700, 1800]))
        for state in (press_model.STATE_SHAKING, press_model.STATE_FALLING):
            self.assertTrue(press_model.is_committed(_press(state=state), []))
        for state in (4, 5, 6, 7, 8):
            self.assertFalse(press_model.is_committed(_press(state=state), [1832]))

    def test_both_live_hits_were_inside_the_zone(self) -> None:
        # tools/stage_walk_diag.py --level 6: hit at x 1811 lane 71 by the
        # press at 1832, and at x 4503 lane 87 by the one at 4520 -- 41 and 25
        # lanes above them, where the old lane test never looked.
        for (px, x, y) in ((1832, 1811, 71), (4520, 4503, 87)):
            zones = press_model.drop_zones(_press(x=px))
            self.assertTrue(any(_body(x, y).overlaps(z) for z in zones), (px, x, y))

    def test_the_street_above_its_reach_is_free(self) -> None:
        zones = press_model.drop_zones(_press(x=1832))

        self.assertFalse(any(_body(1811, 40).overlaps(z) for z in zones))
        self.assertFalse(any(_body(1760, 80).overlaps(z) for z in zones))


class PressObstacleTests(unittest.TestCase):
    def test_a_wall_only_while_committed(self) -> None:
        actor = _blaze(1700, 72)
        body, origin = nav.actor_footprint(actor)

        armed = nav.solid_obstacles({actor, _press()}, body=body, origin=origin)
        shaking = nav.solid_obstacles(
            {actor, _press(state=press_model.STATE_SHAKING)}, body=body, origin=origin
        )

        self.assertEqual(armed, [])
        self.assertEqual(len(shaking), 2)

    def test_the_press_is_no_projectile(self) -> None:
        from sor_autoplay.ai.decide import could_projectile_sidestep

        self.assertEqual(
            could_projectile_sidestep({_blaze(1811, 71), _press(state=press_model.STATE_FALLING)}),
            set(),
        )


class PressEscapeTests(unittest.TestCase):
    CAMERA = CameraRange(left=1600, right=1990, top=0, bottom=112)

    def test_backs_out_of_the_zone_it_just_walked_into(self) -> None:
        # The walk set it off from $EA's left edge: straight back out is 4
        # updates; up and out of its lanes would take 12.
        walker = _Walker(1787, 72, walls=(), camera=self.CAMERA)
        press = _press(state=press_model.STATE_SHAKING)
        gamepad = _gamepad()
        gamepad.steer_x(1)
        gamepad.steer_x(1)
        gamepad.steer_x(1)  # walking right when it went off

        for _ in range(10):
            execute_tick(
                ADVANCE,
                {walker.actor, press, self.CAMERA, Stage(level_index=ROUND_6, direction="right")},
                gamepad,
            )
            self.assertFalse(gamepad.held & RIGHT, "walked on into the zone")
            walker.step(gamepad.held)

        zones = press_model.drop_zones(press)
        self.assertFalse(any(_body(walker.x, walker.y).overlaps(z) for z in zones))

    def test_the_escape_does_not_walk_into_a_wall(self) -> None:
        # Inside $F4 with the way left walled off: out by the lane instead.
        press = _press(x=1000)
        zones = press_model.drop_zones(press)
        body = _body(1030, 108)

        def constrain(x, y, vx):
            if x < 1025:
                return None
            return x, min(max(y, LANE_MIN), LANE_MAX)

        step = press_model.escape_step(
            body, (1030, 108), zones, speeds=walk_speeds(BLAZE), constrain=constrain
        )

        self.assertEqual(step, (0, -1))


class LandingTests(unittest.TestCase):
    """Moves that set the actor down somewhere and keep it there."""

    CAMERA = CameraRange(left=4300, right=4600, top=0, bottom=112)

    def test_no_jump_onto_a_live_press(self) -> None:
        actor = _blaze(4440, 89)

        for state in (press_model.STATE_ARMED, press_model.STATE_FALLING):
            context = {actor, self.CAMERA, _press(x=4520, state=state)}
            self.assertFalse(nav.jump_landing_is_safe(context, actor, 4500), state)
        down = {actor, self.CAMERA, _press(x=4520, state=5)}
        self.assertTrue(nav.jump_landing_is_safe(down, actor, 4500))

    def test_no_crossover_under_a_live_press(self) -> None:
        # The live case: knee, knee, then the crossover carried the hold from
        # x 4452 over the body at 4480 to 4508, under the press at 4520 -- the
        # landing set it off, and the hold kept the actor there.
        holder = replace(_blaze(4452, 89), action_state=0x60, held_enemy_slot="obj05")
        held = Garcia(
            slot="obj05",
            type_id=0x20,
            world_x=4480,
            world_y=89,
            health=20,
            combat_phase=CombatPhase.GRABBED,
            targets_player=1,
            facing_left=True,
        )

        open_street = could_hold_actions(generate_inference_tokens({holder, held, self.CAMERA}))
        under_a_press = could_hold_actions(
            generate_inference_tokens({holder, held, self.CAMERA, _press(x=4520)})
        )

        self.assertIn(FlipHold, {type(v) for v in open_street})
        self.assertNotIn(FlipHold, {type(v) for v in under_a_press})
        self.assertIn(AttackHeldEnemy, {type(v) for v in under_a_press})


class PressWalkTests(unittest.TestCase):
    """The walk past an armed press, with the press playing its own states."""

    SHAKE_UPDATES = 11
    FALL_UPDATES = 16
    # z > 112 from the 11th update of the fall: the box reaches a standing body.
    HURTS_FROM = 11

    def _run(
        self,
        *,
        walls,
        ticks: int = 260,
        boxes: bool = False,
        press_x: int = 1832,
        start: tuple[float, float] = (1700, 72),
        camera: CameraRange = CameraRange(left=1600, right=1990, top=0, bottom=112),
        facing_left: bool = False,
        since_trigger: int | None = None,
    ):
        walker = _Walker(*start, walls=walls, camera=camera, boxes=boxes)
        walker.facing_left = facing_left
        press = _press(x=press_x)
        if since_trigger is not None:
            state = press_model.STATE_SHAKING if since_trigger < self.SHAKE_UPDATES else press_model.STATE_FALLING
            press = replace(press, state=state)
        gamepad = _gamepad()
        hits = []
        for tick in range(ticks):
            if press.state == press_model.STATE_ARMED and press_model.in_trigger_window(press, walker.x):
                press, since_trigger = replace(press, state=press_model.STATE_SHAKING), 0
            elif since_trigger is not None:
                since_trigger += 1
                if since_trigger == self.SHAKE_UPDATES:
                    press = replace(press, state=press_model.STATE_FALLING)
                elif since_trigger == self.SHAKE_UPDATES + self.FALL_UPDATES:
                    press = replace(press, state=4)
            falling_for = None if since_trigger is None else since_trigger - self.SHAKE_UPDATES
            if press.state == press_model.STATE_FALLING and falling_for >= self.HURTS_FROM:
                boxes = [
                    Rect(press.world_x + x0, press.world_y + y0, x1 - x0, y1 - y0)
                    for x0, x1, y0, y1 in press_model.DROP_BOXES
                ]
                # The ROM's test is inclusive ($AB88: bgt / blt).
                body = walker.body
                if any(
                    body.left <= b.right and body.right >= b.left and body.top <= b.bottom and body.bottom >= b.top
                    for b in boxes
                ):
                    hits.append((tick, walker.x, walker.y))
            context = {
                walker.actor,
                press,
                camera,
                Stage(level_index=ROUND_6, direction="right"),
                *walls,
            }
            execute_tick(ADVANCE, context, gamepad)
            walker.step(gamepad.held)
        return walker, since_trigger, hits

    def test_open_street(self) -> None:
        walker, since_trigger, hits = self._run(walls=())

        self.assertIsNotNone(since_trigger, "never set the press off")
        self.assertEqual(hits, [])
        self.assertGreater(walker.x, 1900)

    def test_between_the_housing_and_the_press(self) -> None:
        # Round 6's first press stands under the first housing's reach: with
        # lanes 0-63 walled and $EA over lanes 61-103, the only way past a
        # committed press is to wait for it to land.
        housing = tuple(
            Wall(world_x=1680 + 8 * row, lane_y=8 * row, width=240 - 8 * row, height=8)
            for row in range(8)
        )

        walker, since_trigger, hits = self._run(walls=housing)

        self.assertIsNotNone(since_trigger, "never set the press off")
        self.assertEqual(hits, [])
        self.assertGreater(walker.x, 1900)

    def test_a_turn_does_not_carry_the_body_back_in(self) -> None:
        # The live hits (round 6, swept): the walk set the press at 2632 off
        # on lane 84, the escape backed out left, and the router -- planning
        # with the idle box facing left, 9 px clear -- sent her RIGHT. Turning
        # moved the box 7-10 px right, into $EA, as it came down: hit at x
        # 2574. The same with the press at 3688 and 4520.
        for walls in ((), HOUSING):
            with self.subTest(housing=bool(walls)):
                walker, since_trigger, hits = self._run(
                    walls=walls,
                    boxes=True,
                    press_x=2632,
                    start=(2500, 84),
                    camera=CameraRange(left=2400, right=2752, top=0, bottom=112),
                )

                self.assertIsNotNone(since_trigger, "never set the press off")
                self.assertEqual(hits, [])
                self.assertGreater(walker.x, 2700)

    def test_standing_where_the_escape_left_her(self) -> None:
        # The live moment itself: backed out to x 2573, idle facing left --
        # her box 2561..2571, clear of $EA's zone from 2580 -- as the press
        # at 2632 starts to fall. Facing right her box would reach 2585.
        for walls in ((), HOUSING):
            with self.subTest(housing=bool(walls)):
                walker, _, hits = self._run(
                    walls=walls,
                    boxes=True,
                    press_x=2632,
                    start=(2573, 84),
                    camera=CameraRange(left=2400, right=2752, top=0, bottom=112),
                    facing_left=True,
                    since_trigger=self.SHAKE_UPDATES,
                )

                self.assertEqual(hits, [])
                self.assertGreater(walker.x, 2700)

    def test_both_scenarios_with_the_rom_boxes(self) -> None:
        housing = tuple(
            Wall(world_x=1680 + 8 * row, lane_y=8 * row, width=240 - 8 * row, height=8)
            for row in range(8)
        )
        for walls in ((), housing):
            with self.subTest(housing=bool(walls)):
                walker, since_trigger, hits = self._run(walls=walls, boxes=True)

                self.assertIsNotNone(since_trigger, "never set the press off")
                self.assertEqual(hits, [])
                self.assertGreater(walker.x, 1900)


class PressEnvelopeTests(unittest.TestCase):
    """The zone is tested against every box a turn or a step could swap in."""

    def test_the_envelope_covers_both_facings(self) -> None:
        for span in (BLAZE_IDLE_LEFT, BLAZE_IDLE_RIGHT, BLAZE_WALK):
            body = nav.body_rect(replace(_blaze(2573, 84), hitbox=_blaze_box(2573, 84, span)))
            envelope = press_model.standing_envelope(body, (2573, 84), BLAZE)
            self.assertEqual((envelope.left, envelope.right), (2561, 2585), span)
            self.assertEqual((envelope.top, envelope.bottom), (76, 92))

    def test_the_router_sees_the_envelope(self) -> None:
        # Idle facing left at 2573: the box (2561..2571) is clear of $EA's
        # zone (from 2580), the body facing right (2575..2585) is not.
        actor = replace(_blaze(2573, 84), facing_left=True, hitbox=_blaze_box(2573, 84, BLAZE_IDLE_LEFT))
        press = _press(x=2632, state=press_model.STATE_FALLING)
        body, origin = nav.actor_footprint(actor)
        zones = press_model.drop_zones(press)

        self.assertFalse(any(body.overlaps(z) for z in zones))
        grown = nav.press_obstacles({actor, press}, body=body, origin=origin)
        self.assertTrue(any(body.overlaps(z) for z in grown))
        # Grown only by what the envelope adds: once the origin is 12 px
        # clear of the zone (x 2568 and left), so is the body.
        self.assertTrue(any(body.moved_by(-4, 0).overlaps(z) for z in grown))
        self.assertFalse(any(body.moved_by(-5, 0).overlaps(z) for z in grown))

    def test_the_point_form_for_the_street_plan(self) -> None:
        # The live case: the press at 4520 re-armed with the actor in its
        # window, and the street plan stepped DOWN-RIGHT to x 4576 lane 96 --
        # origin above $F4's zone (from lane 101), body (to 104) inside it.
        actor = _blaze(4576, 96)
        press = _press(x=4520, state=press_model.STATE_FALLING)
        points = nav.solid_obstacles({actor, press})

        def inside(x, y):
            return any(r.left < x < r.right and r.top < y < r.bottom for r in points)

        self.assertTrue(inside(4576, 96))
        self.assertTrue(inside(4591, 94))  # the envelope (from 4579) still reaches 4580
        self.assertFalse(inside(4593, 94))
        self.assertFalse(inside(4576, 92))  # body to lane 100: clear

    def test_no_step_right_after_backing_out(self) -> None:
        # The live tick after the escape: idle facing left at (2573, 86), her
        # box 9 px clear of $EA's zone, while the press falls. RIGHT is the
        # turn that puts it inside -- what the router chose, live.
        camera = CameraRange(left=2400, right=2752, top=0, bottom=112)
        actor = replace(_blaze(2573, 86), facing_left=True, hitbox=_blaze_box(2573, 86, BLAZE_IDLE_LEFT))
        press = _press(x=2632, state=press_model.STATE_FALLING)
        gamepad = _gamepad()

        for _ in range(8):
            execute_tick(
                ADVANCE,
                {actor, press, camera, Stage(level_index=ROUND_6, direction="right"), *HOUSING},
                gamepad,
            )
            self.assertFalse(gamepad.held & RIGHT, "turned back into the zone")

    def test_the_escape_is_held_at_once(self) -> None:
        # Walking right when the walk set it off: the escape reverses on the
        # first tick instead of ramping the axis through the centre.
        camera = CameraRange(left=2400, right=2752, top=0, bottom=112)
        actor = replace(_blaze(2586, 84), hitbox=_blaze_box(2586, 84, BLAZE_WALK))
        press = _press(x=2632, state=press_model.STATE_SHAKING)
        gamepad = _gamepad()
        for _ in range(3):
            gamepad.steer_x(1)

        execute_tick(ADVANCE, {actor, press, camera, Stage(level_index=ROUND_6, direction="right")}, gamepad)

        self.assertTrue(gamepad.held & LEFT)
        self.assertFalse(gamepad.held & RIGHT)

    def test_no_verb_walks_into_a_committed_zone(self) -> None:
        # The live case: the press at 4520 re-armed with the actor in its
        # window, the street plan held DOWN-RIGHT at x 4576 lane 93 (camera
        # edge), the escape held UP the tick after, and so on until it landed.
        # The pad the verb drives keeps the step that stays clear.
        import sor_autoplay.ai.execute as execute_module

        actor = _blaze(4576, 93)
        press = _press(x=4520, state=press_model.STATE_FALLING)
        camera = CameraRange(left=4288, right=4576, top=0, bottom=112)
        held = {}

        def drive(verb, context, gamepad):
            for mask in (DOWN | RIGHT, DOWN, RIGHT | 0x0010):
                gamepad.hold(mask)
                held[mask] = gamepad.held

        real = execute_module.execute_verb
        execute_module.execute_verb = drive
        try:
            execute_tick(ADVANCE, {actor, press, camera, Stage(level_index=ROUND_6, direction="right")}, _gamepad())
        finally:
            execute_module.execute_verb = real

        self.assertEqual(held[DOWN | RIGHT], RIGHT)
        self.assertEqual(held[DOWN], 0)
        self.assertEqual(held[RIGHT | 0x0010], RIGHT | 0x0010)

    def test_a_landing_in_reach_counts_the_turn(self) -> None:
        # A landing whose box, as it is, ends 1 px short of $EA's zone but
        # whose origin a turn would put inside it.
        press = _press(x=2632)
        body = Rect(2569, 76, 10, 16)  # idle facing left at 2581
        self.assertFalse(press_model.lands_in_reach({press}, body))
        self.assertTrue(press_model.lands_in_reach({press}, body, origin=(2581, 84), character_id=BLAZE))


if __name__ == "__main__":
    unittest.main()
