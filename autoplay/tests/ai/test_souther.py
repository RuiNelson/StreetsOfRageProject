"""The Souther plan's ROM model and decisions (``ai/souther.py``).

Pure functions over tokens, so every rule the engage and the hold loop rest on
is pinned here directly -- the multi-tick behaviour is ``test_stability``'s,
the verb wiring ``test_decide``/``test_priority``/``test_execute``'s.
"""

import unittest
from dataclasses import replace

from sor_autoplay.ai import souther as plan
from sor_autoplay.ai.tokens import Myself, Souther
from sor_autoplay.phases import CombatPhase

LANE_LO, LANE_HI = 8.0, 106.0


def _actor(world_x: int, world_y: int, *, facing_left: bool = False, **overrides) -> Myself:
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
        facing_left=facing_left,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def _souther(world_x: int = 200, world_y: int = 50, *, primary_state: int = 1, **overrides) -> Souther:
    fields = dict(
        slot="obj11",
        type_id=0x55,
        world_x=world_x,
        world_y=world_y,
        health=32,
        combat_phase=CombatPhase.ATTACKING if primary_state == 2 else CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        primary_state=primary_state,
        tactical=0,
    )
    fields.update(overrides)
    return Souther(**fields)


def _engage(actor, souther):
    return plan.plan_engage(actor, souther, lane_lo=LANE_LO, lane_hi=LANE_HI)


class CommitGateTests(unittest.TestCase):
    """``$15EDA``'s lane gate depends on the side: ``$0A`` above, ``$1C`` else."""

    def test_the_gate_is_ten_pixels_above_him_and_twenty_eight_otherwise(self) -> None:
        self.assertEqual(plan.commit_lane(-1), 0x0A)
        self.assertEqual(plan.commit_lane(0), 0x1C)
        self.assertEqual(plan.commit_lane(40), 0x1C)

    def test_eleven_px_above_cannot_be_committed_on_while_eleven_below_can(self) -> None:
        souther = _souther(world_x=200, world_y=50)
        self.assertFalse(plan.can_commit_on(_actor(150, 39), souther))
        self.assertTrue(plan.can_commit_on(_actor(150, 41), souther))
        self.assertTrue(plan.can_commit_on(_actor(150, 41 + 0x1C - 12), souther))
        self.assertFalse(plan.can_commit_on(_actor(150, 50 + 0x1C), souther))

    def test_the_inner_abort_and_the_widest_window_bound_it_on_x(self) -> None:
        souther = _souther(world_x=200, world_y=50)
        self.assertFalse(plan.can_commit_on(_actor(200 - 0x17, 50), souther))
        self.assertTrue(plan.can_commit_on(_actor(200 - 0x18, 50), souther))
        self.assertTrue(plan.can_commit_on(_actor(200 - 0x67, 50), souther))
        self.assertFalse(plan.can_commit_on(_actor(200 - 0x68, 50), souther))

    def test_only_a_free_souther_commits(self) -> None:
        for primary in (0x02, 0x03, 0x04, 0x05, 0x0A):
            with self.subTest(primary=primary):
                self.assertFalse(
                    plan.can_commit_on(_actor(150, 50), _souther(primary_state=primary))
                )
        self.assertFalse(plan.can_commit_on(_actor(150, 50), _souther(health=0xFFFF)))


class ClawBandTests(unittest.TestCase):
    """His claw is his own box: lane -10..+24, body +-8 on top."""

    def test_the_claw_band_is_asymmetric(self) -> None:
        self.assertTrue(plan.in_claw_lane(-17))
        self.assertFalse(plan.in_claw_lane(-18))
        self.assertTrue(plan.in_claw_lane(31))
        self.assertFalse(plan.in_claw_lane(32))

    def test_the_grab_lane_is_under_sixteen(self) -> None:
        self.assertTrue(plan.in_grab_lane(15))
        self.assertTrue(plan.in_grab_lane(-15))
        self.assertFalse(plan.in_grab_lane(16))


