"""Onihime/Yasha ROM commit gates and the denial doctrine built on them.

Every threshold here is a literal ROM constant (`$159F8`, `$15A64`, `$15BE8`,
`$15C72`); a failure means the agent is standing where the twins are allowed to
commit.
"""

from __future__ import annotations

import dataclasses
import unittest

from sor_autoplay.agent import twins as twins_ai
from sor_autoplay.agent.bosses import tactical_move
from sor_autoplay.phases import CombatPhase
from sor_autoplay.world_map import MapEntity


def _player(
    *,
    world_x: int = 100,
    world_y: int = 60,
    action_state: int = 0x02,
) -> MapEntity:
    return MapEntity(
        kind="player",
        family="Player",
        symbol="P",
        color="#fff",
        label="P1",
        type_id=1,
        world_x=world_x,
        world_y=world_y,
        world_z=0xA0,
        map_x=float(world_x),
        map_y=float(world_y),
        health=0x50,
        slot="P1",
        action_state=action_state,
    )


def _twin(
    *,
    world_x: int,
    world_y: int,
    slot: str,
    mode_flags: int = 1,
    pair_role: int = 1,
    health: int = 0x20,
    phase: CombatPhase = CombatPhase.NORMAL,
) -> MapEntity:
    return MapEntity(
        kind="boss",
        family="Onihime/Yasha",
        symbol="B",
        color="#f00",
        label=slot,
        type_id=0x58,
        world_x=world_x,
        world_y=world_y,
        world_z=0xA0,
        map_x=float(world_x),
        map_y=float(world_y),
        health=health,
        slot=slot,
        action_state=0x01,
        mode_flags=mode_flags,
        pair_role=pair_role,
        combat_phase=phase,
    )


class GateModelTests(unittest.TestCase):
    """`$159F8` / `$15A64` / `$15BE8` / `$15C72` windows."""

    def test_throw_band_is_the_half_step_diagonal(self) -> None:
        # $159F8 requires lane +$52 in [$10,$20): coplanar and wide are safe.
        self.assertFalse(twins_ai.in_throw_band(0))
        self.assertFalse(twins_ai.in_throw_band(15))
        self.assertTrue(twins_ai.in_throw_band(16))
        self.assertTrue(twins_ai.in_throw_band(31))
        self.assertFalse(twins_ai.in_throw_band(32))

    def test_sidestep_clearance_clears_the_band(self) -> None:
        """A 28 px sidestep used to park the player inside the trigger."""

        self.assertTrue(twins_ai.in_throw_band(28.0))
        self.assertFalse(twins_ai.in_throw_band(twins_ai.LANE_SAFE_CLEARANCE))

    def test_throw_commit_needs_band_lane_and_close_x(self) -> None:
        me = _player(world_x=100, world_y=60)
        banded = twins_ai.assess(me, _twin(world_x=180, world_y=80, slot="B0"))
        self.assertTrue(banded.can_throw_commit)

        coplanar = twins_ai.assess(me, _twin(world_x=180, world_y=62, slot="B0"))
        self.assertFalse(coplanar.can_throw_commit)

        wide = twins_ai.assess(me, _twin(world_x=180, world_y=100, slot="B0"))
        self.assertFalse(wide.can_throw_commit)

        far = twins_ai.assess(me, _twin(world_x=220, world_y=80, slot="B0"))
        self.assertFalse(far.can_throw_commit)

    def test_jump_attack_is_distance_only(self) -> None:
        me = _player(world_x=100, world_y=60)
        near = twins_ai.assess(me, _twin(world_x=190, world_y=60, slot="B0"))
        self.assertTrue(near.can_jump_attack)
        far = twins_ai.assess(me, _twin(world_x=200, world_y=60, slot="B0"))
        self.assertFalse(far.can_jump_attack)

    def test_leap_grab_needs_a_staggered_player(self) -> None:
        grabber = _twin(world_x=200, world_y=60, slot="B1", mode_flags=2, pair_role=2)
        healthy = twins_ai.assess(_player(), grabber)
        self.assertFalse(healthy.can_leap_grab)
        # Player action $5A-$5F is the hurt/knockdown family ($179F8 → +$77=1).
        hurt = twins_ai.assess(_player(action_state=0x5A), grabber)
        self.assertTrue(hurt.can_leap_grab)

    def test_committed_or_recovering_twin_has_no_open_gate(self) -> None:
        me = _player()
        recovering = _twin(
            world_x=140, world_y=60, slot="B0", phase=CombatPhase.RECOVERY
        )
        self.assertFalse(twins_ai.assess(me, recovering).can_act)

    def test_grab_mode_reads_mode_flags_then_role_seed(self) -> None:
        self.assertTrue(
            twins_ai.is_grab_mode(
                _twin(world_x=0, world_y=0, slot="B0", mode_flags=2)
            )
        )
        self.assertFalse(
            twins_ai.is_grab_mode(
                _twin(world_x=0, world_y=0, slot="B0", mode_flags=1)
            )
        )
        # +$7B unreadable → fall back to the +$5D role seed.
        self.assertTrue(
            twins_ai.is_grab_mode(
                _twin(world_x=0, world_y=0, slot="B0", mode_flags=0, pair_role=2)
            )
        )


