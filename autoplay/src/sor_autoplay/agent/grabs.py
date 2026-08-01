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
from ..phases import CombatPhase, is_dangerous
from ..world_map import MapEntity
from . import coop
from .characters import CharacterProfile, DEFAULT_PROFILE
from .controls import Intent


WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

# Keep treating a proven hold as active through one missed observer sample.
# A longer latch feeds its own B presses back into the $60-$6F reaction family
# after the held enemy has died, producing an empty knee/throw loop.
HOLD_LATCH_TICKS = 2
# Live: B alone knees; mix B+back for throws after a few knees.
THROW_EVERY = 3
GRAB_INPUT_RETRY_TICKS = 4
HOLD_INPUT_ACTIONS = frozenset({0x28, 0x4A, 0x60, 0x66})
GRAB_ANIMATION_ACTIONS = frozenset({0x62, 0x64, 0x68, 0x6A, 0x6C, 0x6E})

# Enemy-held player sequence, indexed by player action +$30:
# $78 acquire -> $7A held -> C -> $7C crossover -> $7A with +$58.bit7 ->
# B -> $7E counter throw. This is a two-edge protocol, not a B+C chord.
ENEMY_HOLD_ACQUIRE_ACTION = 0x78
ENEMY_HOLD_ACTION = 0x7A
ENEMY_HOLD_CROSSOVER_ACTION = 0x7C
ENEMY_HOLD_COUNTER_THROW_ACTION = 0x7E
ENEMY_HOLD_ACTIONS = frozenset(
    {
        ENEMY_HOLD_ACQUIRE_ACTION,
        ENEMY_HOLD_ACTION,
        ENEMY_HOLD_CROSSOVER_ACTION,
        ENEMY_HOLD_COUNTER_THROW_ACTION,
    }
)
ENEMY_GRAB_COUNTER_WINDOW = 0x80  # player +$58 bit 7


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
    linked = False
    if entities is not None:
        linked = _player_has_grabbed_enemy(me, entities, player_index=player_index)

    weapon_type = 0x08 <= held_type <= 0x0C
    # Strong evidence only. +$4C is a general contact pointer, while +$5E
    # remains a pointer to the projectile after pepper spray/other weapons are
    # released and +$60 has already cleared. Neither pointer alone proves an
    # enemy hold. The live $60 hold is recognized by the GRABBED enemy's
    # reciprocal link; other grab layouts retain a non-weapon held_type.
    enemy_grab = linked or (held_type != 0 and not weapon_type)
    # A live reciprocal GRABBED link is stronger evidence than +$60, which can
    # retain the previously carried weapon type after the player grabs a foe.
    weapon = weapon_type and not linked
    holding = weapon or enemy_grab

    return GrabContext(
        holding=holding,
        weapon=weapon,
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
        if entity.is_defeated:
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
    last_input_tick: int = -10_000

    def reset(self) -> None:
        self.latched = False
        self.clear_ticks = 0
        self.pulse = 0
        self.last_input_tick = -10_000


@dataclass
class EnemyGrabEscapeMemory:
    """Retry guard for the ROM-confirmed enemy-grab counter protocol."""

    active: bool = False
    last_command: str = ""
    last_input_tick: int = -10_000

    def reset(self) -> None:
        self.active = False
        self.last_command = ""
        self.last_input_tick = -10_000


def decide_enemy_grab_escape(
    me: MapEntity,
    memory: EnemyGrabEscapeMemory,
    *,
    tick: int,
) -> Intent | None:
    """Own $78-$7E and execute C, then B in the eight-tick counter window."""

    action = me.action_base
    if action not in ENEMY_HOLD_ACTIONS:
        memory.reset()
        return None

    memory.active = True
    if action == ENEMY_HOLD_ACQUIRE_ACTION:
        return Intent(note=f"enemy grab acquire ${me.action_state:02X}")
    if action == ENEMY_HOLD_CROSSOVER_ACTION:
        return Intent(note=f"enemy grab crossover ${me.action_state:02X}")
    if action == ENEMY_HOLD_COUNTER_THROW_ACTION:
        return Intent(note=f"enemy grab counter throw ${me.action_state:02X}")

    command = "throw" if me.action_flags & ENEMY_GRAB_COUNTER_WINDOW else "jump"
    if (
        command == memory.last_command
        and tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS
    ):
        return Intent(note=f"await enemy grab {command} ${me.action_state:02X}")

    memory.last_command = command
    memory.last_input_tick = tick
    if command == "throw":
        return Intent(attack=True, note="escape enemy grab counter throw")
    return Intent(jump=True, note="escape enemy grab crossover")


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
    ally: MapEntity | None = None,
) -> Intent | None:
    # Do not abort on is_hurt during hold-react ($60) — that state is not hurt.
    if ctx.hurt and not is_grab_family(me.action_base):
        memory.reset()
        return None

    # Live orphan-contact recovery: after a defeated enemy disappears, action
    # $60 can retain only its stale +$4C pointer. Movement leaves the player
    # frozen indefinitely; one B edge selects $6A and returns to idle $02.
    # Restrict this to exact $60 so the resulting $6A transition is not fed
    # another artificial knee/throw pulse.
    if not ctx.holding and me.action_base in HOLD_INPUT_ACTIONS:
        if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
            return Intent(note=f"await orphan grab ${me.action_state:02X}")
        memory.last_input_tick = tick
        note = (
            "release stale contact"
            if me.action_base == 0x60 and me.contact_ptr
            else f"resolve orphan grab ${me.action_state:02X}"
        )
        return Intent(attack=True, note=note)

    prof = profile if profile is not None else DEFAULT_PROFILE

    # Player +$60 is a stable carried-weapon type, unlike the transient enemy
    # grab evidence that the latch exists to bridge. Never feed a missing
    # weapon sample through the enemy knee/throw tree.
    if ctx.weapon:
        memory.reset()
        return _weapon_tree(
            me, ctx, tick=tick, foe=foe, profile=prof, ally=ally
        )

    if ctx.enemy_grab:
        memory.latched = True
        memory.clear_ticks = 0
    elif memory.latched:
        memory.clear_ticks += 1
        if memory.clear_ticks >= HOLD_LATCH_TICKS:
            memory.reset()
            return None
    else:
        memory.reset()
        return None

    return _enemy_grab_tree(
        me,
        ctx,
        memory,
        tick=tick,
        foe=foe,
        progress_right=progress_right,
        crowd=crowd,
        profile=prof,
        ally=ally,
    )


