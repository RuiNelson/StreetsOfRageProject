"""Enemy- and boss-specific counters derived from ROM AI analysis.

Family behaviours (``ai-analysis/enemy-ai.md``):

| Family | Threat | Counter idea |
|---|---|---|
| Garcia | Basic pack fighter | Close combo / grab; clean lane |
| Signal | Slide, get behind, throw | Face them; rear-attack when flanking; don't stay still |
| Haku-Ro | Fast ninja, jump-ins | Pre-empt with jump kick; don't chase teleports |
| Nora | Whip + feign injury | Mid-range then burst; don't rush "downed" poses |
| Jack | Axe/torch projectile helper | Normal combat against body; lane-dodge helper |
| Abadede | Clothesline charge | Sidestep charge, punish recovery |
| Antonio | Boomerang / mid spacing | Stay just outside $28-$78 attack window, then burst |
| Souther | Claws, punishes jumps | Prefer grounded combos; avoid jump-ins |
| Bongo | Lane circle + charge/flame | Sidestep charge lane, punish after breath |
| Onihime/Yasha | Jump grabs / twin split | Keep mobile; isolate survivor |
| Mr. X | Charge / fire (type $35) | Mid-close pressure, rear escape when charged |

These are **heuristics** for the autoplay agent, not frame-perfect TAS scripts.

Attack choice is **deterministic** (no tick RNG). Random jump/punch rolls were
the main source of air punches and wrong-direction swings.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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


class JackWeaponPhase(Enum):
    """ROM-backed attached/helper phase for enemy type $27."""

    ARMED = auto()
    THROWING = auto()
    UNARMED = auto()


class JackProjectilePhase(Enum):
    """ROM dispatcher phase for Jack's type-$28 helper objects."""

    ATTACHED = auto()
    LAUNCHED = auto()
    INACTIVE = auto()


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


# Jack's type-$27 state $0E clears +$52 before creating/launching its type-$28
# helper. Damage still applies while armed (punches land), but a body grab is
# only reliable while unarmed or during the throw window ($0E).
JACK_TYPE = 0x27
JACK_THROW_STATE = 0x0E
_JACK_PROJECTILE = 0x28


def jack_projectile_phase(entity: MapEntity) -> JackProjectilePhase | None:
    """Distinguish juggling helpers from weapons that are actually in flight.

    The type-$28 dispatcher table at ROM $103A2 maps state $01 to $FCB6,
    which keeps the two helpers attached to Jack's body. States $02-$04 map
    to the launch, ballistic, and special thrown handlers at $FE46/$FED6/$FEE4.
    Other states are initialization/spawn bookkeeping and are not attacks.
    """

    if entity.type_id != _JACK_PROJECTILE or entity.kind != "projectile":
        return None
    primary = (entity.primary_state >> 8) & 0xFF
    if primary == 0x01:
        return JackProjectilePhase.ATTACHED
    if 0x02 <= primary <= 0x04:
        return JackProjectilePhase.LAUNCHED
    return JackProjectilePhase.INACTIVE


def dangerous_projectile(entity: MapEntity) -> bool:
    """Return whether a projectile object represents an active attack."""

    if entity.kind != "projectile":
        return False
    phase = jack_projectile_phase(entity)
    return phase is None or phase == JackProjectilePhase.LAUNCHED


