"""``MoveAwayFromPartner``: step out from under the partner, along the lane
away from it (level: P1 up, P2 down), as the top-priority verb (user)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from sor_ai.ai.decide import could_move_away_from_partner, generate_verb_tokens
from sor_ai.ai.execute import execute_tick
from sor_ai.ai.gamepad import AXIS_RAMP_TICKS, SharedGamepadState, VirtualGamepad
from sor_ai.ai.priority import determine_priority_verb
from sor_ai.ai.tokens import (
    AnimationInProgress,
    CameraRange,
    InContinueMenu,
    Garcia,
    MoveAwayFromPartner,
    Myself,
    Partner,
    Stage,
    Verb,
    find_all,
)
from sor_ai.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008
CAMERA = CameraRange(left=0, right=320, top=0, bottom=112)
STAGE = Stage(level_index=0, direction="right")


def _player(cls, slot: str, index: int, **overrides):
    fields = dict(
        slot=slot,
        player_index=index,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=64,
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
    fields.update(overrides)
    return cls(**fields)


def _p1(**overrides) -> Myself:
    return _player(Myself, "P1", 1, **overrides)


def _p2_myself(**overrides) -> Myself:
    return _player(Myself, "P2", 2, **overrides)


def _partner(slot: str = "P2", **overrides) -> Partner:
    return _player(Partner, slot, 2 if slot == "P2" else 1, **overrides)


def _verbs(context) -> set[Verb]:
    return set(find_all(context, Verb))


class CouldMoveAwayTests(unittest.TestCase):
    def test_produced_when_both_axes_are_under_ten(self) -> None:
        context = {_p1(), _partner(world_x=105, world_y=68)}

        self.assertEqual(
            could_move_away_from_partner(context),
            {MoveAwayFromPartner(actor_slot="P1", target_slot="P2")},
        )

    def test_not_produced_when_either_axis_is_ten_or_more(self) -> None:
        # Level on the lane at a distance is an ordinary side-by-side fight.
        self.assertEqual(
            could_move_away_from_partner({_p1(), _partner(world_x=140, world_y=64)}), set()
        )
        self.assertEqual(
            could_move_away_from_partner({_p1(), _partner(world_x=100, world_y=74)}), set()
        )

    def test_not_produced_without_a_partner(self) -> None:
        self.assertEqual(could_move_away_from_partner({_p1()}), set())

    def test_not_produced_mid_animation_airborne_or_in_a_menu(self) -> None:
        partner = _partner(world_x=100)
        self.assertEqual(
            could_move_away_from_partner(
                {_p1(), partner, AnimationInProgress(slot="P1")}
            ),
            set(),
        )
        self.assertEqual(
            could_move_away_from_partner({_p1(is_airborne=True), partner}), set()
        )
        self.assertEqual(
            could_move_away_from_partner({_p1(), partner, InContinueMenu(slot="P1", name_entry=False, selects_no=False)}), set()
        )

    def test_the_second_player_produces_it_too(self) -> None:
        context = {_p2_myself(), _partner("P1", world_x=102)}

        self.assertEqual(
            could_move_away_from_partner(context),
            {MoveAwayFromPartner(actor_slot="P2", target_slot="P1")},
        )


class MoveAwayPriorityTests(unittest.TestCase):
    def test_outranks_an_enemy_walk_and_a_punch(self) -> None:
        enemy = Garcia(
            slot="obj01",
            type_id=0x20,
            world_x=130,
            world_y=64,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )
        context = {_p1(), _partner(world_x=104, world_y=66), enemy, STAGE, CAMERA}
        context |= generate_verb_tokens(context)
        self.assertGreater(len(_verbs(context)), 1)

        winner = _verbs(determine_priority_verb(context))

        self.assertEqual(winner, {MoveAwayFromPartner(actor_slot="P1", target_slot="P2")})


class MoveAwayExecuteTests(unittest.TestCase):
    def _run(self, actor, partner):
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=actor.player_index)
        verb = MoveAwayFromPartner(actor_slot=actor.slot, target_slot=partner.slot)
        # An X step rides the pad's steering ramp; a lane step is held at once.
        for _ in range(AXIS_RAMP_TICKS):
            execute_tick(verb, {actor, partner, CAMERA}, gamepad)
        return gamepad.held

    def test_level_on_the_lane_p1_goes_up_even_though_that_reads_as_a_grab(self) -> None:
        held = self._run(_p1(world_y=64), _partner(world_x=102, world_y=64))

        self.assertEqual(held, UP)

    def test_level_on_the_lane_p2_goes_down(self) -> None:
        held = self._run(_p2_myself(world_y=64), _partner("P1", world_x=102, world_y=64))

        self.assertEqual(held, DOWN)

    def test_below_the_partner_goes_down_whoever_it_is(self) -> None:
        # The case the first wording got wrong: P1 below P2 went up, at them.
        self.assertEqual(self._run(_p1(world_y=68), _partner(world_x=102, world_y=64)), DOWN)
        self.assertEqual(
            self._run(_p2_myself(world_y=68), _partner("P1", world_x=102, world_y=64)), DOWN
        )

    def test_above_the_partner_goes_up_whoever_it_is(self) -> None:
        self.assertEqual(self._run(_p1(world_y=60), _partner(world_x=102, world_y=64)), UP)
        self.assertEqual(
            self._run(_p2_myself(world_y=60), _partner("P1", world_x=102, world_y=64)), UP
        )

    def test_at_the_lane_edge_it_steps_away_on_x_instead(self) -> None:
        # Top of the band, level: the lane step is out, the partner is to the
        # right, so the actor goes left -- never down toward nothing it chose.
        held = self._run(_p1(world_x=100, world_y=8), _partner(world_x=104, world_y=8))

        self.assertEqual(held, LEFT)

    def test_at_the_lane_edge_a_partner_on_the_inside_is_not_walked_into(self) -> None:
        # Above the partner and at the top edge: up is blocked, and down would
        # be toward them, so only the X step is left.
        held = self._run(_p1(world_x=104, world_y=8), _partner(world_x=100, world_y=12))

        self.assertEqual(held, RIGHT)


if __name__ == "__main__":
    unittest.main()
