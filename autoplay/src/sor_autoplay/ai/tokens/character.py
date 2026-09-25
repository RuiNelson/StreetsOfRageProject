"""``Character`` token hierarchy: playable characters and enemies.

Per ``AI.md``: character identity (Axel/Adam/Blaze) is a plain attribute
rather than a subclass, since playable characters do not otherwise differ in
token structure. ``Character`` is the common actor base; ``Enemy`` (in
``enemy.py``) and ``PlayableCharacter`` (``Myself`` / ``Partner``) descend
from it. Action-state conventions live on ``PlayableCharacter``.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from sor_autoplay.hitboxes import Hitbox
from sor_autoplay.memory_map import (
    ACTION_HOLD_BASES,
    ACTION_THROW_AIR_TECHABLE,
    PLAYER_KNEE_CHAIN_BIT,
)
from sor_autoplay.phases import CombatPhase

from .pickup_tokens import is_weapon_type
from .tokens import Observed

# Measured normal-punch attack boxes facing right (controls-and-input.md):
# outer X edge of +$64; inner X is the dead zone (body already past the box).
# Usable centre-to-centre is a few px past the outer edge (victim body ~13 wide).
PUNCH_INNER_X: dict[int, int] = {0: 16, 1: 8, 2: 18}  # Axel, Adam, Blaze
PUNCH_OUTER_X: dict[int, int] = {0: 50, 1: 48, 2: 60}  # slightly inside measured outer
PUNCH_RANGE_Y = 12  # attack box Y is ±8; leave a small lane slack
DEFAULT_PUNCH_INNER_X = 14
DEFAULT_PUNCH_OUTER_X = 48

# Measured bat/pipe swing reach (weapons-range-and-damage.md §5, live Axel):
# max |w_x-p_x| = 36 px, shorter than any character's unarmed outer edge above
# -- a held bat/pipe must use this instead of the per-character punch table.
MELEE_WEAPON_TYPES = frozenset({0x0A, 0x0B})  # baseball bat, steel pipe
MELEE_WEAPON_PUNCH_OUTER_X = 36
# The swing ($48) connects near its peak, not in the hand: the weapon is its
# own object, its origin runs from the hand (w_x-p_x = 6) out to the peak --
# 36 px for Axel (weapons-range-and-damage.md §5), 53 for Blaze (measured on
# round 1's booths with both weapons) -- and its box reaches about 18 px back
# from there (Blaze broke a +-16 booth from 19 px and swung 93 times from 17
# without touching it). Adam is unmeasured; his punch (48) is Axel's (50),
# not Blaze's (60), so he takes Axel's peak -- an estimate, not a reading.
MELEE_WEAPON_SWING_PEAK_X: dict[int, int] = {0: 36, 1: 36, 2: 53}
DEFAULT_MELEE_WEAPON_SWING_PEAK_X = 36
MELEE_WEAPON_SWING_BACK_X = 18
# When the swing's box is live is unmeasured: it commits the actor ~26 frames
# (13 player updates) and is live only near its peak. The updates, counted
# from the B edge, the box may be out on -- the plans play every window
# inside this span (``jack.SWING_LIVE_WINDOWS``), and the no-whiff test arms
# the swing at its end (``kinematics.melee_strike_connect_frames``).
MELEE_WEAPON_SWING_LIVE_UPDATES = (3, 9)
MELEE_WEAPON_SWING_LOCK_UPDATES = 13
# Half an ordinary enemy's body on X (the idle bodies run about +-6): how far
# a body reaches back toward the actor from its own origin, when its own box
# is not at hand.
ENEMY_BODY_HALF_X = 6
KNIFE_TYPE = 0x08
BOTTLE_TYPE = 0x09
PEPPER_SPRAY_TYPE = 0x0C
# The knife's B is two moves (``$3084 (player_held_object_attack_input)``,
# reimplemented in ``SoRInteractions.cpp``'s ``hasNearbyObjectInFront``): a
# stab (``$46``, the knife kept) when *any* object of the first 32 slots --
# any type but ``$00``/``$16``: an enemy, an item, a prop, a projectile --
# stands in front of the player less than ``$90`` (144) px away on X, on a
# lane in ``[y - 12, y + 12)``; otherwise the throw (``$44``, released on
# frame 1). So a knife "thrown" at an enemy 40-90 px away is a stab into the
# air, and a stab needs its target inside the stab's own reach.
KNIFE_CONE_X = 0x90
KNIFE_CONE_LANE_BELOW = 12  # lane >= y - 12
KNIFE_CONE_LANE_ABOVE = 12  # lane < y + 12


# A hit is box-against-*body*, not box-against-point: `$450C` tests the
# attacker's attack box (+$64) against the victim's body box (+$70), which is
# about 13px wide. controls-and-input.md draws the conclusion for the outer
# edge itself -- "the usable centre-to-centre distance runs a few pixels past
# the numbers above" -- and the same is true at the *inner* edge, where it
# matters far more: a body centred just inside the box still overlaps it.
#
# Half a body, rounded down, deliberately conservative. Without it the AI
# believed a foe standing 10px in front of Axel was unhittable, and the
# consequences were not subtle (measured on the whiff harness): it refused to
# punch, `could_walk_to_near_enemy` took the tick and aimed 46px away to
# re-establish "proper" range, walking away turned the actor around, the
# enemy then read as *behind* it, the turn-around branch aimed back at it --
# and the actor shuffled between two points forever, in punching range of an
# enemy it never once hit. The same false dead zone is also the first clause
# of `rear_attack_is_warranted`, so it promoted the slow B+C chord at
# point-blank range as the "escape" from a situation a plain punch answers.
BODY_OVERLAP_X = 6


def punch_inner_x(character_id: int | None) -> int:
    """The measured inner edge of the punch box itself."""

    if character_id is None:
        return DEFAULT_PUNCH_INNER_X
    return PUNCH_INNER_X.get(character_id, DEFAULT_PUNCH_INNER_X)


def swing_peak_x(character_id: int | None) -> int:
    """Where a bat or pipe swing's own origin peaks, px in front of the actor."""

    if character_id is None:
        return DEFAULT_MELEE_WEAPON_SWING_PEAK_X
    return MELEE_WEAPON_SWING_PEAK_X.get(character_id, DEFAULT_MELEE_WEAPON_SWING_PEAK_X)


