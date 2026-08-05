"""Decision context and exclusive player modes for the agent pipeline.

Pipeline (per seat, per decision)::

    GameSnapshot
        → DecisionContext (perception bag)
        → PlayerMode (exclusive ROM partition)
        → Commitment / skills (multi-frame ownership)
        → free goal + combat / nav (when mode is FREE)
        → Intent → coop gate → button mask

Hard ROM facts live on the snapshot and knowledge graph. Soft preference
scores (pressure, target utility) never expand what a mode allows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

from ..state import GameSnapshot, PlayerSnapshot
from ..world_map import MapEntity
from .arbiter import GoalMemory
from .autoplanner import AutoPlanner
from .characters import CharacterProfile, profile_for
from .coop import CoopContext, build_coop
from .grabs import (
    ENEMY_HOLD_ACTIONS,
    GRAB_ANIMATION_ACTIONS,
    EnemyGrabEscapeMemory,
    GrabMemory,
    ThrowLandTechMemory,
    context_from_player,
)
from .jump_kick import JumpKickPending
from .knowledge import TacticalKnowledgeGraph, build_tactical_graph
from .navigation import NavMemory
from .pressure import PressureReport, compute_pressure
from .stage import StageAdvice, stage_advice
from .walk import WalkState

if TYPE_CHECKING:
    from .skills import Commitment


class PlayerMode(Enum):
    """Exclusive ROM-facing modes. FREE is the only open tactical space."""

    DIALOG = auto()
    CONTINUE_UI = auto()  # type-$0F continue Yes/No or high-score name entry
    NOT_PLAYABLE = auto()
    STEADY = auto()  # pause / police special / menus — decided at session level
    ENEMY_HELD = auto()
    HURT = auto()
    HOLDING = auto()
    GRAB_ANIM = auto()
    AIRBORNE = auto()
    FREE = auto()


@dataclass
class SeatMemory:
    """All mutable per-seat policy memory (not ROM state)."""

    phase: int = 0
    last_note: str = ""
    attack_cd: int = 0
    grab: GrabMemory = field(default_factory=GrabMemory)
    enemy_grab_escape: EnemyGrabEscapeMemory = field(
        default_factory=EnemyGrabEscapeMemory
    )
    throw_land_tech: ThrowLandTechMemory = field(
        default_factory=ThrowLandTechMemory
    )
    walk: WalkState = field(default_factory=WalkState)
    nav: NavMemory = field(default_factory=NavMemory)
    planner: AutoPlanner = field(default_factory=AutoPlanner)
    goal: GoalMemory = field(default_factory=GoalMemory)
    jump_kick: JumpKickPending = field(default_factory=JumpKickPending)
    commitment: Commitment | None = None

    def __post_init__(self) -> None:
        # Late import avoids circular dependency at module load.
        if self.commitment is None:
            from .skills import Commitment

            self.commitment = Commitment()

    def clear_tactical(self) -> None:
        """Drop multi-frame tactical state (walk, plans, goals, skills)."""

        self.walk.clear()
        self.planner.reset()
        self.goal.clear()
        self.nav.clear_all()
        self.grab.reset()
        self.enemy_grab_escape.reset()
        self.throw_land_tech.reset()
        self.jump_kick.clear()
        assert self.commitment is not None
        self.commitment.clear()


@dataclass(slots=True)
class DecisionContext:
    """One coherent bag of perception + seat state for a single decision.

    Built once per seat per tick so mode handlers and skills do not re-thread
    a dozen kwargs.
    """

    snapshot: GameSnapshot
    player_index: int
    player_snap: PlayerSnapshot
    me: MapEntity | None
    partner: MapEntity | None
    partner_snap: PlayerSnapshot | None
    both_agents: bool
    config_police_threshold: float
    config_allow_weapon_pickup: bool
    tick: int
    seat: SeatMemory
    profile: CharacterProfile
    advice: StageAdvice
    coop: CoopContext
    mode: PlayerMode
    # Populated after early exclusive modes (need a live player entity).
    graph: TacticalKnowledgeGraph | None = None
    press: PressureReport | None = None

    @property
    def walk(self) -> WalkState:
        return self.seat.walk

    @property
    def nav(self) -> NavMemory:
        return self.seat.nav

    @property
    def planner(self) -> AutoPlanner:
        return self.seat.planner

    @property
    def goal_memory(self) -> GoalMemory:
        return self.seat.goal

    @property
    def grab_mem(self) -> GrabMemory:
        return self.seat.grab

    @property
    def enemy_grab_escape_mem(self) -> EnemyGrabEscapeMemory:
        return self.seat.enemy_grab_escape

    @property
    def attack_cd(self) -> int:
        return self.seat.attack_cd

    def set_attack_cd(self, value: int) -> None:
        self.seat.attack_cd = value

    def ensure_perception(self) -> None:
        """Build knowledge graph and pressure once a live entity is present."""

        if self.me is None or self.graph is not None:
            return
        self.graph = build_tactical_graph(
            self.me,
            self.snapshot.world_map.entities,
            level_index=self.snapshot.level_index,
            player_index=self.player_index,
        )
        self.press = compute_pressure(
            self.snapshot,
            self.player_snap,
            self.me,
            graph=self.graph,
        )


def classify_mode(
    *,
    me: MapEntity | None,
    player_snap: PlayerSnapshot,
    is_mr_x: bool,
    entities: tuple[MapEntity, ...] = (),
    player_index: int = 1,
) -> PlayerMode:
    """Partition the player into one exclusive mode from ROM state.

    Order matches ownership: dialog and non-playable before combat, enemy-held
    and hurt before voluntary holding, grab animations before free combat,
    airborne before grounded free play.
    """

    if is_mr_x:
        return PlayerMode.DIALOG
    # After lives are exhausted the slot becomes type $0F (continue/name entry).
    # player_mode bit is cleared, so mode_active is false — still drive the seat.
    if getattr(player_snap, "is_continue_ui", False):
        return PlayerMode.CONTINUE_UI
    if me is None or not player_snap.is_playable:
        return PlayerMode.NOT_PLAYABLE
    if me.action_base in ENEMY_HOLD_ACTIONS:
        return PlayerMode.ENEMY_HELD
    if me.is_hurt:
        return PlayerMode.HURT
    if me.action_base in GRAB_ANIMATION_ACTIONS:
        return PlayerMode.GRAB_ANIM

    from . import combat as combat_mod

    if combat_mod.player_airborne_action(me):
        return PlayerMode.AIRBORNE

    gctx = context_from_player(me, entities, player_index=player_index)
    if gctx.holding:
        return PlayerMode.HOLDING
    return PlayerMode.FREE


def build_decision_context(
    snapshot: GameSnapshot,
    *,
    player_index: int,
    player_snap: PlayerSnapshot,
    both_agents: bool,
    police_threshold: float,
    allow_weapon_pickup: bool = True,
    tick: int,
    seat: SeatMemory,
    me: MapEntity | None,
    partner: MapEntity | None,
    partner_snap: PlayerSnapshot | None,
    is_mr_x: bool,
) -> DecisionContext:
    """Assemble a DecisionContext and classify the exclusive mode."""

    advice = stage_advice(snapshot.level_index)
    profile = profile_for(player_snap.character_id)
    coop_ctx = build_coop(
        me=me,
        me_snap=player_snap,
        partner=partner,
        partner_snap=partner_snap,
        both_agents=both_agents,
    )
    mode = classify_mode(
        me=me,
        player_snap=player_snap,
        is_mr_x=is_mr_x,
        entities=snapshot.world_map.entities if me is not None else (),
        player_index=player_index,
    )

    return DecisionContext(
        snapshot=snapshot,
        player_index=player_index,
        player_snap=player_snap,
        me=me,
        partner=partner,
        partner_snap=partner_snap,
        both_agents=both_agents,
        config_police_threshold=police_threshold,
        config_allow_weapon_pickup=allow_weapon_pickup,
        tick=tick,
        seat=seat,
        profile=profile,
        advice=advice,
        coop=coop_ctx,
        mode=mode,
    )