def _twin_arc(
    *,
    world_x: int,
    world_z: int,
    vel_z: float,
    vel_x: float = 1.0,
    ground_z: int = 160,
    world_y: int = 64,
    slot: str = "B0",
) -> MapEntity:
    """A twin mid jump-attack, with the ROM's own live velocity fields."""

    base = _twin(world_x=world_x, world_y=world_y, slot=slot)
    return dataclasses.replace(
        base,
        world_z=world_z,
        ground_z=ground_z,
        vel_x=vel_x,
        vel_z=vel_z,
        tactical=twins_ai.JUMP_ATTACK_TACTICAL,
    )


class ArcPredictionTests(unittest.TestCase):
    """`$15ABA` is ballistic and cannot steer, so the landing is computable.

    Reference sample captured live at the Round-5 encounter (phase timer, z,
    x, vz), ground plane 160, vx +1.0 throughout:

        timer  4  z 152  x 5126  vz -7.250
        timer  5  z 146  x 5130  vz -6.500
        ...      (vz steps +0.75 per tick)
        apex   ~z 121 around timer 13-14
    """

    def test_landing_is_predicted_from_the_launch_frame(self) -> None:
        twin = _twin_arc(world_x=5126, world_z=152, vel_z=-7.25)
        forecast = twins_ai.predict_landing(twin)
        self.assertIsNotNone(forecast)
        # -7.25 with +0.75/tick returns to the plane after ~19 more ticks.
        self.assertGreaterEqual(forecast.ticks, 16)
        self.assertLessEqual(forecast.ticks, 22)
        # Travelling right at 4 px/tick, it lands well ahead of where it is.
        self.assertGreater(forecast.x, float(twin.world_x) + 60)

    def test_descending_body_lands_soon_and_close(self) -> None:
        # Past apex, most of the drop already spent.
        twin = _twin_arc(world_x=5200, world_z=150, vel_z=+3.0)
        forecast = twins_ai.predict_landing(twin)
        self.assertIsNotNone(forecast)
        self.assertLessEqual(forecast.ticks, 4)

    def test_grounded_body_has_no_forecast(self) -> None:
        twin = _twin_arc(world_x=5200, world_z=160, vel_z=0.0)
        self.assertIsNone(twins_ai.predict_landing(twin))

    def test_intercept_stands_under_the_landing(self) -> None:
        from sor_autoplay.agent.characters import PROFILES

        me = _player(world_x=5100, world_y=64)
        twin = _twin_arc(world_x=5126, world_z=152, vel_z=-7.25)
        forecast = twins_ai.predict_landing(twin)
        goal_x, goal_y = twins_ai.intercept_point(me, forecast, PROFILES[0])
        # Stand *under* the landing: the back attack's box is body-centred, so
        # spacing off at punch range is the wrong geometry for it.
        self.assertAlmostEqual(goal_x, forecast.x, delta=1.0)
        self.assertAlmostEqual(goal_y, float(forecast.twin.world_y), delta=1.0)


