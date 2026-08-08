import unittest

from sor_autoplay.ai.attack_decisions import CounterGrab, Punch
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.walk_decisions import Sidestep, WalkToAdvanceStage, WalkToCoordinate
from sor_autoplay.hud import _describe_decision


class DescribeDecisionTests(unittest.TestCase):
    """_describe_decision is the HUD's "what is the AI doing" label -- it
    reads the field names shared across ai/*.py's Decision subclasses
    (target_slot/threat_slot/direction/coordinate) instead of special-casing
    every concrete class, so this exercises each of those shapes."""

    def test_none_reads_as_no_button(self) -> None:
        self.assertEqual(_describe_decision(None), "—  (no button)")

    def test_decision_with_a_target_slot(self) -> None:
        decision = Punch(actor_slot="P1", target_slot="obj03")

        self.assertEqual(_describe_decision(decision), "Punch  (→obj03)")

    def test_decision_with_a_threat_slot_and_direction(self) -> None:
        decision = Sidestep(actor_slot="P1", threat_slot="obj04", direction="up")

        self.assertEqual(_describe_decision(decision), "Sidestep  (up →obj04)")

    def test_decision_with_a_coordinate(self) -> None:
        decision = WalkToCoordinate(actor_slot="P1", target_x=10, target_y=20)

        self.assertEqual(_describe_decision(decision), "WalkToCoordinate  (→(10,20))")

    def test_decision_with_only_a_direction(self) -> None:
        decision = WalkToAdvanceStage(actor_slot="P1", direction="right")

        self.assertEqual(_describe_decision(decision), "WalkToAdvanceStage  (right)")

    def test_decision_with_no_extra_fields_shows_bare_name(self) -> None:
        self.assertEqual(_describe_decision(CallPolice(actor_slot="P1")), "CallPolice")
        self.assertEqual(_describe_decision(CounterGrab(actor_slot="P1")), "CounterGrab")


if __name__ == "__main__":
    unittest.main()
