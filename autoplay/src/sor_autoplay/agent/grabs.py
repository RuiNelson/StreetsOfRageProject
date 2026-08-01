"""Grab / hold / throw decision trees for standard controls.

GameFAQs: prefer **throw (B + away)** over knee mash. Vault/suplex only when
explicitly armed and safe — default path is always throw so we never stall
while holding an enemy.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..world_map import MapEntity
from .characters import CharacterProfile, DEFAULT_PROFILE
from .controls import Intent


WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

# Keep sequences short so sticky hold still produces attack edges.
FACE_TICKS = 1
THROW_PULSES = 5  # attack on/off cycles


@dataclass(frozen=True, slots=True)
class GrabContext:
    holding: bool
    weapon: bool
    enemy_grab: bool
    held_type: int
    action_base: int
    airborne: bool
    hurt: bool


def context_from_player(me: MapEntity) -> GrabContext:
    held_type = me.held_type & 0xFF
    held_ptr = me.held_ptr & 0xFFFF
    action_grab = is_grab_family(me.action_base)
    holding = held_type != 0 or held_ptr != 0 or action_grab
    weapon = 0x08 <= held_type <= 0x0C
    # Enemy grab if holding non-weapon, or grab action with any hold.
    enemy_grab = holding and (not weapon)
    if action_grab and not weapon:
        enemy_grab = True
    return GrabContext(
        holding=holding,
        weapon=weapon and held_type != 0,
        enemy_grab=enemy_grab,
        held_type=held_type,
        action_base=me.action_base,
        airborne=me.is_airborne,
        hurt=me.is_hurt,
    )


def is_grab_family(action_base: int) -> bool:
    return (
        0x28 <= action_base <= 0x2F
        or 0x44 <= action_base <= 0x4F
        or action_base == 0x4A
        or 0x30 <= action_base <= 0x3F
    )


@dataclass
class GrabMemory:
    phase: str = "idle"  # idle | face | throw_on | throw_off
    face_ticks: int = 0
    throw_pulses: int = 0
    throw_dir: int = -1  # +1 right, -1 left (away from foe)

    def reset(self) -> None:
        self.phase = "idle"
        self.face_ticks = 0
        self.throw_pulses = 0
        self.throw_dir = -1


def decide_held(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None = None,
    progress_right: bool = True,
    crowd: int = 0,
    profile: CharacterProfile | None = None,
) -> Intent | None:
    if ctx.hurt:
        memory.reset()
        return None
    if not ctx.holding:
        memory.reset()
        return None

    prof = profile if profile is not None else DEFAULT_PROFILE

    if ctx.weapon:
        return _weapon_tree(me, ctx, memory, tick=tick, foe=foe, profile=prof)

    return _enemy_grab_tree(
        me,
        ctx,
        memory,
        tick=tick,
        foe=foe,
        progress_right=progress_right,
        crowd=crowd,
        profile=prof,
    )


def _throw_away_direction(
    me: MapEntity,
    foe: MapEntity | None,
    *,
    progress_right: bool,
    crowd: int,
) -> int:
    """B+away from bad guy (GameFAQs).

    If we know the held foe position, throw opposite them. With a crowd, throw
    toward stage progress to hit packs.
    """

    if crowd >= 2:
        return 1 if progress_right else -1
    if foe is not None:
        # Away from foe.
        return -1 if foe.map_x >= me.map_x else 1
    # No foe entity: throw opposite stage progress (over the shoulder).
    return -1 if progress_right else 1


def _enemy_grab_tree(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    progress_right: bool,
    crowd: int,
    profile: CharacterProfile,
) -> Intent:
    """Always throw — never idle while holding.

    Sequence: face (hold away 1 tick) → pulse B+away until release or timeout.
    No vault path here (it was stalling holds without completing throws).
    """

    if memory.phase == "idle":
        memory.phase = "face"
        memory.face_ticks = 0
        memory.throw_pulses = 0
        memory.throw_dir = _throw_away_direction(
            me, foe, progress_right=progress_right, crowd=crowd
        )

    left = memory.throw_dir < 0
    right = memory.throw_dir > 0

    if memory.phase == "face":
        memory.face_ticks += 1
        if memory.face_ticks >= FACE_TICKS:
            memory.phase = "throw_on"
            memory.throw_pulses = 0
        return Intent(
            left=left,
            right=right,
            note=f"throw aim ({profile.name}) " + ("L" if left else "R"),
        )

    if memory.phase == "throw_on":
        memory.throw_pulses += 1
        memory.phase = "throw_off"
        return Intent(
            left=left,
            right=right,
            attack=True,
            note=f"throw ({profile.name}) " + ("L" if left else "R"),
        )

    if memory.phase == "throw_off":
        memory.throw_pulses += 1
        if memory.throw_pulses >= THROW_PULSES * 2:
            # Still holding? restart throw cycle immediately (do not rear-escape).
            memory.phase = "face"
            memory.face_ticks = 0
            memory.throw_dir = _throw_away_direction(
                me, foe, progress_right=progress_right, crowd=crowd
            )
        else:
            memory.phase = "throw_on"
        return Intent(
            left=left,
            right=right,
            note=f"throw hold ({profile.name})",
        )

    # Safety net: always throw, never rear while grappling.
    memory.phase = "face"
    memory.face_ticks = 0
    memory.throw_dir = _throw_away_direction(
        me, foe, progress_right=progress_right, crowd=crowd
    )
    return Intent(
        left=memory.throw_dir < 0,
        right=memory.throw_dir > 0,
        note=f"throw recover ({profile.name})",
    )


def _weapon_tree(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    profile: CharacterProfile,
) -> Intent:
    held = ctx.held_type
    melee = held in (WEAPON_BAT, WEAPON_PIPE)
    throwable = held in (WEAPON_KNIFE, WEAPON_BOTTLE, WEAPON_PEPPER)
    blaze_weak = held in profile.weak_weapons

    face_left = face_right = False
    in_melee = mid = False
    if foe is not None:
        dx = foe.map_x - me.map_x
        face_left = dx < -6
        face_right = dx > 6
        in_melee = abs(dx) <= 36 and abs(foe.map_y - me.map_y) <= 14
        mid = 24 <= abs(dx) <= 100

    pulse = (tick % 2) == 0

    if melee:
        if not in_melee and foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                note=f"weapon approach ${held:02X}",
            )
        return Intent(
            left=face_left,
            right=face_right,
            attack=pulse,
            note=f"weapon swing ${held:02X}",
        )

    if throwable:
        if blaze_weak and foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                attack=pulse,
                note=f"dump weapon ${held:02X}",
            )
        if foe is not None and (mid or in_melee):
            return Intent(
                left=face_left,
                right=face_right,
                attack=pulse,
                note=f"weapon use ${held:02X}",
            )
        if foe is not None:
            return Intent(left=face_left, right=face_right, note="weapon close")
        return Intent(note=f"hold weapon ${held:02X}")

    return Intent(attack=pulse, note=f"hold ${held:02X}")


def want_grab_approach(
    me: MapEntity,
    foe: MapEntity,
    *,
    grab_bias: float,
) -> bool:
    if grab_bias < 0.20:
        return False
    # Only when already almost in strike range — do not walk into their chest.
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    return 16 <= dx <= 28 and dy <= 12
