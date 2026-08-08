"""Build direct-observation ``Information`` tokens from an already-fetched
``GameSnapshot``.

Per ``AI.md``, this reuses the HUD's own RAM poll/analysis rather than
duplicating it: callers must pass in a ``GameSnapshot`` already produced by
``sor_autoplay.state.read_snapshot`` (or an equivalent fixture in tests).
This module never reads RAM and never calls ``read_snapshot`` itself.
"""

from __future__ import annotations

from sor_autoplay.phases import CombatPhase, player_phase
from sor_autoplay.state import GameSnapshot, PlayerSnapshot
from sor_autoplay.world_map import MapEntity

from .character import Myself, Partner
from .enemy import Enemy
from .essential import AnimationInProgress, CameraRange, Stage
from .hazard_tokens import Projectile
from .tokens import Context


def _stage_direction(level_index: int) -> str:
    if level_index == 6:
        return "none"
    if level_index == 7:
        return "left"
    return "right"


def _find_player_entity(snapshot: GameSnapshot, player_index: int) -> MapEntity | None:
    slot = f"P{player_index}"
    for entity in snapshot.world_map.entities:
        if entity.kind == "player" and entity.slot == slot:
            return entity
    return None


def _build_playable_character(
    cls: type[Myself] | type[Partner],
    *,
    player_snapshot: PlayerSnapshot,
    entity: MapEntity,
) -> Myself | Partner:
    return cls(
        slot=f"P{player_snapshot.index}",
        player_index=player_snapshot.index,
        character_id=player_snapshot.character_id,
        character_name=player_snapshot.character_name,
        world_x=entity.world_x,
        world_y=entity.world_y,
        health=player_snapshot.health if player_snapshot.health is not None else 0,
        health_percent=(
            player_snapshot.health_percent
            if player_snapshot.health_percent is not None
            else 0.0
        ),
        lives=player_snapshot.lives,
        specials=player_snapshot.specials,
        held_weapon_type=entity.held_type,
        facing_left=entity.facing_left,
        combat_phase=entity.combat_phase,
    )


def _maybe_animation_in_progress(entity: MapEntity) -> AnimationInProgress | None:
    phase = player_phase(action_byte=entity.action_state, held_type=entity.held_type)
    if phase == CombatPhase.NORMAL:
        return None
    return AnimationInProgress(slot=entity.slot)


def generate_direct_observation_tokens(
    snapshot: GameSnapshot, *, player_index: int
) -> Context:
    context: Context = set()

    myself_snapshot = snapshot.players[player_index - 1]
    myself_entity = _find_player_entity(snapshot, player_index)
    if myself_entity is not None:
        context.add(
            _build_playable_character(
                Myself, player_snapshot=myself_snapshot, entity=myself_entity
            )
        )
        animation = _maybe_animation_in_progress(myself_entity)
        if animation is not None:
            context.add(animation)

    partner_index = 2 if player_index == 1 else 1
    partner_snapshot = snapshot.players[partner_index - 1]
    if partner_snapshot.is_playable:
        partner_entity = _find_player_entity(snapshot, partner_index)
        if partner_entity is not None:
            context.add(
                _build_playable_character(
                    Partner, player_snapshot=partner_snapshot, entity=partner_entity
                )
            )
            animation = _maybe_animation_in_progress(partner_entity)
            if animation is not None:
                context.add(animation)

    for entity in snapshot.world_map.entities:
        if entity.kind in ("enemy", "boss") and not entity.is_defeated:
            context.add(
                Enemy(
                    slot=entity.slot,
                    type_id=entity.type_id,
                    world_x=entity.world_x,
                    world_y=entity.world_y,
                    health=entity.health,
                    combat_phase=entity.combat_phase,
                    targets_player=entity.targets_player,
                    facing_left=entity.facing_left,
                )
            )
        elif entity.kind == "projectile":
            context.add(
                Projectile(
                    slot=entity.slot,
                    world_x=entity.world_x,
                    world_y=entity.world_y,
                    vel_x=entity.vel_x,
                    vel_z=entity.vel_z,
                )
            )

    context.add(
        CameraRange(
            left=snapshot.world_map.camera_left,
            right=snapshot.world_map.camera_right,
            top=snapshot.world_map.camera_top,
            bottom=snapshot.world_map.camera_bottom,
        )
    )
    context.add(
        Stage(
            level_index=snapshot.level_index,
            direction=_stage_direction(snapshot.level_index),
        )
    )

    return context