def throw_back_direction(
    me: MapEntity,
    *,
    progress_right: bool = True,
    crowd: int = 0,
    foe: MapEntity | None = None,
    ally: MapEntity | None = None,
) -> int:
    """B+away: opposite of facing (bit0 set = face left).

    When a live co-op partner sits nearby, prefer the side that does not
    fling the held body into them (SoR1 friendly fire on throws).
    """

    del foe
    if crowd >= 3:
        default = 1 if progress_right else -1
    elif me.action_state & 0x01:
        default = 1
    else:
        default = -1
    return coop.throw_direction_away_from_ally(
        me, ally, default_dir=default
    )


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
    ally: MapEntity | None = None,
) -> Intent:
    """Live: B alone knees the held foe. Mix B+back for throws."""

    # B/C edges are accepted only in the stable front/back hold actions. The
    # baseline trace showed repeated B presses through $6A/$63 animations,
    # keeping the player stuck after the enemy was already dead.
    if me.action_base not in HOLD_INPUT_ACTIONS:
        return Intent(note=f"grab anim ${me.action_state:02X}")
    if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
        return Intent(note=f"await grab input ${me.action_state:02X}")
    memory.last_input_tick = tick
    memory.pulse += 1

    if me.action_base == 0x66:
        return Intent(
            attack=True,
            note=f"suplex ({profile.name}) act=${me.action_state:02X}",
        )

    back = throw_back_direction(
        me,
        progress_right=progress_right,
        crowd=crowd,
        foe=foe,
        ally=ally,
    )
    # Mostly knees (proven to deal damage). Every Nth pulse: B+back throw.
    # If a co-op partner is body-overlapped on the hold, prefer an immediate
    # away throw rather than kneeing into them (SoR1 friendly fire).
    force_throw = coop.attack_would_hit_ally(
        me, ally, max_range=coop.ALLY_BODY_X + 2.0
    )
    if force_throw or crowd >= 2 or memory.pulse % THROW_EVERY == 0:
        left = back < 0
        right = back > 0
        side = "L" if left else "R"
        note = (
            f"throw clear of ally {side}"
            if force_throw
            else (
                f"throw ({profile.name}) {side} "
                f"act=${me.action_state:02X} hold=${ctx.held_type:02X}"
            )
        )
        return Intent(
            left=left,
            right=right,
            attack=True,
            note=note,
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
    *,
    tick: int,
    foe: MapEntity | None,
    profile: CharacterProfile,
    ally: MapEntity | None = None,
) -> Intent | None:
    del tick
    held = ctx.held_type
    melee = held in (WEAPON_BAT, WEAPON_PIPE)
    throwable = held in (WEAPON_KNIFE, WEAPON_BOTTLE, WEAPON_PEPPER)
    blaze_weak = held in profile.weak_weapons

    # The ROM's held-weapon jump family ($3C-$42) is owned by the airborne
    # policy. It steers the evasion without manufacturing an unsupported
    # weapon attack edge in flight.
    if ctx.airborne:
        return None

    # A held weapon's input loop is active only in ordinary ground actions or
    # its ROM-specific ready family ($30-$3A). Do not hammer B throughout
    # $44/$6x attack animations: besides being useless, that was the visible
    # "furious" repeated attack behaviour.
    action = me.action_base
    input_ready = 0x02 <= action <= 0x0E or 0x30 <= action <= 0x3A
    if not input_ready:
        dx = 0.0 if foe is None else foe.map_x - me.map_x
        face_left = dx < 0 or (dx == 0 and bool(me.action_state & 0x01))
        face_right = not face_left
        return Intent(
            left=face_left,
            right=face_right,
            note=f"weapon anim ${held:02X} act=${me.action_state:02X}",
        )

    # A carried weapon is inventory, not an instruction to attack every poll.
    # Let normal stage/combat policy run until a live foe is in a usable box.
    # Dangerous attacks also return to combat policy so family counters (for
    # example jumping Signal's sweep) take priority over a weapon swing. This
    # is deliberately after the animation lock above.
    if foe is None or is_dangerous(foe.combat_phase):
        return None

    dx = foe.map_x - me.map_x
    dy = foe.map_y - me.map_y
    if abs(dy) > 12:
        return None
    if dx < 0:
        face_left, face_right = True, False
    elif dx > 0:
        face_left, face_right = False, True
    else:
        face_left = bool(me.action_state & 0x01)
        face_right = not face_left
    in_melee = abs(dx) <= 36
    mid = 20 <= abs(dx) <= 100

    # Never swing or throw a weapon through a co-op partner (SoR1 friendly fire).
    if coop.attack_would_hit_ally(
        me,
        ally,
        face_left=face_left,
        thrown=throwable,
        max_range=coop.ALLY_THROWN_RANGE if throwable else coop.ALLY_MELEE_RANGE,
    ):
        return None

    if melee:
        if not in_melee:
            return None
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=f"weapon swing ${held:02X}",
        )

    if throwable:
        if not (mid or in_melee):
            return None
        if blaze_weak:
            return Intent(
                left=face_left,
                right=face_right,
                attack=True,
                note=f"dump weapon ${held:02X}",
            )
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=f"weapon use ${held:02X}",
        )

    return None


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
        if entity.is_defeated:
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
        if entity.is_defeated or entity.health == 0:
            continue
        d = abs(entity.map_x - me.map_x) + abs(entity.map_y - me.map_y) * 0.5
        if d < 28 and d < best_d:
            best_d = d
            best = entity
    return best
