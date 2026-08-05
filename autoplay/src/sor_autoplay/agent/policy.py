"""Pure agent policy: GameSnapshot → per-player button masks.

Standard controls only (see ``controls.py``). No host ``--altControls``.

Pipeline per seat (see ``context.py`` / ``skills.py``)::

    mode → exclusive skills → crossover plan → police → hold skill → free

Movement uses a latched **walk-to-(x,y)** state (``walk.py``): D-pad directions
stay held until the world-space goal is reached or passed through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace as dc_replace

from ..phases import CombatPhase, is_dangerous, is_punishable
from ..state import GameSnapshot, PlayerSnapshot
from ..world_map import MapEntity
from . import (
    bosses,
    combat,
    coop,
    enemies as enemy_ai,
    navigation,
    pressure,
    stage,
)
from .arbiter import GoalKind, solve_goal
from .context import DecisionContext, PlayerMode, SeatMemory, build_decision_context
from .controls import Intent, mask_from_intent
from .expert import DEFAULT_COMBAT_EXPERT
from .jump_kick import JumpKickPlan
from .knowledge import Relation
from .navigation import NavMemory
from .skills import (
    try_crossover_suplex,
    try_hold_resolve,
    try_start_mode_skill,
)
from .walk import WalkState, blend_walk_with_actions


# game_state values where live combat/progression input makes sense.
_INGAME_STATES = frozenset({0x14, 0x16})
_POLICE_THRESHOLD = 4.5
# How far ahead (world X) to aim when progressing an empty screen.
_PROGRESS_LEAD = 160.0


def _routing_holes(
    snapshot: GameSnapshot,
    advice: stage.StageAdvice,
) -> tuple:
    """Terrain solids the navigator must detour around.

    - Pit holes (class 0) when stage advice asks (stage 4).
    - Collision barriers (class ≥ 2): factory machine walls, etc. Always on
      (except elevator, which never populates ``floor_barriers``).
    - Type-``$42`` press object AABBs as a crush-zone supplement.

    Live stage-6 sampling: class-2 columns block RIGHT on the upper lanes while
    the crusher object sits at a different Y; barriers are the path blocker.
    """

    from ..hazards import FloorHole

    holes: list[FloorHole] = []
    if advice.avoid_holes:
        holes.extend(snapshot.floor_holes)
    holes.extend(snapshot.floor_barriers)
    holes.extend(stage.press_solid_holes(snapshot.world_map.entities))
    return tuple(holes)


@dataclass
class AgentConfig:
    """Which seats the AI currently drives."""

    p1_enabled: bool = False
    p2_enabled: bool = False
    hold_frames: int = 2
    police_threshold: float = _POLICE_THRESHOLD
    # Diagnostic: suppress every police-special spend. The special is worth 10
    # damage to each living boss and is normally correct against the pair, so
    # this is for isolating melee competence in measurement, not doctrine.
    allow_police_special: bool = True

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
    """Per-session mutable policy memory (not ROM state).

    Per-seat state lives in :class:`SeatMemory`. Attribute aliases
    (``p1_walk``, ``p1_nav``, …) remain for tests and the HUD.
    """

    tick: int = 0
    p1: SeatMemory = field(default_factory=SeatMemory)
    p2: SeatMemory = field(default_factory=SeatMemory)

    def seat(self, player_index: int) -> SeatMemory:
        return self.p1 if player_index == 1 else self.p2

    # --- Backward-compatible accessors (tests / HUD) ---

    @property
    def p1_phase(self) -> int:
        return self.p1.phase

    @p1_phase.setter
    def p1_phase(self, value: int) -> None:
        self.p1.phase = value

    @property
    def p2_phase(self) -> int:
        return self.p2.phase

    @p2_phase.setter
    def p2_phase(self, value: int) -> None:
        self.p2.phase = value

    @property
    def p1_last_note(self) -> str:
        return self.p1.last_note

    @p1_last_note.setter
    def p1_last_note(self, value: str) -> None:
        self.p1.last_note = value

    @property
    def p2_last_note(self) -> str:
        return self.p2.last_note

    @p2_last_note.setter
    def p2_last_note(self, value: str) -> None:
        self.p2.last_note = value

    @property
    def p1_walk(self) -> WalkState:
        return self.p1.walk

    @property
    def p2_walk(self) -> WalkState:
        return self.p2.walk

    @property
    def p1_nav(self) -> NavMemory:
        return self.p1.nav

    @property
    def p2_nav(self) -> NavMemory:
        return self.p2.nav

    def phase(self, player_index: int) -> int:
        return self.seat(player_index).phase

    def set_phase(self, player_index: int, value: int) -> None:
        self.seat(player_index).phase = value

    def attack_cd(self, player_index: int) -> int:
        return self.seat(player_index).attack_cd

    def set_attack_cd(self, player_index: int, value: int) -> None:
        self.seat(player_index).attack_cd = value

    def grab_mem(self, player_index: int):
        return self.seat(player_index).grab

    def enemy_grab_escape_mem(self, player_index: int):
        return self.seat(player_index).enemy_grab_escape

    def walk(self, player_index: int) -> WalkState:
        return self.seat(player_index).walk

    def nav(self, player_index: int) -> NavMemory:
        return self.seat(player_index).nav

    def planner(self, player_index: int):
        return self.seat(player_index).planner

    def clear_planners(self) -> None:
        self.p1.planner.reset()
        self.p2.planner.reset()
        assert self.p1.commitment is not None and self.p2.commitment is not None
        self.p1.commitment.clear()
        self.p2.commitment.clear()

    def clear_nav(self) -> None:
        self.p1.nav.clear_all()
        self.p2.nav.clear_all()

    def goal(self, player_index: int):
        return self.seat(player_index).goal

    def clear_goals(self) -> None:
        self.p1.goal.clear()
        self.p2.goal.clear()

    def set_note(self, player_index: int, note: str) -> None:
        self.seat(player_index).last_note = note

    def clear_tactical(self) -> None:
        self.p1.clear_tactical()
        self.p2.clear_tactical()


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
        memory.clear_tactical()
        return AgentDecision(0, 0, steady=True)

    if snapshot.paused or snapshot.police_special_active:
        memory.clear_tactical()
        return AgentDecision(0, 0, p1_note="steady", p2_note="steady", steady=True)

    if snapshot.game_state not in _INGAME_STATES:
        memory.clear_tactical()
        return AgentDecision(0, 0, p1_note="menu idle", p2_note="menu idle", steady=True)

    p1_mask = 0
    p2_mask = 0
    p1_note = ""
    p2_note = ""
    both = config.p1_enabled and config.p2_enabled

    if config.p1_enabled and _seat_drivable(snapshot.p1):
        intent = _decide_one(
            snapshot,
            player_index=1,
            player_snap=snapshot.p1,
            config=config,
            memory=memory,
            both_agents=both,
        )
        # Hard final gate: no path may emit B/B+C into a live partner.
        intent = coop.guard_attack_intent(
            _player_entity(snapshot, 1),
            _player_entity(snapshot, 2)
            if _seat_drivable(snapshot.p2)
            else None,
            intent,
            both_agents=both,
        )
        p1_mask = mask_from_intent(intent)
        p1_note = intent.note
        memory.set_note(1, intent.note)

    if config.p2_enabled and _seat_drivable(snapshot.p2):
        intent = _decide_one(
            snapshot,
            player_index=2,
            player_snap=snapshot.p2,
            config=config,
            memory=memory,
            both_agents=both,
        )
        intent = coop.guard_attack_intent(
            _player_entity(snapshot, 2),
            _player_entity(snapshot, 1)
            if _seat_drivable(snapshot.p1)
            else None,
            intent,
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
    """Mode → commitment skills → police → free tactical path."""

    other_i = _other_index(player_index)
    partner = _player_entity(snapshot, other_i)
    partner_player = snapshot.players[other_i - 1]
    partner_snap: PlayerSnapshot | None = partner_player
    if not partner_player.mode_active and not partner_player.is_playable:
        partner = None
        partner_snap = None

    ctx = build_decision_context(
        snapshot,
        player_index=player_index,
        player_snap=player_snap,
        both_agents=both_agents,
        police_threshold=config.police_threshold,
        tick=memory.tick,
        seat=memory.seat(player_index),
        me=_player_entity(snapshot, player_index),
        partner=partner,
        partner_snap=partner_snap,
        is_mr_x=stage.is_mr_x_offer(snapshot),
    )

    # --- Exclusive modes (dialog / continue / not playable / enemy-held / hurt) ---
    if ctx.mode == PlayerMode.DIALOG:
        ctx.walk.clear()
        ctx.planner.reset()
        ctx.goal_memory.clear()
        assert ctx.seat.commitment is not None
        ctx.seat.commitment.clear(ctx)
        return _mr_x_intent(snapshot, player_index, memory)

    if ctx.mode == PlayerMode.CONTINUE_UI:
        ctx.walk.clear()
        ctx.planner.reset()
        ctx.goal_memory.clear()
        assert ctx.seat.commitment is not None
        ctx.seat.commitment.clear(ctx)
        return _continue_ui_intent(player_snap)

    if ctx.mode == PlayerMode.NOT_PLAYABLE:
        ctx.walk.clear()
        ctx.planner.reset()
        ctx.goal_memory.clear()
        assert ctx.seat.commitment is not None
        ctx.seat.commitment.clear(ctx)
        return Intent(note="not playable")

    mode_intent = try_start_mode_skill(ctx)
    if mode_intent is not None:
        return mode_intent

    # Live player from here on.
    assert ctx.me is not None
    ctx.ensure_perception()
    assert ctx.graph is not None and ctx.press is not None

    # --- Crossover-suplex commitment (before police / ordinary hold) ---
    planned = try_crossover_suplex(ctx)
    if planned is not None:
        return planned

    if config.allow_police_special and pressure.should_call_police(
        ctx.press,
        player_snap.specials,
        threshold=config.police_threshold,
        level_index=snapshot.level_index,
    ) and combat.player_can_start_ground_action(ctx.me):
        ctx.walk.clear()
        assert ctx.seat.commitment is not None
        ctx.seat.commitment.clear(ctx)
        return Intent(special=True, note=f"police ({ctx.press.reason})")

    # --- Hold / weapon tree + closed grab animations ---
    held = try_hold_resolve(ctx)
    if held is not None:
        return held

    # Only when the partner is in a jump action family — never world_z
    # (standing elevation is always large and falsely enabled this forever).
    if both_agents and coop.partner_throw_opportunity(ctx.me, ctx.coop.partner):
        ctx.walk.clear()
        return Intent(jump=True, attack=True, note="2P air assist")

    return _decide_free(ctx)


def _decide_free(ctx: DecisionContext) -> Intent:
    """Grounded free tactical path: air, props, arbiter, combat, progress.

    Future migration steps lift more of this into skills; behavior is preserved
    from the pre-migration priority ladder.
    """

    me = ctx.me
    assert me is not None
    assert ctx.graph is not None and ctx.press is not None
    snapshot = ctx.snapshot
    walk = ctx.walk
    nav = ctx.nav
    profile = ctx.profile
    advice = ctx.advice
    coop_ctx = ctx.coop
    graph = ctx.graph
    press = ctx.press
    player_snap = ctx.player_snap
    player_index = ctx.player_index
    goal_memory = ctx.goal_memory
    low_hp = (player_snap.health_percent or 100.0) < 40.0

    # --- Airborne first (must beat loot/walk) ---
    # ROM state sequence is $10 launch -> $12 free flight -> $16 air attack ->
    # $14 landing.  B is accepted in $12, not in $10; pressing it during $14
    # starts an unrelated ground action on landing.
    # When a jump-kick plan is armed, hold its launch direction and delay B
    # until the solved free-flight frame (multi-enemy Z/X timing).
    if combat.player_airborne_action(me):
        walk.clear()
        jk = ctx.seat.jump_kick
        aim = combat.select_target(
            me,
            snapshot.world_map.entities,
            profile,
            prefer_forward=advice.progress_right,
            my_seat=player_index,
            graph=graph,
            preferred_slot=goal_memory.target_slot,
        )
        aim_e = aim.entity if aim is not None else None
        if aim_e is None:
            aim_e = combat.select_breakable(
                me,
                snapshot.world_map.entities,
                prefer_forward=advice.progress_right,
                graph=graph,
            )
        if jk.active:
            fl = jk.face_left
            fr = not jk.face_left
            hold_l = jk.hold_dir < 0
            hold_r = jk.hold_dir > 0
        elif aim_e is not None:
            fl, fr = combat.face_intent_dirs(me, aim_e)
            hold_l, hold_r = fl, fr
        else:
            fl = combat.player_facing_left(me)
            fr = not fl
            hold_l, hold_r = fl, fr

        if combat.player_jump_landing(me) or combat.player_jump_attacking(me):
            if combat.player_jump_landing(me):
                jk.clear()
            return Intent(
                left=hold_l or fl,
                right=hold_r or fr,
                note=(
                    f"air kick {aim_e.label if aim_e else ''}".strip()
                    if combat.player_jump_attacking(me)
                    else f"air land {aim_e.label if aim_e else 'follow'}".strip()
                ),
            )

        if combat.player_jump_starting(me):
            return Intent(
                left=hold_l or fl,
                right=hold_r or fr,
                note=f"air launch {aim_e.label if aim_e else 'follow'}".strip(),
            )

        # Free flight $12/$13: fire B on the solved schedule.
        # Agent decisions span multiple ROM frames (hold_frames / poll), so map
        # fine-grained free-flight frame indices onto decision delays:
        #   kick_free_frame ≤ 3 → B on first free-flight decision
        #   else               → wait one free-flight decision (mid-arc)
        if combat.player_jump_attack_ready(me):
            if jk.active:
                jk.free_frames_seen += 1
                delay = 0 if jk.kick_free_frame <= 3 else 1
                ready_to_kick = jk.free_frames_seen > delay
            else:
                ready_to_kick = True
            if ready_to_kick:
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=fl
                ):
                    return Intent(
                        left=hold_l or fl,
                        right=hold_r or fr,
                        note="air hold clear of ally",
                    )
                ctx.set_attack_cd(2)
                hit_n = jk.expected_hits if jk.active else 0
                jk.clear()
                return Intent(
                    left=hold_l or fl,
                    right=hold_r or fr,
                    attack=True,
                    note=(
                        f"air kick×{hit_n} {aim_e.label if aim_e else ''}".strip()
                        if hit_n
                        else f"air attack {aim_e.label if aim_e else ''}".strip()
                    ),
                )
            return Intent(
                left=hold_l or fl,
                right=hold_r or fr,
                note=(
                    f"air wait B@{jk.kick_free_frame} "
                    f"{aim_e.label if aim_e else ''}"
                ).strip(),
            )

        state = (
            "launch"
            if combat.player_jump_starting(me)
            else "kick"
            if combat.player_jump_attacking(me)
            else "land"
            if combat.player_jump_landing(me)
            else "air"
        )
        return Intent(
            left=hold_l or fl,
            right=hold_r or fr,
            note=f"air {state} {aim_e.label if aim_e else 'follow'}".strip(),
        )

    # Left the air without consuming the plan (interrupted / unexpected).
    if ctx.seat.jump_kick.active and not combat.player_airborne_action(me):
        ctx.seat.jump_kick.clear()

    # Round-8 type-$45 props can cross the screen at roughly 12 px per
    # four-frame decision while carrying damage.  Treating them like static
    # crates made the stand-off goal move toward the player every tick, so the
    # agent walked straight into the collision.  Smash only when already in
    # grounded range; otherwise leave the prop's lane and hold there until it
    # passes instead of chasing it.
    moving_props = tuple(
        entity
        for entity in snapshot.world_map.entities
        if entity.kind == "breakable"
        and entity.outgoing_damage > 0
        and graph.entity_has(entity, Relation.REACHABLE)
    )
    if moving_props:
        prop = min(
            moving_props,
            key=lambda entity: math.hypot(
                entity.map_x - me.map_x,
                entity.map_y - me.map_y,
            ),
        )
        abs_dx = abs(prop.map_x - me.map_x)
        abs_dy = abs(prop.map_y - me.map_y)
        fl, fr = combat.face_intent_dirs(me, prop)
        if (
            combat.can_break(me, prop, profile, require_facing=True)
            and combat.player_can_start_ground_action(me)
            and ctx.attack_cd == 0
        ):
            if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=fl
                ):
                walk.clear()
                return Intent(
                    left=fl,
                    right=fr,
                    note=f"ally blocks smash {prop.label}",
                )
            walk.clear()
            ctx.set_attack_cd(3)
            return Intent(
                left=fl,
                right=fr,
                attack=True,
                note=f"smash {prop.label} moving threat",
            )
        if abs_dx <= 220.0:
            if abs_dy < 28.0:
                lane_low = 14.0
                lane_high = max(lane_low, snapshot.world_map.camera_bottom - 12.0)
                goal_y = max(
                    (lane_low, lane_high),
                    key=lambda lane: (abs(lane - prop.world_y), lane),
                )
                return _walk_toward(
                    walk,
                    me,
                    goal_x=float(me.world_x),
                    goal_y=goal_y,
                    reason=f"evade moving threat {prop.label}",
                    snapshot=snapshot,
                    advice=advice,
                    nav=nav,
                    eps_x=3.0,
                    eps_y=5.0,
                )
            walk.clear()
            return Intent(note=f"hold safe lane {prop.label}")

    # Round-6 type-$42 hydraulic presses: solid housing + crushing, never smashable.
    # The machine blocks the walk path — not only the crusher lane. Commit to
    # detour (Y) → advance past the solid far edge (X) before combat/progress
    # can re-aim through the housing.
    # (Do not name the local ``press`` — that shadows the pressure report.)
    presses = stage.stage_press_entities(snapshot.world_map.entities)
    if presses:
        lead = _PROGRESS_LEAD if advice.progress_right else -_PROGRESS_LEAD
        probe_x = float(me.world_x) + lead
        probe_y = float(me.world_y)
        press_entity = stage.select_blocking_press(
            me,
            presses,
            goal_x=probe_x,
            goal_y=probe_y,
            progress_right=advice.progress_right,
        )
        if press_entity is not None:
            gx, gy, reason = stage.press_bypass_goal(
                me,
                press_entity,
                progress_right=advice.progress_right,
                level_index=snapshot.level_index,
                camera_bottom=float(snapshot.world_map.camera_bottom),
            )
            # While leaving the crush band, force a pure lane walk so hole
            # escape does not rewrite the note to "escape hole". Once on the
            # safe lane, route through nav so solid AABBs keep the advance
            # committed past the housing.
            if "leave press" in reason or "detour press" in reason:
                walk.clear()
                walk.set_goal(
                    me,
                    gx,
                    gy,
                    reason=reason,
                    eps_x=3.0,
                    eps_y=5.0,
                    force=True,
                )
                intent = walk.step(me)
                if intent is None:
                    return Intent(note=f"walk idle ({reason})")
                return intent
            return _walk_toward(
                walk,
                me,
                goal_x=gx,
                goal_y=gy,
                reason=reason,
                snapshot=snapshot,
                advice=advice,
                nav=nav,
                eps_x=6.0,
                eps_y=5.0,
            )

    # --- Symbolic/fuzzy tactical arbitration ---
    # Generate legal fight/loot/progress goals from the knowledge graph, then
    # solve a constrained utility problem. This replaces the old unconditional
    # "pickup before combat" priority.
    allow_hp = coop.should_take_health_pickup(player_snap, coop_ctx)
    allow_star = coop.should_take_special_or_life(player_snap, coop_ctx)
    item = combat.select_pickup(
        me,
        snapshot.world_map.entities,
        allow_health=allow_hp,
        allow_special_life=allow_star,
        allow_weapons=True,
        already_holding_weapon=me.is_holding_weapon,
        held_weapon_type=me.held_type,
        profile=profile,
        graph=graph,
    )
    target = combat.select_target(
        me,
        snapshot.world_map.entities,
        profile,
        prefer_forward=advice.progress_right,
        my_seat=player_index,
        graph=graph,
        preferred_slot=(
            goal_memory.target_slot
            if goal_memory.kind == GoalKind.FIGHT
            else None
        ),
    )
    arbitration = solve_goal(
        graph,
        me,
        target=None if target is None else target.entity,
        target_utility=0.0 if target is None else target.utility,
        item=item,
        pressure_urgency=press.urgency,
        health_percent=player_snap.health_percent or 100.0,
        memory=goal_memory,
    )

    if arbitration.winner.kind == GoalKind.LOOT and item is not None:
        loot_verb = (
            "upgrade weapon"
            if item.kind == "weapon" and me.is_holding_weapon
            else "loot"
        )
        close = combat.can_collect_pickup(me, item)
        if close and combat.player_can_start_ground_action(me):
            # Pickup uses B; body-overlap with a partner can still friendly-fire.
            if coop.ally_in_attack_bubble(me, coop_ctx.partner, max_x=coop.ALLY_BODY_X + 4.0, max_y=coop.ALLY_LANE_HALF):
                walk.clear()
                return Intent(note=f"ally blocks {loot_verb} {item.label}")
            walk.clear()
            return Intent(attack=True, note=f"{loot_verb} {item.label}")
        if close:
            walk.clear()
            return Intent(note=f"await {loot_verb} {item.label}")
        return _walk_toward(
            walk,
            me,
            goal_x=float(item.world_x),
            goal_y=float(item.world_y),
            reason=f"{loot_verb} {item.label}",
            snapshot=snapshot,
            advice=advice,
            nav=nav,
            eps_x=3.0,
            eps_y=3.0,
        )

    # --- Combat ---
    # Face-then-hit. Jump-kick is C, then B while airborne — NEVER C+B together
    # (that is rear attack on the ground).
    # ROM facing: bit0 set = face left. Rear threats use current ROM face.
    #
    # Highest free-combat priority: B+C whenever a rear hostile is inside the
    # measured chord window. Instant back protection outranks walking into a
    # front grab while someone is already on your back (main free-damage source).
    face_right_now_me = not combat.player_facing_left(me)
    rear_foe = combat.closest_behind(
        me,
        snapshot.world_map.entities,
        face_right=face_right_now_me,
        max_dist=combat.REAR_REACT_RANGE,
        graph=graph,
    )
    rear_chord_ready = (
        rear_foe is not None
        and not me.is_hurt
        and ctx.attack_cd == 0
        and combat.player_can_start_ground_action(me)
        and combat.can_rear_hit(
            me, rear_foe, profile, face_right=face_right_now_me
        )
    )
    if rear_chord_ready:
        assert rear_foe is not None  # for type checkers; guarded above
        face_left_now = combat.player_facing_left(me)
        if coop.attack_would_hit_ally(
            me, coop_ctx.partner, face_left=face_left_now, rear=True
        ):
            return _clear_ally_lane(
                walk,
                me,
                coop_ctx.partner,
                reason=f"ally blocks rear {rear_foe.label}",
                snapshot=snapshot,
                advice=advice,
                nav=nav,
            )
        walk.clear()
        # The chord owns the seat until recovery (17/44/30 frames at
        # ~4 frames per decision); re-pressing B+C mid-move is wasted.
        ctx.set_attack_cd(max(2, profile.rear_recover // 4))
        return Intent(
            left=face_left_now,
            right=not face_left_now,
            rear_attack=True,
            note=f"rear {rear_foe.label}",
        )

    if target is not None:
        foe = target.entity
        # Distant back security (rear not yet in B+C window): grab a legal
        # front target so crossover-suplex can shield the back once held.
        # Armed Jack is not grabbable. Never walk into grab-shield when the
        # rear chord can already fire — that path returned above.
        rear_threat = DEFAULT_COMBAT_EXPERT.assess(
            me,
            snapshot.world_map.entities,
            held_enemy=None,
            graph=graph,
        ).rear_threat_slot
        rear_entity = next(
            (
                entity
                for entity in snapshot.world_map.entities
                if entity.slot == rear_threat
            ),
            None,
        )
        # If expert found a rear threat we can already chord, treat as not
        # "grab-shield only" (should have returned above; re-check for safety).
        rear_chord_available = (
            rear_entity is not None
            and combat.can_rear_hit(
                me,
                rear_entity,
                profile,
                face_right=not combat.player_facing_left(me),
            )
        )
        back_exposed = (
            rear_entity is not None
            and rear_entity.slot != foe.slot
            and foe.kind in ("enemy", "boss")
            and not rear_chord_available
        )
        grabbable = enemy_ai.is_enemy_grabbable(foe)
        if graph.entity_has(foe, Relation.GRABBABLE):
            grabbable = True
        elif graph.entity_has(foe, Relation.ARMED) and not graph.entity_has(
            foe, Relation.THROWING
        ):
            grabbable = False
        # Carried weapon owns B: body-grab walks collapse the stand-off and
        # fire the weapon at punch range. Keep reach advantage while armed.
        if me.is_holding_weapon:
            grabbable = False

        dx, dy, _geom, plan = combat.approach_vector(
            me,
            target,
            profile,
            low_health=low_hp,
            entities=snapshot.world_map.entities,
        )
        if back_exposed and grabbable:
            plan = dc_replace(
                plan,
                grab_bias=max(plan.grab_bias, 0.9),
                jump_bias=min(plan.jump_bias, 0.1),
                note=f"{plan.note}|back-shield",
            )
        phase = foe.combat_phase
        phase_name = phase.name.lower()
        tag = foe.phase_tag
        cd = ctx.attack_cd
        abs_dx = abs(target.dx)
        abs_dy = abs(target.dy)
        band = combat.engagement_band(abs_dx, abs_dy, profile)
        lane_ok = combat.lane_aligned(me, foe)
        facing_ok = combat.facing_toward(me, foe)
        punch_ok = combat.can_punch(me, foe, profile, require_facing=True)
        punch_geom = combat.can_punch(me, foe, profile, require_facing=False)
        # Mathematical jump-kick solve over the full entity list: predicts
        # multi-enemy hits and the optimal free-flight frame for B.
        jk_plan_box: list[JumpKickPlan] = []
        jump_ok = combat.can_jump_kick(
            me,
            foe,
            profile,
            entities=snapshot.world_map.entities,
            partner=coop_ctx.partner,
            plan_out=jk_plan_box,
        )
        jk_plan = jk_plan_box[0] if jk_plan_box else None
        if jk_plan is None and jump_ok:
            jk_plan = combat.evaluate_jump_kick(
                me,
                snapshot.world_map.entities,
                profile,
                primary=foe,
                partner=coop_ctx.partner,
            )
        # Pack kick even when primary is slightly outside soft FAQ band.
        if not jump_ok and not plan.no_jump:
            pack_plan = combat.evaluate_jump_kick(
                me,
                snapshot.world_map.entities,
                profile,
                primary=foe,
                partner=coop_ctx.partner,
            )
            if (
                pack_plan is not None
                and pack_plan.hit_count >= 2
                and pack_plan.primary_hit
                and not pack_plan.ally_hit
            ):
                jump_ok = True
                jk_plan = pack_plan
        jump_hits = jk_plan.hit_count if jk_plan is not None else 0
        jump_score = jk_plan.score if jk_plan is not None else 0.0
        face_left, face_right_now = combat.face_intent_dirs(me, foe)
        if jk_plan is not None and jk_plan.hold_dir != 0:
            face_left = jk_plan.face_left
            face_right_now = not jk_plan.face_left

        if foe.kind == "projectile" or plan.kind == enemy_ai.ThreatKind.PROJECTILE:
            evade_x = me.world_x - 40 if dx > 0 else me.world_x + 40
            evade_y = me.world_y + (18 if (me.world_x + me.world_y) % 2 == 0 else -18)
            return _walk_toward(
                walk,
                me,
                goal_x=evade_x,
                goal_y=evade_y,
                reason=f"dodge {foe.label}",
                snapshot=snapshot,
                advice=advice,
                nav=nav,
            )

        if phase == CombatPhase.GRABBED and not me.is_grabbing:
            walk.clear()
            lead = _PROGRESS_LEAD if advice.progress_right else -_PROGRESS_LEAD
            return _walk_toward(
                walk,
                me,
                goal_x=float(me.world_x) + lead,
                goal_y=float(me.world_y),
                reason=f"skip held {foe.label}",
                snapshot=snapshot,
                advice=advice,
                nav=nav,
            )

        if combat.player_busy_attacking(me):
            walk.clear()
            if combat.can_queue_normal_combo(me, foe, profile):
                if not coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                    return Intent(
                        left=face_left,
                        right=face_right_now,
                        attack=True,
                        note=f"combo queue {foe.label} [{tag}]",
                    )
            if me.action_base == 0x18 and me.action_flags & 0x20:
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    note=f"combo queued {foe.label} [{tag}]",
                )
            return Intent(
                left=face_left,
                right=face_right_now,
                note=f"atk anim {foe.label} [{tag}]",
            )

        # Secure the back first: walk into a legal grab on the front target so
        # the hold can convert to crossover→suplex when a rear hostile exists.
        if (
            back_exposed
            and grabbable
            and not me.is_hurt
            and foe.kind in ("enemy", "boss")
            and phase != CombatPhase.GRABBED
        ):
            if (
                abs_dx <= 24.0
                and lane_ok
                and facing_ok
                and cd == 0
                and combat.player_can_start_ground_action(me)
            ):
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks grab shield {foe.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(3)
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    attack=True,
                    note=(
                        f"grab shield {foe.label} "
                        f"vs rear {rear_entity.label if rear_entity else ''}"
                    ).strip(),
                )
            return _walk_toward(
                walk,
                me,
                goal_x=float(foe.world_x),
                goal_y=float(foe.world_y),
                reason=(
                    f"close grab shield {foe.label} "
                    f"[{rear_entity.label if rear_entity else 'rear'}]"
                ),
                snapshot=snapshot,
                advice=advice,
                nav=nav,
                eps_x=4.0,
                eps_y=6.0,
            )

        # Souther boss movement: active sidesteps on real commits.
        boss_tactic = bosses.tactical_move(
            me,
            foe,
            snapshot.world_map.entities,
            level_index=snapshot.level_index,
        )
        if boss_tactic is not None:
            if boss_tactic.hold:
                walk.clear()
                return Intent(note=boss_tactic.note)
            return _walk_toward(
                walk,
                me,
                goal_x=boss_tactic.goal_x,
                goal_y=boss_tactic.goal_y,
                reason=boss_tactic.note,
                snapshot=snapshot,
                advice=advice,
                nav=nav,
                eps_x=3.0,
                eps_y=5.0,
            )

        # Signal's state $08 can select the state-$0B low sliding sweep. The
        # latter starts animation $18 at 7 px/frame, so a grounded punch is a
        # poor generic interrupt. Start C now; the airborne branch emits B only
        # after the ROM reaches free-flight $12/$13. Never jump into a pit.
        if combat.signal_sweep_threat(me, foe):
            walk.clear()
            holes = _routing_holes(snapshot, advice)
            if (
                combat.player_can_start_ground_action(me)
                and navigation.jump_landing_safe(me, foe, holes)
            ):
                ctx.set_attack_cd(1)
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    jump=True,
                    note=f"jump Signal sweep [{tag}]",
                )
            return Intent(
                left=face_left,
                right=face_right_now,
                note=f"brace Signal sweep [{tag}]",
            )

        # Ordinary Garcia states above $07 are family moves, not UNKNOWN: for
        # the common Round-1 type $22, $09 is the approach/wind-up and $0A is
        # the active punch. The measured normal-punch boxes now let us strike
        # first; an already-safe off-lane player must not walk back into it.
        if combat.enemy_attack_committed(me, foe):
            if not lane_ok:
                # Boss phase decoders can report CHARGE while the boss is
                # actually waiting for the player to enter its lane. Ordinary
                # enemies will close the lane themselves, but Antonio was
                # observed motionless for hundreds of frames at dy=73. A boss
                # is a hard progression blocker, so deliberately re-align
                # instead of accepting an unbounded "guard lane" fixed point.
                # Exception: a charging boss *already inside reactive lane
                # range* (Antonio's dash-in commit, closing on both axes) is
                # not "waiting" — walking to match its lane here marches the
                # player straight into the hit instead of falling through to
                # the off-lane retreat below. A charge from far off-lane
                # (dy well outside THREAT_LANE_REACT_HALF) still re-aligns.
                charging_nearby = (
                    foe.combat_phase == CombatPhase.CHARGE
                    and abs_dy <= combat.THREAT_LANE_REACT_HALF
                )
                if foe.kind == "boss" and not charging_nearby:
                    return _walk_toward(
                        walk,
                        me,
                        goal_x=float(me.world_x),
                        goal_y=float(foe.world_y),
                        reason=f"reengage boss {foe.label} [{tag}]",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                        eps_x=3.0,
                        eps_y=6.0,
                    )
                if abs_dy <= combat.THREAT_LANE_REACT_HALF:
                    escape_y = float(me.world_y) + (
                        -combat.THREAT_LANE_ESCAPE
                        if target.dy >= 0
                        else combat.THREAT_LANE_ESCAPE
                    )
                    # Ordinary enemy movement clamps the lane to $02-$70.
                    # At an edge, holding farther outward does nothing while
                    # Signal/Garcia closes the gap; retreat in X instead.
                    if not combat.ENEMY_LANE_MIN <= escape_y <= combat.ENEMY_LANE_MAX:
                        escape_x = float(me.world_x) + (
                            -40.0 if target.dx >= 0 else 40.0
                        )
                        return _walk_toward(
                            walk,
                            me,
                            goal_x=escape_x,
                            goal_y=float(me.world_y),
                            reason=f"retreat edge {foe.label} [{tag}]",
                            snapshot=snapshot,
                            advice=advice,
                            nav=nav,
                            eps_x=3.0,
                            eps_y=3.0,
                        )
                    return _walk_toward(
                        walk,
                        me,
                        goal_x=float(me.world_x),
                        goal_y=escape_y,
                        reason=f"escape lane {foe.label} [{tag}]",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                        eps_x=3.0,
                        eps_y=3.0,
                    )
                walk.clear()
                return Intent(note=f"guard lane {foe.label} [{tag}]")
            if abs_dx <= profile.strike_range + combat.PREEMPTIVE_PUNCH_LEAD:
                if cd == 0 and combat.player_can_start_ground_action(me):
                    if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                        return _clear_ally_lane(
                            walk,
                            me,
                            coop_ctx.partner,
                            reason=f"ally blocks interrupt {foe.label}",
                            snapshot=snapshot,
                            advice=advice,
                        nav=nav,
                        )
                    walk.clear()
                    ctx.set_attack_cd(3)
                    return Intent(
                        left=face_left,
                        right=face_right_now,
                        attack=True,
                        note=f"interrupt {foe.label} [{tag}]",
                    )
                walk.clear()
                if not facing_ok:
                    return Intent(
                        left=face_left,
                        right=face_right_now,
                        note=f"face threat {foe.label} [{tag}]",
                    )
                return Intent(note=f"guard threat {foe.label} [{tag}]")

        face_right_for_rear = not combat.player_facing_left(me)
        behind = combat.enemy_is_behind(
            me,
            foe,
            face_right=face_right_for_rear,
        )
        # Use the full closing-aware chord window, not only the static box.
        # A foe walking into the rear box during startup must still force B+C.
        rear_connect = combat.can_rear_hit(
            me, foe, profile, face_right=face_right_for_rear
        )

        # State transitions can start and finish between four-frame samples
        # (notably Signal's easy slide). Meet nearby basic enemies during their
        # approach instead of waiting for the first dangerous-state sample.
        # Never intercept a foe already on our rear arc — that is a B+C case.
        if (
            not behind
            and combat.should_intercept_basic_enemy(me, foe, profile)
        ):
            if cd == 0 and combat.player_can_start_ground_action(me):
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks intercept {foe.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(3)
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    attack=True,
                    note=f"intercept {foe.label} [{tag}]",
                )
            walk.clear()
            if not facing_ok:
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    note=f"face approach {foe.label} [{tag}]",
                )
            return Intent(note=f"hold range {foe.label} [{tag}]")

        # Face first when about to punch.
        if punch_geom and not facing_ok and cd == 0 and not behind:
            walk.clear()
            ctx.set_attack_cd(1)
            return Intent(
                left=face_left,
                right=face_right_now,
                note=f"face {foe.label} [{tag}]",
            )

        if not me.is_hurt and cd == 0:
            mix = enemy_ai.attack_mix(
                plan,
                profile,
                tick=ctx.tick + player_index * 3,
                in_range=punch_geom,
                crowd=press.enemy_count,
                phase_name=phase_name,
                band=band,
                behind=rear_connect,
                lane_ok=lane_ok,
                facing_ok=facing_ok,
                can_jump=jump_ok,
                grabbable=grabbable,
                back_exposed=back_exposed,
                jump_hits=jump_hits,
                jump_score=jump_score,
            )

            if is_punishable(phase) and phase != CombatPhase.GRABBED:
                # Nora-style grab still preferred on punish when grab_bias high.
                if mix != "grab_walk" and punch_ok:
                    if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                        return _clear_ally_lane(
                            walk,
                            me,
                            coop_ctx.partner,
                            reason=f"ally blocks punish {foe.label}",
                            snapshot=snapshot,
                            advice=advice,
                        nav=nav,
                        )
                    walk.clear()
                    ctx.set_attack_cd(2)
                    return Intent(
                        left=face_left,
                        right=face_right_now,
                        attack=True,
                        note=f"punish {foe.label} [{tag}]",
                    )

            if mix == "rear" and combat.can_rear_hit(
                me, foe, profile, face_right=not combat.player_facing_left(me)
            ):
                face_now = combat.player_facing_left(me)
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_now, rear=True
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks back {foe.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(4)
                return Intent(
                    left=face_left if face_left else face_now,
                    right=face_right_now
                    if face_right_now
                    else (not face_now),
                    rear_attack=True,
                    note=f"back atk {profile.name} {foe.label}",
                )

            # Grab approach (Nora, Jack throw window, elevated back-shield):
            # walk to body range and press B to start the hold tree.
            if mix == "grab_walk" and grabbable:
                if (
                    abs_dx <= 24.0
                    and lane_ok
                    and facing_ok
                    and combat.player_can_start_ground_action(me)
                ):
                    if coop.attack_would_hit_ally(
                        me, coop_ctx.partner, face_left=face_left
                    ):
                        return _clear_ally_lane(
                            walk,
                            me,
                            coop_ctx.partner,
                            reason=f"ally blocks grab {foe.label}",
                            snapshot=snapshot,
                            advice=advice,
                            nav=nav,
                        )
                    walk.clear()
                    ctx.set_attack_cd(3)
                    return Intent(
                        left=face_left,
                        right=face_right_now,
                        attack=True,
                        note=f"grab {foe.label} [{tag}]",
                    )
                if not facing_ok and abs_dx <= 40.0:
                    walk.clear()
                    return Intent(
                        left=face_left,
                        right=face_right_now,
                        note=f"face grab {foe.label} [{tag}]",
                    )
                return _walk_toward(
                    walk,
                    me,
                    goal_x=float(foe.world_x),
                    goal_y=float(foe.world_y),
                    reason=f"close grab {foe.label} [{tag}]",
                    snapshot=snapshot,
                    advice=advice,
                    nav=nav,
                    eps_x=4.0,
                    eps_y=6.0,
                )

            # Jump start: C only + face/dir from the solver. B is deferred to
            # free flight at the solved frame (multi-enemy timing).
            # Refuse jumps whose arc/landing crosses a pit or press solid.
            holes = _routing_holes(snapshot, advice)
            land_x = (
                jk_plan.landing_world_x
                if jk_plan is not None
                else None
            )
            land_safe = navigation.jump_landing_safe(
                me, foe, holes, land_x=land_x, land_y=float(me.world_y)
            )
            if (
                mix == "jump"
                and jump_ok
                and facing_ok
                and not plan.no_jump
                and land_safe
            ):
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks jump {foe.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(1)
                if jk_plan is not None:
                    ctx.seat.jump_kick.arm(jk_plan, primary_slot=foe.slot)
                    hold_l = jk_plan.hold_dir < 0 or (
                        jk_plan.hold_dir == 0 and face_left
                    )
                    hold_r = jk_plan.hold_dir > 0 or (
                        jk_plan.hold_dir == 0 and face_right_now
                    )
                    family = foe.family or foe.label
                    return Intent(
                        left=hold_l,
                        right=hold_r,
                        jump=True,
                        note=(
                            f"jump start×{jk_plan.hit_count} "
                            f"{family} [{tag}] {jk_plan.note}"
                        ),
                    )
                family = foe.family or foe.label
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    jump=True,
                    note=f"jump start {family} [{tag}]",
                )

            if mix == "punch" and punch_ok:
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=face_left
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks punch {foe.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(3)
                return Intent(
                    left=face_left,
                    right=face_right_now,
                    attack=True,
                    note=f"punch {foe.label} [{tag}]",
                )

        if punch_geom and cd > 0:
            walk.clear()
            return Intent(
                left=face_left,
                right=face_right_now,
                note=f"face {foe.label} cd={cd}",
            )

        # Stand point: jump counters hold mid range; grab plans walk to body.
        if plan.grab_bias >= 0.5 and grabbable:
            stand_x = float(foe.world_x)
            stand_y = float(foe.world_y)
            reason = f"close grab {foe.label} [{tag}]"
        elif plan.jump_bias >= 0.5 or jump_hits >= 2:
            side = -1.0 if target.dx > 0 else 1.0
            # Prefer a stand-off near half the solved range, else FAQ mid band.
            mid = (profile.jump_kick_min + profile.jump_kick_max) * 0.5
            if jk_plan is not None and jk_plan.range_x > 20:
                mid = min(mid, max(28.0, jk_plan.range_x * 0.55))
            stand_x = float(foe.world_x) + side * mid
            stand_y = float(foe.world_y)
            reason = (
                f"jump range×{jump_hits} {foe.label} [{tag}]"
                if jump_hits
                else f"jump range {foe.label} [{tag}]"
            )
        else:
            stand_x, stand_y = _stand_point(
                me,
                target,
                profile,
                low_health=low_hp,
                entities=snapshot.world_map.entities,
            )
            reason = f"close {foe.label} [{tag}]"
        if (
            is_dangerous(phase)
            and plan.sidestep
            and plan.jump_bias < 0.5
            and band != "close"
            and abs_dx <= combat.DANGER_REACT_X
        ):
            stand_y = float(me.world_y) + (16 if dy >= 0 else -16)
            stand_x = float(me.world_x) + (-28 if dx > 0 else 28)
            reason = f"evade {foe.label} [{tag}]"
        elif not lane_ok:
            # Keep the horizontal stand-off already computed above (jump mid,
            # weapon park, or unarmed approach_offset). The old "match lane
            # first" pin of stand_x to me.world_x walked pure-Y into a
            # diagonally closing foe and arrived chest-to-chest — free punch
            # or body-grab. can_punch still refuses B until Y aligns.
            stand_y = float(foe.world_y)
            reason = f"lane {foe.label} [{tag}]"
        elif is_punishable(phase) and plan.grab_bias < 0.5:
            stand_x, stand_y = _stand_point(
                me,
                target,
                profile,
                low_health=False,
                entities=snapshot.world_map.entities,
            )
            reason = f"chase punish {foe.label} [{tag}]"

        # Wave scroll lock: do not chase ordinary pack members into the
        # progress-edge clamp. Sit mid-field until they walk into engage range.
        if not reason.startswith("evade"):
            hold = combat.midfield_hold_goal(
                me,
                foe,
                progress_right=advice.progress_right,
            )
            if hold is not None:
                stand_x, stand_y = hold
                reason = f"hold mid {foe.label} [{tag}]"

        return _walk_toward(
            walk,
            me,
            goal_x=stand_x,
            goal_y=stand_y,
            reason=reason,
            snapshot=snapshot,
            advice=advice,
            nav=nav,
            # The stand point is only 2–6 px inside character strike range.
            # An 8 px arrival tolerance can stop outside the hit box forever.
            # Mid-field wait uses a looser X eps so the seat idles instead of
            # micro-adjusting forever at map_x≈160.
            eps_x=12.0 if reason.startswith("hold mid") else 3.0,
            eps_y=6.0,
        )

    # Fight won the arbiter but no extractable target (stale graph / off-lane
    # pack). Never fall through to stage progress — that walks into the scroll
    # lock. Park mid-field until a real target appears.
    if arbitration.winner.kind == GoalKind.FIGHT:
        hold = combat.midfield_hold_goal(
            me,
            None,
            progress_right=advice.progress_right,
        )
        assert hold is not None
        return _walk_toward(
            walk,
            me,
            goal_x=hold[0],
            goal_y=hold[1],
            reason="hold mid (wave)",
            snapshot=snapshot,
            advice=advice,
            nav=nav,
            eps_x=12.0,
            eps_y=8.0,
        )

    # --- Breakables (crates / phone booths → loot) when no combat target ---
    # Symbolic rule: smash only from the sides. Top/bottom approaches never
    # land a grounded B; route side-align → lane → close via navigation.
    prop = combat.select_breakable(
        me,
        snapshot.world_map.entities,
        prefer_forward=advice.progress_right,
        graph=graph,
    )
    if prop is not None:
        fl, fr = combat.face_intent_dirs(me, prop)
        holes = _routing_holes(snapshot, advice)
        side_ready = navigation.breakable_side_ready(
            me, prop, profile, holes=holes
        )
        punch_ok = (
            side_ready
            and combat.can_break(me, prop, profile, require_facing=True)
        )
        punch_geom = (
            side_ready
            and combat.can_break(me, prop, profile, require_facing=False)
        )
        jump_ok = (
            side_ready
            and combat.can_jump_kick(me, prop, profile, loose_lane=True)
            and navigation.jump_landing_safe(me, prop, holes)
        )
        cd = ctx.attack_cd

        if combat.player_busy_attacking(me):
            walk.clear()
            return Intent(left=fl, right=fr, note=f"atk anim {prop.label}")

        if punch_geom and not combat.facing_toward(me, prop) and cd == 0:
            walk.clear()
            return Intent(left=fl, right=fr, note=f"face {prop.label}")

        if not me.is_hurt and cd == 0:
            if punch_ok:
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=fl
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks smash {prop.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(3)
                return Intent(
                    left=fl,
                    right=fr,
                    attack=True,
                    note=f"smash {prop.label}",
                )
            # Jump-break only from a side stand-off with a safe landing.
            if jump_ok and combat.facing_toward(me, prop):
                if coop.attack_would_hit_ally(
                    me, coop_ctx.partner, face_left=fl
                ):
                    return _clear_ally_lane(
                        walk,
                        me,
                        coop_ctx.partner,
                        reason=f"ally blocks jump-break {prop.label}",
                        snapshot=snapshot,
                        advice=advice,
                        nav=nav,
                    )
                walk.clear()
                ctx.set_attack_cd(1)
                return Intent(
                    left=fl,
                    right=fr,
                    jump=True,
                    note=f"jump-break {prop.label}",
                )

        approach = navigation.breakable_side_approach(
            me,
            prop,
            profile,
            progress_right=advice.progress_right,
            holes=holes,
            memory=nav,
        )
        return _walk_toward(
            walk,
            me,
            goal_x=approach.goal_x,
            goal_y=approach.goal_y,
            reason=approach.reason,
            snapshot=snapshot,
            advice=advice,
            nav=nav,
            # Always commit break approaches so walk/hole routing cannot
            # re-pick the void side of a pit-adjacent crate every poll.
            eps_x=5.0,
            eps_y=5.0,
        )

    # --- Progress (symbolic hole routing via NavMemory) ---
    lead = _PROGRESS_LEAD if advice.progress_right else -_PROGRESS_LEAD
    preferred_lane = None
    if advice.avoid_holes or advice.elevator:
        preferred_lane = float(0x40 if snapshot.level_index != 6 else 0x50)
    if not advice.horizontal_progress:
        # Discard a progress/approach latch left by the preceding elevator
        # wave.  Even if its old X goal is within WalkState's refresh slack,
        # the clear platform must never inherit LEFT/RIGHT.
        walk.clear()
    progress = navigation.progress_goal(
        me,
        progress_right=advice.progress_right,
        horizontal=advice.horizontal_progress,
        lead=lead,
        preferred_lane=preferred_lane,
        note=advice.note,
    )
    return _walk_toward(
        walk,
        me,
        goal_x=progress.goal_x,
        goal_y=progress.goal_y,
        reason=progress.reason,
        snapshot=snapshot,
        advice=advice,
        nav=nav,
        eps_x=24.0,
        eps_y=8.0,
    )


def _clear_ally_lane(
    walk: WalkState,
    me: MapEntity,
    ally: MapEntity | None,
    *,
    reason: str,
    snapshot: GameSnapshot,
    advice: stage.StageAdvice,
    nav: NavMemory | None = None,
) -> Intent:
    """Step off the partner's lane instead of friendly-firing through them."""

    if ally is None:
        walk.clear()
        return Intent(note=reason)
    delta = coop.ally_clear_lane_delta(me, ally)
    return _walk_toward(
        walk,
        me,
        goal_x=float(me.world_x),
        goal_y=float(me.world_y) + delta,
        reason=reason,
        snapshot=snapshot,
        advice=advice,
        nav=nav,
        eps_x=3.0,
        eps_y=4.0,
    )