def jack_weapon_phase(entity: MapEntity) -> JackWeaponPhase | None:
    """Decode Jack's attached/helper phase from his dispatcher state and +$52.

    State $0E wins over the latch because the state transition and byte clear
    can straddle an observation boundary. Non-Jack entities return ``None`` so
    callers cannot accidentally apply this family rule to the $28 projectile.
    """

    if entity.type_id != JACK_TYPE or entity.kind not in ("enemy", "boss"):
        return None
    primary = (entity.primary_state >> 8) & 0xFF
    if primary == JACK_THROW_STATE:
        return JackWeaponPhase.THROWING
    if entity.family_state & 0x01:
        return JackWeaponPhase.ARMED
    return JackWeaponPhase.UNARMED

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
        # Keep mid/far spacing and open with C→B jump kicks rather than
        # walking into Signal's slide/flank range for grounded punches.
        range_scale=1.15,
        jump_bias=0.85,
        rear_bias=0.30,
        grab_bias=0.05,
        sidestep=True,
        priority=1.7,
        note="signal jump-in mid-air",
    ),
    "Haku-Ro": CounterPlan(
        ThreatKind.MOBILE,
        range_scale=1.1,
        jump_bias=0.45,
        grab_bias=0.10,
        priority=1.5,
        note="haku jump intercept",
    ),
    "Nora": CounterPlan(
        ThreatKind.WHIP,
        # Close for a body grab, then knee/throw — safer than trading whip hits.
        range_scale=0.75,
        jump_bias=0.0,
        grab_bias=0.85,
        distrust_downed=True,
        priority=1.9,
        note="nora grab and attack",
    ),
    "Jack": CounterPlan(
        ThreatKind.MIDRANGE,
        range_scale=0.9,
        jump_bias=0.0,
        grab_bias=0.15,  # overridden per weapon phase in plan_for
        priority=2.1,
        note="jack normal vulnerable / helper dodge",
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
        jump_bias=0.0,
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
        jump_bias=0.0,
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

# User-facing target order expressed as fuzzy membership, rather than a hard
# lexicographic sort.  Geometry, an active attack and a punish window can still
# outweigh a family preference, while equally positioned foes consistently use
# boss > Jack > Nora > Signal > Haku-Ro (ninja) > Garcia.
_FAMILY_TARGET_PRIORITY: dict[str, float] = {
    "Garcia": 0.20,
    "Haku-Ro": 0.36,
    "Signal": 0.52,
    "Nora": 0.68,
    "Jack": 0.84,
}


def is_enemy_grabbable(entity: MapEntity) -> bool:
    """Hard grab affordance. Armed Jack cannot be grabbed; throwing can.

    Other live combatants remain grabbable. Projectiles and defeated objects
    never are. Punches against armed Jack remain legal separately.
    """

    if entity.kind not in ("enemy", "boss"):
        return False
    if entity.is_defeated:
        return False
    jack_phase = jack_weapon_phase(entity)
    if jack_phase == JackWeaponPhase.ARMED:
        return False
    if jack_phase == JackWeaponPhase.THROWING:
        return True
    if jack_phase == JackWeaponPhase.UNARMED:
        return True
    return True


def plan_for(entity: MapEntity) -> CounterPlan:
    """Return the counter plan for one combatant (or projectile)."""

    if entity.type_id in _TYPE_PLANS:
        plan = _TYPE_PLANS[entity.type_id]
    elif entity.family in _FAMILY_PLANS:
        plan = _FAMILY_PLANS[entity.family]
    elif entity.kind == "boss":
        plan = CounterPlan(
            ThreatKind.GENERIC,
            range_scale=1.15,
            sidestep=True,
            priority=2.5,
            note="boss generic",
        )
    elif entity.kind == "projectile":
        plan = CounterPlan(
            ThreatKind.PROJECTILE,
            range_scale=2.0,
            prefer_lane_delta=1.0,
            sidestep=True,
            priority=2.0,
            note="projectile dodge",
        )
    else:
        plan = _DEFAULT

    # Jack grab affordance is phase-dependent: armed helpers block grabs;
    # the throw window is the opening to close and grapple.
    jack_phase = jack_weapon_phase(entity)
    if jack_phase == JackWeaponPhase.ARMED:
        return replace(
            plan,
            grab_bias=0.0,
            note="jack armed — punch/dodge, no grab",
        )
    if jack_phase == JackWeaponPhase.THROWING:
        return replace(
            plan,
            grab_bias=0.75,
            jump_bias=0.0,
            note="jack throw window — grab",
        )
    if jack_phase == JackWeaponPhase.UNARMED:
        return replace(
            plan,
            grab_bias=0.40,
            note="jack unarmed — grab ok",
        )
    return plan


def threat_priority(entity: MapEntity) -> float:
    return plan_for(entity).priority


def target_priority_membership(entity: MapEntity) -> float:
    """Return a normalized symbolic preference for target arbitration.

    A launched projectile is an immediate defensive concern and therefore
    keeps the highest reactive membership.  Bosses are the highest combatant
    class; ordinary family values retain enough spacing for hysteresis to
    notice a meaningful tier change.
    """

    if entity.kind == "projectile":
        return 1.0
    if entity.kind == "boss":
        return 0.96
    return _FAMILY_TARGET_PRIORITY.get(entity.family, 0.28)


def adjust_approach(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
    *,
    low_health: bool = False,
) -> tuple[float, float, bool, CounterPlan]:
    """Compute (dx_sign, dy_sign, in_range, plan).

    Stand at about ``strike_range * 0.7`` on X so we face them with a gap for
    punches (not chest-to-chest). Match lane first — off-lane is air-punch land.
    """

    plan = plan_for(foe)
    dx = foe.map_x - me.map_x
    dy = foe.map_y - me.map_y

    strike = profile.strike_range * plan.range_scale
    # Stand near outer strike range (approach_offset). Old 0.55×strike (~15px)
    # was chest-to-chest and let enemies free-punch / body-grab us.
    stand_dist = max(profile.approach_offset, strike * 0.85)
    if low_health:
        stand_dist = max(stand_dist, profile.caution_range * 0.7)
    # Jump-in counters (Signal, Haku-Ro): park in the kick window, not punch.
    if plan.jump_bias >= 0.5:
        stand_dist = max(
            stand_dist,
            (profile.jump_kick_min + profile.jump_kick_max) * 0.5,
        )
    # Grab pressure (Nora, throw-window Jack, back-shield): walk to body range.
    if plan.grab_bias >= 0.5:
        stand_dist = min(stand_dist, 20.0)
    # Body-grab / contact danger band — never park inside this on X unless
    # we are deliberately grabbing.
    too_close = max(18.0, profile.approach_offset * 0.7)
    if plan.grab_bias >= 0.5:
        too_close = 10.0

    if plan.kind == ThreatKind.PROJECTILE or foe.kind == "projectile":
        evade_x = -1.0 if dx > 0 else 1.0
        evade_y = 1.0 if (me.map_y + me.world_x) % 2 == 0 else -1.0
        return evade_x, evade_y, False, plan

    side = -1.0 if dx > 0 else 1.0 if dx < 0 else -1.0
    desired_x = foe.map_x + side * stand_dist
    # Always prefer matching lane before X micro-adjust.
    lane_slop = 8.0
    if abs(dy) > lane_slop:
        desired_y = foe.map_y
    else:
        desired_y = me.map_y

    if plan.sidestep and plan.kind in (
        ThreatKind.CHARGER,
        ThreatKind.FLANKER,
        ThreatKind.CLAWER,
    ):
        # Jump-in Signal prefers same-lane spacing, not permanent sidestep.
        if plan.jump_bias < 0.5 and abs(dx) < strike + 50:
            desired_y = foe.map_y + (14.0 if plan.prefer_lane_delta >= 0 else -14.0)

    err_x = desired_x - me.map_x
    err_y = desired_y - me.map_y
    out_dx = 0.0
    out_dy = 0.0
    # Lane first when badly off.
    if abs(err_y) > lane_slop:
        out_dy = 1.0 if err_y > 0 else -1.0
        # Small X only if already somewhat close on Y path.
        if abs(dy) <= 20 and abs(err_x) > 10:
            out_dx = 1.0 if err_x > 0 else -1.0
    else:
        if abs(err_x) > 6:
            out_dx = 1.0 if err_x > 0 else -1.0

    abs_dx = abs(dx)
    # Inside body-contact band: back out first (do not walk further in),
    # unless this plan wants a body grab.
    if (
        plan.grab_bias < 0.5
        and abs_dx < too_close
        and abs(dy) <= lane_slop + 4
    ):
        out_dx = -1.0 if dx > 0 else 1.0 if dx < 0 else out_dx

    in_range = abs_dx <= strike and abs(dy) <= 12.0
    return out_dx, out_dy, in_range, plan


def attack_mix(
    plan: CounterPlan,
    profile: CharacterProfile,
    *,
    tick: int = 0,
    in_range: bool,
    crowd: int = 1,
    phase_name: str = "normal",
    band: str = "close",
    behind: bool = False,
    lane_ok: bool = True,
    facing_ok: bool = True,
    can_jump: bool = False,
    grabbable: bool = True,
    back_exposed: bool = False,
) -> str:
    """Return 'punch' | 'jump' | 'rear' | 'grab_walk' | 'wait'.

    Deterministic rules (``tick`` kept for API compat, unused for rolls):

    - **rear** only when ``behind`` and we would otherwise punch.
    - **jump** for family jump counters (Signal, Haku-Ro) in jump/approach.
    - **grab_walk** when grab_bias is high (Nora) or back security demands it.
    - **punch** only when ``in_range`` and ``lane_ok`` (and ideally facing).
    - Otherwise **wait** (caller walks).
    """

    del tick, crowd, profile  # reserved / unused

    if behind:
        return "rear"

    if not lane_ok:
        return "wait"

    # Back security outranks family preference: close and grab a legal front
    # target so the crossover-suplex plan can shield the rear.
    grab_pressure = plan.grab_bias
    if back_exposed and grabbable:
        grab_pressure = max(grab_pressure, 0.9)

    if phase_name in ("knockdown", "blocked", "recovery"):
        if grab_pressure >= 0.5 and grabbable:
            return "grab_walk"
        if in_range and facing_ok:
            return "punch"
        return "wait"

    if phase_name in ("charge", "attacking") and plan.sidestep and not in_range:
        # Still allow Signal-style jump-ins while they wind up at range.
        if (
            can_jump
            and not plan.no_jump
            and plan.jump_bias >= 0.5
            and band in ("jump", "approach")
        ):
            return "jump"
        return "wait"

    # Family jump counters (Signal mid-air, Haku-Ro intercept): prefer C→B
    # from the jump window rather than walking into grounded trade range.
    if (
        can_jump
        and not plan.no_jump
        and plan.jump_bias >= 0.25
        and band in ("jump", "approach")
        and grab_pressure < 0.7
    ):
        return "jump"

    # High grab bias only (Nora, Jack throw window, elevated back-shield).
    # Mild Garcia grab_bias (~0.35) must not force body walks over punches.
    if grab_pressure >= 0.5 and grabbable and phase_name in (
        "normal",
        "recovery",
        "knockdown",
        "unknown",
    ):
        if band in ("close", "approach", "jump") or not in_range:
            return "grab_walk"

    if not in_range:
        return "wait"

    if not facing_ok:
        return "wait"

    return "punch"
