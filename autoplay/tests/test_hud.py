import os
import unittest

from sor_autoplay.ai.reach import CLOSING_ENEMY_THREAT_FRAMES
from sor_autoplay.ai.tokens import CounterGrab, Punch
from sor_autoplay.ai.loop import VerbState
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import WalkToAdvanceStage
from sor_autoplay.hitboxes import Hitbox
from sor_autoplay.hud import ObserverHud, _window_config_path
from sor_autoplay.hud import _describe_verb, _describe_pending
from sor_autoplay.hud import _blend_hex, _closing_projection, _expand_to_min, _hitbox_to_canvas
from sor_autoplay.phases import CombatPhase
from sor_autoplay.world_map import MapEntity, WorldMap


class DescribeVerbTests(unittest.TestCase):
    """_describe_verb is the HUD's "what is the AI doing" label -- it
    reads the field names shared across ai/*.py's Verb subclasses
    (target_slot/threat_slot/direction/coordinate) instead of special-casing
    every concrete class, so this exercises each of those shapes."""

    def test_none_reads_as_no_button(self) -> None:
        self.assertEqual(_describe_verb(None), "—  (no button)")

    def test_verb_with_a_target_slot(self) -> None:
        verb = Punch(actor_slot="P1", target_slot="obj03")

        self.assertEqual(_describe_verb(verb), "Punch  (→obj03)")

    def test_verb_with_only_a_direction(self) -> None:
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")

        self.assertEqual(_describe_verb(verb), "WalkToAdvanceStage  (right)")

    def test_verb_with_no_extra_fields_shows_bare_name(self) -> None:
        self.assertEqual(_describe_verb(CallPolice(actor_slot="P1")), "CallPolice")
        self.assertEqual(_describe_verb(CounterGrab(actor_slot="P1")), "CounterGrab")


class DescribePendingTests(unittest.TestCase):
    """_describe_pending renders the candidate list the AI considered before
    priority collapse -- the HUD's "one extra label (pending verb)"."""

    def test_empty_pending_reads_as_blank(self) -> None:
        self.assertEqual(_describe_pending(()), "")

    def test_single_pending_verb(self) -> None:
        state = VerbState(
            winning=Punch(actor_slot="P1", target_slot="obj03"),
            pending=(Punch(actor_slot="P1", target_slot="obj03"),),
        )
        self.assertEqual(
            _describe_pending(state.pending), "Pending  Punch  (→obj03)"
        )

    def test_multiple_pending_verbs_are_comma_joined(self) -> None:
        pending = (
            Punch(actor_slot="P1", target_slot="obj03"),
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        )
        self.assertEqual(
            _describe_pending(pending),
            "Pending  Punch  (→obj03), WalkToAdvanceStage  (right)",
        )


def _world(*, camera_x: int = 768) -> WorldMap:
    """A WorldMap fixture wide enough that projected coordinates land inside
    the plot; only the fields _hitbox_to_canvas actually reads are given
    non-trivial values."""

    return WorldMap(
        camera_x=camera_x,
        camera_y=0,
        camera_left=32.0,
        camera_right=288.0,
        camera_top=0.0,
        camera_bottom=112.0,
        view_left=-100.0,
        view_right=420.0,
        view_top=-20.0,
        view_bottom=132.0,
        entities=(),
    )


def _enemy_entity(**overrides) -> MapEntity:
    fields = dict(
        kind="enemy",
        family="Signal",
        symbol="S",
        color="#7dffa0",
        label="Signal",
        type_id=0x24,
        world_x=200,
        world_y=64,
        world_z=0,
        map_x=200.0,
        map_y=64.0,
        health=8,
        slot="obj00",
        combat_phase=CombatPhase.ATTACKING,
        facing_left=True,
        enemy_vel_x=-2.5,
        enemy_vel_y=0.0,
    )
    fields.update(overrides)
    return MapEntity(**fields)


class ClosingProjectionTests(unittest.TestCase):
    """_closing_projection is the pure decision behind the HUD's closing-
    threat arrow (a committed ordinary enemy with real velocity toward the
    actor -- Signal's slide, enemy-ai.md "Signal's slide is velocity, not a
    hitbox", is the ROM-confirmed case with no AttackRange at all to draw
    instead)."""

    def test_projects_a_committed_enemys_own_velocity(self) -> None:
        entity = _enemy_entity(map_x=200.0, map_y=64.0, enemy_vel_x=-2.5, enemy_vel_y=1.0)

        result = _closing_projection(entity)

        self.assertEqual(
            result,
            (
                200.0 + -2.5 * CLOSING_ENEMY_THREAT_FRAMES,
                64.0 + 1.0 * CLOSING_ENEMY_THREAT_FRAMES,
            ),
        )

    def test_a_calm_enemy_gets_no_arrow_even_while_moving(self) -> None:
        # A routine approach has real velocity too -- only a committed
        # (ATTACKING/CHARGE) phase should surface it, or every walking
        # enemy would draw one and bury Signal's slide in the noise.
        entity = _enemy_entity(combat_phase=CombatPhase.NORMAL)

        self.assertIsNone(_closing_projection(entity))

    def test_a_stationary_enemy_gets_no_arrow(self) -> None:
        entity = _enemy_entity(enemy_vel_x=0.0, enemy_vel_y=0.0)

        self.assertIsNone(_closing_projection(entity))

    def test_only_ordinary_enemies_qualify_not_players_or_bosses(self) -> None:
        for kind in ("player", "boss", "breakable", "weapon"):
            with self.subTest(kind=kind):
                entity = _enemy_entity(kind=kind)
                self.assertIsNone(_closing_projection(entity))


