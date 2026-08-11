"""Decode live combat phases from object RAM (ordinary enemies + bosses).

Ordinary-enemy primary state is a **byte** at ``+$30`` followed by flags at
``+$31``. Code commonly writes both at once as words such as
``$0100/$0300/$0400/$0500``; family dispatch tables also use states above
``$07`` for approach and attack moves.

Bosses use a **byte** at ``+$30`` (primary) and ``+$67`` (tactical substate).
"""

from __future__ import annotations

from enum import Enum, auto

from . import memory_map as mm


class CombatPhase(Enum):
    """Coarse combat phase used by the HUD map outlines."""

    UNKNOWN = auto()
    NORMAL = auto()  # free to act / approach
    ATTACKING = auto()  # committed attack — dangerous
    KNOCKDOWN = auto()  # punish window
    GRABBED = auto()  # held by a player
    BLOCKED = auto()  # stuck on geometry — free damage
    SCRIPTED = auto()  # police / remove / control
    DEATH = auto()  # dying — ignore as target
    RECOVERY = auto()  # boss hitstun / police reaction
    STUNNED = auto()  # ordinary enemy frozen on a timed stun — free hits
    CHARGE = auto()  # boss charge / clothesline commit
    HURT_PLAYER = auto()  # player hurt states
    HOLDING = auto()  # player holding weapon/enemy
    HELD_BY_ENEMY = auto()  # enemy has grabbed the player ($78-$7E)


# Player action dispatcher entries $78/$7A/$7C/$7E form the enemy-grab
# counter sequence. Facing occupies bit 0, so compare the even base action.
PLAYER_HELD_BY_ENEMY_ACTIONS = frozenset({0x78, 0x7A, 0x7C, 0x7E})


def player_is_held_by_enemy_action(action_byte: int) -> bool:
    return (action_byte & 0xFE) in PLAYER_HELD_BY_ENEMY_ACTIONS


_GARCIA_MOVE_PHASES: dict[int, dict[int, CombatPhase]] = {
    # ROM dispatcher tables at $D60E, $D9A2, $DD80 and $E32E. In particular,
    # type $22 state $09 runs $E124 (attack approach) and state $0A runs
    # $E190 (the active punch). Leaving these as UNKNOWN made the agent walk
    # directly into Round-1 Garcia punches.
    0x20: {
        0x09: CombatPhase.ATTACKING,
        0x0A: CombatPhase.ATTACKING,
        0x0C: CombatPhase.CHARGE,
    },
    0x21: {
        0x0A: CombatPhase.ATTACKING,
        0x0B: CombatPhase.CHARGE,
    },
    0x22: {
        0x09: CombatPhase.CHARGE,
        0x0A: CombatPhase.ATTACKING,
        # Dispatcher table $DD80 entry $0B -> $E20A. Live Round-1 RAM kept
        # outgoing damage $04 here even after health reached zero.
        0x0B: CombatPhase.ATTACKING,
        # $0F/$10 lead into $11 ($DF0A attack animation/contact path).
        # $13 ($DDE6) is the damaging special entry observed in Round 1.
        0x0F: CombatPhase.CHARGE,
        0x10: CombatPhase.CHARGE,
        0x11: CombatPhase.ATTACKING,
        0x13: CombatPhase.ATTACKING,
    },
    0x23: {
        0x09: CombatPhase.ATTACKING,
        0x0C: CombatPhase.CHARGE,
    },
    # Signal $24: $08 selects the attack, $09/$0A are its moving strike,
    # $0B/$0C are contact/throw paths, and $0D is recovery.
    0x24: {
        0x08: CombatPhase.CHARGE,
        0x09: CombatPhase.ATTACKING,
        0x0A: CombatPhase.ATTACKING,
        0x0B: CombatPhase.ATTACKING,
        0x0C: CombatPhase.ATTACKING,
        0x0D: CombatPhase.RECOVERY,
    },
}


