"""``generate_verb_tokens`` and its ``could_*`` candidate generators.

Per ``AI.md``, each ``could_*`` function is concerned only with whether a
verb is possible and sensible — never with relative importance across
verbs, which is ``determine_priority_verb``'s job (``priority.py``).

Reach questions ("can this move hit that enemy from here?") are answered by
``reach.py``'s band predicates -- shared with ``priority.py`` so all stages
agree on one definition of every band -- called through ``_targets_in_reach``/
``_actionable_targets`` below.
"""

from __future__ import annotations

import math
from typing import Callable

from .. import prop_solids
from ..memory_map import ACTION_HOLD_CROSSOVER
from ..phases import CombatPhase, is_dangerous, is_punishable
from . import kinematics, navigation as nav, reach
from .tokens import (
    CounterGrab,
    FlipHold,
    GrabEnemy,
    HitAntonioBoomerang,
    JumpAttack,
    AttackHeldEnemy,
    MeleeWeaponAttack,
    Punch,
    RearAttack,
    ReleaseGrab,
    OpenBreakable,
    Supplex,
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
from .tokens import Antonio, Boss, Enemy, Jack, Souther
from .tokens import (
    GrabReason,
    Surrounded,
)
from .tokens import AnimationInProgress, CameraRange, DebugNoFood, Stage
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
    is_weapon_type,
)
from .tokens import CallPolice
from .tokens import HandleContinueMenu, HandleMrXDialog, InContinueMenu, InMrXDialog
from .tokens import Context, Token, find, find_all
from .tokens import (
    DodgeAntonioKick,
    DodgeSoutherSlash,
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
# A live Boss is a third reason, at the same laxer gate as Surrounded: $16A60
# (later_boss_police_special_reaction) does a flat -10 HP against the
# $55-$58 family's shared 32-max health pool ($17EDC boss_init_combat_stats),
# so one press is roughly a third of a later-boss's whole bar -- an order of
# magnitude better than the special's ordinary value against a street enemy.
# Hoarding it for the panic thresholds above and dying with it unspent is
# worse than spending it well before that against a boss.
POLICE_HEALTH_PERCENT_THRESHOLD_BOSS = 60.0

KNIFE_RANGE_X = 90
KNIFE_RANGE_Y = 16
KNIFE_MELEE_X = 40
PEPPER_SPRAY_TYPE = 0x0C

HEALTH_PICKUP_MISSING_MIN = 16
HEALTH_CRITICAL_PERCENT = 40.0

BREAKABLE_PUNCH_X = 36
# When to press B: the punch attack box is ±8 on lane. A larger number
# fired the strike from a corner the box cannot reach and the booth
# never broke. The *walk* goal still uses BREAKABLE_APPROACH_Y -- a
# 16px body needs more than 8px of slack to have a region at all.
BREAKABLE_PUNCH_Y = 8
BREAKABLE_APPROACH_Y = 16
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
    """Whether ``actor`` has a body in its hands -- the gate every other
    ``could_*`` stands down behind, so the hold family owns the tick.

    Thin alias for ``PlayableCharacter.is_holding_enemy``, which reads the
    ROM's own hold link (``+$4C``) and the action family rather than
    ``+$60`` alone. ``+$60`` is the *weapon* link and says nothing about a
    held later boss -- the bug that let the AI stand in a live front hold on
    Antonio for a whole round-1 fight without ever pressing B.
    """

    return actor.is_holding_enemy


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


def _targets_in_reach(context: Context, actor: PlayableCharacter, band, verb_cls) -> set[str]:
    """Live enemies ``verb_cls`` would connect with from here, right now.

    Tested across the move's own timeline (``reach.connects``,
    ``kinematics.connect_frames(verb_cls, ...)``) rather than only at the
    observed instant, so an enemy walking *into* range arms the move as it
    arrives instead of after. Shared by every ``could_*`` that asks "can
    this move reach that enemy" so the band is computed identically
    wherever it is asked -- see ``reach.connects``.
    """

    return {
        enemy.slot
        for enemy in reach.live_enemies(context)
        if reach.connects(band, actor, enemy, kinematics.connect_frames(verb_cls, actor, enemy))
    }


def _actionable_targets(context: Context, actor: PlayableCharacter) -> set[str]:
    """Live enemies some already-available attack would really fire on now.

    Answered about the observed position only, unlike ``_targets_in_reach``:
    this is the "stop walking, you can already hit it" signal
    ``could_walk_to_near_enemy`` reads, and answering it about the future
    would stop the approach early. See ``reach.enemy_actionable``.
    """

    enemies = reach.live_enemies(context)
    return {enemy.slot for enemy in enemies if reach.enemy_actionable(actor, enemy, enemies)}


STAB_WEAPON_TYPES = frozenset({0x08, 0x09})  # knife, bottle
# Every weapon type MeleeWeaponAttack covers: bat/pipe, knife/bottle, pepper.
MELEE_WEAPON_HELD_TYPES = MELEE_WEAPON_TYPES | STAB_WEAPON_TYPES | frozenset({PEPPER_SPRAY_TYPE})


def _could_melee_strike(
    context: Context, *, held_types: frozenset[int] | None, make_verb: Callable[[str, str, int], Token]
) -> Context:
    """Shared body for ``could_punch`` / ``could_melee_weapon_attack``: they
    issue the identical B-button input (see execute.py's
    ``state_machine_melee_strike``), gated only on which weapon type (if any)
    the actor holds. ``held_types=None`` means unarmed (``Punch``).
    ``make_verb(actor_slot, target_slot, held_weapon_type)`` builds the
    concrete ``Verb`` -- ``Punch`` ignores the weapon type it is passed,
    ``MeleeWeaponAttack`` carries it as its own ``weapon_type`` field.

    Refuses an *unarmed* punch on a Jack currently juggling his axe/torch
    (``Jack.has_projectile``): closing in with bare fists trades hits with
    the spin. A held weapon reaches past that spin -- bat, pipe, knife,
    bottle, pepper -- and must be used; ``could_jump_attack`` is already
    refused while armed, so skipping the swing left the AI walking around
    him doing nothing. The kick and the from-behind chord stay available
    unarmed.
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
        # _targets_in_reach already carries the "in front (within tolerance)
        # and inside the band" judgment this used to recompute inline.
        for target_slot in _targets_in_reach(context, actor, reach.punch_would_connect, Punch):
            target = find(context, Enemy, slot=target_slot)
            if (
                held_types is None
                and isinstance(target, Jack)
                and target.has_projectile
            ):
                continue
            # Antonio: a grounded B is standing still in front of him, and
            # $16EAE's zero-velocity path is the kick trigger. That is the
            # first punch as much as a follow-up combo -- the previous
            # "one punch opens the grab" exception stood in the window
            # that arms the kick and lost the ranking contest to the hop
            # that should have been the opener (punch 20+boss vs jump 18+
            # boss). The hop is the opener (could_jump_attack); the grab
            # is the punish (ANTONIO_ON_PUNISH); DodgeAntonioKick owns a
            # kick/dash that is already locked in.
            if isinstance(target, Antonio):
                continue
            verbs.add(make_verb(actor.slot, target_slot, actor.held_weapon_type))
    return verbs


def could_punch(context: Context) -> Context:
    return _could_melee_strike(
        context,
        held_types=None,
        make_verb=lambda actor_slot, target_slot, _weapon_type: Punch(
            actor_slot=actor_slot, target_slot=target_slot
        ),
    )


def could_melee_weapon_attack(context: Context) -> Context:
    return _could_melee_strike(
        context,
        held_types=MELEE_WEAPON_HELD_TYPES,
        make_verb=lambda actor_slot, target_slot, weapon_type: MeleeWeaponAttack(
            actor_slot=actor_slot, target_slot=target_slot, weapon_type=weapon_type
        ),
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
        # _targets_in_reach only, not a fast-closing enemy's own
        # velocity: an earlier version also fired on that early-warning
        # signal, before the enemy was actually in the chord's real range.
        # Live testing showed that backfires -- $322A only hits based on
        # *current* position, so committing to it early is a guaranteed
        # whiff that locks the actor in the attack's own recovery frames
        # exactly when the still-closing enemy arrives and lands its hit
        # for free.
        # Produced on band membership alone, per AI.md: a could_* asks only
        # "is this possible and does it make some kind of sense", never "is
        # this the one to take". Whether the chord is the *right* answer --
        # rather than turning around and punching -- is a ranking question,
        # and lives in priority._emergency_rear_attack via
        # reach.rear_attack_is_warranted.
        # On Jack's back (a jump that overshot, still facing the wrong
        # way): the chord would fire away from him. Walk around and grab.
        on_screen = reach.on_screen_enemies(context)
        on_jacks_back = {
            jack.slot
            for jack in on_screen
            if isinstance(jack, Jack)
            and GrabReason.JACK_FROM_BEHIND in reach.grab_reasons(context, actor, jack, on_screen)
        }
        for target_slot in _targets_in_reach(context, actor, reach.in_rear_band, RearAttack):
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


def _walk_in_beats_the_hop(actor: PlayableCharacter, antonio: Antonio) -> bool:
    """True when this actor should take a hold on ``antonio`` rather than hop.

    Unarmed (a held weapon has no grab and no unarmed kick -- ``could_jump_
    attack`` refuses the launch armed anyway) and already inside the X range
    the hold is taken from, whatever the lane offset still is. The lane half
    is deliberately *not* tested: the ticks while the approach converges the
    last of its offset are exactly when the hop used to win.

    The range is the **hold's**, not the hop's, and that boundary is
    measured rather than reasoned. Widening it to the hop's own band (75px
    on Blaze) does what it says -- hop episodes fell to 10-133 ticks a fight
    -- and cost health: 40 / 60 / 60 damage taken against 60 / 20 / 20 / 20 /
    20 for this version. Out at 60-75px on his lane the hop is the better
    answer, because it closes the gap *and* attacks, where walking that band
    just stands in the kick window for longer. The hop is not the enemy; the
    hop **as the only plan** was.
    """

    if actor.held_weapon_type != 0 or actor.is_airborne:
        return False
    if antonio.is_defeated:
        return False
    return abs(antonio.world_x - actor.world_x) <= punch_outer_x(actor.character_id)


def could_grab_enemy(context: Context) -> Context:
    """Walk into an enemy, unarmed and unattacking, to take a hold of it.

    Both halves of the question are already answered: ``reach.grab_would_
    connect`` says the walk-in would connect, ``reach.grab_reasons`` says the
    hold is worth more than a strike here. This function only adds the
    gates about the *actor*.

    Armed actors are excluded. The ROM's contact test does not care what the
    actor carries -- a live front hold on Antonio was recorded with a pipe
    (``$0B``) still in ``+$60`` -- but every held weapon has its own melee
    move with better reach or damage than a bare hold, and closing to contact
    would spend that advantage, so for the AI holding a weapon is a reason
    not to grab, exactly as it is a reason not to ``Punch``.

    Lifting this for Antonio alone -- where the weapon really does buy
    nothing, since every grounded B on him is refused armed or not -- was
    tried and **measured worse**: three fights gave 40 / 160 / 40 damage
    taken with a death, against 40 / 40 / 20 / 60 / 60 and none without it,
    and the hop it was meant to displace did not go away. See
    ``autoplay/CLAUDE.md``.
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
        in_reach = _targets_in_reach(context, actor, reach.grab_would_connect, GrabEnemy)
        threatening = reach.incoming_melee_targets(context, actor)
        on_screen = reach.on_screen_enemies(context)
        for enemy in on_screen:
            if enemy.slot not in in_reach:
                continue
            if enemy.slot in threatening:
                # Walking into a committed attack is how the actor takes the
                # hit rather than the hold -- same reasoning that keeps
                # could_jump_attack from kicking into one.
                continue
            if not reach.grab_reasons(context, actor, enemy, on_screen):
                continue
            verbs.add(GrabEnemy(actor_slot=actor.slot, target_slot=enemy.slot))
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
        # ...including the C crossover ($76/$80), which runs ~28 ticks and
        # ignores every fresh edge: acting through it is what put a
        # WalkToNearEnemy and a rear chord between a flip and its suplex.
        if base in (0x28, 0x2A, 0x2C, 0x2E, 0x62, 0x64, 0x68, 0x6A, 0x6C, 0x6E):
            continue
        if base in ACTION_HOLD_CROSSOVER:
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

        # reach.held_enemy answers this for a later boss too, which the
        # GRABBED phase alone cannot: a held Antonio reads primary $04, the
        # same byte as his ordinary hit reaction. Nearest-of-everything stays
        # as the last resort so a hold whose partner cannot be identified at
        # all still knees rather than idling.
        nearest = reach.held_enemy(actor, enemies) or min(
            [e for e in enemies if e.combat_phase is CombatPhase.GRABBED] or enemies,
            key=_distance,
            default=None,
        )
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
# So retreat is gated on the one situation where the exchange genuinely is not
# survivable and space is worth more than damage: **hurt** -- below this much
# health there is no room to trade, and a KO costs a whole life. Shares
# HEALTH_CRITICAL_PERCENT's reading of "hurt enough to change plans", which
# _pickup_is_useful already uses.
#
# **Being surrounded used to be a second reason, and is not any more.** That
# clause read "no amount of facing answers being hit from both sides at once;
# the only fix is space" -- and space is not the fix. Per the user, a crowd is
# answered by taking a hold: grab one of the bodies and suplex or throw it
# (see inference.check_for_grab_opportunities' GrabReason.WHILE_SURROUNDED
# case). Backing away from a crowd at full health is the failure this whole
# comment already describes one paragraph up -- the AI backs off, the crowd
# follows, and the round goes nowhere -- it was just exempted from its own
# rule.
#
# Measured, and this is why it had to go rather than merely be re-tuned:
# widening check_for_surrounded's box (reach.SURROUNDED_NEAR_X/_Y) so the
# judgment stops collapsing after a dozen pixels made *this* gate fire
# everywhere, and over 1155 swept crowd scenes RetreatFromDanger went 173 ->
# 376 while WalkToNearEnemy went 381 -> 204. The AI got dramatically more
# passive as a direct side effect of making the crowd judgment work.
#
# Surrounded still matters -- it raises CallPolice (the actual panic button,
# still health-gated) and the WHILE_SURROUNDED grab reason. It just no
# longer means "flee".
#
# Healthy, the AI walks in and takes the hit it has to take, crowd or not.
RETREAT_HEALTH_PERCENT_THRESHOLD = HEALTH_CRITICAL_PERCENT


