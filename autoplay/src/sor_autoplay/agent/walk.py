"""Walk-to-(x, y) state: hold D-pad until the goal is reached or passed.

The game needs continuous held directions for walking. Recomputing
left/right every poll from a noisy error sign causes button flicker.
Instead we latch a world-space goal and keep the same direction until:

- both axes are within epsilon (arrived), or
- the player has crossed the goal on an axis (passed through), or
- the goal is cleared (interrupt / new plan).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..world_map import MapEntity
from .controls import Intent


# Arrival band in world/map units (pixels-ish).
DEFAULT_EPS_X = 10.0
DEFAULT_EPS_Y = 8.0
# If still active this many ticks without progress, try a perpendicular re-aim.
# Navigation.NavMemory also tracks stuck independently and can override goals.
STUCK_TICKS = 20
# Ignore tiny goal updates while walking (don't reset latch).
GOAL_UPDATE_SLACK = 14.0


@dataclass
class WalkState:
    """Per-player latched navigation goal in **world** coordinates."""

    active: bool = False
    goal_x: float = 0.0
    goal_y: float = 0.0
    # Locked travel signs (−1 / 0 / +1). Set when the goal is (re)armed.
    dir_x: int = 0
    dir_y: int = 0
    reason: str = ""
    eps_x: float = DEFAULT_EPS_X
    eps_y: float = DEFAULT_EPS_Y
    ticks: int = 0
    # Last position for stuck detection.
    last_x: float = 0.0
    last_y: float = 0.0
    stuck_ticks: int = 0

    def clear(self) -> None:
        self.active = False
        self.dir_x = 0
        self.dir_y = 0
        self.reason = ""
        self.ticks = 0
        self.stuck_ticks = 0

    def set_goal(
        self,
        me: MapEntity,
        goal_x: float,
        goal_y: float,
        *,
        reason: str = "walk",
        eps_x: float = DEFAULT_EPS_X,
        eps_y: float = DEFAULT_EPS_Y,
        force: bool = False,
    ) -> None:
        """Arm or refresh a walk goal from the player's current world pose."""

        gx, gy = float(goal_x), float(goal_y)
        same_neighbourhood = (
            self.active
            and abs(gx - self.goal_x) <= GOAL_UPDATE_SLACK
            and abs(gy - self.goal_y) <= GOAL_UPDATE_SLACK
        )
        if same_neighbourhood and not force:
            # Same neighbourhood — keep latched directions; only refresh label.
            self.reason = reason
            return
        if same_neighbourhood and force:
            # Forced refresh of a committed nav waypoint: update coordinates
            # but **preserve stuck counters**. Resetting stuck every poll was
            # why recovery never fired during hole detours.
            self.goal_x = gx
            self.goal_y = gy
            self.reason = reason
            self.eps_x = eps_x
            self.eps_y = eps_y
            self._reaim(me)
            return

        self.active = True
        self.goal_x = gx
        self.goal_y = gy
        self.reason = reason
        self.eps_x = eps_x
        self.eps_y = eps_y
        self.ticks = 0
        self.stuck_ticks = 0
        self.last_x = float(me.world_x)
        self.last_y = float(me.world_y)
        self._reaim(me)

    def _reaim(self, me: MapEntity, *, prefer_perpendicular: bool = False) -> None:
        err_x = self.goal_x - float(me.world_x)
        err_y = self.goal_y - float(me.world_y)
        dx = 0 if abs(err_x) <= self.eps_x else (1 if err_x > 0 else -1)
        dy = 0 if abs(err_y) <= self.eps_y else (1 if err_y > 0 else -1)
        if prefer_perpendicular and dx != 0 and dy != 0:
            # Stuck while diagonal: try the longer remaining axis alone first.
            if abs(err_y) >= abs(err_x):
                dx = 0
            else:
                dy = 0
        elif prefer_perpendicular and dx != 0 and dy == 0:
            # Stuck on pure X toward an unreachable goal: probe lane change.
            dy = 1 if (int(me.world_x) + int(me.world_y)) % 2 == 0 else -1
            dx = 0
        elif prefer_perpendicular and dy != 0 and dx == 0:
            dx = 1 if err_x >= 0 else -1
            dy = 0
        self.dir_x = dx
        self.dir_y = dy
        if self.dir_x == 0 and self.dir_y == 0:
            # Already on the goal band — treat as finished (not an active walk).
            self.active = False
            self.reason = ""
            self.ticks = 0
            self.stuck_ticks = 0

    def arrived_or_past(self, me: MapEntity) -> bool:
        """True when on the goal band or we have crossed it along travel dir."""

        x = float(me.world_x)
        y = float(me.world_y)
        gx, gy = self.goal_x, self.goal_y

        on_x = abs(gx - x) <= self.eps_x
        on_y = abs(gy - y) <= self.eps_y

        # Passed through: moving right and now at/beyond goal X, etc.
        past_x = False
        if self.dir_x > 0 and x >= gx - self.eps_x:
            past_x = True
        elif self.dir_x < 0 and x <= gx + self.eps_x:
            past_x = True
        elif self.dir_x == 0:
            past_x = on_x

        past_y = False
        if self.dir_y > 0 and y >= gy - self.eps_y:
            past_y = True
        elif self.dir_y < 0 and y <= gy + self.eps_y:
            past_y = True
        elif self.dir_y == 0:
            past_y = on_y

        return past_x and past_y

    def step(self, me: MapEntity) -> Intent | None:
        """Return a held-direction intent, or None if idle/finished."""

        if not self.active:
            return None

        self.ticks += 1
        x = float(me.world_x)
        y = float(me.world_y)

        if self.arrived_or_past(me):
            reason = self.reason
            self.clear()
            return Intent(note=f"walk done ({reason})")

        # Stuck: little movement while buttons held — re-aim once.
        moved = abs(x - self.last_x) + abs(y - self.last_y)
        if moved < 0.5:
            self.stuck_ticks += 1
        else:
            self.stuck_ticks = 0
            self.last_x = x
            self.last_y = y

        if self.stuck_ticks >= STUCK_TICKS:
            # Do not only re-point at the same goal axes — try a perpendicular
            # bias so we leave a wall/pit edge instead of freezing.
            self._reaim(me, prefer_perpendicular=True)
            self.stuck_ticks = 0
            if not self.active:
                return None

        # If we overshot one axis only, zero that latch so we don't reverse-spam.
        if self.dir_x > 0 and x >= self.goal_x - self.eps_x:
            self.dir_x = 0
        elif self.dir_x < 0 and x <= self.goal_x + self.eps_x:
            self.dir_x = 0
        if self.dir_y > 0 and y >= self.goal_y - self.eps_y:
            self.dir_y = 0
        elif self.dir_y < 0 and y <= self.goal_y + self.eps_y:
            self.dir_y = 0

        if self.dir_x == 0 and self.dir_y == 0:
            # Re-aim remaining error or finish.
            self._reaim(me)
            if not self.active:
                return Intent(note=f"walk done ({self.reason})")

        return Intent(
            left=self.dir_x < 0,
            right=self.dir_x > 0,
            up=self.dir_y < 0,
            down=self.dir_y > 0,
            note=f"walk to ({self.goal_x:.0f},{self.goal_y:.0f}) {self.reason}",
        )


def blend_walk_with_actions(
    walk_intent: Intent,
    *,
    attack: bool = False,
    jump: bool = False,
    rear_attack: bool = False,
    special: bool = False,
    note_suffix: str = "",
) -> Intent:
    """Keep latched walk directions and OR face-button actions."""

    note = walk_intent.note
    if note_suffix:
        note = f"{note} + {note_suffix}"
    return Intent(
        left=walk_intent.left,
        right=walk_intent.right,
        up=walk_intent.up,
        down=walk_intent.down,
        attack=attack,
        jump=jump,
        rear_attack=rear_attack,
        special=special,
        note=note,
    )
