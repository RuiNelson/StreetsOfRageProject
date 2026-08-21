"""Build direct-observation ``Information`` tokens from an already-fetched
``GameSnapshot``.

Per ``AI.md``, this reuses the HUD's own RAM poll/analysis rather than
duplicating it: callers must pass in a ``GameSnapshot`` already produced by
``sor_autoplay.state.read_snapshot`` (or an equivalent fixture in tests).
This module never reads RAM and never calls ``read_snapshot`` itself.

``NoraAttackTracker`` is the one exception to ``generate_direct_observation_
tokens`` otherwise being a pure function of its ``GameSnapshot`` argument --
see its own docstring for why ``Nora.ticks_since_last_attack`` needs cross-
tick memory that a single snapshot cannot supply.
"""

from __future__ import annotations

from sor_autoplay.memory_map import ACTION_HOLDING
from sor_autoplay.phases import CombatPhase, is_dangerous, player_phase
from sor_autoplay.state import GameSnapshot, PlayerSnapshot
from sor_autoplay.world_map import MapEntity

from .tokens import Myself, Partner
from .tokens import Boss, Enemy, Grunt, Jack, Nora, enemy_class_for_type
from .tokens import AnimationInProgress, CameraRange, InContinueMenu, InMrXDialog, Stage
from .tokens import Breakable, Pit, Projectile
from .tokens import NORA_TICKS_SINCE_ATTACK_UNKNOWN
from .tokens import Weapon, build_pickup_token
from .tokens import Context


class NoraAttackTracker:
    """Cross-tick memory of how long ago each on-screen Nora last attacked.

    The one deliberate exception to this pipeline's usual statelessness --
    AI.md's process loop rebuilds every token fresh from a single
    ``GameSnapshot`` every tick, and ``execute.py``'s own docstring is
    explicit that there is "no separate, longer-lived state kept between
    ticks beyond the game's own RAM and the virtual gamepad's sticky hold".
    This mirrors that hold's own precedent (``gamepad.py``'s ``steer_x``):
    a single poll is a snapshot, never a transition, and "how long since
    *this* Nora last attacked" is a transition-derived fact no single tick's
    ``combat_phase`` can answer by itself.

    Owned per ``AgentLoop`` instance -- one per AI-controlled player, the
    same granularity every other piece of per-tick state in this codebase
    already uses -- so it never needs to reconcile two players' views of the
    same enemy. :meth:`forget_missing` must be called every tick with the
    slots actually observed as a live Nora this tick, or a slot's stale
    count would otherwise be inherited by whatever enemy the game later
    reuses that slot for.
    """

    def __init__(self) -> None:
        self._ticks: dict[str, int] = {}

    def update(self, slot: str, *, dangerous: bool) -> int:
        """Advance one Nora's counter by a tick and return its new value.

        Reset to 0 while ``dangerous`` (``phases.is_dangerous`` on her
        current ``combat_phase``) -- covering her whole whip engage-and-swing
        state and the lunge's windup and strike alike, so the count starts
        climbing from the moment she actually stops being dangerous, not
        from whichever of those sub-states happened to be sampled.
        """

        ticks = 0 if dangerous else self._ticks.get(slot, 0) + 1
        self._ticks[slot] = ticks
        return ticks

    def forget_missing(self, live_slots: frozenset[str]) -> None:
        """Drop every tracked slot not in ``live_slots``, so a slot the game
        later reuses for a different enemy starts over rather than
        inheriting a stale count."""

        for slot in tuple(self._ticks):
            if slot not in live_slots:
                del self._ticks[slot]


class HoldTracker:
    """Cross-tick memory of how many ticks this actor has held an enemy.

    The second deliberate exception to ``generate_direct_observation_tokens``
    otherwise being a pure function of its ``GameSnapshot`` argument, for the
    same reason ``NoraAttackTracker`` is the first: "how long has *this* hold
    lasted" is a transition-derived fact no single tick's ``action_state`` can
    answer, and there is no ROM-decoded escape/struggle counter on the held
    enemy to read instead (checked: neither ``enemy-ai.md`` nor the later-boss
    grabbee states ``$06``-``$09`` name one).

    Owned per ``AgentLoop`` instance, keyed by the *actor's* own slot
    (``P1``/``P2``) rather than the held enemy's -- a hold is 1:1 with the
    actor holding it, and unlike ``NoraAttackTracker`` there is no risk of the
    game reusing an actor's own player slot for something else, so this needs
    no ``forget_missing`` companion.
    """

    def __init__(self) -> None:
        self._ticks: dict[str, int] = {}

    def update(self, actor_slot: str, *, holding: bool) -> int:
        """Advance one actor's hold counter by a tick and return its new value.

        Reset to 0 the instant ``holding`` goes false -- released, thrown, or
        the enemy escaped -- so a fresh hold always starts its own knee count
        rather than inheriting a stale one.
        """

        ticks = self._ticks.get(actor_slot, 0) + 1 if holding else 0
        self._ticks[actor_slot] = ticks
        return ticks


