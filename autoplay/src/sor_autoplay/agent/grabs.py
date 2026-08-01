"""Grab / hold / throw decision trees for standard controls.

ROM (``loc_00002D20`` / ``player_held_object_attack_input``):

- Grab input is only processed while player ``+$60`` (held type) is nonzero, and
  often only on certain animation frames.
- **Attack uses the press edge** at object ``+$55`` bit4 — not the held bit.
  Sticky ``hold_buttons`` with B continuously latched produces **one** edge then
  silence; the agent looked frozen while holding.
- Throw is **B + back** (opposite action-state facing bit0). Knees are B alone.

Policy: latch hold for several ticks (RAM can flicker), always request B with
back, and let the app fire **VSync-aligned** press pulses so edges land.
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

# Keep treating hold as active this many ticks after RAM drops (anti-flicker).
HOLD_LATCH_TICKS = 12
# After this many throw pulses still holding → also try plain knee (B, no dir).
KNEE_AFTER_THROWS = 6


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
    phase_hold = me.combat_phase == CombatPhase.HOLDING
    holding = (
        held_type != 0
        or held_ptr != 0
        or action_grab
        or phase_hold
        or me.is_grabbing
    )
    weapon = 0x08 <= held_type <= 0x0C
    enemy_grab = holding and (not weapon)
    if action_grab and not weapon:
        enemy_grab = True
    # Enemy type in +$60 is not a weapon — force enemy grab tree.
    if held_type != 0 and not weapon:
        enemy_grab = True
        holding = True
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
    """Latched hold so one-frame RAM glitches do not abort the throw loop."""

    latched: bool = False
    clear_ticks: int = 0
    throw_count: int = 0
    tick: int = 0

    def reset(self) -> None:
        self.latched = False
        self.clear_ticks = 0
        self.throw_count = 0
        self.tick = 0


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

    if ctx.holding:
        memory.latched = True
        memory.clear_ticks = 0
    elif memory.latched:
        memory.clear_ticks += 1
        if memory.clear_ticks >= HOLD_LATCH_TICKS:
            memory.reset()
            return None
        # Fall through: still finish throw while latched.
    else:
        memory.reset()
        return None

    prof = profile if profile is not None else DEFAULT_PROFILE
    memory.tick += 1

    if ctx.weapon and ctx.holding:
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
    foe: MapEntity | None = None,
) -> int:
    """Direction for B+away throw: opposite of player facing.

    ROM action-state bit0 set = face left → back is right. Do not use a free
    nearby foe here — that aimed the stick the wrong way while holding.
    """

    del foe  # facing only; held enemy is in front of facing
    if crowd >= 3:
        return 1 if progress_right else -1
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
    """Always attack while holding: B+back throw, occasional plain knee.

    App layer converts ``attack=True`` into a **press_buttons** pulse so the ROM
    sees a real +$55 edge every decision (sticky latch cannot do that alone).
    """

    del tick  # use memory.tick for cadence

    memory.throw_count += 1
    back = throw_back_direction(
        me, progress_right=progress_right, crowd=crowd, foe=foe
    )
    left = back < 0
    right = back > 0
    side = "L" if left else "R"

    # Every few throws: plain knee (B, no dir) in case back-throw is rejected.
    if memory.throw_count >= KNEE_AFTER_THROWS and (memory.throw_count % 4) == 0:
        return Intent(
            attack=True,
            note=f"knee ({profile.name}) hold=${ctx.held_type:02X}",
        )

    # Always request attack edge + back. Never idle / direction-only.
    return Intent(
        left=left,
        right=right,
        attack=True,
        note=f"throw ({profile.name}) {side} hold=${ctx.held_type:02X}",
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
        face_left = bool(me.action_state & 0x01)
        face_right = not face_left

    # Always pulse attack so app can fire edges (same as enemy grab).
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
            attack=True,
            note=f"weapon swing ${held:02X}",
        )

    if throwable:
        if blaze_weak and foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                attack=True,
                note=f"dump weapon ${held:02X}",
            )
        if foe is not None and (mid or in_melee):
            return Intent(
                left=face_left,
                right=face_right,
                attack=True,
                note=f"weapon use ${held:02X}",
            )
        if foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                attack=True,
                note=f"weapon throw ${held:02X}",
            )
        return Intent(attack=True, note=f"hold weapon ${held:02X}")

    # Unknown held type (enemy id in +$60): throw tree.
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


def notes_need_attack_pulse(note: str) -> bool:
    """True when the app must use press_buttons so +$55 sees an edge."""

    n = note.lower()
    return any(
        k in n
        for k in (
            "throw",
            "knee",
            "weapon swing",
            "weapon use",
            "weapon throw",
            "dump weapon",
            "hold weapon",
        )
    )
