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
from sor_autoplay.memory_map import ACTION_THROW_AIR_TECHABLE
from sor_autoplay.phases import CombatPhase

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


def punch_usable_inner_x(character_id: int | None) -> int:
    """The nearest a *body* can be and still be hit -- see BODY_OVERLAP_X.

    This, not ``punch_inner_x``, is what "too close to punch" means. The raw
    edge stays available for anything that really is about the box (the walk
    verb's stop distance, which wants the box comfortably clear).
    """

    return max(0, punch_inner_x(character_id) - BODY_OVERLAP_X)


def punch_outer_x(character_id: int | None, held_weapon_type: int = 0) -> int:
    if held_weapon_type in MELEE_WEAPON_TYPES:
        return MELEE_WEAPON_PUNCH_OUTER_X
    if character_id is None:
        return DEFAULT_PUNCH_OUTER_X
    return PUNCH_OUTER_X.get(character_id, DEFAULT_PUNCH_OUTER_X)


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

    @property
    def action_base(self) -> int:
        """Action family with facing bit cleared."""

        return self.action_state & 0xFE

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