class DoctrineTests(unittest.TestCase):
    def test_focus_prefers_lower_hp_then_the_nearer_body(self) -> None:
        me = _player()
        approach = _twin(world_x=160, world_y=60, slot="B0", mode_flags=1)
        grabber = _twin(
            world_x=200, world_y=60, slot="B1", mode_flags=2, pair_role=2
        )
        # Equal HP: take the body we can actually reach. Preferring the grab
        # twin here measured worse — the seat walked past a twin standing in
        # punch range to chase a distant focus and landed nothing.
        self.assertEqual(
            twins_ai.scene(me, (me, approach, grabber)).focus.slot, "B0"
        )
        # A wounded body always outranks distance.
        wounded = _twin(world_x=260, world_y=60, slot="B1", health=0x08, mode_flags=2)
        healthy = _twin(world_x=140, world_y=60, slot="B0", mode_flags=1)
        self.assertEqual(
            twins_ai.scene(me, (me, healthy, wounded)).focus.slot, "B1"
        )
        # Grab mode still breaks a tie between equally close, equal-HP bodies.
        left = _twin(world_x=40, world_y=60, slot="B0", mode_flags=1)
        right = _twin(world_x=160, world_y=60, slot="B1", mode_flags=2, pair_role=2)
        self.assertEqual(
            twins_ai.scene(_player(world_x=100), (me, left, right)).focus.slot, "B1"
        )

    def test_safe_lane_clears_the_band_for_every_live_twin(self) -> None:
        me = _player(world_x=100, world_y=60)
        a = _twin(world_x=150, world_y=80, slot="B0")
        b = _twin(world_x=150, world_y=44, slot="B1")
        lane = twins_ai.safe_lane(me, (me, a, b), level_index=4)
        self.assertFalse(twins_ai.in_throw_band(lane - 80))
        self.assertFalse(twins_ai.in_throw_band(lane - 44))

    def test_scene_retreats_from_an_armed_leap_while_staggered(self) -> None:
        me = _player(world_x=250, world_y=60, action_state=0x5A)
        grabber = _twin(
            world_x=330, world_y=60, slot="B1", mode_flags=2, pair_role=2
        )
        doctrine = twins_ai.scene(me, (me, grabber))
        self.assertIsNotNone(doctrine.retreat_from)
        goal_x, _ = twins_ai.retreat_goal(
            me, grabber, level_index=4, entities=(me, grabber)
        )
        # Retreat away from the body, past the $90 leap window.
        self.assertLess(goal_x, me.world_x)
        self.assertGreaterEqual(abs(goal_x - grabber.world_x), twins_ai.LEAP_GRAB_X)

    def test_cornered_retreat_stays_inside_the_walk_band(self) -> None:
        """$43AA clamps the player: never latch a goal outside the arena."""

        me = _player(world_x=60, world_y=60, action_state=0x5A)
        grabber = _twin(
            world_x=140, world_y=60, slot="B1", mode_flags=2, pair_role=2
        )
        goal_x, _ = twins_ai.retreat_goal(
            me, grabber, level_index=4, entities=(me, grabber)
        )
        self.assertLess(goal_x, me.world_x)
        goal_map_x = float(me.map_x) + (goal_x - float(me.world_x))
        self.assertGreaterEqual(goal_map_x, twins_ai.WALK_BAND_MIN)

    def test_scene_baits_the_grab_twin_instead_of_walking_in(self) -> None:
        me = _player(world_x=100, world_y=60)
        grabber = _twin(
            world_x=180, world_y=60, slot="B1", mode_flags=2, pair_role=2
        )
        # dx = 80 is inside $15C72's $40-$70 jump-in window.
        self.assertIsNotNone(twins_ai.scene(me, (me, grabber)).hold_for_walk_in)
        # A punishable body is closed on instead — free damage outranks bait.
        stunned = _twin(
            world_x=180,
            world_y=60,
            slot="B1",
            mode_flags=2,
            pair_role=2,
            phase=CombatPhase.RECOVERY,
        )
        self.assertIsNone(twins_ai.scene(me, (me, stunned)).hold_for_walk_in)

    def test_approach_twin_is_closed_on_normally(self) -> None:
        """Only the grab path punishes a walk-in; the approach twin does not."""

        me = _player(world_x=100, world_y=60)
        approach = _twin(world_x=180, world_y=60, slot="B0", mode_flags=1)
        self.assertIsNone(twins_ai.scene(me, (me, approach)).hold_for_walk_in)


