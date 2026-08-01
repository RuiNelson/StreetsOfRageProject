"""Character-specific combat preferences (Axel / Adam / Blaze).

Tuned from the original Streets of Rage move lists (GameFAQs player guide):

| | Adam | Blaze | Axel |
|---|---|---|---|
| Identity | Balanced, best pipe/bat range | Fast, weak combo, strong throws | Slow, strong combo, short rear |
| Jump kick | Good range, use openings | Best range — use confidently | Short range knee |
| Back (B+C) | Best range, start farther | Mid range | Fastest, shortest — only when close |
| Grapple | Prefer throw over knees | Prefer throw; vault→back suplex | Throw / knees if needed |
| Weapons | Great bat/pipe | Weak knife/bottle; OK bat/pipe | Average all |
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    name: str
    # Horizontal engagement (world/map units ≈ pixels).
    strike_range: float
    lane_align: float
    # Jump-kick window (C then B / B+C air) — GameFAQs ranges differ by character.
    jump_kick_min: float
    jump_kick_max: float
    # Back attack (B+C) usable distance. Axel short/fast; Adam long/slow.
    rear_range_min: float
    rear_range_max: float
    # Mix biases 0..1 when already in a valid band.
    jump_attack_bias: float
    rear_attack_bias: float
    combo_bias: float  # grounded B mash preference (Blaze low)
    grab_bias: float  # walk-in to start grapple
    # Grapple tree.
    grab_knees: int  # FAQ: prefer throw; keep knees low
    prefer_throw: bool  # B+away over grapple combo
    prefer_vault: bool  # C vault then rear B (suplex) when safe
    # Positioning.
    approach_offset: float
    caution_range: float
    # Weapon pickup preference (type id set). Empty = all weapons OK.
    preferred_weapons: frozenset[int]
    weak_weapons: frozenset[int]  # skip unless nothing else nearby


# Character IDs: 0 Axel, 1 Adam, 2 Blaze (ROM globals).
# Weapon types: knife $08 bottle $09 bat $0A pipe $0B pepper $0C
_BAT_PIPE = frozenset({0x0A, 0x0B})
_ALL_WEAPONS = frozenset({0x08, 0x09, 0x0A, 0x0B, 0x0C})
_KNIFE_BOTTLE = frozenset({0x08, 0x09})

PROFILES: dict[int, CharacterProfile] = {
    0: CharacterProfile(  # Axel Stone — strong but slow; short fast backfist
        name="Axel",
        strike_range=30.0,
        lane_align=10.0,
        jump_kick_min=24.0,
        jump_kick_max=52.0,  # shortest jump range of the three
        rear_range_min=8.0,
        rear_range_max=32.0,  # FAQ: shortest range, only when needed
        jump_attack_bias=0.28,
        rear_attack_bias=0.40,  # fast backfist — use in its band
        combo_bias=0.55,  # strong combo ****
        grab_bias=0.20,
        grab_knees=1,
        prefer_throw=True,
        prefer_vault=False,
        approach_offset=14.0,
        caution_range=36.0,
        preferred_weapons=_ALL_WEAPONS,
        weak_weapons=frozenset(),
    ),
    1: CharacterProfile(  # Adam Hunter — balanced; best back-attack range; pipes/bats
        name="Adam",
        strike_range=36.0,
        lane_align=12.0,
        jump_kick_min=28.0,
        jump_kick_max=78.0,  # good jumpkick range
        rear_range_min=20.0,
        rear_range_max=56.0,  # FAQ: best range, start farther
        jump_attack_bias=0.48,
        rear_attack_bias=0.32,
        combo_bias=0.40,
        grab_bias=0.18,
        grab_knees=0,  # FAQ: knees not worth it vs throw
        prefer_throw=True,
        prefer_vault=True,  # vault → back surplex when safe
        approach_offset=16.0,
        caution_range=40.0,
        preferred_weapons=_BAT_PIPE,
        weak_weapons=frozenset(),
    ),
    2: CharacterProfile(  # Blaze Fielding — fast; weak combo; jumpkick + throws shine
        name="Blaze",
        strike_range=28.0,
        lane_align=10.0,
        jump_kick_min=26.0,
        jump_kick_max=84.0,  # FAQ: best jumpkick range
        rear_range_min=14.0,
        rear_range_max=44.0,
        jump_attack_bias=0.55,  # use with confidence
        rear_attack_bias=0.28,
        combo_bias=0.18,  # FAQ: worst combo — avoid mashing
        grab_bias=0.28,  # throws are her power
        grab_knees=0,
        prefer_throw=True,
        prefer_vault=True,
        approach_offset=12.0,
        caution_range=42.0,
        preferred_weapons=_BAT_PIPE,
        weak_weapons=_KNIFE_BOTTLE,  # short range for her
    ),
}

DEFAULT_PROFILE = PROFILES[0]


def profile_for(character_id: int | None) -> CharacterProfile:
    if character_id is None:
        return DEFAULT_PROFILE
    return PROFILES.get(character_id, DEFAULT_PROFILE)
