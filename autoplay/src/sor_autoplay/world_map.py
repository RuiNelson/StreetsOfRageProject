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
    action_state: int = 0  # object +$30 (player action / enemy primary)
    held_type: int = 0  # player +$60; nonzero while holding weapon/grab target
    held_ptr: int = 0  # player +$5E low word
    outgoing_damage: int = 0  # +$34 active hit frame damage nibble
    combo_state: int = 0  # player +$5D

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
        return self.held_type != 0

    @property
    def is_airborne(self) -> bool:
        return self.world_z >= 8

    @property
    def is_grabbing(self) -> bool:
        base = self.action_base
        return self.is_holding and (
            0x28 <= base <= 0x2F or 0x44 <= base <= 0x4F or base == 0x4A
        )

    @property
    def is_holding_weapon(self) -> bool:
        # Weapon object types $08-$0C (knife..pepper); grab targets are enemy types.
        return 0x08 <= (self.held_type & 0xFF) <= 0x0C

    @property
    def is_hurt(self) -> bool:
        base = self.action_base
        return 0x50 <= base <= 0x5F


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
    action_state = _u8(slot, mm.OBJ_ACTION_STATE)
    held_type = _u8(slot, mm.OBJ_HELD_TYPE) if style.kind == "player" else 0
    held_ptr = _u16(slot, mm.OBJ_HELD_PTR) if style.kind == "player" else 0
    outgoing = _u8(slot, mm.OBJ_OUTGOING_DAMAGE)
    combo = _u8(slot, mm.OBJ_COMBO_STATE) if style.kind == "player" else 0
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
        held_type=held_type,
        held_ptr=held_ptr,
        outgoing_damage=outgoing,
        combo_state=combo,
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
