"""Extract a 2D world map replica from player slots, object table, and camera.

Visualization is a **top-down stage map** (not CRT sprite projection):

    map_x = world_x - cam_x          # horizontal, camera-relative
    map_y = lane_y                   # depth (+$14); small = back of stage

Elevation ``world_z`` (+$18) is kept on each entity for diagnostics but is
**not** applied to the plot. The camera rectangle is the player walk band
(32..288 × 0..lane_max from ``clamp_players_to_gameplay_bounds``), not the full
320 px CRT — so a player at the left/right walk limit sits on the box rim.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import memory_map as mm
from .object_catalog import EntityStyle, player_style, style_for_object
from .attack_ranges import AttackRange, attack_ranges_for_object
from .hitboxes import OBJ_CACHED_BODY_BOX, Hitbox, cached_box, object_boxes
from .rom_data import RomData
from .phases import (
    CombatPhase,
    boss_phase,
    decode_target_seat,
    ordinary_enemy_phase,
    phase_label,
    player_is_held_by_enemy_action,
    player_phase,
)

# Horizontal span of one Mega Drive screen in world-X units (CRT viewport).
# Agent on-screen / activation checks still use this full 320 band.
SCREEN_WIDTH = 320
# Playable walk band from clamp_players_to_gameplay_bounds ($43AA):
#   X: min = cam_x + $20, span = $100 → map_x ∈ [32, 288]
#   Y: min = $02, max = $70 (most rounds), max = $A0 on level index 6 (round 7).
# Live check (player held at left limit): world_x - cam_x == 32.
LANE_Y_MIN = 0x02
LANE_Y_MAX_DEFAULT = 0x70
LANE_Y_MAX_ROUND7 = 0xA0  # level_index == 6
CAMERA_X_MIN = 0x20  # left walk limit relative to camera
CAMERA_X_SPAN = 0x100  # walkable width (not the full 320 px CRT)
# Default camera height for aspect / empty maps (most rounds).
LANE_BAND_HEIGHT = LANE_Y_MAX_DEFAULT  # 112
# Camera box aspect = walk band, not full CRT (player min X sits on the left rim).
MAP_ASPECT = CAMERA_X_SPAN / LANE_BAND_HEIGHT  # 256/112 ≈ 2.286

CAMERA_WORLD_LEFT = float(CAMERA_X_MIN)
CAMERA_WORLD_WIDTH = float(CAMERA_X_SPAN)
CAMERA_WORLD_RIGHT = CAMERA_WORLD_LEFT + CAMERA_WORLD_WIDTH  # 288
CAMERA_WORLD_HEIGHT = float(LANE_BAND_HEIGHT)

# Soft padding around the camera for the *view* (full map plate). The HUD maps
# the view and draws the true camera as a subset: camera stays exactly
# 32..288 × 0..lane_max (player walk clamp). Combat targeting still uses the
# full CRT-relative 0..320 X band (SCREEN_WIDTH). Loot uses the walk band plus
# the ROM pickup half-width so the agent never walks toward dim/off-camera
# collectables stranded past the clamp.
VIEW_MARGIN_X = 40.0
VIEW_MARGIN_Y = 16.0
# How far outside the visible screen (in map_x) we still list actors so they
# appear in the off-camera map ring. Combat still requires map_x in 0..320;
# loot is tighter (see LOOT_CAMERA_*).
INCLUDE_MARGIN_X = SCREEN_WIDTH * 2
INCLUDE_MARGIN_Y = LANE_BAND_HEIGHT // 2
# ROM $3136 pickup search is about ±$14 on X. Match combat.PICKUP_SAFE_X so a
# free ground item is only COLLECTIBLE when some legal player stand point in
# the walk band can reach it without forcing a camera scroll.
LOOT_REACH_X = 16.0
LOOT_CAMERA_LEFT = CAMERA_WORLD_LEFT - LOOT_REACH_X  # 16
LOOT_CAMERA_RIGHT = CAMERA_WORLD_RIGHT + LOOT_REACH_X  # 304


def is_in_loot_camera(map_x: float) -> bool:
    """True when map_x is within walk-band camera ± pickup reach.

    Items outside this band may still be drawn dim on the diagnostic map (view
    ring / CRT letterbox), but the player cannot stand close enough for B to
    collect them without a scroll the agent cannot force (locked waves, left
    camera edge).
    """

    return LOOT_CAMERA_LEFT <= float(map_x) <= LOOT_CAMERA_RIGHT

# HUD letterbox uses the same aspect as the lane camera band.
SCREEN_HEIGHT = LANE_BAND_HEIGHT


def lane_y_max_for_level(level_index: int) -> int:
    """Playable lane ceiling for the current campaign level index."""

    return LANE_Y_MAX_ROUND7 if level_index == 6 else LANE_Y_MAX_DEFAULT

_MAP_KINDS = frozenset(
    {
        "player",
        "enemy",
        "boss",
        "weapon",
        "breakable",
        "pickup",
        "projectile",
    }
)

OBJECT_SLOT_COUNT = mm.OBJECT_TABLE_SLOTS  # 66
OBJECT_SLOT_SIZE = mm.OBJECT_SLOT_SIZE  # 0x80
OBJECT_TABLE_BYTES = OBJECT_SLOT_COUNT * OBJECT_SLOT_SIZE

ADDR_ACTORS_BASE = mm.ADDR_P1_OBJECT  # 0xFFB800
ACTORS_BYTES = 0x100 + OBJECT_TABLE_BYTES

ADDR_CAMERA_BASE = 0xFFE000
CAMERA_BYTES = 0x20
CAM_X_OFF = 0x02
CAM_Y_OFF = 0x0E


@dataclass(frozen=True, slots=True)
class MapEntity:
    """One drawable object in world space + top-down map space."""

    kind: str
    family: str
    symbol: str
    color: str
    label: str
    type_id: int
    world_x: int
    world_y: int  # lane / depth at +$14
    world_z: int  # elevation at +$18 (stored for diagnostics; not used in plot)
    # Top-down map coordinates (camera-relative X, absolute lane Y).
    map_x: float
    map_y: float
    health: int | None
    slot: str
    # Agent combat fields (defaults keep older call sites valid).
    action_state: int = 0  # low byte of +$30 (player action / boss primary)
    primary_state: int = 0  # full word at +$30 (ordinary enemy $0100 steps)
    character_id: int | None = None  # player-only; 0/1/2 = Axel/Adam/Blaze
    held_type: int = 0  # player +$60; nonzero while holding weapon/grab target
    held_ptr: int = 0  # player +$5E low word
    contact_ptr: int = 0  # player +$4C contact/grab partner (live hold uses this)
    outgoing_damage: int = 0  # +$34 active hit frame damage nibble
    action_flags: int = 0  # player +$58; bit5 combo queue, bit7 grab-counter window
    tech_armed: int = 0  # player +$45; bounce-cancel tech arm
    tech_latched: int = 0  # player +$46; C+Up latched before land
    combo_state: int = 0  # player +$5D
    tactical: int = 0  # boss +$67
    pair_role: int = 0  # later-boss +$5D (1/2) when kind==boss
    target_ptr: int = 0  # ordinary +$42 / boss target low word
    attacker_ptr: int = 0  # ordinary +$3E attacker/holder low word
    family_state: int = 0  # ordinary +$52; Jack bit0 = weapon attached
    subtype: int = 0  # generic +$0B family-local subtype/debris selector
    script_param: int = 0  # generic +$40 ELC parameter; type $45 motion selector
    # Weapon wear (+$50, usable when < 3) / pickup effect index. Shared offset
    # with player character id and boss distances — only meaningful for
    # weapon/pickup kinds.
    item_param: int = 0
    # Ordinary enemies (kind=="enemy" only): remaining stun frames at the same
    # +$50 offset. Seeded with $18 by the hitstun handler $9B88 and with $A0 by
    # the pepper-spray path in $A43E, and counted down by whichever of the two
    # owns the current state — so it is only meaningful while combat_phase is
    # CombatPhase.STUNNED.
    stun_timer: int = 0
    # Weapon/pickup +$51: zero = free ground object; nonzero = held/thrown/
    # reserved/mid-collect. ROM will not start a pickup when this is set.
    interaction: int = 0
    facing_left: bool = False  # ordinary +$09 bit1; player action bit0
    boss_dist_x: int = 0  # later-boss +$50 abs X to target
    boss_dist_lane: int = 0  # later-boss +$52 abs lane to target
    mode_flags: int = 0  # later-boss +$7B; twin bit1 = grab/throw AI path
    target_unavailable: int = 0  # later-boss +$77 from $179F8
    phase_timer: int = 0  # later-boss +$78 jump/throw timeline counter
    ground_z: int | None = None  # later-boss +$4C ground/landing height
    vel_x: float = 0.0  # +$20 signed 16.16, ROM units per tick
    vel_z: float = 0.0  # +$24 signed 16.16, ROM units per tick
    # Ordinary-enemy velocity (kind=="enemy" only; distinct offsets/fields
    # from the boss vel_x/vel_z above -- see memory_map.py).
    enemy_vel_x: float = 0.0  # +$1C signed 16.16
    enemy_vel_y: float = 0.0  # +$20 signed 16.16 (lane)
    # Player X velocity at +$1C (same offset as ordinary-enemy X). Antonio's
    # kick gate reads this word on the targeted player.
    player_vel_x: float = 0.0
    combat_phase: CombatPhase = CombatPhase.UNKNOWN
    # The object's real body AABB. A player reads its own cached box straight
    # out of the object (+$70, written every frame by $4140) and needs no ROM
    # tables for it; everything else is rebuilt from the ROM shape tables the
    # way $AB24 does (hitboxes.py), and needs RomData to do that. None means
    # "not available this tick" either way -- no RomData for a non-player, or
    # a degenerate cached box for a player mid no-attack frame -- never a
    # guessed rectangle.
    hitbox: Hitbox | None = None
    # Every reach this object has, extracted from its type's animation set
    # (attack_ranges.py). Empty for a player (its reach is the punch geometry
    # in tokens/character.py, not this field), for anything that does not
    # attack, and for bosses, whose animation sets are not labelled.
    attack_ranges: tuple[AttackRange, ...] = ()

    @property
    def is_free_ground_item(self) -> bool:
        """True when the ROM would accept this object as a B-pickup target."""

        if self.kind == "weapon":
            # $3136: type $08-$0C, +$51 == 0, +$50 < 3.
            return self.interaction == 0 and (self.item_param & 0xFF) < 3
        if self.kind == "pickup":
            # Already-linked consumables set +$51 before delete.
            return self.interaction == 0
        return False

    # Back-compat aliases used by HUD/app during the rename.
    @property
    def screen_x(self) -> float:
        return self.map_x

    @property
    def screen_y(self) -> float:
        return self.map_y

    @property
    def action_base(self) -> int:
        """Action family with facing bit cleared (player convention)."""

        return self.action_state & 0xFE

    @property
    def is_holding(self) -> bool:
        # +$4C is a general contact pointer. +$5E can remain pointed at a
        # released weapon projectile after +$60 clears. Reciprocal enemy-link
        # evidence is resolved with the full entity list in grabs.py.
        return self.held_type != 0

    @property
    def is_airborne(self) -> bool:
        """True while in a jump action family.

        Live SoR stores ground elevation around ``+$18`` high-word ``$A0`` for
        standing players, so a ``world_z >= 8`` test is always true and broke
        grounded combat. Normal jumps use ``$10–$17``. ROM input routine
        ``$3010`` starts a held-weapon jump at ``$3C`` and its handlers run
        through ``$42``.
        """

        base = self.action_base
        return 0x10 <= base <= 0x17 or 0x3C <= base <= 0x42

    @property
    def is_grabbing(self) -> bool:
        # +$5E/+$60 also represent a carried weapon. A weapon hold must not be
        # mistaken for an enemy grapple by policy branches using this helper.
        if self.is_holding_weapon:
            return False
        base = self.action_base
        grab_action = (
            0x28 <= base <= 0x3F
            or 0x44 <= base <= 0x4F
            or 0x60 <= base <= 0x6F
        )
        # These action ranges overlap weapon pickup/use states, so an action
        # byte alone is not proof. Live $60 enemy holds retain +$4C contact;
        # other layouts may retain a non-weapon +$60 held type.
        return self.held_type != 0 or (grab_action and self.contact_ptr != 0)

    @property
    def is_holding_weapon(self) -> bool:
        # Weapon object types $08-$0C (knife..pepper); grab targets are enemy types.
        return 0x08 <= (self.held_type & 0xFF) <= 0x0C

    @property
    def is_hurt(self) -> bool:
        """True while voluntary combat input is locked (hurt / throw victim).

        Covers knockdown ``$50–$5F``, ordinary throw air ``$70–$74``, and
        special-throw choreography ``$82–$8F``. Free combat must not run here.
        """

        base = self.action_base
        if 0x50 <= base <= 0x5F:
            return True
        if 0x70 <= base <= 0x74:
            return True
        if 0x82 <= base <= 0x8F:
            return True
        return False

    @property
    def throw_tech_ready(self) -> bool:
        """True when C+Up can arm the bounce-cancel latch (``+$45`` set)."""

        return (
            self.tech_armed != 0
            and self.action_base in mm.ACTION_THROW_AIR_TECHABLE
        )

    @property
    def is_held_by_enemy(self) -> bool:
        """True while the ROM is running the enemy-grab counter sequence."""

        return player_is_held_by_enemy_action(self.action_state)

    @property
    def is_defeated(self) -> bool:
        """Hard enemy lifecycle fact, independent of a stale action family.

        Ordinary-enemy lethal checks are signed: zero health is still alive
        and needs a finishing hit, while $8000-$FFFF has already crossed the
        lethal boundary. The explicit death phase covers boss/death layouts
        whose health word is not useful.
        """

        if self.kind not in ("enemy", "boss"):
            return False
        if self.combat_phase == CombatPhase.DEATH:
            return True
        return self.health is not None and self.health >= 0x8000

    @property
    def phase_tag(self) -> str:
        if self.is_defeated:
            return phase_label(CombatPhase.DEATH)
        return phase_label(self.combat_phase)

    @property
    def targets_player(self) -> int | None:
        """1 or 2 if this combatant is targeting that player seat."""

        return decode_target_seat(self.target_ptr)


@dataclass(frozen=True, slots=True)
class WorldMap:
    """Top-down camera-relative overview of live actors."""

    camera_x: int
    camera_y: int  # ROM camera Y (unused for map Y; kept for completeness)
    # Camera frustum in map space: X is cam-relative, Y is absolute lane.
    camera_left: float
    camera_right: float
    camera_top: float
    camera_bottom: float
    view_left: float
    view_right: float
    view_top: float
    view_bottom: float
    entities: tuple[MapEntity, ...]

    @property
    def view_width(self) -> float:
        return max(1e-6, self.view_right - self.view_left)

    @property
    def view_height(self) -> float:
        return max(1e-6, self.view_bottom - self.view_top)

    @property
    def camera_width(self) -> float:
        return max(1e-6, self.camera_right - self.camera_left)

    @property
    def camera_height(self) -> float:
        return max(1e-6, self.camera_bottom - self.camera_top)

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity.kind] = counts.get(entity.kind, 0) + 1
        return counts

    def threats_targeting(self, player_index: int) -> tuple[MapEntity, ...]:
        """Combatants whose ROM target pointer points at this player seat."""

        return tuple(
            e
            for e in self.entities
            if e.kind in ("enemy", "boss")
            and not e.is_defeated
            and e.targets_player == player_index
        )

    def phase_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.entities:
            if entity.kind not in ("enemy", "boss"):
                continue
            tag = entity.phase_tag
            counts[tag] = counts.get(tag, 0) + 1
        return counts


def _u8(data: bytes, offset: int) -> int:
    return data[offset]


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def fixed16_world_x(data: bytes, offset: int) -> int:
    return _u16(data, offset)


def fixed16_lane_y(data: bytes, offset: int) -> int:
    return _u16(data, offset)


def fixed1616_signed(data: bytes, offset: int) -> float:
    """Signed 16.16 fixed-point long (ROM velocity fields +$20 / +$24)."""

    raw = int.from_bytes(data[offset : offset + 4], "big")
    if raw >= 0x8000_0000:
        raw -= 0x1_0000_0000
    return raw / 65536.0


def project_to_map(
    world_x: int,
    lane_y: int,
    *,
    camera_x: int,
) -> tuple[float, float]:
    """Top-down map projection for visualization.

    - X: camera-relative world X (0 = left edge of the scrolled screen)
    - Y: absolute lane depth (small = back of stage / "up" on the map)

    Elevation is intentionally ignored here.
    """

    return float(world_x - camera_x), float(lane_y)


def project_to_screen(
    world_x: int,
    lane_y: int,
    elev_z: int,
    *,
    camera_x: int,
    camera_y: int,
) -> tuple[float, float]:
    """CRT sprite projection (kept for diagnostics; not used for map plot).

    ROM ``emit_object_sprite_mapping`` without VDP $80 bias:
        x = world_x - cam_x
        y = (lane_y >> 1) + elev_z - cam_y
    """

    return float(world_x - camera_x), float((lane_y >> 1) + elev_z - camera_y)


def _object_geometry(
    slot: bytes,
    rom: RomData | None,
    *,
    style_kind: str,
    type_id: int,
    world_x: int,
    world_y: int,
    world_z: int,
    held_type: int,
) -> tuple[Hitbox | None, tuple[AttackRange, ...]]:
    """The object's body box and its reaches, or empty without enough data.

    Players are the one case that needs no ROM tables at all: ``$4140``
    already wrote their body box into the object at ``+$70`` (six absolute
    words), so it is read directly (``hitboxes.cached_box``) rather than
    rebuilt. Nothing populates ``attack_ranges`` for a player -- the extracted
    ranges are indexed by ordinary-enemy type id and describe an animation
    set a player object does not use; a player's own reach is Axel/Adam/
    Blaze's *punch* geometry in ``tokens/character.py``, not this field.

    Every other kind is reconstructed from the ROM shape tables the way
    ``$AB24`` does, and needs ``rom`` for that: the body box follows the
    object's position and current animation frame every tick, while the
    attack ranges are static per type and only re-derived when the held
    weapon changes what the object can reach.
    """

    if style_kind == "player":
        return cached_box(slot, OBJ_CACHED_BODY_BOX), ()
    if rom is None:
        return None, ()
    _attack, body = object_boxes(
        rom.shapes,
        slot,
        type_id=type_id,
        world_x=world_x,
        lane_y=world_y,
        world_z=world_z,
    )
    ranges = attack_ranges_for_object(
        rom.animations, rom.shapes, type_id=type_id, held_weapon_type=held_type
    )
    return body, ranges


def _entity_from_object(
    slot: bytes,
    *,
    slot_name: str,
    style: EntityStyle,
    type_id: int,
    camera_x: int,
    character_id: int | None = None,
    police_special_active: bool = False,
    rom: RomData | None = None,
) -> MapEntity | None:
    if len(slot) < OBJECT_SLOT_SIZE:
        return None
    world_x = fixed16_world_x(slot, mm.OBJ_POS_X)
    world_y = fixed16_lane_y(slot, mm.OBJ_POS_Y)
    world_z = fixed16_lane_y(slot, mm.OBJ_POS_Z)
    map_x, map_y = project_to_map(world_x, world_y, camera_x=camera_x)
    health: int | None
    if style.kind in ("player", "enemy", "boss"):
        health = _u16(slot, mm.OBJ_HEALTH)
    else:
        health = None

    primary_state = _u16(slot, mm.OBJ_PRIMARY_STATE)
    # Byte at +$30 is the player/boss action/primary index. Do NOT use
    # primary_state & 0xFF (that is +$31) — live hold was $60 read as $00.
    action_state = _u8(slot, mm.OBJ_ACTION_STATE)
    outgoing = _u8(slot, mm.OBJ_OUTGOING_DAMAGE)
    subtype = _u8(slot, mm.OBJ_SUBTYPE)
    script_param = _u8(slot, mm.OBJ_SCRIPT_PARAM)
    # Ordinary enemies: +$09 bit1. Players: action-state +$30 bit0 (set = left).
    facing_left = bool(_u8(slot, mm.OBJ_FACING) & 0x02)

    held_type = 0
    held_ptr = 0
    contact_ptr = 0
    combo = 0
    action_flags = 0
    tech_armed = 0
    tech_latched = 0
    tactical = 0
    pair_role = 0
    target_ptr = 0
    attacker_ptr = 0
    family_state = 0
    item_param = 0
    stun_timer = 0
    interaction = 0
    boss_dist_x = 0
    boss_dist_lane = 0
    mode_flags = 0
    target_unavailable = 0
    phase_timer = 0
    ground_z = None
    vel_x = 0.0
    vel_z = 0.0
    enemy_vel_x = 0.0
    enemy_vel_y = 0.0
    player_vel_x = 0.0
    phase = CombatPhase.UNKNOWN

    if style.kind == "player":
        held_type = _u8(slot, mm.OBJ_HELD_TYPE)
        held_ptr = _u16(slot, mm.OBJ_HELD_PTR)
        contact_ptr = _u16(slot, mm.OBJ_CONTACT_PTR)
        action_flags = _u8(slot, mm.OBJ_ACTION_FLAGS)
        tech_armed = _u8(slot, mm.OBJ_TECH_ARM)
        tech_latched = _u8(slot, mm.OBJ_TECH_LATCH)
        combo = _u8(slot, mm.OBJ_COMBO_STATE)
        facing_left = bool(action_state & 0x01)
        phase = player_phase(action_byte=action_state, held_type=held_type)
        # Same +$1C X-velocity word Antonio's kick gate ($16EAE) reads.
        player_vel_x = fixed1616_signed(slot, mm.OBJ_VEL_X_ORDINARY)
    elif style.kind == "enemy":
        target_ptr = _u16(slot, mm.OBJ_TARGET_PTR)
        attacker_ptr = _u16(slot, mm.OBJ_ATTACKER_PTR)
        family_state = _u8(slot, mm.OBJ_FAMILY_STATE)
        enemy_vel_x = fixed1616_signed(slot, mm.OBJ_VEL_X_ORDINARY)
        enemy_vel_y = fixed1616_signed(slot, mm.OBJ_VEL_LANE_ORDINARY)
        stun_timer = _u8(slot, mm.OBJ_ORDINARY_STUN_TIMER)
        phase = ordinary_enemy_phase(
            primary_state,
            type_id=type_id,
            health=health,
            police_special_active=police_special_active,
        )
    elif style.kind == "boss":
        tactical = _u8(slot, mm.OBJ_BOSS_TACTICAL)
        pair_role = _u8(slot, mm.OBJ_PAIR_ROLE)
        boss_dist_x = _u16(slot, mm.OBJ_BOSS_DIST_X)
        boss_dist_lane = _u16(slot, mm.OBJ_BOSS_DIST_LANE)
        mode_flags = _u8(slot, mm.OBJ_BOSS_MODE_FLAGS)
        target_unavailable = _u8(slot, mm.OBJ_BOSS_TARGET_UNAVAIL)
        phase_timer = _u8(slot, mm.OBJ_BOSS_PHASE_TIMER)
        ground_z = fixed16_lane_y(slot, mm.OBJ_BOSS_GROUND_Z)
        vel_x = fixed1616_signed(slot, mm.OBJ_VEL_X)
        vel_z = fixed1616_signed(slot, mm.OBJ_VEL_Z)
        # Target pointer location differs by boss generation.
        if type_id in (0x30, 0x35):
            target_ptr = _u16(slot, mm.OBJ_BESPOKE_TARGET)
        else:
            target_ptr = _u16(slot, mm.OBJ_LATER_BOSS_TARGET)
        phase = boss_phase(
            type_id=type_id, primary_byte=action_state, tactical=tactical
        )
    elif style.kind in ("weapon", "pickup"):
        item_param = _u8(slot, mm.OBJ_ITEM_PARAM)
        interaction = _u8(slot, mm.OBJ_INTERACTION)
        phase = (
            CombatPhase.NORMAL
            if interaction == 0 and (style.kind != "weapon" or item_param < 3)
            else CombatPhase.SCRIPTED
        )
    elif style.kind == "projectile":
        vel_x = fixed1616_signed(slot, mm.OBJ_VEL_X)
        vel_z = fixed1616_signed(slot, mm.OBJ_VEL_Z)
        phase = CombatPhase.ATTACKING
    elif style.kind == "breakable" and outgoing:
        # Round-8 type-$45 moving props set outgoing damage while in flight.
        # Retain their smashable kind, but expose the active danger phase to
        # symbolic/fuzzy consumers instead of treating them as inert scenery.
        phase = CombatPhase.ATTACKING

    hitbox, ranges = _object_geometry(
        slot,
        rom,
        style_kind=style.kind,
        type_id=type_id,
        world_x=world_x,
        world_y=world_y,
        world_z=world_z,
        held_type=held_type,
    )

    return MapEntity(
        kind=style.kind,
        family=style.family,
        symbol=style.symbol,
        color=style.color,
        label=style.label,
        type_id=type_id,
        world_x=world_x,
        world_y=world_y,
        world_z=world_z,
        map_x=map_x,
        map_y=map_y,
        health=health,
        slot=slot_name,
        action_state=action_state,
        primary_state=primary_state,
        character_id=character_id,
        held_type=held_type,
        hitbox=hitbox,
        attack_ranges=ranges,
        held_ptr=held_ptr,
        contact_ptr=contact_ptr,
        outgoing_damage=outgoing,
        action_flags=action_flags,
        tech_armed=tech_armed,
        tech_latched=tech_latched,
        combo_state=combo,
        tactical=tactical,
        pair_role=pair_role,
        target_ptr=target_ptr,
        attacker_ptr=attacker_ptr,
        family_state=family_state,
        subtype=subtype,
        script_param=script_param,
        item_param=item_param,
        stun_timer=stun_timer,
        interaction=interaction,
        facing_left=facing_left,
        boss_dist_x=boss_dist_x,
        mode_flags=mode_flags,
        target_unavailable=target_unavailable,
        phase_timer=phase_timer,
        ground_z=ground_z,
        vel_x=vel_x,
        vel_z=vel_z,
        enemy_vel_x=enemy_vel_x,
        enemy_vel_y=enemy_vel_y,
        player_vel_x=player_vel_x,
        boss_dist_lane=boss_dist_lane,
        combat_phase=phase,
    )


def _is_hidden(slot: bytes) -> bool:
    """SAT skip flag (bit 0 of +$01).

    Caution: hitstun/invuln **flash** toggles this bit every frame so the sprite
    blinks. That is not the same as a dormant off-screen spawn (which holds the
    bit set until activation). Callers must not treat a single sample of this
    bit as "remove from map" for combatants.
    """

    return bool(_u8(slot, mm.OBJ_FLAGS) & mm.OBJ_FLAG_HIDDEN)


def _is_dormant_combatant(entity: MapEntity, slot: bytes) -> bool:
    """Return whether a combatant has not entered live gameplay yet.

    Ordinary enemies start at primary state ``$0000``.  Their activation entry
    (ROM ``$937A``) sets the SAT-hidden bit while testing eligibility; once the
    check succeeds, ``$B1D6`` advances +$30 to ``$0100`` and the hidden bit is
    cleared.  Active enemies can later toggle the hidden bit while flashing, so
    the state word—not visibility alone—is the stable discriminator, and the
    state word alone is the whole test: the hidden bit is a *symptom* ``$937A``
    sets while checking eligibility, not the definition of dormancy.

    Requiring both used to leave a real gap.  The wave's object slots are
    populated before ``$937A`` runs, so for a frame they hold a full entity
    that is not hidden yet and whose state is still ``$0000``.  Recorded live:
    five enemies appearing for exactly one tick at ``$00``/health 0/zero
    velocity, spaced across the whole level ahead, and the AI threw a punch at
    the nearest of them — 48px away, at nothing — before they vanished again.

    Boss families do not share that state machine.  A boss with neither state
    nor health has no evidence of activation and should likewise stay out of
    observations until its handler initializes it.
    """

    if entity.kind == "enemy":
        return entity.primary_state == 0
    if entity.kind == "boss":
        return entity.primary_state == 0 and not entity.health
    return False


def _near_camera_map(map_x: float, map_y: float, *, lane_max: int) -> bool:
    return (
        -INCLUDE_MARGIN_X <= map_x <= SCREEN_WIDTH + INCLUDE_MARGIN_X
        and -INCLUDE_MARGIN_Y <= map_y <= lane_max + INCLUDE_MARGIN_Y
    )


def _include_entity(entity: MapEntity, slot: bytes, *, lane_max: int) -> bool:
    if entity.kind not in _MAP_KINDS:
        return False
    if not _near_camera_map(entity.map_x, entity.map_y, lane_max=lane_max):
        return False
    # A dormant ordinary enemy is real RAM data but not a live game object yet.
    # Keeping it here creates a phantom target for both the HUD and the agent.
    if _is_dormant_combatant(entity, slot):
        return False
    # Active combatants survive a one-frame SAT flash; other hidden objects do
    # not represent something the player can currently interact with.
    if _is_hidden(slot) and entity.kind not in ("player", "enemy", "boss"):
        return False
    return True


def _enforce_aspect(
    left: float,
    right: float,
    top: float,
    bottom: float,
    *,
    aspect: float,
) -> tuple[float, float, float, float]:
    """Grow the shorter side so (right-left)/(bottom-top) == aspect."""

    width = right - left
    height = bottom - top
    if width / height > aspect:
        target_h = width / aspect
        pad = (target_h - height) / 2.0
        return left, right, top - pad, bottom + pad
    target_w = height * aspect
    pad = (target_w - width) / 2.0
    return left - pad, right + pad, top, bottom


def _framed_view(
    lane_max: int,
    entities: tuple[MapEntity, ...] | list[MapEntity] = (),
) -> tuple[float, float, float, float, float, float, float, float]:
    """Camera = player walk band; view grows to include observed entities.

    Camera rectangle stays 32..288 × 0..lane_max (ROM $43AA X clamp + lane max).
    The wider view can expand for live off-screen actors while preserving the
    same aspect ratio. Dormant, uninitialized enemies are not observations.
    """

    cam_left = CAMERA_WORLD_LEFT
    cam_right = CAMERA_WORLD_RIGHT
    cam_top = 0.0
    cam_bottom = float(lane_max)
    aspect = (cam_right - cam_left) / cam_bottom

    raw_left = cam_left - VIEW_MARGIN_X
    raw_right = cam_right + VIEW_MARGIN_X
    raw_top = cam_top - VIEW_MARGIN_Y
    raw_bottom = cam_bottom + VIEW_MARGIN_Y

    if entities:
        pad_x = 24.0
        pad_y = 12.0
        xs = [e.map_x for e in entities]
        ys = [e.map_y for e in entities]
        raw_left = min(raw_left, min(xs) - pad_x)
        raw_right = max(raw_right, max(xs) + pad_x)
        raw_top = min(raw_top, min(ys) - pad_y)
        raw_bottom = max(raw_bottom, max(ys) + pad_y)

    raw_left, raw_right, raw_top, raw_bottom = _enforce_aspect(
        raw_left, raw_right, raw_top, raw_bottom, aspect=aspect
    )
    return cam_left, cam_right, cam_top, cam_bottom, raw_left, raw_right, raw_top, raw_bottom


def parse_world_map(
    *,
    actors_block: bytes,
    camera_block: bytes,
    p1_character_id: int | None = None,
    p2_character_id: int | None = None,
    p1_mode_active: bool = False,
    p2_mode_active: bool = False,
    level_index: int = 0,
    police_special_active: bool = False,
    rom: RomData | None = None,
) -> WorldMap:
    if len(actors_block) < ACTORS_BYTES:
        raise ValueError(f"actors_block too short ({len(actors_block)} < {ACTORS_BYTES})")
    if len(camera_block) < max(CAM_X_OFF + 2, CAM_Y_OFF + 2):
        raise ValueError("camera_block too short")

    camera_x = _u16(camera_block, CAM_X_OFF)
    camera_y = _u16(camera_block, CAM_Y_OFF)
    lane_max = lane_y_max_for_level(level_index)

    entities: list[MapEntity] = []

    for index, base, char_id in (
        (1, 0x00, p1_character_id),
        (2, 0x80, p2_character_id),
    ):
        slot = actors_block[base : base + OBJECT_SLOT_SIZE]
        type_id = _u8(slot, mm.OBJ_TYPE)
        if type_id != mm.OBJ_TYPE_ACTIVE_PLAYER:
            continue
        object_char = _u8(slot, mm.OBJ_CHARACTER_ID)
        if object_char in (0, 1, 2):
            char_id = object_char
        style = player_style(index, char_id)
        entity = _entity_from_object(
            slot,
            slot_name=f"P{index}",
            style=style,
            type_id=type_id,
            camera_x=camera_x,
            character_id=char_id,
            rom=rom,
        )
        # Players: always keep while type-1; ignore SAT blink/hidden bit.
        if entity is not None:
            entities.append(entity)

    table = actors_block[0x100 : 0x100 + OBJECT_TABLE_BYTES]
    for i in range(OBJECT_SLOT_COUNT):
        off = i * OBJECT_SLOT_SIZE
        slot = table[off : off + OBJECT_SLOT_SIZE]
        type_id = _u8(slot, mm.OBJ_TYPE)
        style = style_for_object(
            type_id,
            action_state=_u8(slot, mm.OBJ_ACTION_STATE),
            subtype=_u8(slot, mm.OBJ_SUBTYPE),
            variant=_u8(slot, mm.OBJ_PRIMARY_STATE + 1),
        )
        if style is None or style.kind == "player":
            continue
        entity = _entity_from_object(
            slot,
            slot_name=f"obj{i:02d}",
            style=style,
            type_id=type_id,
            camera_x=camera_x,
            police_special_active=police_special_active,
            rom=rom,
        )
        if entity is not None and _include_entity(entity, slot, lane_max=lane_max):
            entities.append(entity)

    cam_l, cam_r, cam_t, cam_b, v_l, v_r, v_t, v_b = _framed_view(lane_max, entities)

    return WorldMap(
        camera_x=camera_x,
        camera_y=camera_y,
        camera_left=cam_l,
        camera_right=cam_r,
        camera_top=cam_t,
        camera_bottom=cam_b,
        view_left=v_l,
        view_right=v_r,
        view_top=v_t,
        view_bottom=v_b,
        entities=tuple(entities),
    )


def empty_world_map() -> WorldMap:
    cam_l, cam_r, cam_t, cam_b, v_l, v_r, v_t, v_b = _framed_view(LANE_Y_MAX_DEFAULT, ())
    return WorldMap(
        camera_x=0,
        camera_y=0,
        camera_left=cam_l,
        camera_right=cam_r,
        camera_top=cam_t,
        camera_bottom=cam_b,
        view_left=v_l,
        view_right=v_r,
        view_top=v_t,
        view_bottom=v_b,
        entities=(),
    )
