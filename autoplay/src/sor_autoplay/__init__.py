"""Streets of Rage remote observer."""

from sor_ai.state import GameSnapshot, PlayerSnapshot, read_snapshot
from sor_ai.world_map import MapEntity, WorldMap

__all__ = [
    "GameSnapshot",
    "MapEntity",
    "PlayerSnapshot",
    "WorldMap",
    "read_snapshot",
    "__version__",
]

__version__ = "0.4.0"