# The whole hold family ($60-$6F) plus the C crossover ($76/$80), not only the
# two stable holds $60/$66 --
# see PlayableCharacter's own docstring. Counting the animation locks in
# between ($62/$64/$68/$6A/$6C/$6E) is what lets HOLD_KNEE_TICKS describe
# "since this enemy was first grabbed", matching the docstring on
# PlayableCharacter.hold_ticks: a knee and a flip both pass through a lock
# frame, and resetting the counter there would restart the knee budget after
# every single knee.
HOLD_ACTION_BASES = ACTION_HOLDING


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
    hold_ticks: int = 0,
) -> Myself | Partner:
    # The ROM's own hold link, but only while the action byte says a hold is
    # what +$4C describes -- outside the grab/hold families it is a general
    # contact pointer (world_map.MapEntity.contact_slot).
    held_enemy_slot = (
        entity.contact_slot if entity.action_base in ACTION_HOLDING else None
    )
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
        hitbox=entity.hitbox,
        vel_x=entity.player_vel_x,
        hold_ticks=hold_ticks,
        held_enemy_slot=held_enemy_slot,
    )


# Phases where the player is free to issue a new input right now, even
# though they aren't idle:
# - HOLDING covers idle-carrying a weapon and grabbing an enemy (B knee /
#   throw). A held weapon's $44/$46/$48 swing is ATTACKING, not HOLDING —
#   mashing B there cancels the hit boxes (round-1 booth, pipe, action $49).
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
    snapshot: GameSnapshot,
    *,
    player_index: int,
    nora_tracker: NoraAttackTracker | None = None,
    hold_tracker: HoldTracker | None = None,
) -> Context:
    context: Context = set()
    live_nora_slots: set[str] = set()

    myself_snapshot = snapshot.players[player_index - 1]
    if myself_snapshot.is_continue_ui:
        context.add(
            InContinueMenu(
                slot=f"P{player_index}",
                name_entry=myself_snapshot.name_entry_active,
                selects_no=myself_snapshot.continue_selects_no,
                name_slot=myself_snapshot.name_slot,
                name_letter_index=myself_snapshot.name_letter_index,
            )
        )
    if snapshot.mr_x_offer_flag and myself_snapshot.mr_x_choice_active:
        context.add(
            InMrXDialog(
                slot=f"P{player_index}",
                selects_no=myself_snapshot.mr_x_selects_no,
            )
        )
    myself_entity = _find_player_entity(snapshot, player_index)
    if myself_entity is not None:
        myself_slot = f"P{player_index}"
        myself_hold_ticks = (
            hold_tracker.update(
                myself_slot,
                holding=(myself_entity.action_state & 0xFE) in HOLD_ACTION_BASES,
            )
            if hold_tracker is not None
            else 0
        )
        context.add(
            _build_playable_character(
                Myself,
                player_snapshot=myself_snapshot,
                entity=myself_entity,
                hold_ticks=myself_hold_ticks,
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
            partner_slot = f"P{partner_index}"
            partner_hold_ticks = (
                hold_tracker.update(
                    partner_slot,
                    holding=(partner_entity.action_state & 0xFE) in HOLD_ACTION_BASES,
                )
                if hold_tracker is not None
                else 0
            )
            context.add(
                _build_playable_character(
                    Partner,
                    player_snapshot=partner_snapshot,
                    entity=partner_entity,
                    hold_ticks=partner_hold_ticks,
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
            elif cls is Nora:
                live_nora_slots.add(entity.slot)
                extra["ticks_since_last_attack"] = (
                    nora_tracker.update(
                        entity.slot, dangerous=is_dangerous(entity.combat_phase)
                    )
                    if nora_tracker is not None
                    else NORA_TICKS_SINCE_ATTACK_UNKNOWN
                )
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
                    primary_state=entity.action_state,
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
                    held_weapon_type=entity.held_type,
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
                    type_id=entity.type_id,
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

    if nora_tracker is not None:
        nora_tracker.forget_missing(frozenset(live_nora_slots))

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
