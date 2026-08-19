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
from enum import Enum, auto

from ...attack_ranges import AttackRange
from ...hitboxes import Hitbox
from ...phases import CombatPhase
from .character import Character
from .tokens import Inferred


@dataclass(frozen=True, slots=True, kw_only=True)
class Enemy(Character):
    """A hostile on-screen actor that can be hit and defeated.

    ``hitbox`` is this enemy's real body AABB, rebuilt per tick from the ROM
    shape tables the way ``$AB24`` does -- enemies cache nothing, so it has
    to be reconstructed (``hitboxes.py``). ``attack_ranges`` is every reach
    the enemy has, extracted from its type's own animation set plus whatever
    it is carrying (``attack_ranges.py``). Both are value objects, not
    tokens: a token may not embed a token by value, and these are properties
    *of* this enemy rather than independent observations.

    Both default to empty, which is what a session without ROM table access
    looks like -- consumers must treat "no hitbox" as "unknown", never as
    "no body".
    """

    type_id: int
    targets_player: int | None  # 1 or 2, or None — from MapEntity.targets_player
    # Ordinary-enemy velocity only (Grunt family); Boss populates its own
    # vel_x/vel_z below from different offsets -- see memory_map.py's
    # OBJ_VEL_X_ORDINARY/OBJ_VEL_LANE_ORDINARY.
    grunt_vel_x: float = 0.0  # +$1C signed 16.16, ordinary enemies only
    grunt_vel_y: float = 0.0  # +$20 signed 16.16 (lane), ordinary enemies only
    hitbox: Hitbox | None = None
    attack_ranges: tuple[AttackRange, ...] = ()
    # Pickup weapon type $08-$0C while this enemy is holding one, else 0.
    # Ordinary enemies do not store this at +$60 (that word is their
    # scripted approach X); observe copies it from MapEntity.held_type,
    # which world_map resolves from the held weapon's +$52 holder pointer.
    held_weapon_type: int = 0

    def predict_position_after_n_frames(self, n_frames: int) -> tuple[int, int]:
        """Where this enemy stands ``n_frames`` from now, on its own velocity.

        The unit is a **60 Hz game frame**, not an AI poll tick, because that
        is the unit the ROM itself moves in: ``grunt_vel_x``/``grunt_vel_y``
        are the raw 16.16 fields at ``+$1C``/``+$20``, and ``$17AB8``
        integrates them into the position exactly once per frame. A poll tick
        is ~2 of those at the 33ms default (``app.DEFAULT_POLL_MS``), so
        anything that multiplies these velocities by a *tick* count under-
        projects by that factor -- see ``ai/kinematics.py``, which owns the
        conversion and every lead time built on top of this.

        Constant velocity only: this is where the enemy *would* be if it
        kept doing what it is doing, which is exactly right over the handful
        of frames a move's startup lasts and increasingly optimistic beyond
        that (``kinematics.MAX_LEAD_FRAMES`` is the trust horizon callers
        clamp to).

        A ``Boss`` always reports 0 velocity here and therefore predicts to
        its current position: its own ``vel_x``/``vel_z`` live at different
        offsets, are not confirmed to be the X/lane pair, and boss tactics
        are out of scope (see ``Boss``). That is "no better guess than
        standing still", not an assertion that it is stationary.
        """

        return (
            round(self.world_x + self.grunt_vel_x * n_frames),
            round(self.world_y + self.grunt_vel_y * n_frames),
        )

    @property
    def is_defeated(self) -> bool:
        """This enemy is already dead -- a body, not a target.

        The same hard lifecycle rule ``world_map.MapEntity.is_defeated``
        uses, and for the same reason: the ROM's ordinary-enemy lethal checks
        are **signed**, so a health word of ``$8000``-``$FFFF`` has crossed
        the lethal boundary while the object still sits in its slot with an
        action family that has not caught up yet. Zero health has *not* --
        that enemy is still alive and owed a finishing hit.

        Judging "still a target" from ``combat_phase`` alone therefore keeps
        a corpse in the target set for as long as its stale action family
        lasts: the AI walks to it, ranks it against real enemies, and punches
        it. That is exactly the "attacking enemies that are not there" a
        player sees.
        """

        return self.health is not None and self.health >= 0x8000

    @property
    def max_reach(self) -> int:
        """How far ahead this enemy can hit from where it stands, in px.

        Zero when nothing was extracted (a boss, or no ROM tables), which
        callers must read as "unknown" and fall back on their own margins
        for -- not as "harmless".
        """

        return max((r.forward_max for r in self.attack_ranges), default=0)

    @property
    def min_reach(self) -> int:
        """The nearest an enemy's *shortest* attack still reaches.

        Positive means a dead zone: every attack it has starts further out
        than this, so standing closer is safe from all of them. Nora is the
        clear case (whip shape $22 starts 32px out); most enemies have a box
        that reaches their own feet and return 0.
        """

        return min((r.forward_min for r in self.attack_ranges), default=0)


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


