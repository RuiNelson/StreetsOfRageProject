"""Extract each enemy type's real attack reach from the ROM's own tables.

An enemy's reach is not a tunable: it is whichever collision shapes its
animations select. ``ai-analysis/graphics-engine.md`` §8.3 documents the
three levels this module walks, transcribed from ``$AF46
(emit_object_sprite_mapping)`` and ``$B1A2 (init_object_animation_frame)``::

    animation set    word[i]        -> animation record, relative to the set
    animation record byte  frames   -> frame count
                     byte  duration -> per-frame delay
                     word[f]        -> frame record, relative to the animation
                                       bit 15 = record carries 2 extra bytes
    frame record     byte  pieces   -> sprite pieces; negative ends decoding
                     [2 bytes when the frame offset had bit 15 set]
                     byte  attack box id  -> object +$02
                     byte  body box id    -> object +$03

Neither table stores a length. The animation count comes from the first
offset (animation 0 starts immediately after the set's own table); the frame
count is the animation record's first byte, which ``$B0C8`` compares ``+$0A``
against before wrapping the animation.

Animations come in adjacent mirrored pairs, the **even** member facing right.
Only the even members are read here, so every extracted box is already
oriented forward and needs no mirroring -- the same reason
``hitboxes.build_box`` does not mirror either.

Two things this module deliberately does not claim:

* **A box is not damage.** Outgoing damage lives in ``+$34``, written by the
  enemy's state code, so a frame can carry a contact box purely to make
  ``$AA22`` report interaction -- the grab/push path. Garcia's and Signal's
  *idle* animations both select a body-sized box for exactly that reason. See
  ``MIN_REACH_GAIN`` for how those are told apart from a strike.
* **Held weapons are not extracted.** A weapon stays its own object with its
  own shape and attach table (``$60A0`` for an enemy holder), so its reach is
  not in the enemy's animation set at all. ``held_weapon_range`` supplies the
  one measured value available instead, and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .hitboxes import Hitbox, ShapeTables, build_box

# Animation-set bases per enemy family (labels.csv / enemy-ai.md's
# visual-family table). Bosses are deliberately absent: their sets are not
# labelled and bespoke boss tactics are out of scope.
ANIMATION_SET_FOR_TYPE: Mapping[int, int] = {
    0x20: 0x1FC70,  # garcia_animation_set
    0x21: 0x1FC70,
    0x22: 0x1FC70,
    0x23: 0x1FC70,
    0x24: 0x22948,  # signal_animation_set
    0x25: 0x2402C,  # haku_ro_animation_set
    0x2A: 0x2402C,
    0x26: 0x242F8,  # nora_animation_set
    0x27: 0x2556C,  # jack_animation_set
    0x28: 0x2556C,  # Jack's thrown axe/torch helper shares the set
}

# Every distinct set, read once each even though several types share one.
ANIMATION_SET_BASES = tuple(sorted(set(ANIMATION_SET_FOR_TYPE.values())))

# How much of a set to read. Sets are a few KB at most; over-reading is
# harmless because every offset walked comes from the data itself.
ANIMATION_SET_BYTES = 0x1000

# A frame's attack box only counts as *reach* when it extends meaningfully
# past that same frame's own body box. Without this, Signal's idle animation
# would register as an attack: it selects box $3D, whose forward edge sits 11
# px out against a body box's 9 -- a contact box for his grab, not a strike.
# Half a tile is the smallest gain that cannot be that kind of rounding.
MIN_REACH_GAIN = 8

# Bat/pipe melee reach measured live (weapons-range-and-damage.md §5, "Live
# Axel": max |w_x - p_x| = 36). The weapon is a separate object whose reach is
# attach offset + shape extent rather than anything in the holder's animation
# set, so this is the measured value, not an extracted one -- and it is the
# only weapon whose reach has been measured at all.
MELEE_WEAPON_REACH_X = 36
MELEE_WEAPON_LANE = 8
MELEE_WEAPON_TYPES = frozenset({0x0A, 0x0B})


class MemorySource(Protocol):
    def read_memory(self, address: int, length: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class AttackRange:
    """One attack an enemy can reach with, in object-relative pixels.

    Forward-oriented: ``forward_min``/``forward_max`` are distances ahead of
    the enemy's own origin along its facing, so the same range describes a
    left-facing enemy mirrored. Absolute coordinates come from
    :meth:`projected`, which needs the enemy's position and facing.

    Not a ``Token``: tokens may not embed tokens by value (``AI.md``), and an
    attack range is a property *of* an enemy, not an independent observation.

    ``forward_min`` is the reason this is a range and not a number. Nora's
    whip (shape ``$22``) starts 32 px out: inside that, her only attacking
    animation cannot touch the player at all.
    """

    shape_id: int
    animation: int
    forward_min: int
    forward_max: int
    lane_min: int
    lane_max: int
    height_min: int
    height_max: int

    @property
    def has_dead_zone(self) -> bool:
        """True when standing closer than ``forward_min`` is safe from it."""

        return self.forward_min > 0

    def covers(self, forward_dx: int, lane_dy: int) -> bool:
        """Would this reach a target ``forward_dx`` ahead and ``lane_dy`` off?

        ``forward_dx`` is signed along the enemy's facing: negative means
        behind it, which no forward-oriented box covers.
        """

        return (
            self.forward_min <= forward_dx <= self.forward_max
            and self.lane_min <= lane_dy <= self.lane_max
        )

    def projected(self, *, world_x: int, lane_y: int, world_z: int, facing_left: bool) -> Hitbox:
        """This range as an absolute AABB, were the attack thrown right now."""

        if facing_left:
            x0, x1 = world_x - self.forward_max, world_x - self.forward_min
        else:
            x0, x1 = world_x + self.forward_min, world_x + self.forward_max
        return Hitbox(
            x0=x0,
            x1=x1,
            y0=lane_y + self.lane_min,
            y1=lane_y + self.lane_max,
            z0=world_z + self.height_min,
            z1=world_z + self.height_max,
        )


@dataclass(frozen=True, slots=True)
class AnimationSets:
    """Raw bytes of every ordinary-enemy animation set, read once.

    ROM never changes, so this is read alongside :class:`hitboxes.ShapeTables`
    when the link is established and reused for the whole session.
    """

    blocks: Mapping[int, bytes]

    @classmethod
    def read(cls, client: MemorySource) -> AnimationSets:
        return cls(
            blocks={
                base: client.read_memory(base, ANIMATION_SET_BYTES)
                for base in ANIMATION_SET_BASES
            }
        )


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _frame_box_ids(block: bytes, anim_base: int, offset: int) -> tuple[int, int] | None:
    """``(attack id, body id)`` for one frame record, or ``None``.

    ``None`` covers a negative piece count, which is where both ``$AFE8`` and
    ``$B04C`` stop decoding, and any offset that leaves the block.
    """

    extra = 2 if offset & 0x8000 else 0
    record = anim_base + (offset & 0x7FFF)
    if record + 3 + extra > len(block):
        return None
    if block[record] & 0x80:
        return None
    return block[record + 1 + extra], block[record + 2 + extra]


def _reach_from_shape(tables: ShapeTables, box_id: int) -> tuple[int, int, int, int, int, int] | None:
    """A shape record as origin-relative extents, via ``hitboxes.build_box``.

    Building at the origin is what turns the ROM's absolute-coordinate
    construction into the relative extents an ``AttackRange`` wants, without
    re-implementing the sign extension and lane-table indirection.
    """

    box = build_box(tables, box_id=box_id, world_x=0, lane_y=0, world_z=0)
    if box is None:
        return None
    return box.x0, box.x1, box.y0, box.y1, box.z0, box.z1


def attack_ranges_for_set(
    sets: AnimationSets, tables: ShapeTables, set_base: int
) -> tuple[AttackRange, ...]:
    """Every reaching attack box the set's right-facing animations select.

    Deduplicated by shape id: the same box recurring across frames and
    animations is one reach, not several. Ordered by how far it reaches, so
    the longest is last and ``max`` needs no key.
    """

    block = sets.blocks.get(set_base)
    if not block:
        return ()

    first = _u16(block, 0)
    if first < 2 or first > len(block):
        return ()
    animation_count = first // 2

    found: dict[int, AttackRange] = {}
    # Even animations only -- the odd member of each pair is the same
    # animation facing left, and would contribute mirrored duplicates.
    for index in range(0, animation_count, 2):
        anim_base = _u16(block, 2 * index)
        if anim_base + 2 > len(block):
            continue
        frame_count = block[anim_base]
        for frame in range(frame_count):
            table_at = anim_base + 2 + 2 * frame
            if table_at + 2 > len(block):
                break
            ids = _frame_box_ids(block, anim_base, _u16(block, table_at))
            if ids is None:
                continue
            attack_id, body_id = ids
            if not attack_id or attack_id in found:
                continue
            attack = _reach_from_shape(tables, attack_id)
            if attack is None:
                continue
            body = _reach_from_shape(tables, body_id)
            body_forward = body[1] if body is not None else 0
            if attack[1] < body_forward + MIN_REACH_GAIN:
                # A contact box, not a strike -- see MIN_REACH_GAIN.
                continue
            found[attack_id] = AttackRange(
                shape_id=attack_id,
                animation=index,
                forward_min=attack[0],
                forward_max=attack[1],
                lane_min=attack[2],
                lane_max=attack[3],
                height_min=attack[4],
                height_max=attack[5],
            )
    return tuple(sorted(found.values(), key=lambda r: (r.forward_max, r.shape_id)))


def held_weapon_range(weapon_type: int) -> AttackRange | None:
    """The extra reach an enemy gains from the weapon it is carrying.

    Measured rather than extracted (see the module docstring): only bat and
    pipe have a published number, so every other held type returns ``None``
    rather than a guess.
    """

    if weapon_type not in MELEE_WEAPON_TYPES:
        return None
    return AttackRange(
        shape_id=0,
        animation=-1,
        forward_min=0,
        forward_max=MELEE_WEAPON_REACH_X,
        lane_min=-MELEE_WEAPON_LANE,
        lane_max=MELEE_WEAPON_LANE,
        height_min=-60,
        height_max=0,
    )


def attack_ranges_for_object(
    sets: AnimationSets,
    tables: ShapeTables,
    *,
    type_id: int,
    held_weapon_type: int = 0,
) -> tuple[AttackRange, ...]:
    """Every reach this enemy has right now: its own, plus what it carries."""

    set_base = ANIMATION_SET_FOR_TYPE.get(type_id & 0xFF)
    ranges = attack_ranges_for_set(sets, tables, set_base) if set_base is not None else ()
    weapon = held_weapon_range(held_weapon_type)
    if weapon is None:
        return ranges
    return tuple(sorted((*ranges, weapon), key=lambda r: (r.forward_max, r.shape_id)))
