"""``Enemy`` observation token and its per-type/boss-family subclasses.

Per ``ai-analysis/enemy-ai.md`` and ``world_map.py``'s ``MapEntity``: ordinary
enemies ($20-$2A) all share one object layout, so only Jack ($27) needs an
extra field (``family_state`` bit 0, weapon attached). Every boss is a direct
``Boss`` subclass. The tactical/pair_role/boss_dist_*/mode_flags/
target_unavailable/phase_timer/ground_z/vel_* fields live on ``Boss`` with
defaults: Abadede/Mr. X use a bespoke target pointer and leave them at their
defaults (meaningless there), while Souther/Antonio/Bongo/Onihime-Yasha (all
sharing type $58, distinguished only by ``pair_role`` at runtime) fully
populate them.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from ...phases import CombatPhase
from .character import Character
from .tokens import Inferred


@dataclass(frozen=True, slots=True, kw_only=True)
class Enemy(Character):
    """A hostile on-screen actor that can be hit and defeated."""

    type_id: int
    targets_player: int | None  # 1 or 2, or None — from MapEntity.targets_player
    # Ordinary-enemy velocity only (Grunt family); Boss populates its own
    # vel_x/vel_z below from different offsets -- see memory_map.py's
    # OBJ_VEL_X_ORDINARY/OBJ_VEL_LANE_ORDINARY.
    grunt_vel_x: float = 0.0  # +$1C signed 16.16, ordinary enemies only
    grunt_vel_y: float = 0.0  # +$20 signed 16.16 (lane), ordinary enemies only


@dataclass(frozen=True, slots=True, kw_only=True)
class Grunt(Enemy, ABC):
    """An ordinary (non-boss) enemy.

    ``stun_timer`` is the ROM's own remaining-stun counter at ``+$50``,
    in 60 Hz frames. Only ordinary enemies have it: the two handlers that
    seed and decrement it ($9B88 for the $18-frame hitstun, $A43E for the
    $A0-frame pepper-spray immobilization) are ordinary-enemy state-table
    entries, and every boss family runs its own hit reactions instead.
    """

    stun_timer: int = 0  # +$50, frames left; only meaningful while stunned

    @property
    def is_stunned(self) -> bool:
        """True while the enemy is frozen on a timed stun (see ``stun_timer``).

        A stun is not just a punish window: unlike KNOCKDOWN (which ends in
        a wake-up with invulnerability) or RECOVERY (the tail of a move the
        enemy chose), the enemy is standing, hittable and unable to act for
        the whole of ``stun_timer``.
        """

        return self.combat_phase is CombatPhase.STUNNED


@dataclass(frozen=True, slots=True, kw_only=True)
class Garcia(Grunt):
    """Garcia ordinary enemy (types $20-$23)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Signal(Grunt):
    """Signal ordinary enemy (type $24)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HakuRo(Grunt):
    """HakuRo ordinary enemy (types $25, $2A)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Nora(Grunt):
    """Nora ordinary enemy (type $26)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Jack(Grunt):
    """Jack ordinary enemy (type $27); may carry a weapon."""

    has_projectile: bool  # family_state bit 0 -- "weapon attached"


@dataclass(frozen=True, slots=True, kw_only=True)
class Boss(Enemy, ABC):
    """A boss enemy with its own tactical state and behaviour fields."""

    tactical: int = 0  # boss +$67 substate; Abadede police latch when set
    pair_role: int = 0  # later-type +$5D (1/2) twin role when kind==boss
    boss_dist_x: int = 0  # later-type +$50 abs X to target
    boss_dist_lane: int = 0  # later-type +$52 abs lane to target
    mode_flags: int = 0  # later-type +$7B; twin bit1 = grab/throw AI path
    target_unavailable: int = 0  # later-type +$77 from $179F8
    phase_timer: int = 0  # later-type +$78 jump/throw timeline counter
    ground_z: int | None = None  # later-type +$4C ground/landing height
    vel_x: float = 0.0  # +$20 signed 16.16, ROM units per tick
    vel_z: float = 0.0  # +$24 signed 16.16, ROM units per tick


@dataclass(frozen=True, slots=True, kw_only=True)
class Abadede(Boss):
    """Abadede boss (type $30)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MrX(Boss):
    """Mr. X boss (type $35)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Souther(Boss):
    """Souther boss (type $55)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Antonio(Boss):
    """Antonio boss (type $56)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Bongo(Boss):
    """Bongo boss (type $57)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Onihime(Boss):
    """Onihime/Yasha twin boss (type $58).

    The ROM runs two same-type instances (Onihime + Yasha), distinguished at
    runtime by pair_role, not by different type ids.
    """