def ordinary_enemy_phase(
    primary_state_word: int,
    *,
    type_id: int | None = None,
    health: int | None = None,
    police_special_active: bool = False,
) -> CombatPhase:
    """Map ordinary-enemy state/flags at ``+$30/$31`` to a combat phase.

    ``health`` and ``police_special_active`` are only consulted to tell the
    two meanings of state ``$0400`` apart -- see the ``ENEMY_ST_SCRIPTED``
    branch below. Omitting them keeps the conservative reading (SCRIPTED).
    """

    hi = primary_state_word & 0xFF00
    if hi == mm.ENEMY_ST_NORMAL or hi == 0x0000:
        return CombatPhase.NORMAL
    if hi == mm.ENEMY_ST_ALT:
        # $9B88 (ordinary_enemy_apply_contact_damage) *is* this state's own
        # per-frame handler, and all it does is count the stun timer +$50
        # down (`subq.b #1,$50(a0)`, seeded with $18 = 24 frames on the hit
        # that starts it) until it writes $0100 back and hands control to
        # the family AI again. So this is a timed hitstun the player caused
        # -- the enemy cannot act for its duration -- not merely the tail of
        # a move it chose, which is what RECOVERY means everywhere else here
        # (e.g. Signal's own $0D animation delay below).
        return CombatPhase.STUNNED
    if hi == mm.ENEMY_ST_KNOCKDOWN:
        return CombatPhase.KNOCKDOWN
    if hi == mm.ENEMY_ST_SCRIPTED:
        # Shared handler $A43E, every ordinary type's state-table entry 4,
        # serves two unrelated purposes (enemy-ai.md, "Collision, reactions,
        # grabs, and death"):
        #
        # - pepper-spray immobilization -- it loads +$50 = $A0 (160 frames)
        #   and counts it down to $0100 exactly like the hitstun above, a
        #   far longer free-hit window than any knockdown;
        # - police-special sweep removal, which forces the same $0400 with
        #   health $FFFF while the global special flag is up.
        #
        # Only the first is a stun. The second is the enemy being taken off
        # the board by the special and must stay SCRIPTED so nothing chases
        # or waits for it.
        if not police_special_active and (health is None or health != 0xFFFF):
            return CombatPhase.STUNNED
        return CombatPhase.SCRIPTED
    if hi == mm.ENEMY_ST_GRABBED:
        return CombatPhase.GRABBED
    if hi == mm.ENEMY_ST_DEATH:
        return CombatPhase.DEATH
    if hi == mm.ENEMY_ST_BLOCKED:
        return CombatPhase.BLOCKED
    if type_id is not None:
        family = _GARCIA_MOVE_PHASES.get(type_id & 0xFF)
        if family is not None:
            return family.get((primary_state_word >> 8) & 0xFF, CombatPhase.NORMAL)
    return CombatPhase.UNKNOWN


def boss_phase(
    *,
    type_id: int,
    primary_byte: int,
    tactical: int,
) -> CombatPhase:
    """Heuristic boss phase from primary byte + tactical ``+$67``.

    Exact move tables differ per family; nonzero tactical usually means a
    committed substate (approach fine-tuning, attack, or police latch).
    Abadede forces primary ``$06`` on hit/police; ``$0E`` is lethal.
    """

    p = primary_byte & 0xFF
    t = tactical & 0xFF

    # Shared death / hit patterns across later bosses and Abadede.
    if type_id == 0x30:  # Abadede
        if p in (0x0E,):
            return CombatPhase.DEATH
        if p in (0x06,):  # forced hit / police reaction path
            return CombatPhase.RECOVERY
        if p in (0x08, 0x0B):
            return CombatPhase.ATTACKING
        if t != 0:
            return CombatPhase.CHARGE
        return CombatPhase.NORMAL

    if type_id == 0x35:  # Mr. X
        if p >= 0x0C:
            return CombatPhase.DEATH
        if t != 0 or p in (0x04, 0x05, 0x06, 0x07, 0x08):
            return CombatPhase.ATTACKING
        return CombatPhase.NORMAL

    # Souther primary $02 is claw/contact even when +$67 is zero.
    if type_id == 0x55 and p == 0x02:
        return CombatPhase.ATTACKING

    # Antonio primary $02 ($171CC antonio_state2_close_strike, asm $16F0E):
    # a short committed action entered from state 1 on a target
    # proximity/velocity/facing gate (not a pure distance check like the
    # tactical $08 dash/boomerang commit below). Tactical is cleared to 0 on
    # entry, so without this the generic t!=0 heuristic below sees it as
    # NORMAL — a real blind spot, since one of the entry paths is the
    # target's X-velocity being exactly zero, which is the player's own
    # signature while throwing a stationary ground combo.
    if type_id == 0x56 and p == 0x02:
        return CombatPhase.ATTACKING

    # Onihime/Yasha (type $58) — ROM tables at $158D8 / $15A5E / $15BE0:
    #   primary $01 active combat: +$67 $00 idle, $01 chase/walk, $02 jump
    #   attack, $03 leap-to-grab. Only $02/$03 (and primary $02 commit) are
    #   damaging commits. Treating chase ($01) as ATTACKING made the agent
    #   perpetual-evade and never punch/jump/grab.
    if type_id == 0x58:
        if p == 0x02:
            return CombatPhase.ATTACKING  # $15D0C grab/throw commit
        if p == 0x0A:
            return CombatPhase.RECOVERY  # police special
        if p == 0x05 or p >= 0x0C:
            return CombatPhase.DEATH
        if p in (0x03, 0x04):
            return CombatPhase.RECOVERY  # hit reaction / recover → punish
        # Shared later-boss grabbee / throw cleanup — player is holding them.
        if p in (0x06, 0x07, 0x08, 0x09):
            return CombatPhase.GRABBED
        if p == 0x01:
            if t in (0x02, 0x03):
                return CombatPhase.ATTACKING  # jump attack / leap-to-grab
            return CombatPhase.NORMAL  # idle $00 or chase $01 — free to strike
        return CombatPhase.NORMAL

    # Later bosses $55-$58 (non-twin paths above): police reaction shared $0A
    if p == 0x0A:
        return CombatPhase.RECOVERY
    if p >= 0x0C:
        return CombatPhase.DEATH
    # Shared grabbee / throw cleanup while a player holds the boss body.
    # Must be GRABBED (not CHARGE) so hold detection / knee-suplex run.
    if type_id in (0x55, 0x56, 0x57, 0x58) and 0x06 <= p <= 0x09:
        return CombatPhase.GRABBED
    # Higher primary indices are usually attack/airborne families.
    if p >= 0x06:
        return CombatPhase.ATTACKING if t != 0 else CombatPhase.CHARGE
    if t != 0:
        # Antonio sets tactical $08 on a dash-like commit (asm $16E88).
        if t >= 0x06:
            return CombatPhase.CHARGE
        return CombatPhase.ATTACKING
    return CombatPhase.NORMAL


