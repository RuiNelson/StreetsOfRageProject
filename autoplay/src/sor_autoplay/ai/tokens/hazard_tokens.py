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
    attack_box_id: int = 0  # +$02, latched by the renderer
    screen_x: int = 0  # +$28, biased ($80 = the left edge)
    countdown: int = 0  # +$6B: updates of the outbound leg left
    lane_target: int = 0  # +$52: the lane the return homes on
    lane_target_above: bool = False  # +$61
    turn_lane: int = 0  # +$78 word: what the turn copies into +$52
    knock_timer: int = 0  # +$7B: updates left once knocked away


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
