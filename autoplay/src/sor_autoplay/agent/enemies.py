"""Enemy- and boss-specific counters derived from ROM AI analysis.

Family behaviours (``ai-analysis/enemy-ai.md``):

| Family | Threat | Counter idea |
|---|---|---|
| Garcia | Basic pack fighter | Close combo / grab; clean lane |
| Signal | Slide, get behind, throw | Face them; rear-attack when flanking; don't stay still |
| Haku-Ro | Fast ninja, jump-ins | Pre-empt with jump kick; don't chase teleports |
| Nora | Whip + feign injury | Mid-range then burst; don't rush "downed" poses |
| Jack | Axe/torch projectiles | Lane-dodge projectiles; rush when juggling |
| Abadede | Clothesline charge | Sidestep charge, punish recovery |
| Antonio | Boomerang / mid spacing | Stay just outside $28-$78 attack window, then burst |
| Souther | Claws, punishes jumps | Prefer grounded combos; avoid jump-ins |
| Bongo | Lane circle + charge/flame | Sidestep charge lane, punish after breath |
| Onihime/Yasha | Jump grabs / twin split | Keep mobile; isolate survivor |
| Mr. X | Charge / fire (type $35) | Mid-close pressure, rear escape when charged |

These are **heuristics** for the autoplay agent, not frame-perfect TAS scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..world_map import MapEntity
from .characters import CharacterProfile


class ThreatKind(Enum):
    PACK = auto()
    FLANKER = auto()
    MOBILE = auto()
    WHIP = auto()
    PROJECTILE = auto()
    CHARGER = auto()
    MIDRANGE = auto()
    CLAWER = auto()
    JUMP_GRAB = auto()
    FINAL = auto()
    GENERIC = auto()


@dataclass(frozen=True, slots=True)
class CounterPlan:
    """How to stand and what attack mix to prefer against one foe."""

    kind: ThreatKind
    # Multiplier on preferred strike distance (1.0 = character default).
    range_scale: float = 1.0
    # Prefer lane offset (sign: + toward front / larger map_y).
    prefer_lane_delta: float = 0.0
    # Bias toward jump / rear / grab / hold-back.
    jump_bias: float = 0.0
    rear_bias: float = 0.0
    grab_bias: float = 0.0
    # When True, avoid walking straight into their X; circle / sidestep.
    sidestep: bool = False
    # When True, do not jump (enemy punishes air).
    no_jump: bool = False
    # When True, treat "low health / downed" foe as still dangerous (Nora feint).
    distrust_downed: bool = False
    # Extra priority weight for target selection.
    priority: float = 1.0
    note: str = ""


# Type-id ranges for Jack projectile helper.
_JACK_PROJECTILE = 0x28

_FAMILY_PLANS: dict[str, CounterPlan] = {
    "Garcia": CounterPlan(
        ThreatKind.PACK,
        range_scale=1.0,
        grab_bias=0.35,
        priority=1.0,
        note="garcia combo/grab",
    ),
    "Signal": CounterPlan(
        ThreatKind.FLANKER,
        range_scale=0.9,
        rear_bias=0.45,
        grab_bias=0.15,
        sidestep=True,
        priority=1.7,
        note="signal face + rear",
    ),
    "Haku-Ro": CounterPlan(
        ThreatKind.MOBILE,
        range_scale=1.1,
        jump_bias=0.35,
        grab_bias=0.10,
        priority=1.5,
        note="haku jump intercept",
    ),
    "Nora": CounterPlan(
        ThreatKind.WHIP,
        range_scale=1.15,
        jump_bias=0.05,
        grab_bias=0.25,
        distrust_downed=True,
        priority=1.3,
        note="nora mid then grab",
    ),
    "Jack": CounterPlan(
        ThreatKind.PROJECTILE,
        range_scale=0.85,
        prefer_lane_delta=1.0,
        jump_bias=0.10,
        grab_bias=0.20,
        sidestep=True,
        priority=1.6,
        note="jack lane dodge / rush",
    ),
    "Abadede": CounterPlan(
        ThreatKind.CHARGER,
        range_scale=1.2,
        prefer_lane_delta=1.0,
        rear_bias=0.25,
        grab_bias=0.05,
        sidestep=True,
        no_jump=True,
        priority=3.0,
        note="abadede sidestep charge",
    ),
    "Souther": CounterPlan(
        ThreatKind.CLAWER,
        range_scale=1.05,
        rear_bias=0.15,
        grab_bias=0.10,
        no_jump=True,
        priority=2.6,
        note="souther grounded only",
    ),
    "Antonio": CounterPlan(
        ThreatKind.MIDRANGE,
        range_scale=1.35,
        jump_bias=0.08,
        grab_bias=0.05,
        sidestep=True,
        priority=2.5,
        note="antonio outside boomerang",
    ),
    "Bongo": CounterPlan(
        ThreatKind.CHARGER,
        range_scale=1.25,
        prefer_lane_delta=1.0,
        rear_bias=0.20,
        sidestep=True,
        no_jump=True,
        priority=2.5,
        note="bongo sidestep flame",
    ),
    "Onihime/Yasha": CounterPlan(
        ThreatKind.JUMP_GRAB,
        range_scale=1.1,
        jump_bias=0.05,
        rear_bias=0.30,
        grab_bias=0.10,
        sidestep=True,
        priority=2.6,
        note="twins stay mobile",
    ),
}

# Boss type overrides when family label is generic "Boss".
_TYPE_PLANS: dict[int, CounterPlan] = {
    0x30: _FAMILY_PLANS["Abadede"],
    0x55: _FAMILY_PLANS["Souther"],
    0x56: _FAMILY_PLANS["Antonio"],
    0x57: _FAMILY_PLANS["Bongo"],
    0x58: _FAMILY_PLANS["Onihime/Yasha"],
    0x35: CounterPlan(  # Mr. X body
        ThreatKind.FINAL,
        range_scale=1.0,
        rear_bias=0.30,
        grab_bias=0.0,
        sidestep=True,
        priority=3.5,
        note="mr.x pressure",
    ),
    _JACK_PROJECTILE: CounterPlan(
        ThreatKind.PROJECTILE,
        range_scale=2.0,
        prefer_lane_delta=1.0,
        sidestep=True,
        priority=2.2,
        note="dodge jack projectile",
    ),
}

_DEFAULT = CounterPlan(ThreatKind.GENERIC, note="default")


def plan_for(entity: MapEntity) -> CounterPlan:
    """Return the counter plan for one combatant (or projectile)."""

    if entity.type_id in _TYPE_PLANS:
        return _TYPE_PLANS[entity.type_id]
    if entity.family in _FAMILY_PLANS:
        return _FAMILY_PLANS[entity.family]
    if entity.kind == "boss":
        return CounterPlan(
            ThreatKind.GENERIC,
            range_scale=1.15,
            sidestep=True,
            priority=2.5,
            note="boss generic",
        )
    if entity.kind == "projectile":
        return CounterPlan(
            ThreatKind.PROJECTILE,
            range_scale=2.0,
            prefer_lane_delta=1.0,
            sidestep=True,
            priority=2.0,
            note="projectile dodge",
        )
    return _DEFAULT


def threat_priority(entity: MapEntity) -> float:
    return plan_for(entity).priority


def adjust_approach(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
    *,
    low_health: bool = False,
) -> tuple[float, float, bool, CounterPlan]:
    """Compute (dx_sign, dy_sign, in_range, plan) with family-specific spacing.

    Signs are -1 / 0 / +1 in map space.
    """

    plan = plan_for(foe)
    dx = foe.map_x - me.map_x
    dy = foe.map_y - me.map_y

    strike = profile.strike_range * plan.range_scale
    if low_health:
        strike = max(strike, profile.caution_range * 0.85)

    # Stand slightly off the foe on the side we approach from.
    side = -1.0 if dx > 0 else 1.0 if dx < 0 else -1.0
    offset = profile.approach_offset * plan.range_scale
    if plan.sidestep and abs(dx) < strike + 40:
        # Prefer a lane offset rather than head-on for chargers/flankers.
        desired_y = foe.map_y + (18.0 if plan.prefer_lane_delta >= 0 else -18.0)
    else:
        desired_y = foe.map_y + plan.prefer_lane_delta * 10.0

    desired_x = foe.map_x + side * offset

    # Antonio: only pull in from outside the far band; jump-ins handle mid.
    if plan.kind == ThreatKind.MIDRANGE and abs(dx) > 0x78:
        desired_x = foe.map_x + side * strike

    if plan.kind == ThreatKind.PROJECTILE or foe.kind == "projectile":
        evade_x = -1.0 if dx > 0 else 1.0
        evade_y = 1.0 if (me.map_y + me.world_x) % 2 == 0 else -1.0
        return evade_x, evade_y, False, plan

    err_x = desired_x - me.map_x
    err_y = desired_y - me.map_y
    out_dx = 0.0
    out_dy = 0.0
    if abs(err_x) > 6:
        out_dx = 1.0 if err_x > 0 else -1.0
    if abs(err_y) > profile.lane_align:
        out_dy = 1.0 if err_y > 0 else -1.0

    # Always face the foe when close — never stroll past their back.
    if abs(dx) < 50 and abs(dy) < 20:
        out_dx = 1.0 if dx > 0 else -1.0 if dx < 0 else out_dx

    in_range = abs(dx) <= strike + 10 and abs(dy) <= profile.lane_align + 10
    return out_dx, out_dy, in_range, plan


def attack_mix(
    plan: CounterPlan,
    profile: CharacterProfile,
    *,
    tick: int,
    in_range: bool,
    crowd: int,
    phase_name: str = "normal",
    band: str = "close",
    behind: bool = False,
) -> str:
    """Return 'punch' | 'jump' | 'rear' | 'grab_walk' | 'wait'."""

    if behind:
        return "rear"

    if phase_name in ("knockdown", "blocked", "recovery"):
        return "punch" if in_range or band == "close" else "jump"

    # Mid-range: jump+attack is the efficient opener.
    if band == "jump" and not plan.no_jump:
        return "jump"
    if band == "approach" and not plan.no_jump:
        roll = ((tick * 17) % 100) / 100.0
        if roll < 0.55 + profile.jump_attack_bias * 0.3:
            return "jump"
        return "wait"

    if phase_name in ("charge", "attacking") and plan.sidestep and not in_range:
        return "rear" if tick % 3 == 0 else "wait"

    if not in_range and band == "far":
        return "wait"

    if not in_range:
        if plan.grab_bias >= 0.35 and phase_name == "normal":
            return "grab_walk"
        return "jump" if not plan.no_jump else "wait"

    roll = ((tick * 17) % 100) / 100.0
    jump_p = profile.jump_attack_bias + plan.jump_bias
    rear_p = profile.rear_attack_bias + plan.rear_bias
    grab_p = plan.grab_bias * 0.5

    if plan.no_jump:
        jump_p = 0.0
    if crowd >= 3:
        rear_p += 0.20
    if phase_name == "attacking":
        rear_p += 0.30

    if roll < rear_p:
        return "rear"
    if roll < rear_p + jump_p:
        return "jump"
    if roll < rear_p + jump_p + grab_p * 0.35 and phase_name == "normal":
        return "grab_walk"
    return "punch"
