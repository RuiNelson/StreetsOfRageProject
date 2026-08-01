"""Character-specific combat preferences (Axel / Adam / Blaze).

All three share the same button vocabulary under standard controls; differences
are range, aggression, and how often rear/jump attacks are preferred.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    name: str
    # Preferred horizontal engagement distance (world/map units).
    strike_range: float
    # Lane tolerance before we adjust depth to match the target.
    lane_align: float
    # How often (0..1) to mix in jump/rear attacks when already in range.
    jump_attack_bias: float
    rear_attack_bias: float
    # Prefer grab setup (walk-in) vs pure punching on grab-friendly foes.
    grab_bias: float
    # Prefer to keep a small lead so combos connect from the front.
    approach_offset: float
    # When low HP, extra back-off distance from packs.
    caution_range: float
    # Max grab knees before throw (character preference).
    grab_knees: int


# Aggressive defaults: more jump-ins and rear reactions, shorter stand-off.
PROFILES: dict[int, CharacterProfile] = {
    0: CharacterProfile(  # Axel — Grand Upper (rear) + solid jump-ins
        name="Axel",
        strike_range=30.0,
        lane_align=10.0,
        jump_attack_bias=0.38,
        rear_attack_bias=0.35,
        grab_bias=0.22,
        approach_offset=14.0,
        caution_range=36.0,
        grab_knees=2,
    ),
    1: CharacterProfile(  # Adam — long jump kicks
        name="Adam",
        strike_range=36.0,
        lane_align=12.0,
        jump_attack_bias=0.50,
        rear_attack_bias=0.22,
        grab_bias=0.12,
        approach_offset=16.0,
        caution_range=40.0,
        grab_knees=2,
    ),
    2: CharacterProfile(  # Blaze — fast jump-ins and rear escapes
        name="Blaze",
        strike_range=28.0,
        lane_align=10.0,
        jump_attack_bias=0.45,
        rear_attack_bias=0.30,
        grab_bias=0.20,
        approach_offset=12.0,
        caution_range=42.0,
        grab_knees=2,
    ),
}

DEFAULT_PROFILE = PROFILES[0]


def profile_for(character_id: int | None) -> CharacterProfile:
    if character_id is None:
        return DEFAULT_PROFILE
    return PROFILES.get(character_id, DEFAULT_PROFILE)
