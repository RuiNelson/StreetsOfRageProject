from __future__ import annotations

import unittest

from ai_play.actions import (
    A,
    B,
    C,
    DOWN,
    FRAMES_PER_ACTION,
    LEFT,
    RIGHT,
    UP,
    decode_action,
)


class ActionDecoderTests(unittest.TestCase):
    def test_radius_noise_gate_suppresses_every_button(self) -> None:
        decoded = decode_action((1, 0, 0.25, 1, 1, 1))
        self.assertEqual(decoded.buttons, 0)
        self.assertEqual(decoded.held_frames, 0)

    def test_radius_maps_to_one_through_twelve_frames(self) -> None:
        self.assertEqual(decode_action((0, 0, 0.25001, 0, 0, 0)).held_frames, 1)
        self.assertEqual(
            decode_action((0, 0, 1.0, 0, 0, 0)).held_frames,
            FRAMES_PER_ACTION,
        )

    def test_quantizes_eight_screen_directions(self) -> None:
        expected = (
            ((1, 0), RIGHT),
            ((1, 1), RIGHT | DOWN),
            ((0, 1), DOWN),
            ((-1, 1), LEFT | DOWN),
            ((-1, 0), LEFT),
            ((-1, -1), LEFT | UP),
            ((0, -1), UP),
            ((1, -1), RIGHT | UP),
        )
        for (x, y), buttons in expected:
            with self.subTest(x=x, y=y):
                self.assertEqual(
                    decode_action((x, y, 1, 0, 0, 0)).buttons,
                    buttons,
                )

    def test_button_thresholds_are_strict(self) -> None:
        at_threshold = decode_action((0, 0, 1, 0.5, 0.5, 0.5))
        self.assertEqual(at_threshold.buttons, 0)

        above = decode_action((0, 0, 1, 0.5001, 0.9, 1))
        self.assertEqual(above.buttons, A | B | C)

    def test_rejects_wrong_action_size(self) -> None:
        with self.assertRaises(ValueError):
            decode_action((0, 0, 1))


if __name__ == "__main__":
    unittest.main()
