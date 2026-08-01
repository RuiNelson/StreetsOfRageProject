"""Object-type → map style (symbol/color/family) for Streets of Rage entities.

Classifications follow ``ai-analysis/enemy-ai.md`` and
``ai-analysis/items-and-weapons.md`` plus ``code-analysis/addresses.csv``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityStyle:
    """How one live object should appear on the 2D map."""

    kind: str  # player | enemy | boss | weapon | breakable | pickup | projectile | other
    family: str
    symbol: str
    color: str  # Tk color string
    label: str


# Player character IDs (object +$50 / globals): 0 Axel, 1 Adam, 2 Blaze.
PLAYER_COLORS = {
    0: "#4da3ff",  # Axel — blue
    1: "#ffd84d",  # Adam — yellow
    2: "#ff5c5c",  # Blaze — red
}
PLAYER_NAMES = {0: "Axel", 1: "Adam", 2: "Blaze"}

# Ordinary-enemy visual families (ROM art-family table at $A4E).
# Internal types still keep distinct colours within a family.
_ENEMY_STYLES: dict[int, EntityStyle] = {
    # Garcia family ($20-$23)
    0x20: EntityStyle("enemy", "Garcia", "G", "#7dffa0", "Garcia"),
    0x21: EntityStyle("enemy", "Garcia", "G", "#3fd97a", "Garcia"),
    0x22: EntityStyle("enemy", "Garcia", "G", "#1fad58", "Garcia"),
    0x23: EntityStyle("enemy", "Garcia", "G", "#b8ff6a", "Garcia (strong)"),
    # Signal
    0x24: EntityStyle("enemy", "Signal", "S", "#ff9a3c", "Signal"),
    # Haku-Ro
    0x25: EntityStyle("enemy", "Haku-Ro", "H", "#c084ff", "Haku-Ro"),
    0x2A: EntityStyle("enemy", "Haku-Ro", "H", "#a855f7", "Haku-Ro"),
    # Nora
    0x26: EntityStyle("enemy", "Nora", "N", "#ff6ec7", "Nora"),
    # Jack
    0x27: EntityStyle("enemy", "Jack", "J", "#d4a574", "Jack"),
    # Jack axe/torch helper (projectile)
    0x28: EntityStyle("projectile", "Jack", "*", "#e8c39e", "Jack projectile"),
    # Police-special sweep controller — not a combatant; omit from map.
}

# Boss families: symbol always "B", colours differ by type.
_BOSS_STYLES: dict[int, EntityStyle] = {
    0x30: EntityStyle("boss", "Abadede", "B", "#ff2d55", "Abadede"),
    0x55: EntityStyle("boss", "Souther", "B", "#ff9500", "Souther"),
    0x56: EntityStyle("boss", "Antonio", "B", "#af52de", "Antonio"),
    0x57: EntityStyle("boss", "Bongo", "B", "#34c759", "Bongo"),
    0x58: EntityStyle("boss", "Onihime/Yasha", "B", "#ff375f", "Onihime/Yasha"),
}

# Carried / ground weapons.
_WEAPON_STYLES: dict[int, EntityStyle] = {
    0x08: EntityStyle("weapon", "Weapon", "k", "#5ac8fa", "Knife"),
    0x09: EntityStyle("weapon", "Weapon", "b", "#64d2ff", "Bottle"),
    0x0A: EntityStyle("weapon", "Weapon", "/", "#32ade6", "Baseball bat"),
    0x0B: EntityStyle("weapon", "Weapon", "|", "#007aff", "Steel pipe"),
    0x0C: EntityStyle("weapon", "Weapon", "p", "#00c7be", "Pepper spray"),
    0x1E: EntityStyle("projectile", "Debris", ".", "#8e8e93", "Bottle shard"),
}

# Breakable props.
_BREAKABLE_STYLES: dict[int, EntityStyle] = {
    0x11: EntityStyle("breakable", "Breakable", "#", "#a1a1aa", "Phone booth"),
    0x19: EntityStyle("breakable", "Breakable", "□", "#71717a", "Crate/prop"),
    # Later rounds do not reuse the early phone-booth/crate dispatchers.  The
    # exact types come from the decoded ELC streams and their collision paths:
    #   R3 $18; R4 $1B/$1C/$1D; R5 $1F; R6 $41; R8 $45.
    # Use descriptive labels rather than retail scenery names that the ROM
    # does not encode.  State-aware debris rejection lives below.
    0x18: EntityStyle("breakable", "Breakable", "□", "#8b7d6b", "Round 3 prop"),
    0x1B: EntityStyle("breakable", "Breakable", "□", "#88786a", "Round 4 prop"),
    0x1C: EntityStyle("breakable", "Breakable", "□", "#927d68", "Round 4 prop"),
    0x1D: EntityStyle("breakable", "Breakable", "□", "#9b8269", "Round 4 prop"),
    0x1F: EntityStyle("breakable", "Breakable", "□", "#867768", "Round 5 prop"),
    0x41: EntityStyle("breakable", "Breakable", "□", "#7c7368", "Round 6 prop"),
    0x45: EntityStyle("breakable", "Breakable", "◆", "#d97706", "Moving prop"),
}

# Type $42 is a separate Round-6 moving collision object.  Its initializer
# writes outgoing damage $14 and its state machine repeatedly moves it on Z;
# unlike the prop families above, it has no player-hit destruction path.
_HAZARD_STYLES: dict[int, EntityStyle] = {
    0x42: EntityStyle("projectile", "Stage hazard", "!", "#ef4444", "Moving hazard"),
}

# Consumable pickups (types with shared effect index at +$50).
# Apple = type $4B (small health, effect index 1); large food = $47.
_PICKUP_STYLES: dict[int, EntityStyle] = {
    0x3F: EntityStyle("pickup", "Score", "$", "#ffd60a", "3000 pts"),
    0x40: EntityStyle("pickup", "Score", "$", "#ff9f0a", "10000 pts"),
    0x47: EntityStyle("pickup", "Health", "+", "#30d158", "Full health"),
    0x4B: EntityStyle("pickup", "Health", "a", "#63e6be", "Apple (small health)"),
    0x4C: EntityStyle("pickup", "Life", "♥", "#ff453a", "Extra life"),
    0x4F: EntityStyle("pickup", "Special", "★", "#bf5af2", "Police special"),
}

# Types we deliberately never draw (UI / effects / controllers).
_SKIP_TYPES = frozenset(
    {
        0x00,  # empty slot
        0x06,  # menu/char-select cursor
        0x0F,  # continue/game-over UI object
        0x29,  # police-special enemy-sweep controller
        0x48,  # wave GO prompt
        0x49,  # contact VFX
        0x4A,  # related short-lived effect (not a collectable)
        0x54,  # multi-slot segmented effect (not a combatant)
    }
)

_ALL_STATIC: dict[int, EntityStyle] = {}
_ALL_STATIC.update(_ENEMY_STYLES)
_ALL_STATIC.update(_BOSS_STYLES)
_ALL_STATIC.update(_WEAPON_STYLES)
_ALL_STATIC.update(_BREAKABLE_STYLES)
_ALL_STATIC.update(_HAZARD_STYLES)
_ALL_STATIC.update(_PICKUP_STYLES)


# Intact breakables have completed their initializer and sit in primary byte
# state $01.  Hits advance the original object to later bounce/timer states;
# types $11/$18/$1D/$41 can additionally spawn fragments with the *same* type.
_INTACT_BREAKABLE_STATE = 0x01
_SUBTYPE_DEBRIS_TYPES = frozenset({0x18, 0x1D, 0x41})


def player_style(player_index: int, character_id: int | None) -> EntityStyle:
    """Style for P1/P2 fixed object slots."""

    name = PLAYER_NAMES.get(character_id if character_id is not None else -1, "Player")
    color = PLAYER_COLORS.get(character_id if character_id is not None else -1, "#e5e5ea")
    symbol = str(player_index)  # "1" / "2"
    return EntityStyle(
        kind="player",
        family="Player",
        symbol=symbol,
        color=color,
        label=f"P{player_index} {name}",
    )


def style_for_type(type_id: int) -> EntityStyle | None:
    """Return a map style for a gameplay object type, or None to skip."""

    type_id &= 0xFF
    if type_id in _SKIP_TYPES:
        return None
    if type_id in _ALL_STATIC:
        return _ALL_STATIC[type_id]
    # Active playable character object type in the fixed player slots.
    if type_id == 0x01:
        return EntityStyle("player", "Player", "P", "#e5e5ea", "Player")
    # Unknown ordinary-enemy / boss ranges still plot; other types stay off the
    # map so ambient/effect objects cannot look like phantom enemies.
    if 0x20 <= type_id <= 0x2A:
        return EntityStyle("enemy", "Unknown", "?", "#9ca3af", f"Enemy ${type_id:02X}")
    if type_id in (0x30, 0x55, 0x56, 0x57, 0x58):
        return EntityStyle("boss", "Boss", "B", "#ff453a", f"Boss ${type_id:02X}")
    return None


def style_for_object(
    type_id: int,
    *,
    action_state: int,
    subtype: int = 0,
    variant: int = 0,
) -> EntityStyle | None:
    """Classify one live object using type plus family-local lifecycle state.

    A type-only catalog is sufficient for enemies and pickups, but not for
    breakables: their broken originals and debris can retain the intact type
    for several visible frames.  Returning ``None`` for those states prevents
    the map and policy from attacking fragments after the prop is gone.

    ``variant`` is object ``+$31`` (the type-$11 fragment selector), while
    ``subtype`` is ``+$0B`` (used by later same-type debris families).
    """

    type_id &= 0xFF
    style = style_for_type(type_id)
    if style is None or style.kind != "breakable":
        return style
    if (action_state & 0xFF) != _INTACT_BREAKABLE_STATE:
        return None
    if type_id == 0x11 and (variant & 0xFF) != 0:
        return None
    if type_id in _SUBTYPE_DEBRIS_TYPES and (subtype & 0xFF) != 0:
        return None
    return style


def is_map_relevant_type(type_id: int) -> bool:
    return style_for_type(type_id) is not None
