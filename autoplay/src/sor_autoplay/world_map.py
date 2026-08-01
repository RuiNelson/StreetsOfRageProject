"""Extract a 2D world map replica from player slots, object table, and camera.

Visualization is a **top-down stage map** (not CRT sprite projection):

    map_x = world_x - cam_x          # horizontal, camera-relative
    map_y = lane_y                   # depth (+$14); small = back of stage

Elevation ``world_z`` (+$18) is kept on each entity for future agent use but is
**not** applied to the plot. The camera rectangle is 320 × 224 in that space
(MD width × a fixed lane band with the same aspect).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import memory_map as mm
from .object_catalog import EntityStyle, player_style, style_for_type
from .phases import (
    CombatPhase,
    boss_phase,
    decode_target_seat,
    ordinary_enemy_phase,
    phase_label,
    player_phase,
)

# Horizontal span of one Mega Drive screen in world-X units.
SCREEN_WIDTH = 320
# Playable lane Y from clamp_players_to_gameplay_bounds ($43AA):
#   min = $02, max = $70 (most rounds), max = $A0 on level index 6 (round 7).
LANE_Y_MIN = 0x02
LANE_Y_MAX_DEFAULT = 0x70
LANE_Y_MAX_ROUND7 = 0xA0  # level_index == 6
# Default camera height for aspect / empty maps (most rounds).
LANE_BAND_HEIGHT = LANE_Y_MAX_DEFAULT  # 112
MAP_ASPECT = SCREEN_WIDTH / LANE_BAND_HEIGHT  # 320/112 ≈ 2.857

CAMERA_WORLD_WIDTH = float(SCREEN_WIDTH)
CAMERA_WORLD_HEIGHT = float(LANE_BAND_HEIGHT)

VIEW_MARGIN_X = 40.0
VIEW_MARGIN_Y = 16.0
# How far outside the visible screen (in map_x) we still list actors.
# Dormant wave spawns often sit ~one screen ahead; keep two screens of lookahead.
INCLUDE_MARGIN_X = SCREEN_WIDTH * 2
INCLUDE_MARGIN_Y = LANE_BAND_HEIGHT // 2

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
    world_z: int  # elevation at +$18 (stored for agents; not used in plot)
    # Top-down map coordinates (camera-relative X, absolute lane Y).
    map_x: float
    map_y: float
    health: int | None
    slot: str
    # Agent combat fields (defaults keep older call sites valid).
    action_state: int = 0  # low byte of +$30 (player action / boss primary)
    primary_state: int = 0  # full word at +$30 (ordinary enemy $0100 steps)
    held_type: int = 0  # player +$60; nonzero while holding weapon/grab target
    held_ptr: int = 0  # player +$5E low word
    contact_ptr: int = 0  # player +$4C contact/grab partner (live hold uses this)
    outgoing_damage: int = 0  # +$34 active hit frame damage nibble
    action_flags: int = 0  # player +$58; bit5 queues normal-combo continuation
    combo_state: int = 0  # player +$5D
    tactical: int = 0  # boss +$67
    pair_role: int = 0  # later-boss +$5D (1/2) when kind==boss
    target_ptr: int = 0  # ordinary +$42 / boss target low word
    attacker_ptr: int = 0  # ordinary +$3E attacker/holder low word
    facing_left: bool = False  # ordinary +$09 bit1; player action bit0
    boss_dist_x: int = 0  # later-boss +$50 abs X to target
    boss_dist_lane: int = 0  # later-boss +$52 abs lane to target
    combat_phase: CombatPhase = CombatPhase.UNKNOWN

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
        # +$4C is a general contact pointer and can remain nonzero outside a
        # hold.  Treat only the dedicated held fields as standalone evidence;
        # enemy-link evidence is resolved with the full entity list in grabs.py.
        return self.held_type != 0 or self.held_ptr != 0

    @property
    def is_airborne(self) -> bool:
        """True while in a jump action family.

        Live SoR stores ground elevation around ``+$18`` high-word ``$A0`` for
        standing players, so a ``world_z >= 8`` test is always true and broke
        grounded combat. Use action ``$10–$17`` only.
        """

        base = self.action_base
        return 0x10 <= base <= 0x17

    @property
    def is_grabbing(self) -> bool:
        base = self.action_base
        if 0x28 <= base <= 0x2F or 0x44 <= base <= 0x4F or base == 0x4A:
            return True
        # Live hold: Axel stays in $60–$6F while enemy is GRABBED; +$60 often 0.
        if 0x60 <= base <= 0x6F:
            return True
        if 0x30 <= base <= 0x3F:
            return True
        return self.held_type != 0 or self.held_ptr != 0 or self.contact_ptr != 0

    @property
    def is_holding_weapon(self) -> bool:
        # Weapon object types $08-$0C (knife..pepper); grab targets are enemy types.
        return 0x08 <= (self.held_type & 0xFF) <= 0x0C

    @property
    def is_hurt(self) -> bool:
        base = self.action_base
        return 0x50 <= base <= 0x5F

    @property
    def phase_tag(self) -> str:
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
            if e.kind in ("enemy", "boss") and e.targets_player == player_index
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
    """CRT sprite projection (kept for agents / diagnostics; not used for map plot).

    ROM ``emit_object_sprite_mapping`` without VDP $80 bias:
        x = world_x - cam_x
        y = (lane_y >> 1) + elev_z - cam_y
    """

    return float(world_x - camera_x), float((lane_y >> 1) + elev_z - camera_y)


def _entity_from_object(
    slot: bytes,
    *,
    slot_name: str,
    style: EntityStyle,
    type_id: int,
    camera_x: int,
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
    # Ordinary enemies: +$09 bit1. Players: action-state +$30 bit0 (set = left).
    facing_left = bool(_u8(slot, mm.OBJ_FACING) & 0x02)

    held_type = 0
    held_ptr = 0
    contact_ptr = 0
    combo = 0
    action_flags = 0
    tactical = 0
    pair_role = 0
    target_ptr = 0
    attacker_ptr = 0
    boss_dist_x = 0
    boss_dist_lane = 0
    phase = CombatPhase.UNKNOWN

    if style.kind == "player":
        held_type = _u8(slot, mm.OBJ_HELD_TYPE)
        held_ptr = _u16(slot, mm.OBJ_HELD_PTR)
        contact_ptr = _u16(slot, mm.OBJ_CONTACT_PTR)
        action_flags = _u8(slot, mm.OBJ_ACTION_FLAGS)
        combo = _u8(slot, mm.OBJ_COMBO_STATE)
        facing_left = bool(action_state & 0x01)
        phase = player_phase(action_byte=action_state, held_type=held_type)
    elif style.kind == "enemy":
        target_ptr = _u16(slot, mm.OBJ_TARGET_PTR)
        attacker_ptr = _u16(slot, mm.OBJ_ATTACKER_PTR)
        phase = ordinary_enemy_phase(primary_state)
    elif style.kind == "boss":
        tactical = _u8(slot, mm.OBJ_BOSS_TACTICAL)
        pair_role = _u8(slot, mm.OBJ_PAIR_ROLE)
        boss_dist_x = _u16(slot, mm.OBJ_BOSS_DIST_X)
        boss_dist_lane = _u16(slot, mm.OBJ_BOSS_DIST_LANE)
        # Target pointer location differs by boss generation.
        if type_id in (0x30, 0x35):
            target_ptr = _u16(slot, mm.OBJ_BESPOKE_TARGET)
        else:
            target_ptr = _u16(slot, mm.OBJ_LATER_BOSS_TARGET)
        phase = boss_phase(
            type_id=type_id, primary_byte=action_state, tactical=tactical
        )
    elif style.kind == "projectile":
        phase = CombatPhase.ATTACKING

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
        held_type=held_type,
        held_ptr=held_ptr,
        contact_ptr=contact_ptr,
        outgoing_damage=outgoing,
        action_flags=action_flags,
        combo_state=combo,
        tactical=tactical,
        pair_role=pair_role,
        target_ptr=target_ptr,
        attacker_ptr=attacker_ptr,
        facing_left=facing_left,
        boss_dist_x=boss_dist_x,
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
    if entity.kind in ("enemy", "boss") and entity.health is not None and entity.health == 0:
        return False

    # Hitstun flash toggles flags bit0; combatants must still plot.
    # Dormant off-screen spawns also hold bit0 — they are kept on the map too.
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
    """Camera = visible playfield; view grows to include dormant spawns etc.

    Camera rectangle stays 0..320 × 0..lane_max (what the player sees).
    The wider view expands so off-screen waiting enemies remain visible outside
    that rectangle while preserving the same aspect ratio.
    """

    cam_left = 0.0
    cam_right = CAMERA_WORLD_WIDTH
    cam_top = 0.0
    cam_bottom = float(lane_max)
    aspect = cam_right / cam_bottom

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
        )
        # Players: always keep while type-1; ignore SAT blink/hidden bit.
        if entity is not None:
            entities.append(entity)

    table = actors_block[0x100 : 0x100 + OBJECT_TABLE_BYTES]
    for i in range(OBJECT_SLOT_COUNT):
        off = i * OBJECT_SLOT_SIZE
        slot = table[off : off + OBJECT_SLOT_SIZE]
        type_id = _u8(slot, mm.OBJ_TYPE)
        style = style_for_type(type_id)
        if style is None or style.kind == "player":
            continue
        entity = _entity_from_object(
            slot,
            slot_name=f"obj{i:02d}",
            style=style,
            type_id=type_id,
            camera_x=camera_x,
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
