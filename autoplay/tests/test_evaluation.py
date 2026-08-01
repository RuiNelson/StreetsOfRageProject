"""Deterministic lockstep evaluator and acceptance-metric tests."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from sor_autoplay.agent import (
    AgentConfig,
    AgentDecision,
    AgentState,
    decide_actions,
)
from sor_autoplay.evaluation import (
    EvaluationCriteria,
    EvaluationStep,
    LockstepEvaluator,
    WorkRamSource,
    snapshot_from_work_ram,
)
from sor_autoplay.memory_map import (
    ADDR_CAM_X,
    ADDR_GAME_STATE,
    ADDR_LEVEL,
    ADDR_P1_CHARACTER_ID,
    ADDR_P1_LIVES,
    ADDR_P1_OBJECT,
    ADDR_P1_SPECIALS,
    ADDR_PLAYER_MODE,
    ADDR_WAVE,
    MAX_HEALTH,
    OBJ_ACTION_STATE,
    OBJ_CHARACTER_ID,
    OBJ_FLAGS,
    OBJ_HEALTH,
    OBJ_HELD_TYPE,
    OBJ_POS_X,
    OBJ_POS_Y,
    OBJ_POS_Z,
    OBJ_PRIMARY_STATE,
    OBJ_TYPE,
)


BASE = 0xFF0000
OBJECT_TABLE = 0xFFB900


def _offset(address: int) -> int:
    return address - BASE


def _put_u8(ram: bytearray, address: int, value: int) -> None:
    ram[_offset(address)] = value & 0xFF


def _put_u16(ram: bytearray, address: int, value: int) -> None:
    start = _offset(address)
    ram[start : start + 2] = (value & 0xFFFF).to_bytes(2, "big")


def _put_fixed(ram: bytearray, address: int, value: int) -> None:
    start = _offset(address)
    ram[start : start + 4] = ((value & 0xFFFF) << 16).to_bytes(4, "big")


def _game_ram(
    *,
    health: int = MAX_HEALTH,
    lives: int = 3,
    item: bool = True,
    enemy_health: int | None = None,
    enemy_primary: int = 0x0100,
) -> bytes:
    ram = bytearray(0x10000)
    _put_u16(ram, ADDR_GAME_STATE, 0x0016)
    _put_u16(ram, ADDR_LEVEL, 0)
    _put_u16(ram, ADDR_WAVE, 1)
    _put_u8(ram, ADDR_PLAYER_MODE, 1)
    _put_u8(ram, ADDR_P1_CHARACTER_ID, 0)
    _put_u8(ram, ADDR_P1_LIVES, lives)
    _put_u8(ram, ADDR_P1_SPECIALS, 1)
    _put_u16(ram, ADDR_CAM_X, 0)

    p1 = ADDR_P1_OBJECT
    _put_u8(ram, p1 + OBJ_TYPE, 1)
    _put_u8(ram, p1 + OBJ_ACTION_STATE, 0x02)
    _put_u16(ram, p1 + OBJ_HEALTH, health)
    _put_u8(ram, p1 + OBJ_CHARACTER_ID, 0)
    _put_fixed(ram, p1 + OBJ_POS_X, 100)
    _put_fixed(ram, p1 + OBJ_POS_Y, 64)
    _put_fixed(ram, p1 + OBJ_POS_Z, 160)

    if enemy_health is not None:
        _put_u8(ram, OBJECT_TABLE + OBJ_TYPE, 0x22)
        _put_u16(ram, OBJECT_TABLE + OBJ_PRIMARY_STATE, enemy_primary)
        _put_u16(ram, OBJECT_TABLE + OBJ_HEALTH, enemy_health)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_X, 130)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_Y, 64)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_Z, 160)
    elif item:
        _put_u8(ram, OBJECT_TABLE + OBJ_TYPE, 0x4B)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_X, 112)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_Y, 64)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_Z, 160)
    return bytes(ram)


@dataclass
class _Result:
    frame: int
    work_ram: bytes


class _FakeClient:
    def __init__(self, work_rams: list[bytes]) -> None:
        self._work_rams = work_rams
        self.calls: list[dict[str, int]] = []
        self.lockstep: list[bool] = []
        self.released = False

    def set_lockstep(self, enabled: bool) -> None:
        self.lockstep.append(enabled)

    def step_input(self, **kwargs: int) -> _Result:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._work_rams) - 1)
        return _Result(frame=len(self.calls), work_ram=self._work_rams[index])

    def release_buttons(self) -> None:
        self.released = True


class WorkRamTests(unittest.TestCase):
    def test_snapshot_decodes_coherent_step_ram(self) -> None:
        snapshot = snapshot_from_work_ram(_game_ram())
        self.assertEqual(snapshot.game_state, 0x16)
        self.assertEqual(snapshot.p1.health, MAX_HEALTH)
        self.assertTrue(any(e.kind == "pickup" for e in snapshot.world_map.entities))

    def test_source_rejects_out_of_range_reads(self) -> None:
        source = WorkRamSource(bytes(0x10000))
        with self.assertRaises(ValueError):
            source.read_memory(0xFEFFFF, 1)
        with self.assertRaises(ValueError):
            WorkRamSource(bytes(10))

    def test_stage2_phantom_is_absent_from_coherent_observation(self) -> None:
        ram = bytearray(_game_ram(item=False, enemy_health=0, enemy_primary=0))
        _put_u16(ram, ADDR_LEVEL, 1)
        _put_u16(ram, ADDR_CAM_X, 768)
        _put_fixed(ram, ADDR_P1_OBJECT + OBJ_POS_X, 800)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_X, 848)
        _put_fixed(ram, OBJECT_TABLE + OBJ_POS_Y, 80)
        _put_u8(ram, OBJECT_TABLE + OBJ_TYPE, 0x21)
        _put_u8(ram, OBJECT_TABLE + OBJ_FLAGS, 0x09)

        snapshot = snapshot_from_work_ram(bytes(ram))

        self.assertFalse(
            any(entity.kind == "enemy" for entity in snapshot.world_map.entities)
        )
        decision = decide_actions(
            snapshot,
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertEqual(decision.p1_mask & 0x20, 0, decision.p1_note)


class LockstepEvaluatorTests(unittest.TestCase):
    def test_weapon_air_attack_and_signal_counter_metrics(self) -> None:
        weapon_ram = bytearray(_game_ram(item=False))
        _put_u8(weapon_ram, ADDR_P1_OBJECT + OBJ_ACTION_STATE, 0x32)
        _put_u8(weapon_ram, ADDR_P1_OBJECT + OBJ_HELD_TYPE, 0x0A)
        weapon_report = LockstepEvaluator(
            _FakeClient([bytes(weapon_ram), bytes(weapon_ram)]),
            decisions=1,
            policy=lambda _snapshot: AgentDecision(
                p1_mask=0x20,
                p2_mask=0,
                p1_note="weapon swing $0A",
            ),
            criteria=EvaluationCriteria(max_weapon_air_attacks=0),
        ).run()
        self.assertEqual(weapon_report.metrics.weapon_attack_edges, 1)
        self.assertEqual(weapon_report.metrics.weapon_air_attack_edges, 1)
        self.assertFalse(weapon_report.passed)

        signal_ram = bytearray(_game_ram(item=False, enemy_health=4))
        _put_u8(signal_ram, OBJECT_TABLE + OBJ_TYPE, 0x24)
        _put_u16(signal_ram, OBJECT_TABLE + OBJ_PRIMARY_STATE, 0x0800)
        signal_report = LockstepEvaluator(
            _FakeClient([bytes(signal_ram), bytes(signal_ram)]),
            decisions=1,
            policy=lambda _snapshot: AgentDecision(
                p1_mask=0x40,
                p2_mask=0,
                p1_note="jump Signal sweep",
            ),
            criteria=EvaluationCriteria(min_signal_sweep_jumps=1),
        ).run()
        self.assertEqual(signal_report.metrics.signal_sweep_jumps, 1)
        self.assertTrue(signal_report.passed)

    def test_exact_face_pulse_metrics_trace_and_acceptance(self) -> None:
        before = _game_ram(health=80, item=True)
        after = _game_ram(health=76, item=False)
        client = _FakeClient([before, before, after])
        trace: list[EvaluationStep] = []
        evaluator = LockstepEvaluator(
            client,
            decisions=1,
            policy=lambda _snapshot: AgentDecision(
                p1_mask=0x20,
                p2_mask=0,
                p1_note="loot Apple",
            ),
            criteria=EvaluationCriteria(
                max_damage=3,
                max_lives_lost=0,
                max_failed_pickups=0,
                min_pickups=1,
            ),
            trace_sink=trace.append,
        )
        report = evaluator.run()

        self.assertFalse(report.passed)
        self.assertEqual(report.metrics.damage_taken, 4)
        self.assertEqual(report.metrics.damage_events, 1)
        self.assertEqual(report.metrics.lives_lost, 0)
        self.assertEqual(report.metrics.pickup_attempts, 1)
        self.assertEqual(report.metrics.pickups_collected, 1)
        self.assertEqual(report.metrics.failed_pickup_attempts, 0)
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0].outcome.damage_taken, 4)
        self.assertEqual(trace[0].outcome.pickups_collected, 1)

        self.assertEqual(client.lockstep, [True, False])
        self.assertTrue(client.released)
        self.assertEqual(client.calls[0]["held_frames"], 0)
        self.assertEqual(client.calls[1]["held_frames"], 3)
        self.assertEqual(client.calls[1]["total_frames"], 3)
        self.assertEqual(client.calls[2]["player1"], 0)
        self.assertEqual(client.calls[2]["held_frames"], 1)

    def test_criteria_reports_every_regression(self) -> None:
        snapshot = snapshot_from_work_ram(_game_ram())
        client = _FakeClient([_game_ram(), _game_ram()])
        report = LockstepEvaluator(
            client,
            decisions=1,
            policy=lambda _snapshot: AgentDecision(0, 0, p1_note="idle"),
            criteria=EvaluationCriteria(min_enemy_damage=1, min_forward_progress=1),
        ).run()
        self.assertEqual(len(report.failures), 2)
        self.assertEqual(snapshot.p1.health, 80)

    def test_life_loss_cannot_look_like_health_gain(self) -> None:
        before = _game_ram(health=4, lives=3, item=False)
        respawned = _game_ram(health=80, lives=2, item=False)
        report = LockstepEvaluator(
            _FakeClient([before, respawned]),
            decisions=1,
            policy=lambda _snapshot: AgentDecision(0, 0, p1_note="idle"),
            criteria=EvaluationCriteria(max_damage=3, max_lives_lost=0),
        ).run()
        self.assertEqual(report.metrics.damage_taken, 4)
        self.assertEqual(report.metrics.lives_lost, 1)
        self.assertEqual(len(report.failures), 2)

    def test_zero_enemy_health_needs_underflow_before_defeat(self) -> None:
        one_hp = _game_ram(item=False, enemy_health=1)
        zero_hp = _game_ram(item=False, enemy_health=0)
        lethal = _game_ram(item=False, enemy_health=0xFFFF, enemy_primary=0x0300)
        report = LockstepEvaluator(
            _FakeClient([one_hp, zero_hp, zero_hp, lethal, lethal]),
            decisions=2,
            policy=lambda _snapshot: AgentDecision(0x20, 0, p1_note="punch"),
        ).run()
        self.assertEqual(report.metrics.enemy_damage, 2)
        self.assertEqual(report.metrics.enemies_defeated, 1)


if __name__ == "__main__":
    unittest.main()
