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

from .tokens import Myself, Partner
from .tokens import Boss, Enemy, Grunt, Jack, enemy_class_for_type
from .tokens import AnimationInProgress, CameraRange, Stage
from .tokens import Breakable, Pit, Projectile
from .tokens import Weapon, build_pickup_token
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
        action_state=entity.action_state,
        is_airborne=entity.is_airborne,
        action_flags=entity.action_flags,
        tech_armed=entity.tech_armed,
    )


# Phases where the player is free to issue a new input right now, even
# though they aren't idle:
# - HOLDING covers carrying a weapon and grabbing an enemy (B knee / throw).
# - HELD_BY_ENEMY is the enemy-grab counter sequence (C then B) — the player
#   *must* be able to act or the AI freezes until thrown.
_FREE_TO_ACT_PHASES = frozenset(
    {
        CombatPhase.NORMAL,
        CombatPhase.HOLDING,
        CombatPhase.HELD_BY_ENEMY,
    }
)


def _maybe_animation_in_progress(entity: MapEntity) -> AnimationInProgress | None:
    phase = player_phase(action_byte=entity.action_state, held_type=entity.held_type)
    if phase in _FREE_TO_ACT_PHASES:
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
            cls = enemy_class_for_type(entity.type_id)
            extra: dict[str, object] = {}
            if issubclass(cls, Grunt):
                # +$50 is a per-kind alias in RAM; world_map only reads it as
                # a stun timer for kind=="enemy", which is exactly the Grunt
                # family here. Boss keeps its own +$50 (distance to target).
                extra["stun_timer"] = entity.stun_timer
            if cls is Jack:
                extra["has_projectile"] = bool(entity.family_state & 0x01)
            elif issubclass(cls, Boss):
                extra.update(
                    tactical=entity.tactical,
                    pair_role=entity.pair_role,
                    boss_dist_x=entity.boss_dist_x,
                    boss_dist_lane=entity.boss_dist_lane,
                    mode_flags=entity.mode_flags,
                    target_unavailable=entity.target_unavailable,
                    phase_timer=entity.phase_timer,
                    ground_z=entity.ground_z,
                    vel_x=entity.vel_x,
                    vel_z=entity.vel_z,
                )
            context.add(
                cls(
                    slot=entity.slot,
                    type_id=entity.type_id,
                    world_x=entity.world_x,
                    world_y=entity.world_y,
                    health=entity.health,
                    combat_phase=entity.combat_phase,
                    targets_player=entity.targets_player,
                    facing_left=entity.facing_left,
                    grunt_vel_x=entity.enemy_vel_x,
                    grunt_vel_y=entity.enemy_vel_y,
                    hitbox=entity.hitbox,
                    attack_ranges=entity.attack_ranges,
                    **extra,
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
        elif entity.kind == "weapon" and entity.is_free_ground_item:
            context.add(
                Weapon(
                    slot=entity.slot,
                    world_x=entity.world_x,
                    world_y=entity.world_y,
                    weapon_type=entity.type_id,
                    wear=entity.item_param & 0xFF,
                    hitbox=entity.hitbox,
                )
            )
        elif entity.kind == "pickup" and entity.is_free_ground_item:
            token = build_pickup_token(
                slot=entity.slot,
                world_x=entity.world_x,
                world_y=entity.world_y,
                pickup_type=entity.type_id,
            )
            if token is not None:
                context.add(token)
        elif entity.kind == "breakable":
            # Intact props sit in primary state $01; debris/fragments are
            # filtered by style_for_object but keep a soft guard here.
            if entity.combat_phase not in (
                CombatPhase.DEATH,
                CombatPhase.SCRIPTED,
            ):
                context.add(
                    Breakable(
                        slot=entity.slot,
                        world_x=entity.world_x,
                        world_y=entity.world_y,
                        type_id=entity.type_id,
                        hitbox=entity.hitbox,
                    )
                )

    for hole in snapshot.floor_holes:
        context.add(
            Pit(
                world_x=hole.world_x,
                lane_y=hole.lane_y,
                width=hole.width,
                height=hole.height,
            )
        )

    context.add(
        CameraRange(
            # world_map.camera_left/right are the ROM's screen-relative walk
            # clamp (always 32..288 in map_x space, per world_map.py's
            # _framed_view) — NOT a world-absolute rectangle. Every other
            # token here (Enemy/Myself/Weapon/... world_x) is in absolute,
            # ever-growing world-scroll coordinates, so this must be
            # translated by camera_x or every could_*'s _in_camera check
            # silently stops matching anything the moment the level scrolls
            # past map_x 288. Y does not scroll in this game, so top/bottom
            # need no translation.
            left=snapshot.world_map.camera_x + snapshot.world_map.camera_left,
            right=snapshot.world_map.camera_x + snapshot.world_map.camera_right,
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
