"""The unarmed jump kick, update by update -- the ROM's own physics, measured.

User: "a IA não tem bem ideia do ataque de pontapé no ar, estudar bem esse
ataque para ser previsível para a IA, não só para quando tem um partner, mas
também para ser usado no resto para calcular os ataques". Everything the
pipeline knows about a jump kick -- where the kicker is on every frame of the
flight, when its kick box is out and where, and so which bodies the kick
lands on -- comes from here, for the AI's own kicks and for the partner's.

**Objects move at 30 Hz.** ``$AD8E (update_objects_and_build_sprites)``
updates both players, waits a VBlank itself (``$10514``,
``wait_vblank_without_graphics_upload``) and only then runs the 66 object
slots, and the main loop waits the second VBlank: every object, player and
enemy alike, moves once per two 60 Hz frames. So every ROM rate below is per
*update*, and a flight lasts twice as many frames as it has updates (plus a
lag frame now and then, when a pass overruns). Measured in lockstep
(``tools/jump_kick_lab.py``): the crouch timer ``+$0D`` steps 5 to 1 over
**10** frames, and X changes on every other frame.

The model, update by update (``$1FC0`` crouch, ``$1FDC`` free flight,
``$2000`` kick):

- **crouch** ``$10``: 5 updates on the ground;
- **launch** (the update the crouch runs out): ``$3832`` sets v_z from
  ``$3842`` -- Axel -7.5, Adam -8.5, Blaze -9.5 -- and ``$384E`` sets v_x to
  +-3.0 toward a held Left/Right (0 with neither), turning the facing; the
  position integrates once with those, with no gravity yet;
- **free flight** ``$12``: gravity +0.90625 (``$389A``), then air steer
  +-0.375 toward a held Left/Right, clamped to +-3.5 (``$38C0``, which turns
  the facing too), then a fresh B edge turns it into the kick (``$3914``,
  keeping v_x);
- **kick** ``$16``: no air steer at all; gravity +0.90625 while v_z < 0 and
  the lighter +0.53125 once it is not (``$38AE`` tests the sign first); a
  damaging contact holds the flight still -- no gravity, no movement -- for
  4 updates (``$21B4``), after which it resumes along the same path;
- every update v_z <= 12 (``$3886``), x += v_x, z += v_z, and the update
  that takes z past the floor lands (``$3E78``: z snaps to the floor, action
  ``$14`` for 5 updates, then idle).

The kick box (``+$64``), relative to the origin while facing right, is
exactly what the manuscript measured -- Axel x 14..42 z -46..-19, Adam
x 17..72 z -43..-14, Blaze x 3..49 z -38..-6, lane +-8 for all three. Axel
and Adam put it out on the kick edge's own update, 3 damage every update to
the landing; Blaze's kick animation carries no box on its first two frames
(3 updates each), so hers comes out **6 updates after the edge**, 2 damage.
The box sits high on the body: near the top of the arc it clears a standing
body (Axel's is z -51..0) altogether, so a kick X-aligned with a body can
still pass over it -- and low on the way up and down it reaches far: Axel's
kick lands on a standing body as far as ~110 px from where he took off,
nearly twice the 60 px the old reach band assumed. That gap is what let
kicks aimed at an enemy land on a partner standing further along.

Measured flights (lab, B on the first free-flight update, direction held):

| | lands (updates after launch) | X travelled | apex |
| --- | --- | --- | --- |
| Axel | 19 (17 without the kick) | 67.1 (62.4) | -34.9 |
| Adam | 23 (~19.5) | 77.3 (69.4) | -44.2 |
| Blaze | ~24 (~21) | 84.0 (76.4) | -54.7 |
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from ..hitboxes import Hitbox
from .kinematics import AI_LATENCY_FRAMES
from .tokens import Character, Enemy, PlayableCharacter

# One object update, in 60 Hz frames -- see the module docstring.
UPDATE_FRAMES = 2

CROUCH_UPDATES = 5
LAND_UPDATES = 5
LAUNCH_SPEED_X = 3.0
LAUNCH_SPEED_Z: dict[int, float] = {0: -7.5, 1: -8.5, 2: -9.5}
# Blaze's, the highest and longest flight: an unknown kicker is assumed to
# stay in the air, and to reach, as far as any of the three can.
DEFAULT_LAUNCH_SPEED_Z = -9.5
GRAVITY = 0.90625
KICK_FALL_GRAVITY = 0.53125
AIR_STEER = 0.375
AIR_SPEED_MAX = 3.5
FALL_SPEED_MAX = 12.0
HIT_FREEZE_UPDATES = 4

# The kick box (+$64) and the standing body (+$70, idle), each
# (x0, x1, lane0, lane1, z0, z1) relative to the origin while facing right.
KICK_BOX: dict[int, tuple[int, int, int, int, int, int]] = {
    0: (14, 42, -8, 8, -46, -19),
    1: (17, 72, -8, 8, -43, -14),
    2: (3, 49, -8, 8, -38, -6),
}
# The widest reach of the three, for the same reason as above.
DEFAULT_KICK_BOX = (3, 72, -8, 8, -46, -6)
KICK_BOX_DELAY_UPDATES: dict[int, int] = {0: 0, 1: 0, 2: 6}
STANDING_BODY: dict[int, tuple[int, int, int, int, int, int]] = {
    0: (0, 13, -8, 8, -51, 0),
    1: (-5, 7, -8, 8, -53, 0),
    2: (2, 12, -8, 8, -48, 0),
}
# A body of unknown shape: centred, a player's width and height.
DEFAULT_BODY = (-7, 7, -8, 8, -53, 0)

ACTION_CROUCH = 0x10
ACTION_FREE_FLIGHT = 0x12
ACTION_KICK = 0x16

# The executor presses B on the first tick it sees free flight, so the edge
# reaches ``$3914`` on free-flight update 1 or 2 depending on where the poll
# falls; a judgment that has to hold "whenever the kick comes out" asks both.
KICK_EDGE_UPDATES = (1, 2)
# Longer than any flight (Blaze lands ~24 updates after launch).
MAX_FLIGHT_UPDATES = 48


@dataclass(frozen=True, slots=True)
class KickStep:
    """One update of a flight: where the kicker's origin is after it moved,
    how many 60 Hz frames from now that is, and the kick box it has out then
    (``None`` on an update with no damaging box, and on the landing)."""

    frame: int
    x: float
    z: float
    attack: Hitbox | None
    landed: bool = False


def launch_speed_z(character_id: int | None) -> float:
    if character_id is None:
        return DEFAULT_LAUNCH_SPEED_Z
    return LAUNCH_SPEED_Z.get(character_id, DEFAULT_LAUNCH_SPEED_Z)


def kick_box(character_id: int | None) -> tuple[int, int, int, int, int, int]:
    if character_id is None:
        return DEFAULT_KICK_BOX
    return KICK_BOX.get(character_id, DEFAULT_KICK_BOX)


def kick_box_delay(character_id: int | None) -> int:
    if character_id is None:
        return 0
    return KICK_BOX_DELAY_UPDATES.get(character_id, 0)


def _placed(
    rel: tuple[int, int, int, int, int, int], x: float, lane: float, z: float, facing_left: bool
) -> Hitbox:
    """A relative box placed at an origin the way ``$4140`` places it: on the
    position's integer part (the high word of the 16.16 long), mirrored in X
    when facing left."""

    x0, x1, y0, y1, z0, z1 = rel
    if facing_left:
        x0, x1 = -x1, -x0
    ox, oy, oz = math.floor(x), math.floor(lane), math.floor(z)
    return Hitbox(x0=ox + x0, x1=ox + x1, y0=oy + y0, y1=oy + y1, z0=oz + z0, z1=oz + z1)


def _fly(
    *,
    character_id: int | None,
    lane: float,
    ground_z: float,
    x: float,
    z: float,
    vx: float,
    vz: float,
    facing_left: bool,
    kicking: bool,
    kick_age: int,
    steer: int,
    kick_on: int | None,
    frame: int,
) -> list[KickStep]:
    """Free flight and kick from a state the kicker is already in, one
    ``KickStep`` per update until the landing (included, flagged)."""

    rel = kick_box(character_id)
    delay = kick_box_delay(character_id)
    steps: list[KickStep] = []
    for update in range(1, MAX_FLIGHT_UPDATES + 1):
        if kicking:
            vz += GRAVITY if vz < 0 else KICK_FALL_GRAVITY
            kick_age += 1
        else:
            vz += GRAVITY
            if steer:
                vx = max(-AIR_SPEED_MAX, min(AIR_SPEED_MAX, vx + steer * AIR_STEER))
                facing_left = steer < 0
            if kick_on is not None and update == kick_on:
                kicking, kick_age = True, 0
        vz = min(vz, FALL_SPEED_MAX)
        x += vx
        z += vz
        frame += UPDATE_FRAMES
        if z >= ground_z:
            steps.append(KickStep(frame=frame, x=x, z=ground_z, attack=None, landed=True))
            break
        attack = _placed(rel, x, lane, z, facing_left) if kicking and kick_age >= delay else None
        steps.append(KickStep(frame=frame, x=x, z=z, attack=attack))
    return steps


def launch_arc(
    actor: PlayableCharacter, *, direction: int, kick_on: int | None = 1
) -> list[KickStep]:
    """The flight a jump launched now would take, with the kick edge on
    free-flight update ``kick_on`` (``None``: no kick) and ``direction``
    (-1, 0, +1) held from the press to the landing -- what
    ``execute.state_machine_jump_attack`` does.

    The first step is the launch update itself, ``AI_LATENCY_FRAMES`` plus
    the 10-frame crouch from now; the actor is taken to be standing on its
    floor (``world_z``).
    """

    ground = float(actor.world_z)
    facing_left = direction < 0 if direction else actor.facing_left
    vx = LAUNCH_SPEED_X * direction
    vz = launch_speed_z(actor.character_id)
    frame = AI_LATENCY_FRAMES + CROUCH_UPDATES * UPDATE_FRAMES
    x = actor.world_x + vx
    z = ground + vz
    launch = KickStep(frame=frame, x=x, z=z, attack=None)
    return [
        launch,
        *_fly(
            character_id=actor.character_id,
            lane=actor.world_y,
            ground_z=ground,
            x=x,
            z=z,
            vx=vx,
            vz=vz,
            facing_left=facing_left,
            kicking=False,
            kick_age=0,
            steer=direction,
            kick_on=kick_on,
            frame=frame,
        ),
    ]


def airborne_arc(player: PlayableCharacter, *, kick_on: int | None = 1) -> list[KickStep]:
    """The rest of a flight ``player`` is already in, or ``[]`` when that is
    not an unarmed jump this model knows or its floor is unknown.

    A kick already out keeps going, its box assumed out (Blaze's six quiet
    updates are not observed from outside, and assuming them over would
    under-state her kick). Free flight kicks on update ``kick_on`` from now
    (``None``: not at all) and steers nowhere: what the kicker holds is not
    observed, so its velocity is taken as it is. A crouch has not launched
    yet; it is taken to launch on the next update, toward its facing.
    """

    ground = player.ground_z
    if ground is None:
        return []
    base = player.action_state & 0xFE
    char = player.character_id
    if base == ACTION_CROUCH:
        direction = -1 if player.facing_left else 1
        vx = LAUNCH_SPEED_X * direction
        vz = launch_speed_z(char)
        x = player.world_x + vx
        z = float(ground) + vz
        frame = AI_LATENCY_FRAMES + UPDATE_FRAMES
        launch = KickStep(frame=frame, x=x, z=z, attack=None)
        return [
            launch,
            *_fly(
                character_id=char,
                lane=player.world_y,
                ground_z=float(ground),
                x=x,
                z=z,
                vx=vx,
                vz=vz,
                facing_left=player.facing_left,
                kicking=False,
                kick_age=0,
                steer=0,
                kick_on=kick_on,
                frame=frame,
            ),
        ]
    if base not in (ACTION_FREE_FLIGHT, ACTION_KICK):
        return []
    kicking = base == ACTION_KICK
    return _fly(
        character_id=char,
        lane=player.world_y,
        ground_z=float(ground),
        x=float(player.world_x),
        z=float(player.world_z),
        vx=player.vel_x,
        vz=player.vel_z,
        facing_left=player.facing_left,
        kicking=kicking,
        kick_age=kick_box_delay(char) if kicking else 0,
        steer=0,
        kick_on=None if kicking else kick_on,
        frame=AI_LATENCY_FRAMES - UPDATE_FRAMES,
    )


def landing_dx(actor: PlayableCharacter) -> float:
    """How far a kick launched now carries the actor before it lands, B on
    the first free-flight update and the direction held throughout."""

    arc = launch_arc(actor, direction=1, kick_on=1)
    return arc[-1].x - actor.world_x


def overlaps(attack: Hitbox, body: Hitbox, *, inclusive: bool) -> bool:
    """The ROM's contact test between a kick box and a body.

    Two routines, two comparisons: an enemy's ``$AAA0`` tests the player's
    box through ``$AB88``, strictly on every axis (``Hitbox.overlaps``);
    ``$4478``'s ``$450C``, the test against the *other player*, compares with
    ``bgt``/``blt``/``bge``, so there boxes that merely touch already hit.
    """

    if not inclusive:
        return attack.overlaps(body)
    return (
        attack.x0 <= body.x1
        and body.x0 <= attack.x1
        and attack.y0 <= body.y1
        and body.y0 <= attack.y1
        and attack.z0 <= body.z1
        and body.z0 <= attack.z1
    )


def first_hit_frame(
    steps: list[KickStep],
    body_at: Callable[[int], Hitbox | None],
    *,
    inclusive: bool,
) -> int | None:
    """The first frame whose kick box lands on the body ``body_at`` places
    at that frame, or ``None`` when the whole flight misses it."""

    for step in steps:
        if step.attack is None:
            continue
        body = body_at(step.frame)
        if body is not None and overlaps(step.attack, body, inclusive=inclusive):
            return step.frame
    return None


def standing_body(
    rel: tuple[int, int, int, int, int, int],
    x: float,
    lane: float,
    ground_z: float,
    facing_left: bool,
) -> Hitbox:
    return _placed(rel, x, lane, ground_z, facing_left)


def enemy_body(enemy: Enemy, *, ground_z: float) -> Hitbox:
    """``enemy``'s own body box, or a player-sized stand-in on the floor
    when the ROM tables were not available to rebuild it."""

    box = enemy.hitbox
    if box is not None and not box.is_degenerate:
        return box
    return standing_body(DEFAULT_BODY, enemy.world_x, enemy.world_y, ground_z, enemy.facing_left)


def player_body(player: PlayableCharacter) -> Hitbox:
    """``player``'s body box (``+$70``), or its standing one on its floor."""

    box = player.hitbox
    if box is not None and not box.is_degenerate:
        return box
    rel = STANDING_BODY.get(player.character_id, DEFAULT_BODY) if player.character_id is not None else DEFAULT_BODY
    ground = player.ground_z if player.ground_z is not None else player.world_z
    return standing_body(rel, player.world_x, player.world_y, float(ground), player.facing_left)