class BossTacticIntegrationTests(unittest.TestCase):
    def test_standing_in_the_throw_band_forces_a_mandatory_exit(self) -> None:
        me = _player(world_x=100, world_y=60)
        focus = _twin(world_x=160, world_y=80, slot="B0")
        move = tactical_move(me, focus, (me, focus), level_index=4)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertTrue(move.mandatory)
        self.assertIn("throw band", move.note)
        self.assertFalse(twins_ai.in_throw_band(move.goal_y - 80))

    def test_commit_evasion_never_lands_inside_the_band(self) -> None:
        me = _player(world_x=100, world_y=60)
        committed = _twin(
            world_x=140, world_y=60, slot="B0", phase=CombatPhase.ATTACKING
        )
        move = tactical_move(me, committed, (me, committed), level_index=4)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertFalse(twins_ai.in_throw_band(move.goal_y - 60))

    def test_coplanar_idle_pair_still_leaves_combat_free(self) -> None:
        """Coplanar is safe: no gate is armed, so movement must not intervene."""

        me = _player(world_x=100, world_y=60)
        a = _twin(world_x=160, world_y=60, slot="B0")
        b = _twin(world_x=210, world_y=58, slot="B1")
        self.assertIsNone(tactical_move(me, a, (me, a, b), level_index=4))


if __name__ == "__main__":
    unittest.main()