def _stand_point(
    me: MapEntity,
    target: combat.TargetChoice,
    profile,
    *,
    low_health: bool,
    entities: tuple[MapEntity, ...] | list[MapEntity] | None = None,
) -> tuple[float, float]:
    """World-space stand-off: same lane, outer strike gap on X.

    ROM pickup box is ~±20 X; body-grabs happen closer. Unarmed seats park at
    ``approach_offset`` (44–56) so measured punches still reach but enemies do
    not free-hit us. Armed seats use ``weapon.approach_stand_dx`` so knife /
    pepper / bat keep their reach advantage instead of walking into punch range.
    ``target.plan`` scales the stand-off per family. Always match the foe's
    lane (off-lane = air punches).
    """

    from . import weapons as W

    foe = target.entity
    plan = target.plan
    del entities  # kept for signature stability with the free-combat caller
    side = -1.0 if (foe.world_x - me.world_x) > 0 else 1.0
    if me.is_holding_weapon and W.is_weapon_type(me.held_type):
        dist = W.approach_stand_dx(me.held_type, profile)
        if low_health:
            dist = max(dist, profile.caution_range * 0.65)
        # Keep at least the weapon's too-close shell; no unarmed clamp that
        # would pull a knife stand (96) down into punch range (~50).
        dist = max(W.too_close_dx(me.held_type) + 4.0, dist)
    else:
        strike = profile.strike_range * plan.range_scale
        dist = max(float(profile.approach_offset), strike * 0.85)
        if low_health:
            dist = max(dist, profile.caution_range * 0.65)
        # Jump-in counters: park in kick window.
        if plan.jump_bias >= 0.5:
            dist = max(
                dist,
                (profile.jump_kick_min + profile.jump_kick_max) * 0.5,
            )
        # Grab pressure (Nora): collapse to body range.
        if plan.grab_bias >= 0.5:
            dist = min(dist, 20.0)
        else:
            # Keep stand strictly inside measured punch box (strike - 4).
            dist = max(22.0, min(dist, strike - 4.0))
    stand_x = float(foe.world_x) + side * dist
    stand_y = float(foe.world_y)
    return stand_x, stand_y


