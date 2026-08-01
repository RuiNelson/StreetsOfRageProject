"""Grab / hold / throw decision trees for standard controls.

ROM notes (``player-health-lives-and-combat.md``, ``sor.asm`` ``$2D20``):

- Holding: player ``+$60`` (type) and ``+$5E`` (pointer) non-zero.
- While holding, idle path is ``loc_00002D20`` (not the free-move path).
- Attack while holding goes through ``player_held_object_attack_input`` and
  selects actions ``$44/$46/$48`` for swings/throws of weapons or grabs.
- Direction low nibble of held input ``+$54`` selects grab strike/throw via
  the ``$2D6C`` table when the held target is in the grab-ready state.
- Face buttons are **edge-triggered**; directions must be **held** continuously.

With sticky ``hold_buttons``, this module:

- keeps throw direction latched across ticks;
- **pulses** attack (on one tick, off the next) so the ROM sees new edges.
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

# Grab sequence timing (agent decision ticks @ ~30 Hz with sticky hold).
KNEE_PULSES = 2  # attack edges while grabbing
THROW_FACE_TICKS = 2  # hold direction only so facing settles
THROW_ATTACK_TICKS = 3  # direction + pulsed attack


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
    held_type = me.held_type & 0xFF
    held_ptr = me.held_ptr & 0xFFFF
    # Be liberal: any of type/ptr/action family means we own a hold.
    action_grab = is_grab_family(me.action_base)
    holding = held_type != 0 or held_ptr != 0 or action_grab
    weapon = 0x08 <= held_type <= 0x0C
    enemy_grab = holding and (not weapon or action_grab)
    if action_grab and held_type == 0:
        enemy_grab = True
    return GrabContext(
        holding=holding,
        weapon=weapon and not action_grab,
        enemy_grab=enemy_grab,
        held_type=held_type,
        action_base=me.action_base,
        airborne=me.is_airborne,
        hurt=me.is_hurt,
    )


def is_grab_family(action_base: int) -> bool:
    return (
        0x28 <= action_base <= 0x2F
        or 0x44 <= action_base <= 0x4F
        or action_base == 0x4A
        or 0x30 <= action_base <= 0x3F  # grab strike variants in table $2D8C+
    )


@dataclass
class GrabMemory:
    """Per-player multi-tick grab/throw sequencer."""

    phase: str = "idle"  # idle | knee_on | knee_off | face | throw_on | throw_off
    knee_pulses: int = 0
    face_ticks: int = 0
    throw_ticks: int = 0
    throw_dir: int = 1  # +1 right, -1 left, 0 up
    attack_gate: bool = False  # alternate for edge generation

    def reset(self) -> None:
        self.phase = "idle"
        self.knee_pulses = 0
        self.face_ticks = 0
        self.throw_ticks = 0
        self.throw_dir = 1
        self.attack_gate = False


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

    if not ctx.holding:
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


def _throw_direction(
    me: MapEntity,
    *,
    foe: MapEntity | None,
    progress_right: bool,
    crowd: int,
) -> int:
    """+1 right, -1 left, 0 up."""

    if crowd >= 3:
        return 0  # up-throw to clear pack
    # Prefer throw toward stage progress.
    direction = 1 if progress_right else -1
    # Face away from densest nearby threat if known.
    if foe is not None and abs(foe.map_x - me.map_x) > 8:
        # Throw *along* progress, not necessarily toward the foe.
        pass
    return direction


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
    """Grabbed enemy: a couple of knee pulses, then face + throw with edges.

    Attack is pulsed (on/off) so sticky ``hold_buttons`` still produces
    press-edges. Direction for the throw stays held across the sequence.
    """

    if memory.phase == "idle":
        memory.phase = "knee_on"
        memory.knee_pulses = 0
        memory.attack_gate = True

    # --- Knee pulses: attack edge, no direction ---
    if memory.phase in ("knee_on", "knee_off"):
        if memory.knee_pulses >= KNEE_PULSES:
            memory.phase = "face"
            memory.face_ticks = 0
            memory.throw_dir = _throw_direction(
                me, foe=foe, progress_right=progress_right, crowd=crowd
            )
        elif memory.phase == "knee_on":
            memory.phase = "knee_off"
            memory.knee_pulses += 1
            return Intent(attack=True, note=f"grab knee {memory.knee_pulses}")
        else:
            # Release attack one tick so the next knee is a fresh edge.
            memory.phase = "knee_on"
            return Intent(note="grab knee gap")

    left = memory.throw_dir < 0
    right = memory.throw_dir > 0
    up = memory.throw_dir == 0

    # --- Face settle: hold direction only ---
    if memory.phase == "face":
        memory.face_ticks += 1
        if memory.face_ticks >= THROW_FACE_TICKS:
            memory.phase = "throw_on"
            memory.throw_ticks = 0
        return Intent(
            left=left,
            right=right,
            up=up,
            note="grab face " + ("U" if up else ("L" if left else "R")),
        )

    # --- Throw: direction held + pulsed attack ---
    if memory.phase in ("throw_on", "throw_off"):
        memory.throw_ticks += 1
        if memory.throw_ticks > THROW_ATTACK_TICKS * 2:
            # Finished sequence; if still holding next tick, restart.
            memory.reset()
            # Keep facing so we don't spin.
            return Intent(
                left=left,
                right=right,
                up=up,
                note="grab throw done",
            )
        if memory.phase == "throw_on":
            memory.phase = "throw_off"
            return Intent(
                left=left,
                right=right,
                up=up,
                attack=True,
                note="grab throw " + ("U" if up else ("L" if left else "R")),
            )
        memory.phase = "throw_on"
        return Intent(
            left=left,
            right=right,
            up=up,
            note="grab throw gap",
        )

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
    """Swing melee weapons; throw consumables at range. Pulse attack edges."""

    held = ctx.held_type
    melee = held in (WEAPON_BAT, WEAPON_PIPE)
    throwable = held in (WEAPON_KNIFE, WEAPON_BOTTLE, WEAPON_PEPPER)

    face_left = False
    face_right = False
    face_up = False
    face_down = False
    in_melee = False
    mid = False
    if foe is not None:
        dx = foe.map_x - me.map_x
        dy = foe.map_y - me.map_y
        face_left = dx < -4
        face_right = dx > 4
        face_up = dy < -8
        face_down = dy > 8
        in_melee = abs(dx) <= 36 and abs(dy) <= 14
        mid = 20 <= abs(dx) <= 90

    # Alternate attack gate so sticky hold still makes edges.
    memory.attack_gate = not memory.attack_gate
    pulse = memory.attack_gate

    if melee:
        if not in_melee and foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                up=face_up,
                down=face_down,
                note=f"weapon approach ${held:02X}",
            )
        return Intent(
            left=face_left,
            right=face_right,
            attack=pulse,
            note=f"weapon swing ${held:02X}",
        )

    if throwable:
        if foe is not None and in_melee and held == WEAPON_PEPPER:
            return Intent(attack=pulse, note="pepper spray")
        if foe is not None and mid:
            return Intent(
                left=face_left,
                right=face_right,
                attack=pulse,
                note=f"weapon throw ${held:02X}",
            )
        if foe is not None and in_melee:
            return Intent(attack=pulse, note=f"weapon poke ${held:02X}")
        if foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                up=face_up,
                down=face_down,
                note=f"weapon close ${held:02X}",
            )
        return Intent(note=f"hold weapon ${held:02X}")

    return Intent(attack=pulse, note=f"hold unknown ${held:02X}")


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
    return dx <= 22 and dy <= 12
