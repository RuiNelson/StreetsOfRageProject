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


# Tuned for classic SoR feel, not frame-perfect TAS.
PROFILES: dict[int, CharacterProfile] = {
    0: CharacterProfile(  # Axel — solid mid-range punches, Grand Upper (rear), good grabs
        name="Axel",
        strike_range=28.0,
        lane_align=10.0,
        jump_attack_bias=0.12,
        rear_attack_bias=0.22,
        grab_bias=0.30,
        approach_offset=18.0,
        caution_range=40.0,
        grab_knees=3,
    ),
    1: CharacterProfile(  # Adam — longer reach, jump kicks, fewer grabs
        name="Adam",
        strike_range=34.0,
        lane_align=12.0,
        jump_attack_bias=0.30,
        rear_attack_bias=0.10,
        grab_bias=0.18,
        approach_offset=22.0,
        caution_range=44.0,
        grab_knees=2,
    ),
    2: CharacterProfile(  # Blaze — fast, kiting, jump-heavy, quick throws
        name="Blaze",
        strike_range=26.0,
        lane_align=10.0,
        jump_attack_bias=0.24,
        rear_attack_bias=0.16,
        grab_bias=0.28,
        approach_offset=16.0,
        caution_range=48.0,
        grab_knees=2,
    ),
}

DEFAULT_PROFILE = PROFILES[0]


def profile_for(character_id: int | None) -> CharacterProfile:
    if character_id is None:
        return DEFAULT_PROFILE
    return PROFILES.get(character_id, DEFAULT_PROFILE)
