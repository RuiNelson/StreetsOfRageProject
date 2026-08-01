"""Pure agent policy: GameSnapshot → per-player button masks.

Standard controls only (see ``controls.py``). No host ``--altControls``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..state import GameSnapshot, PlayerSnapshot
from ..world_map import MapEntity
from . import combat, coop, pressure, stage
from .characters import profile_for
from .controls import Intent, mask_from_intent


# game_state values where live combat/progression input makes sense.
_INGAME_STATES = frozenset({0x14, 0x16})
# Pressure threshold for police special (see pressure.py).
_POLICE_THRESHOLD = 4.5


@dataclass
class AgentConfig:
    """Which seats the AI currently drives."""

    p1_enabled: bool = False
    p2_enabled: bool = False
    # Hold frames when applying input (standard ~2 frames @ 60 Hz).
    hold_frames: int = 2
    police_threshold: float = _POLICE_THRESHOLD

    def enabled_for(self, player_index: int) -> bool:
        if player_index == 1:
            return self.p1_enabled
        if player_index == 2:
            return self.p2_enabled
        return False

    def any_enabled(self) -> bool:
        return self.p1_enabled or self.p2_enabled


@dataclass
class AgentState:
    """Per-session mutable policy memory (not ROM state)."""

    tick: int = 0
    # Simple phase counters for multi-tick sequences (Mr. X, rear attack).
    p1_phase: int = 0
    p2_phase: int = 0
    p1_last_note: str = ""
    p2_last_note: str = ""
    # Stagger attack so B is not held every frame (edge-friendly combos).
    p1_attack_cd: int = 0
    p2_attack_cd: int = 0

    def phase(self, player_index: int) -> int:
        return self.p1_phase if player_index == 1 else self.p2_phase

    def set_phase(self, player_index: int, value: int) -> None:
        if player_index == 1:
            self.p1_phase = value
        else:
            self.p2_phase = value

    def attack_cd(self, player_index: int) -> int:
        return self.p1_attack_cd if player_index == 1 else self.p2_attack_cd

    def set_attack_cd(self, player_index: int, value: int) -> None:
        if player_index == 1:
            self.p1_attack_cd = value
        else:
            self.p2_attack_cd = value

    def set_note(self, player_index: int, note: str) -> None:
        if player_index == 1:
            self.p1_last_note = note
        else:
            self.p2_last_note = note


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """One tick of AI output for both seats."""

    p1_mask: int
    p2_mask: int
    p1_note: str = ""
    p2_note: str = ""
    steady: bool = False  # paused / police special — no input


def _player_entity(snapshot: GameSnapshot, index: int) -> MapEntity | None:
    slot = f"P{index}"
    for entity in snapshot.world_map.entities:
        if entity.kind == "player" and entity.slot == slot:
            return entity
    # Fallback: symbol match.
    for entity in snapshot.world_map.entities:
        if entity.kind == "player" and entity.symbol == str(index):
            return entity
    return None


def _other_index(index: int) -> int:
    return 2 if index == 1 else 1


def decide_actions(
    snapshot: GameSnapshot,
    config: AgentConfig,
    memory: AgentState | None = None,
) -> AgentDecision:
    """Compute button masks for the current snapshot.

    Pure with respect to the game: only ``memory`` is mutated for timing.
    """

    if memory is None:
        memory = AgentState()
    memory.tick += 1

    if not config.any_enabled() or not snapshot.connected:
        return AgentDecision(0, 0, steady=True)

    # Steady: do not fight the pause/special scripts.
    if snapshot.paused or snapshot.police_special_active:
        return AgentDecision(0, 0, p1_note="steady", p2_note="steady", steady=True)

    # Outside gameplay: leave menus to the human (agents only play rounds).
    if snapshot.game_state not in _INGAME_STATES:
        return AgentDecision(0, 0, p1_note="menu idle", p2_note="menu idle", steady=True)

    p1_mask = 0
    p2_mask = 0
    p1_note = ""
    p2_note = ""

    both = config.p1_enabled and config.p2_enabled

    if config.p1_enabled and (snapshot.p1.is_playable or snapshot.p1.mode_active):
        intent = _decide_one(
            snapshot,
            player_index=1,
            player_snap=snapshot.p1,
            config=config,
            memory=memory,
            both_agents=both,
        )
        p1_mask = mask_from_intent(intent)
        p1_note = intent.note
        memory.set_note(1, intent.note)

    if config.p2_enabled and (snapshot.p2.is_playable or snapshot.p2.mode_active):
        intent = _decide_one(
            snapshot,
            player_index=2,
            player_snap=snapshot.p2,
            config=config,
            memory=memory,
            both_agents=both,
        )
        p2_mask = mask_from_intent(intent)
        p2_note = intent.note
        memory.set_note(2, intent.note)

    # Decay attack cooldowns.
    for idx in (1, 2):
        cd = memory.attack_cd(idx)
        if cd > 0:
            memory.set_attack_cd(idx, cd - 1)

    return AgentDecision(
        p1_mask=p1_mask,
        p2_mask=p2_mask,
        p1_note=p1_note,
        p2_note=p2_note,
    )


def _decide_one(
    snapshot: GameSnapshot,
    *,
    player_index: int,
    player_snap: PlayerSnapshot,
    config: AgentConfig,
    memory: AgentState,
    both_agents: bool,
) -> Intent:
    me = _player_entity(snapshot, player_index)
    other_i = _other_index(player_index)
    partner = _player_entity(snapshot, other_i)
    partner_player = snapshot.players[other_i - 1]
    partner_snap: PlayerSnapshot | None = partner_player
    if not partner_player.mode_active and not partner_player.is_playable:
        partner = None
        partner_snap = None

    coop_ctx = coop.build_coop(
        me=me,
        me_snap=player_snap,
        partner=partner,
        partner_snap=partner_snap,
        both_agents=both_agents,
    )
    advice = stage.stage_advice(snapshot.level_index)
    profile = profile_for(player_snap.character_id)

    # --- Mr. X dialog: always choose NO (refuse) ---
    if stage.is_mr_x_offer(snapshot):
        return _mr_x_intent(snapshot, player_index, memory)

    if me is None or not player_snap.is_playable:
        # Not spawned (continue screen etc.) — face button / start left to human.
        return Intent(note="not playable")

    # --- Police special under pressure ---
    press = pressure.compute_pressure(snapshot, player_snap, me)
    if pressure.should_call_police(
        press,
        player_snap.specials,
        threshold=config.police_threshold,
        level_index=snapshot.level_index,
    ):
        return Intent(special=True, note=f"police ({press.reason})")

    # --- 2P mid-air assist ---
    if both_agents and coop.partner_throw_opportunity(me, coop_ctx.partner):
        # Jump under partner + attack chord.
        return Intent(jump=True, attack=True, note="2P air assist")

    low_hp = (player_snap.health_percent or 100.0) < 40.0

    # --- Pickups / weapons ---
    allow_hp = coop.should_take_health_pickup(player_snap, coop_ctx)
    allow_star = coop.should_take_special_or_life(player_snap, coop_ctx)
    item = combat.select_pickup(
        me,
        snapshot.world_map.entities,
        allow_health=allow_hp,
        allow_special_life=allow_star,
        allow_weapons=True,
    )
    if item is not None:
        dx = item.map_x - me.map_x
        dy = item.map_y - me.map_y
        close = abs(dx) < 22 and abs(dy) < 14
        intent = Intent(
            left=dx < -4,
            right=dx > 4,
            up=dy < -profile.lane_align,
            down=dy > profile.lane_align,
            attack=close,  # B near item → pickup priority in ROM
            note=f"loot {item.label}",
        )
        return _apply_stage_geometry(intent, me, snapshot, advice)

    # --- Combat target ---
    target = combat.select_target(
        me,
        snapshot.world_map.entities,
        profile,
        prefer_forward=advice.progress_right,
    )
    if target is not None:
        dx, dy, in_range = combat.approach_vector(
            me, target, profile, low_health=low_hp
        )
        # Crowd relief when surrounded and not yet in a clean strike.
        if not in_range and press.enemy_count >= 3:
            px, py = combat.peril_vector(me, snapshot.world_map.entities)
            if px != 0:
                dx = px
            if py != 0 and abs(dy) < 0.5:
                dy = py

        attack = False
        jump = False
        rear = False
        cd = memory.attack_cd(player_index)
        if in_range and cd == 0:
            # Mix attacks by character bias and tick.
            phase = memory.tick + player_index * 3
            roll = (phase % 100) / 100.0
            if press.enemy_count >= 3 and roll < profile.rear_attack_bias:
                rear = True
                memory.set_attack_cd(player_index, 4)
            elif roll < profile.jump_attack_bias:
                jump = True
                attack = True
                memory.set_attack_cd(player_index, 5)
            else:
                attack = True
                memory.set_attack_cd(player_index, 3)

        intent = Intent(
            left=dx < 0,
            right=dx > 0,
            up=dy < 0,
            down=dy > 0,
            attack=attack,
            jump=jump,
            rear_attack=rear,
            note=f"fight {target.entity.label}",
        )
        return _apply_stage_geometry(intent, me, snapshot, advice)

    # --- No enemies: progress the stage ---
    dx = 1.0 if advice.progress_right else -1.0
    dy = 0.0
    # Prefer mid-lane for safety on hole stages.
    if advice.avoid_holes or advice.elevator:
        mid = 0x40 if snapshot.level_index != 6 else 0x50
        if me.world_y < mid - 12:
            dy = 1.0
        elif me.world_y > mid + 12:
            dy = -1.0

    intent = Intent(
        left=dx < 0,
        right=dx > 0,
        up=dy < 0,
        down=dy > 0,
        note=f"progress ({advice.note})",
    )
    return _apply_stage_geometry(intent, me, snapshot, advice)


def _apply_stage_geometry(
    intent: Intent,
    me: MapEntity,
    snapshot: GameSnapshot,
    advice: stage.StageAdvice,
) -> Intent:
    if not advice.avoid_holes and not snapshot.floor_holes:
        return intent

    desired_dx = (-1.0 if intent.left else 1.0 if intent.right else 0.0)
    desired_dy = (-1.0 if intent.up else 1.0 if intent.down else 0.0)
    dx, dy = stage.steer_away_from_holes(
        float(me.world_x),
        float(me.world_y),
        desired_dx,
        desired_dy,
        snapshot.floor_holes,
        level_index=snapshot.level_index,
    )
    return Intent(
        left=dx < 0,
        right=dx > 0,
        up=dy < 0,
        down=dy > 0,
        attack=intent.attack,
        jump=intent.jump,
        special=intent.special,
        rear_attack=intent.rear_attack,
        confirm=intent.confirm,
        note=intent.note + (" [hole]" if (dx, dy) != (desired_dx, desired_dy) else ""),
    )


def _mr_x_intent(
    snapshot: GameSnapshot,
    player_index: int,
    memory: AgentState,
) -> Intent:
    """Always answer NO (refuse Mr. X) then confirm.

    Selection uses Left/Right; face button confirms. We pulse RIGHT for a few
    ticks, then press attack to confirm. Bit flags from RAM (when present)
    short-circuit the pulse.
    """

    flags = snapshot.raw.get(f"p{player_index}_obj59", None)
    choice_active = True
    choice_bit = None
    if flags is not None:
        choice_active = bool(flags & 0x10)  # bit 4
        choice_bit = flags
        if not choice_active:
            # Offer machine running but this seat is not choosing yet.
            return Intent(note="mr.x wait")

    action = stage.mr_x_choice_intent(
        _player_entity(snapshot, player_index),
        choice_bit=choice_bit,
        choice_active=choice_active,
    )
    phase = memory.phase(player_index)
    if action == "select_no" or (action is None and phase < 4):
        memory.set_phase(player_index, phase + 1)
        return Intent(right=True, note="mr.x select NO")
    memory.set_phase(player_index, 0)
    return Intent(confirm=True, note="mr.x confirm NO")