def swing_inner_x(character_id: int | None, body_half_x: int = ENEMY_BODY_HALF_X) -> int:
    """The nearest a body reaching ``body_half_x`` back toward the actor can
    stand and still meet a bat/pipe swing: nearer, it is under the swing."""

    return max(0, swing_peak_x(character_id) - MELEE_WEAPON_SWING_BACK_X - body_half_x)


def punch_usable_inner_x(character_id: int | None, held_weapon_type: int = 0) -> int:
    """The nearest a *body* can be and still be hit -- see BODY_OVERLAP_X.

    This, not ``punch_inner_x``, is what "too close to punch" means. The raw
    edge stays available for anything that really is about the box (the walk
    verb's stop distance, which wants the box comfortably clear).

    The same with a bat or pipe. A band from the swing's peak (Blaze 29..53,
    ``swing_inner_x``) was tried and measured worse live (user: "Muito mau,
    vejo a IA a perder muito mais vida que antes, por exemplo, espera muito
    depois de dar um ataque com pipe ou bat"): it rested on a booth's wall,
    not a body, and it left the actor walking while enemies came in under it.
    ``held_weapon_type`` is kept so the question stays asked in one place.
    """

    return max(0, punch_inner_x(character_id) - BODY_OVERLAP_X)


def punch_outer_x(character_id: int | None, held_weapon_type: int = 0) -> int:
    """The farthest B lands from, for the weapon in hand.

    Bat/pipe: Axel's measured 36 for everyone (weapons-range-and-damage.md
    §5) -- Blaze's 53 went with the swing-peak band, reverted (see
    ``punch_usable_inner_x``). Knife and bottle: the punch's own box -- their stab (``$46``) and swing
    (``$44`` without a release) are unmeasured, and the hand that carries them
    is the punch's. Pepper's B is a throw, never a strike; its number is the
    punch's only so the geometry that asks "how far does this actor reach"
    has one."""

    if held_weapon_type in MELEE_WEAPON_TYPES:
        return MELEE_WEAPON_PUNCH_OUTER_X
    if character_id is None:
        return DEFAULT_PUNCH_OUTER_X
    return PUNCH_OUTER_X.get(character_id, DEFAULT_PUNCH_OUTER_X)


def knife_cone_contains(
    actor_x: int, actor_y: int, facing_left: bool, object_x: int, object_y: int
) -> bool:
    """``hasNearbyObjectInFront``'s test for one object: in front on the
    facing, under 144 px on X (unsigned, so 0 counts as in front facing
    right), on a lane in ``[y - 12, y + 12)``."""

    if object_x >= actor_x:
        if facing_left:
            return False
        distance = object_x - actor_x
    else:
        if not facing_left:
            return False
        distance = actor_x - object_x
    if distance >= KNIFE_CONE_X:
        return False
    return actor_y - KNIFE_CONE_LANE_BELOW <= object_y < actor_y + KNIFE_CONE_LANE_ABOVE


