"""Deterministic lockstep evaluation for autoplay policies.

The GUI poller is intentionally real-time.  This module is the repeatable test
surface: every policy decision advances an exact number of emulated frames and
uses the coherent 64 KiB work-RAM image returned by ``step_input``.  A future
learning policy can be injected through the same ``GameSnapshot -> decision``
callable without changing metrics or scenario acceptance criteria.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence, TextIO

from .agent import AgentConfig, AgentDecision, AgentState, decide_actions
from .agent.characters import profile_for
from .agent.combat import (
    can_jump_kick,
    can_punch,
    player_can_start_ground_action,
    signal_sweep_threat,
)
from .agent.expert import DEFAULT_COMBAT_EXPERT, TacticalGoal
from .agent.grabs import (
    ENEMY_GRAB_COUNTER_WINDOW,
    ENEMY_HOLD_ACTION,
    ENEMY_HOLD_ACTIONS,
    context_from_player,
    held_enemy_entity,
)
from .agent.knowledge import Relation, build_tactical_graph
from .phases import should_ignore_as_target
from .state import GameSnapshot, read_snapshot
from .world_map import MapEntity


WORK_RAM_BASE = 0xFF0000
WORK_RAM_SIZE = 0x10000
FACE_BUTTONS = 0x70
DIRECTIONS = 0x0F
GAMEPLAY_STATES = frozenset({0x14, 0x16})
BOSS_STALL_GRACE_STEPS = 8


class LockstepClient(Protocol):
    def set_lockstep(self, enabled: bool) -> object: ...

    def step_input(
        self,
        *,
        player1: int = 0,
        player2: int = 0,
        held_frames: int,
        total_frames: int,
        timeout_ms: int | None = None,
    ) -> object: ...

    def release_buttons(self) -> object: ...


class WorkRamSource:
    """Expose one coherent 64 KiB step result through ``read_snapshot``."""

    def __init__(self, work_ram: bytes) -> None:
        if len(work_ram) != WORK_RAM_SIZE:
            raise ValueError(
                f"work RAM must be exactly {WORK_RAM_SIZE} bytes, got {len(work_ram)}"
            )
        self._work_ram = work_ram

    def read_memory(self, address: int, length: int) -> bytes:
        if length < 0:
            raise ValueError("length must be non-negative")
        start = address - WORK_RAM_BASE
        end = start + length
        if start < 0 or end > WORK_RAM_SIZE:
            raise ValueError(
                f"work-RAM read outside 0x{WORK_RAM_BASE:06X}..0xFFFFFF: "
                f"address=0x{address:06X}, length={length}"
            )
        return self._work_ram[start:end]


def snapshot_from_work_ram(work_ram: bytes) -> GameSnapshot:
    """Decode the coherent work-RAM image returned by a lockstep step."""

    return read_snapshot(WorkRamSource(work_ram))


def _player_entity(snapshot: GameSnapshot, player_index: int) -> MapEntity | None:
    wanted = f"P{player_index}"
    return next(
        (
            entity
            for entity in snapshot.world_map.entities
            if entity.kind == "player" and entity.slot.upper() == wanted
        ),
        None,
    )


def _entities(snapshot: GameSnapshot, kinds: tuple[str, ...]) -> dict[str, MapEntity]:
    return {
        entity.slot: entity
        for entity in snapshot.world_map.entities
        if entity.kind in kinds
    }


@dataclass(frozen=True, slots=True)
class StepOutcome:
    damage_taken: int = 0
    enemy_damage: int = 0
    enemies_defeated: int = 0
    pickups_collected: int = 0
    failed_pickup_attempts: int = 0
    forward_progress: int = 0

    @property
    def reward(self) -> float:
        """Stable baseline score; learning systems may supply another reward."""

        return (
            float(self.enemy_damage)
            - 2.0 * float(self.damage_taken)
            + 8.0 * float(self.pickups_collected)
            + 0.02 * float(self.forward_progress)
        )


@dataclass(slots=True)
class EpisodeMetrics:
    player_index: int
    decisions: int = 0
    frames: int = 0
    start_health: int | None = None
    end_health: int | None = None
    damage_taken: int = 0
    damage_events: int = 0
    lives_lost: int = 0
    enemy_damage: int = 0
    enemies_defeated: int = 0
    pickup_attempts: int = 0
    pickups_collected: int = 0
    failed_pickup_attempts: int = 0
    jumps: int = 0
    ground_attack_attempts: int = 0
    ground_attack_starts: int = 0
    failed_ground_attack_starts: int = 0
    weapon_attack_edges: int = 0
    weapon_air_attack_edges: int = 0
    signal_sweep_jumps: int = 0
    jack_armed_ground_attacks: int = 0
    jack_armed_jump_starts: int = 0
    jack_throw_window_ground_attacks: int = 0
    back_exposed_grab_opportunities: int = 0
    missed_back_exposure_responses: int = 0
    crossover_suplex_starts: int = 0
    suplexes: int = 0
    invalid_grab_animation_attacks: int = 0
    enemy_grab_escape_jump_edges: int = 0
    enemy_grab_counter_throw_edges: int = 0
    missed_enemy_grab_escape_responses: int = 0
    defeated_enemy_attack_edges: int = 0
    defeated_enemy_pursuit_steps: int = 0
    unreachable_enemy_stall_steps: int = 0
    loot_under_threat_steps: int = 0
    boss_progress_steps: int = 0
    boss_stall_steps: int = 0
    face_actions: int = 0
    forward_progress: int = 0
    total_reward: float = 0.0
    actions: Counter[str] = field(default_factory=Counter)
    _last_x: int | None = field(default=None, repr=False)
    _zero_health_foes: set[str] = field(default_factory=set, repr=False)
    _boss_stall_streak: int = field(default=0, repr=False)
    _last_enemy_grab_signature: tuple[int, bool] | None = field(
        default=None,
        repr=False,
    )

    @classmethod
    def start(cls, snapshot: GameSnapshot, player_index: int) -> "EpisodeMetrics":
        player = snapshot.players[player_index - 1]
        entity = _player_entity(snapshot, player_index)
        return cls(
            player_index=player_index,
            start_health=player.health,
            end_health=player.health,
            _last_x=None if entity is None else entity.world_x,
            _zero_health_foes={
                foe.slot
                for foe in snapshot.world_map.entities
                if foe.kind in ("enemy", "boss") and foe.health == 0
            },
        )

    def observe(
        self,
        before: GameSnapshot,
        after: GameSnapshot,
        decision: AgentDecision,
        *,
        advanced_frames: int,
    ) -> StepOutcome:
        before_player = before.players[self.player_index - 1]
        after_player = after.players[self.player_index - 1]
        mask = decision.p1_mask if self.player_index == 1 else decision.p2_mask
        note = decision.p1_note if self.player_index == 1 else decision.p2_note
        bucket = note.split(" ", 1)[0] if note else "empty"
        self.actions[bucket] += 1
        self.decisions += 1
        self.frames += advanced_frames
        self.end_health = after_player.health
        if mask & FACE_BUTTONS:
            self.face_actions += 1
        if mask & 0x40:
            self.jumps += 1

        before_entity = _player_entity(before, self.player_index)
        after_entity = _player_entity(after, self.player_index)
        ground_attack_attempt = bool(
            (mask & 0x60) == 0x20
            and not note.startswith("loot ")
            and before_entity is not None
            and player_can_start_ground_action(before_entity)
        )
        if ground_attack_attempt:
            self.ground_attack_attempts += 1
            if (
                after_entity is not None
                and not player_can_start_ground_action(after_entity)
            ):
                self.ground_attack_starts += 1
            else:
                self.failed_ground_attack_starts += 1

        weapon_attack = bool(
            mask & 0x20
            and before_entity is not None
            and before_entity.is_holding_weapon
            and (
                note.startswith("weapon ")
                or note.startswith("dump weapon ")
            )
        )
        if weapon_attack:
            self.weapon_attack_edges += 1
            live_foe_on_screen = any(
                entity.kind in ("enemy", "boss")
                and 0 <= entity.map_x <= 320
                and not entity.is_defeated
                and not should_ignore_as_target(entity.combat_phase)
                for entity in before.world_map.entities
            )
            if not live_foe_on_screen:
                self.weapon_air_attack_edges += 1

        if mask & 0x40 and before_entity is not None:
            if any(
                entity.kind in ("enemy", "boss")
                and not entity.is_defeated
                and signal_sweep_threat(before_entity, entity)
                for entity in before.world_map.entities
            ):
                self.signal_sweep_jumps += 1

        if before_entity is not None:
            graph = build_tactical_graph(
                before_entity,
                before.world_map.entities,
                level_index=before.level_index,
                player_index=self.player_index,
            )
            profile = profile_for(before_player.character_id)
            armed_jacks = graph.entities_with(Relation.ARMED)
            throwing_jacks = graph.entities_with(Relation.THROWING)
            if (
                mask & 0x20
                and player_can_start_ground_action(before_entity)
                and any(
                    can_punch(
                        before_entity,
                        jack,
                        profile,
                        require_facing=False,
                    )
                    for jack in armed_jacks
                )
            ):
                self.jack_armed_ground_attacks += 1
            if mask & 0x40 and any(
                can_jump_kick(before_entity, jack, profile)
                for jack in armed_jacks
            ):
                self.jack_armed_jump_starts += 1
            if (
                mask & 0x20
                and player_can_start_ground_action(before_entity)
                and any(
                    can_punch(
                        before_entity,
                        jack,
                        profile,
                        require_facing=False,
                    )
                    for jack in throwing_jacks
                )
            ):
                self.jack_throw_window_ground_attacks += 1
            grab = context_from_player(
                before_entity,
                before.world_map.entities,
                player_index=self.player_index,
            )
            held_enemy = (
                held_enemy_entity(before_entity, before.world_map.entities)
                if grab.enemy_grab
                else None
            )
            assessment = DEFAULT_COMBAT_EXPERT.assess(
                before_entity,
                before.world_map.entities,
                held_enemy=held_enemy,
            )
            if assessment.goal == TacticalGoal.CROSSOVER_SUPLEX:
                self.back_exposed_grab_opportunities += 1
                if mask & 0x40:
                    self.crossover_suplex_starts += 1
                else:
                    self.missed_back_exposure_responses += 1
            if grab.enemy_grab and before_entity.action_base == 0x66 and mask & 0x20:
                self.suplexes += 1

            if (
                mask & 0x20
                and 0x60 <= before_entity.action_base <= 0x6E
                and before_entity.action_base not in (0x60, 0x66)
            ):
                self.invalid_grab_animation_attacks += 1

            if before_entity.action_base == ENEMY_HOLD_ACTION:
                counter_window = bool(
                    before_entity.action_flags & ENEMY_GRAB_COUNTER_WINDOW
                )
                signature = (before_entity.action_base, counter_window)
                expected_mask = 0x20 if counter_window else 0x40
                if mask & expected_mask:
                    if counter_window:
                        self.enemy_grab_counter_throw_edges += 1
                    else:
                        self.enemy_grab_escape_jump_edges += 1
                elif signature != self._last_enemy_grab_signature:
                    self.missed_enemy_grab_escape_responses += 1
                self._last_enemy_grab_signature = signature
            elif before_entity.action_base not in ENEMY_HOLD_ACTIONS:
                self._last_enemy_grab_signature = None

            live_combatants = tuple(
                entity
                for entity in graph.entities_with(Relation.REACHABLE)
                if entity.kind in ("enemy", "boss", "projectile")
            )
            defeated_in_punch_range = any(
                0.0 <= entity.map_x <= 320.0
                and can_punch(
                    before_entity,
                    entity,
                    profile,
                    require_facing=False,
                )
                for entity in graph.entities_with(Relation.DEFEATED)
            )
            if (
                mask & 0x20
                and player_can_start_ground_action(before_entity)
                and defeated_in_punch_range
                and not live_combatants
            ):
                self.defeated_enemy_attack_edges += 1

            defeated_on_screen = tuple(
                entity
                for entity in graph.entities_with(Relation.DEFEATED)
                if 0.0 <= entity.map_x <= 320.0
            )
            other_objectives = tuple(
                entity
                for entity in graph.entities_with(Relation.REACHABLE)
                if entity.kind in ("pickup", "weapon", "breakable")
            )
            # Note-independent pursuit signal for controlled empty-arena
            # scenarios. Normal horizontal stage progress is allowed; moving
            # against it or changing lane toward an allocated corpse is not.
            if (
                defeated_on_screen
                and not live_combatants
                and not other_objectives
            ):
                against_progress = (
                    before.level_index != 7
                    and bool(mask & 0x04)
                    and any(
                        e.map_x < before_entity.map_x - 8
                        for e in defeated_on_screen
                    )
                ) or (
                    before.level_index == 7
                    and bool(mask & 0x08)
                    and any(
                        e.map_x > before_entity.map_x + 8
                        for e in defeated_on_screen
                    )
                )
                toward_lane = (
                    bool(mask & 0x01)
                    and any(
                        e.map_y < before_entity.map_y - 4
                        for e in defeated_on_screen
                    )
                ) or (
                    bool(mask & 0x02)
                    and any(
                        e.map_y > before_entity.map_y + 4
                        for e in defeated_on_screen
                    )
                )
                if against_progress or toward_lane:
                    self.defeated_enemy_pursuit_steps += 1

            blocking = graph.entities_with(Relation.BLOCKS_PROGRESS)
            unreachable = tuple(
                entity
                for entity in before.world_map.entities
                if entity.kind in ("enemy", "boss")
                and 0.0 <= entity.map_x <= 320.0
                and not graph.entity_has(entity, Relation.REACHABLE)
                and not entity.is_defeated
                and not should_ignore_as_target(entity.combat_phase)
            )
            if (
                unreachable
                and not blocking
                and not mask & 0x0F
                and player_can_start_ground_action(before_entity)
            ):
                self.unreachable_enemy_stall_steps += 1

            loot_action = (
                note.startswith("loot ")
                or note.startswith("await loot ")
                or " loot " in note
            )
            immediate_danger = any(
                graph.entity_has(entity, Relation.NEAR_PLAYER)
                for entity in graph.entities_with(Relation.DANGEROUS)
            )
            boss_blocking = any(entity.kind == "boss" for entity in blocking)
            if loot_action and (immediate_danger or boss_blocking):
                self.loot_under_threat_steps += 1
            if boss_blocking and "progress" in note:
                self.boss_progress_steps += 1
            boss_guard_stall = (
                boss_blocking
                and mask == 0
                and note.startswith("guard lane ")
                and player_can_start_ground_action(before_entity)
            )
            if boss_guard_stall:
                self._boss_stall_streak += 1
                if self._boss_stall_streak > BOSS_STALL_GRACE_STEPS:
                    self.boss_stall_steps += 1
            else:
                self._boss_stall_streak = 0

        lives_lost = max(0, before_player.lives - after_player.lives)
        self.lives_lost += lives_lost
        damage_taken = 0
        if lives_lost and before_player.health is not None:
            # A death can remove the player object (health=None) or replace it
            # with a full-health respawn between samples. Count the remaining
            # health depleted on that life so a death cannot look like healing.
            damage_taken = before_player.health
        elif before_player.health is not None and after_player.health is not None:
            damage_taken = max(0, before_player.health - after_player.health)
        if damage_taken:
            self.damage_taken += damage_taken
            self.damage_events += 1

        attack_edge = bool(mask & 0x20)
        before_foes = _entities(before, ("enemy", "boss"))
        after_foes = _entities(after, ("enemy", "boss"))
        enemy_damage = 0
        defeated = 0
        for slot, old in before_foes.items():
            if old.health is None or not 0 <= old.health < 0x8000:
                continue
            new = after_foes.get(slot)
            if old.health == 0:
                self._zero_health_foes.add(slot)
            elif new is not None and new.health is not None and 0 <= new.health < old.health:
                enemy_damage += old.health - new.health
                if new.health == 0:
                    self._zero_health_foes.add(slot)
            elif attack_edge and (
                new is None
                or new.health is None
                or new.health >= 0x8000
                or new.phase_tag == "die"
            ):
                enemy_damage += old.health
                defeated += 1

        # Ordinary-enemy KO checks are signed: zero HP is still active, and a
        # further hit underflows it to $FFFF before death. Track that transition
        # across samples so a finishing hit is neither lost nor counted early.
        for slot in tuple(self._zero_health_foes):
            new = after_foes.get(slot)
            lethal_health = (
                new is not None
                and new.health is not None
                and new.health >= 0x8000
            )
            if new is None or lethal_health or new.phase_tag == "die":
                if lethal_health:
                    enemy_damage += 1
                defeated += 1
                self._zero_health_foes.discard(slot)
        self.enemy_damage += enemy_damage
        self.enemies_defeated += defeated

        loot_attempt = attack_edge and note.startswith("loot ")
        pickup_count = 0
        failed_pickup = 0
        if loot_attempt:
            self.pickup_attempts += 1
            before_items = _entities(before, ("pickup", "weapon"))
            after_items = _entities(after, ("pickup", "weapon"))
            pickup_count = sum(slot not in after_items for slot in before_items)
            if pickup_count:
                self.pickups_collected += pickup_count
            else:
                failed_pickup = 1
                self.failed_pickup_attempts += 1

        progress = 0
        if after_entity is not None:
            if self._last_x is not None:
                raw_progress = after_entity.world_x - self._last_x
                progress = -raw_progress if after.level_index == 7 else raw_progress
                self.forward_progress += progress
            self._last_x = after_entity.world_x

        outcome = StepOutcome(
            damage_taken=damage_taken,
            enemy_damage=enemy_damage,
            enemies_defeated=defeated,
            pickups_collected=pickup_count,
            failed_pickup_attempts=failed_pickup,
            forward_progress=progress,
        )
        self.total_reward += outcome.reward
        return outcome

    def to_dict(self) -> dict[str, object]:
        return {
            "player": self.player_index,
            "decisions": self.decisions,
            "frames": self.frames,
            "start_health": self.start_health,
            "end_health": self.end_health,
            "damage_taken": self.damage_taken,
            "damage_events": self.damage_events,
            "lives_lost": self.lives_lost,
            "enemy_damage": self.enemy_damage,
            "enemies_defeated": self.enemies_defeated,
            "pickup_attempts": self.pickup_attempts,
            "pickups_collected": self.pickups_collected,
            "failed_pickup_attempts": self.failed_pickup_attempts,
            "jumps": self.jumps,
            "ground_attack_attempts": self.ground_attack_attempts,
            "ground_attack_starts": self.ground_attack_starts,
            "failed_ground_attack_starts": self.failed_ground_attack_starts,
            "weapon_attack_edges": self.weapon_attack_edges,
            "weapon_air_attack_edges": self.weapon_air_attack_edges,
            "signal_sweep_jumps": self.signal_sweep_jumps,
            "jack_armed_ground_attacks": self.jack_armed_ground_attacks,
            "jack_armed_jump_starts": self.jack_armed_jump_starts,
            "jack_throw_window_ground_attacks": self.jack_throw_window_ground_attacks,
            "back_exposed_grab_opportunities": self.back_exposed_grab_opportunities,
            "missed_back_exposure_responses": self.missed_back_exposure_responses,
            "crossover_suplex_starts": self.crossover_suplex_starts,
            "suplexes": self.suplexes,
            "invalid_grab_animation_attacks": self.invalid_grab_animation_attacks,
            "enemy_grab_escape_jump_edges": self.enemy_grab_escape_jump_edges,
            "enemy_grab_counter_throw_edges": self.enemy_grab_counter_throw_edges,
            "missed_enemy_grab_escape_responses": self.missed_enemy_grab_escape_responses,
            "defeated_enemy_attack_edges": self.defeated_enemy_attack_edges,
            "defeated_enemy_pursuit_steps": self.defeated_enemy_pursuit_steps,
            "unreachable_enemy_stall_steps": self.unreachable_enemy_stall_steps,
            "loot_under_threat_steps": self.loot_under_threat_steps,
            "boss_progress_steps": self.boss_progress_steps,
            "boss_stall_steps": self.boss_stall_steps,
            "face_actions": self.face_actions,
            "forward_progress": self.forward_progress,
            "total_reward": round(self.total_reward, 3),
            "actions": dict(sorted(self.actions.items())),
        }


@dataclass(frozen=True, slots=True)
class EvaluationCriteria:
    max_damage: int | None = None
    max_damage_events: int | None = None
    max_lives_lost: int | None = None
    max_failed_pickups: int | None = None
    max_failed_ground_attack_starts: int | None = None
    max_weapon_air_attacks: int | None = None
    max_missed_back_exposures: int | None = None
    min_pickups: int | None = None
    min_enemy_damage: int | None = None
    min_forward_progress: int | None = None
    min_signal_sweep_jumps: int | None = None
    min_jack_armed_ground_attacks: int | None = None
    min_jack_armed_jumps: int | None = None
    min_jack_throw_counters: int | None = None
    min_suplexes: int | None = None
    max_invalid_grab_attacks: int | None = None
    min_enemy_grab_escape_jumps: int | None = None
    min_enemy_grab_counter_throws: int | None = None
    max_missed_enemy_grab_escapes: int | None = None
    max_defeated_enemy_attacks: int | None = None
    max_defeated_enemy_pursuit: int | None = None
    max_unreachable_enemy_stalls: int | None = None
    max_loot_under_threat: int | None = None
    max_boss_progress: int | None = None
    max_boss_stalls: int | None = None

    def failures(self, metrics: EpisodeMetrics) -> tuple[str, ...]:
        failures: list[str] = []
        checks = (
            (self.max_damage, metrics.damage_taken, "damage", "at most"),
            (
                self.max_damage_events,
                metrics.damage_events,
                "damage events",
                "at most",
            ),
            (self.max_lives_lost, metrics.lives_lost, "lives lost", "at most"),
            (
                self.max_failed_pickups,
                metrics.failed_pickup_attempts,
                "failed pickup attempts",
                "at most",
            ),
            (
                self.max_failed_ground_attack_starts,
                metrics.failed_ground_attack_starts,
                "failed ground-attack starts",
                "at most",
            ),
            (
                self.max_weapon_air_attacks,
                metrics.weapon_air_attack_edges,
                "weapon air attacks",
                "at most",
            ),
            (
                self.max_missed_back_exposures,
                metrics.missed_back_exposure_responses,
                "missed back-exposure responses",
                "at most",
            ),
            (
                self.max_invalid_grab_attacks,
                metrics.invalid_grab_animation_attacks,
                "invalid grab-animation attacks",
                "at most",
            ),
            (
                self.max_missed_enemy_grab_escapes,
                metrics.missed_enemy_grab_escape_responses,
                "missed enemy-grab escape responses",
                "at most",
            ),
            (
                self.max_defeated_enemy_attacks,
                metrics.defeated_enemy_attack_edges,
                "defeated-enemy attack edges",
                "at most",
            ),
            (
                self.max_defeated_enemy_pursuit,
                metrics.defeated_enemy_pursuit_steps,
                "defeated-enemy pursuit steps",
                "at most",
            ),
            (
                self.max_unreachable_enemy_stalls,
                metrics.unreachable_enemy_stall_steps,
                "unreachable-enemy stall steps",
                "at most",
            ),
            (
                self.max_loot_under_threat,
                metrics.loot_under_threat_steps,
                "loot-under-threat steps",
                "at most",
            ),
            (
                self.max_boss_progress,
                metrics.boss_progress_steps,
                "boss-progress steps",
                "at most",
            ),
            (
                self.max_boss_stalls,
                metrics.boss_stall_steps,
                "boss-stall steps after grace window",
                "at most",
            ),
        )
        for limit, observed, label, wording in checks:
            if limit is not None and observed > limit:
                failures.append(f"{label}: expected {wording} {limit}, observed {observed}")
        minimums = (
            (self.min_pickups, metrics.pickups_collected, "pickups"),
            (self.min_enemy_damage, metrics.enemy_damage, "enemy damage"),
            (
                self.min_forward_progress,
                metrics.forward_progress,
                "forward progress",
            ),
            (
                self.min_signal_sweep_jumps,
                metrics.signal_sweep_jumps,
                "Signal sweep jumps",
            ),
            (
                self.min_jack_armed_ground_attacks,
                metrics.jack_armed_ground_attacks,
                "armed-Jack ground attacks",
            ),
            (
                self.min_jack_armed_jumps,
                metrics.jack_armed_jump_starts,
                "armed-Jack jump starts",
            ),
            (
                self.min_jack_throw_counters,
                metrics.jack_throw_window_ground_attacks,
                "Jack throw-window ground counters",
            ),
            (
                self.min_enemy_grab_escape_jumps,
                metrics.enemy_grab_escape_jump_edges,
                "enemy-grab crossover jumps",
            ),
            (
                self.min_enemy_grab_counter_throws,
                metrics.enemy_grab_counter_throw_edges,
                "enemy-grab counter throws",
            ),
            (self.min_suplexes, metrics.suplexes, "suplexes"),
        )
        for limit, observed, label in minimums:
            if limit is not None and observed < limit:
                failures.append(f"{label}: expected at least {limit}, observed {observed}")
        return tuple(failures)


@dataclass(frozen=True, slots=True)
class EvaluationStep:
    decision: int
    frame: int
    game_state: int
    level: int
    wave: int
    health: int | None
    player_x: int | None
    player_y: int | None
    player_action: int | None
    visible_enemies: int
    mask: int
    note: str
    outcome: StepOutcome
    actors: tuple[dict[str, object], ...] = ()
    player_action_flags: int = 0
    player_contact: int = 0
    player_held_type: int = 0
    player_held_ptr: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "frame": self.frame,
            "game_state": self.game_state,
            "level": self.level,
            "wave": self.wave,
            "health": self.health,
            "player_x": self.player_x,
            "player_y": self.player_y,
            "player_action": self.player_action,
            "visible_enemies": self.visible_enemies,
            "mask": self.mask,
            "note": self.note,
            "actors": list(self.actors),
            "player_action_flags": self.player_action_flags,
            "player_contact": self.player_contact,
            "player_held_type": self.player_held_type,
            "player_held_ptr": self.player_held_ptr,
            "outcome": {
                "damage_taken": self.outcome.damage_taken,
                "enemy_damage": self.outcome.enemy_damage,
                "enemies_defeated": self.outcome.enemies_defeated,
                "pickups_collected": self.outcome.pickups_collected,
                "failed_pickup_attempts": self.outcome.failed_pickup_attempts,
                "forward_progress": self.outcome.forward_progress,
                "reward": round(self.outcome.reward, 3),
            },
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    metrics: EpisodeMetrics
    failures: tuple[str, ...]
    terminal_reason: str

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "terminal_reason": self.terminal_reason,
            "failures": list(self.failures),
            "metrics": self.metrics.to_dict(),
        }


class LockstepEvaluator:
    """Run a policy with exact frame steps and collect comparable outcomes."""

    def __init__(
        self,
        client: LockstepClient,
        *,
        player_index: int = 1,
        decisions: int = 600,
        step_frames: int = 4,
        face_frames: int = 3,
        step_timeout_ms: int = 5_000,
        policy: Callable[[GameSnapshot], AgentDecision] | None = None,
        agent_config: AgentConfig | None = None,
        criteria: EvaluationCriteria | None = None,
        trace_sink: Callable[[EvaluationStep], None] | None = None,
    ) -> None:
        if player_index not in (1, 2):
            raise ValueError("player_index must be 1 or 2")
        if decisions <= 0:
            raise ValueError("decisions must be positive")
        if step_frames < 2:
            raise ValueError("step_frames must be at least 2")
        if not 1 <= face_frames < step_frames:
            raise ValueError("face_frames must be in 1..step_frames-1")
        if step_timeout_ms <= 0:
            raise ValueError("step_timeout_ms must be positive")
        self.client = client
        self.player_index = player_index
        self.decisions = decisions
        self.step_frames = step_frames
        self.face_frames = face_frames
        self.step_timeout_ms = step_timeout_ms
        self.criteria = criteria or EvaluationCriteria()
        self.trace_sink = trace_sink
        if policy is None:
            config = agent_config or AgentConfig(
                p1_enabled=player_index == 1,
                p2_enabled=player_index == 2,
                police_threshold=99.0,
            )
            memory = AgentState()
            self.policy = lambda snapshot: decide_actions(snapshot, config, memory)
        else:
            self.policy = policy

    def _advance(self, decision: AgentDecision) -> object:
        p1 = decision.p1_mask
        p2 = decision.p2_mask
        if (p1 | p2) & FACE_BUTTONS:
            self.client.step_input(
                player1=p1,
                player2=p2,
                held_frames=self.face_frames,
                total_frames=self.face_frames,
                timeout_ms=self.step_timeout_ms,
            )
            release_frames = self.step_frames - self.face_frames
            return self.client.step_input(
                player1=p1 & DIRECTIONS,
                player2=p2 & DIRECTIONS,
                held_frames=release_frames,
                total_frames=release_frames,
                timeout_ms=self.step_timeout_ms,
            )
        return self.client.step_input(
            player1=p1,
            player2=p2,
            held_frames=self.step_frames,
            total_frames=self.step_frames,
            timeout_ms=self.step_timeout_ms,
        )

    def run(self) -> EvaluationReport:
        self.client.set_lockstep(True)
        terminal_reason = "decision limit"
        try:
            initial = self.client.step_input(
                held_frames=0,
                total_frames=1,
                timeout_ms=self.step_timeout_ms,
            )
            snapshot = snapshot_from_work_ram(initial.work_ram)  # type: ignore[attr-defined]
            if snapshot.game_state not in GAMEPLAY_STATES:
                raise RuntimeError(
                    f"evaluation must start in gameplay, got 0x{snapshot.game_state:04X}"
                )
            if not snapshot.players[self.player_index - 1].is_playable:
                raise RuntimeError(f"P{self.player_index} is not playable")
            metrics = EpisodeMetrics.start(snapshot, self.player_index)
            runtime_failure: str | None = None

            for index in range(self.decisions):
                decision = self.policy(snapshot)
                try:
                    result = self._advance(decision)
                except TimeoutError as exc:
                    runtime_failure = f"lockstep timeout at decision {index}: {exc}"
                    terminal_reason = runtime_failure
                    break
                next_snapshot = snapshot_from_work_ram(result.work_ram)  # type: ignore[attr-defined]
                outcome = metrics.observe(
                    snapshot,
                    next_snapshot,
                    decision,
                    advanced_frames=self.step_frames,
                )
                if self.trace_sink is not None:
                    player = _player_entity(next_snapshot, self.player_index)
                    mask = (
                        decision.p1_mask
                        if self.player_index == 1
                        else decision.p2_mask
                    )
                    note = (
                        decision.p1_note
                        if self.player_index == 1
                        else decision.p2_note
                    )
                    visible_enemies = sum(
                        entity.kind in ("enemy", "boss")
                        and 0 <= entity.map_x <= 320
                        for entity in next_snapshot.world_map.entities
                    )
                    actors = tuple(
                        {
                            "slot": entity.slot,
                            "kind": entity.kind,
                            "type": entity.type_id,
                            "x": entity.world_x,
                            "map_x": entity.map_x,
                            "y": entity.world_y,
                            "z": entity.world_z,
                            "health": entity.health,
                            "action": entity.action_state,
                            "primary": entity.primary_state,
                            "family_state": entity.family_state,
                            "phase": entity.phase_tag,
                        }
                        for entity in next_snapshot.world_map.entities
                        if entity.kind
                        in ("enemy", "boss", "projectile", "pickup", "weapon")
                        and -32 <= entity.map_x <= 352
                    )
                    self.trace_sink(
                        EvaluationStep(
                            decision=index,
                            frame=result.frame,  # type: ignore[attr-defined]
                            game_state=next_snapshot.game_state,
                            level=next_snapshot.level_index,
                            wave=next_snapshot.wave,
                            health=next_snapshot.players[self.player_index - 1].health,
                            player_x=None if player is None else player.world_x,
                            player_y=None if player is None else player.world_y,
                            player_action=None if player is None else player.action_state,
                            visible_enemies=visible_enemies,
                            mask=mask,
                            note=note,
                            outcome=outcome,
                            actors=actors,
                            player_action_flags=(
                                0 if player is None else player.action_flags
                            ),
                            player_contact=0 if player is None else player.contact_ptr,
                            player_held_type=0 if player is None else player.held_type,
                            player_held_ptr=0 if player is None else player.held_ptr,
                        )
                    )
                snapshot = next_snapshot
                if snapshot.game_state not in GAMEPLAY_STATES:
                    terminal_reason = f"left gameplay (0x{snapshot.game_state:04X})"
                    break
                if not snapshot.players[self.player_index - 1].is_playable:
                    terminal_reason = f"P{self.player_index} no longer playable"
                    break

            failures = self.criteria.failures(metrics)
            if runtime_failure is not None:
                failures = (*failures, runtime_failure)
            return EvaluationReport(metrics, failures, terminal_reason)
        finally:
            try:
                self.client.release_buttons()
            finally:
                self.client.set_lockstep(False)


class JsonLinesTrace:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def __call__(self, step: EvaluationStep) -> None:
        self.stream.write(json.dumps(step.to_dict(), sort_keys=True) + "\n")
        self.stream.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sor-autoplay-eval",
        description="Run the autoplay policy in deterministic lockstep and emit JSON metrics.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6969)
    parser.add_argument("--player", type=int, choices=(1, 2), default=1)
    parser.add_argument("--decisions", type=int, default=600)
    parser.add_argument("--step-frames", type=int, default=4)
    parser.add_argument("--face-frames", type=int, default=3)
    parser.add_argument("--step-timeout-ms", type=int, default=5_000)
    parser.add_argument(
        "--restart-character",
        choices=("axel", "adam", "blaze"),
        help="restart and freeze at a verified Round-1 start before evaluation",
    )
    parser.add_argument(
        "--scenario-seed",
        type=lambda value: int(value, 0),
        default=0x2A6D365A,
        help="ROM RNG seed used by --restart-character (decimal or 0x-prefixed)",
    )
    parser.add_argument(
        "--scenario-frame-phase",
        type=lambda value: int(value, 0),
        default=0,
        help="VBlank phase used by --restart-character (decimal or 0x-prefixed)",
    )
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-damage", type=int)
    parser.add_argument("--max-damage-events", type=int)
    parser.add_argument("--max-lives-lost", type=int)
    parser.add_argument("--max-failed-pickups", type=int)
    parser.add_argument("--max-failed-ground-attack-starts", type=int)
    parser.add_argument("--max-weapon-air-attacks", type=int)
    parser.add_argument("--max-missed-back-exposures", type=int)
    parser.add_argument("--min-pickups", type=int)
    parser.add_argument("--min-enemy-damage", type=int)
    parser.add_argument("--min-forward-progress", type=int)
    parser.add_argument("--min-signal-sweep-jumps", type=int)
    parser.add_argument("--min-jack-armed-ground-attacks", type=int)
    parser.add_argument("--min-jack-armed-jumps", type=int)
    parser.add_argument("--min-jack-throw-counters", type=int)
    parser.add_argument("--min-suplexes", type=int)
    parser.add_argument("--max-invalid-grab-attacks", type=int)
    parser.add_argument("--min-enemy-grab-escape-jumps", type=int)
    parser.add_argument("--min-enemy-grab-counter-throws", type=int)
    parser.add_argument("--max-missed-enemy-grab-escapes", type=int)
    parser.add_argument("--max-defeated-enemy-attacks", type=int)
    parser.add_argument("--max-defeated-enemy-pursuit", type=int)
    parser.add_argument("--max-unreachable-enemy-stalls", type=int)
    parser.add_argument("--max-loot-under-threat", type=int)
    parser.add_argument("--max-boss-progress", type=int)
    parser.add_argument("--max-boss-stalls", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from .app import _ensure_megadrive_remote_on_path

    _ensure_megadrive_remote_on_path()
    from megadrive_remote import MegaDriveClient

    criteria = EvaluationCriteria(
        max_damage=args.max_damage,
        max_damage_events=args.max_damage_events,
        max_lives_lost=args.max_lives_lost,
        max_failed_pickups=args.max_failed_pickups,
        max_failed_ground_attack_starts=args.max_failed_ground_attack_starts,
        max_weapon_air_attacks=args.max_weapon_air_attacks,
        max_missed_back_exposures=args.max_missed_back_exposures,
        min_pickups=args.min_pickups,
        min_enemy_damage=args.min_enemy_damage,
        min_forward_progress=args.min_forward_progress,
        min_signal_sweep_jumps=args.min_signal_sweep_jumps,
        min_jack_armed_ground_attacks=args.min_jack_armed_ground_attacks,
        min_jack_armed_jumps=args.min_jack_armed_jumps,
        min_jack_throw_counters=args.min_jack_throw_counters,
        min_suplexes=args.min_suplexes,
        max_invalid_grab_attacks=args.max_invalid_grab_attacks,
        min_enemy_grab_escape_jumps=args.min_enemy_grab_escape_jumps,
        min_enemy_grab_counter_throws=args.min_enemy_grab_counter_throws,
        max_missed_enemy_grab_escapes=args.max_missed_enemy_grab_escapes,
        max_defeated_enemy_attacks=args.max_defeated_enemy_attacks,
        max_defeated_enemy_pursuit=args.max_defeated_enemy_pursuit,
        max_unreachable_enemy_stalls=args.max_unreachable_enemy_stalls,
        max_loot_under_threat=args.max_loot_under_threat,
        max_boss_progress=args.max_boss_progress,
        max_boss_stalls=args.max_boss_stalls,
    )
    trace_stream: TextIO | None = None
    try:
        trace_sink = None
        if args.trace is not None:
            trace_stream = args.trace.open("w", encoding="utf-8")
            trace_sink = JsonLinesTrace(trace_stream)
        with MegaDriveClient(args.host, args.port) as client:
            client.ping()
            scenario = None
            if args.restart_character is not None:
                from .scenarios import reach_round1_start

                scenario = reach_round1_start(
                    client,
                    args.restart_character,
                    rng_seed=args.scenario_seed,
                    frame_phase=args.scenario_frame_phase,
                )
            report = LockstepEvaluator(
                client,
                player_index=args.player,
                decisions=args.decisions,
                step_frames=args.step_frames,
                face_frames=args.face_frames,
                step_timeout_ms=args.step_timeout_ms,
                criteria=criteria,
                trace_sink=trace_sink,
            ).run()
        report_payload = report.to_dict()
        if scenario is not None:
            report_payload["scenario"] = scenario
        report_json = json.dumps(report_payload, indent=2, sort_keys=True)
        if args.report is not None:
            args.report.write_text(report_json + "\n", encoding="utf-8")
        print(report_json)
        return 0 if report.passed else 2
    finally:
        if trace_stream is not None:
            trace_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
