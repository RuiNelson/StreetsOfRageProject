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
from . import weapons as W
from .characters import CharacterProfile, DEFAULT_PROFILE
from .controls import Intent


WEAPON_KNIFE = W.WEAPON_KNIFE
WEAPON_BOTTLE = W.WEAPON_BOTTLE
WEAPON_BAT = W.WEAPON_BAT
WEAPON_PIPE = W.WEAPON_PIPE
WEAPON_PEPPER = W.WEAPON_PEPPER

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


# Partner-boost multi-frame phases (GrabMemory.partner_boost_phase).
PARTNER_BOOST_CROSSOVER = "crossover"
PARTNER_BOOST_AWAIT_BACK = "await_back"
PARTNER_BOOST_JUMP = "jump"
PARTNER_BOOST_AIR = "air_kick"

# Geometry for the higher co-op jump-kick after a partner vault (AISpec §1.4.3).
PARTNER_BOOST_FOE_DX_MIN = 36.0
PARTNER_BOOST_FOE_DX_MAX = 110.0
PARTNER_BOOST_FOE_LANE = 28.0
PARTNER_HOLD_BODY_X = 48.0
PARTNER_HOLD_BODY_Y = 20.0


@dataclass(frozen=True, slots=True)
class GrabContext:
    holding: bool
    weapon: bool
    enemy_grab: bool
    partner_grab: bool
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
    partner_grab = False
    if entities is not None:
        linked = _player_has_grabbed_enemy(me, entities, player_index=player_index)
        # Partner holds use the same action family as enemy holds. Detect the
        # other player body only when no reciprocal GRABBED enemy is linked.
        if not linked:
            partner_grab = held_partner_entity(me, entities) is not None

    weapon_type = 0x08 <= held_type <= 0x0C
    # Strong evidence only. +$4C is a general contact pointer, while +$5E
    # remains a pointer to the projectile after pepper spray/other weapons are
    # released and +$60 has already cleared. Neither pointer alone proves an
    # enemy hold. The live $60 hold is recognized by the GRABBED enemy's
    # reciprocal link; other grab layouts retain a non-weapon held_type.
    # Partner holds must not be classified as enemy_grab via a non-weapon
    # held_type residue.
    enemy_grab = linked or (
        held_type != 0 and not weapon_type and not partner_grab
    )
    # A live reciprocal GRABBED link is stronger evidence than +$60, which can
    # retain the previously carried weapon type after the player grabs a foe.
    weapon = weapon_type and not linked and not partner_grab
    holding = weapon or enemy_grab or partner_grab

    return GrabContext(
        holding=holding,
        weapon=weapon,
        enemy_grab=enemy_grab,
        partner_grab=partner_grab,
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
    # Partner-boost SM (AISpec §1.4.3): C vault → C jump → B air kick.
    partner_boost_phase: str = ""

    def reset(self) -> None:
        self.latched = False
        self.clear_ticks = 0
        self.pulse = 0
        self.last_input_tick = -10_000
        self.partner_boost_phase = ""


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
    both_agents: bool = False,
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
        memory.partner_boost_phase = ""
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

    # Partner hold (AISpec §1.4.3): never treat as enemy knee/throw by default.
    if ctx.partner_grab:
        memory.latched = True
        memory.clear_ticks = 0
        return _partner_hold_tree(
            me,
            memory,
            tick=tick,
            foe=foe,
            ally=ally,
            both_agents=both_agents,
        )

    if ctx.enemy_grab:
        memory.latched = True
        memory.clear_ticks = 0
        memory.partner_boost_phase = ""
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


def held_partner_entity(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> MapEntity | None:
    """Other player body latched in a hold with this seat (AISpec §1.4.3)."""

    if not is_grab_family(me.action_base) and me.action_base not in HOLD_INPUT_ACTIONS:
        # Still recognize mid-vault / air-boost frames if phase is active elsewhere.
        if not (0x76 <= me.action_base <= 0x80 or me.is_airborne):
            return None
    best: MapEntity | None = None
    best_d = 1e9
    for entity in entities:
        if entity.kind != "player":
            continue
        if entity.slot == me.slot:
            continue
        dx = abs(entity.map_x - me.map_x)
        dy = abs(entity.map_y - me.map_y)
        if dx > PARTNER_HOLD_BODY_X or dy > PARTNER_HOLD_BODY_Y:
            continue
        d = dx + dy * 0.5
        if d < best_d:
            best_d = d
            best = entity
    return best


def release_grab_intent(
    me: MapEntity,
    held_body: MapEntity | None,
) -> Intent:
    """Walk away from the held body to drop the grab (AISpec §1.4.2)."""

    if held_body is not None:
        dx = held_body.map_x - me.map_x
    else:
        # Held body is usually in front; walk opposite of facing.
        dx = -1.0 if bool(me.action_state & 0x01) else 1.0
    if dx >= 0:
        return Intent(left=True, note="release grab away L")
    return Intent(right=True, note="release grab away R")


def want_partner_boost(
    me: MapEntity,
    foe: MapEntity | None,
    *,
    both_agents: bool,
) -> bool:
    """True when a partner vault → high jump-kick is tactically useful."""

    if not both_agents:
        return False
    if foe is None or foe.kind not in ("enemy", "boss"):
        return False
    if foe.is_defeated or foe.health == 0:
        return False
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    return (
        PARTNER_BOOST_FOE_DX_MIN <= dx <= PARTNER_BOOST_FOE_DX_MAX
        and dy <= PARTNER_BOOST_FOE_LANE
    )


def is_intentional_partner_hold_attack(intent: Intent) -> bool:
    """Co-op gate allowlist for intentional partner-hold tools (boost kick)."""

    note = intent.note or ""
    return note.startswith("partner boost")


def _partner_hold_tree(
    me: MapEntity,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    ally: MapEntity | None,
    both_agents: bool,
) -> Intent:
    """Partner body hold: release by walking away, or high jump-kick boost."""

    # Continue an in-flight boost even if hold evidence flickered one sample.
    if memory.partner_boost_phase == PARTNER_BOOST_AIR or (
        memory.partner_boost_phase and me.is_airborne
    ):
        memory.partner_boost_phase = PARTNER_BOOST_AIR
        if me.is_airborne:
            if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
                return Intent(note="await partner boost kick")
            memory.last_input_tick = tick
            return Intent(attack=True, note="partner boost air kick")
        memory.partner_boost_phase = ""
        return release_grab_intent(me, ally)

    boost = bool(memory.partner_boost_phase) or want_partner_boost(
        me, foe, both_agents=both_agents
    )
    if boost:
        return _partner_boost_step(me, memory, tick=tick, foe=foe, ally=ally)

    # Default: abandon the grab without damaging the partner (walk away).
    memory.partner_boost_phase = ""
    return release_grab_intent(me, ally)


def _partner_boost_step(
    me: MapEntity,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    ally: MapEntity | None,
) -> Intent:
    """C vault to opposite side → C jump off → B in free-flight."""

    del foe
    action = me.action_base
    phase = memory.partner_boost_phase

    if phase == "" or phase == PARTNER_BOOST_CROSSOVER:
        if action == 0x66:
            memory.partner_boost_phase = PARTNER_BOOST_JUMP
        elif action in (0x76, 0x80):
            memory.partner_boost_phase = PARTNER_BOOST_AWAIT_BACK
            return Intent(note="partner boost vault")
        elif action == 0x60:
            if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
                return Intent(note="await partner boost crossover")
            memory.last_input_tick = tick
            memory.partner_boost_phase = PARTNER_BOOST_AWAIT_BACK
            return Intent(jump=True, note="partner boost crossover")
        else:
            # Unexpected frame: fall back to release rather than knee the ally.
            memory.partner_boost_phase = ""
            return release_grab_intent(me, ally)

    if phase == PARTNER_BOOST_AWAIT_BACK:
        if action in (0x76, 0x80):
            return Intent(note="partner boost vault")
        if action == 0x66:
            memory.partner_boost_phase = PARTNER_BOOST_JUMP
        elif action == 0x60:
            if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
                return Intent(note="await partner boost crossover")
            memory.last_input_tick = tick
            return Intent(jump=True, note="partner boost crossover retry")
        else:
            memory.partner_boost_phase = ""
            return release_grab_intent(me, ally)

    if phase == PARTNER_BOOST_JUMP or action == 0x66:
        if me.is_airborne:
            memory.partner_boost_phase = PARTNER_BOOST_AIR
            if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
                return Intent(note="await partner boost kick")
            memory.last_input_tick = tick
            return Intent(attack=True, note="partner boost air kick")
        if action == 0x66 or action in HOLD_INPUT_ACTIONS:
            if tick - memory.last_input_tick < GRAB_INPUT_RETRY_TICKS:
                return Intent(note="await partner boost jump")
            memory.last_input_tick = tick
            memory.partner_boost_phase = PARTNER_BOOST_AIR
            return Intent(jump=True, note="partner boost jump")
        memory.partner_boost_phase = ""
        return release_grab_intent(me, ally)

    memory.partner_boost_phase = ""
    return release_grab_intent(me, ally)


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
    force_throw = coop.ally_in_attack_bubble(
        me, ally, max_x=coop.ALLY_BODY_X + 2.0, max_y=coop.ALLY_LANE_HALF
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
    """Use held weapons with ROM range/damage geometry (see ``weapons``).

    - Bat/pipe: B only when ``|ΔX| ≤ 36`` and lane ``|ΔY| ≤ 12``.
    - Knife: same B; ROM ``$3084`` picks melee ``$46`` if foe in front ≤144 px,
      else throw ``$44``. Policy stabs in-cone; throws only when past the cone
      and a one-shot kill (or we are not conserving the knife); otherwise walks
      in for multi-hit stabs.
    - Pepper: B throw in a shorter corridor (≤100 px) + immobilize value.
    - Bottle: not attack-thrown; dump only at melee body range.
    """

    del tick
    held = ctx.held_type & 0xFF
    if not W.is_weapon_type(held):
        return None

    melee = W.is_melee_weapon(held)
    throwable = W.is_throw_weapon(held)
    blaze_weak = held in profile.weak_weapons
    dmg = W.damage_of(held)

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
    abs_dx = abs(dx)
    abs_dy = abs(dy)
    if not W.in_weapon_lane(dy):
        return None
    # Desired facing toward the foe (Intent will turn if needed).
    if dx < 0:
        want_left, want_right = True, False
    elif dx > 0:
        want_left, want_right = False, True
    else:
        want_left = bool(me.action_state & 0x01)
        want_right = not want_left
    # ROM facing: action +$30 bit 0 set = facing left.
    current_face_left = bool(me.action_state & 0x01)
    face_ok = W.facing_toward(dx, current_face_left)
    face_left, face_right = want_left, want_right

    def _ally_blocks(*, thrown: bool) -> bool:
        # Never swing or throw near a co-op partner (SoR1 friendly fire).
        return coop.ally_in_attack_bubble(
            me,
            ally,
            max_x=coop.ALLY_THROWN_RANGE if thrown else coop.ALLY_MELEE_RANGE,
        )

    # --- Bat / steel pipe: origin reach 36 px (live Axel) ---
    if melee:
        if not W.melee_can_connect(abs_dx, abs_dy):
            return None
        if _ally_blocks(thrown=False):
            return None
        if not face_ok:
            return Intent(
                left=face_left,
                right=face_right,
                note=f"weapon face ${held:02X} d={dmg}",
            )
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=f"weapon swing ${held:02X} d={dmg} r≤{W.MELEE_ORIGIN_REACH:.0f}",
        )

    # --- Knife: same B → ROM $46 melee in cone, $44 throw outside ---
    if held == W.WEAPON_KNIFE:
        foe_hp = foe.health if foe.health is not None else None
        mode = W.knife_mode(abs_dx, abs_dy, foe_health=foe_hp)
        if mode is None:
            # Out of band, or past cone with multi-hit foe: free combat closes.
            return None
        if _ally_blocks(thrown=(mode == "throw")):
            return None
        if not face_ok:
            return Intent(
                left=face_left,
                right=face_right,
                note=f"weapon face knife d={dmg}",
            )
        if mode == "melee":
            hits = W.hits_to_kill(foe_hp, held) if foe_hp else 0
            return Intent(
                left=face_left,
                right=face_right,
                attack=True,
                note=(
                    f"weapon attack knife d={dmg} "
                    f"dx={abs_dx:.0f}≤{W.KNIFE_MELEE_SCAN_X}"
                    + (f" hits≈{hits}" if hits else "")
                ),
            )
        # throw: past $90 scan, within flight envelope, preferably one-shot
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=(
                f"weapon throw knife d={dmg} "
                f"dx={abs_dx:.0f}≤{W.KNIFE_THROW_MAX:.0f}"
            ),
        )

    # --- Pepper: throw corridor + immobilize ---
    if held == W.WEAPON_PEPPER:
        if not W.pepper_should_throw(abs_dx, abs_dy):
            return None
        if _ally_blocks(thrown=True):
            return None
        if not face_ok:
            return Intent(
                left=face_left,
                right=face_right,
                note=f"weapon face pepper d={dmg}",
            )
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=(
                f"weapon throw pepper d={dmg} "
                f"stun={W.PEPPER_IMMOBILIZE_FRAMES}f"
            ),
        )

    # --- Bottle: not attack-thrown; dump only at melee ---
    if held == W.WEAPON_BOTTLE:
        if not W.bottle_should_dump(abs_dx, abs_dy):
            return None
        if _ally_blocks(thrown=False):
            return None
        if not face_ok:
            return Intent(
                left=face_left,
                right=face_right,
                note=f"weapon face bottle d={dmg}",
            )
        tag = "dump" if blaze_weak else "use"
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=f"weapon {tag} bottle d={dmg}",
        )

    return None


def want_grab_approach(
    me: MapEntity,
    foe: MapEntity,
    *,
    grab_bias: float,
) -> bool:
    """True when geometry is in the body-grab band for a high grab-bias plan."""

    if grab_bias < 0.35:
        return False
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    # Slightly wider band so Nora grab pressure keeps walking until contact.
    return 12 <= dx <= 28 and dy <= 12


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
