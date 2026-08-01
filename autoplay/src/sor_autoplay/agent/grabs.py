"""Grab / hold / throw decision trees for standard controls.

ROM (``loc_00002D20`` / ``player_held_object_attack_input``):

- While holding, **attack edge** (``+$55`` bit4) enters grab-attack family ``$44``
  via ``player_held_object_attack_input``.
- Throw is **B + away/back** (GameFAQs): away is **opposite player facing**,
  not "away from nearest free enemy". Using nearest-foe flipped the stick to
  *toward* the held target and produced endless knees / freezes.
- Player facing is action-state bit 0 (set = face left).

Default path: always throw (B+back with clean edges). Never idle while holding.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import CombatPhase
from ..world_map import MapEntity
from .characters import CharacterProfile, DEFAULT_PROFILE
from .controls import Intent


WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

# Sticky hold_buttons needs a real off frame so +$55 sees an attack edge.
FACE_TICKS = 1
# throw_on (B held) / throw_off (B released) pairs.
THROW_PULSES = 8


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
    # Also treat player combat phase HOLDING as holding (held_type path).
    phase_hold = me.combat_phase == CombatPhase.HOLDING
    holding = held_type != 0 or held_ptr != 0 or action_grab or phase_hold
    weapon = 0x08 <= held_type <= 0x0C
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
    """Player action families used while acquiring/holding/throwing."""

    return (
        0x28 <= action_base <= 0x2F
        or 0x30 <= action_base <= 0x3F
        or 0x44 <= action_base <= 0x4F
        or action_base == 0x4A
    )


@dataclass
class GrabMemory:
    phase: str = "idle"  # idle | face | throw_on | throw_off
    face_ticks: int = 0
    throw_pulses: int = 0
    throw_dir: int = -1  # +1 right, -1 left (back / away)

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


def throw_back_direction(
    me: MapEntity,
    *,
    progress_right: bool = True,
    crowd: int = 0,
) -> int:
    """B+away direction: opposite of player facing (ROM bit0 set = face left).

    Crowd override: throw toward stage progress so the body hits packs.
    """

    if crowd >= 3:
        return 1 if progress_right else -1
    # Facing left → back is right (+1); facing right → back is left (−1).
    if me.action_state & 0x01:
        return 1
    return -1


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
    """Always throw with B+back — never idle while holding an enemy.

    Sequence: hold away 1 tick → pulse B+away (on/off) until release.
    ``foe`` is ignored for direction (was the stall bug); kept for API compat.
    """

    del foe  # direction is face-relative, not nearest-foe

    if memory.phase == "idle":
        memory.phase = "face"
        memory.face_ticks = 0
        memory.throw_pulses = 0
        memory.throw_dir = throw_back_direction(
            me, progress_right=progress_right, crowd=crowd
        )

    # Refresh throw_dir each cycle in case facing flipped during the grab.
    if memory.phase == "face":
        memory.throw_dir = throw_back_direction(
            me, progress_right=progress_right, crowd=crowd
        )

    left = memory.throw_dir < 0
    right = memory.throw_dir > 0
    side = "L" if left else "R"

    if memory.phase == "face":
        memory.face_ticks += 1
        if memory.face_ticks >= FACE_TICKS:
            memory.phase = "throw_on"
            memory.throw_pulses = 0
        return Intent(
            left=left,
            right=right,
            note=f"throw aim ({profile.name}) {side}",
        )

    if memory.phase == "throw_on":
        memory.throw_pulses += 1
        memory.phase = "throw_off"
        return Intent(
            left=left,
            right=right,
            attack=True,
            note=f"throw ({profile.name}) {side}",
        )

    if memory.phase == "throw_off":
        memory.throw_pulses += 1
        if memory.throw_pulses >= THROW_PULSES * 2:
            memory.phase = "face"
            memory.face_ticks = 0
            memory.throw_dir = throw_back_direction(
                me, progress_right=progress_right, crowd=crowd
            )
        else:
            memory.phase = "throw_on"
        return Intent(
            left=left,
            right=right,
            note=f"throw hold ({profile.name}) {side}",
        )

    memory.phase = "face"
    memory.face_ticks = 0
    memory.throw_dir = throw_back_direction(
        me, progress_right=progress_right, crowd=crowd
    )
    return Intent(
        left=memory.throw_dir < 0,
        right=memory.throw_dir > 0,
        attack=True,  # hard edge immediately on recover
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
        if dx < 0:
            face_left, face_right = True, False
        elif dx > 0:
            face_left, face_right = False, True
        else:
            face_left = bool(me.action_state & 0x01)
            face_right = not face_left
        in_melee = abs(dx) <= 36 and abs(foe.map_y - me.map_y) <= 12
        mid = 20 <= abs(dx) <= 100
    else:
        # Keep current face.
        face_left = bool(me.action_state & 0x01)
        face_right = not face_left

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

    # Unknown held type (enemy type id left in +$60): treat as grab throw.
    return _enemy_grab_tree(
        me,
        ctx,
        memory,
        tick=tick,
        foe=foe,
        progress_right=True,
        crowd=0,
        profile=profile,
    )


def want_grab_approach(
    me: MapEntity,
    foe: MapEntity,
    *,
    grab_bias: float,
) -> bool:
    """Grab-walk is usually worse than punching from spacing — keep rare."""

    if grab_bias < 0.35:
        return False
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    return 18 <= dx <= 26 and dy <= 10


def held_enemy_entity(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> MapEntity | None:
    """Best entity representing the foe we are currently holding."""

    best: MapEntity | None = None
    best_d = 1e9
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.combat_phase == CombatPhase.GRABBED:
            d = abs(entity.map_x - me.map_x) + abs(entity.map_y - me.map_y)
            if d < best_d:
                best_d = d
                best = entity
    if best is not None:
        return best
    # Fallback: very close combatant (body-overlap grab without phase yet).
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.health is not None and entity.health <= 0:
            continue
        d = abs(entity.map_x - me.map_x) + abs(entity.map_y - me.map_y) * 0.5
        if d < 28 and d < best_d:
            best_d = d
            best = entity
    return best