class PlanEngageTests(unittest.TestCase):
    def test_on_his_lane_and_close_it_walks_straight_in(self) -> None:
        engage = _engage(_actor(170, 50), _souther(200, 50))
        self.assertIs(engage.mode, plan.EngageMode.WALK_IN)
        self.assertTrue(engage.press_toward)
        self.assertEqual(engage.toward, 1)
        self.assertLess(engage.target_x, 200)

    def test_the_walk_in_keeps_a_lane_inside_the_grab_band(self) -> None:
        # Moving onto his exact lane would cross the 10 px gate above him for
        # nothing: contact only needs the two lanes under 16 apart.
        actor = _actor(170, 38)
        engage = _engage(actor, _souther(200, 50))
        self.assertIs(engage.mode, plan.EngageMode.WALK_IN)
        self.assertEqual(engage.target_y, actor.world_y)

    def test_above_him_the_corridor_sits_between_the_gate_and_the_grab_band(self) -> None:
        engage = _engage(_actor(100, 20), _souther(200, 60))
        self.assertIs(engage.mode, plan.EngageMode.CORRIDOR_ABOVE)
        self.assertEqual(engage.target_y, 60 + plan.ABOVE_AIM_DY)
        # The aim itself is gate-proof (>= 10 above) and grab-ready (<= 15).
        self.assertLessEqual(abs(plan.ABOVE_AIM_DY), plan.GRAB_LANE)
        self.assertGreater(abs(plan.ABOVE_AIM_DY), plan.COMMIT_LANE_ABOVE)
        self.assertFalse(engage.press_toward)

    def test_below_him_the_corridor_clears_both_the_gate_and_the_claw(self) -> None:
        engage = _engage(_actor(100, 100), _souther(200, 40))
        self.assertIs(engage.mode, plan.EngageMode.CORRIDOR_BELOW)
        self.assertEqual(engage.target_y, 40 + plan.BELOW_AIM_DY)
        self.assertGreaterEqual(plan.BELOW_AIM_DY, plan.COMMIT_LANE_LEVEL_OR_BELOW + 4)
        self.assertFalse(plan.in_claw_lane(plan.BELOW_AIM_DY - 3))

    def test_no_room_above_means_the_corridor_below(self) -> None:
        # He fights from the top rows; there is no lane above him to stand in.
        engage = _engage(_actor(100, 60), _souther(200, 6))
        self.assertIs(engage.mode, plan.EngageMode.CORRIDOR_BELOW)

    def test_the_side_the_actor_is_on_is_kept(self) -> None:
        self.assertIs(
            _engage(_actor(100, 90), _souther(200, 50)).mode,
            plan.EngageMode.CORRIDOR_BELOW,
        )
        self.assertIs(
            _engage(_actor(100, 20), _souther(200, 50)).mode,
            plan.EngageMode.CORRIDOR_ABOVE,
        )

    def test_below_him_the_lane_closes_only_inside_his_inner_abort(self) -> None:
        outside = _engage(_actor(200 - plan.CONVERGE_DX - 2, 90), _souther(200, 50))
        inside = _engage(_actor(200 - plan.CONVERGE_DX + 2, 90), _souther(200, 50))
        self.assertIs(outside.mode, plan.EngageMode.CORRIDOR_BELOW)
        self.assertIs(inside.mode, plan.EngageMode.CONVERGE)
        self.assertEqual(inside.target_y, 50)
        self.assertLess(plan.CONVERGE_DX, plan.POCKET_DX)

    def test_a_live_claw_out_of_grab_reach_is_left_by_lane_only(self) -> None:
        actor = _actor(140, 70)  # 20 below: in his claw, not in the grab band
        engage = _engage(actor, _souther(200, 50, primary_state=2))
        self.assertIs(engage.mode, plan.EngageMode.ESCAPE_CLAW)
        self.assertEqual(engage.target_x, actor.world_x)
        self.assertFalse(plan.in_claw_lane(engage.target_y - 50))

    def test_the_shallow_side_escape_is_used_from_above(self) -> None:
        actor = _actor(140, 34)  # 16 above: in his claw, not in the grab band
        engage = _engage(actor, _souther(200, 50, primary_state=2))
        self.assertIs(engage.mode, plan.EngageMode.ESCAPE_CLAW)
        self.assertLess(engage.target_y, 50 - 18)

    def test_a_live_claw_inside_grab_reach_is_walked_into(self) -> None:
        # His leaning body walks into the actor's box: grab beats hit.
        engage = _engage(_actor(165, 50), _souther(200, 50, primary_state=2))
        self.assertIs(engage.mode, plan.EngageMode.WALK_IN)
        self.assertTrue(engage.press_toward)

    def test_toward_always_points_at_him(self) -> None:
        souther = _souther(200, 50)
        self.assertEqual(_engage(_actor(100, 90), souther).toward, 1)
        self.assertEqual(_engage(_actor(300, 90, facing_left=True), souther).toward, -1)
        # On top of him the side comes from facing, not from the jittery compare.
        self.assertEqual(_engage(_actor(198, 50, facing_left=True), souther).toward, -1)
        self.assertEqual(_engage(_actor(202, 50, facing_left=False), souther).toward, 1)


