"""Typed tactical knowledge graph built from one coherent game snapshot."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto

from ..phases import CombatPhase, is_dangerous, is_punishable, should_ignore_as_target
from ..world_map import LANE_Y_MIN, SCREEN_WIDTH, MapEntity, lane_y_max_for_level
from .enemies import JackWeaponPhase, jack_weapon_phase


# Boss sprites/activation points may sit just beyond the 320 px viewport while
# already blocking the player at the scroll boundary (Antonio is observed at
# map X=328).  This is intentionally much smaller than the observer's broad
# discovery margin and never relaxes the playable-lane constraint below.
_BOSS_ACTIVATION_MARGIN_X = 64.0


class Relation(Enum):
    REACHABLE = auto()
    TARGETS_PLAYER = auto()
    DANGEROUS = auto()
    PUNISHABLE = auto()
    BEHIND_PLAYER = auto()
    SAME_LANE = auto()
    NEAR_PLAYER = auto()
    BLOCKS_PROGRESS = auto()
    COLLECTIBLE = auto()
    ARMED = auto()
    THROWING = auto()
    GRABBABLE = auto()
    AIR_ATTACK_ONLY = auto()


@dataclass(frozen=True, slots=True)
class Edge:
    subject: str
    relation: Relation
    object: str | None = None


@dataclass(frozen=True, slots=True)
class TacticalKnowledgeGraph:
    """Entity nodes and symbolic relations used by rules and optimizers."""

    player_slot: str
    nodes: dict[str, MapEntity]
    edges: frozenset[Edge]
    level_index: int

    def has(
        self,
        subject: str,
        relation: Relation,
        object: str | None = None,
    ) -> bool:
        return Edge(subject, relation, object) in self.edges

    def entity_has(self, entity: MapEntity, relation: Relation) -> bool:
        return self.has(entity.slot, relation)

    def entities_with(self, relation: Relation) -> tuple[MapEntity, ...]:
        return tuple(
            entity
            for entity in self.nodes.values()
            if self.entity_has(entity, relation)
        )


def _combatant_alive(entity: MapEntity) -> bool:
    if should_ignore_as_target(entity.combat_phase):
        return False
    if entity.health is None or entity.health < 0x8000:
        return True
    return is_dangerous(entity.combat_phase)


def entity_reachable(entity: MapEntity, *, level_index: int) -> bool:
    """Hard interaction constraint, including the current playable lane.

    Round 1 pre-creates enemies at lane Y=0.  They can carry active-looking AI
    states but cannot be reached until the level trigger moves/materializes
    them.  X-only visibility made the old policy wait on those actors forever.
    """

    right_edge = float(SCREEN_WIDTH)
    if entity.kind == "boss":
        right_edge += _BOSS_ACTIVATION_MARGIN_X
    if not 0.0 <= entity.map_x <= right_edge:
        return False
    lane_max = float(lane_y_max_for_level(level_index))
    if not float(LANE_Y_MIN) <= entity.map_y <= lane_max:
        return False
    if entity.kind in ("enemy", "boss"):
        return _combatant_alive(entity)
    return entity.kind in ("projectile", "pickup", "weapon", "breakable")


def build_tactical_graph(
    player: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    level_index: int,
    player_index: int,
) -> TacticalKnowledgeGraph:
    nodes = {entity.slot: entity for entity in entities}
    edges: set[Edge] = set()
    face_left = bool(player.action_state & 0x01)
    for entity in entities:
        if entity.slot == player.slot:
            continue
        reachable = entity_reachable(entity, level_index=level_index)
        if reachable:
            edges.add(Edge(entity.slot, Relation.REACHABLE))

        dx = entity.map_x - player.map_x
        dy = entity.map_y - player.map_y
        distance = math.hypot(dx, dy)
        if distance <= 160.0:
            edges.add(Edge(entity.slot, Relation.NEAR_PLAYER))
        if abs(dy) <= 12.0:
            edges.add(Edge(entity.slot, Relation.SAME_LANE))
        if (face_left and dx > 8.0) or (not face_left and dx < -8.0):
            edges.add(Edge(entity.slot, Relation.BEHIND_PLAYER))

        if entity.kind in ("enemy", "boss", "projectile"):
            if entity.targets_player == player_index:
                edges.add(
                    Edge(entity.slot, Relation.TARGETS_PLAYER, player.slot)
                )
            if entity.kind == "projectile" or is_dangerous(entity.combat_phase):
                edges.add(Edge(entity.slot, Relation.DANGEROUS))
            if is_punishable(entity.combat_phase):
                edges.add(Edge(entity.slot, Relation.PUNISHABLE))
            if (
                reachable
                and entity.kind in ("enemy", "boss")
                and entity.combat_phase != CombatPhase.GRABBED
                and (entity.kind == "boss" or distance <= 220.0)
            ):
                edges.add(Edge(entity.slot, Relation.BLOCKS_PROGRESS))

            jack_phase = jack_weapon_phase(entity)
            if jack_phase == JackWeaponPhase.ARMED:
                edges.add(Edge(entity.slot, Relation.ARMED))
                edges.add(Edge(entity.slot, Relation.AIR_ATTACK_ONLY))
            elif jack_phase == JackWeaponPhase.THROWING:
                edges.add(Edge(entity.slot, Relation.THROWING))
                edges.add(Edge(entity.slot, Relation.GRABBABLE))
            elif jack_phase == JackWeaponPhase.UNARMED:
                edges.add(Edge(entity.slot, Relation.GRABBABLE))

        if reachable and entity.kind in ("pickup", "weapon"):
            edges.add(Edge(entity.slot, Relation.COLLECTIBLE))

    return TacticalKnowledgeGraph(
        player_slot=player.slot,
        nodes=nodes,
        edges=frozenset(edges),
        level_index=level_index,
    )
