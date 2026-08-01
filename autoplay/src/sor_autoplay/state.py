"""Live game-state replica built from remote work-RAM reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from . import memory_map as mm
from .bcd import bcd_nibble_byte, bcd_word, bcd_long_digits, format_score
from .hazards import (
    FloorHole,
    holes_for_level,
    is_paused,
    is_police_special_active,
)
from .world_map import WorldMap, empty_world_map, parse_world_map


class MemorySource(Protocol):
    """Minimal client surface used by the observer."""

    def read_memory(self, address: int, length: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    """One player's resources as the HUD and future agent need them."""

    index: int  # 1 or 2
    mode_active: bool
    object_type: int
    character_id: int | None
    character_name: str
    health: int | None
    health_percent: float | None
    lives: int
    specials: int
    score: int
    score_text: str
    continues: int
    out_flag: int
    is_playable: bool

    def summary_line(self) -> str:
        if not self.mode_active and not self.is_playable:
            return f"P{self.index}: inactive"

        char = self.character_name
        if self.health_percent is None:
            hp = "—"
        else:
            hp = f"{self.health_percent:5.1f}%"
        return (
            f"P{self.index}: {char:<5}  "
            f"HP {hp}  "
            f"Lives {self.lives}  "
            f"Specials {self.specials}  "
            f"Score {self.score_text}"
        )


# States where the round countdown and live player objects are meaningful.
_GAMEPLAY_TIMER_STATES = frozenset({0x14, 0x16})
# States where confirmed/selected characters and campaign resources matter.
_PLAYER_RESOURCE_STATES = frozenset(
    {
        0x14,
        0x16,  # in-game
        0x18,
        0x1A,  # round clear
        0x20,
        0x22,  # character select
        0x28,
        0x2A,  # level intro
    }
)


@dataclass(frozen=True, slots=True)
class GameSnapshot:
    """Compact replica of the SoR campaign/HUD state the observer cares about."""

    connected: bool
    game_state: int
    game_mode: str
    level_index: int
    level_display: int
    wave: int
    player_mode: int
    time_left: int
    time_left_raw: int
    round_timer_bcd: int
    clock_stopped: bool
    timer_valid: bool
    paused: bool = False
    police_special_active: bool = False
    police_special_caller: int | None = None  # 0=P1, 1=P2 while special active
    floor_holes: tuple[FloorHole, ...] = ()
    players: tuple[PlayerSnapshot, PlayerSnapshot] = ()
    world_map: WorldMap = field(default_factory=empty_world_map)
    error: str | None = None
    raw: dict[str, int] = field(default_factory=dict, repr=False)

    @property
    def p1(self) -> PlayerSnapshot:
        return self.players[0]

    @property
    def p2(self) -> PlayerSnapshot:
        return self.players[1]

    def active_players(self) -> list[PlayerSnapshot]:
        return [p for p in self.players if p.mode_active or p.is_playable]


def game_mode_label(game_state: int) -> str:
    return mm.GAME_MODE_LABELS.get(game_state, f"Unknown (0x{game_state:02X})")


def character_name(character_id: int | None) -> str:
    if character_id is None:
        return "—"
    return mm.CHARACTER_NAMES.get(character_id, f"#{character_id}")


def _u8(data: bytes, offset: int) -> int:
    return data[offset]


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def _decode_score(raw_long: int) -> int:
    return bcd_long_digits(raw_long & mm.SCORE_VALUE_MASK, digits=8) % 1_000_000


