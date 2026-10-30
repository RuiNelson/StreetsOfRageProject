"""Packed-BCD helpers for Streets of Rage work-RAM values."""

from __future__ import annotations


def bcd_nibble_byte(value: int) -> int:
    """Decode one packed-BCD byte (two digits) to decimal.

    Values that are not valid BCD still return a best-effort digit sum so the
    HUD never crashes on transient garbage during mode transitions.
    """

    value &= 0xFF
    high = (value >> 4) & 0x0F
    low = value & 0x0F
    if high > 9 or low > 9:
        # Fall back to raw binary interpretation for invalid BCD.
        return value
    return high * 10 + low


def bcd_word(value: int) -> int:
    """Decode a 16-bit packed-BCD word (up to four digits)."""

    value &= 0xFFFF
    return bcd_nibble_byte(value >> 8) * 100 + bcd_nibble_byte(value)


def bcd_long_digits(value: int, *, digits: int = 6) -> int:
    """Decode a big-endian packed-BCD integer kept in a 32-bit word.

    Streets of Rage scores are six display digits stored as packed BCD in a
    longword (for example ``0x00050000`` == 50_000). High dirty/flag bits should
    be masked by the caller before decoding when known.
    """

    if digits < 1 or digits > 8:
        raise ValueError("digits must be in 1..8")
    value &= (1 << (digits * 4)) - 1
    total = 0
    place = 1
    for _ in range(digits):
        nibble = value & 0x0F
        if nibble > 9:
            nibble = 0
        total += nibble * place
        place *= 10
        value >>= 4
    return total


def format_score(value: int, *, digits: int = 6) -> str:
    """Format a decoded score with fixed width and leading zeros."""

    return f"{value:0{digits}d}"
