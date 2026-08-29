"""``ObserverApp._apply_scenario``'s post-jump gating.

Regression coverage for the bug reported live as "go_to_boss_2 resets the
game mid-level": once a ``DebugScenario`` level jump lands, the gate used to
hold the AI off the continue/name-entry screen exactly like it holds it off
being on the wrong level -- so a death before the boss (round 2's Souther
costs 1-2 lives over a long traversal, per autoplay/CLAUDE.md) left the
continue prompt unanswered until its own timer expired and the ROM fell back
to the title screen. That is indistinguishable from the level resetting.
``tools/boss_fight.py`` hit the identical gate and documents it as hanging
the harness completely; this test pins the fix in ``app.py`` itself, which
``scripts/autoplay`` (and so ``scripts/go_to_boss_2``) actually runs.
"""

import unittest

from sor_autoplay import memory_map as mm
from sor_autoplay.app import ObserverApp
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.state import GameSnapshot, PlayerSnapshot


def _player(*, object_type: int, is_playable: bool) -> PlayerSnapshot:
    return PlayerSnapshot(
        index=1,
        mode_active=True,
        object_type=object_type,
        character_id=None,
        character_name="Blaze",
        health=0,
        health_percent=0.0,
        lives=1,
        specials=0,
        score=0,
        score_text="000000",
        continues=0,
        out_flag=0,
        is_playable=is_playable,
    )


def _snapshot(*, level_index: int, player: PlayerSnapshot) -> GameSnapshot:
    empty_p2 = _player(object_type=0, is_playable=False)
    return GameSnapshot(
        connected=True,
        game_state=0,
        game_mode="gameplay",
        level_index=level_index,
        level_display=level_index + 1,
        wave=0,
        player_mode=0,
        time_left=60,
        time_left_raw=60,
        round_timer_bcd=0,
        clock_stopped=False,
        timer_valid=True,
        players=(player, empty_p2),
    )


class ApplyScenarioContinueUiTests(unittest.TestCase):
    def _app_past_jump(self) -> ObserverApp:
        app = ObserverApp(host="127.0.0.1", port=0, scenario=DebugScenario(start_level=2))
        app.scenario._level_jump_done = True  # simulate the jump already landed
        app._client = object()  # any non-None sentinel; only identity is checked
        return app

    def test_continue_ui_is_not_gated_off_even_on_the_wrong_level(self) -> None:
        app = self._app_past_jump()
        continue_ui_player = _player(object_type=mm.OBJ_TYPE_CONTINUE_UI, is_playable=False)
        # level_index deliberately does not match the target level (0, not 1):
        # a dead player's level tracking is moot, and this must not re-trigger
        # the gate that used to strand the continue prompt unanswered.
        snapshot = _snapshot(level_index=0, player=continue_ui_player)

        self.assertTrue(app._apply_scenario(snapshot))

    def test_ordinary_off_level_gameplay_is_still_gated(self) -> None:
        app = self._app_past_jump()
        playable_but_wrong_level = _player(object_type=mm.OBJ_TYPE_ACTIVE_PLAYER, is_playable=True)
        snapshot = _snapshot(level_index=0, player=playable_but_wrong_level)

        self.assertFalse(app._apply_scenario(snapshot))

    def test_on_target_level_and_playable_ticks_normally(self) -> None:
        app = self._app_past_jump()
        playable_on_level = _player(object_type=mm.OBJ_TYPE_ACTIVE_PLAYER, is_playable=True)
        snapshot = _snapshot(level_index=1, player=playable_on_level)

        self.assertTrue(app._apply_scenario(snapshot))


if __name__ == "__main__":
    unittest.main()