class HitboxToCanvasTests(unittest.TestCase):
    """X needs the camera offset (hitbox coordinates are absolute world, map
    coordinates are camera-relative); the lane axis (Y) is already absolute
    in both, so it must pass straight through untouched."""

    def test_x_is_offset_by_camera_x_before_projecting(self) -> None:
        world = _world(camera_x=768)
        box = Hitbox(x0=780, x1=820, y0=34, y1=50, z0=-40, z1=-8)
        ox, oy, plot_w, plot_h = 10.0, 10.0, 260.0, 112.0

        x0, y0, x1, y1 = _hitbox_to_canvas(box, world, ox, oy, plot_w, plot_h)

        from sor_autoplay.hud import _map_x, _map_y

        self.assertEqual(x0, _map_x(780 - 768, world, ox, plot_w))
        self.assertEqual(x1, _map_x(820 - 768, world, ox, plot_w))
        self.assertEqual(y0, _map_y(34, world, oy, plot_h))
        self.assertEqual(y1, _map_y(50, world, oy, plot_h))

    def test_a_wider_box_projects_to_a_wider_rectangle(self) -> None:
        world = _world()
        ox, oy, plot_w, plot_h = 10.0, 10.0, 260.0, 112.0
        narrow = Hitbox(x0=790, x1=800, y0=34, y1=50, z0=0, z1=0)
        wide = Hitbox(x0=760, x1=840, y0=34, y1=50, z0=0, z1=0)

        nx0, _, nx1, _ = _hitbox_to_canvas(narrow, world, ox, oy, plot_w, plot_h)
        wx0, _, wx1, _ = _hitbox_to_canvas(wide, world, ox, oy, plot_w, plot_h)

        self.assertGreater(wx1 - wx0, nx1 - nx0)

    def test_an_asymmetric_lane_offset_is_not_recentred(self) -> None:
        # Nora's real whip lane extent (-12..+10) is not symmetric about her
        # own position -- the projection must preserve that, not re-centre it.
        world = _world()
        ox, oy, plot_w, plot_h = 10.0, 10.0, 260.0, 112.0
        box = Hitbox(x0=800, x1=848, y0=64 - 12, y1=64 + 10, z0=0, z1=0)

        _, y0, _, y1 = _hitbox_to_canvas(box, world, ox, oy, plot_w, plot_h)

        from sor_autoplay.hud import _map_y

        self.assertEqual(y0, _map_y(52, world, oy, plot_h))
        self.assertEqual(y1, _map_y(74, world, oy, plot_h))


class BlendHexTests(unittest.TestCase):
    """AttackRange squares fake translucency by pre-mixing a solid colour
    rather than using Tk's `stipple` (silently a no-op on Aqua/macOS,
    rendering flat opaque fill instead of a dithered pattern)."""

    def test_alpha_zero_is_pure_background(self) -> None:
        self.assertEqual(_blend_hex("#ff453a", "#11131c", 0.0), "#11131c")

    def test_alpha_one_is_pure_foreground(self) -> None:
        self.assertEqual(_blend_hex("#ff453a", "#11131c", 1.0), "#ff453a")

    def test_partial_alpha_lands_between_the_two_colours(self) -> None:
        blended = _blend_hex("#ff453a", "#11131c", 0.5)
        for i in (1, 3, 5):
            fg_channel = int("#ff453a"[i : i + 2], 16)
            bg_channel = int("#11131c"[i : i + 2], 16)
            blended_channel = int(blended[i : i + 2], 16)
            lo, hi = sorted((fg_channel, bg_channel))
            self.assertLessEqual(lo, blended_channel)
            self.assertLessEqual(blended_channel, hi)


class ExpandToMinTests(unittest.TestCase):
    def test_leaves_a_span_already_at_or_above_the_minimum_untouched(self) -> None:
        self.assertEqual(_expand_to_min(10.0, 20.0, 6.0), (10.0, 20.0))
        self.assertEqual(_expand_to_min(10.0, 16.0, 6.0), (10.0, 16.0))

    def test_grows_a_smaller_span_symmetrically_about_its_centre(self) -> None:
        a, b = _expand_to_min(10.0, 12.0, 6.0)
        self.assertAlmostEqual(b - a, 6.0)
        self.assertAlmostEqual((a + b) / 2, 11.0)  # centre unchanged

    def test_never_shrinks_a_real_box(self) -> None:
        a, b = _expand_to_min(0.0, 100.0, 6.0)
        self.assertEqual((a, b), (0.0, 100.0))


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
