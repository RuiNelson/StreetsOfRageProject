"""Character-specific combat preferences (Axel / Adam / Blaze).

Tuned from the original Streets of Rage move lists (GameFAQs player guide):

| | Adam | Blaze | Axel |
|---|---|---|---|
| Identity | Balanced, best pipe/bat range | Fast, weak combo, strong throws | Slow, strong combo, short rear |
| Jump kick | Good range, use openings | Best range — use confidently | Short range knee |
| Back (B+C) | Best range, start farther | Mid range | Fastest, shortest — only when close |
| Grapple | Prefer throw over knees | Prefer throw; vault→back suplex | Throw / knees if needed |
| Weapons | Great bat/pipe | Weak knife/bottle; OK bat/pipe | Average all |

Punch and back-attack numbers are **measured**, not FAQ-derived. Live
lockstep trace of the player attack box `+$64` (ROM `$450C` compares the
attacker's `+$64` against the victim's `+$70`, so `+$64` is the attack box),
facing right, one B or one B+C edge from grounded idle:

| Char | Punch box X | Start | Active | Rear box X | Start | Active | Dmg |
|---|---|---:|---:|---|---:|---:|---:|
| Axel | +16..+57 | 3 | 10 | −40..−8 | 3 | 10 | 3 |
| Adam | +8..+54 | 3 | 10 | −42..+14 | 21 | 18 | 3 |
| Blaze | +18..+68 | 5 | 10 | −53..−5 | 7 | 16 | 2 |

Both boxes are Y ±8. The punch has an inner edge as well as an outer one: a
body that closes inside it is not hit. See `combat.rear_hit_window`.
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
    # Measured punch attack box `+$64` (facing right, relative to player X).
    punch_inner: float
    punch_outer: float
    punch_startup: int
    # Measured B+C chord: rear box edges behind the player (positive numbers),
    # frames until +$34 arms, damaging frames, damage, frames back to idle.
    rear_range_min: float
    rear_range_max: float
    rear_startup: int
    rear_active: int
    rear_damage: int
    rear_recover: int
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

# Spacing (ROM-backed):
# - Pickup box is playerX−20 .. playerX+20 (SoRInteractions objectInsidePickupBox).
# - Body-overlap grabs happen closer than that (~≤16–18). Standing at 14px invited
#   free enemy punches/grabs.
# - Live lockstep traces of the +$64 attack box on the damaging normal-punch
#   frames: Axel +16..+57, Adam +8..+54, Blaze +18..+68 (Y ±8). Policy strike
#   ranges keep a 4–6px safety margin inside those outer edges.
# - Stand near outer strike range (approach_offset); step in only to connect.
# - Lane hit band ~±12 (hasNearbyObjectInFront Y window).
PROFILES: dict[int, CharacterProfile] = {
    0: CharacterProfile(  # Axel Stone — strong but slow; short fast backfist
        name="Axel",
        strike_range=52.0,
        lane_align=12.0,
        jump_kick_min=28.0,
        jump_kick_max=50.0,  # shortest jump range of the three
        punch_inner=16.0,
        punch_outer=57.0,
        punch_startup=3,
        rear_range_min=8.0,  # box −40..−8 behind
        rear_range_max=40.0,
        rear_startup=3,
        rear_active=10,
        rear_damage=3,
        rear_recover=17,
        jump_attack_bias=0.40,  # use jump-kick in mid window
        rear_attack_bias=0.40,  # fast backfist — use in its band
        combo_bias=0.55,  # strong combo ****
        grab_bias=0.10,  # prefer spaced punches over walk-in grabs
        grab_knees=0,
        prefer_throw=True,
        prefer_vault=False,
        approach_offset=46.0,  # measured first-punch box reaches 57px
        caution_range=48.0,
        preferred_weapons=_ALL_WEAPONS,
        weak_weapons=frozenset(),
    ),
    1: CharacterProfile(  # Adam Hunter — balanced; best back-attack range; pipes/bats
        name="Adam",
        strike_range=50.0,
        lane_align=12.0,
        jump_kick_min=30.0,
        jump_kick_max=72.0,  # good jumpkick range
        punch_inner=8.0,
        punch_outer=54.0,
        punch_startup=3,
        rear_range_min=0.0,  # box −42..+14 straddles him (the hop)
        rear_range_max=42.0,
        rear_startup=21,  # $22 -> $24 hop, lands in $14
        rear_active=18,
        rear_damage=3,
        rear_recover=39,  # $24 ends at 38, lands in $14
        jump_attack_bias=0.45,
        rear_attack_bias=0.12,  # 39-frame commit for 3 damage — last resort
        combo_bias=0.40,
        grab_bias=0.10,
        grab_knees=0,  # FAQ: knees not worth it vs throw
        prefer_throw=True,
        prefer_vault=True,  # vault → back suplex when safe
        approach_offset=44.0,  # measured first-punch box reaches 54px
        caution_range=52.0,
        preferred_weapons=_BAT_PIPE,
        weak_weapons=frozenset(),
    ),
    2: CharacterProfile(  # Blaze Fielding — fast; weak combo; jumpkick + throws shine
        name="Blaze",
        strike_range=62.0,
        lane_align=12.0,
        jump_kick_min=28.0,
        jump_kick_max=78.0,  # FAQ: best jumpkick range
        punch_inner=18.0,
        punch_outer=68.0,
        punch_startup=5,  # one frame slower to arm than the other two
        rear_range_min=5.0,  # box −53..−5 behind: the longest of the three
        rear_range_max=53.0,
        rear_startup=7,
        rear_active=16,
        rear_damage=2,  # weakest chord of the three
        rear_recover=30,
        jump_attack_bias=0.60,  # jump kick is her power tool
        rear_attack_bias=0.28,
        combo_bias=0.18,  # FAQ: worst combo — avoid mashing
        grab_bias=0.15,  # throws strong but spacing still preferred
        grab_knees=0,
        prefer_throw=True,
        prefer_vault=True,
        approach_offset=56.0,  # measured first-punch box reaches 68px
        caution_range=48.0,
        preferred_weapons=_BAT_PIPE,
        weak_weapons=_KNIFE_BOTTLE,  # short range for her
    ),
}

DEFAULT_PROFILE = PROFILES[0]


def profile_for(character_id: int | None) -> CharacterProfile:
    if character_id is None:
        return DEFAULT_PROFILE
    return PROFILES.get(character_id, DEFAULT_PROFILE)
