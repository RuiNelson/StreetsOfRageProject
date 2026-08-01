"""Grab / hold / throw decision trees for standard controls.

ROM notes (``player-health-lives-and-combat.md``, ``SoRInteractions.cpp``):

- Holding is tracked at player ``+$60`` (type) and ``+$5E`` (pointer).
- Weapon types ``$08-$0C`` use the held-object attack path (swing / throw).
- Enemy holds use action families ``$28+`` (grab) and ``$44+`` (throw select).
- While holding a target, directional input + attack selects grab strikes vs
  throws; attack+jump chord becomes action ``$4A`` (carry rear family).
- Normal grab *initiation* is collision/contact, not the attack button
  (attack near items prioritizes pickup). Walking into a stunned foe helps.

Standard controls only: B=attack, C=jump, D-pad=direction.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..world_map import MapEntity
from .controls import Intent


# Weapon type ids.
WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

# How many agent ticks to knee before throwing.
DEFAULT_KNEE_TICKS = 3
# Ticks to hold direction+attack for a committed throw.
THROW_HOLD_TICKS = 2


@dataclass(frozen=True, slots=True)
class GrabContext:
    """What the player is currently holding, if anything."""

    holding: bool
    weapon: bool
    enemy_grab: bool
    held_type: int
    action_base: int
    airborne: bool
    hurt: bool


def context_from_player(me: MapEntity) -> GrabContext:
    holding = me.is_holding
    weapon = me.is_holding_weapon
    # Enemy grab: held type outside weapon range, or action in grab family.
    enemy_grab = holding and not weapon
    if me.is_grabbing:
        enemy_grab = True
    return GrabContext(
        holding=holding,
        weapon=weapon,
        enemy_grab=enemy_grab or me.is_grabbing,
        held_type=me.held_type & 0xFF,
        action_base=me.action_base,
        airborne=me.is_airborne,
        hurt=me.is_hurt,
    )


def is_grab_family(action_base: int) -> bool:
    return 0x28 <= action_base <= 0x2F or 0x44 <= action_base <= 0x4F or action_base == 0x4A


@dataclass
class GrabMemory:
    """Per-player multi-tick grab/throw sequencer."""

    knees_done: int = 0
    throw_ticks: int = 0
    phase: str = "idle"  # idle | knee | throw | weapon_swing | weapon_throw
    throw_dir: int = 1  # +1 right, -1 left, 0 up

    def reset(self) -> None:
        self.knees_done = 0
        self.throw_ticks = 0
        self.phase = "idle"
        self.throw_dir = 1


def decide_held(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None = None,
    progress_right: bool = True,
    crowd: int = 0,
) -> Intent | None:
    """If holding something, return an intent; else None (caller continues)."""

    if ctx.hurt:
        memory.reset()
        return None

    if not ctx.holding and not is_grab_family(ctx.action_base):
        memory.reset()
        return None

    if ctx.weapon:
        return _weapon_tree(me, ctx, memory, tick=tick, foe=foe, crowd=crowd)

    return _enemy_grab_tree(
        me,
        ctx,
        memory,
        tick=tick,
        foe=foe,
        progress_right=progress_right,
        crowd=crowd,
    )


def _enemy_grab_tree(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    progress_right: bool,
    crowd: int,
) -> Intent:
    """Knee a few times, then throw toward progress or away from pack."""

    # Choose throw direction: toward stage progress, or away from densest side.
    throw_dir = 1 if progress_right else -1
    if foe is not None and abs(foe.map_x - me.map_x) > 4:
        # Throw the held target toward empty space / progress.
        throw_dir = 1 if (foe.map_x >= me.map_x) == progress_right else throw_dir

    if crowd >= 3:
        # Escape throw sooner when surrounded.
        knee_target = 1
    else:
        knee_target = DEFAULT_KNEE_TICKS

    if memory.phase == "idle":
        memory.phase = "knee"
        memory.knees_done = 0

    if memory.phase == "knee":
        if memory.knees_done < knee_target:
            memory.knees_done += 1
            # Grab strike: attack without direction (ROM grab path).
            return Intent(attack=True, note=f"grab knee {memory.knees_done}")
        memory.phase = "throw"
        memory.throw_ticks = 0
        memory.throw_dir = throw_dir

    if memory.phase == "throw":
        memory.throw_ticks += 1
        # Direction + attack = throw; occasionally up-throw for multi-enemy.
        up = crowd >= 2 and (tick % 5 == 0)
        left = memory.throw_dir < 0 and not up
        right = memory.throw_dir > 0 and not up
        if memory.throw_ticks >= THROW_HOLD_TICKS:
            memory.reset()
        return Intent(
            left=left,
            right=right,
            up=up,
            attack=True,
            note="grab throw" + (" up" if up else (" L" if left else " R")),
        )

    # Carry rear (attack+jump) if still holding after a failed throw phase.
    memory.reset()
    return Intent(rear_attack=True, note="grab rear escape")


def _weapon_tree(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    crowd: int,
) -> Intent:
    """Swing melee weapons; throw consumables (knife/bottle/pepper) at range."""

    held = ctx.held_type
    melee = held in (WEAPON_BAT, WEAPON_PIPE)
    throwable = held in (WEAPON_KNIFE, WEAPON_BOTTLE, WEAPON_PEPPER)

    # Face the foe if present.
    face_left = False
    face_right = False
    in_melee = False
    if foe is not None:
        dx = foe.map_x - me.map_x
        face_left = dx < -4
        face_right = dx > 4
        in_melee = abs(dx) <= 36 and abs(foe.map_y - me.map_y) <= 14

    if melee:
        if memory.phase not in ("weapon_swing", "idle"):
            memory.phase = "weapon_swing"
        # Bat/pipe: close and swing; throw only if many enemies and far.
        if not in_melee and foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                up=foe.map_y < me.map_y - 8,
                down=foe.map_y > me.map_y + 8,
                note=f"weapon approach ${held:02X}",
            )
        memory.reset()
        return Intent(
            left=face_left,
            right=face_right,
            attack=True,
            note=f"weapon swing ${held:02X}",
        )

    if throwable:
        # Prefer throw when a foe is mid-distance; swing/use if very close.
        if foe is not None and in_melee and held == WEAPON_PEPPER:
            return Intent(attack=True, note="pepper spray")
        if foe is not None and 20 <= abs(foe.map_x - me.map_x) <= 90:
            # Direction + attack throws knife/bottle in classic SoR.
            memory.phase = "weapon_throw"
            return Intent(
                left=face_left,
                right=face_right,
                attack=True,
                note=f"weapon throw ${held:02X}",
            )
        if foe is not None and abs(foe.map_x - me.map_x) < 20:
            return Intent(attack=True, note=f"weapon poke ${held:02X}")
        if foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                up=foe.map_y < me.map_y - 8,
                down=foe.map_y > me.map_y + 8,
                note=f"weapon close ${held:02X}",
            )
        # No foe: keep weapon, walk progress handled by caller if we return None
        # — but we're holding so just idle-hold.
        return Intent(note=f"hold weapon ${held:02X}")

    # Unknown held type: attack.
    return Intent(attack=True, note=f"hold unknown ${held:02X}")


def want_grab_approach(
    me: MapEntity,
    foe: MapEntity,
    *,
    grab_bias: float,
) -> bool:
    """True when we should walk into the foe without punching (grab setup)."""

    if grab_bias < 0.15:
        return False
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    # Same lane, close — collision grab window.
    return dx <= 22 and dy <= 12
