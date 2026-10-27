"""``--widescreen`` moves the game's screen-edge tests out by ``$20`` per side.

``SoRWidescreenArena.cpp`` ports the ROM routines that compare an object's
``+$28`` (biased screen X) with a window: the hit window ``$AAA0``/``$ABA4``,
the on-screen tests ``$97CE``/``$97E6``, Abadede's charge ``$14C38`` and
Jack's retreat ``$F4A6``. The models replay those routines, so each sim carries
``widescreen`` and widens exactly those windows with the helpers below. A test
the ROM does inline (``$92AC``, Antonio's, Souther's, the twins' and Bongo's
own band checks) is **not** widened: it stayed a 320 px test there too.
"""

from __future__ import annotations

GROW = 0x20


def lo(edge: int, widescreen: bool) -> int:
    """A window's low edge, ``$20`` further out in widescreen."""

    return edge - GROW if widescreen else edge


def hi(edge: int, widescreen: bool) -> int:
    """A window's high edge, ``$20`` further out in widescreen."""

    return edge + GROW if widescreen else edge


def inside(screen_x: int, window: tuple[int, int], widescreen: bool) -> bool:
    """``window[0] <= screen_x < window[1]``, widened in widescreen."""

    return lo(window[0], widescreen) <= screen_x < hi(window[1], widescreen)