def player_phase(
    *,
    action_byte: int,
    held_type: int,
) -> CombatPhase:
    base = action_byte & 0xFE
    if player_is_held_by_enemy_action(action_byte):
        return CombatPhase.HELD_BY_ENEMY
    # Knockdown $50–$5F, ordinary throw air $70–$74, special-throw $82–$8F.
    if 0x50 <= base <= 0x5F or 0x70 <= base <= 0x74 or 0x82 <= base <= 0x8F:
        return CombatPhase.HURT_PLAYER
    if held_type:
        return CombatPhase.HOLDING
    if 0x18 <= base <= 0x1F or 0x20 <= base <= 0x27:
        return CombatPhase.ATTACKING
    # $28 grab acquire, $30–$3F hold moves, $44 throw family, $60 hold/react.
    if (
        0x28 <= base <= 0x3F
        or 0x44 <= base <= 0x4F
        or 0x60 <= base <= 0x6F
    ):
        return CombatPhase.HOLDING
    if 0x10 <= base <= 0x17:
        return CombatPhase.NORMAL  # jump — still actionable
    return CombatPhase.NORMAL


def phase_label(phase: CombatPhase) -> str:
    return {
        CombatPhase.UNKNOWN: "?",
        CombatPhase.NORMAL: "idle",
        CombatPhase.ATTACKING: "atk",
        CombatPhase.KNOCKDOWN: "down",
        CombatPhase.GRABBED: "held",
        CombatPhase.BLOCKED: "block",
        CombatPhase.SCRIPTED: "script",
        CombatPhase.DEATH: "die",
        CombatPhase.RECOVERY: "recov",
        CombatPhase.STUNNED: "stun",
        CombatPhase.CHARGE: "charge",
        CombatPhase.HURT_PLAYER: "hurt",
        CombatPhase.HOLDING: "hold",
        CombatPhase.HELD_BY_ENEMY: "enemy-hold",
    }.get(phase, "?")


def phase_color(phase: CombatPhase) -> str | None:
    """Optional marker outline tint for the HUD map."""

    return {
        CombatPhase.KNOCKDOWN: "#30d158",  # free punish
        CombatPhase.BLOCKED: "#64d2ff",
        CombatPhase.ATTACKING: "#ff453a",
        CombatPhase.CHARGE: "#ff9f0a",
        CombatPhase.GRABBED: "#bf5af2",
        CombatPhase.RECOVERY: "#ffd60a",
        CombatPhase.STUNNED: "#a3e635",  # free hits, like KNOCKDOWN but frozen
        CombatPhase.DEATH: "#636366",
        CombatPhase.SCRIPTED: "#8e8e93",
        CombatPhase.HELD_BY_ENEMY: "#ff375f",
    }.get(phase)


def decode_target_seat(target_ptr: int) -> int | None:
    """Return 1/2 if ``target_ptr`` is a player object low-word, else None."""

    lo = target_ptr & 0xFFFF
    if lo == mm.ADDR_P1_OBJECT_LO:
        return 1
    if lo == mm.ADDR_P2_OBJECT_LO:
        return 2
    return None


def is_punishable(phase: CombatPhase) -> bool:
    return phase in (
        CombatPhase.KNOCKDOWN,
        CombatPhase.BLOCKED,
        CombatPhase.RECOVERY,
        CombatPhase.STUNNED,
        CombatPhase.GRABBED,
    )


def is_dangerous(phase: CombatPhase) -> bool:
    return phase in (CombatPhase.ATTACKING, CombatPhase.CHARGE)


def should_ignore_as_target(phase: CombatPhase) -> bool:
    return phase in (CombatPhase.DEATH, CombatPhase.SCRIPTED)