def _walk_toward(
    walk: WalkState,
    me: MapEntity,
    *,
    goal_x: float,
    goal_y: float,
    reason: str,
    snapshot: GameSnapshot,
    advice: stage.StageAdvice,
    nav: NavMemory | None = None,
    eps_x: float = 10.0,
    eps_y: float = 8.0,
    attack: bool = False,
    jump: bool = False,
    rear: bool = False,
) -> Intent:
    """Set/refresh walk goal and return held-direction intent until arrival.

    Hole stages route through the symbolic navigator: a latched DETOUR→ADVANCE
    plan replaces per-tick UP/DOWN flips that shook stage 4.
    """

    holes = _routing_holes(snapshot, advice)
    if nav is not None:
        # Always route through the navigator: hole detours when present, and
        # stuck recovery even when the hole map is empty (walls / crates).
        waypoint = navigation.route_to_goal(
            me,
            goal_x,
            goal_y,
            holes,
            nav,
            level_index=snapshot.level_index,
            progress_right=advice.progress_right,
            reason=reason,
        )
        goal_x, goal_y = waypoint.goal_x, waypoint.goal_y
        reason = waypoint.reason
        # Unstuck escapes must re-arm the walk latch from scratch so D-pad
        # dirs actually change (same-neighbourhood refresh keeps old dirs).
        if "unstuck" in reason:
            walk.clear()
            walk.set_goal(
                me,
                goal_x,
                goal_y,
                reason=reason,
                eps_x=min(eps_x, 6.0),
                eps_y=min(eps_y, 5.0),
                force=True,
            )
        elif waypoint.committed:
            # Committed detours: refresh coords without wiping dirs every poll.
            eps_x = min(eps_x, 6.0)
            eps_y = min(eps_y, 5.0)
            walk.set_goal(
                me,
                goal_x,
                goal_y,
                reason=reason,
                eps_x=eps_x,
                eps_y=eps_y,
                force=True,
            )
        else:
            walk.set_goal(
                me,
                goal_x,
                goal_y,
                reason=reason,
                eps_x=eps_x,
                eps_y=eps_y,
            )
    else:
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

    # Emergency only: if we are already overlapping a pit or press solid, escape.
    # Do not re-steer every frame while a latched nav plan is active — that was
    # the stage-4 shakiness (detour side flipped each poll).
    if holes:
        intent = _emergency_hole_escape(intent, me, holes, snapshot.level_index)

    if attack or jump or rear:
        return blend_walk_with_actions(
            intent, attack=attack, jump=jump, rear_attack=rear
        )
    return intent


