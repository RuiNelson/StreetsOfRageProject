"""Streets of Rage remote observer and autoplay agents."""

from .state import GameSnapshot, PlayerSnapshot, read_snapshot
from .world_map import MapEntity, WorldMap

__all__ = [
    "GameSnapshot",
    "MapEntity",
    "PlayerSnapshot",
    "WorldMap",
    "read_snapshot",
    "__version__",
]

__version__ = "0.2.0"
