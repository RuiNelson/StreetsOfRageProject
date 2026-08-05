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
    """Coarse combat phase used by the agent and HUD."""

    UNKNOWN = auto()
    NORMAL = auto()  # free to act / approach
    ATTACKING = auto()  # committed attack — dangerous
    KNOCKDOWN = auto()  # punish window
    GRABBED = auto()  # held by a player
    BLOCKED = auto()  # stuck on geometry — free damage
    SCRIPTED = auto()  # police / remove / control
    DEATH = auto()  # dying — ignore as target
    RECOVERY = auto()  # boss hitstun / police reaction
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
) -> CombatPhase:
    """Map ordinary-enemy state/flags at ``+$30/$31`` to a combat phase."""

    hi = primary_state_word & 0xFF00
    if hi == mm.ENEMY_ST_NORMAL or hi == 0x0000:
        return CombatPhase.NORMAL
    if hi == mm.ENEMY_ST_ALT:
        # Shared $9B36 contact/reaction handling. It is a good follow-up window,
        # but not evidence that the enemy is starting another family move.
        return CombatPhase.RECOVERY
    if hi == mm.ENEMY_ST_KNOCKDOWN:
        return CombatPhase.KNOCKDOWN
    if hi == mm.ENEMY_ST_SCRIPTED:
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
        CombatPhase.RECOVERY: "stun",
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
        CombatPhase.GRABBED,
    )


def is_dangerous(phase: CombatPhase) -> bool:
    return phase in (CombatPhase.ATTACKING, CombatPhase.CHARGE)


def should_ignore_as_target(phase: CombatPhase) -> bool:
    return phase in (CombatPhase.DEATH, CombatPhase.SCRIPTED)
