"""Onihime/Yasha counter-AI from ROM routines (``enemy-ai.md`` type ``$58``).

Two independent type-``$58`` objects share one update (``$158C4``). Pair role
``+$5D`` seeds ``+$7B`` bit 1 (grab path vs approach path). There is no enrage:
killing one twin unlinks the survivor (``$17F9C``) and the fight becomes much
easier — so policy **focus-fires one body until she is dead**.

ROM distance windows (state 1, approach / grab setup):

| Window | Field | Threshold | Effect |
| --- | --- | --- | --- |
| Jump arm | abs X ``+$50`` | ``< $60`` (96) | approach path → tactical ``$02`` jump |
| Approach commit | lane ``+$52``, X | lane ``[$10,$20)``, X ``< $70`` | → primary ``$02`` throw |
| Grab commit helper | X, screen X | X ``≥ $90`` aborts; screen mid required | leap-to-grab arm |
| Grab jump-in | X | prefer ``< $40`` or ``$40–$70`` | stronger jump into grab |

Primary ``$02`` is the committed grab/throw timeline (``$15D0C``) — always leave
the attack lane. Tactical ``+$67`` on approach: ``$00`` idle, ``$01`` chase,
``$02`` jump attack. Grab path uses its own table including ``$03`` leap arm.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..phases import CombatPhase, is_dangerous, is_punishable
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level
from .enemies import CounterPlan, ThreatKind


TWIN_TYPE = 0x58
TWIN_FAMILY = "Onihime/Yasha"

# --- ROM thresholds (bytes; see enemy-ai.md Onihime/Yasha section) ---
JUMP_ARM_X = 0x60  # 96 — approach close-range jump arm $15A64
APPROACH_COMMIT_X = 0x70  # 112 — commit window max X
APPROACH_COMMIT_LANE_LO = 0x10  # 16
APPROACH_COMMIT_LANE_HI = 0x20  # 32 exclusive
GRAB_COMMIT_X = 0x90  # 144 — grab helper aborts if X >= this
GRAB_JUMP_PREF_X = 0x40  # 64 — grab jump-in prefers this band
NEAR_X = 150.0
NEAR_Y = 36.0

# Focus-fire: stick to one twin; switching requires this utility gap (never used
# for the other twin while focus lives — hard lock below).
FOCUS_UTILITY = 0.55
FOCUS_PICK_HP_WEIGHT = 0.12
FOCUS_PICK_DIST_WEIGHT = 0.02


class TwinComposition(Enum):
    ABSENT = auto()
    PAIR = auto()
    SURVIVOR = auto()


class TwinRoutine(Enum):
    """Decoded primary/tactical behaviour for one twin body."""

    INIT = auto()
    APPROACH_IDLE = auto()  # state1, +$67=0, approach path
    APPROACH_CHASE = auto()  # state1, +$67=1
    APPROACH_JUMP = auto()  # state1, +$67=2 jump attack $15ABA
    GRAB_HUNT = auto()  # state1, grab path (role 2 / +$7B bit1)
    GRAB_LEAP = auto()  # state1 grab, +$67=3 leap-to-grab $15BE8
    COMMIT = auto()  # primary $02 throw/grab timeline $15D0C
    RECOVERY = auto()  # hit / police / shared recovery
    OTHER = auto()


@dataclass
class TwinFocusMemory:
    """Sticky focus-fire latch: kill one twin before engaging the other."""

    focus_slot: str | None = None

    def clear(self) -> None:
        self.focus_slot = None


# Pair: deny both jump arm and approach commit on the focus target by parking
# just outside $60, stay off shared lane depth, never jump, never walk into grab.
_PAIR_FOCUS_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.35,  # ~strike*1.35 ≈ outside jump arm for Axel/Adam
    prefer_lane_delta=1.0,
    jump_bias=0.0,
    rear_bias=0.30,
    grab_bias=0.0,
    sidestep=True,
    no_jump=True,
    priority=3.0,
    note="twins pair focus — finish one",
)

# Non-focus twin while pair is up: only used if selector somehow picks her;
# prefer evade spacing.
_PAIR_OTHER_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.45,
    prefer_lane_delta=1.0,
    jump_bias=0.0,
    rear_bias=0.40,
    grab_bias=0.0,
    sidestep=True,
    no_jump=True,
    priority=2.4,
    note="twins pair other — disengage",
)

# Survivor: pressure and grab; still respect jump/commit windows.
_SURVIVOR_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.08,
    prefer_lane_delta=0.0,
    jump_bias=0.10,
    rear_bias=0.25,
    grab_bias=0.55,
    sidestep=True,
    no_jump=False,
    priority=2.7,
    note="twin survivor — pressure/grab",
)

# Static fallback without entity list.
_STATIC_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.15,
    jump_bias=0.0,
    rear_bias=0.30,
    grab_bias=0.10,
    sidestep=True,
    no_jump=True,
    priority=2.6,
    note="twins (static)",
)


def is_twin(entity: MapEntity) -> bool:
    return entity.kind == "boss" and entity.type_id == TWIN_TYPE


def live_twins(
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> tuple[MapEntity, ...]:
    return tuple(
        e for e in entities if is_twin(e) and not e.is_defeated
    )


def twin_composition(
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> TwinComposition:
    n = len(live_twins(entities))
    if n >= 2:
        return TwinComposition.PAIR
    if n == 1:
        return TwinComposition.SURVIVOR
    return TwinComposition.ABSENT


def twin_primary(entity: MapEntity) -> int:
    """Primary state byte at ``+$30`` (boss dispatcher index).

    Use ``action_state`` (byte at ``+$30``). Do **not** use
    ``primary_state & 0xFF`` — that is ``+$31`` on big-endian word reads.
    """

    return entity.action_state & 0xFF


def twin_tactical(entity: MapEntity) -> int:
    """Tactical substate ``+$67``."""

    return entity.tactical & 0xFF


def abs_x_to_player(me: MapEntity, twin: MapEntity) -> float:
    """Prefer ROM boss distance ``+$50`` when present, else world ΔX."""

    if twin.boss_dist_x > 0:
        return float(twin.boss_dist_x)
    return abs(float(twin.world_x) - float(me.world_x))


def abs_lane_to_player(me: MapEntity, twin: MapEntity) -> float:
    if twin.boss_dist_lane > 0:
        return float(twin.boss_dist_lane)
    return abs(float(twin.world_y) - float(me.world_y))


def decode_routine(entity: MapEntity) -> TwinRoutine:
    """Map primary/tactical/pair_role onto a counter-relevant routine."""

    if not is_twin(entity) or entity.is_defeated:
        return TwinRoutine.OTHER
    p = twin_primary(entity)
    t = twin_tactical(entity)
    phase = entity.combat_phase

    if p == 0x00:
        return TwinRoutine.INIT
    if p == 0x02:
        return TwinRoutine.COMMIT
    if p in (0x03, 0x04, 0x0A) or phase in (
        CombatPhase.RECOVERY,
        CombatPhase.BLOCKED,
    ):
        return TwinRoutine.RECOVERY
    if p >= 0x05 and phase == CombatPhase.DEATH:
        return TwinRoutine.OTHER
    if p != 0x01:
        if is_dangerous(phase):
            return TwinRoutine.COMMIT
        if is_punishable(phase):
            return TwinRoutine.RECOVERY
        return TwinRoutine.OTHER

    # State 1 active combat.
    # Grab path: pair_role 2 seeds +$7B bit1. We cannot read +$7B live; role
    # 2 is the durable grab-AI seed until unpair. Survivor (role 0) may promote
    # — treat role 0 with high grab bias contexts via phase/tactical leap.
    grab_path = entity.pair_role == 2
    if t == 0x03:
        return TwinRoutine.GRAB_LEAP
    if t == 0x02:
        # Approach jump $15ABA, or grab-path jump-in $15C72 (also uses $02).
        return TwinRoutine.APPROACH_JUMP if not grab_path else TwinRoutine.GRAB_LEAP
    if grab_path:
        return TwinRoutine.GRAB_HUNT
    if t == 0x01:
        return TwinRoutine.APPROACH_CHASE
    return TwinRoutine.APPROACH_IDLE


def in_jump_arm_range(me: MapEntity, twin: MapEntity) -> bool:
    """True when approach path can arm jump (abs X < $60)."""

    return abs_x_to_player(me, twin) < JUMP_ARM_X


def in_approach_commit_window(me: MapEntity, twin: MapEntity) -> bool:
    """True when approach path can enter primary $02 (lane + X window)."""

    dx = abs_x_to_player(me, twin)
    dy = abs_lane_to_player(me, twin)
    return (
        dx < APPROACH_COMMIT_X
        and APPROACH_COMMIT_LANE_LO <= dy < APPROACH_COMMIT_LANE_HI
    )


def in_grab_commit_range(me: MapEntity, twin: MapEntity) -> bool:
    """True when grab helper can start leap-to-grab (X < $90)."""

    return abs_x_to_player(me, twin) < GRAB_COMMIT_X


def nearby_twins(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    *,
    max_dx: float = NEAR_X,
    max_dy: float = NEAR_Y,
) -> tuple[MapEntity, ...]:
    return tuple(
        twin
        for twin in live_twins(entities)
        if abs(twin.world_x - me.world_x) <= max_dx
        and abs(twin.world_y - me.world_y) <= max_dy
    )


def twins_bracket_player(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> bool:
    nearby = nearby_twins(me, entities)
    if len(nearby) < 2:
        return False
    return (
        min(t.world_x for t in nearby) < me.world_x
        and max(t.world_x for t in nearby) > me.world_x
    )


def _focus_pick_score(me: MapEntity, twin: MapEntity) -> float:
    """Higher = better first focus. Prefer weaker + closer + approach role."""

    hp = float(twin.health if twin.health is not None else 0x20)
    if hp >= 0x8000:
        hp = 0.0
    dist = abs(float(twin.world_x) - float(me.world_x)) + 0.5 * abs(
        float(twin.world_y) - float(me.world_y)
    )
    score = -FOCUS_PICK_HP_WEIGHT * hp - FOCUS_PICK_DIST_WEIGHT * dist
    # Approach-role twin (1) is usually safer to pin; grab-role (2) is more
    # dangerous but removing her first is also valid — prefer closer/weaker
    # above role. Small bias toward lower HP already dominates.
    if twin.pair_role == 1:
        score += 0.03
    if is_dangerous(twin.combat_phase) or decode_routine(twin) in (
        TwinRoutine.COMMIT,
        TwinRoutine.APPROACH_JUMP,
        TwinRoutine.GRAB_LEAP,
    ):
        # If one is mid-commit on us, do not pick her as "focus to chase" —
        # still OK if she is the only close body; small penalty so we may
        # pick the free twin to kill while dodging the other.
        score -= 0.02
    return score


def update_focus(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    memory: TwinFocusMemory,
) -> str | None:
    """Latch focus on one twin until she is defeated, then the survivor.

    Time-tested strategy: reduce the fight to a single body ASAP.
    """

    twins = live_twins(entities)
    composition = twin_composition(entities)

    if composition is TwinComposition.ABSENT:
        memory.clear()
        return None

    if composition is TwinComposition.SURVIVOR:
        memory.focus_slot = twins[0].slot
        return memory.focus_slot

    # PAIR: keep sticky focus while that body lives.
    if memory.focus_slot is not None:
        still = next((t for t in twins if t.slot == memory.focus_slot), None)
        if still is not None:
            return memory.focus_slot

    # Pick a new focus and latch.
    best = max(twins, key=lambda t: _focus_pick_score(me, t))
    memory.focus_slot = best.slot
    return memory.focus_slot


def twin_focus_bonus(
    entity: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    *,
    focus_slot: str | None,
    my_seat: int = 1,
) -> float:
    """Target utility delta enforcing focus-fire while both twins live.

    Focus twin gets a large positive boost. The other twin gets a penalty so
    the selector will not thrash. Emergency: if the other twin is in COMMIT /
    jump on us and focus is far, allow a smaller reactive bump (still below
    focus).
    """

    if twin_composition(entities) is not TwinComposition.PAIR:
        return 0.0
    if not is_twin(entity) or entity.is_defeated:
        return 0.0

    if focus_slot and entity.slot == focus_slot:
        bonus = FOCUS_UTILITY
        # Finish priority: lower HP focus slightly higher.
        if entity.health is not None and entity.health < 0x10:
            bonus += 0.05
        if entity.targets_player == my_seat:
            bonus += 0.02
        return min(0.65, bonus)

    # Non-focus twin.
    routine = decode_routine(entity)
    if routine in (
        TwinRoutine.COMMIT,
        TwinRoutine.APPROACH_JUMP,
        TwinRoutine.GRAB_LEAP,
    ):
        # Allow defensive re-target only for an immediate commit — still well
        # below a healthy focus lock so DPS returns to focus after evade.
        return -0.05
    return -0.35


def twin_scene_plan(
    composition: TwinComposition,
    *,
    entity: MapEntity | None = None,
    focus_slot: str | None = None,
) -> CounterPlan | None:
    if composition is TwinComposition.ABSENT:
        return None
    if composition is TwinComposition.SURVIVOR:
        plan = _SURVIVOR_PLAN
        if entity is not None:
            return _apply_routine_overlay(plan, decode_routine(entity), survivor=True)
        return plan
    # PAIR
    if entity is not None and focus_slot and entity.slot != focus_slot:
        plan = _PAIR_OTHER_PLAN
    else:
        plan = _PAIR_FOCUS_PLAN
    if entity is not None:
        return _apply_routine_overlay(plan, decode_routine(entity), survivor=False)
    return plan


def _apply_routine_overlay(
    plan: CounterPlan,
    routine: TwinRoutine,
    *,
    survivor: bool,
) -> CounterPlan:
    """Tighten spacing / attack mix for the live ROM routine."""

    from dataclasses import replace

    if routine is TwinRoutine.COMMIT:
        return replace(
            plan,
            range_scale=max(plan.range_scale, 1.5),
            grab_bias=0.0,
            jump_bias=0.0,
            no_jump=True,
            sidestep=True,
            note=f"{plan.note}|commit evade",
        )
    if routine in (TwinRoutine.APPROACH_JUMP, TwinRoutine.GRAB_LEAP):
        return replace(
            plan,
            range_scale=max(plan.range_scale, 1.4),
            grab_bias=0.0,
            jump_bias=0.0,
            no_jump=True,
            sidestep=True,
            note=f"{plan.note}|jump arm evade",
        )
    if routine is TwinRoutine.RECOVERY:
        # Punish window — allow grab/punch pressure.
        return replace(
            plan,
            range_scale=min(plan.range_scale, 1.0 if survivor else 1.1),
            grab_bias=max(plan.grab_bias, 0.55 if survivor else 0.35),
            jump_bias=0.0,
            no_jump=True,
            note=f"{plan.note}|punish recovery",
        )
    if routine is TwinRoutine.GRAB_HUNT:
        # Stay outside grab commit X ($90) when possible via range_scale.
        return replace(
            plan,
            range_scale=max(plan.range_scale, 1.4),
            grab_bias=0.0,
            note=f"{plan.note}|deny grab X≥$90",
        )
    if routine in (TwinRoutine.APPROACH_IDLE, TwinRoutine.APPROACH_CHASE):
        # Deny jump arm ($60) and approach commit — park outside $60.
        return replace(
            plan,
            range_scale=max(plan.range_scale, 1.3),
            note=f"{plan.note}|deny jump arm",
        )
    return plan


def plan_for_twin(
    entity: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity] | None = None,
    *,
    focus_slot: str | None = None,
) -> CounterPlan | None:
    """Return twin-specific plan, or None if entity is not a live twin."""

    if not is_twin(entity) or entity.is_defeated:
        return None
    if entities is None:
        return _STATIC_PLAN
    composition = twin_composition(entities)
    return twin_scene_plan(
        composition, entity=entity, focus_slot=focus_slot
    ) or _STATIC_PLAN


@dataclass(frozen=True, slots=True)
class TwinTactic:
    goal_x: float
    goal_y: float
    hold: bool
    note: str


def tactical_move(
    me: MapEntity,
    target: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    level_index: int,
    focus_slot: str | None = None,
) -> TwinTactic | None:
    """Routine-aware movement for twin fights (pair focus + survivor)."""

    if not is_twin(target) or target.is_defeated:
        return None
    composition = twin_composition(entities)
    if composition is TwinComposition.ABSENT:
        return None

    if composition is TwinComposition.SURVIVOR:
        return _survivor_tactic(me, target, level_index=level_index)

    return _pair_tactic(
        me,
        target,
        entities,
        level_index=level_index,
        focus_slot=focus_slot,
    )


def _survivor_tactic(
    me: MapEntity,
    target: MapEntity,
    *,
    level_index: int,
) -> TwinTactic | None:
    routine = decode_routine(target)
    if routine in (
        TwinRoutine.COMMIT,
        TwinRoutine.APPROACH_JUMP,
        TwinRoutine.GRAB_LEAP,
    ):
        return _evade_attack_lane(
            me,
            attack_lane=float(target.world_y),
            level_index=level_index,
            family="twin survivor commit",
        )
    # Deny approach jump arm / grab commit by leaving lane if inside window
    # and she is chasing, rather than trading on her depth.
    if routine in (
        TwinRoutine.APPROACH_CHASE,
        TwinRoutine.APPROACH_IDLE,
        TwinRoutine.GRAB_HUNT,
    ):
        if in_jump_arm_range(me, target) or (
            routine is TwinRoutine.GRAB_HUNT and in_grab_commit_range(me, target)
        ):
            if abs_lane_to_player(me, target) < 14.0:
                return _evade_attack_lane(
                    me,
                    attack_lane=float(target.world_y),
                    level_index=level_index,
                    family="twin survivor deny window",
                    clearance=22.0,
                )
    return None


def _pair_tactic(
    me: MapEntity,
    target: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    level_index: int,
    focus_slot: str | None,
) -> TwinTactic | None:
    twins = live_twins(entities)
    nearby = nearby_twins(me, entities)

    # 1. Bracket: both sides on X — leave shared depth immediately.
    if twins_bracket_player(me, entities):
        shared = sum(float(t.world_y) for t in nearby) / max(1, len(nearby))
        return _evade_attack_lane(
            me,
            attack_lane=shared,
            level_index=level_index,
            family="twins pair surround",
        )

    # 2. Any twin in COMMIT / jump arm toward us — leave that lane first
    #    (including the non-focus body so focus-fire is not interrupted by a
    #    grab throw from behind).
    urgent = tuple(
        t
        for t in twins
        if decode_routine(t)
        in (
            TwinRoutine.COMMIT,
            TwinRoutine.APPROACH_JUMP,
            TwinRoutine.GRAB_LEAP,
        )
        and abs(t.world_x - me.world_x) <= NEAR_X
        and abs(t.world_y - me.world_y) <= NEAR_Y + 12
    )
    if urgent:
        # Prefer leaving the most dangerous / closest commit lane.
        threat = min(
            urgent,
            key=lambda t: (
                0 if decode_routine(t) is TwinRoutine.COMMIT else 1,
                abs(t.world_x - me.world_x),
            ),
        )
        return _evade_attack_lane(
            me,
            attack_lane=float(threat.world_y),
            level_index=level_index,
            family=(
                "twins pair focus-evade"
                if focus_slot and threat.slot == focus_slot
                else "twins pair partner-evade"
            ),
        )

    # 3. Focus engagement: stay on focus depth only when safe; keep a lane
    #    offset from the *other* twin so she cannot share commit depth.
    focus = next((t for t in twins if t.slot == focus_slot), target)
    other = next((t for t in twins if t.slot != focus.slot), None)

    if other is not None and abs(other.world_x - me.world_x) <= NEAR_X:
        # Leave shared lane with partner while we pressure focus.
        if abs(float(me.world_y) - float(other.world_y)) < 16.0:
            return _evade_attack_lane(
                me,
                attack_lane=float(other.world_y),
                level_index=level_index,
                family="twins pair isolate partner",
                clearance=26.0,
            )
        # Deny grabber X if she is hunting and inside $90.
        if (
            decode_routine(other) is TwinRoutine.GRAB_HUNT
            and in_grab_commit_range(me, other)
            and abs_lane_to_player(me, other) < 20.0
        ):
            # Back off on X away from the grabber, hold lane.
            away = -1.0 if other.world_x > me.world_x else 1.0
            return TwinTactic(
                goal_x=float(me.world_x) + away * 48.0,
                goal_y=float(me.world_y),
                hold=False,
                note="twins pair deny grab X",
            )

    # 4. Focus twin inside jump-arm / approach-commit window while idle/chase:
    #    micro lane leave so she cannot enter primary $02.
    if focus is not None:
        fr = decode_routine(focus)
        if fr in (TwinRoutine.APPROACH_IDLE, TwinRoutine.APPROACH_CHASE):
            if in_approach_commit_window(me, focus) or (
                in_jump_arm_range(me, focus) and abs_lane_to_player(me, focus) < 14.0
            ):
                return _evade_attack_lane(
                    me,
                    attack_lane=float(focus.world_y),
                    level_index=level_index,
                    family="twins pair deny commit window",
                    clearance=20.0,
                )

    return None


def _evade_attack_lane(
    me: MapEntity,
    *,
    attack_lane: float,
    level_index: int,
    family: str,
    clearance: float = 28.0,
) -> TwinTactic:
    lane_gap = abs(float(me.world_y) - attack_lane)
    if lane_gap >= clearance - 4.0:
        return TwinTactic(
            goal_x=float(me.world_x),
            goal_y=float(me.world_y),
            hold=True,
            note=f"hold safe lane {family}",
        )

    lane_min = float(LANE_Y_MIN + 6)
    lane_max = float(lane_y_max_for_level(level_index) - 6)
    candidates = tuple(
        lane
        for lane in (attack_lane - clearance, attack_lane + clearance)
        if lane_min <= lane <= lane_max
    )
    if not candidates:
        goal_y = (
            lane_max
            if attack_lane <= (lane_min + lane_max) / 2.0
            else lane_min
        )
    else:
        goal_y = min(
            candidates,
            key=lambda lane: (abs(lane - float(me.world_y)), lane),
        )
    return TwinTactic(
        goal_x=float(me.world_x),
        goal_y=goal_y,
        hold=False,
        note=f"sidestep {family}",
    )


# ---------------------------------------------------------------------------
# Compatibility aliases used by scene.py / older imports
# ---------------------------------------------------------------------------

TWIN_NEAR_X = NEAR_X
TWIN_NEAR_Y = NEAR_Y
