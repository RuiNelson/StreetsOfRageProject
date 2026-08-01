"""Stage-specific rules: holes, elevator, reverse scroll, Mr. X dialog."""

from __future__ import annotations

from dataclasses import dataclass

from ..hazards import FloorHole
from ..state import GameSnapshot
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level


# Campaign level indices (0-based).
LEVEL_STAGE4_HOLES = 3  # round 4
LEVEL_STAGE7_ELEVATOR = 6  # round 7
LEVEL_STAGE8_LEFT = 7  # round 8 — reverse scroll / Mr. X


@dataclass(frozen=True, slots=True)
class StageAdvice:
    """Progress direction and geometric constraints for the current level."""

    progress_right: bool  # False on stage 8 (move left)
    avoid_holes: bool
    elevator: bool
    note: str


def stage_advice(level_index: int) -> StageAdvice:
    if level_index == LEVEL_STAGE8_LEFT:
        return StageAdvice(
            progress_right=False,
            avoid_holes=False,
            elevator=False,
            note="stage 8 leftward",
        )
    if level_index == LEVEL_STAGE7_ELEVATOR:
        return StageAdvice(
            progress_right=True,
            avoid_holes=True,  # elevator edges behave like pits
            elevator=True,
            note="stage 7 elevator",
        )
    if level_index == LEVEL_STAGE4_HOLES:
        return StageAdvice(
            progress_right=True,
            avoid_holes=True,
            elevator=False,
            note="stage 4 holes",
        )
    return StageAdvice(
        progress_right=True,
        avoid_holes=level_index in (LEVEL_STAGE4_HOLES, LEVEL_STAGE7_ELEVATOR),
        elevator=False,
        note="default",
    )


def point_in_hole(world_x: float, lane_y: float, holes: tuple[FloorHole, ...], *, margin: float = 6.0) -> FloorHole | None:
    for hole in holes:
        if (
            hole.world_x - margin <= world_x <= hole.world_x_end + margin
            and hole.lane_y - margin <= lane_y <= hole.lane_y_end + margin
        ):
            return hole
    return None


def steer_away_from_holes(
    world_x: float,
    lane_y: float,
    desired_dx: float,
    desired_dy: float,
    holes: tuple[FloorHole, ...],
    *,
    level_index: int,
) -> tuple[float, float]:
    """If the next step would enter a pit, cancel or reverse that axis."""

    if not holes:
        return desired_dx, desired_dy

    step = 12.0
    trial_x = world_x + (step if desired_dx > 0 else -step if desired_dx < 0 else 0.0)
    trial_y = lane_y + (step if desired_dy > 0 else -step if desired_dy < 0 else 0.0)

    # Also clamp lane to playable band (especially elevator top/bottom).
    lane_max = lane_y_max_for_level(level_index)
    if trial_y < LANE_Y_MIN + 4:
        desired_dy = max(0.0, desired_dy)
    if trial_y > lane_max - 4:
        desired_dy = min(0.0, desired_dy)

    if desired_dx != 0 and point_in_hole(trial_x, lane_y, holes, margin=10.0):
        # Prefer vertical detour if the sideways step is a pit.
        if not point_in_hole(world_x, trial_y, holes, margin=10.0):
            desired_dx = 0.0
        else:
            desired_dx = -desired_dx  # reverse
    if desired_dy != 0 and point_in_hole(world_x, trial_y, holes, margin=10.0):
        desired_dy = 0.0

    # If already overlapping a hole AABB, push toward nearest safe edge.
    current = point_in_hole(world_x, lane_y, holes, margin=0.0)
    if current is not None:
        mid_x = (current.world_x + current.world_x_end) / 2.0
        mid_y = (current.lane_y + current.lane_y_end) / 2.0
        desired_dx = -1.0 if world_x >= mid_x else 1.0
        desired_dy = -1.0 if lane_y >= mid_y else 1.0

    return desired_dx, desired_dy


def is_mr_x_offer(snapshot: GameSnapshot) -> bool:
    """True when the final Mr. X dialogue / choice machine is live."""

    raw = snapshot.raw.get("mr_x_offer_flag", 0)
    if raw:
        return True
    # Fallback: stage 8, clock stopped, no combat threats — choice phase.
    if snapshot.level_index != LEVEL_STAGE8_LEFT:
        return False
    if not snapshot.clock_stopped:
        return False
    threats = sum(
        1
        for e in snapshot.world_map.entities
        if e.kind in ("enemy", "boss") and not e.is_defeated
    )
    return threats == 0 and snapshot.timer_valid


def mr_x_choice_intent(
    player: MapEntity | None,
    *,
    choice_bit: int | None,
    choice_active: bool,
) -> str | None:
    """Return 'select_no', 'confirm', or None.

    ``object+$59`` bit 3 = selected side; bit 4 = choice UI active.
    For the initial offer, bit 3 = 1 is refuse ("NO") / continue the fight.
    """

    if not choice_active:
        return None
    if choice_bit is None:
        # No object flag: press right then confirm over a few ticks via state.
        return "select_no"
    if (choice_bit & 0x08) == 0:
        return "select_no"  # need RIGHT to move selection to NO
    return "confirm"