# Rear-attack ($322A player_attack_jump_chord) own attack box +$64, measured
# live facing right (controls-and-input.md "Measured chord timing"): Y is
# always +-8 for all three characters. Adam's chord is a hop ($22 -> $24)
# whose box reaches forward as well as behind; Axel/Blaze only reach behind.
REAR_ATTACK_Y = 8
REAR_ATTACK_BEHIND_MAX_X: dict[int, int] = {0: 40, 1: 42, 2: 53}  # Axel, Adam, Blaze
REAR_ATTACK_FRONT_MAX_X: dict[int, int] = {0: 0, 1: 14, 2: 0}
DEFAULT_REAR_ATTACK_BEHIND_MAX_X = 48
DEFAULT_REAR_ATTACK_FRONT_MAX_X = 0

# The chord has an inner edge behind the actor as well as an outer one, and
# the measured boxes give it: Axel's is X -40..**-8**, Blaze's -53..**-5**.
# Adam's -42..+14 runs continuously through his own origin, so his is 0. A
# body closer than this is *under* the box and cannot be hit by the chord at
# all -- the same dead zone the punch has at its inner edge.
#
# Live symptom of leaving it out, reproduced on the tick harness: the actor
# lands a jump kick slightly past an enemy, ends up 5px from it, and every
# tick from then on `in_rear_band` says the chord reaches, `rear_attack_is_
# warranted` agrees (a target inside the punch dead zone is precisely its
# first clause), and the AI fires B+C into nothing -- forever, because the
# whiff never changes the geometry that produced it.
REAR_ATTACK_BEHIND_MIN_X: dict[int, int] = {0: 8, 1: 0, 2: 5}
DEFAULT_REAR_ATTACK_BEHIND_MIN_X = 8