def moving_body(
    body: Hitbox, vel_x: float, *, margin_x: int = 0, margin_y: int = 0
) -> Callable[[int], Hitbox]:
    """``body`` carried along at ``vel_x`` px per update, widened by the
    margins: where a walking player will be ``frame`` frames from now."""

    def at(frame: int) -> Hitbox:
        shift = math.floor(vel_x * frame / UPDATE_FRAMES)
        return Hitbox(
            x0=body.x0 + shift - margin_x,
            x1=body.x1 + shift + margin_x,
            y0=body.y0 - margin_y,
            y1=body.y1 + margin_y,
            z0=body.z0,
            z1=body.z1,
        )

    return at


def launch_direction(actor: PlayableCharacter, target: Character) -> int:
    """The way the executor launches a jump kick at ``target``: toward it,
    or the way the actor faces when the two share an X."""

    dx = target.world_x - actor.world_x
    if dx:
        return 1 if dx > 0 else -1
    return -1 if actor.facing_left else 1


@lru_cache(maxsize=None)
def landing_distance(character_id: int | None) -> float:
    """How far a kick launched now carries the kicker before it lands: B on
    the first free-flight update, the direction held throughout. The lab's
    67.1 / 77.3 / 84.0 px."""

    vx = LAUNCH_SPEED_X
    vz = launch_speed_z(character_id)
    steps = _fly(
        character_id=character_id,
        lane=0.0,
        ground_z=0.0,
        x=vx,
        z=vz,
        vx=vx,
        vz=vz,
        facing_left=False,
        kicking=False,
        kick_age=0,
        steer=1,
        kick_on=1,
        frame=0,
    )
    return steps[-1].x


