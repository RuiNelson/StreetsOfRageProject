"""Round 6's Souther pair (``ai/souther_pair.py``): his state-1 replay, and
the plan built on it for the one who is not in the actor's hands."""

import unittest

from sor_autoplay.ai import souther as single
from sor_autoplay.ai import souther_pair as pair
from sor_autoplay.ai.decide import could_engage_souther, generate_verb_tokens
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.tokens import EngageSouther, Myself, Souther, ThrowHeldEnemy, AttackHeldEnemy, Verb
from sor_autoplay.phases import CombatPhase

CAM_X = 5056


def _actor(world_x: int, world_y: int, *, facing_left: bool = False, **overrides) -> Myself:
    fields = dict(
        slot="P1", player_index=1, character_id=2, character_name="Blaze",
        world_x=world_x, world_y=world_y, health=80, health_percent=100.0, lives=3,
        specials=1, held_weapon_type=0, facing_left=facing_left,
        combat_phase=CombatPhase.NORMAL, action_state=0x02 | int(facing_left), is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def _souther(world_x: int, world_y: int, *, slot: str = "obj01", role: int = 2, **overrides) -> Souther:
    fields = dict(
        slot=slot, type_id=0x55, world_x=world_x, world_y=world_y, health=32,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=False,
        primary_state=1, tactical=0, pair_role=role,
        screen_x=world_x - CAM_X + pair.SCREEN_BIAS,
    )
    fields.update(overrides)
    return Souther(**fields)


def _sim(souther: Souther) -> pair.SoutherSim:
    return pair.SoutherSim.from_token(souther, cam_x=CAM_X)


class CommitGateTests(unittest.TestCase):
    def test_it_is_souther_can_commit_on_for_a_target_walking_in(self) -> None:
        for dx, dy in ((30, 5), (30, -9), (30, -11), (100, 20), (110, 20), (20, 0), (60, 27), (60, 28)):
            with self.subTest(dx=dx, dy=dy):
                actor = _actor(200 + dx, 60 + dy, facing_left=True)
                souther = _souther(200, 60)
                self.assertEqual(
                    pair.commit_gate(dx, abs(dy), above=dy < 0, target_vx=-3.25, target_left_of_him=False),
                    single.can_commit_on(actor, souther),
                )

    def test_the_x_window_follows_the_targets_own_velocity(self) -> None:
        # Target on his right: walking left is into him, right is away.
        self.assertEqual(pair.commit_dx(-3.25, False), pair.COMMIT_DX_CLOSING)
        self.assertEqual(pair.commit_dx(3.25, False), pair.COMMIT_DX_AWAY)
        self.assertEqual(pair.commit_dx(0.0, False), pair.COMMIT_DX_STANDING)
        self.assertEqual(pair.commit_dx(3.25, True), pair.COMMIT_DX_CLOSING)


class StandoffTests(unittest.TestCase):
    def test_a_target_facing_away_is_rushed_and_topped_by_18_to_21_lanes(self) -> None:
        # He is on the actor's left, the actor faces right: the rush.
        sim = _sim(_souther(5100, 60, role=1))
        target = pair.TargetState(x=5250.0, y=60.0, facing_left=False)
        pair.update(sim, target)
        self.assertEqual(sim.vx, pair.RUSH_SPEED)
        self.assertEqual(sim.vy, -4.0)  # level (under 8 px): straight up, 4 px
        eta = pair.commits_within(_sim(_souther(5100, 60, role=1)), target, 40)
        self.assertIsNotNone(eta)

    def test_a_target_facing_him_is_backed_off_from(self) -> None:
        # Inside $78 he backs away 1 px an update; past $90 he closes at 1.
        sim = _sim(_souther(5100, 60, role=1))
        target = pair.TargetState(x=5200.0, y=60.0, facing_left=True)
        pair.update(sim, target)
        self.assertEqual(sim.vx, -pair.RESTORE_SPEED)
        self.assertEqual(sim.vy, 0.0)
        far = _sim(_souther(5100, 60, role=1))
        pair.update(far, pair.TargetState(x=5250.0, y=60.0, facing_left=True))
        self.assertEqual(far.vx, pair.RESTORE_SPEED)
        # From 100 px, backing off: never inside $58 of a standing target.
        self.assertIsNone(pair.commits_within(_sim(_souther(5100, 60, role=1)), target, 40))

    def test_role_two_drifts_half_a_lane_down_by_a_standing_target(self) -> None:
        sim = _sim(_souther(5100, 60, role=2))
        pair.update(sim, pair.TargetState(x=5250.0, y=20.0, facing_left=True))
        self.assertEqual(sim.vy, 0.5)

    def test_the_lane_mirrors_the_targets(self) -> None:
        sim = _sim(_souther(5100, 60, role=1))
        pair.update(sim, pair.TargetState(x=5250.0, y=20.0, vy=-1.625, facing_left=True))
        self.assertEqual(sim.vy, 1.625)

    def test_the_attack_run_waits_for_its_timer(self) -> None:
        sim = _sim(_souther(5100, 60, role=1, mode_flags=pair.ATTACK_RUN_TIMER - 1))
        pair.update(sim, pair.TargetState(x=5250.0, y=60.0, facing_left=True))
        self.assertEqual(sim.tactical, 1)
        pair.update(sim, pair.TargetState(x=5250.0, y=60.0, facing_left=True))
        self.assertEqual(sim.vx, pair.RUSH_SPEED)


class HoldStepTests(unittest.TestCase):
    def _holding(self, x: int, y: int, *, facing_left: bool) -> Myself:
        return _actor(x, y, facing_left=facing_left, action_state=0x60 | int(facing_left), held_enemy_slot="obj00")

    def test_the_other_one_rushing_from_behind_gets_the_throw(self) -> None:
        # Held on the right, the other 110 px behind on the left: the hold
        # faces the actor away from him, so he rushes, tops its lane and claws.
        actor = self._holding(5200, 40, facing_left=False)
        held = _souther(5230, 40, slot="obj00", role=1, primary_state=3)
        other = _souther(5090, 40, role=2)
        self.assertIs(pair.hold_step(actor, held, [other], cam_x=CAM_X), single.HoldStep.THROW)

    def test_the_other_one_in_front_and_lanes_apart_leaves_the_knee(self) -> None:
        # Both in front, the free one 26 lanes under an actor above him: his
        # gate (10 px above) stays shut and he backs off.
        actor = self._holding(5200, 27, facing_left=True)
        held = _souther(5170, 27, slot="obj00", role=1, primary_state=3)
        other = _souther(5160, 53, role=2)
        self.assertIs(pair.hold_step(actor, held, [other], cam_x=CAM_X), single.HoldStep.KNEE)

    def test_a_knee_that_kills_is_never_traded_for_the_throw(self) -> None:
        actor = self._holding(5200, 40, facing_left=False)
        held = _souther(5230, 40, slot="obj00", role=1, primary_state=3, health=2)
        other = _souther(5090, 40, role=2)
        self.assertIs(pair.hold_step(actor, held, [other], cam_x=CAM_X), single.HoldStep.KNEE)


class PickTargetTests(unittest.TestCase):
    def test_the_one_just_let_go_keeps_the_loop(self) -> None:
        actor = _actor(5200, 40, facing_left=True)
        released = _souther(5168, 40, slot="obj01")
        nearer_on_paper = _souther(5190, 70, slot="obj00")
        self.assertIs(pair.pick_target(actor, [nearer_on_paper, released]), released)

    def test_otherwise_the_nearest_not_the_lower_slot(self) -> None:
        actor = _actor(5200, 40)
        far = _souther(5300, 40, slot="obj00")
        near = _souther(5120, 60, slot="obj01")
        self.assertIs(pair.pick_target(actor, [far, near]), near)

    def test_a_knocked_down_one_waits(self) -> None:
        actor = _actor(5200, 40)
        down = _souther(5150, 40, slot="obj00", primary_state=0x08)
        up = _souther(5320, 40, slot="obj01")
        self.assertIs(pair.pick_target(actor, [down, up]), up)


class EngageTests(unittest.TestCase):
    def test_out_of_the_other_ones_live_claw_by_lane(self) -> None:
        actor = _actor(5200, 30, facing_left=True)
        target = _souther(5186, 43, slot="obj00", role=1)
        clawing = _souther(5157, 6, slot="obj01", primary_state=single.CLAW_PRIMARY, facing_left=False)
        plan = pair.plan_engage(actor, target, [clawing], lane_lo=14.0, lane_hi=112.0)
        self.assertIs(plan.mode, single.EngageMode.ESCAPE_CLAW)
        self.assertEqual(plan.target_x, actor.world_x)
        self.assertFalse(single.in_claw_lane(plan.target_y - clawing.world_y))

    def test_one_engage_for_the_pair(self) -> None:
        actor = _actor(5200, 40, facing_left=True)
        verbs = could_engage_souther(
            generate_inference_tokens({actor, _souther(5120, 60, slot="obj01"), _souther(5300, 40, slot="obj00")})
        )
        self.assertEqual(verbs, {EngageSouther(actor_slot="P1", target_slot="obj01")})

    def test_the_throw_is_wired_for_a_held_souther(self) -> None:
        actor = _actor(5200, 40, action_state=0x60, held_enemy_slot="obj00")
        held = _souther(5230, 40, slot="obj00", role=1, primary_state=4, hold_flags=1)
        other = _souther(5090, 40, slot="obj01", role=2)
        verbs = {
            type(v) for v in generate_verb_tokens({actor, held, other}) if isinstance(v, Verb)
        }
        self.assertIn(ThrowHeldEnemy, verbs)
        self.assertNotIn(AttackHeldEnemy, verbs)


if __name__ == "__main__":
    unittest.main()