# Default for a Nora the tracker has no history for yet (no NoraAttackTracker
# supplied to generate_direct_observation_tokens, or a slot observed for the
# first time this tick): large enough that nothing downstream mistakes an
# unobserved Nora for one that has recently attacked. Not a frame count --
# ticks_since_last_attack counts AI poll ticks (observe.NoraAttackTracker),
# unlike everything in kinematics.py and reach.CLOSING_ENEMY_THREAT_FRAMES,
# which are 60 Hz game frames.
NORA_TICKS_SINCE_ATTACK_UNKNOWN = 1_000


@dataclass(frozen=True, slots=True, kw_only=True)
class Nora(Grunt):
    """Nora ordinary enemy (type $26).

    ``ticks_since_last_attack`` is cross-tick memory, not a RAM field: it
    counts AI poll ticks since this exact enemy slot was last observed in a
    dangerous phase (``phases.is_dangerous`` -- her whip engage-and-swing at
    state ``$08``/``$0A`` or the scripted lunge at ``$15``, per ``phases.py``'s
    ``0x26`` table), reset to 0 while she is dangerous and counting up once
    she stops. Maintained by ``observe.NoraAttackTracker`` and defaulted here
    to :data:`NORA_TICKS_SINCE_ATTACK_UNKNOWN` for any caller that builds a
    ``Nora`` without going through it (tests, or a tick with no tracker
    supplied) -- see that class for why this is the one deliberate exception
    to this pipeline's usual per-tick statelessness. Small values are the
    signal ``priority._emergency_jump_attack`` uses to prefer a jump kick in
    the brief window before she can attack again -- see
    ``ai-analysis/enemy-ai.md``'s Nora state-8 swing loop, which can repeat
    up to three times before she gives up and returns to normal chase.
    """

    ticks_since_last_attack: int = NORA_TICKS_SINCE_ATTACK_UNKNOWN


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
    # Boss primary byte at +$30 (MapEntity.action_state). Antonio's kick is
    # primary $02; the 1→2 transition is what reach.antonio_will_kick predicts.
    primary_state: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Abadede(Boss):
    """Abadede boss (type $30)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MrX(Boss):
    """Mr. X boss (type $35)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Souther(Boss):
    """Souther boss (type $55).

    Primary state 1 (``$15EDA (souther_state1_active_combat)``) is active
    combat: the standoff bands, the lane closing, and the proximity/velocity
    gate that advances him to state 2. Primary state 2
    (``$16118 (souther_state2_claw_commit)``) is the committed claw --
    wind-up, launch, then an 8px/frame dash that only ever steers on X.
    """

    def strike_is_committed(self) -> bool:
        """True when the claw is already locked in.

        Primary ``$02`` is the whole committed sequence; unlike Antonio there
        is no separate tactical commit value, because
        ``$16118 (souther_state2_claw_commit)`` is entered *by* clearing
        ``+$67`` and every one of its tactical handlers is already part of the
        claw. The uncommitted state-1 gate is
        ``reach.souther_will_slash``'s business, not this.
        """

        return self.primary_state == 0x02


@dataclass(frozen=True, slots=True, kw_only=True)
class Antonio(Boss):
    """Antonio boss (type $56).

    Primary state 1 (``$16DA0``) is active combat: facing, boomerang
    maintain/throw (tactical ``$08``), and the proximity/velocity/facing
    gate that advances him to state 2. Primary state 2 (``$171CC``) is the
    committed close-range power kick. ``reach.antonio_will_kick`` names that
    transition before -- and while -- it lands.
    """

    def strike_is_committed(self) -> bool:
        """True when the kick or the dash/throw is already locked in.

        Primary ``$02`` is the close-range kick (``$171CC``). Tactical
        ``$08`` is the boomerang dash/throw commit (``$16E88``). Turning
        (tactical ``$09``) and merely standing inside the ``$16EAE``
        prediction window are not commits -- those are when a punch can
        still land and open the grab.
        """

        return self.primary_state == 0x02 or self.tactical == 0x08


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