def rear_attack_behind_max_x(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_REAR_ATTACK_BEHIND_MAX_X
    return REAR_ATTACK_BEHIND_MAX_X.get(character_id, DEFAULT_REAR_ATTACK_BEHIND_MAX_X)


def rear_attack_behind_min_x(character_id: int | None) -> int:
    """The chord's inner edge behind the actor, body width allowed for.

    Same correction as ``punch_usable_inner_x``: the box starts 8px behind
    Axel, but a body centred nearer than that still reaches into it.
    """

    if character_id is None:
        edge = DEFAULT_REAR_ATTACK_BEHIND_MIN_X
    else:
        edge = REAR_ATTACK_BEHIND_MIN_X.get(
            character_id, DEFAULT_REAR_ATTACK_BEHIND_MIN_X
        )
    return max(0, edge - BODY_OVERLAP_X)


def rear_attack_front_max_x(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_REAR_ATTACK_FRONT_MAX_X
    return REAR_ATTACK_FRONT_MAX_X.get(character_id, DEFAULT_REAR_ATTACK_FRONT_MAX_X)


@dataclass(frozen=True, slots=True, kw_only=True)
class Character(Observed, ABC):
    """A living on-screen actor: a playable character or an enemy.

    Carries only what every actor shares (identity ``slot``, position,
    health, facing, combat phase). Player-only state lives on
    ``PlayableCharacter``; hostile-only state lives on ``Enemy``.
    """

    slot: str  # "P1"/"P2" for playable; MapEntity slot like "obj07" otherwise
    world_x: int
    world_y: int
    health: int | None
    facing_left: bool
    combat_phase: CombatPhase
    # The object's 128 bytes, for a plan that replays its update from the ROM
    # model (world_map.MapEntity.raw): the players and Mr. X. Empty otherwise.
    raw: bytes = b""


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayableCharacter(Character, ABC):
    """A player-controlled character (``Myself`` / ``Partner``).

    Action-state conventions (``controls-and-input.md``,
    ``player-health-lives-and-combat.md``):

    - ``+$30`` bit 0 = facing left; even base is the action family.
    - Front hold ``$60`` / back hold ``$66`` accept B/C edges for knee/throw/suplex.
    - Enemy-held sequence ``$78`` → ``$7A`` → optional crossover ``$7C`` → counter
      ``$7E``; ``action_flags`` bit 7 is the post-crossover B window (``+$58``).
    - ``tech_armed`` (``+$45``) is set only by specific special/boss hold-throw
      choreography launching into ``$5C``/``$88`` — an ordinary street-enemy
      throw (``$72`` via ``$29D0``) never arms it, so C+Up is inert there
      (controls-and-input.md "C+Up landing tech").

    ``hitbox`` is this character's real body AABB, read straight out of the
    object rather than reconstructed: unlike an enemy, a player caches it at
    ``+$70`` every frame (``$4140``), so ``world_map`` only has to read it
    (``hitboxes.cached_box``). ``None`` on a no-attack frame with a
    degenerate cached box, or without a link -- never a guessed rectangle.
    There is no matching ``attack_ranges`` here: a player's reach is the
    punch/rear/jump-kick geometry already in this module
    (``punch_outer_x`` and friends), which is per-character and per-weapon,
    not per-animation-frame the way an enemy's is.
    """

    player_index: int  # 1 or 2
    character_id: int | None
    character_name: str
    health_percent: float
    lives: int
    specials: int
    held_weapon_type: int  # 0 = none; else the weapon type id (0x08-0x0C)
    action_state: int  # raw byte at +$30; front-hold $60 vs back-hold $66
    is_airborne: bool  # from MapEntity.is_airborne; JumpAttack C-then-B
    # player +$58: bit 7 = grab-counter B window after C crossover ($7C).
    action_flags: int = 0
    tech_armed: int = 0  # player +$45; bounce-cancel tech may still be latched
    hitbox: Hitbox | None = None
    # Player X velocity at +$1C (signed 16.16, px per object update -- two
    # 60 Hz frames, see ai/jump_kick.py). Antonio's kick gate at $16EAE reads
    # this exact word: a value of 0 is the standing-still path that fires the
    # power kick during a ground combo.
    vel_x: float = 0.0
    # Height at +$18 (down is positive) and its velocity at +$24, per update:
    # what ai/jump_kick.py needs to carry a flight already in the air on.
    world_z: int = 0
    vel_z: float = 0.0
    # Lane velocity at +$20, per update: ai/antonio.py puts the boxes of a
    # walk held into the lane clamp a step past it, where $4140 cached them.
    vel_lane: float = 0.0
    # The floor under this player: its own height the last tick it stood on
    # the ground (observe.GroundTracker). A flight lands back on it, and a
    # jump gives no other way to know where that is. None until observed.
    ground_z: int | None = None
    # Ticks since this actor took its current hold (front $60 or back $66),
    # cross-tick memory from observe.HoldTracker -- there is no ROM-decoded
    # escape/struggle timer on the held enemy to read instead. 0 while not
    # holding. priority.py's held-move scoring reads this to knee a few times
    # before the flip->suplex finish takes over, rather than finishing the
    # instant a hold is taken (measured live against Souther: the AI grabbed
    # and immediately flipped, milking zero knees).
    hold_ticks: int = 0
    # Slot of the body this actor currently has in its hands, from the ROM's
    # own hold link (+$4C, world_map.MapEntity.contact_slot) -- None when not
    # holding, or when the pointer does not resolve to a live object; P1/P2
    # when the body is the other player (is_holding_player). This is the
    # *identity* half of is_holding_enemy below, which only answers whether a
    # hold exists at all.
    held_enemy_slot: str | None = None
    # player +$61: the last knee of the current front-hold chain ($6A, then
    # $6C) -- see knees_in_chain.
    knee_chain_last: int = 0
    # player +$63: loc_235A's front-hold release countdown (memory_map.
    # OBJ_HOLD_RELEASE_COUNTDOWN). Seeded with 3 by the grab; each frame held
    # back decrements it, and the hold drops on the frame it goes negative.
    hold_release_countdown: int = 0
    # player +$4B bit 7 (memory_map.PLAYER_CROSSOVER_SPENT_BIT): this hold's
    # one C crossover has been used. A second one takes $26E2's failure path
    # and lands the actor out of the hold beside a free body.
    crossover_spent: bool = False
    # player +$31: Antonio's standing-still kick window ($16EAE) reads bit 1
    # of it on his target. Nothing in the player code sets that bit, so it
    # reads 0 -- carried anyway so ai/antonio.py applies the ROM's own test.
    flags_31: int = 0
    # player +$59, +$4B and +$7C, raw. A later boss's $179F8 marks its target
    # unavailable (+$77) while +$59 bit 1 (a hit reaction, until the floor
    # landing) or +$4B bit 1 is set, or the action is $5A-$5F; $AA34 tests no
    # contact on a player with +$59 bit 1 or +$7C bit 0 (a contact code not
    # yet consumed). ai/antonio.py applies both.
    flags_59: int = 0
    flags_4b: int = 0
    contact_code: int = 0
    # The animation (+$08), its frame (+$0A) and that frame's countdown
    # (+$0D) -- the rear attack's timeline (ai/twins.py) -- and the position
    # as 16.16 ($43AA clamps only the integer word, so the fraction matters).
    anim: int = 0
    anim_frame: int = 0
    anim_countdown: int = 0
    fine_x: float = 0.0
    fine_y: float = 0.0
    # ``$3084``'s knife test, read off the object table this snapshot: some
    # object (any type but $00/$16) stands in front under 144 px, on a lane in
    # [y - 12, y + 12). With a knife in hand, B is then the stab, else the
    # throw (``knife_cone_contains``).
    knife_cone_occupied: bool = False

    @property
    def knees_in_chain(self) -> int:
        """Knees already landed in this front hold's chain: 0, 1 or 2.

        ``$2BA8`` keeps the count in the player's own object. The first B of a
        chain sets ``+$58`` bit 6 and writes ``$6A`` to ``+$61``; each later B
        steps ``+$61`` by 2 while it is still inside ``[$6A, $6E)``. So the
        next knee after two is ``$6E`` -- 3 damage and the heavy flag, which
        knocks the held body away and ends the hold. Bit 6 survives only
        ``$60``/``$6A``/``$6C`` (``$394E``'s mask table), which is why the
        walk before a grab, a crossover and any other action all restart the
        chain at one.
        """

        if not self.action_flags & PLAYER_KNEE_CHAIN_BIT:
            return 0
        if self.knee_chain_last == 0x6A:
            return 1
        if self.knee_chain_last == 0x6C:
            return 2
        return 0

    @property
    def action_base(self) -> int:
        """Action family with facing bit cleared."""

        return self.action_state & 0xFE

    @property
    def is_holding_player(self) -> bool:
        """True while the body in this actor's hands is the *other player*.

        Walking into the partner takes a hold on them exactly as walking into
        an enemy does. ``$4478 (resolve_player_vs_player_collision)`` turns a
        walking box on the other player's body, with no damage out, into grab
        contact (``+$7C`` = 3) and a reciprocal ``+$7E`` link; ``$3266`` then
        takes the same front ``$60`` / back ``$66`` hold it takes on an enemy
        and writes the partner's object into ``+$4C``, which ``world_map``
        decodes as ``P1``/``P2``. Every hold move from there -- the knee, the
        throw, the C crossover and the suplex after it -- lands on the
        partner.
        """

        return self.held_enemy_slot in ("P1", "P2")

    @property
    def is_holding_enemy(self) -> bool:
        """True while this actor has an enemy body in its hands.

        Read from the **action byte**, not from ``held_weapon_type``
        (``+$60``). ``+$60`` is the weapon/pickup link written by ``$3136
        (find_close_interaction_target)``; the grab path only exchanges it
        for *ordinary* enemies. Holding a later boss leaves it reading 0 --
        or the weapon the actor is still carrying, since a hold and a
        carried weapon coexist. Both were measured live on Antonio: the
        actor sat in front hold ``$60``/``$61`` for an entire round-1 fight
        with ``+$60`` reading ``$00`` in one run and ``$0B`` in another,
        while B kneed him for 2 and C→B suplexed him for 5.

        The action family is what ``controls-and-input.md`` documents as
        authoritative and is character-independent: ``$60``/``$66`` are the
        stable front/back holds and the rest of ``$60-$6F`` are their
        animation locks (``ACTION_HOLD_BASES``).

        ``held_weapon_type`` is still honoured as a second, independent
        witness so an ordinary-enemy hold observed on a frame whose action
        byte has already left the family is not lost.
        """

        if self.held_enemy_slot is not None:
            # Includes the C crossover ($76/$80), which observe.py only fills
            # in when +$4C actually points at a body -- that family is also
            # the co-op partner vault, which holds nothing.
            return True
        if self.action_base in ACTION_HOLD_BASES:
            return True
        held = self.held_weapon_type
        return held != 0 and not is_weapon_type(held)

    @property
    def counter_window_open(self) -> bool:
        """True when the held-by-enemy counter accepts a B edge (``+$58`` bit 7)."""

        return bool(self.action_flags & 0x80)

    @property
    def throw_tech_ready(self) -> bool:
        """True when a fresh C-edge + Up can still latch the bounce-cancel
        landing tech (``+$45`` set on a techable free-flight action).

        Mirrors ``world_map.MapEntity.throw_tech_ready`` exactly — that
        property already carries the "only certain throws arm this" nuance,
        this is just the same fact surfaced on the AI's own token.
        """

        return self.tech_armed != 0 and self.action_base in ACTION_THROW_AIR_TECHABLE


@dataclass(frozen=True, slots=True, kw_only=True)
class Myself(PlayableCharacter):
    """The playable character this agent controls (player_index 1 or 2)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Partner(PlayableCharacter):
    """The other playable character in the game, when present."""