def launch_hits(actor: PlayableCharacter, target: Enemy) -> bool:
    """Would a kick launched at ``target`` now land on its body -- whichever
    of ``KICK_EDGE_UPDATES`` the executor's B edge reaches the ROM on?

    Against an enemy, so ``$AB88``'s strict comparison. ``target`` is taken
    to stay where it is for the flight: the caller projects it over the
    crouch first (``reach.connects``), and trusting a velocity past that is
    what once had the AI launch from 100+ px at a target that then stopped.
    """

    direction = launch_direction(actor, target)
    body = enemy_body(target, ground_z=float(actor.world_z))
    return all(
        first_hit_frame(
            launch_arc(actor, direction=direction, kick_on=kick_on),
            lambda frame: body,
            inclusive=False,
        )
        is not None
        for kick_on in KICK_EDGE_UPDATES
    )


def airborne_hits(actor: PlayableCharacter, target: Enemy) -> bool | None:
    """Would B pressed now still land on ``target`` before the actor comes
    down? ``None`` when the flight cannot be followed (floor unknown)."""

    steps = airborne_arc(actor, kick_on=1)
    if not steps or actor.ground_z is None:
        return None
    body = enemy_body(target, ground_z=float(actor.ground_z))
    return first_hit_frame(steps, lambda frame: body, inclusive=False) is not None