class HoldStepTests(unittest.TestCase):
    def _front(self, *, knees: int, **overrides) -> Myself:
        last = {0: 0, 1: 0x6A, 2: 0x6C}[knees]
        flags = 0x40 if knees else 0
        return _actor(
            100, 50, action_state=0x60, action_flags=flags, knee_chain_last=last,
            held_enemy_slot="obj11", **overrides
        )

    def test_two_knees_then_the_release(self) -> None:
        souther = _souther(health=20)
        self.assertIs(plan.hold_step(self._front(knees=0), souther), plan.HoldStep.KNEE)
        self.assertIs(plan.hold_step(self._front(knees=1), souther), plan.HoldStep.KNEE)
        self.assertIs(plan.hold_step(self._front(knees=2), souther), plan.HoldStep.RELEASE)

    def test_a_third_knee_only_when_it_kills(self) -> None:
        self.assertIs(
            plan.hold_step(self._front(knees=2), _souther(health=3)), plan.HoldStep.KNEE
        )
        self.assertIs(
            plan.hold_step(self._front(knees=2), _souther(health=4)), plan.HoldStep.RELEASE
        )

    def test_a_back_hold_crosses_once_and_only_suplexes_to_kill(self) -> None:
        back = _actor(100, 50, action_state=0x66, held_enemy_slot="obj11")
        self.assertIs(plan.hold_step(back, _souther(health=20)), plan.HoldStep.CROSS)
        self.assertIs(
            plan.hold_step(replace(back, crossover_spent=True), _souther(health=20)),
            plan.HoldStep.RELEASE,
        )
        self.assertIs(plan.hold_step(back, _souther(health=5)), plan.HoldStep.SUPLEX)

    def test_nothing_during_an_animation_lock(self) -> None:
        crossing = _actor(100, 50, action_state=0x76, held_enemy_slot="obj11")
        self.assertIs(plan.hold_step(crossing, _souther()), plan.HoldStep.WAIT)


class KneeChainAndReleaseTests(unittest.TestCase):
    def test_the_chain_is_read_from_the_players_own_object(self) -> None:
        self.assertEqual(_actor(0, 0).knees_in_chain, 0)
        self.assertEqual(_actor(0, 0, action_flags=0x40, knee_chain_last=0x6A).knees_in_chain, 1)
        self.assertEqual(_actor(0, 0, action_flags=0x40, knee_chain_last=0x6C).knees_in_chain, 2)
        # Bit 6 clear: whatever +$61 still holds is a finished chain.
        self.assertEqual(_actor(0, 0, action_flags=0x00, knee_chain_last=0x6C).knees_in_chain, 0)
        # $6E is outside [$6A, $6E): the next B starts a new chain.
        self.assertEqual(_actor(0, 0, action_flags=0x40, knee_chain_last=0x6E).knees_in_chain, 0)

    def test_the_release_press_spans_the_whole_countdown(self) -> None:
        # A fresh hold released on the 8th back frame in every lab cycle.
        self.assertEqual(plan.release_press_frames(3), 8)
        self.assertEqual(plan.release_press_frames(1), 4)
        self.assertEqual(plan.release_press_frames(0), 2)
        # $FF right after a release, or anything out of range: a fresh 3.
        self.assertEqual(plan.release_press_frames(0xFF), 8)


if __name__ == "__main__":
    unittest.main()
