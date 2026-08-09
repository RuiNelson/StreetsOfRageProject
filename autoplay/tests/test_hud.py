import os
import unittest

from sor_autoplay.ai.tokens import CounterGrab, Punch
from sor_autoplay.ai.loop import DecisionState
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import WalkToAdvanceStage
from sor_autoplay.hud import ObserverHud, _window_config_path
from sor_autoplay.hud import _describe_decision, _describe_pending


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

    def test_decision_with_only_a_direction(self) -> None:
        decision = WalkToAdvanceStage(actor_slot="P1", direction="right")

        self.assertEqual(_describe_decision(decision), "WalkToAdvanceStage  (right)")

    def test_decision_with_no_extra_fields_shows_bare_name(self) -> None:
        self.assertEqual(_describe_decision(CallPolice(actor_slot="P1")), "CallPolice")
        self.assertEqual(_describe_decision(CounterGrab(actor_slot="P1")), "CounterGrab")


class DescribePendingTests(unittest.TestCase):
    """_describe_pending renders the candidate list the AI considered before
    priority collapse -- the HUD's "one extra label (pending decision)"."""

    def test_empty_pending_reads_as_blank(self) -> None:
        self.assertEqual(_describe_pending(()), "")

    def test_single_pending_decision(self) -> None:
        state = DecisionState(
            winning=Punch(actor_slot="P1", target_slot="obj03"),
            pending=(Punch(actor_slot="P1", target_slot="obj03"),),
        )
        self.assertEqual(
            _describe_pending(state.pending), "Pending  Punch  (→obj03)"
        )

    def test_multiple_pending_decisions_are_comma_joined(self) -> None:
        pending = (
            Punch(actor_slot="P1", target_slot="obj03"),
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        )
        self.assertEqual(
            _describe_pending(pending),
            "Pending  Punch  (→obj03), WalkToAdvanceStage  (right)",
        )


class _FakeRoot:
    """Minimal stand-in for the Tk root: only what _sanitize_geometry uses."""

    def __init__(self) -> None:
        self.root = self

    def winfo_screenwidth(self) -> int:
        return 1600

    def winfo_screenheight(self) -> int:
        return 1000


class WindowGeometryTests(unittest.TestCase):
    """The persisted-window-geometry logic must restore the last size/position
    instead of maximizing, and must never persist a zoomed (maximized) size."""

    def test_config_path_honors_xdg(self) -> None:
        old = os.environ.pop("XDG_CONFIG_HOME", None)
        try:
            os.environ["XDG_CONFIG_HOME"] = "/tmp/cfg"
            self.assertEqual(
                str(_window_config_path()), "/tmp/cfg/sor-autoplay/window.json"
            )
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_sanitize_keeps_valid_geometry(self) -> None:
        self.assertEqual(
            ObserverHud._sanitize_geometry(_FakeRoot(), "900x600+120+90"),
            "900x600+120+90",
        )

    def test_sanitize_clamps_to_screen(self) -> None:
        fake = _FakeRoot()
        self.assertEqual(
            ObserverHud._sanitize_geometry(fake, "2000x1200+1500+200"),
            "1600x1000+0+0",
        )
        self.assertEqual(
            ObserverHud._sanitize_geometry(fake, "800x600+4000+5000"),
            "800x600+800+400",
        )

    def test_sanitize_rejects_garbage(self) -> None:
        fake = _FakeRoot()
        self.assertIsNone(ObserverHud._sanitize_geometry(fake, ""))
        self.assertIsNone(ObserverHud._sanitize_geometry(fake, "abc"))
        self.assertIsNone(ObserverHud._sanitize_geometry(fake, "0x600+1+1"))
        self.assertIsNone(ObserverHud._sanitize_geometry(fake, "900x-5+1+1"))


if __name__ == "__main__":
    unittest.main()