# A human partner moves without notice: the body a kick has to miss is
# theirs carried along at the velocity they have, and then this much wider.
PARTNER_MARGIN_X = 8
PARTNER_MARGIN_Y = 4


def _partner_body_at(player: PlayableCharacter) -> Callable[[int], Hitbox]:
    return moving_body(
        player_body(player), player.vel_x, margin_x=PARTNER_MARGIN_X, margin_y=PARTNER_MARGIN_Y
    )


def launch_hits_player(actor: PlayableCharacter, player: PlayableCharacter, *, direction: int) -> bool:
    """Would a kick launched now in ``direction`` touch the other player on
    any update of its flight, whichever edge the kick comes out on?

    ``$450C``'s inclusive comparison, the partner's body carried at their own
    velocity and widened by ``PARTNER_MARGIN_X``/``_Y``: the answer has to
    be "no" for every kick the executor might actually throw.
    """

    body_at = _partner_body_at(player)
    return any(
        first_hit_frame(
            launch_arc(actor, direction=direction, kick_on=kick_on), body_at, inclusive=True
        )
        is not None
        for kick_on in KICK_EDGE_UPDATES
    )


def airborne_hits_player(actor: PlayableCharacter, player: PlayableCharacter) -> bool:
    """Would B pressed now (or on the next update) put the kick on the other
    player before the actor lands? Unknown flights answer yes: not kicking
    costs a kick, kicking the partner costs the partner."""

    if actor.ground_z is None:
        return True
    body_at = _partner_body_at(player)
    return any(
        first_hit_frame(airborne_arc(actor, kick_on=kick_on), body_at, inclusive=True)
        is not None
        for kick_on in KICK_EDGE_UPDATES
    )


