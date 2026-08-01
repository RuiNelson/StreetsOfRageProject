"""Grab / hold / throw decision trees for standard controls.

Live proof (paused Axel holding Signal, 2026-08-01):

- Player action byte at ``+$30`` was ``$60`` (hold/react family).
- ``held_type`` (``+$60``) and ``held_ptr`` (``+$5E``) were **zero**.
- Contact partner at ``+$4C`` pointed at the enemy slot.
- Enemy primary state ``$0500`` GRABBED, attacker ``+$3E`` = ``$B800`` (P1).
- **B alone** reduced enemy HP 4→2→0 (knees work).

The agent never entered the grab tree because it read action as the **low**
byte of a big-endian word at +$30 (always 0 when action is $60) and required
held_type. That is fixed in ``world_map``; this module detects hold via
action family $28–$3F / $44–$4F / $60–$6F, contact_ptr, held fields, or a
nearby GRABBED enemy linked to the player.

ROM attack uses press edges at +$55 — app must ``press_buttons`` for B pulses.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..memory_map import ADDR_P1_OBJECT_LO, ADDR_P2_OBJECT_LO
from ..phases import CombatPhase
from ..world_map import MapEntity
from .characters import CharacterProfile, DEFAULT_PROFILE
from .controls import Intent


WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

# Keep treating hold as active after RAM drops (anti-flicker).
HOLD_LATCH_TICKS = 18
# Live: B alone knees; mix B+back for throws after a few knees.
THROW_EVERY = 3


@dataclass(frozen=True, slots=True)
class GrabContext:
    holding: bool
    weapon: bool
    enemy_grab: bool
    held_type: int
    action_base: int
    airborne: bool
    hurt: bool


def is_grab_family(action_base: int) -> bool:
    """Player action families used while acquiring/holding/throwing."""

    base = action_base & 0xFE
    return (
        0x28 <= base <= 0x3F
        or 0x44 <= base <= 0x4F
        or 0x60 <= base <= 0x6F
    )


def context_from_player(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | None = None,
    *,
    player_index: int = 1,
) -> GrabContext:
    held_type = me.held_type & 0xFF
    held_ptr = me.held_ptr & 0xFFFF
    contact_ptr = me.contact_ptr & 0xFFFF
    action_grab = is_grab_family(me.action_base)
    phase_hold = me.combat_phase == CombatPhase.HOLDING
    linked = False
    if entities is not None:
        linked = _player_has_grabbed_enemy(me, entities, player_index=player_index)

    holding = (
        held_type != 0
        or held_ptr != 0
        or contact_ptr != 0
        or action_grab
        or phase_hold
        or me.is_grabbing
        or linked
    )
    weapon = 0x08 <= held_type <= 0x0C
    enemy_grab = holding and not weapon
    if action_grab and not weapon:
        enemy_grab = True
    if linked:
        enemy_grab = True
        holding = True
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


def _player_has_grabbed_enemy(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    player_index: int,
) -> bool:
    """True if an enemy is in GRABBED phase and linked to this player seat."""

    seat_lo = ADDR_P1_OBJECT_LO if player_index == 1 else ADDR_P2_OBJECT_LO
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.combat_phase != CombatPhase.GRABBED:
            continue
        # Attacker/holder low word points at player object.
        if (entity.attacker_ptr & 0xFFFF) == seat_lo:
            return True
        if (entity.target_ptr & 0xFFFF) == seat_lo:
            return True
        # Very close + grabbed (partner pointer may not be decoded yet).
        if abs(entity.map_x - me.map_x) < 48 and abs(entity.map_y - me.map_y) < 20:
            return True
    return False


@dataclass
class GrabMemory:
    """Latched hold so one-frame RAM glitches do not abort the attack loop."""

    latched: bool = False
    clear_ticks: int = 0
    pulse: int = 0

    def reset(self) -> None:
        self.latched = False
        self.clear_ticks = 0
        self.pulse = 0


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
    # Do not abort on is_hurt during hold-react ($60) — that state is not hurt.
    if ctx.hurt and not is_grab_family(me.action_base):
        memory.reset()
        return None

    if ctx.holding:
        memory.latched = True
        memory.clear_ticks = 0
    elif memory.latched:
        memory.clear_ticks += 1
        # Drop latch faster once action leaves hold families (enemy already gone).
        limit = 4 if not is_grab_family(me.action_base) else HOLD_LATCH_TICKS
        if memory.clear_ticks >= limit:
            memory.reset()
            return None
    else:
        memory.reset()
        return None

    prof = profile if profile is not None else DEFAULT_PROFILE
    memory.pulse += 1

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
    """B+away: opposite of facing (bit0 set = face left)."""

    del foe
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
    """Live: B alone knees the held foe. Mix B+back for throws.

    Always set attack=True so the app can fire VSync press edges every poll.
    """

    del tick
    back = throw_back_direction(
        me, progress_right=progress_right, crowd=crowd, foe=foe
    )
    # Mostly knees (proven to deal damage). Every Nth pulse: B+back throw.
    if memory.pulse % THROW_EVERY == 0:
        left = back < 0
        right = back > 0
        side = "L" if left else "R"
        return Intent(
            left=left,
            right=right,
            attack=True,
            note=(
                f"throw ({profile.name}) {side} "
                f"act=${me.action_state:02X} hold=${ctx.held_type:02X}"
            ),
        )
    return Intent(
        attack=True,
        note=(
            f"knee ({profile.name}) "
            f"act=${me.action_state:02X} hold=${ctx.held_type:02X}"
        ),
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
    del memory, tick
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
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=f"weapon throw ${held:02X}",
        )

    return Intent(attack=True, note=f"hold weapon ${held:02X}")


def want_grab_approach(
    me: MapEntity,
    foe: MapEntity,
    *,
    grab_bias: float,
) -> bool:
    if grab_bias < 0.35:
        return False
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    return 18 <= dx <= 26 and dy <= 10


def held_enemy_entity(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> MapEntity | None:
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
