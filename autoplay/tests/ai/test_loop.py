import unittest
from unittest.mock import MagicMock, patch

from sor_autoplay.ai.tokens import Punch
from sor_autoplay.ai.tokens import Enemy
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop, VerbState
from sor_autoplay.ai.tokens import WalkToAdvanceStage
from sor_autoplay.phases import CombatPhase
from sor_autoplay.state import GameSnapshot, PlayerSnapshot


def _player(*, is_playable: bool) -> PlayerSnapshot:
    return PlayerSnapshot(
        index=1,
        mode_active=True,
        object_type=1,
        character_id=0,
        character_name="Axel",
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        score=0,
        score_text="000000",
        continues=0,
        out_flag=0,
        is_playable=is_playable,
    )


def _snapshot(*, paused: bool = False, timer_valid: bool = True, is_playable: bool = True) -> GameSnapshot:
    p1 = _player(is_playable=is_playable)
    p2 = _player(is_playable=False)
    return GameSnapshot(
        connected=True,
        game_state=0x14,
        game_mode="In game",
        level_index=0,
        level_display=1,
        wave=0,
        player_mode=1,
        time_left=99,
        time_left_raw=0x99,
        round_timer_bcd=0,
        clock_stopped=False,
        timer_valid=timer_valid,
        paused=paused,
        players=(p1, p2),
    )


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    state = SharedGamepadState(client)
    return VirtualGamepad(state, player_index=1), client