def _emergency_hole_escape(
    intent: Intent,
    me: MapEntity,
    holes: tuple,
    level_index: int,
) -> Intent:
    """Only rewrite movement when already inside a pit AABB."""

    hit = navigation.point_in_hole(
        float(me.world_x), float(me.world_y), holes, margin=0.0
    )
    if hit is None:
        return intent
    escape = navigation.escape_hole_waypoint(
        float(me.world_x),
        float(me.world_y),
        hit,
        level_index=level_index,
    )
    dx = escape.goal_x - float(me.world_x)
    dy = escape.goal_y - float(me.world_y)
    return Intent(
        left=dx < -2.0,
        right=dx > 2.0,
        up=dy < -2.0,
        down=dy > 2.0,
        attack=intent.attack,
        jump=False,  # never jump while escaping a pit
        special=intent.special,
        rear_attack=False,
        confirm=intent.confirm,
        note=intent.note + " [escape hole]",
    )


def _seat_drivable(player: PlayerSnapshot) -> bool:
    """Whether this seat may receive agent input this decision.

    Continue / name-entry objects clear the player_mode bit, so ``mode_active``
    is false while ``object_type`` is still ``$0F``.
    """

    return player.is_playable or player.mode_active or player.is_continue_ui


def _continue_ui_intent(player: PlayerSnapshot) -> Intent:
    """Drive type-$0F continue Yes/No and optional high-score name entry.

    ROM (``$5218`` / ``$56E6`` / ``$57D2``):

    - ``object+$4B`` bit7 set → name entry (``$57D2``). On the remapped edge
      byte ``object+$55``: **B** (attack, bit4) is *backspace*; **C** or **A**
      (jump/special, bits 5|6) *places* the current glyph. Three placements
      (or place while glyph is END ``$1A``) finish and clear bit7.
    - bit7 clear → continue Yes/No. ``object+$63`` is 0=YES / nonzero=NO;
      UP/DOWN toggle; any face button (``$F0`` on the global press buffer)
      confirms. YES consumes a continue and rebuilds the active player.

    Policy: place three name glyphs with **C**, force YES, then confirm with
    **B**. Never refuse a continue while continues remain.
    """

    if player.name_entry_active:
        # $57D2: B = backspace, C/A = place. Default cursor glyphs are fine;
        # three place edges fill the three slots and exit name entry.
        return Intent(jump=True, note="name entry place C")

    if player.continues <= 0 or player.out_flag:
        return Intent(note="continue out / game over")

    if player.continue_selects_no:
        # Edge-sensitive UP/DOWN toggle; one direction press flips to YES.
        return Intent(up=True, note="continue select YES")

    return Intent(confirm=True, note="continue confirm YES")


def _mr_x_intent(
    snapshot: GameSnapshot,
    player_index: int,
    memory: AgentState,
) -> Intent:
    """Refuse Mr. X: hold DOWN + A for the whole offer.

    ROM ``$120EC`` reads held ``object+$54`` and processes **DOWN before** face
    bits in the same poll, so one frame can set bit3 (NO) and register. Input is
    ignored outside the choice window; previously we idled on ``+$59`` bit4 clear
    ("mr.x wait") and never advanced when that bit stayed clear between phases.
    Never hold UP (YES).
    """

    del snapshot, player_index, memory  # refuse path is stateless
    return Intent(down=True, special=True, note="mr.x refuse NO (DOWN+A)")