class GrabReason(Enum):
    """Why a grab is judged worth more than a strike right now.

    Each member is one situation ``reach.grab_reasons`` recognises, kept as
    an enum rather than a discriminator on a dedicated token since it is a
    pure function's return value now, not a stored judgment: every situation
    is scored by the identical ``priority._emergency_grab_enemy`` -- "best
    tier among reasons present for this pair" -- with only the tier constant
    differing per reason. Most reasons are ``Grunt``-only; ``ANTONIO_ON_
    PUNISH`` is the exception, because Antonio's punish window is the
    opening of the punch-grab-suplex that beats standing still to combo him
    (the combo is his own kick trigger).
    """

    CLEAR_REAR = auto()
    """A hold on this enemy is the way out of being caught between two.

    Produced when another live enemy is inside ``reach.rear_threats``' box
    behind the actor. Taking the front body turns that pincer into a
    weapon: ``could_hold_actions`` already answers a rear threat with
    ``ThrowHeldEnemy`` (B+back), which throws the held enemy backwards
    *into* the one behind, and offers ``FlipHold`` as the alternate that
    ends up facing that way.
    """

    DEAD_ZONE = auto()
    """Every attack this enemy has starts further out than the actor can be.

    Produced when the enemy's extracted ``attack_ranges`` all have a
    positive ``forward_min`` (``Enemy.min_reach``), so closing to contact
    leaves it with no move that connects at all.

    Today the ROM picks out exactly one enemy this way: ``Nora``, whose only
    attacking animation selects shape ``$22``, reaching 32 to 80 pixels
    ahead. Every other ordinary type has at least one box that covers its own
    feet. That is deliberately *not* hardcoded here -- an enemy earns this
    because of its extracted geometry, so a corrected extraction or a
    newly-covered type changes the AI's behaviour without changing anything
    here.
    """

    JACK_FROM_BEHIND = auto()
    """The actor is already on Jack's back -- take the hold before he turns.

    Produced when the actor stands behind a live ``Jack``
    (``reach.enemy_forward_dx`` negative: Jack is facing away). His axe
    juggle and lunge punish a front exchange; a back grab skips both. The
    walk-in still has to face him (``reach.grab_would_connect``), so this
    is "caught him from behind", not "he is behind us" -- that side is
    ``RearAttack``.
    """

    DODGE_CHARGE = auto()
    """A committed enemy is charging in from *behind* this grabbable one.

    Produced when ``reach.is_incoming_melee`` already holds for another live
    enemy against this actor, that enemy sits on the **same side** as the
    grab candidate, and is **further away** than it -- the user's own
    description: "an enemy in front, and behind it, a Signal".

    Signal is the case this exists for, and the ROM is why it is nasty:
    his slide (state ``$0A``) is *velocity, not a hitbox* -- enemy-ai.md's
    own phrase -- so it carries no attack shape for any reach check to find
    and it closes about 2.5 px per frame. There is nothing to sidestep and
    little time to sidestep it in, and what it costs is a knockdown, which
    is the most expensive thing that can happen in a crowd.

    Taking the hold is the answer: the actor stops being a free-standing
    target for the slide's whole approach, the held body is between it and
    the charge, and ``could_hold_actions`` converts the hold into damage
    (``FlipHold`` -> ``Supplex`` with nothing behind to throw into) rather
    than into a wasted defensive action.

    Deliberately *not* "any committed enemy anywhere". The same-side and
    further-away tests are what make it the described geometry rather than a
    blanket "grab whenever anyone swings", which would turn every ordinary
    exchange into a grab.
    """

    WHILE_SURROUNDED = auto()
    """The actor is boxed in -- a body in its hands is the way out.

    Produced for any grabbable ``Grunt`` while this actor carries a
    ``Surrounded`` token. It is the crowd counterpart of ``CLEAR_REAR``,
    which only fires on a *confirmed rear* enemy (``reach.rear_threats``):
    a crowd standing in front of and beside the actor -- three bodies
    inside the close box with none strictly behind -- produced no grab
    opportunity at all, so the AI answered being surrounded with a plain
    ``Punch`` at one of them.

    A hold is worth more than a strike here for reasons that do not apply
    one-on-one. It takes one of the bodies out of the fight for its whole
    duration, and it ends in damage the crowd cannot interrupt: the front
    hold's own follow-ups are already ``FlipHold`` -> ``Supplex``, or
    ``ThrowHeldEnemy`` when ``could_hold_actions`` sees a rear threat to
    throw the body *into*. ``Surrounded``'s own docstring says no amount of
    facing answers being hit from both sides at once; a hold is the answer
    that does not require choosing a side.

    Whether the hold is *reachable* is still ``reach.grab_would_connect``'s
    question -- ``decide.could_grab_enemy`` needs both -- so this never
    proposes walking across a crowd to reach someone.
    """

    ANTONIO_ON_PUNISH = auto()
    """Antonio is in hitstun -- walk in and hold him, then suplex.

    Produced when a live ``Antonio`` is in a punishable phase (``RECOVERY``
    after ``$17C36 boss_apply_pending_damage`` writes shared later-boss
    states ``$03``/``$04``). A second punch here is standing still in front
    of him, which is the ``$16EAE`` zero-velocity kick path; the hold is
    how a human actually beats him.

    Not produced while he can still act: walking into a ready Antonio
    is how the kick lands first.
    """

    SOUTHER_ON_PUNISH = auto()
    """Souther is in hitstun -- walk in and hold him, then suplex.

    Produced when a live ``Souther`` is in a punishable phase, the same
    shared later-boss ``RECOVERY`` states ``$03``/``$04`` that ``$17C36
    boss_apply_pending_damage`` writes for Antonio. His base health is
    ``$20`` against ``$18`` for Antonio (``$17EDC boss_init_combat_stats``),
    so the suplex chain matters more here, not less.

    Deliberately its own reason rather than sharing Antonio's: the *reason*
    the hold pays off differs. Antonio's is that a second punch is his own
    kick trigger; Souther's is simply that ``$15EDA
    (souther_state1_active_combat)`` cannot re-arm the slash while he is in
    recovery, so the walk-in is free.
    """


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


