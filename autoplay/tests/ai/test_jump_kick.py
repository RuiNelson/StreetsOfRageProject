"""``ai/jump_kick.py`` -- the jump kick's flight, pinned to the lockstep lab.

Every number here was read out of the game one frame at a time
(``tools/jump_kick_lab.py``: grounded idle at X 800, lane 64, height 160,
C + Right on frame 0, B on the first free-flight update). The simulator has
to reproduce them exactly -- positions are 16.16 in the ROM and exact binary
fractions here, so equality is the right test, not closeness.
"""

import unittest

from sor_autoplay.ai import jump_kick
from sor_autoplay.ai.tokens import Enemy, Myself, Partner
from sor_autoplay.phases import CombatPhase

AXEL, ADAM, BLAZE = 0, 1, 2


def make_actor(character_id: int = AXEL, **overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=character_id,
        character_name=("Axel", "Adam", "Blaze")[character_id],
        world_x=800,
        world_y=64,
        world_z=160,
        ground_z=160,
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


def make_partner(**overrides) -> Partner:
    fields = dict(
        slot="P2",
        player_index=2,
        character_id=BLAZE,
        character_name="Blaze",
        world_x=900,
        world_y=64,
        world_z=160,
        ground_z=160,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=True,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Partner(**fields)


def make_enemy(**overrides) -> Enemy:
    fields = dict(
        slot="obj01",
        type_id=0x20,
        world_x=860,
        world_y=64,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Enemy(**fields)


def flight(character_id: int, **kwargs) -> list[jump_kick.KickStep]:
    return jump_kick.launch_arc(make_actor(character_id), **kwargs)


class LabTraceTests(unittest.TestCase):
    def test_axel_kicked_flight_update_by_update(self) -> None:
        steps = flight(AXEL, direction=1, kick_on=1)
        # Launch update: x += 3.0, z += -7.5, no gravity yet.
        self.assertEqual((steps[0].x, steps[0].z), (803.0, 152.5))
        # Free-flight update 1: gravity, one air-steer step (3.375), then the
        # kick edge -- the box is out on this very update.
        self.assertEqual((steps[1].x, steps[1].z), (806.375, 145.90625))
        box = steps[1].attack
        self.assertEqual(
            (box.x0, box.x1, box.y0, box.y1, box.z0, box.z1), (820, 848, 56, 72, 99, 126)
        )
        # The kick locks v_x: 3.375 per update from there to the landing.
        self.assertEqual(steps[2].x - steps[1].x, 3.375)
        # Lands 19 updates after the launch, 67.125 px on.
        self.assertTrue(steps[-1].landed)
        self.assertEqual(len(steps) - 1, 19)
        self.assertEqual(steps[-1].x - 800, 67.125)

    def test_every_character_lands_where_the_lab_did(self) -> None:
        # (kicked, unkicked) X travelled, and apex height above the floor.
        expected = {
            AXEL: (67.125, 62.375, -34.875),
            ADAM: (77.25, 69.375, -44.21875),
            BLAZE: (84.0, 76.375, -54.65625),
        }
        for character, (kicked, unkicked, apex) in expected.items():
            with self.subTest(character=character):
                with_kick = flight(character, direction=1, kick_on=1)
                without = flight(character, direction=1, kick_on=None)
                self.assertEqual(with_kick[-1].x - 800, kicked)
                self.assertEqual(without[-1].x - 800, unkicked)
                self.assertEqual(min(step.z for step in with_kick) - 160, apex)
                self.assertEqual(jump_kick.landing_distance(character), kicked)

    def test_blazes_box_comes_out_six_updates_after_the_edge(self) -> None:
        steps = flight(BLAZE, direction=1, kick_on=1)
        first = next(i for i, step in enumerate(steps) if step.attack is not None)
        self.assertEqual(first, 1 + 6)
        box = steps[first].attack
        self.assertEqual((box.x1 - box.x0, box.z1 - box.z0), (46, 32))

    def test_a_vertical_hop_stays_put(self) -> None:
        steps = flight(ADAM, direction=0, kick_on=1)
        self.assertTrue(all(step.x == 800 for step in steps))

    def test_the_crouch_is_ten_frames(self) -> None:
        # 5 updates at 30 Hz, after the pipeline's own latency.
        steps = flight(AXEL, direction=1, kick_on=1)
        self.assertEqual(
            steps[0].frame, jump_kick.AI_LATENCY_FRAMES + 10
        )
        self.assertEqual(steps[1].frame - steps[0].frame, 2)


class ReachTests(unittest.TestCase):
    def test_axels_kick_lands_on_a_partner_far_past_the_old_band(self) -> None:
        # The old reach band stopped at 60 px. The flight's box, low on the
        # way down, still lands on a standing body 100 px out.
        axel = make_actor(AXEL)
        self.assertTrue(
            jump_kick.launch_hits_player(axel, make_partner(world_x=900), direction=1)
        )
        self.assertFalse(
            jump_kick.launch_hits_player(axel, make_partner(world_x=940), direction=1)
        )

    def test_a_partner_a_lane_band_away_is_safe(self) -> None:
        axel = make_actor(AXEL)
        self.assertFalse(
            jump_kick.launch_hits_player(
                axel, make_partner(world_x=880, world_y=64 + 16 + 1 + 5), direction=1
            )
        )

    def test_a_partner_behind_the_launch_is_safe(self) -> None:
        axel = make_actor(AXEL)
        self.assertFalse(
            jump_kick.launch_hits_player(axel, make_partner(world_x=760), direction=1)
        )

    def test_the_kick_can_pass_over_a_body_right_in_front(self) -> None:
        # Blaze's box only comes out six updates in, near the top of her arc,
        # where it rides above a standing body she has already passed.
        blaze = make_actor(BLAZE)
        self.assertFalse(jump_kick.launch_hits(blaze, make_enemy(world_x=830)))
        self.assertTrue(jump_kick.launch_hits(blaze, make_enemy(world_x=870)))

    def test_every_enemy_on_the_flight_path_is_counted(self) -> None:
        axel = make_actor(AXEL)
        near = make_enemy(slot="obj01", world_x=850)
        far = make_enemy(slot="obj02", world_x=895)
        off_lane = make_enemy(slot="obj03", world_x=870, world_y=100)
        hit = jump_kick.enemies_hit(axel, near, [near, far, off_lane])
        self.assertEqual({enemy.slot for enemy in hit}, {"obj01", "obj02"})


class AirborneArcTests(unittest.TestCase):
    def test_a_flight_in_the_air_resumes_where_the_launch_left_it(self) -> None:
        # Frozen mid-flight at the lab's free-flight update 1, before the kick.
        mid = make_actor(
            AXEL,
            world_x=806,
            world_z=146,
            vel_x=3.375,
            vel_z=-6.59375,
            action_state=0x12,
            is_airborne=True,
        )
        steps = jump_kick.airborne_arc(mid, kick_on=1)
        self.assertTrue(steps[-1].landed)
        self.assertIsNotNone(steps[0].attack)

    def test_an_unknown_floor_is_no_flight(self) -> None:
        mid = make_actor(AXEL, action_state=0x12, is_airborne=True, ground_z=None)
        self.assertEqual(jump_kick.airborne_arc(mid), [])
        self.assertTrue(jump_kick.airborne_hits_player(mid, make_partner()))


class PartnerPadKickTests(unittest.TestCase):
    """In free flight the kick edge is held back while it would land on the
    partner (``execute._hold_back_kick``); the direction stays held."""

    B = 0x0020
    RIGHT = 0x0008

    def _tick(self, partner_x: int):
        from unittest.mock import MagicMock

        from sor_autoplay.ai.execute import execute_tick
        from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
        from sor_autoplay.ai.tokens import JumpAttack

        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        flying = make_actor(
            AXEL,
            world_x=806,
            world_z=146,
            vel_x=3.375,
            vel_z=-6.59375,
            action_state=0x12,
            is_airborne=True,
        )
        context = {flying, make_partner(world_x=partner_x), make_enemy(world_x=850)}
        execute_tick(JumpAttack(actor_slot="P1", target_slot="obj01"), context, gamepad)
        return client

    def _pressed_b(self, client) -> bool:
        return any(call.kwargs["player1"] & self.B for call in client.press_buttons.call_args_list)

    def test_no_kick_edge_while_the_kick_would_land_on_the_partner(self) -> None:
        client = self._tick(partner_x=880)
        self.assertFalse(self._pressed_b(client))
        self.assertEqual(client.hold_buttons.call_args.kwargs["player1"], self.RIGHT)

    def test_the_kick_comes_out_once_the_partner_is_clear(self) -> None:
        self.assertTrue(self._pressed_b(self._tick(partner_x=1000)))


if __name__ == "__main__":
    unittest.main()