def _player_from_blocks(
    *,
    index: int,
    globals_block: bytes,
    objects_block: bytes,
    object_base: int,
    player_mode: int,
    mode_bit: int,
    lives_off: int,
    specials_off: int,
    out_off: int,
    char_off: int,
    continues_off: int,
    score_off: int,
) -> PlayerSnapshot:
    mode_active = bool(player_mode & mode_bit)
    obj = objects_block[object_base : object_base + mm.OBJECT_SLOT_SIZE]
    object_type = _u8(obj, mm.OBJ_TYPE)
    is_playable = object_type == mm.OBJ_TYPE_ACTIVE_PLAYER

    # Prefer the live object character while the player is spawned; otherwise
    # fall back to the post-confirm global written by character select.
    object_char = _u8(obj, mm.OBJ_CHARACTER_ID)
    global_char = _u8(globals_block, char_off)
    if is_playable and object_char in mm.CHARACTER_NAMES:
        character_id: int | None = object_char
    elif global_char in mm.CHARACTER_NAMES:
        character_id = global_char
    elif is_playable:
        character_id = object_char
    elif mode_active:
        character_id = global_char
    else:
        character_id = None

    health: int | None
    health_percent: float | None
    if is_playable:
        health = _u16(obj, mm.OBJ_HEALTH)
        if health > mm.MAX_HEALTH:
            # Clamp display if RAM is mid-write or unexpected.
            health = min(health, mm.MAX_HEALTH * 2)
        health_percent = 100.0 * min(health, mm.MAX_HEALTH) / mm.MAX_HEALTH
    else:
        health = None
        health_percent = None

    lives = bcd_nibble_byte(_u8(globals_block, lives_off))
    specials = bcd_nibble_byte(_u8(globals_block, specials_off))
    score = _decode_score(_u32(globals_block, score_off))
    continues = _u16(globals_block, continues_off)
    out_flag = _u8(globals_block, out_off)

    return PlayerSnapshot(
        index=index,
        mode_active=mode_active,
        object_type=object_type,
        character_id=character_id,
        character_name=character_name(character_id),
        health=health,
        health_percent=health_percent,
        lives=lives,
        specials=specials,
        score=score,
        score_text=format_score(score),
        continues=continues,
        out_flag=out_flag,
        is_playable=is_playable,
    )