def enemies_hit(actor: PlayableCharacter, target: Enemy, enemies: list[Enemy]) -> list[Enemy]:
    """Every enemy a kick launched at ``target`` now would land on.

    The kick stays out from its edge to the landing and hits every body its
    box crosses (``controls-and-input.md``: same-lane packs on the flight
    path are one of the kick's strongest uses). A hit freezes the flight for
    ``HIT_FREEZE_UPDATES`` and then resumes along the same path, so against
    bodies that stay put the set hit does not depend on the freezes.
    """

    ground = float(actor.world_z)
    steps = launch_arc(actor, direction=launch_direction(actor, target), kick_on=1)
    return [
        enemy
        for enemy in enemies
        if first_hit_frame(
            steps, lambda frame, e=enemy: enemy_body(e, ground_z=ground), inclusive=False
        )
        is not None
    ]


def swept_area(steps: list[KickStep]) -> Hitbox | None:
    """The smallest box covering every kick box of a flight -- the ground a
    kick sweeps, for anything that has to keep clear of it."""

    boxes = [step.attack for step in steps if step.attack is not None]
    if not boxes:
        return None
    return Hitbox(
        x0=min(b.x0 for b in boxes),
        x1=max(b.x1 for b in boxes),
        y0=min(b.y0 for b in boxes),
        y1=max(b.y1 for b in boxes),
        z0=min(b.z0 for b in boxes),
        z1=max(b.z1 for b in boxes),
    )