def _retreat_is_worth_it(context: Context, actor: PlayableCharacter) -> bool:
    """Whether backing off beats engaging -- see RETREAT_HEALTH_PERCENT_THRESHOLD.

    Also the single owner test for a dangerous, close enemy: when this is
    true ``could_retreat_from_danger`` claims it and
    ``could_walk_to_near_enemy`` stands off; when false the walk claims it and
    retreat produces nothing. Exactly one of the two ever holds a given
    enemy, which is what keeps them from handing it back and forth.
    """

    return actor.health_percent < RETREAT_HEALTH_PERCENT_THRESHOLD


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
        actionable = _actionable_targets(context, actor)
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
        threatening = reach.incoming_melee_targets(context, actor)
        standing_off = _retreat_is_worth_it(context, actor)
        for enemy in enemies:
            if enemy.slot in actionable:
                # Already hittable: walking closer to *this* enemy is what the
                # skip means. It is deliberately per-enemy and not "any enemy
                # is actionable, so propose nothing" -- that global form was a
                # live-reported bug, and a bad one, because it made the boss
                # disappear from the tick entirely. With a grunt in punch range
                # and Souther two steps away, no verb was produced for Souther
                # at all, so the grunt's punch won by default and the AI stood
                # there hitting the sideshow while the boss walked in. Ranking
                # is what should settle that (the walk-in carries
                # _EMERGENCY_BOSS_TARGET), and it cannot settle a contest it is
                # never shown.
                continue
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
                isinstance(enemy, Antonio)
                and enemy.strike_is_committed()
                and reach.antonio_will_kick(enemy, actor)
            ):
                # could_dodge_antonio_kick owns a locked-in kick/dash.
                continue
            if (
                isinstance(enemy, Antonio)
                and not is_punishable(enemy.combat_phase)
                and not _walk_in_beats_the_hop(actor, enemy)
                and reach.connects(
                    reach.in_jump_attack_band,
                    actor,
                    enemy,
                    kinematics.connect_frames(JumpAttack, actor, enemy),
                )
            ):
                # Jump-kick owns the last stretch only when the kick would
                # actually connect (same lane, in front, in range) *and*
                # there is no hold to take instead -- armed, in other words,
                # since that is the one case with no grab (and no unarmed
                # kick either). An X-only skip hopped at him from any lane
                # and kicked air. A punishable Antonio is a grab walk-in,
                # and so, now, is a ready one already at contact X range:
                # the walk has to keep the tick or nothing converges the
                # lane offset the approach is holding.
                continue
            if (
                standing_off
                and is_dangerous(enemy.combat_phase)
                and reach.too_close_to_keep_approaching(
                    actor, enemy, extra_margin=reach.APPROACH_RELEASE_MARGIN
                )
            ):
                # Hysteresis (see reach.APPROACH_RELEASE_MARGIN). Skipping
                # only on the incoming-melee judgment above put approach and
                # retreat on one shared boundary: a single retreat step
                # cleared it, which un-skipped this walk, which walked
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
        actionable = _actionable_targets(context, actor)
        for target_slot in reach.incoming_melee_targets(context, actor):
            enemy = find(context, Enemy, slot=target_slot)
            if enemy is None:
                continue
            if target_slot in actionable:
                continue  # already hittable -- attack instead of retreating
            verbs.add(RetreatFromDanger(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def could_projectile_sidestep(context: Context) -> Context:
    """Step off an incoming projectile's lane before it lands.

    One candidate per observed ``Projectile`` that ``reach.projectile_
    threatens`` this actor -- approaching, in this actor's lane, and within
    the impact window -- unless it is still tethered to whoever is carrying
    it (``reach.jack_still_juggling``/``antonio_still_holding_boomerang``) or
    is one of Souther's unthrowable claw/afterimage objects (``reach.is_
    souther_claw``). Gated the same way as every other reactive verb: not
    mid-animation, not caught in an enemy's grab, and not itself holding one
    (a hold locks the actor's own input options, same reasoning as
    ``could_walk_to_near_enemy``/``could_retreat_from_danger``).
    """

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        for projectile in find_all(context, Projectile):
            if reach.jack_still_juggling(projectile, context):
                continue
            if reach.antonio_still_holding_boomerang(projectile, context):
                continue
            if reach.is_souther_claw(projectile):
                continue
            if not reach.projectile_threatens(projectile, actor):
                continue
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

    "Off-screen" here has to mean the same thing it means there, which is
    ``reach.in_visible_screen`` -- the CRT -- and not ``in_camera``'s walk
    clamp. A body in the 32px strip down either side of the clamp *is*
    chased now, so carving it out would hand the advance a target the
    approach is still walking toward.
    """

    camera = find(context, CameraRange)
    blocking = []
    for enemy in reach.live_enemies(context):
        if (
            camera is not None
            and not reach.in_visible_screen(camera, enemy.world_x, enemy.world_y)
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
    """The three situations the special is for: about to die, boxed in, or a
    live boss.

    All three still need at least one live enemy -- calling the police into
    an empty street spends the special for nothing (the boss case implies
    this already, but the shared early return keeps the rule in one place).
    ``Surrounded`` and a live ``Boss`` are both laxer-gate reasons: the
    special is the one move that clears every side at once, and against
    ``$16A60``'s flat -10 HP it is worth roughly a third of a later-boss's
    whole health bar in one press -- both good enough reasons to spend it
    well before the "about to die" thresholds, at a health gate just lax
    enough that it is never spent while comfortably healthy either.

    Souther is carved out of the boss bonus (user: "a maioria do dano
    deve-se a ataques de polícia, não usar ataques de polícia"). The call
    does buy the flat 10 damage, but it also puts the *caller* into action
    ``$3`` for the shared ``$16AEC`` delay -- 300 P1 / 390 P2 frames, about
    5-6.5s, entirely unresponsive to input (measured live: 798 of 798 ticks
    sampled in that action were at an unchanged position, the longest run
    644 ticks starting on the exact tick ``CallPolice`` fired). That is also
    the single longest window ``SOUTHER_ON_PUNISH`` ever gets -- Souther is
    forced into the shared ``$0A`` reaction for the same span -- so the call
    spends the fight's best grab-and-suplex opportunity on a frozen actor
    and buys only the scripted 10, where a landed hold-into-suplex chain is
    worth far more. The re-approach that follows from scratch is where
    ``autoplay/CLAUDE.md``'s "every hit is primary $02, with WalkToNearEnemy
    holding the tick through the second before" damage actually comes from,
    which is the indirect sense in which the special *causes* it. The
    near-death thresholds above stay: at 18%/35% health nothing is lost by
    freezing, since Souther freezes with the actor, and a life lost there
    (+``PLAYER_MAX_HEALTH`` on the scored damage total) is far worse than a
    spent special. Scoped to Souther, not the shared mechanism, because
    Antonio's numbers are separately measured and this has not been.
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
    if surrounded and actor.health_percent < POLICE_HEALTH_PERCENT_THRESHOLD_SURROUNDED:
        return True
    boss_alive = any(
        not boss.is_defeated and not isinstance(boss, Souther)
        for boss in find_all(context, Boss)
    )
    return boss_alive and actor.health_percent < POLICE_HEALTH_PERCENT_THRESHOLD_BOSS


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
      ``_targets_in_reach`` with ``reach.in_jump_attack_band`` (in front,
      in lane, inside the kick's free-flight range; past punch outer
      except for Antonio, whose opener includes punch range because a
      grounded B is his kick trigger), the "never launch into a committed
      attack" gate, and
      ``navigation.jump_landing_is_safe`` -- the pathfinder refuses a
      launch whose current-lane flight would skip a walk-around and land
      in a pit.
    - *airborne*: nothing is left to decide. The trajectory is fixed at
      takeoff (controls-and-input.md: no mid-air lane control, only limited
      air steer), so the only question is whether to press the kick edge --
      and pressing it is free, while not pressing it means landing having
      done nothing at all.

    That second case used to depend on the jump-attack band still holding
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
            # swing -- could_melee_weapon_attack -- reached by walking in,
            # which could_walk_to_near_enemy already does.
            continue
        if not actor.is_airborne and reach.souther_would_punish_jump(actor, context):
            # The exact opposite of the Antonio exception below. Souther's
            # $16234 (souther_counter_jump_attack) reads the *player's* action
            # state -- $16/$17/$42/$43, this very move -- and answers it by
            # jumping straight to primary $02 with the claw already spawned,
            # ignoring every distance band and gate the ordinary commit has to
            # satisfy. So there is no geometry that makes the launch safe: the
            # refusal is per-actor and covers every target, because a hop aimed
            # at an unrelated grunt inside his box is countered identically.
            #
            # It is also not limited to the states that arm the counter, which
            # is how the first version of this let the AI jump into the claws
            # anyway: the handlers that skip $16234 skip it because he is
            # *already attacking*, so that window is the one where a live claw
            # is waiting for the flight. See reach.souther_would_punish_jump.
            #
            # Only the *launch* is refused. Once airborne the flight is
            # committed and the fallback below still has to produce a verb, or
            # the tick reaches press_no_button and costs both the kick and the
            # held direction $384E samples.
            continue
        target_slots = _targets_in_reach(context, actor, reach.in_jump_attack_band, JumpAttack)
        # Jump-kicking Antonio is the opener inside punch range too
        # (in_jump_attack_band drops its min-dx for him), but only when
        # the kick would connect: same lane, in front, within free-flight
        # range. An earlier X-only add hopped at him from any lane. A
        # punishable Antonio is a grab, not another hop -- unless already
        # airborne, when the flight has to finish.
        kick_slots = {
            antonio.slot
            for antonio in find_all(context, Antonio)
            if not antonio.is_defeated and reach.antonio_will_kick(antonio, actor)
        }
        if not actor.is_airborne:
            for antonio in find_all(context, Antonio):
                if is_punishable(antonio.combat_phase):
                    target_slots.discard(antonio.slot)
                elif _walk_in_beats_the_hop(actor, antonio):
                    # Ready, and the approach has already brought the actor
                    # to the X range a hold is taken from. The hop from here
                    # is 45 committed airborne frames for ~2 damage; the
                    # walk-in is a few frames and ends with him unable to
                    # act at all (GrabReason.ANTONIO_WALK_IN). Withdrawing
                    # the hop here is what stops it winning the couple of
                    # ticks while the approach converges the last of the
                    # lane offset, which is the only reason it still had the
                    # tick: at that moment the grab is not yet offered
                    # (grab_would_connect wants GRAB_RANGE_Y) and nothing
                    # else outranks a jump.
                    target_slots.discard(antonio.slot)
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
        threatening = reach.incoming_melee_targets(context, actor)
        for target_slot in target_slots:
            if (
                not actor.is_airborne
                and target_slot in threatening
                and target_slot not in kick_slots
                and not isinstance(find(context, Enemy, slot=target_slot), Antonio)
            ):
                continue
            if not actor.is_airborne:
                target = find(context, Enemy, slot=target_slot)
                if target is None:
                    continue
                # The pathfinder owns "would this jump land in a pit / skip
                # a walk-around": a grounded launch that fails that test is
                # the stage-4 suicide (kick toward an enemy across a hole).
                # Airborne the trajectory is already committed.
                if not nav.jump_landing_is_safe(context, actor, target.world_x):
                    continue
            verbs.add(JumpAttack(actor_slot=actor.slot, target_slot=target_slot))
    return verbs


def could_dodge_antonio_kick(context: Context) -> Context:
    """Answer his kick -- by hopping the one already locked in, or by
    stepping out of the gate that has not fired yet.

    One candidate per live Antonio whose kick gate (``reach.antonio_will_
    kick``) is live. ``committed`` splits the two cases and they take
    opposite inputs: primary ``$02`` or tactical ``$08`` is a strike already
    coming and gets the hop, while a merely *satisfiable* gate gets a pure
    lane step that denies it -- ``$16EAE`` needs the target within ``$10``
    (16px) of his lane, so 16px of lane is the whole difference between a
    kick and no kick.

    The uncommitted half used to be refused outright ("a predicted window is
    the opener, not a dodge"), on the reasoning that stepping out while he is
    still choosing is a dodge loop that never reaches grab range. What that
    missed is how much warning the gate actually gives: measured over nine
    onsets in one fight, ``antonio_will_kick`` was true for **9-12 ticks**
    before seven of them, with the actor sitting at 7px of lane and hopping
    straight into it. `reach.can_break_antonio_kick_lane` is what keeps the
    loop from returning -- it produces nothing once the actor is already
    clear, so the step ends by itself.

    Suppressed once the actor is already airborne -- ``could_jump_attack``
    owns the hop-over then, and producing a sidestep mid-crouch would
    release the jump direction ``$384E`` samples.
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
        for antonio in find_all(context, Antonio):
            if antonio.is_defeated:
                continue
            if not reach.antonio_will_kick(antonio, actor):
                continue
            committed = antonio.strike_is_committed()
            if not committed and not reach.can_break_antonio_kick_lane(actor, antonio):
                # Nothing a pre-emptive step could achieve: already clear of
                # his lane, or with no room to get clear. Leaving the tick to
                # the approach here is what keeps this from becoming the
                # dodge loop that never reaches grab range.
                continue
            verbs.add(
                DodgeAntonioKick(
                    actor_slot=actor.slot,
                    target_slot=antonio.slot,
                    committed=committed,
                )
            )
    return verbs


def could_dodge_souther_slash(context: Context) -> Context:
    """Step off the lane of a claw dash Souther has already committed to.

    One candidate per live Souther whose claw gate (``reach.souther_will_
    slash``) is live and who is in primary ``$02``
    (``Souther.strike_is_committed``). The uncommitted state-1 gate is
    deliberately not enough, for the same reason ``could_dodge_antonio_kick``
    refuses it: leaving the lane while he is still choosing is the dodge loop
    that never gets close enough to hit him.

    A lane step is the *whole* answer, and specifically not a hop --
    ``$161C6 (souther_state2_claw_dash)`` writes only ``+$1C`` and so cannot
    follow the lane change, while ``$16234
    (souther_counter_jump_attack)`` punishes exactly the jump that answers
    Antonio. Suppressed while airborne, like the Antonio dodge, since
    ``could_jump_attack`` owns a flight already underway.
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
        for souther in find_all(context, Souther):
            if souther.is_defeated:
                continue
            if not reach.souther_will_slash(souther, actor):
                continue
            if not souther.strike_is_committed():
                # Predicted window only: walking in and punching is the
                # opener, same as could_dodge_antonio_kick. A pre-emptive
                # version of this branch shipped once (the predicted
                # $15EDA gate alone was enough to dodge) and was reverted:
                # measured live over a full fight it fired on only 28 of
                # 1794 ticks, no measurable benefit, and it is redundant
                # with execute._souther_pocket_stop_dx now denying the
                # commit outright by keeping the approach inside the $18
                # inner abort in the first place -- from there
                # reach.souther_will_slash's own predictive gate cannot even
                # fire (dist_x < SOUTHER_SLASH_DIST_MIN refuses it), so a
                # pre-emptive dodge branch would mostly be dead weight,
                # not more coverage.
                continue
            verbs.add(
                DodgeSoutherSlash(actor_slot=actor.slot, target_slot=souther.slot)
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
    copies are filtered by ``reach.antonio_still_holding_boomerang``.
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

        for projectile in find_all(context, Projectile):
            if projectile.type_id != reach.ANTONIO_BOOMERANG_TYPE_ID:
                continue
            if reach.antonio_still_holding_boomerang(projectile, context):
                continue
            if not reach.projectile_threatens(projectile, actor) and not _boomerang_in_punch_band(
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


def _a_weapon_would_disarm_the_plan(context: Context) -> bool:
    """Whether picking a weapon up would cost more than it could ever pay.

    True while a live Souther is on screen, and measured rather than
    reasoned. Armed, the AI has **no move on him at all**: ``could_grab_
    enemy`` excludes an armed actor outright, ``could_punch`` is unarmed-only,
    and ``could_jump_attack`` is refused near him for his own counter. What
    is supposed to replace them is ``MeleeWeaponAttack`` -- and across ten
    scored fights it fired **zero** times, while ``WalkToWeapon`` took 137 to
    223 ticks of five of them. The detour is pure loss: it spends the
    approach and hands back nothing.

    That matters more against him than against anyone else because the hold
    is the plan (user: "e essencial agarrar o boss"), and being armed is the
    one condition that forbids the hold outright. The ROM's own contact grab
    does not care what the actor carries -- a live front hold on Antonio was
    recorded with a pipe in ``+$60`` -- but lifting that exclusion was tried
    for Antonio and measured worse, so the answer here is the other one: do
    not pick the weapon up while the fight that needs bare hands is on.

    Scoped to Souther deliberately. The same refusal was tried twice for
    Antonio and measured no better both times (see autoplay/CLAUDE.md); his
    fight has a hop in it that an armed actor can still throw, and this one
    does not.
    """

    return any(not souther.is_defeated for souther in find_all(context, Souther))


def could_walk_to_weapon(context: Context) -> Context:
    verbs: set[Token] = set()
    camera = find(context, CameraRange)
    if _a_weapon_would_disarm_the_plan(context):
        return verbs
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        # reach.weapon_upgrade_rank is the judgment "in camera, still usable,
        # and better than what this actor holds" -- one candidate per
        # upgrade, since priority.py's rank-scaled emergency favours the
        # better one rather than a min/max pick made here.
        for weapon in find_all(context, Weapon):
            if reach.weapon_upgrade_rank(actor, weapon, camera) is None:
                continue
            if reach.any_pit_endangers(context, weapon.world_x, weapon.world_y):
                # Never walk toward a target sitting in a pit's danger zone.
                continue
            verbs.add(WalkToWeapon(actor_slot=actor.slot, target_slot=weapon.slot))
    return verbs


def _food_is_spoken_for(context: Context) -> bool:
    """Whether the food on this screen must be left where it is.

    True while a live Antonio is on screen (user): the round-1 arena's food
    is what a player who has just fought the whole street arrives *needing*,
    and the boss fight is not allowed to spend it. Measured, this is not a
    small thing either -- across ten fights the one that took four hits (a
    full bar) survived only by eating at 20 HP, so the AI was leaning on the
    pickup as a crutch and the numbers were flattered by it.

    Deliberately about the pickup, not the walk: `_boss_attack_gate_is_live`
    already refuses *other* item detours inside his kick window and used to
    exempt health from that as "the one thing worth a kick". This overrides
    that exemption for him -- the fight has to be survivable without it.

    ``DebugNoFood`` says the same thing for a whole session rather than for
    one boss: it is the harness's ``--no-food``, so a measured fight cannot
    be flattered by a heal. See that token.
    """

    if find(context, DebugNoFood) is not None:
        return True
    return any(not antonio.is_defeated for antonio in find_all(context, Antonio))


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
        leave_the_food = _food_is_spoken_for(context)
        useful = [
            p
            for p in pickups
            if _pickup_is_useful(actor, p)
            and not (leave_the_food and isinstance(p, HealthPickup))
        ]
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
    if not (
        punch_usable_inner_x(actor.character_id) <= dx <= breakable_smash_outer_x(prop)
    ):
        return False
    # Prefer the ROM's own test: attack-box lane vs the prop's body lane.
    # Origin slack of 16 punched through air when the body sat behind the
    # origin (every solid record ends 4px in front of the feet).
    if prop.hitbox is not None and not prop.hitbox.is_degenerate:
        punch_y0 = actor.world_y - BREAKABLE_PUNCH_Y
        punch_y1 = actor.world_y + BREAKABLE_PUNCH_Y
        return punch_y0 < prop.hitbox.y1 and prop.hitbox.y0 < punch_y1
    return abs(prop.world_y - actor.world_y) <= BREAKABLE_PUNCH_Y


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
        | could_dodge_souther_slash(context)
        | could_hit_antonio_boomerang(context)
        | could_walk_to_advance_stage(context)
        | could_punch(context)
        | could_melee_weapon_attack(context)
        | could_rear_attack(context)
        | could_call_police(context)
        | could_jump_attack(context)
        | could_throw_knife(context)
        | could_throw_pepper(context)
        | could_walk_to_weapon(context)
        | could_walk_to_pickup(context)
        | could_open_breakable(context)
    )
