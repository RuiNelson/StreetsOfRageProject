"""Typed tactical knowledge graph built from one coherent game snapshot."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto

from ..phases import CombatPhase, is_dangerous, is_punishable, should_ignore_as_target
from ..world_map import (
    LANE_Y_MIN,
    SCREEN_WIDTH,
    MapEntity,
    is_in_loot_camera,
    lane_y_max_for_level,
)
from .enemies import (
    JackProjectilePhase,
    JackWeaponPhase,
    dangerous_projectile,
    is_enemy_grabbable,
    jack_projectile_phase,
    jack_weapon_phase,
)


# Boss sprites/activation points may sit just beyond the 320 px viewport while
# already blocking the player at the scroll boundary (Antonio is observed at
# map X=328).  This is intentionally much smaller than the observer's broad
# discovery margin and never relaxes the playable-lane constraint below.
_BOSS_ACTIVATION_MARGIN_X = 64.0


class Relation(Enum):
    REACHABLE = auto()
    DEFEATED = auto()
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
    ATTACHED = auto()
    LAUNCHED = auto()


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
    if entity.is_defeated or should_ignore_as_target(entity.combat_phase):
        return False
    return True


def entity_reachable(entity: MapEntity, *, level_index: int) -> bool:
    """Hard interaction constraint, including the current playable lane.

    Round 1 pre-creates enemies at lane Y=0.  They can carry active-looking AI
    states but cannot be reached until the level trigger moves/materializes
    them.  X-only visibility made the old policy wait on those actors forever.

    Free ground loot is tighter than combat: only the walk-band camera ± the
    ROM pickup box (see ``is_in_loot_camera``). Combatants still use the full
    CRT 0..320 band (bosses get a small right margin).
    """

    if entity.kind in ("pickup", "weapon"):
        if not is_in_loot_camera(entity.map_x):
            return False
    else:
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
        defeated = entity.is_defeated
        if defeated:
            edges.add(Edge(entity.slot, Relation.DEFEATED))
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

        if entity.kind in ("enemy", "boss") and defeated:
            # Signed-negative health/death is a hard lifecycle constraint.
            # Do not re-derive danger, punish, blocking, or affordances from a
            # stale family state while the corpse is still allocated.
            continue

        if entity.kind in ("enemy", "boss", "projectile"):
            if entity.targets_player == player_index:
                edges.add(
                    Edge(entity.slot, Relation.TARGETS_PLAYER, player.slot)
                )
            if dangerous_projectile(entity) or (
                entity.kind != "projectile" and is_dangerous(entity.combat_phase)
            ):
                edges.add(Edge(entity.slot, Relation.DANGEROUS))
            jack_helper_phase = jack_projectile_phase(entity)
            if jack_helper_phase == JackProjectilePhase.ATTACHED:
                edges.add(Edge(entity.slot, Relation.ATTACHED))
            elif jack_helper_phase == JackProjectilePhase.LAUNCHED:
                edges.add(Edge(entity.slot, Relation.LAUNCHED))
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
                # Armed Jack is punchable but not grabbable until the throw
                # window (state $0E) or the helper latch clears.
            elif jack_phase == JackWeaponPhase.THROWING:
                edges.add(Edge(entity.slot, Relation.THROWING))
            if (
                entity.kind in ("enemy", "boss")
                and is_enemy_grabbable(entity)
                and entity.combat_phase != CombatPhase.GRABBED
            ):
                edges.add(Edge(entity.slot, Relation.GRABBABLE))

        # ROM $3136 only accepts free ground weapons (+$51==0, +$50<3) and
        # unlinked pickups. Held/thrown/exhausted objects must not be loot goals
        # even when they still appear in the object table on-camera.
        if (
            reachable
            and entity.kind in ("pickup", "weapon")
            and entity.is_free_ground_item
        ):
            edges.add(Edge(entity.slot, Relation.COLLECTIBLE))

    return TacticalKnowledgeGraph(
        player_slot=player.slot,
        nodes=nodes,
        edges=frozenset(edges),
        level_index=level_index,
    )