def snapshot_from_memory_blocks(
    *,
    globals_block: bytes,
    timer_block: bytes,
    objects_block: bytes,
    stop_clock: int = 0,
    camera_block: bytes | None = None,
    actors_block: bytes | None = None,
    pause_text_flag: int = 0,
    police_special_active_byte: int = 0,
    police_special_caller_byte: int = 0,
    collision_map: bytes | None = None,
    blockmap_stride: int = 0,
    connected: bool = True,
    error: str | None = None,
) -> GameSnapshot:
    """Build a snapshot from pre-fetched RAM windows.

    Expected windows (big-endian bus image):
    - ``globals_block``: 0x40 bytes starting at ``$FFFF00``
    - ``timer_block``: at least 3 bytes starting at ``$FFFB00``
    - ``objects_block``: at least 0x100 bytes starting at ``$FFB800`` (P1 then P2)
    - ``camera_block`` (optional): ``$FFE000`` camera structure
    - ``actors_block`` (optional): P1+P2+object table for the 2D map; when
      omitted, ``objects_block`` is used if long enough, else the map is empty
    """

    if len(globals_block) < 0x28:
        raise ValueError("globals_block too short")
    if len(timer_block) < 3:
        raise ValueError("timer_block too short")
    if len(objects_block) < 0x100:
        raise ValueError("objects_block too short")

    game_state = _u16(globals_block, mm.ADDR_GAME_STATE - 0xFFFF00)
    level_index = _u16(globals_block, mm.ADDR_LEVEL - 0xFFFF00)
    wave = _u16(globals_block, mm.ADDR_WAVE - 0xFFFF00)
    player_mode = _u8(globals_block, mm.ADDR_PLAYER_MODE - 0xFFFF00)

    game_timer_raw = _u16(timer_block, 0)
    # Wave starts write $40/$50/$60 as BCD-looking binary values; the clock path
    # treats them as packed-BCD seconds for the on-screen countdown.
    time_left = bcd_word(game_timer_raw)
    round_timer_bcd = bcd_nibble_byte(_u8(timer_block, mm.ADDR_ROUND_TIMER_BCD - mm.ADDR_GAME_TIMER))

    base = 0xFFFF00
    p1 = _player_from_blocks(
        index=1,
        globals_block=globals_block,
        objects_block=objects_block,
        object_base=0,
        player_mode=player_mode,
        mode_bit=mm.PLAYER_MODE_P1,
        lives_off=mm.ADDR_P1_LIVES - base,
        specials_off=mm.ADDR_P1_SPECIALS - base,
        out_off=mm.ADDR_P1_OUT_FLAG - base,
        char_off=mm.ADDR_P1_CHARACTER_ID - base,
        continues_off=mm.ADDR_P1_CONTINUES - base,
        score_off=mm.ADDR_SCORE_P1 - base,
    )
    p2 = _player_from_blocks(
        index=2,
        globals_block=globals_block,
        objects_block=objects_block,
        object_base=mm.OBJECT_SLOT_SIZE,
        player_mode=player_mode,
        mode_bit=mm.PLAYER_MODE_P2,
        lives_off=mm.ADDR_P2_LIVES - base,
        specials_off=mm.ADDR_P2_SPECIALS - base,
        out_off=mm.ADDR_P2_OUT_FLAG - base,
        char_off=mm.ADDR_P2_CHARACTER_ID - base,
        continues_off=mm.ADDR_P2_CONTINUES - base,
        score_off=mm.ADDR_SCORE_P2 - base,
    )

    timer_valid = game_state in _GAMEPLAY_TIMER_STATES
    # Outside campaign resource states, zeroed/stale character IDs look like Axel.
    if game_state not in _PLAYER_RESOURCE_STATES and not p1.is_playable:
        p1 = _blank_player(1, p1)
    if game_state not in _PLAYER_RESOURCE_STATES and not p2.is_playable:
        p2 = _blank_player(2, p2)

    world = empty_world_map()
    map_source = actors_block if actors_block is not None else objects_block
    from .world_map import ACTORS_BYTES

    if camera_block is not None and len(map_source) >= ACTORS_BYTES:
        world = parse_world_map(
            actors_block=map_source[:ACTORS_BYTES],
            camera_block=camera_block,
            p1_character_id=p1.character_id,
            p2_character_id=p2.character_id,
            p1_mode_active=p1.mode_active or p1.is_playable,
            p2_mode_active=p2.mode_active or p2.is_playable,
            level_index=level_index,
        )

    special_on = is_police_special_active(police_special_active_byte)
    holes: tuple[FloorHole, ...] = ()
    if (
        collision_map is not None
        and blockmap_stride > 0
        and camera_block is not None
        and game_state in _GAMEPLAY_TIMER_STATES
    ):
        holes = holes_for_level(
            collision_map,
            stride=blockmap_stride,
            level_index=level_index,
            camera_x=world.camera_x,
        )

    return GameSnapshot(
        connected=connected,
        game_state=game_state,
        game_mode=game_mode_label(game_state),
        level_index=level_index,
        level_display=level_index + 1 if level_index < 0xFE else level_index,
        wave=wave,
        player_mode=player_mode,
        time_left=time_left,
        time_left_raw=game_timer_raw,
        round_timer_bcd=round_timer_bcd,
        clock_stopped=bool(stop_clock),
        timer_valid=timer_valid,
        paused=is_paused(pause_text_flag),
        police_special_active=special_on,
        police_special_caller=(police_special_caller_byte & 0xFF) if special_on else None,
        floor_holes=holes,
        players=(p1, p2),
        world_map=world,
        error=error,
        raw={
            "game_state": game_state,
            "level": level_index,
            "wave": wave,
            "player_mode": player_mode,
            "game_timer": game_timer_raw,
            "round_timer_bcd": _u8(timer_block, 2),
            "p1_lives_raw": _u8(globals_block, mm.ADDR_P1_LIVES - base),
            "p1_specials_raw": _u8(globals_block, mm.ADDR_P1_SPECIALS - base),
            "p2_lives_raw": _u8(globals_block, mm.ADDR_P2_LIVES - base),
            "p2_specials_raw": _u8(globals_block, mm.ADDR_P2_SPECIALS - base),
            "camera_x": world.camera_x,
            "map_entities": len(world.entities),
            "pause_text_flag": pause_text_flag & 0xFF,
            "police_special_active": police_special_active_byte & 0xFF,
            "floor_holes": len(holes),
            "blockmap_stride": blockmap_stride,
        },
    )