class PolicyEngagementTests(unittest.TestCase):
    """The seat must actually press B on a twin that is standing in range.

    Live Round-5 handoffs produced 370 actionable decisions with **zero**
    ground-attack attempts, so geometry alone is not enough evidence — this
    drives the real policy end to end.
    """

    def _decide(self, entities, *, special: bool = False):
        from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
        from tests.test_agent_combat import PolicyIntegrationTests

        helper = PolicyIntegrationTests('run')
        snap = helper._snap(entities)
        return decide_actions(
            snap,
            AgentConfig(p1_enabled=True, allow_police_special=special),
            AgentState(),
        )

    ATTACK = 0x20  # Buttons.B

    def test_punches_a_coplanar_twin_inside_strike_range(self) -> None:
        me = _player(world_x=100, world_y=64)
        focus = _twin(world_x=140, world_y=64, slot="B0", mode_flags=1)
        partner = _twin(world_x=300, world_y=64, slot="B1", mode_flags=2, pair_role=2)
        decision = self._decide((me, focus, partner))
        self.assertTrue(decision.p1_mask & self.ATTACK, decision.p1_note)
        self.assertIn("punch", decision.p1_note)

    def test_never_swings_from_inside_the_measured_dead_zone(self) -> None:
        """Live sweep: no damage under 28 px, clean hits 28-52, none past 56.

        The twins end every jump arc on top of the player, so a policy that
        swings at `dx < 28` spends the whole fight whiffing — which is exactly
        what hundreds of live attack decisions with zero damage looked like.
        """

        me = _player(world_x=100, world_y=64)
        crowding = _twin(world_x=112, world_y=64, slot="B0", mode_flags=1)
        partner = _twin(world_x=320, world_y=64, slot="B1", mode_flags=2, pair_role=2)
        decision = self._decide((me, crowding, partner))
        self.assertFalse(decision.p1_mask & self.ATTACK, decision.p1_note)
        self.assertIn("reset", decision.p1_note)

    def test_enemy_hold_actions_own_the_seat_over_the_twin_skill(self) -> None:
        """`$78`-`$7F` must reach the enemy-grab escape skill, not twin combat.

        A live twin trace appeared to show the twin skill swinging while the
        player was held in `$79`. It was a trace artifact — every state column
        is sampled *after* the input, so the row paired a note decided while
        free with the grab that landed during those frames. The partition is
        correct, and this pins it so the question is not reopened.
        """

        from types import SimpleNamespace

        from sor_autoplay.agent.context import PlayerMode, classify_mode

        playable = SimpleNamespace(is_playable=True, is_continue_ui=False)
        for action in (0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F):
            me = _player(action_state=action)
            mode = classify_mode(
                me=me,
                player_snap=playable,
                is_mr_x=False,
                entities=(me,),
                player_index=1,
            )
            self.assertIs(mode, PlayerMode.ENEMY_HELD, f"action ${action:02X}")
            self.assertTrue(me.is_held_by_enemy, f"action ${action:02X}")

    def test_strike_band_matches_the_sweep(self) -> None:
        from sor_autoplay.agent.characters import PROFILES

        me = _player(world_x=100, world_y=64)
        profile = PROFILES[0]  # Axel, strike_range 52
        for dx, expected in ((12, False), (24, False), (28, True),
                             (44, True), (70, False)):
            twin = _twin(world_x=100 + dx, world_y=64, slot="B0")
            self.assertEqual(
                twins_ai.can_strike(me, twin, profile), expected, f"dx={dx}"
            )

    def test_a_committed_twin_out_of_reach_does_not_cancel_the_punch(self) -> None:
        """Live: 110 pressure sidesteps alternated with 108 approaches.

        A twin committed to `$15D0C` travels a fixed arc. Beyond its reach it
        cannot touch us this decision, so it must not cancel an in-range punch
        on the focus.
        """

        me = _player(world_x=100, world_y=64)
        focus = _twin(world_x=140, world_y=64, slot="B0", mode_flags=1)
        far_committed = _twin(
            world_x=225,
            world_y=64,
            slot="B1",
            mode_flags=2,
            pair_role=2,
            phase=CombatPhase.ATTACKING,
        )
        decision = self._decide((me, focus, far_committed))
        self.assertTrue(decision.p1_mask & self.ATTACK, decision.p1_note)


class FeignTests(unittest.TestCase):
    """Speedrun tactic: show the back, then back-attack.

    `$15C72` only arms against a player who is facing the boss and closing on
    it, so a turned back denies the grab twin's jump-in outright and the body
    walks into back-attack range under its own power.
    """

    def _decide(self, entities):
        from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
        from tests.test_agent_combat import PolicyIntegrationTests

        helper = PolicyIntegrationTests("run")
        return decide_actions(
            helper._snap(entities),
            AgentConfig(p1_enabled=True, allow_police_special=False),
            AgentState(),
        )

    def _behind(self, dx: int):
        me = _player(world_x=100, world_y=64, action_state=0x02)  # facing right
        rear = _twin(world_x=100 - dx, world_y=64, slot="B0", mode_flags=2, pair_role=2)
        far = _twin(world_x=400, world_y=64, slot="B1", mode_flags=1)
        return self._decide((me, rear, far))

    def test_never_turns_toward_a_twin_closing_on_our_back(self) -> None:
        for dx in (90, 70, 55, 40):
            decision = self._behind(dx)
            # LEFT (0x04) would turn to meet it and arm the jump-in.
            self.assertFalse(decision.p1_mask & 0x04, f"dx={dx}: {decision.p1_note}")

    def test_back_attacks_once_the_rear_twin_arrives(self) -> None:
        decision = self._behind(28)
        self.assertEqual(decision.p1_mask & 0x60, 0x60, decision.p1_note)
        self.assertIn("rear", decision.p1_note)