class AgentLoopGatingTests(unittest.TestCase):
    def test_paused_releases_and_skips_observation(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(0x0008)
        client.hold_buttons.reset_mock()
        loop = AgentLoop(gamepad)
        snapshot = _snapshot(paused=True)

        with patch("sor_autoplay.ai.loop.generate_direct_observation_tokens") as observe:
            result = loop.tick(snapshot, player_index=1)
            observe.assert_not_called()

        self.assertEqual(gamepad.held, 0)
        self.assertIsNone(result)

    def test_invalid_timer_releases_and_skips_observation(self) -> None:
        gamepad, _client = _gamepad()
        loop = AgentLoop(gamepad)
        snapshot = _snapshot(timer_valid=False)

        with patch("sor_autoplay.ai.loop.generate_direct_observation_tokens") as observe:
            result = loop.tick(snapshot, player_index=1)
            observe.assert_not_called()

        self.assertEqual(gamepad.held, 0)
        self.assertIsNone(result)

    def test_not_playable_releases_and_skips_observation(self) -> None:
        gamepad, _client = _gamepad()
        loop = AgentLoop(gamepad)
        snapshot = _snapshot(is_playable=False)

        with patch("sor_autoplay.ai.loop.generate_direct_observation_tokens") as observe:
            result = loop.tick(snapshot, player_index=1)
            observe.assert_not_called()

        self.assertEqual(gamepad.held, 0)
        self.assertIsNone(result)


class AgentLoopPipelineTests(unittest.TestCase):
    def test_full_pipeline_wires_observe_inference_decide_priority_execute(self) -> None:
        gamepad, client = _gamepad()
        loop = AgentLoop(gamepad)
        snapshot = _snapshot()

        enemy = Enemy(
            slot="obj01",
            type_id=0x20,
            world_x=0,
            world_y=0,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )
        punch = Punch(actor_slot="P1", target_slot="obj01")
        observed_context = {enemy}
        verb_context = {enemy, punch}

        with (
            patch(
                "sor_autoplay.ai.loop.generate_direct_observation_tokens",
                return_value=observed_context,
            ) as observe,
            patch(
                "sor_autoplay.ai.loop.generate_inference_tokens",
                return_value=set(),
            ) as inference,
            patch(
                "sor_autoplay.ai.loop.generate_verb_tokens",
                return_value=verb_context,
            ) as decide,
        ):
            result = loop.tick(snapshot, player_index=1)

            observe.assert_called_once_with(
                snapshot, player_index=1, nora_tracker=loop._nora_tracker
            )
            inference.assert_called_once_with(observed_context)
            decide.assert_called_once()

        # generate_verb_tokens's return value stood in for the whole
        # accumulated context; determine_priority_verb keeps the single
        # Punch, and execute_verb should have pressed B (punch).
        client.press_buttons.assert_called_once_with(player1=0x0020, player2=0, frames=4)
        # tick() hands back the winning Verb (e.g. for a HUD to show
        # what the AI is doing) after execute_verb has already run.
        self.assertIs(result, punch)

    def test_no_surviving_verb_presses_no_button(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(0x0008)
        client.hold_buttons.reset_mock()
        loop = AgentLoop(gamepad)
        snapshot = _snapshot()

        with (
            patch(
                "sor_autoplay.ai.loop.generate_direct_observation_tokens",
                return_value=set(),
            ),
            patch("sor_autoplay.ai.loop.generate_inference_tokens", return_value=set()),
            patch("sor_autoplay.ai.loop.generate_verb_tokens", return_value=set()),
        ):
            result = loop.tick(snapshot, player_index=1)

        self.assertEqual(gamepad.held, 0)
        self.assertIsNone(result)


class VerbStateHudTests(unittest.TestCase):
    """AI.md's UI step: every tick copies the surviving Verb plus every
    candidate into a thread-safe VerbState the HUD can read without
    touching the pipeline."""

    def _enemy(self) -> Enemy:
        return Enemy(
            slot="obj01",
            type_id=0x20,
            world_x=0,
            world_y=0,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )

    def test_inform_hud_exposes_winning_and_pending(self) -> None:
        loop = AgentLoop(_gamepad()[0])
        enemy = self._enemy()
        punch = Punch(actor_slot="P1", target_slot="obj01")

        loop.inform_hud({enemy, punch}, pending=(punch,))

        state = loop.verb_state()
        self.assertIsInstance(state, VerbState)
        self.assertIs(state.winning, punch)
        self.assertEqual(state.pending, (punch,))

    def test_inform_hud_clears_with_empty_context(self) -> None:
        loop = AgentLoop(_gamepad()[0])
        punch = Punch(actor_slot="P1", target_slot="obj01")
        loop.inform_hud({punch}, pending=(punch,))

        loop.inform_hud(set())

        state = loop.verb_state()
        self.assertIsNone(state.winning)
        self.assertEqual(state.pending, ())

    def test_full_pipeline_fills_pending_with_all_candidates(self) -> None:
        gamepad, _client = _gamepad()
        loop = AgentLoop(gamepad)
        enemy = self._enemy()
        punch = Punch(actor_slot="P1", target_slot="obj01")
        walk = WalkToAdvanceStage(actor_slot="P1", direction="right")

        with (
            patch(
                "sor_autoplay.ai.loop.generate_direct_observation_tokens",
                return_value={enemy},
            ),
            patch("sor_autoplay.ai.loop.generate_inference_tokens", return_value=set()),
            patch(
                "sor_autoplay.ai.loop.generate_verb_tokens",
                return_value={enemy, punch, walk},
            ),
        ):
            result = loop.tick(_snapshot(), player_index=1)

        state = loop.verb_state()
        self.assertIs(result, punch)
        self.assertIs(state.winning, punch)
        self.assertEqual(set(state.pending), {punch, walk})

    def test_gated_tick_clears_the_previous_verb_state(self) -> None:
        gamepad, _client = _gamepad()
        loop = AgentLoop(gamepad)
        enemy = self._enemy()
        punch = Punch(actor_slot="P1", target_slot="obj01")
        with (
            patch(
                "sor_autoplay.ai.loop.generate_direct_observation_tokens",
                return_value={enemy},
            ),
            patch("sor_autoplay.ai.loop.generate_inference_tokens", return_value=set()),
            patch(
                "sor_autoplay.ai.loop.generate_verb_tokens",
                return_value={enemy, punch},
            ),
        ):
            loop.tick(_snapshot(), player_index=1)
        self.assertIs(loop.verb_state().winning, punch)

        with patch("sor_autoplay.ai.loop.generate_direct_observation_tokens") as observe:
            loop.tick(_snapshot(paused=True), player_index=1)
            observe.assert_not_called()

        state = loop.verb_state()
        self.assertIsNone(state.winning)
        self.assertEqual(state.pending, ())


if __name__ == "__main__":
    unittest.main()
