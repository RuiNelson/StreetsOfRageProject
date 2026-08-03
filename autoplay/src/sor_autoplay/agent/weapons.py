"""ROM-backed weapon model: damage, range, utility, and use geometry.

Source of truth: ``StreetsOfRageRecompilation/ai-analysis/items-and-weapons.md``
and ``weapons-range-and-damage.md`` (ROM + Axel live probes).

Combat equations (integer world pixels, screen/map X):

Damage on a connecting hit::

    D = DAMAGE[type] ∈ {5, 3, 4, 4, 2}   # knife, bottle, bat, pipe, pepper

Hits to kill an ordinary enemy with health H::

    hits = ceil(H / D)

Knife ``$08`` is **both** melee and throw. ``player_held_object_attack_input``
(``$3084``) picks the action family on attack edge:

- action **``$46``** (stab/melee) if any object is in front within **``$90`` (144)**
  px and lane ``[Y−12, Y+12]``;
- action **``$44``** (throw) otherwise.

Throw release (``$21E6``) only fires on family **``$44``** for knife/pepper:

    X_launch = X_hold ± 48
    Z_launch = Z_hold + 16
    knife:  vx = ±16, vz = 0
    pepper: vx = ±6,  vz = -3

Knife bounce on ground impact::

    vx := -vx / 4

Bat/pipe connecting band (Axel live)::

    |w_x − p_x| ≤ MELEE_ORIGIN_REACH (36)
    |ΔY| ≤ WEAPON_LANE (12)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .characters import CharacterProfile
from .fuzzy import clamp01

# Object types ($08–$0C).
WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

WEAPON_TYPES = frozenset(
    {WEAPON_KNIFE, WEAPON_BOTTLE, WEAPON_BAT, WEAPON_PIPE, WEAPON_PEPPER}
)
MELEE_WEAPONS = frozenset({WEAPON_BAT, WEAPON_PIPE})
# Can become airborne projectiles via attack family $44 + $21E6.
THROW_WEAPONS = frozenset({WEAPON_KNIFE, WEAPON_PEPPER})
# Held impact / dump only — not attack-thrown.
BOTTLE_WEAPONS = frozenset({WEAPON_BOTTLE})

# --- ROM damage nibble at object +$34 ---
DAMAGE: dict[int, int] = {
    WEAPON_KNIFE: 5,
    WEAPON_BOTTLE: 3,
    WEAPON_BAT: 4,
    WEAPON_PIPE: 4,
    WEAPON_PEPPER: 2,
}
MAX_WEAPON_DAMAGE = 5

# Pepper immobilize: enemy +$50 timer $A0 frames at handler $A43E.
PEPPER_IMMOBILIZE_FRAMES = 0xA0  # 160 ≈ 2.67 s @ 60 Hz

# --- Geometry (world/map pixels) ---
WEAPON_LANE = 12.0  # shared Y band for swings/throws (policy / hit tables)
MELEE_ORIGIN_REACH = 36.0  # Axel live bat/pipe |w_x−p_x| on hit frames
THROW_LAUNCH_DX = 48.0  # |ΔX| spawn vs hold origin
THROW_LAUNCH_DZ = 16.0  # ΔZ spawn vs hold origin (Z down-positive in ROM)

# Knife: ROM $3084 picks action $46 if foe in front within $90 (144) px.
KNIFE_VX = 16.0
KNIFE_MELEE_SCAN_X = 0x90  # 144 — selects stab family $46 vs throw $44
KNIFE_MELEE_REACH = 48.0  # policy: prefer stab inside this (inside scan cone)
KNIFE_THROW_MIN = float(KNIFE_MELEE_SCAN_X)  # throw when beyond melee-scan cone
KNIFE_THROW_MAX = 160.0  # engage envelope; walk closer if farther

# Pepper: primarily thrown ($44); vx=±6, arc.
PEPPER_VX = 6.0
PEPPER_THROW_MIN = 24.0
PEPPER_THROW_MAX = 100.0

# Bottle: no attack throw; only dump/B when body-close.
BOTTLE_DUMP_REACH = MELEE_ORIGIN_REACH

# Preferred |ΔX| stand-off while carrying. Keep weapons' reach advantage:
# free combat must not walk armed seats into unarmed punch/body range.
# Knife parks deep in the ROM $90 (144) stab cone; bat/pipe just inside
# origin reach 36; pepper mid throw corridor; bottle near dump reach.
WEAPON_APPROACH_DX: dict[int, float] = {
    WEAPON_KNIFE: 96.0,
    WEAPON_BOTTLE: 28.0,
    WEAPON_BAT: 30.0,
    WEAPON_PIPE: 30.0,
    WEAPON_PEPPER: 72.0,
}
# Back out when closer than this (same lane) so multi-hit stabs / swings do
# not end chest-to-chest. Still allows B once space is reopened.
WEAPON_TOO_CLOSE_DX: dict[int, float] = {
    WEAPON_KNIFE: 52.0,
    WEAPON_BOTTLE: 14.0,
    WEAPON_BAT: 18.0,
    WEAPON_PIPE: 18.0,
    WEAPON_PEPPER: 32.0,
}


@dataclass(frozen=True, slots=True)
class WeaponSpec:
    """Static per-type combat parameters."""

    type_id: int
    name: str
    damage: int
    kind: str  # "melee" | "throw" | "hybrid" | "dump"
    # Absolute |ΔX| band where B is useful (lane already filtered).
    use_min_dx: float
    use_max_dx: float
    # Fuzzy utility ingredients in [0, 1] before profile modifiers.
    range_score: float
    control_score: float


SPECS: dict[int, WeaponSpec] = {
    WEAPON_KNIFE: WeaponSpec(
        WEAPON_KNIFE,
        "knife",
        5,
        "hybrid",  # melee $46 in cone, throw $44 outside
        0.0,
        KNIFE_THROW_MAX,
        range_score=0.95,
        control_score=0.45,
    ),
    WEAPON_BOTTLE: WeaponSpec(
        WEAPON_BOTTLE,
        "bottle",
        3,
        "dump",
        0.0,
        BOTTLE_DUMP_REACH,
        range_score=0.25,
        control_score=0.10,  # one-way shatter, shards deal 0
    ),
    WEAPON_BAT: WeaponSpec(
        WEAPON_BAT,
        "bat",
        4,
        "melee",
        0.0,
        MELEE_ORIGIN_REACH,
        range_score=0.55,
        control_score=0.55,
    ),
    WEAPON_PIPE: WeaponSpec(
        WEAPON_PIPE,
        "pipe",
        4,
        "melee",
        0.0,
        MELEE_ORIGIN_REACH,
        range_score=0.55,
        control_score=0.55,
    ),
    WEAPON_PEPPER: WeaponSpec(
        WEAPON_PEPPER,
        "pepper",
        2,
        "throw",
        0.0,
        PEPPER_THROW_MAX,
        range_score=0.70,
        control_score=0.90,  # 160-frame immobilize
    ),
}


def damage_of(type_id: int) -> int:
    return DAMAGE.get(type_id & 0xFF, 0)


def hits_to_kill(health: int, type_id: int) -> int:
    """ceil(H / D); at least 1 if D>0 and H>0."""

    d = damage_of(type_id)
    if d <= 0 or health <= 0:
        return 0 if health <= 0 else 999
    return int(math.ceil(health / d))


def is_melee_weapon(type_id: int) -> bool:
    return (type_id & 0xFF) in MELEE_WEAPONS


def is_throw_weapon(type_id: int) -> bool:
    return (type_id & 0xFF) in THROW_WEAPONS


def is_weapon_type(type_id: int) -> bool:
    return (type_id & 0xFF) in WEAPON_TYPES


def weapon_utility(type_id: int, profile: CharacterProfile | None = None) -> float:
    """Scalar usefulness in [0, 1] for pickup / upgrade decisions.

    Equation (weights sum to 1 before profile tweak)::

        U = 0.45 · (D / 5) + 0.35 · range_score + 0.20 · control_score
        U += 0.12 if preferred;  U -= 0.20 if weak  (then clamp)
    """

    tid = type_id & 0xFF
    spec = SPECS.get(tid)
    if spec is None:
        return 0.0
    damage_term = spec.damage / float(MAX_WEAPON_DAMAGE)
    u = 0.45 * damage_term + 0.35 * spec.range_score + 0.20 * spec.control_score
    if profile is not None:
        if tid in profile.preferred_weapons:
            u += 0.12
        if tid in profile.weak_weapons:
            u -= 0.20
    return clamp01(u)


# Back-compat name used by combat pickup selection.
def weapon_value(type_id: int, profile: CharacterProfile | None = None) -> float:
    return weapon_utility(type_id, profile)


def is_weapon_upgrade(
    current_type: int,
    candidate_type: int,
    profile: CharacterProfile | None,
    *,
    margin: float = 0.08,
) -> bool:
    current = current_type & 0xFF
    candidate = candidate_type & 0xFF
    if current not in SPECS:
        return candidate in SPECS
    return weapon_utility(candidate, profile) >= weapon_utility(current, profile) + margin


def in_weapon_lane(dy: float, *, half: float = WEAPON_LANE) -> bool:
    return abs(dy) <= half


def facing_toward(dx: float, face_left: bool) -> bool:
    """True if the character faces the foe (dx = foe.x − me.x)."""

    if dx == 0:
        return True
    return (dx < 0) == face_left


def melee_can_connect(abs_dx: float, abs_dy: float) -> bool:
    return abs_dy <= WEAPON_LANE and abs_dx <= MELEE_ORIGIN_REACH


def knife_can_hit(abs_dx: float, abs_dy: float) -> bool:
    """Enemy is inside knife engage range (melee scan or throw flight)."""

    return abs_dy <= WEAPON_LANE and 0.0 < abs_dx <= KNIFE_THROW_MAX


def knife_should_melee(abs_dx: float, abs_dy: float) -> bool:
    """ROM selects stab family ``$46`` when a front target is within ``$90`` X.

    Policy uses the same scan limit so B produces a melee attack, not a throw.
    """

    return abs_dy <= WEAPON_LANE and 0.0 < abs_dx <= float(KNIFE_MELEE_SCAN_X)


def knife_should_throw(abs_dx: float, abs_dy: float) -> bool:
    """Throw family ``$44`` when foe is past the melee-scan cone but still hittable.

    ``$3084`` only picks ``$44`` when no object is found in the front ``$90``
    box; enemies beyond 144 px and within ~160 px are the intentional throw
    band.
    """

    if abs_dy > WEAPON_LANE:
        return False
    return float(KNIFE_MELEE_SCAN_X) < abs_dx <= KNIFE_THROW_MAX


def knife_should_use(abs_dx: float, abs_dy: float) -> bool:
    """True when B is useful for knife (stab or throw)."""

    return knife_should_melee(abs_dx, abs_dy) or knife_should_throw(abs_dx, abs_dy)


def knife_decide(
    abs_dx: float,
    abs_dy: float,
    *,
    foe_health: int | None = None,
    prefer_keep_knife: bool = True,
) -> str | None:
    """Choose ``\"melee\"``, ``\"throw\"``, or None (walk / free combat).

    Same **B** always; ROM picks ``$46`` vs ``$44`` from the front cone. Policy:

    - **Melee** when the cone would select ``$46`` (keeps the knife for more hits).
    - **Throw** when past the cone but within flight envelope **and** either the
      foe dies to one knife hit (``H ≤ 5``) or we are not conserving the weapon.
    - If past the cone, multi-hit foe, and ``prefer_keep_knife``: return None so
      free combat closes into the stab cone instead of sacrificing the knife.
    """

    if abs_dy > WEAPON_LANE:
        return None
    if knife_should_melee(abs_dx, abs_dy):
        return "melee"
    if not knife_should_throw(abs_dx, abs_dy):
        return None
    d = DAMAGE[WEAPON_KNIFE]
    one_shot = foe_health is not None and 0 < foe_health <= d
    if one_shot or not prefer_keep_knife:
        return "throw"
    # Multi-hit target just outside stab cone: close for melee, keep knife.
    return None


def pepper_should_throw(abs_dx: float, abs_dy: float) -> bool:
    return (
        abs_dy <= WEAPON_LANE
        and PEPPER_THROW_MIN <= abs_dx <= PEPPER_THROW_MAX
    ) or (abs_dy <= WEAPON_LANE and abs_dx <= MELEE_ORIGIN_REACH)


def bottle_should_dump(abs_dx: float, abs_dy: float) -> bool:
    return abs_dy <= WEAPON_LANE and abs_dx <= BOTTLE_DUMP_REACH


def use_range_for(type_id: int) -> tuple[float, float]:
    """Inclusive |ΔX| band where pressing B is intended."""

    tid = type_id & 0xFF
    if tid == WEAPON_KNIFE:
        return (0.0, KNIFE_THROW_MAX)
    if tid == WEAPON_PEPPER:
        return (0.0, PEPPER_THROW_MAX)
    if tid in MELEE_WEAPONS:
        return (0.0, MELEE_ORIGIN_REACH)
    if tid == WEAPON_BOTTLE:
        return (0.0, BOTTLE_DUMP_REACH)
    return (0.0, 0.0)


def approach_stand_dx(type_id: int, profile: CharacterProfile | None = None) -> float:
    """World |ΔX| stand-off while carrying ``type_id``.

    Falls back to the character's unarmed ``approach_offset`` for unknown types.
    """

    tid = type_id & 0xFF
    stand = WEAPON_APPROACH_DX.get(tid)
    if stand is not None:
        return stand
    if profile is not None:
        return float(profile.approach_offset)
    return 46.0


def too_close_dx(type_id: int) -> float:
    """|ΔX| below which an armed seat should back out before re-engaging."""

    tid = type_id & 0xFF
    return WEAPON_TOO_CLOSE_DX.get(tid, 18.0)


def should_back_out(type_id: int, abs_dx: float, abs_dy: float) -> bool:
    """True when same-lane spacing is tighter than the weapon's stand band."""

    if abs(abs_dy) > WEAPON_LANE:
        return False
    return 0.0 < abs_dx < too_close_dx(type_id)


def knife_mode(
    abs_dx: float,
    abs_dy: float,
    *,
    foe_health: int | None = None,
    prefer_keep_knife: bool = True,
) -> str | None:
    """``\"melee\"``, ``\"throw\"``, or None if out of band / approach preferred."""

    return knife_decide(
        abs_dx,
        abs_dy,
        foe_health=foe_health,
        prefer_keep_knife=prefer_keep_knife,
    )


def expected_damage_over_hits(type_id: int, hits: int) -> int:
    return damage_of(type_id) * max(0, hits)


def ranking_key(type_id: int, profile: CharacterProfile | None = None) -> tuple:
    """Sort key: higher utility first, then higher raw damage."""

    tid = type_id & 0xFF
    return (-weapon_utility(tid, profile), -damage_of(tid), tid)
