"""Tools for observing and eventually automating Streets of Rage."""

from .event_detector import Event, EventDetector, Snapshot, WorkRamSnapshotReader
from .weights import DEFAULT_WEIGHTS, RewardWeights

__all__ = [
    "DEFAULT_WEIGHTS",
    "Event",
    "EventDetector",
    "RewardWeights",
    "Snapshot",
    "WorkRamSnapshotReader",
]
