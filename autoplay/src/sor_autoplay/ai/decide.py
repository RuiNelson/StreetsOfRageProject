"""``generate_verb_tokens`` and its ``could_*`` candidate generators.

Per ``AI.md``, each ``could_*`` function is concerned only with whether a
verb is possible and sensible — never with relative importance across
verbs, which is ``determine_priority_verb``'s job (``priority.py``).

Reach questions ("can this move hit that enemy from here?") are not answered
here: ``inference.py`` answers them once per tick into ``TargetInReach``
tokens, using the geometry in ``reach.py``, and these generators read those
tokens.
"""

from __future__ import annotations

import math

from ..phases import CombatPhase, is_dangerous
from . import reach
from .tokens import (
    CounterGrab,
    FlipHold,
    GrabEnemy,
    JumpAttack,
    AttackHeldEnemy,
    Punch,
    RearAttack,
    ReleaseGrab,
    OpenBreakable,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
)
from .tokens import (
    MELEE_WEAPON_TYPES,
    Myself,
    PlayableCharacter,
)
from .tokens import Enemy
from .tokens import (
    ActionableTarget,
    GrabOpportunity,
    InGrabReach,
    InJumpAttackReach,
    InPunchReach,
    InRearReach,
    IncomingMelee,
    Surrounded,
)
from .tokens import AnimationInProgress, CameraRange, Stage
from .tokens import Breakable
from .tokens import (
    PLAYER_MAX_HEALTH,
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
    Weapon,
    WeaponUpgrade,
    is_weapon_type,
)
from .tokens import CallPolice
from .tokens import Context, Token, find, find_all
from .tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)

# Police special is scarce (usually 1/life). Only panic-level situations.
POLICE_HEALTH_PERCENT_THRESHOLD = 18.0
# On the last life a KO risks a continue/game-over screen instead of a free
# respawn at full health (player-health-lives-and-combat.md) -- call police
# sooner rather than risk it.
POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE = 35.0
# Being surrounded is the other reason the special exists — it is the only
# move that clears every side at once. Still gated on health, just far less
# strictly than the "about to die" thresholds above: spending it while
# healthy wastes the one panic button of the life.
POLICE_HEALTH_PERCENT_THRESHOLD_SURROUNDED = 60.0

KNIFE_RANGE_X = 90
KNIFE_RANGE_Y = 16
KNIFE_MELEE_X = 40
PEPPER_SPRAY_TYPE = 0x0C

HEALTH_PICKUP_MISSING_MIN = 16
HEALTH_CRITICAL_PERCENT = 40.0

BREAKABLE_PUNCH_X = 36
BREAKABLE_PUNCH_Y = 16
BREAKABLE_BLOCK_X = 28  # treat as path obstacle within this X of the walk line
BREAKABLE_BLOCK_Y = 20


def _is_holding_enemy(actor: PlayableCharacter) -> bool:
    held = actor.held_weapon_type
    return held != 0 and not is_weapon_type(held)


def _actors(context: Context) -> list[PlayableCharacter]:
    """The characters this pipeline may decide *for* -- only ``Myself``.

    Per AI.md, one loop instance runs per AI-controlled player, "each
    producing its own ``Myself``", and ``AgentLoop.tick`` executes the
    surviving verb on *that* player's own ``VirtualGamepad``. A
    ``Partner`` verb reaching ``execute_verb`` would therefore be
    carried out on the wrong pad: it is parametrized with the partner's
    slot, position and facing, so e.g. a ``Punch`` the partner could land
    made ``Myself`` press B (plus the partner's facing direction) at empty
    air, and it outranks ``Myself``'s own walk candidates while doing it.
    ``Partner`` stays in the context as ``Information`` -- for coordination
    and awareness -- but is never an actor here.
    """

    myself = find(context, Myself)
    return [myself] if myself is not None else []


def _blocked(context: Context, actor: PlayableCharacter) -> bool:
    return find(context, AnimationInProgress, slot=actor.slot) is not None


STAB_WEAPON_TYPES = frozenset({0x08, 0x09})  # knife, bottle


