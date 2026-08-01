"""Pure agent policy: GameSnapshot → per-player button masks.

Standard controls only (see ``controls.py``). No host ``--altControls``.

Movement uses a latched **walk-to-(x,y)** state (``walk.py``): D-pad directions
stay held until the world-space goal is reached or passed through.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..phases import CombatPhase, is_dangerous, is_punishable
from ..state import GameSnapshot, PlayerSnapshot
from ..world_map import MapEntity
from . import combat, coop, enemies as enemy_ai, grabs, pressure, stage
from .characters import profile_for
from .controls import Intent, mask_from_intent
from .grabs import GrabMemory
from .walk import WalkState, blend_walk_with_actions


# game_state values where live combat/progression input makes sense.
_INGAME_STATES = frozenset({0x14, 0x16})
_POLICE_THRESHOLD = 4.5
# How far ahead (world X) to aim when progressing an empty screen.
_PROGRESS_LEAD = 160.0


@dataclass
class AgentConfig:
    """Which seats the AI currently drives."""

    p1_enabled: bool = False
    p2_enabled: bool = False
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
    p1_phase: int = 0
    p2_phase: int = 0
    p1_last_note: str = ""
    p2_last_note: str = ""
    p1_attack_cd: int = 0
    p2_attack_cd: int = 0
    p1_grab: GrabMemory = field(default_factory=GrabMemory)
    p2_grab: GrabMemory = field(default_factory=GrabMemory)
    p1_walk: WalkState = field(default_factory=WalkState)
    p2_walk: WalkState = field(default_factory=WalkState)

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

    def grab_mem(self, player_index: int) -> GrabMemory:
        return self.p1_grab if player_index == 1 else self.p2_grab

    def walk(self, player_index: int) -> WalkState:
        return self.p1_walk if player_index == 1 else self.p2_walk

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
    steady: bool = False


def _player_entity(snapshot: GameSnapshot, index: int) -> MapEntity | None:
    slot = f"P{index}"
    for entity in snapshot.world_map.entities:
        if entity.kind == "player" and entity.slot.upper() == slot:
            return entity
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
    if memory is None:
        memory = AgentState()
    memory.tick += 1

    if not config.any_enabled() or not snapshot.connected:
        return AgentDecision(0, 0, steady=True)

    if snapshot.paused or snapshot.police_special_active:
        memory.p1_walk.clear()
        memory.p2_walk.clear()
        return AgentDecision(0, 0, p1_note="steady", p2_note="steady", steady=True)

    if snapshot.game_state not in _INGAME_STATES:
        memory.p1_walk.clear()
        memory.p2_walk.clear()
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
    walk = memory.walk(player_index)
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

    # --- Mr. X dialog ---
    if stage.is_mr_x_offer(snapshot):
        walk.clear()
        return _mr_x_intent(snapshot, player_index, memory)

    if me is None or not player_snap.is_playable:
        walk.clear()
        return Intent(note="not playable")

    if me.is_hurt:
        walk.clear()
        return Intent(note="hurt")

    press = pressure.compute_pressure(snapshot, player_snap, me)
    if pressure.should_call_police(
        press,
        player_snap.specials,
        threshold=config.police_threshold,
        level_index=snapshot.level_index,
    ):
        walk.clear()
        return Intent(special=True, note=f"police ({press.reason})")

    # --- Grab / weapon hold ---
    gctx = grabs.context_from_player(me)
    gmem = memory.grab_mem(player_index)
    foe_near = combat.nearest_foe(me, snapshot.world_map.entities)
    held_intent = grabs.decide_held(
        me,
        gctx,
        gmem,
        tick=memory.tick,
        foe=foe_near,
        progress_right=advice.progress_right,
        crowd=press.enemy_count,
    )
    if held_intent is not None:
        walk.clear()
        return held_intent

    if both_agents and coop.partner_throw_opportunity(me, coop_ctx.partner):
        walk.clear()
        return Intent(jump=True, attack=True, note="2P air assist")

    low_hp = (player_snap.health_percent or 100.0) < 40.0

    # --- Pickups ---
    allow_hp = coop.should_take_health_pickup(player_snap, coop_ctx)
    allow_star = coop.should_take_special_or_life(player_snap, coop_ctx)
    item = combat.select_pickup(
        me,
        snapshot.world_map.entities,
        allow_health=allow_hp,
        allow_special_life=allow_star,
        allow_weapons=True,
        already_holding_weapon=me.is_holding_weapon,
    )
    if item is not None:
        close = abs(item.world_x - me.world_x) < 22 and abs(item.world_y - me.world_y) < 14
        if close:
            walk.clear()
            return Intent(attack=True, note=f"loot {item.label}")
        return _walk_toward(
            walk,
            me,
            goal_x=float(item.world_x),
            goal_y=float(item.world_y),
            reason=f"loot {item.label}",
            snapshot=snapshot,
            advice=advice,
        )

    # --- Combat ---
    target = combat.select_target(
        me,
        snapshot.world_map.entities,
        profile,
        prefer_forward=advice.progress_right,
        my_seat=player_index,
    )
    if target is not None:
        dx, dy, in_range, plan = combat.approach_vector(
            me, target, profile, low_health=low_hp
        )
        phase = target.entity.combat_phase
        phase_name = phase.name.lower()
        tag = target.entity.phase_tag
        cd = memory.attack_cd(player_index)

        # Projectile: walk to a sidestep point, not into the projectile.
        if target.entity.kind == "projectile" or plan.kind == enemy_ai.ThreatKind.PROJECTILE:
            evade_x = me.world_x - 40 if dx > 0 else me.world_x + 40
            evade_y = me.world_y + (18 if (me.world_x + me.world_y) % 2 == 0 else -18)
            return _walk_toward(
                walk,
                me,
                goal_x=evade_x,
                goal_y=evade_y,
                reason=f"dodge {target.entity.label}",
                snapshot=snapshot,
                advice=advice,
            )

        if phase == CombatPhase.GRABBED and not me.is_grabbing:
            walk.clear()
            lead = _PROGRESS_LEAD if advice.progress_right else -_PROGRESS_LEAD
            return _walk_toward(
                walk,
                me,
                goal_x=float(me.world_x) + lead,
                goal_y=float(me.world_y),
                reason=f"skip held {target.entity.label}",
                snapshot=snapshot,
                advice=advice,
            )

        # Desired stand point for approach (world space).
        stand_x, stand_y = _stand_point(me, target, profile, low_health=low_hp)

        if in_range and not me.is_hurt:
            walk.clear()
            attack = False
            jump = False
            rear = False
            note = f"{target.entity.label} [{tag}]"
            if cd == 0:
                mix = enemy_ai.attack_mix(
                    plan,
                    profile,
                    tick=memory.tick + player_index * 3,
                    in_range=True,
                    crowd=press.enemy_count,
                    phase_name=phase_name,
                )
                if is_punishable(phase) and phase != CombatPhase.GRABBED:
                    attack = True
                    note = f"punish {target.entity.label} [{tag}]"
                    memory.set_attack_cd(player_index, 2)
                elif mix == "grab_walk" or (
                    grabs.want_grab_approach(
                        me,
                        target.entity,
                        grab_bias=max(plan.grab_bias, profile.grab_bias),
                    )
                    and phase_name == "normal"
                ):
                    # Walk a hair into them for collision grab.
                    return _walk_toward(
                        walk,
                        me,
                        goal_x=float(target.entity.world_x),
                        goal_y=float(target.entity.world_y),
                        reason=f"grab setup {target.entity.label}",
                        snapshot=snapshot,
                        advice=advice,
                        eps_x=6.0,
                        eps_y=6.0,
                    )
                elif mix == "rear":
                    rear = True
                    note = f"rear {target.entity.label} [{tag}]"
                    memory.set_attack_cd(player_index, 4)
                elif mix == "jump":
                    jump = True
                    attack = True
                    note = f"jump {target.entity.label} [{tag}]"
                    memory.set_attack_cd(player_index, 5)
                else:
                    attack = True
                    note = f"punch {target.entity.label} [{tag}]"
                    memory.set_attack_cd(player_index, 3)
            return Intent(attack=attack, jump=jump, rear_attack=rear, note=note)

        # Out of range: latch walk to stand point; optional face buttons later.
        hunters = combat.count_hunters(snapshot.world_map.entities, player_index)
        if is_dangerous(phase) and plan.sidestep:
            # Sidestep goal: same X-ish, different lane.
            stand_y = float(me.world_y) + (20 if dy >= 0 else -20)
            stand_x = float(me.world_x) + (-30 if dx > 0 else 30)
            reason = f"evade {target.entity.label} [{tag}]"
        elif is_punishable(phase):
            stand_x = float(target.entity.world_x)
            stand_y = float(target.entity.world_y)
            reason = f"chase punish {target.entity.label} [{tag}]"
        elif press.enemy_count >= 3 or hunters >= 2:
            px, py = combat.peril_vector(me, snapshot.world_map.entities)
            stand_x = float(me.world_x) + px * 40
            stand_y = float(me.world_y) + py * 24
            reason = f"space {target.entity.label}"
        else:
            reason = f"close {target.entity.label} [{tag}]"

        return _walk_toward(
            walk,
            me,
            goal_x=stand_x,
            goal_y=stand_y,
            reason=reason,
            snapshot=snapshot,
            advice=advice,
        )

    # --- Progress ---
    lead = _PROGRESS_LEAD if advice.progress_right else -_PROGRESS_LEAD
    goal_x = float(me.world_x) + lead
    goal_y = float(me.world_y)
    if advice.avoid_holes or advice.elevator:
        mid = 0x40 if snapshot.level_index != 6 else 0x50
        goal_y = float(mid)
    return _walk_toward(
        walk,
        me,
        goal_x=goal_x,
        goal_y=goal_y,
        reason=f"progress ({advice.note})",
        snapshot=snapshot,
        advice=advice,
        eps_x=24.0,  # refresh progress goal as we move
    )


def _stand_point(
    me: MapEntity,
    target: combat.TargetChoice,
    profile,
    *,
    low_health: bool,
) -> tuple[float, float]:
    """World-space point to stand for a good strike."""

    foe = target.entity
    side = -1.0 if (foe.world_x - me.world_x) > 0 else 1.0
    offset = profile.caution_range if low_health else profile.approach_offset
    return float(foe.world_x) + side * offset, float(foe.world_y)


def _walk_toward(
    walk: WalkState,
    me: MapEntity,
    *,
    goal_x: float,
    goal_y: float,
    reason: str,
    snapshot: GameSnapshot,
    advice: stage.StageAdvice,
    eps_x: float = 10.0,
    eps_y: float = 8.0,
    attack: bool = False,
    jump: bool = False,
    rear: bool = False,
) -> Intent:
    """Set/refresh walk goal and return held-direction intent until arrival."""

    # Nudge goal out of floor holes when relevant.
    if advice.avoid_holes and snapshot.floor_holes:
        goal_x, goal_y = _nudge_goal_from_holes(
            goal_x, goal_y, snapshot.floor_holes, level_index=snapshot.level_index
        )

    walk.set_goal(
        me,
        goal_x,
        goal_y,
        reason=reason,
        eps_x=eps_x,
        eps_y=eps_y,
    )
    intent = walk.step(me)
    if intent is None:
        return Intent(note=f"walk idle ({reason})")

    # Hole steer on latched dirs (may zero one axis without flipping every tick).
    intent = _apply_stage_geometry(intent, me, snapshot, advice)
    # If hole steer flipped a direction, re-lock walk dirs to match.
    if walk.active:
        new_dx = (-1 if intent.left else 1 if intent.right else 0)
        new_dy = (-1 if intent.up else 1 if intent.down else 0)
        if new_dx != walk.dir_x or new_dy != walk.dir_y:
            walk.dir_x = new_dx
            walk.dir_y = new_dy

    if attack or jump or rear:
        return blend_walk_with_actions(
            intent, attack=attack, jump=jump, rear_attack=rear
        )
    return intent


def _nudge_goal_from_holes(
    goal_x: float,
    goal_y: float,
    holes: tuple,
    *,
    level_index: int,
) -> tuple[float, float]:
    from ..hazards import FloorHole

    gx, gy = goal_x, goal_y
    for _ in range(4):
        hit: FloorHole | None = stage.point_in_hole(gx, gy, holes, margin=8.0)
        if hit is None:
            break
        # Push goal toward nearest horizontal edge of the hole.
        mid = (hit.world_x + hit.world_x_end) / 2.0
        gx = hit.world_x - 12.0 if gx >= mid else hit.world_x_end + 12.0
        mid_y = (hit.lane_y + hit.lane_y_end) / 2.0
        gy = hit.lane_y - 8.0 if gy >= mid_y else hit.lane_y_end + 8.0
    return gx, gy


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
    flags = snapshot.raw.get(f"p{player_index}_obj59", None)
    choice_active = True
    choice_bit = None
    if flags is not None:
        choice_active = bool(flags & 0x10)
        choice_bit = flags
        if not choice_active:
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
