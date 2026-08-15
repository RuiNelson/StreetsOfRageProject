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

from .. import prop_solids
from ..phases import CombatPhase, is_dangerous, is_punishable
from . import kinematics, reach
from .tokens import (
    CounterGrab,
    FlipHold,
    GrabEnemy,
    HitAntonioBoomerang,
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
    punch_usable_inner_x,
)
from .tokens import Antonio, Enemy, Jack
from .tokens import (
    ActionableTarget,
    AntonioIsGoingToKick,
    GrabOpportunity,
    GrabJackFromBehind,
    InGrabReach,
    InJumpAttackReach,
    InPunchReach,
    InRearReach,
    IncomingMelee,
    IncomingProjectile,
    Surrounded,
)
from .tokens import AnimationInProgress, CameraRange, Stage
from .tokens import Breakable, Projectile
from .tokens import PUNCH_RANGE_Y, punch_outer_x
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
from .tokens import HandleContinueMenu, HandleMrXDialog, InContinueMenu, InMrXDialog
from .tokens import Context, Token, find, find_all
from .tokens import (
    DodgeAntonioKick,
    ProjectileSidestep,
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
# Extra room past a prop's own wall (prop_solids) before a strike is judged
# in range, for the props whose wall out-reaches BREAKABLE_PUNCH_X. Must
# clear both the path finder's lattice step (NAV_STEP, 4) and the executor's
# walk deadband (MOVE_DEADBAND_X, 5), which are the two reasons the actor
# comes to rest short of the exact position it aimed at. See
# ``breakable_smash_outer_x``.
SMASH_WALL_CLEARANCE_X = 8
# How far past a prop the actor can step and still treat it as "ahead" on
# the stage path. Without this slack, one pixel past the origin dropped
# OpenBreakable and handed the tick to WalkToAdvanceStage, which walked
# straight back into the crate -- the two verbs flipping every few ticks.
BREAKABLE_AHEAD_SLACK = 8


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
    the actor holds. ``held_types=None`` means unarmed (``Punch``).

    Refuses a Jack currently juggling his axe/torch (``Jack.has_projectile``)
    for all four -- while he is spinning the weapon, closing in with a punch
    or an armed swing trades hits with it instead of connecting cleanly.
    ``could_jump_attack``'s kick and ``could_rear_attack``'s from-behind chord
    are untouched: both answer him from outside the swing (the kick arrives
    from above, the chord from a side he isn't juggling toward), so they stay
    the only safe finishers on him until he lets the weapon go.
    """

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if actor.is_airborne:
            # There is no such thing as a grounded strike in mid-air: the ROM
            # reads B in free flight as the jump kick ($3914), which is
            # JumpAttack's business and has its own launch/edge state machine
            # (execute.state_machine_jump_attack). Producing a Punch here
            # outranked that verb (20 vs 18) and pressed B straight through
            # it, so the kick fired -- or not -- by accident of timing.
            continue
        held_matches = (
            actor.held_weapon_type == 0 if held_types is None else actor.held_weapon_type in held_types
        )
        if not held_matches:
            continue
        # InPunchReach already carries the "in front (within tolerance) and
        # inside the band" judgment this used to recompute inline.
        kick_slots = {
            token.target_slot
            for token in find_all(context, AntonioIsGoingToKick)
            if token.actor_slot == actor.slot
        }
        for target_slot in reach.targets_of(context, InPunchReach, actor.slot):
            target = find(context, Enemy, slot=target_slot)
            if isinstance(target, Jack) and target.has_projectile:
                continue
            # Standing still to punch Antonio is the ROM's own kick trigger
            # ($16EAE zero-velocity path). Only a real punish window is
            # safe; otherwise DodgeAntonioKick / JumpAttack own him.
            if isinstance(target, Antonio) and (
                target_slot in kick_slots or not is_punishable(target.combat_phase)
            ):
                continue
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
        # On Jack's back (a jump that overshot, still facing the wrong
        # way): the chord would fire away from him. Walk around and grab.
        on_jacks_back = {
            token.target_slot
            for token in find_all(context, GrabJackFromBehind)
            if token.actor_slot == actor.slot
        }
        for target_slot in reach.targets_of(context, InRearReach, actor.slot):
            if target_slot in on_jacks_back:
                continue
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
        kicking = {
            token.target_slot
            for token in find_all(context, AntonioIsGoingToKick)
            if token.actor_slot == actor.slot
        }
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
            if enemy.slot in kicking:
                # could_dodge_antonio_kick owns this pair -- walking in to
                # stand still in front of him is how the kick starts.
                continue
            if (
                isinstance(enemy, Antonio)
                and abs(enemy.world_x - actor.world_x)
                <= reach.jump_attack_max_dx(actor.character_id)
            ):
                # Already inside jump-kick range. Walking closer parks the
                # actor inside the standing-still kick window. JumpAttack
                # owns the last stretch.
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


def could_projectile_sidestep(context: Context) -> Context:
    """Step off an incoming projectile's lane before it lands.

    One candidate per ``IncomingProjectile`` in context -- inference has
    already judged each one approaching, in this actor's lane, and within
    the impact window (``inference.check_for_incoming_projectiles``), so
    nothing here recomputes that geometry. Gated the same way as every other
    reactive verb: not mid-animation, not caught in an enemy's grab, and not
    itself holding one (a hold locks the actor's own input options, same
    reasoning as ``could_walk_to_near_enemy``/``could_retreat_from_danger``).
    """

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        for projectile in find_all(context, IncomingProjectile):
            verbs.add(ProjectileSidestep(actor_slot=actor.slot, target_slot=projectile.slot))
    return verbs


def _ahead_on_stage_path(stage: Stage | None, actor_x: int, target_x: int) -> bool:
    """Whether ``target_x`` still sits on the way to stage progress.

    Shared by ``could_open_breakable`` (which props to walk to) and
    ``_advance_blocking_breakables`` (which props hold back stage advance)
    so the two cannot disagree about the same crate. No stage, or a stage
    with no lateral direction, means every X is a candidate -- there is
    nothing to be "behind".
    """

    if stage is None or stage.direction == "none":
        return True
    if stage.direction == "right":
        return target_x >= actor_x - BREAKABLE_AHEAD_SLACK
    if stage.direction == "left":
        return target_x <= actor_x + BREAKABLE_AHEAD_SLACK
    return True


def _advance_blocking_breakables(context: Context) -> list[Breakable]:
    """On-camera breakables sitting on the stage path.

    A Breakable blocks lateral progress until destroyed. WalkToAdvanceStage
    walking into one, then OpenBreakable walking back (or around) to smash
    it, used to be a limit cycle: OpenBreakable's approach score is 14 down
    to 8 by distance, and WalkToAdvanceStage used to be a flat 12, so they
    handed the tick back and forth the moment hypot-distance crossed
    ~30-45px. Reported from play as the HUD flipping WalkToBreakable /
    WalkToAdvanceStage for as long as a crate was on screen. Advance now
    scores 1 (and 0 while a blocking crate exists), so the cycle cannot
    return, but this gate still refuses to produce the verb next to
    OpenBreakable.

    Same camera and pit filters as ``could_open_breakable``, so a crate
    this refuses to walk to cannot hold back advance either.
    """

    stage = find(context, Stage)
    camera = find(context, CameraRange)
    actors = _actors(context)
    if not actors:
        return []
    actor = actors[0]
    blocking: list[Breakable] = []
    for prop in find_all(context, Breakable):
        if camera is not None and not reach.in_camera(camera, prop.world_x, prop.world_y):
            continue
        if reach.any_pit_endangers(context, prop.world_x, prop.world_y):
            continue
        if _ahead_on_stage_path(stage, actor.world_x, prop.world_x):
            blocking.append(prop)
    return blocking


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

    Also gated on an on-camera Breakable sitting on the stage path: a crate
    blocks lateral progress until smashed, and producing this verb next to
    OpenBreakable is what made the two flip every few ticks (see
    ``_advance_blocking_breakables``).
    """

    verbs: set[Token] = set()
    stage = find(context, Stage)
    if stage is None or stage.direction == "none":
        return verbs
    if _advance_blocking_enemies(context):
        return verbs
    if _advance_blocking_breakables(context):
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


def _has_live_enemy(context: Context) -> bool:
    """A special with nobody to sweep is a waste of the one panic button."""

    return any(not enemy.is_defeated for enemy in find_all(context, Enemy))


def _police_is_worth_it(context: Context, actor: PlayableCharacter) -> bool:
    """The two situations the special is for: about to die, or boxed in.

    Both still need at least one live enemy -- calling the police into an
    empty street spends the special for nothing. ``Surrounded`` is the
    second reason: it is the only move that clears every side at once, so a
    crowd the actor cannot fight its way out of is as good a reason as low
    health, just at a laxer health gate so it is never spent while
    comfortably healthy.
    """

    if not _has_live_enemy(context):
        return False
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


def could_handle_continue_menu(context: Context) -> Context:
    """Always continue, and type ``AI `` on the high-score initials."""

    verbs: set[Token] = set()
    menu = find(context, InContinueMenu)
    if menu is not None:
        verbs.add(HandleContinueMenu(actor_slot=menu.slot))
    return verbs


def could_handle_mr_x_dialog(context: Context) -> Context:
    """Always refuse Mr. X's offer."""

    verbs: set[Token] = set()
    dialog = find(context, InMrXDialog)
    if dialog is not None:
        verbs.add(HandleMrXDialog(actor_slot=dialog.slot))
    return verbs


def could_jump_attack(context: Context) -> Context:
    """Jump-kick only when a horizontal approach is useful — never hop in
    place — and, once airborne, **always**.

    Two different questions, and conflating them is what left the AI sailing
    through jumps in silence:

    - *grounded*: should this jump happen at all? Answered by
      ``InJumpAttackReach`` (in front, past the punch's own outer edge,
      inside the kick's free-flight range) plus the "never launch into a
      committed attack" gate.
    - *airborne*: nothing is left to decide. The trajectory is fixed at
      takeoff (controls-and-input.md: no mid-air lane control, only limited
      air steer), so the only question is whether to press the kick edge --
      and pressing it is free, while not pressing it means landing having
      done nothing at all.

    That second case used to depend on ``InJumpAttackReach`` still holding
    mid-flight, which it often does not: the target walks out of the band,
    drifts a lane, or the flight simply carries the actor past it. Measured
    on the flight harness, 66 of 556 launched jumps produced no kick at all
    for exactly that reason -- and it is worse than a missing B, because a
    tick with no verb reaches ``press_no_button``, which *releases the
    directional hold*. Lose it during the 5-frame crouch and ``$384E`` reads
    no direction at launch, so the jump goes straight up as well as landing
    empty-handed. So while airborne this keeps the verb alive for the nearest
    live enemy when no band target remains.
    """

    verbs: set[Token] = set()
    # Deliberately every *live* enemy, not just the on-screen ones, for the
    # airborne fallback below: an actor already in the air is committed, and
    # an enemy a pixel outside the camera is still a better thing to aim the
    # kick at than releasing the controller mid-flight.
    live = reach.live_enemies(context)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.held_weapon_type != 0:
            # Unarmed only, like every other MeleeAttacks sibling. A held
            # weapon puts the ROM in the *parallel* jump family ($3C-$43,
            # controls-and-input.md) -- a different move, with a different
            # reach, whose kick edge this pipeline models nowhere: the band
            # below is the unarmed free-flight range (60/69/75) and
            # execute's state machine names the unarmed states. Observed
            # live with a bat in hand: 246 of 4859 ticks sat in $42, the
            # armed jump attack, while the AI believed it was performing an
            # ordinary jump kick. Armed, the answer is the weapon's own
            # swing -- could_swing_bat_or_pipe and friends -- reached by
            # walking in, which could_walk_to_near_enemy already does.
            continue
        target_slots = set(reach.targets_of(context, InJumpAttackReach, actor.slot))
        # Hopping over Antonio's kick is the reaction to AntonioIsGoingToKick
        # when the actor is already in the air (or about to be): the kick
        # is a ground strike, and the jump's own travel is the dodge. Added
        # even without InJumpAttackReach so a close-range hop still fires.
        kick_slots = {
            token.target_slot
            for token in find_all(context, AntonioIsGoingToKick)
            if token.actor_slot == actor.slot
        }
        target_slots |= kick_slots
        # Jump-kicking is the safe way to hit Antonio -- a grounded punch
        # is the kick trigger. Offer a hop whenever he is inside the
        # kick's free-flight range, not only in the usual "beyond punch"
        # band.
        for antonio in find_all(context, Antonio):
            if antonio.is_defeated:
                continue
            if abs(antonio.world_x - actor.world_x) <= reach.jump_attack_max_dx(
                actor.character_id
            ):
                target_slots.add(antonio.slot)
        if actor.is_airborne and not target_slots:
            nearest = min(
                live,
                key=lambda e: math.hypot(
                    e.world_x - actor.world_x, e.world_y - actor.world_y
                ),
                default=None,
            )
            if nearest is not None:
                target_slots = {nearest.slot}
        # Never *launch* into a committed attack: the kick's own travel
        # would deliver the actor to the enemy mid-swing, airborne and
        # unable to change its mind. Once already airborne there is no
        # changing course either way, so this gate only applies pre-launch.
        threatening = reach.targets_of(context, IncomingMelee, actor.slot)
        for target_slot in target_slots:
            if (
                not actor.is_airborne
                and target_slot in threatening
                and target_slot not in kick_slots
                and not isinstance(find(context, Enemy, slot=target_slot), Antonio)
            ):
                continue
            verbs.add(JumpAttack(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def could_dodge_antonio_kick(context: Context) -> Context:
    """Leave Antonio's kick lane, or hop, before the kick lands.

    One candidate per ``AntonioIsGoingToKick``. Suppressed once the actor
    is already airborne -- ``could_jump_attack`` owns the hop-over then,
    and producing a sidestep mid-crouch would release the jump direction
    ``$384E`` samples. Grounded, this is the reaction that does not stand
    still in front of him.
    """

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
        for token in find_all(context, AntonioIsGoingToKick):
            if token.actor_slot != actor.slot:
                continue
            verbs.add(
                DodgeAntonioKick(actor_slot=actor.slot, target_slot=token.target_slot)
            )
    return verbs


def _boomerang_in_punch_band(
    actor: PlayableCharacter, world_x: int, world_y: int
) -> bool:
    """Would a forward B connect with a point at ``(world_x, world_y)``.

    Facing is ignored: ``execute`` faces toward the boomerang on the same
    press, so a boomerang that is currently behind still counts if the
    distance is inside the punch box. Lane uses ``PUNCH_RANGE_Y``.
    """

    if abs(world_y - actor.world_y) > PUNCH_RANGE_Y + 6:
        return False
    dx = abs(world_x - actor.world_x)
    # A few extra px of outer slack: the boomerang is fast, and punching
    # a tick early still connects, while punching a tick late eats the hit.
    return dx <= punch_outer_x(actor.character_id, actor.held_weapon_type) + 12


def could_hit_antonio_boomerang(context: Context) -> Context:
    """Punch Antonio's boomerang at the moment it would hit the actor.

    One candidate per in-flight type-``$96`` ``Projectile`` that is heading
    at the actor (or already inside the punch box) and whose projected
    position at punch-connect time still sits in that box. Attached/wind-up
    copies are filtered by ``inference._antonio_still_holding_boomerang``.
    """

    from .inference import (
        ANTONIO_BOOMERANG_TYPE_ID,
        _antonio_still_holding_boomerang,
        _projectile_threatens,
    )

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

        for projectile in find_all(context, Projectile):
            if projectile.type_id != ANTONIO_BOOMERANG_TYPE_ID:
                continue
            if _antonio_still_holding_boomerang(projectile, context):
                continue
            if not _projectile_threatens(projectile, actor) and not _boomerang_in_punch_band(
                actor, projectile.world_x, projectile.world_y
            ):
                continue
            frames = kinematics.connect_frames(HitAntonioBoomerang, actor, projectile)
            if not any(
                _boomerang_in_punch_band(
                    actor,
                    round(projectile.world_x + projectile.vel_x * frame),
                    projectile.world_y,
                )
                for frame in frames
            ):
                continue
            verbs.add(
                HitAntonioBoomerang(actor_slot=actor.slot, target_slot=projectile.slot)
            )
    return verbs


def thrown_weapon_impact_point(actor: PlayableCharacter, enemy: Enemy, verb_cls) -> Enemy:
    """``enemy`` where the thrown weapon would actually meet it.

    The interception, not the current position: a knife covers 16 px per
    frame and pepper spray only 6 (weapons-range-and-damage.md), so a walking
    target moves a real distance during the flight -- half a body width for a
    knife thrown across the screen, several for pepper. ``kinematics``
    resolves the flight time against the target's own velocity.

    Shared with ``priority._emergency_thrown_weapon`` so the verb that gets
    produced and the score it is ranked with are computed about the same
    point; judging them at two different instants would let a candidate exist
    with an emergency of 0 and never be thrown.
    """

    return kinematics.target_at_impact(verb_cls, actor, enemy)


def _in_throw_envelope(actor: PlayableCharacter, target: Enemy) -> bool:
    """Beyond melee, inside throw range, at this exact position."""

    dx = abs(target.world_x - actor.world_x)
    dy = abs(target.world_y - actor.world_y)
    if dy > KNIFE_RANGE_Y:
        return False
    return KNIFE_MELEE_X < dx <= KNIFE_RANGE_X


def thrown_weapon_would_connect(
    actor: PlayableCharacter, enemy: Enemy, verb_cls
) -> bool:
    """True when the throw is worth making, judged now *or* at the impact.

    The union, like every other band in this pipeline
    (``inference.check_for_targets_in_reach``): the prediction may add a
    throw at a target that will have walked into the envelope, and may never
    withdraw one the observed position already offers.
    """

    return _in_throw_envelope(actor, enemy) or _in_throw_envelope(
        actor, thrown_weapon_impact_point(actor, enemy, verb_cls)
    )


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
            if thrown_weapon_would_connect(actor, enemy, verb_cls):
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


def breakable_smash_outer_x(prop: Breakable) -> int:
    """How far from a prop's origin the actor may stand and still hit it.

    ``BREAKABLE_PUNCH_X`` alone is an origin-to-origin distance, which is
    only meaningful while the prop is narrower than the punch reaches. It is
    not, for every type: ``prop_solids`` says a round-6 prop's wall already
    reaches 36px from its own origin -- exactly ``BREAKABLE_PUNCH_X`` -- so
    every position the ROM lets the actor stand in is one this would call out
    of range, and the verb would approach a prop it can never report having
    arrived at. That is the stall this whole pair of constants exists to
    avoid, arrived at from the other side.

    So the reach grows with the wall, and only with the wall: for every prop
    whose wall is already inside ``BREAKABLE_PUNCH_X`` (the phone booth, the
    crate, the round-3 prop) this is exactly the constant it always was, and
    nothing about their approach changes. ``SMASH_WALL_CLEARANCE_X`` is what
    the wider ones get on top of their wall -- enough that a lattice position
    (``NAV_STEP``, 4) or a deadband stop (``MOVE_DEADBAND_X``, 5) just
    outside the wall still counts as arrived, rather than landing in the gap
    between "as close as physics allows" and "close enough to punch".

    The geometry backs the wider number up: the punch box itself runs to
    ~44px in front of Axel, and a prop's *damage* box is its sprite body,
    which for the round-6 prop reaches ~26px back toward the actor from the
    origin -- so a strike thrown from 44px away still lands well inside it.
    """

    return max(
        BREAKABLE_PUNCH_X,
        prop_solids.solid_half_width(prop.type_id) + SMASH_WALL_CLEARANCE_X,
    )


def in_smash_range(actor: PlayableCharacter, prop: Breakable) -> bool:
    """Close enough that B hits the prop without moving first.

    Shared with ``priority`` and ``execute``, which both need the same
    answer now that one verb spans the approach and the strike.

    The **inner** edge matters as much as the outer one, and leaving it out
    was a hard stall: a punch box starts 16px in front of Axel, so a prop the
    actor is standing on top of cannot be hit at all -- but this said "in
    range", the executor pressed B instead of repositioning, and the
    resulting attack animation blocked every verb on the next tick, which
    released the controller and reset the steering axis, so the actor never
    walked away either. Recorded live: **94 seconds** of a 7-minute run spent
    punching one type-$11 prop from 1px away, ~430 presses, ending in a lost
    life -- and 22 shorter stalls in the same run.
    """

    dx = abs(prop.world_x - actor.world_x)
    return (
        punch_usable_inner_x(actor.character_id) <= dx <= breakable_smash_outer_x(prop)
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
        # Ahead on the stage path -- never a crate already behind, which
        # used to be the ``if not ahead: ahead = breakables`` fallback and
        # made the actor turn around after walking past one. A prop already
        # within smash range is still worth the B press on either side.
        candidates = {
            b.slot: b
            for b in breakables
            if _ahead_on_stage_path(stage, actor.world_x, b.world_x)
        }
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
        | could_handle_continue_menu(context)
        | could_handle_mr_x_dialog(context)
        | could_counter_grab(context)
        | could_tech_recover(context)
        | could_hold_actions(context)
        | could_grab_enemy(context)
        | could_walk_to_near_enemy(context)
        | could_retreat_from_danger(context)
        | could_projectile_sidestep(context)
        | could_dodge_antonio_kick(context)
        | could_hit_antonio_boomerang(context)
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