def _could_melee_strike(context: Context, *, held_types: frozenset[int] | None, verb_cls) -> Context:
    """Shared body for ``could_punch`` / ``could_swing_bat_or_pipe`` /
    ``could_stab_with_knife_or_bottle`` / ``could_spray_pepper``: they
    issue the identical B-button input (see execute.py's
    ``state_machine_melee_strike``), gated only on which weapon type (if any)
    the actor holds. ``held_types=None`` means unarmed (``Punch``)."""

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        held_matches = (
            actor.held_weapon_type == 0 if held_types is None else actor.held_weapon_type in held_types
        )
        if not held_matches:
            continue
        # InPunchReach already carries the "in front (within tolerance) and
        # inside the band" judgment this used to recompute inline.
        for target_slot in reach.targets_of(context, InPunchReach, actor.slot):
            verbs.add(verb_cls(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def could_punch(context: Context) -> Context:
    return _could_melee_strike(context, held_types=None, verb_cls=Punch)


def could_swing_bat_or_pipe(context: Context) -> Context:
    return _could_melee_strike(context, held_types=MELEE_WEAPON_TYPES, verb_cls=SwingBatOrPipe)


def could_stab_with_knife_or_bottle(context: Context) -> Context:
    return _could_melee_strike(
        context, held_types=STAB_WEAPON_TYPES, verb_cls=StabWithKnifeOrBottle
    )


def could_spray_pepper(context: Context) -> Context:
    return _could_melee_strike(
        context, held_types=frozenset({PEPPER_SPRAY_TYPE}), verb_cls=SprayPepper
    )


def could_rear_attack(context: Context) -> Context:
    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.is_airborne:
            continue
        # InRearReach, NOT ClosingEnemy: an earlier version also fired here
        # purely on that early-warning inference, before the enemy was
        # actually in the chord's real range. Live testing showed that
        # backfires -- $322A only hits based on *current* position, so
        # committing to it early is a guaranteed whiff that locks the actor
        # in the attack's own recovery frames exactly when the still-closing
        # enemy arrives and lands its hit for free. ClosingEnemy remains a
        # real, tested signal (see inference.py) -- it just needs a genuine
        # evasive reaction to consume it usefully, not an early commit to
        # the same reactive-only attack.
        # Produced on band membership alone, per AI.md: a could_* asks only
        # "is this possible and does it make some kind of sense", never "is
        # this the one to take". Whether the chord is the *right* answer --
        # rather than turning around and punching -- is a ranking question,
        # and lives in priority._emergency_rear_attack via
        # reach.rear_attack_is_warranted.
        for target_slot in reach.targets_of(context, InRearReach, actor.slot):
            verbs.add(RearAttack(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def could_counter_grab(context: Context) -> Context:
    verbs: set[Token] = set()
    for actor in _actors(context):
        if actor.combat_phase is not CombatPhase.HELD_BY_ENEMY:
            continue
        if actor.action_base == 0x7E:
            continue
        verbs.add(CounterGrab(actor_slot=actor.slot))
    return verbs


def could_tech_recover(context: Context) -> Context:
    """Fires precisely inside the C+Up bounce-cancel window
    (controls-and-input.md "C+Up landing tech"). Like ``could_counter_grab``,
    this bypasses the generic ``_blocked`` gate on purpose: the actor is
    airborne/hurt (``HURT_PLAYER``) for this whole window and would
    otherwise never be judged free to act."""

    verbs: set[Token] = set()
    for actor in _actors(context):
        if not actor.throw_tech_ready:
            continue
        verbs.add(TechRecover(actor_slot=actor.slot))
    return verbs


def could_grab_enemy(context: Context) -> Context:
    """Walk into an enemy, unarmed and unattacking, to take a hold of it.

    Both halves of the question are already answered in the context:
    ``InGrabReach`` says the walk-in would connect, ``GrabOpportunity`` says
    the hold is worth more than a strike here. This function only adds the
    gates about the *actor*.

    Armed actors are excluded. The ROM's contact test does not care what the
    actor carries, but every held weapon has its own melee move with better
    reach or damage than a bare hold, and closing to contact would spend
    that advantage -- so for the AI, holding a weapon is a reason not to
    grab, exactly as it is a reason not to ``Punch``.
    """

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.held_weapon_type != 0:
            continue
        if actor.is_airborne:
            # $AAA0 aborts the grab code unless the two bodies are within 8px
            # of elevation, so an airborne actor cannot take a hold at all.
            continue
        in_reach = reach.targets_of(context, InGrabReach, actor.slot)
        threatening = reach.targets_of(context, IncomingMelee, actor.slot)
        for target_slot in reach.targets_of(context, GrabOpportunity, actor.slot):
            if target_slot not in in_reach:
                continue
            if target_slot in threatening:
                # Walking into a committed attack is how the actor takes the
                # hit rather than the hold -- same reasoning that keeps
                # could_jump_attack from kicking into one.
                continue
            verbs.add(GrabEnemy(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def could_hold_actions(context: Context) -> Context:
    """While grabbing an enemy: knee, throw-back, flip→suplex, or release.

    Never leave the AI idle in a hold — that was a common failure mode.
    """

    verbs: set[Token] = set()
    enemies = reach.live_enemies(context)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if not _is_holding_enemy(actor):
            continue
        base = actor.action_base
        # Grab-acquire / mid-throw animations: don't spam new edges.
        if base in (0x28, 0x2A, 0x2C, 0x2E, 0x62, 0x64, 0x68, 0x6A, 0x6C, 0x6E):
            continue

        # Target the enemy actually in the grab, not merely the closest one:
        # every hold move's emergency (priority._held_enemy_emergency) is
        # gated on its target being in CombatPhase.GRABBED, so naming a
        # different bystander that happens to be a pixel nearer collapses
        # the whole hold family to emergency 0 and leaves the choice of
        # knee/throw/suplex to the static priority tie-break instead of the
        # rear-threat reasoning below.
        def _distance(enemy: Enemy) -> float:
            return math.hypot(enemy.world_x - actor.world_x, enemy.world_y - actor.world_y)

        grabbed = [e for e in enemies if e.combat_phase is CombatPhase.GRABBED]
        nearest = min(grabbed or enemies, key=_distance, default=None)
        target_slot = nearest.slot if nearest is not None else actor.slot
        rear = reach.rear_threats(actor, enemies)

        if base == 0x66:
            # Confirmed back hold → B is suplex.
            verbs.add(Supplex(actor_slot=actor.slot, target_slot=target_slot))
            continue

        if base == 0x60:
            if rear:
                # Throw the held body into the rear threat (B+back).
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
                # Also offer flip→suplex as alternate (priority decides).
                verbs.add(FlipHold(actor_slot=actor.slot, target_slot=target_slot))
            else:
                # Standard: knee damage, or flip for a suplex finish.
                verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
                verbs.add(FlipHold(actor_slot=actor.slot, target_slot=target_slot))
            continue

        # Unknown hold-ish state with +$60 non-weapon: still act (knee or release).
        verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
        if nearest is not None:
            verbs.add(ReleaseGrab(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


# Backing off is a *concession*, not a reflex. A beat-em-up is won by
# trading hits: every enemy has to be closed on and struck, and closing on a
# live enemy always means standing inside the range it can hit back from.
# Treating "a committed enemy is within caution distance" as a reason to flee
# therefore refuses the only exchange that ever wins the fight -- the AI backs
# off, the enemy follows, and the round goes nowhere. (It was also half of a
# live limit cycle: retreat and approach fighting over the same enemy, see
# could_retreat_from_danger.)
#
# So retreat is gated on the two situations where the exchange genuinely is
# not survivable and space is worth more than damage:
#
# 1. **Hurt** -- below this much health there is no room to trade, and a KO
#    costs a whole life. Shares HEALTH_CRITICAL_PERCENT's reading of "hurt
#    enough to change plans", which _pickup_is_useful already uses.
# 2. **Surrounded** -- 3+ enemies in the close box or a pincer
#    (inference.check_for_surrounded). No amount of facing answers being hit
#    from both sides at once; the only fix is space.
#
# Healthy and one-on-one, the AI walks in and takes the hit it has to take.
RETREAT_HEALTH_PERCENT_THRESHOLD = HEALTH_CRITICAL_PERCENT


def _retreat_is_worth_it(context: Context, actor: PlayableCharacter) -> bool:
    """Whether backing off beats engaging -- see RETREAT_HEALTH_PERCENT_THRESHOLD.

    Also the single owner test for a dangerous, close enemy: when this is
    true ``could_retreat_from_danger`` claims it and
    ``could_walk_to_near_enemy`` stands off; when false the walk claims it and
    retreat produces nothing. Exactly one of the two ever holds a given
    enemy, which is what keeps them from handing it back and forth.
    """

    if actor.health_percent < RETREAT_HEALTH_PERCENT_THRESHOLD:
        return True
    return any(token.actor_slot == actor.slot for token in find_all(context, Surrounded))


def _ahead_in_stage_direction(actor_world_x: int, enemy_world_x: int, direction: str) -> bool:
    if direction == "right":
        return enemy_world_x >= actor_world_x
    if direction == "left":
        return enemy_world_x <= actor_world_x
    return False


def could_walk_to_near_enemy(context: Context) -> Context:
    verbs: set[Token] = set()
    on_screen = reach.on_screen_enemies(context)
    stage = find(context, Stage)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        enemies = on_screen
        if not enemies and stage is not None:
            # Nothing on-screen to chase: fall back to the nearest live
            # enemy ahead in the stage's own scroll direction (e.g. the
            # next wave, tracked on the world map but not yet in camera).
            # Never chase one that's behind -- that's the "off-screen
            # leftover" this verb must not walk backward for. Without
            # this fallback, a live off-screen enemy still correctly holds
            # back could_walk_to_advance_stage, but nothing ever moves the
            # camera to bring it into view, and the AI is stuck producing no
            # verb at all.
            enemies = [
                e
                for e in reach.live_enemies(context)
                if _ahead_in_stage_direction(actor.world_x, e.world_x, stage.direction)
            ]
        if not enemies:
            continue
        actionable = reach.targets_of(context, ActionableTarget, actor.slot)
        if any(enemy.slot in actionable for enemy in enemies):
            continue
        # One candidate per reachable enemy -- determine_priority_verb
        # (priority.py's distance-scored emergency) picks the closest one,
        # per AI.md's own target-selection principle: this function only
        # says what's possible, never which possibility is best.
        # Stand off only when retreat is actually going to claim the enemy
        # (_retreat_is_worth_it -- hurt or surrounded). Otherwise close in:
        # a committed enemy nearby is the *normal* state of a fight, not a
        # reason to stop walking, and the attack verbs outrank this one the
        # moment it is in range.
        #
        # Neither skip tests which *side* the enemy is on, deliberately --
        # see could_retreat_from_danger for the facing-feedback cycle a
        # front-only skip creates.
        threatening = reach.targets_of(context, IncomingMelee, actor.slot)
        standing_off = _retreat_is_worth_it(context, actor)
        for enemy in enemies:
            if reach.any_pit_endangers(context, enemy.world_x, enemy.world_y):
                # Never walk toward a target that is itself standing in a
                # pit's danger zone -- reaching it means standing there too.
                continue
            if standing_off and enemy.slot in threatening:
                # could_retreat_from_danger covers this one instead -- don't
                # propose closing the last stretch of distance into a
                # committed attack that isn't hittable yet.
                continue
            if (
                standing_off
                and is_dangerous(enemy.combat_phase)
                and reach.too_close_to_keep_approaching(
                    actor, enemy, extra_margin=reach.APPROACH_RELEASE_MARGIN
                )
            ):
                # Hysteresis (see reach.APPROACH_RELEASE_MARGIN). Skipping
                # only on the IncomingMelee token above put approach and
                # retreat on one shared boundary: a single retreat step
                # cleared the token, which un-skipped this walk, which walked
                # straight back in and re-armed it -- a one-tick limit cycle
                # against a single enemy, reproduced by driving the pipeline
                # over synthetic ticks. Stay backed off until genuinely clear
                # of the threat, not one pixel past it.
                continue
            verbs.add(WalkToNearEnemy(actor_slot=actor.slot, target_slot=enemy.slot))
    return verbs


def could_retreat_from_danger(context: Context) -> Context:
    """Back off from a committed enemy -- only when the fight is already lost
    on the current terms.

    Gated on ``_retreat_is_worth_it``: hurt, or surrounded. Backing off is
    not the default answer to danger, because there is no way to defeat an
    enemy without standing in its range at some point -- see that function's
    own comment. Healthy and one-on-one, ``could_walk_to_near_enemy`` owns
    the same enemy and walks in instead.

    Deliberately side-agnostic. An earlier version skipped an enemy at the
    actor's back, reasoning that turning to face it beats fleeing it blind,
    and paired that with a front-only skip in ``could_walk_to_near_enemy``
    so the two never competed for one target. Driving the pipeline over
    synthetic ticks showed that pairing is a *facing-feedback limit cycle*,
    and a far more visible one than the shared-threshold cycle
    ``reach.APPROACH_RELEASE_MARGIN`` documents:

    1. a frontal threat produces ``RetreatFromDanger``; the executor holds
       the D-pad away from it;
    2. holding a direction is what sets facing, so the actor is now facing
       *away* -- and ``reach.enemy_behind_actor`` reads facing, so the very
       same enemy re-classifies as "behind" on the next tick;
    3. as "behind" it is skipped here, and picked up by
       ``could_walk_to_near_enemy``'s turn-around instead, which walks back
       toward it and flips facing again;
    4. which makes it "in front" once more, and step 1 repeats.

    The commanded direction therefore reversed *every single tick* for as
    long as one enemy stayed committed nearby -- with the walk verb's lane
    sidestep riding on top, which is what made it read as darting up/down
    as well. The cure is to take facing out of the ownership decision
    entirely: a dangerous, close enemy belongs to this verb from whichever
    side it stands on, and ``could_walk_to_near_enemy``'s matching skips are
    likewise side-agnostic. Backing away from a behind enemy still gains
    distance, and the turn-around happens naturally once the enemy leaves
    its dangerous phase and this verb stops claiming it.
    """

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if not _retreat_is_worth_it(context, actor):
            continue  # healthy and not boxed in -- engage, don't flee
        actionable = reach.targets_of(context, ActionableTarget, actor.slot)
        for target_slot in reach.targets_of(context, IncomingMelee, actor.slot):
            enemy = find(context, Enemy, slot=target_slot)
            if enemy is None:
                continue
            if target_slot in actionable:
                continue  # already hittable -- attack instead of retreating
            verbs.add(RetreatFromDanger(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def _advance_blocking_enemies(context: Context) -> list[Enemy]:
    """Live enemies that should hold back stage advance.

    Almost every live enemy counts, on-screen or not (see
    ``could_walk_to_advance_stage``) -- except an off-screen enemy already
    at exactly 0 health. Per ``world_map.MapEntity.is_defeated``'s own note,
    zero health is not yet ``is_defeated`` -- the ROM still counts it alive
    and wants one more "finishing" hit -- but ``could_walk_to_near_enemy``
    never chases an off-screen target, so nothing in this pipeline will ever
    deliver that hit. Without this carve-out such a straggler blocks stage
    advance forever, which contradicts ``could_walk_to_near_enemy``'s own
    on-screen-only design intent ("so off-screen leftovers don't block
    stage advance forever").
    """

    camera = find(context, CameraRange)
    blocking = []
    for enemy in reach.live_enemies(context):
        if (
            camera is not None
            and not reach.in_camera(camera, enemy.world_x, enemy.world_y)
            and enemy.health == 0
        ):
            continue
        blocking.append(enemy)
    return blocking


def could_walk_to_advance_stage(context: Context) -> Context:
    """Scroll the stage only once every spawned enemy is gone.

    Gated on every live Enemy token, not just on-screen ones: an enemy that
    has already spawned off-screen (about to walk/scroll into view) is still
    a reason to hold position, not a "next wave cue" to push past. The one
    exception is an off-screen enemy already at 0 health -- see
    ``_advance_blocking_enemies``.
    """

    verbs: set[Token] = set()
    stage = find(context, Stage)
    if stage is None or stage.direction == "none":
        return verbs
    if _advance_blocking_enemies(context):
        return verbs
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        verbs.add(WalkToAdvanceStage(actor_slot=actor.slot, direction=stage.direction))
    return verbs


def could_call_police(context: Context) -> Context:
    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.specials <= 0:
            continue
        if not _police_is_worth_it(context, actor):
            continue
        verbs.add(CallPolice(actor_slot=actor.slot))
    return verbs


def _police_is_worth_it(context: Context, actor: PlayableCharacter) -> bool:
    """The two situations the special is for: about to die, or boxed in.

    ``Surrounded`` is the second one -- it is the only move that clears
    every side at once, so a crowd the actor cannot fight its way out of is
    as good a reason as low health, just at a laxer health gate so it is
    never spent while comfortably healthy.
    """

    threshold = (
        POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE
        if actor.lives <= 1
        else POLICE_HEALTH_PERCENT_THRESHOLD
    )
    if actor.health_percent < threshold:
        return True
    surrounded = any(
        token.actor_slot == actor.slot for token in find_all(context, Surrounded)
    )
    return surrounded and actor.health_percent < POLICE_HEALTH_PERCENT_THRESHOLD_SURROUNDED


def could_jump_attack(context: Context) -> Context:
    """Jump-kick only when a horizontal approach is useful — never hop in
    place. Once already airborne, keep producing the same verb every tick
    so the actor actually lands the follow-through B edge instead of
    sailing through the air silent: ``execute.state_machine_jump_attack``
    only presses B while a ``JumpAttack`` is still winning, and
    ``reach.in_jump_attack_band`` is what keeps the target valid through
    the flight (see its docstring) -- there is no other way for the AI to
    remember it already committed to a kick, since a ``Verb`` carries no
    state across ticks."""

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        # Never *launch* into a committed attack: the kick's own travel
        # would deliver the actor to the enemy mid-swing, airborne and
        # unable to change its mind. Once already airborne there is no
        # changing course either way, so this gate only applies pre-launch.
        threatening = reach.targets_of(context, IncomingMelee, actor.slot)
        for target_slot in reach.targets_of(context, InJumpAttackReach, actor.slot):
            if not actor.is_airborne and target_slot in threatening:
                continue
            verbs.add(JumpAttack(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def _could_throw_ranged_weapon(context: Context, *, weapon_type: int, verb_cls) -> Context:
    """Shared body for ``could_throw_knife`` / ``could_throw_pepper``: one
    candidate per on-screen enemy beyond melee but within throw range --
    never just the nearest. determine_priority_verb (priority.py's
    distance-scored emergency) picks which one actually gets thrown at."""

    verbs: set[Token] = set()
    enemies = reach.on_screen_enemies(context)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.held_weapon_type != weapon_type:
            continue
        for enemy in enemies:
            in_melee_range = (
                abs(enemy.world_x - actor.world_x) <= KNIFE_MELEE_X
                and abs(enemy.world_y - actor.world_y) <= KNIFE_RANGE_Y
            )
            if in_melee_range:
                continue
            if (
                abs(enemy.world_x - actor.world_x) <= KNIFE_RANGE_X
                and abs(enemy.world_y - actor.world_y) <= KNIFE_RANGE_Y
            ):
                verbs.add(verb_cls(actor_slot=actor.slot, target_slot=enemy.slot))
    return verbs


def could_throw_knife(context: Context) -> Context:
    return _could_throw_ranged_weapon(context, weapon_type=0x08, verb_cls=ThrowKnife)


def could_throw_pepper(context: Context) -> Context:
    """Mirrors ``could_throw_knife``'s range gating: items-and-weapons.md
    confirms pepper spray is also attack-thrown (``$21E6``, command 3), but
    its own effective throw range has not been separately measured, so this
    reuses ``KNIFE_MELEE_X``/``KNIFE_RANGE_X``/``KNIFE_RANGE_Y`` as the
    closest available evidence."""

    return _could_throw_ranged_weapon(context, weapon_type=PEPPER_SPRAY_TYPE, verb_cls=ThrowPepper)


def could_walk_to_weapon(context: Context) -> Context:
    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        # WeaponUpgrade is the judgment "in camera, still usable, and better
        # than what this actor holds" -- one candidate per upgrade, since
        # priority.py's rank-scaled emergency favours the better one rather
        # than a min/max pick made here.
        for target_slot in reach.targets_of(context, WeaponUpgrade, actor.slot):
            weapon = find(context, Weapon, slot=target_slot)
            if weapon is None:
                continue
            if reach.any_pit_endangers(context, weapon.world_x, weapon.world_y):
                # Never walk toward a target sitting in a pit's danger zone.
                continue
            verbs.add(WalkToWeapon(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def _pickup_is_useful(actor: PlayableCharacter, pickup: Pickup) -> bool:
    if isinstance(pickup, HealthPickup):
        missing = PLAYER_MAX_HEALTH - actor.health
        if missing <= 0:
            return False
        if actor.health_percent < HEALTH_CRITICAL_PERCENT:
            return True
        return missing >= min(HEALTH_PICKUP_MISSING_MIN, pickup.health_delta)
    if isinstance(pickup, LifePickup):
        return True
    if isinstance(pickup, SpecialPickup):
        return actor.specials < 3
    if isinstance(pickup, ScorePickup):
        return True
    return False


def could_walk_to_pickup(context: Context) -> Context:
    verbs: set[Token] = set()
    camera = find(context, CameraRange)
    if camera is None:
        return verbs
    pickups = [
        p
        for p in find_all(context, Pickup)
        if reach.in_camera(camera, p.world_x, p.world_y)
        # Never walk toward a target sitting in a pit's danger zone.
        and not reach.any_pit_endangers(context, p.world_x, p.world_y)
    ]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        useful = [p for p in pickups if _pickup_is_useful(actor, p)]
        # One candidate per useful pickup -- priority.py's per-target
        # _emergency_walk_to_pickup already ranks by type/urgency, so no
        # selection belongs here.
        for pickup in useful:
            verbs.add(WalkToPickup(actor_slot=actor.slot, target_slot=pickup.slot))
    return verbs


def in_smash_range(actor: PlayableCharacter, prop: Breakable) -> bool:
    """Close enough that B hits the prop without moving first.

    Shared with ``priority`` and ``execute``, which both need the same
    answer now that one verb spans the approach and the strike.
    """

    return (
        abs(prop.world_x - actor.world_x) <= BREAKABLE_PUNCH_X
        and abs(prop.world_y - actor.world_y) <= BREAKABLE_PUNCH_Y
    )


def could_open_breakable(context: Context) -> Context:
    """Props worth opening: already in range, or ahead on the stage path.

    One generator for what used to be ``could_smash_breakable`` plus
    ``could_walk_to_breakable``. The distinction between them was never
    about intent -- both meant "open that prop" -- only about whether the
    actor had arrived yet, which is now answered once here (and again, per
    tick, by ``priority``/``execute``) instead of deciding which of two
    verbs may exist.
    """

    verbs: set[Token] = set()
    stage = find(context, Stage)
    camera = find(context, CameraRange)
    breakables = find_all(context, Breakable)
    if camera is not None:
        breakables = [b for b in breakables if reach.in_camera(camera, b.world_x, b.world_y)]
    # Never walk toward a target sitting in a pit's danger zone.
    breakables = [
        b for b in breakables if not reach.any_pit_endangers(context, b.world_x, b.world_y)
    ]
    if not breakables:
        return verbs
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        # Prefer props ahead on the stage path -- but a prop already within
        # reach is worth opening whichever side of the actor it is on, since
        # opening it costs only the B press.
        ahead = breakables
        if stage is not None and stage.direction == "right":
            ahead = [b for b in breakables if b.world_x >= actor.world_x - 8]
        elif stage is not None and stage.direction == "left":
            ahead = [b for b in breakables if b.world_x <= actor.world_x + 8]
        if not ahead:
            ahead = breakables
        candidates = {b.slot: b for b in ahead}
        candidates.update({b.slot: b for b in breakables if in_smash_range(actor, b)})
        # One candidate per reachable breakable -- priority.py's distance-
        # scored emergency picks the closest one.
        for prop in candidates.values():
            verbs.add(OpenBreakable(actor_slot=actor.slot, target_slot=prop.slot))
    return verbs


def generate_verb_tokens(context: Context) -> Context:
    """Returns context | every could_* candidate that applies."""

    return (
        context
        | could_counter_grab(context)
        | could_tech_recover(context)
        | could_hold_actions(context)
        | could_grab_enemy(context)
        | could_walk_to_near_enemy(context)
        | could_retreat_from_danger(context)
        | could_walk_to_advance_stage(context)
        | could_punch(context)
        | could_swing_bat_or_pipe(context)
        | could_stab_with_knife_or_bottle(context)
        | could_spray_pepper(context)
        | could_rear_attack(context)
        | could_call_police(context)
        | could_jump_attack(context)
        | could_throw_knife(context)
        | could_throw_pepper(context)
        | could_walk_to_weapon(context)
        | could_walk_to_pickup(context)
        | could_open_breakable(context)
    )