def _blank_player(index: int, previous: PlayerSnapshot) -> PlayerSnapshot:
    """Drop stale character/resource fields while keeping mode/object metadata."""

    return PlayerSnapshot(
        index=index,
        mode_active=previous.mode_active,
        object_type=previous.object_type,
        character_id=None,
        character_name="—",
        health=None,
        health_percent=None,
        lives=0,
        specials=0,
        score=0,
        score_text="000000",
        continues=previous.continues,
        out_flag=previous.out_flag,
        is_playable=False,
    )


def read_snapshot(client: MemorySource) -> GameSnapshot:
    """Fetch the RAM windows needed for HUD + 2D map and build a snapshot."""

    from .world_map import ACTORS_BYTES, CAMERA_BYTES

    globals_block = client.read_memory(0xFFFF00, 0x40)
    timer_block = client.read_memory(mm.ADDR_GAME_TIMER, 4)
    actors_block = client.read_memory(mm.ADDR_P1_OBJECT, ACTORS_BYTES)
    camera_block = client.read_memory(mm.ADDR_PRIMARY_CAMERA, CAMERA_BYTES)
    stop_clock = client.read_memory(mm.ADDR_STOP_CLOCK, 1)[0]
    pause_text_flag = client.read_memory(mm.ADDR_PAUSE_TEXT_FLAG, 1)[0]
    police_blob = client.read_memory(mm.ADDR_POLICE_SPECIAL_ACTIVE, 3)
    stride = int.from_bytes(
        client.read_memory(mm.ADDR_PRIMARY_BLOCKMAP_STRIDE, 2), "big"
    )
    # Collision map: stride bytes per lane-row; cover playable lanes + pad.
    # row = lane>>3, so 0xA0 max lane → 0x14 rows; keep a few extra.
    collision_rows = 0x18
    collision_map = (
        client.read_memory(mm.ADDR_LEVEL_COLLISION_CLASS_MAP, stride * collision_rows)
        if stride > 0
        else b""
    )
    return snapshot_from_memory_blocks(
        globals_block=globals_block,
        timer_block=timer_block,
        objects_block=actors_block[:0x100],
        actors_block=actors_block,
        camera_block=camera_block,
        stop_clock=stop_clock,
        pause_text_flag=pause_text_flag,
        police_special_active_byte=police_blob[0],
        police_special_caller_byte=police_blob[2],
        collision_map=collision_map,
        blockmap_stride=stride,
        connected=True,
    )


def disconnected_snapshot(error: str | None = None) -> GameSnapshot:
    empty_player = PlayerSnapshot(
        index=1,
        mode_active=False,
        object_type=0,
        character_id=None,
        character_name="—",
        health=None,
        health_percent=None,
        lives=0,
        specials=0,
        score=0,
        score_text="000000",
        continues=0,
        out_flag=0,
        is_playable=False,
    )
    p2 = PlayerSnapshot(
        index=2,
        mode_active=False,
        object_type=0,
        character_id=None,
        character_name="—",
        health=None,
        health_percent=None,
        lives=0,
        specials=0,
        score=0,
        score_text="000000",
        continues=0,
        out_flag=0,
        is_playable=False,
    )
    return GameSnapshot(
        connected=False,
        game_state=0,
        game_mode="Disconnected",
        level_index=0,
        level_display=0,
        wave=0,
        player_mode=0,
        time_left=0,
        time_left_raw=0,
        round_timer_bcd=0,
        clock_stopped=False,
        timer_valid=False,
        paused=False,
        police_special_active=False,
        police_special_caller=None,
        floor_holes=(),
        players=(empty_player, p2),
        world_map=empty_world_map(),
        error=error,
    )