_TYPE_TO_CLASS: dict[int, type[Enemy]] = {
    0x20: Garcia,
    0x21: Garcia,
    0x22: Garcia,
    0x23: Garcia,
    0x24: Signal,
    0x25: HakuRo,
    0x2A: HakuRo,
    0x26: Nora,
    0x27: Jack,
    0x30: Abadede,
    0x35: MrX,
    0x55: Souther,
    0x56: Antonio,
    0x57: Bongo,
    0x58: Onihime,
}


def enemy_class_for_type(type_id: int) -> type[Enemy]:
    """Map a MapEntity.type_id to its concrete Enemy/Boss subclass.

    Falls back to the generic Enemy for anything unrecognized, matching
    object_catalog.py's own "unknown ranges still plot" fallback philosophy.
    """

    return _TYPE_TO_CLASS.get(type_id & 0xFF, Enemy)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosingEnemy(Inferred):
    """A Grunt closing fast enough on X and lane to reach rear-attack range
    within the next few ticks, even though its *current* position is not
    there yet.

    Produced by ``inference.check_for_closing_enemies`` from a Grunt's
    ``grunt_vel_x``/``grunt_vel_y`` (never for a Boss -- out of scope). The
    band-check helpers in ``decide.py`` are purely instantaneous-position, so
    a fast diagonal closer can go from "outside every reaction band" to
    "already attacking" between two polls with no warning; this token is the
    early-warning signal that lets ``could_rear_attack`` react a few ticks
    ahead of the raw position check. Reference-only per AI.md -- consumers
    look up the full Enemy via ``find(context, Enemy, slot=...)``.
    """

    slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetInReach(Inferred, ABC):
    """An enemy that one of the actor's moves can reach *right now*.

    Produced by ``inference.check_for_targets_in_reach`` once per (actor,
    enemy) pair and per move family, from the geometry in ``ai/reach.py``.
    Reference-only: both ends are slot references, resolved with
    ``find(context, Enemy, slot=...)`` / ``_find_actor``.

    Every concrete subclass answers a different move's question, which is
    why this is a hierarchy rather than one token with a "kind" field: a
    ``could_*`` asks for exactly the band its own move uses, and the
    inference stage computes each band once per tick instead of every
    ``could_*`` and every ``_emergency_*`` recomputing it from raw
    coordinates.
    """

    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class InPunchReach(TargetInReach):
    """A forward strike (B) would connect with this enemy now.

    Produced by ``inference.check_for_targets_in_reach`` when the enemy is
    inside ``reach.in_punch_band`` *and* in front of the actor (within
    ``reach.PUNCH_BEHIND_TOLERANCE_X``) -- the raw band alone ignores facing
    and describes a dead zone the actor cannot actually hit.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class InRearReach(TargetInReach):
    """The ``$322A`` rear/escape chord would reach this enemy now.

    Produced by ``inference.check_for_targets_in_reach`` when the enemy is
    inside ``reach.in_rear_band`` -- the chord's real reach on the enemy's
    own side (behind vs front), never the union of both, since Axel and
    Blaze have zero forward reach.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class InJumpAttackReach(TargetInReach):
    """A jump kick would cover the gap to this enemy now.

    Produced by ``inference.check_for_targets_in_reach`` when the enemy is
    in front, in lane, beyond the actor's punch outer edge and inside the
    kick's own free-flight range (``reach.in_jump_attack_band``).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionableTarget(TargetInReach):
    """An enemy some already-available attack would really fire on now.

    Produced by ``inference.check_for_targets_in_reach`` when
    ``reach.enemy_actionable`` holds: inside the punch reach, or inside the
    rear band *and* the chord is the right answer there
    (``reach.rear_attack_is_warranted``). This is the "stop walking, you can
    already hit it" signal ``could_walk_to_near_enemy`` consumes, and it is
    deliberately narrower than the union of the bands above.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class InGrabReach(TargetInReach):
    """Walking into this enemy would take a hold of it.

    Produced by ``inference.check_for_targets_in_reach`` when
    ``reach.grab_would_connect`` holds -- in front, in lane, and inside the
    actor's own close-combat range. The hold itself is a contact result, not
    an input (see ``reach.GRAB_RANGE_Y``), so "in reach" here means "one
    walk-in away", not "one button away".
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class GrabOpportunity(Inferred, ABC):
    """Holding this enemy is worth more right now than hitting it.

    Abstract because the situations that make a grab pay off are unrelated
    to each other and rank differently; each concrete subclass is one such
    situation, per ``AI.md``'s "subclasses, not discriminator fields". All of
    them are produced by ``inference.check_for_grab_opportunities``, and only
    for a ``Grunt``: boss grabs exist in the ROM (types $55-$58 have the
    shared grabbee states) but bespoke boss tactics are out of scope.

    Reference-only, like the ``TargetInReach`` family: both ends are slot
    references. ``decide.could_grab_enemy`` pairs one of these with an
    ``InGrabReach`` for the same pair -- the opportunity says it is *worth*
    grabbing, the reach token says it is *possible*.
    """

    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GrabToClearRear(GrabOpportunity):
    """A hold on this enemy is the way out of being caught between two.

    Produced by ``inference.check_for_grab_opportunities`` when another live
    enemy is inside ``reach.rear_threats``' box behind the actor. Taking the
    front body turns that pincer into a weapon: ``could_hold_actions``
    already answers a rear threat with ``ThrowHeldEnemy`` (B+back), which
    throws the held enemy backwards *into* the one behind, and offers
    ``FlipHold`` as the alternate that ends up facing that way.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class GrabToNeutralizeWhip(GrabOpportunity):
    """``Nora`` fights with a whip, which cannot answer a body against it.

    Produced by ``inference.check_for_grab_opportunities`` for a live
    ``Nora`` (type $26, "Whip attacks" per enemy-ai.md's visual-family
    table). Her reach is the reason to close it: held, she has no move that
    connects, so a grab converts her best range into her worst.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomingMelee(Inferred):
    """An enemy whose committed attack is close enough to land on the actor.

    Produced by ``inference.check_for_incoming_melee`` for an on-screen
    enemy in a dangerous phase (ATTACKING/CHARGE) sitting inside
    ``reach.too_close_to_keep_approaching``'s caution box. The melee-range
    counterpart of ``IncomingProjectile``: a threat judgment, not a copy of
    every dangerous enemy on screen.
    """

    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PunishWindow(Inferred):
    """An enemy that cannot defend itself right now -- free damage.

    Produced by ``inference.check_for_punish_windows`` for every live enemy
    in a punishable phase (``phases.is_punishable``: knockdown, blocked,
    stunned, grabbed, or move recovery). ``frames_left`` carries the ROM's
    own countdown when it is known -- a stunned ``Grunt``'s ``stun_timer``
    (+$50) -- and 0 when the phase has no readable timer.
    """

    target_slot: str
    frames_left: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Surrounded(Inferred):
    """The actor is boxed in by a crowd rather than facing a queue.

    Produced by ``inference.check_for_surrounded`` when at least
    ``inference.SURROUNDED_MIN_ENEMIES`` live enemies are inside the close
    box around the actor, or when it is pincered (at least one enemy on each
    side of it inside that box). ``in_front``/``behind`` are the counts that
    produced the judgment.
    """

    actor_slot: str
    in_front: int
    behind: int
