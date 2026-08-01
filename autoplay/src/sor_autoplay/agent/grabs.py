"""Grab / hold / throw decision trees for standard controls.

GameFAQs + ROM (``$2D20`` / held attack path):

- Front grapple: **throw** = B + away from enemy (preferred over knee mash).
- **Vault** = C while grappling (flip behind), then **B** for back suplex.
- Grapple combo (B mash) is weaker / leaves you open — use sparingly.
- Face buttons are edge-triggered; directions stay held (sticky hold).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..world_map import MapEntity
from .characters import CharacterProfile, DEFAULT_PROFILE
from .controls import Intent


WEAPON_KNIFE = 0x08
WEAPON_BOTTLE = 0x09
WEAPON_BAT = 0x0A
WEAPON_PIPE = 0x0B
WEAPON_PEPPER = 0x0C

THROW_FACE_TICKS = 2
THROW_ATTACK_TICKS = 4
VAULT_TICKS = 3
BACK_SUPLEX_TICKS = 4


@dataclass(frozen=True, slots=True)
class GrabContext:
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
        or 0x30 <= action_base <= 0x3F
    )


@dataclass
class GrabMemory:
    """Phases: idle → [knee_*] → face → throw_*  OR  vault → suplex_*."""

    phase: str = "idle"
    knee_pulses: int = 0
    face_ticks: int = 0
    throw_ticks: int = 0
    vault_ticks: int = 0
    suplex_ticks: int = 0
    throw_dir: int = 1  # +1 right, -1 left (away from foe)
    attack_gate: bool = False

    def reset(self) -> None:
        self.phase = "idle"
        self.knee_pulses = 0
        self.face_ticks = 0
        self.throw_ticks = 0
        self.vault_ticks = 0
        self.suplex_ticks = 0
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
    profile: CharacterProfile | None = None,
) -> Intent | None:
    if ctx.hurt:
        memory.reset()
        return None
    if not ctx.holding:
        memory.reset()
        return None

    prof = profile if profile is not None else DEFAULT_PROFILE

    if ctx.weapon:
        return _weapon_tree(
            me, ctx, memory, tick=tick, foe=foe, crowd=crowd, profile=prof
        )

    return _enemy_grab_tree(
        me,
        ctx,
        memory,
        tick=tick,
        foe=foe,
        progress_right=progress_right,
        crowd=crowd,
        profile=prof,
    )


def _throw_away_direction(me: MapEntity, foe: MapEntity | None) -> int:
    """B+away from bad guy: direction opposite the foe relative to us."""

    if foe is None:
        return -1  # default throw left
    # Away from foe X.
    if foe.map_x >= me.map_x:
        return -1  # foe on right → throw left (away)
    return 1


def _enemy_grab_tree(
    me: MapEntity,
    ctx: GrabContext,
    memory: GrabMemory,
    *,
    tick: int,
    foe: MapEntity | None,
    progress_right: bool,
    crowd: int,
    profile: CharacterProfile,
) -> Intent:
    """Prefer throw (and optional vault→suplex); knees only if profile allows."""

    if memory.phase == "idle":
        # Safe vault for back suplex (Adam/Blaze FAQ) when not crowded.
        if profile.prefer_vault and crowd <= 1 and (tick + me.world_x) % 5 == 0:
            memory.phase = "vault"
            memory.vault_ticks = 0
        elif profile.grab_knees > 0 and crowd < 2:
            memory.phase = "knee_on"
            memory.knee_pulses = 0
        else:
            memory.phase = "face"
            memory.face_ticks = 0
            memory.throw_dir = _throw_away_direction(me, foe)

    # --- Vault (C) then back-suplex (B) ---
    if memory.phase == "vault":
        memory.vault_ticks += 1
        if memory.vault_ticks >= VAULT_TICKS:
            memory.phase = "suplex_on"
            memory.suplex_ticks = 0
        return Intent(jump=True, note=f"vault ({profile.name})")

    if memory.phase in ("suplex_on", "suplex_off"):
        memory.suplex_ticks += 1
        if memory.suplex_ticks > BACK_SUPLEX_TICKS * 2:
            memory.reset()
            return Intent(note="suplex done")
        if memory.phase == "suplex_on":
            memory.phase = "suplex_off"
            return Intent(attack=True, note=f"back suplex ({profile.name})")
        memory.phase = "suplex_on"
        return Intent(note="suplex gap")

    # --- Optional knee pulses (mostly Axel) ---
    if memory.phase in ("knee_on", "knee_off"):
        if memory.knee_pulses >= profile.grab_knees:
            memory.phase = "face"
            memory.face_ticks = 0
            memory.throw_dir = _throw_away_direction(me, foe)
        elif memory.phase == "knee_on":
            memory.phase = "knee_off"
            memory.knee_pulses += 1
            return Intent(attack=True, note=f"grab knee {memory.knee_pulses}")
        else:
            memory.phase = "knee_on"
            return Intent(note="grab knee gap")

    left = memory.throw_dir < 0
    right = memory.throw_dir > 0

    # Crowd: hurl toward densest progress direction instead of pure away.
    if crowd >= 3 and memory.phase in ("face", "throw_on", "throw_off", "idle"):
        # Prefer throwing into stage progress to hit packs.
        if progress_right:
            left, right = False, True
            memory.throw_dir = 1
        else:
            left, right = True, False
            memory.throw_dir = -1

    if memory.phase == "face":
        memory.face_ticks += 1
        if memory.face_ticks >= THROW_FACE_TICKS:
            memory.phase = "throw_on"
            memory.throw_ticks = 0
        return Intent(
            left=left,
            right=right,
            note=f"throw face ({profile.name}) " + ("L" if left else "R"),
        )

    if memory.phase in ("throw_on", "throw_off"):
        memory.throw_ticks += 1
        if memory.throw_ticks > THROW_ATTACK_TICKS * 2:
            memory.reset()
            return Intent(left=left, right=right, note="throw done")
        if memory.phase == "throw_on":
            memory.phase = "throw_off"
            # B + away = shoulder throw / Blaze flip throw.
            return Intent(
                left=left,
                right=right,
                attack=True,
                note=f"throw ({profile.name}) " + ("L" if left else "R"),
            )
        memory.phase = "throw_on"
        return Intent(left=left, right=right, note="throw gap")

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
    profile: CharacterProfile,
) -> Intent:
    held = ctx.held_type
    melee = held in (WEAPON_BAT, WEAPON_PIPE)
    throwable = held in (WEAPON_KNIFE, WEAPON_BOTTLE, WEAPON_PEPPER)

    # Blaze: weak with knife/bottle — prefer throwing them ASAP at mid range.
    blaze_weak = held in profile.weak_weapons

    face_left = face_right = face_up = face_down = False
    in_melee = mid = False
    if foe is not None:
        dx = foe.map_x - me.map_x
        dy = foe.map_y - me.map_y
        face_left = dx < -4
        face_right = dx > 4
        face_up = dy < -8
        face_down = dy > 8
        in_melee = abs(dx) <= 36 and abs(dy) <= 14
        mid = 20 <= abs(dx) <= 100

    memory.attack_gate = not memory.attack_gate
    pulse = memory.attack_gate

    if melee:
        # Adam/Blaze shine with bat/pipe — close and swing.
        if not in_melee and foe is not None:
            return Intent(
                left=face_left,
                right=face_right,
                up=face_up,
                down=face_down,
                note=f"weapon approach ${held:02X} ({profile.name})",
            )
        return Intent(
            left=face_left,
            right=face_right,
            attack=pulse,
            note=f"weapon swing ${held:02X} ({profile.name})",
        )

    if throwable:
        if blaze_weak and foe is not None:
            # Get rid of weak weapons quickly via throw.
            return Intent(
                left=face_left,
                right=face_right,
                attack=pulse,
                note=f"dump weapon ${held:02X}",
            )
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
    if grab_bias < 0.15:
        return False
    dx = abs(foe.map_x - me.map_x)
    dy = abs(foe.map_y - me.map_y)
    return dx <= 22 and dy <= 12
