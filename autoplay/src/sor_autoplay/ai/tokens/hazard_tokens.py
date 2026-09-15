"""Projectile ``Information`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from ...hitboxes import Hitbox
from .tokens import Observed


@dataclass(frozen=True, slots=True, kw_only=True)
class Projectile(Observed):
    """Direct observation of a live projectile-kind object in flight.

    ``type_id`` distinguishes Jack's axe/torch helper (object_catalog.py
    type ``$28``) from every other projectile family: it is the one type
    whose object exists while still tethered to its owner's juggle, not
    only once thrown, so ``reach.jack_still_juggling`` needs it to tell the
    two apart.

    Antonio's boomerang (type ``$96``) also carries the rest of what its own
    update reads, for ``ai/antonio.py``'s ``BoomerangSim``: it runs the
    later-boss object layout, so ``vel_x`` is its ``+$1C`` X velocity and
    ``vel_lane`` its ``+$20``. Every other projectile leaves those fields 0.
    """

    slot: str
    world_x: int
    world_y: int
    vel_x: float
    vel_z: float
    type_id: int
    state: int = 0  # +$30: 0 on his hand, 1 out, 2 back, 3 knocked away
    vel_lane: float = 0.0  # +$20
    fine_x: float = 0.0  # +$10 as 16.16
    fine_y: float = 0.0  # +$14 as 16.16
    anim: int = 0  # +$08: $40 thrown right, $42 left
    anim_frame: int = 0  # +$0A, the frame shown next
    anim_countdown: int = 0  # +$0D: updates left on it (Bongo's flame hands over on it)
    attack_box_id: int = 0  # +$02, latched by the renderer
    screen_x: int = 0  # +$28, biased ($80 = the left edge)
    countdown: int = 0  # +$6B: updates of the outbound leg left
    lane_target: int = 0  # +$52: the lane the return homes on
    lane_target_above: bool = False  # +$61
    turn_lane: int = 0  # +$78 word: what the turn copies into +$52
    knock_timer: int = 0  # +$7B: updates left once knocked away
    # Jack's axe (type $28) only, for ai/jack.py's AxeSim: ``state`` is its own
    # +$30 (1 juggled, 2 tossed, 3 dropped, 4 thrown), ``vel_x``/``vel_lane``
    # its +$1C/+$20.
    world_z: int = 0  # +$18
    fine_z: float = 0.0  # +$18 as 16.16: the juggle arc is fractional
    owner_slot: str | None = None  # +$42: the Jack it belongs to
    flags_31: int = 0  # +$31: bit 1 = on its way back to his hand / released
    offset: float = 0.0  # +$54: its X offset from him while juggled
    timer_50: int = 0  # +$50: the tossed axe's hang countdown
    body_box_id: int = 0  # +$03


@dataclass(frozen=True, slots=True, kw_only=True)
class StageObjects(Observed, ABC):
    """An inanimate object placed in the stage, observed directly from RAM."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Pit(StageObjects):
    """A floor gap (pit) the player can fall into.

    Observed from ``GameSnapshot.floor_holes`` (the ``hazards.py``
    collision-class scan); fields mirror ``FloorHole`` — an AABB of the
    open region, ``lane_y`` being the top lane in pixels.
    """

    world_x: int
    lane_y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Breakable(StageObjects):
    """Intact smashable prop (phone booth, crate, …) — punch to break.

    Observed from map entities with ``kind == "breakable"`` that are still
    intact (not debris). Blocks lateral progress until destroyed.
    """

    slot: str
    world_x: int
    world_y: int
    type_id: int
    # The prop's animation body box, rebuilt from the ROM shape tables.
    # This is what the prop *draws*, and it is not what stops a walking
    # actor: the wall is the per-type push-back rectangle in
    # ``sor_autoplay.prop_solids``, which navigation/execute route against
    # and which needs only ``type_id``. Kept for display and for anything
    # that wants the sprite's own extent.
    hitbox: Hitbox | None = None
