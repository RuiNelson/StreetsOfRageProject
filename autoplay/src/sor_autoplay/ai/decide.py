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

from . import press as press_model
from .. import prop_solids
from ..memory_map import ACTION_HOLD_CROSSOVER
from ..phases import CombatPhase, is_dangerous
from . import (
    abadede as abadede_plan,
    garcia as garcia_model,
    mr_x as mr_x_model,
    mr_x_plan,
    bongo as bongo_plan,
    jack as jack_plan,
    kinematics,
    navigation as nav,
    reach,
    souther as souther_plan,
)
from .tokens import (
    CounterGrab,
    FlipHold,
    GrabEnemy,
    HitAntonioBoomerang,
    HitTable,
    JumpAttack,
    AttackHeldEnemy,
    MeleeWeaponAttack,
    Punch,
    RearAttack,
    ReleaseGrab,
    ReleasePartner,
    ReleaseToRegrab,
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
from .tokens import Abadede, Antonio, Bongo, Boss, Enemy, Garcia, Jack, MrX, MrXOffice, Onihime, Souther
from .tokens import (
    GrabReason,
    Surrounded,
)
from .tokens import AnimationInProgress, CameraRange, DebugNoFood, DebugNoPolice, Stage
from .tokens import Breakable, Projectile
from .tokens import PUNCH_RANGE_Y, punch_outer_x
from .tokens.character import knife_cone_contains
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
    EngageAbadede,
    EngageMrX,
    FightMrXOffice,
    EngageTwins,
    EngageAntonio,
    EngageBongo,
    EngageJack,
    EngageSouther,
    ProjectileSidestep,
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToScreenCenter,
    WalkToWeapon,
)

# Police special is scarce (usually 1/life). Only panic-level situations.
POLICE_HEALTH_PERCENT_THRESHOLD = 18.0
# On the last life a KO risks a continue/game-over screen instead of a free
# respawn at full health (player-health-lives-and-combat.md) -- call police
# sooner rather than risk it.
POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE = 35.0
# There used to be two laxer reasons as well -- boxed in (Surrounded) and "a
# live boss", both below 60% health -- and they are gone (user: "A AI está a
# depender muito da chamada da polícia!"). The boss one fired in *every*
# scored round-1 fight: 8 of 8 on the baseline batch, after the second hit,
# since two of Antonio's 20-damage kicks leave exactly 50%. The special is
# the life's one panic button, and the two fights it was being spent on have
# plans that never need it (souther.py, antonio.py): a crowd is answered with
# a hold, and a boss with the hold loop.

# Pepper's throw envelope: beyond melee, inside the can's arc. Unmeasured;
# the knife's old numbers, kept for the can alone (``could_throw_pepper``).
KNIFE_RANGE_X = 90
KNIFE_RANGE_Y = 16
KNIFE_MELEE_X = 40
PEPPER_SPRAY_TYPE = 0x0C
# The knife's throw (``$3084``/``$21E6``): it happens only while nothing at all
# stands in the knife's cone (``PlayableCharacter.knife_cone_occupied``), so
# every target on a lane under 12 px off is 144 px out or more. It leaves the
# hand 48 px out and flies level at 16 px an update until it meets a body, so
# the reach is the screen; the lane it can meet a body on is kept to the
# punch box's +-8 (the knife's own lane extent is unmeasured).
KNIFE_THROW_LANE_Y = 8
KNIFE_THROW_MIN_X = 48

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
# A held bat/pipe swing ($48) connects near its peak, not in the hand. The
# weapon is its own object, and its origin runs from the hand (w_x-p_x = 6)
# out to the peak: 36px for Axel (weapons-range-and-damage.md §5), 53px for
# Blaze (measured on round 1's booths with both weapons; Adam unmeasured, so
# the longer one). Its box reaches about 18px back from there: Blaze broke a
# type-$11 booth from 19px, and swung 93 times from 17px without touching
# it (booth box ±16) -- the actor stood still until the round clock took a
# life. So a prop nearer than the peak, less that back reach, less the prop's
# own extent past its origin, is *under* the swing. See
# ``breakable_strike_inner_x``.
MELEE_WEAPON_SWING_PEAK_X: dict[int, int] = {0: 36, 2: 53}
DEFAULT_MELEE_WEAPON_SWING_PEAK_X = 53
MELEE_WEAPON_SWING_BACK_X = 18


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


def _targets_in_reach(
    context: Context, actor: PlayableCharacter, band, verb_cls, *, strike: bool = True
) -> set[str]:
    """Live enemies ``verb_cls`` would land on from here, right now.

    A strike (``strike=True``: the punch, the weapon's move, the rear chord,
    the jump kick) must land under every timing the target can take --
    stopping where it stands, or keeping its velocity until the hit arms --
    and never on a body that cannot be struck (``reach.strike_lands``: the
    no-whiff rule). A walk-in (``GrabEnemy``, ``strike=False``) keeps the
    older, additive test over the move's timeline (``reach.connects``): its
    arrival is contact, and an early one is only more walking. Shared by every
    ``could_*`` that asks "can this move reach that enemy" so the band is
    computed identically wherever it is asked.
    """

    test = reach.strike_lands if strike else reach.connects
    return {
        enemy.slot
        for enemy in reach.live_enemies(context)
        if test(band, actor, enemy, kinematics.connect_frames(verb_cls, actor, enemy))
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

    Never at Jack, armed or not: ``EngageJack`` owns him (``jack.py``), and
    its lookahead is where a strike on him is timed -- the punch, and armed
    the weapon's own move, which lands through his juggle because a live
    strike box meets an axe before the axe meets the actor. A strike thrown
    blind is a trade with the juggle -- the baseline lost 11 hits of 13 to it
    -- and its ``+$34`` turns the walk-in's grab contact into a hit.

    Every strike here passes the no-whiff rule (``reach.strike_lands``): the
    band holds where the target stands and where it walks to before the hit
    arms, and the body can be struck at all (not down on the floor).
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
        for target_slot in _targets_in_reach(context, actor, reach.melee_strike_would_connect, Punch):
            target = find(context, Enemy, slot=target_slot)
            # Jack is taken in a hold from his back or out of his axes' way
            # (jack.py); EngageJack owns him.
            if isinstance(target, Jack):
                continue
            # Antonio is taken in a hold, never struck: a strike sets the
            # actor's +$34 and turns the grab contact into a hit, and standing
            # still to throw it is his own $16EAE kick window. EngageAntonio
            # owns him (antonio.py).
            if isinstance(target, Antonio):
                continue
            # Souther is taken in a hold, never struck -- bare-handed or with
            # a weapon. A strike makes the actor's own +$34 non-zero, so the
            # very contact that would have been the grab ($AAA0's code 3) is
            # a hit instead -- and the hitstun it buys ($163D0) is a state
            # his collision is not even processed in, so it cannot be
            # grabbed from. EngageSouther owns him (souther.py).
            if isinstance(target, Souther):
                continue
            # Bongo too: the hold is the plan against him (bongo.py), and a
            # strike turns the walk-in's grab contact into a hit whose hitstun
            # he gets up from straight into a wind-up. EngageBongo owns him.
            if isinstance(target, Bongo):
                continue
            # Abadede neither (abadede.py): a strike on him is 1 point and a
            # shake he backs off from, and a strike's +$34 turns the walk-in's
            # grab contact into that. The one punch worth throwing -- into his
            # run, when nothing else escapes it -- is EngageAbadede's.
            if isinstance(target, Abadede):
                continue
            # The twins are fought with the rear attack alone, from the edge
            # with the actor's back to them (twins_plan.py); a punch thrown at
            # one turns the actor to face it -- the grab twin's jump-in
            # ($15C72). EngageTwins owns them.
            if isinstance(target, Onihime):
                continue
            # Mr. X neither: the hold loop is the plan (mr_x_plan.py), and a
            # strike turns the walk-in's grab contact into 1 point and a
            # retreat. The punches worth throwing are EngageMrX's own.
            if isinstance(target, MrX) or is_office_helper(context, target):
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
        for target_slot in _targets_in_reach(context, actor, reach.in_rear_band, RearAttack):
            if isinstance(
                find(context, Enemy, slot=target_slot), (Souther, Antonio, Bongo, Abadede, Jack, Onihime, MrX)
            ) or is_office_helper(context, find(context, Enemy, slot=target_slot)):
                # The chord is a strike like any other: it turns the grab
                # contact into a hit. Each boss's engage owns him, and
                # EngageJack owns Jack.
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

    Antonio and Souther are not grabbed through here at all: each is taken by
    his engage's own walk-in (``EngageAntonio``, ``EngageSouther``), armed or
    not, since ``$AAA0`` never reads the weapon.
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
        in_reach = _targets_in_reach(context, actor, reach.grab_would_connect, GrabEnemy, strike=False)
        threatening = reach.incoming_melee_targets(context, actor)
        on_screen = reach.on_screen_enemies(context)
        for enemy in on_screen:
            if enemy.slot not in in_reach:
                continue
            if isinstance(enemy, (Souther, Antonio, Bongo, Abadede, Jack, Onihime, MrX)) or is_office_helper(context, enemy):
                # Each engage walks into him itself, at the moment its plan
                # picks (EngageSouther, EngageAntonio, EngageBongo,
                # EngageAbadede, EngageJack); EngageTwins never takes a hold.
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

    **What is offered depends on how long the actor has**, in the game's own
    frames (user: "a IA deve fazer supplex ou atirar o inimigo se ele estiver
    para atacar na IA... calcula exatamente o tempo que leva a fazer cada
    animação para prever o futuro e decide com base nisso"). Every hold move
    is an animation lock that ignores fresh edges for its whole length, so
    starting one is a commitment, and the lengths are measured rather than
    guessed (``tools/hold_timing_diag.py``, a lockstep host stepped one frame
    at a time; the numbers live in ``kinematics.HOLD_*_FRAMES``):

    - another knee costs 17-18 frames;
    - finishing with a suplex from a *front* hold costs the crossover plus
      the suplex, about 115;
    - finishing with a throw costs 41-46, and throws the body at whatever the
      actor's back is turned to.

    So: with nothing coming, milk knees for
    ``kinematics.hold_knee_budget_frames`` and finish with the suplex. With
    something arriving sooner than a knee takes, do not start one -- throw
    instead, which is the only ending that fits. In between, the knee is
    still safe but the suplex chain is not, so the finisher on offer becomes
    the throw. From a back hold the suplex is the only finisher there is, and
    is offered regardless.

    Confirmed live with the waves alive (``tools/hold_threat_diag.py``): over
    two runs, every one of the eight hold decisions taken with something on
    the clock chose the throw, no knee was ever started under one, and the
    grace observed ran 5-12 frames -- all of it under a knee's 17-18.
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

        if actor.is_holding_player:
            # The body in hand is the partner: walking into the other player
            # takes this same hold ($4478's grab contact, then $3266), and
            # every move below would land on them. The reported case was
            # FlipHold then Supplex, aimed by the nearest-enemy fallback at a
            # bystander and delivered by the ROM to the partner. Letting go
            # is the only move, and it presses nothing but back.
            verbs.add(
                ReleasePartner(actor_slot=actor.slot, target_slot=actor.held_enemy_slot)
            )
            continue

        # A held Souther or Antonio runs the same loop: knee, knee, release,
        # walk back in. souther.hold_step reads the ROM's knee chain and
        # crossover flag -- the holding player's own bytes, which is why it
        # is antonio.hold_step as well -- and returns the one input that
        # keeps him in the actor's hands.
        held = reach.held_enemy(actor, enemies)
        if isinstance(held, Bongo) and base == 0x60:
            # Round 4 keeps a grunt coming through the whole fight (user: "não
            # se focar nesse inimigo, mas prevenir ataques iminentes"). A
            # strike from behind that lands before a knee could finish is
            # answered the way any hold answers it here: throw the body in hand
            # back into it (B+back). The one measured live came the other way
            # -- a type-$22 punch from in front, over the held Bongo, 8 points
            # mid-knee -- which no hold move answers (the throw goes backward
            # and locks the actor 41-46 frames), so it is left alone. Bongo
            # only -- Souther's and Antonio's rounds are swept clean and their
            # loops were measured without it.
            grace = reach.frames_until_any_melee_lands(
                actor, enemies, ignore_slots=frozenset({held.slot})
            )
            if (
                grace is not None
                and grace < kinematics.hold_knee_frames(actor.character_id)
                and reach.rear_threats(actor, enemies)
            ):
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
                continue

        def crossover_lands_under_a_press(body_in_hand: Enemy) -> bool:
            # The crossover carries the actor over the body in hand to the
            # mirror of where it stands, and the hold keeps it there: a live
            # press over that ground sets itself off and comes down on the
            # actor still locked in the hold (press.lands_in_reach). Where it
            # would, the hold keeps to B -- a knee, or in a back hold the
            # suplex -- and the actor stays where it is.
            landing = nav.body_rect(actor).moved_by(2 * (body_in_hand.world_x - actor.world_x), 0)
            return press_model.lands_in_reach(context, landing)

        if isinstance(held, Jack):
            # Jack's loop (jack.hold_step): in a back hold, wait out his axes
            # still in the air -- they point away from a holder behind him and
            # drop at the end of their arcs; out of a front hold's way of them,
            # cross over. Then knee, knee, cross over, suplex -- or, facing a
            # camera bound, the B+back throw that lands him behind the actor.
            step = jack_plan.hold_step(
                actor, held, find_all(context, Projectile), camera=find(context, CameraRange)
            )
            if step is souther_plan.HoldStep.CROSS and crossover_lands_under_a_press(held):
                step = souther_plan.HoldStep.KNEE
            if step is souther_plan.HoldStep.KNEE:
                grace = reach.frames_until_any_melee_lands(
                    actor, enemies, ignore_slots=frozenset({held.slot})
                )
                if grace is not None and grace < kinematics.hold_knee_frames(actor.character_id):
                    # Another enemy's blow lands before a knee could finish:
                    # the throw, as for any held grunt below.
                    verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
                else:
                    verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.RELEASE:
                verbs.add(ReleaseGrab(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.CROSS:
                verbs.add(FlipHold(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.SUPLEX:
                verbs.add(Supplex(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.THROW:
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
            continue
        if isinstance(held, MrX):
            # Mr. X's loop (mr_x_plan.hold_step): knee, knee, release, each on
            # the one substate of his hold that reads the holder's +$7D, and
            # the walk straight back in re-grabs him on the retreat's first
            # update. A Garcia of his whose blow lands from behind before a
            # knee finishes gets him thrown back into it (B+back), as for
            # Bongo's grunt; one from in front, over him, no hold move answers.
            threat = _office_threat(context, actor) if base == 0x60 else None
            if threat is not None and threat[0] < mr_x_plan.HOLD_KNEE_SAFE_UPDATES:
                # A Garcia's blow (garcia.py plays his approach and trigger)
                # lands before a knee, the release after it and a step could
                # all be spent: no knee -- let go now, and the engage has the
                # actor free to punch the Garcia first or step off his jab.
                # Not the throw, from either side: it locks the holder 41-46
                # frames, and his flight hops 48 px at its apex ($13356), over
                # a Garcia close behind.
                verbs.add(ReleaseToRegrab(actor_slot=actor.slot, target_slot=held.slot))
                continue
            step = mr_x_plan.hold_step(
                action_base=base,
                knees_in_chain=actor.knees_in_chain,
                primary=held.primary_state,
                substate=held.substate,
                health=held.health if held.health is not None else 0,
            )
            if step == "knee":
                verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
            elif step == "release":
                verbs.add(ReleaseToRegrab(actor_slot=actor.slot, target_slot=held.slot))
            elif step == "suplex":
                verbs.add(Supplex(actor_slot=actor.slot, target_slot=held.slot))
            continue
        if isinstance(held, (Souther, Antonio, Bongo, Abadede)):
            # Abadede's loop is the same three moves, each pressed on an
            # update his hold reads the holder's +$7D (abadede.hold_step).
            if isinstance(held, Abadede):
                step = abadede_plan.hold_step(actor, held)
            else:
                step = souther_plan.hold_step(actor, held)
            if step is souther_plan.HoldStep.CROSS and crossover_lands_under_a_press(held):
                step = souther_plan.HoldStep.KNEE
            if step is souther_plan.HoldStep.KNEE:
                verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.RELEASE:
                verbs.add(ReleaseToRegrab(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.CROSS:
                verbs.add(FlipHold(actor_slot=actor.slot, target_slot=held.slot))
            elif step is souther_plan.HoldStep.SUPLEX:
                verbs.add(Supplex(actor_slot=actor.slot, target_slot=held.slot))
            continue

        if base == 0x60 and is_office_helper(context, held) and live_mr_x(context):
            # One of Mr. X's Garcias in hand while he lives
            # (mr_x_plan.garcia_hold_step): the throw (B+back) when nothing
            # -- his lunge, the other Garcia, a bullet -- lands on the holder
            # through its lock: it lays this one down far off and knocks down
            # whatever stands behind the actor, Mr. X included ($AA34 tests
            # the thrown bodies at $FFFB24). Else a knee if one fits, else
            # let go: measured, a throw started with him walking in was his
            # lunge, 34, three times in one fight.
            sims = office_sims(context, actor, exclude=held.slot)
            step = mr_x_plan.garcia_hold_step(*sims) if sims is not None else "knee"
            if step == "throw":
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
            elif step == "knee":
                verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
            else:
                verbs.add(ReleaseGrab(actor_slot=actor.slot, target_slot=held.slot))
            continue
        if base == 0x60 and is_office_helper(context, held):
            # The office's first waves: this hold is the kill -- knees while no
            # other Garcia's blow lands sooner than one (garcia.py, not the
            # generic velocity clock, which does not see his approach), else
            # the throw.
            threat = _office_threat(context, actor, exclude=held.slot)
            if threat is not None and threat[0] <= mr_x_plan.KNEE_UPDATES + 2:
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=held.slot))
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

        # How long the actor has before anything *else* on screen can hit it,
        # in the same 60 Hz frames the hold moves are measured in. The body in
        # hand is excluded: it is not a threat while held.
        grace = reach.frames_until_any_melee_lands(
            actor, enemies, ignore_slots=frozenset({target_slot})
        )
        knee_frames = kinematics.hold_knee_frames(actor.character_id)
        suplex_frames = kinematics.hold_finisher_frames(
            actor.character_id, from_back_hold=False
        )

        if base == 0x66:
            # Confirmed back hold → B is suplex, and it is the only finisher
            # reachable from here, threat or no threat.
            verbs.add(Supplex(actor_slot=actor.slot, target_slot=target_slot))
            continue

        if base == 0x60:
            if grace is not None and grace < knee_frames:
                # Not enough time left for another knee, so do not start one:
                # the knee is an animation lock that ignores every fresh edge
                # for its whole length, and being inside one when the blow
                # lands is the worst version of this situation. End the hold
                # instead, with the only finisher that fits -- the throw is
                # 41-46 frames against the flip-and-suplex chain's ~115, and
                # it puts the body between the actor and whatever is arriving.
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
                continue
            # With today's numbers only the branch above can fire when there
            # is a threat at all: ``reach.CLOSING_ENEMY_THREAT_FRAMES`` is 12
            # -- how far a constant velocity is trusted, past which the answer
            # is "not coming" -- and a knee is 17-18, so every *visible*
            # threat is by definition too soon for one. The guard below is
            # still written as a comparison rather than folded away, because
            # it is the frame counts that decide it: widen the horizon and a
            # knee becomes available again inside it, which is the right
            # answer rather than a regression. ``test_stability`` pins the
            # relationship so a change to either number is visible.
            has_time_to_suplex = grace is None or grace >= suplex_frames
            if rear:
                # Throw the held body into the rear threat (B+back).
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
            else:
                # Standard: knee damage, or flip for a suplex finish.
                verbs.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
            if has_time_to_suplex and not (
                nearest is not None and crossover_lands_under_a_press(nearest)
            ):
                verbs.add(FlipHold(actor_slot=actor.slot, target_slot=target_slot))
            elif not rear:
                # There is time for another knee but not for the suplex chain,
                # so the hold still needs an ending that fits in the window.
                verbs.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
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
            if isinstance(enemy, (Souther, Antonio, Bongo, Abadede, Jack, Onihime, MrX)) or is_office_helper(context, enemy):
                # EngageSouther / EngageAntonio / EngageBongo / EngageAbadede /
                # EngageJack / EngageTwins own the whole approach to them,
                # armed or not.
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
            if isinstance(enemy, (Souther, Antonio, Bongo, Abadede, Onihime, MrX)) or is_office_helper(context, enemy):
                # Their attacks are their engage's business: Souther's claw
                # by souther.plan_engage's lane escape, Antonio's kick,
                # Bongo's flame and Abadede's run by their plan_engage's
                # lookahead.
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
        live_jacks = {jack.slot for jack in find_all(context, Jack)}
        for projectile in find_all(context, Projectile):
            if reach.jack_still_juggling(projectile, context):
                continue
            if projectile.type_id == jack_plan.AXE_TYPE and projectile.owner_slot in live_jacks:
                # A live Jack's axes are EngageJack's: jack.plan_engage plays
                # every one of them forward, thrown ones included, and ranks
                # itself up while one is out at the actor.
                continue
            if reach.antonio_still_holding_boomerang(projectile, context):
                continue
            if reach.is_souther_claw(projectile):
                continue
            if projectile.type_id == bongo_plan.FLAME_TYPE:
                # It rides him ($178D0): no flight of its own to step off, and
                # bongo.plan_engage already plays it forward with him.
                continue
            if projectile.type_id == mr_x_model.BULLET_TYPE and live_mr_x(context):
                # Mr. X's bullets are EngageMrX's: mr_x_plan.plan plays every
                # one forward, and the ones he is about to fire.
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


# How close to CameraRange's own edge -- the ROM's $43AA walk clamp,
# camera_x+$20..+$120, not the visible CRT reach.SCREEN_STRIP_X widens it to
# for that separate question -- the actor must already be before
# WalkToScreenCenter considers could_walk_to_near_enemy's off-screen
# fallback genuinely stalled rather than merely still closing. Mirrors
# execute.MOVE_DEADBAND_X, the deadband execute._clamp_mask_to_camera
# releases the walk hold at: inside that margin the executor's own camera
# clamp already refuses to advance the fallback's straight-line aim toward
# an off-screen target, and navigation.world_rect (bounded to the camera
# plus navigation.WORLD_MARGIN_X -- "planning across all of that would
# route around things that are not on screen") gives the router no further
# lattice position either. That is the concrete stuck-in-a-corner bug this
# verb exists to answer (user, in Portuguese: "a IA fica presa a um canto
# do ecrã a tentar chegar a inimigos que estão fora do campo visível no
# ecrã").
PINNED_AT_CAMERA_EDGE_MARGIN = 5


def _pinned_at_camera_edge(camera: CameraRange, actor_world_x: int, direction: str) -> bool:
    """Is the actor already at the walk clamp's own edge in ``direction``?

    ``camera.left``/``camera.right`` are exactly the bound ``reach.
    in_camera`` answers "may the actor stand there" with -- the correct use
    of ``CameraRange`` here, unlike the *visible screen* question
    ``could_walk_to_screen_center``'s own target asks instead (see that
    function and ``WalkToScreenCenter``'s docstring for why the two do not
    conflict). See ``PINNED_AT_CAMERA_EDGE_MARGIN`` for the threshold.
    """

    if direction == "right":
        return actor_world_x >= camera.right - PINNED_AT_CAMERA_EDGE_MARGIN
    if direction == "left":
        return actor_world_x <= camera.left + PINNED_AT_CAMERA_EDGE_MARGIN
    return False


def _actor_pinned_for_screen_center(context: Context, actor: PlayableCharacter) -> bool:
    """Single owner of WalkToScreenCenter's whole production condition, so
    ``could_walk_to_screen_center`` (production) and ``priority.
    _emergency_walk_to_near_enemy``'s pinned ceiling on the stalled fallback
    (scoring) can never disagree about it -- the same pattern
    ``_advance_blocking_enemies`` already established for WalkToAdvanceStage.

    True only while every one of these holds: a ``Stage`` with a lateral
    direction and a ``CameraRange`` both exist; nothing is in ``reach.
    on_screen_enemies`` (the ordinary, on-screen approach is not what is
    stuck, and every combat verb is untouched by this check); a live enemy
    still waits ahead in the stage's own scroll direction -- exactly
    ``could_walk_to_near_enemy``'s own off-screen fallback target; and the
    actor already sits at that fallback's own dead end
    (``_pinned_at_camera_edge``).
    """

    stage = find(context, Stage)
    camera = find(context, CameraRange)
    if stage is None or stage.direction not in ("left", "right") or camera is None:
        return False
    if reach.on_screen_enemies(context):
        return False
    if not any(
        _ahead_in_stage_direction(actor.world_x, enemy.world_x, stage.direction)
        for enemy in reach.live_enemies(context)
    ):
        return False
    return _pinned_at_camera_edge(camera, actor.world_x, stage.direction)


def could_walk_to_screen_center(context: Context) -> Context:
    """Walk toward the visible screen's centre to call an off-screen enemy
    into view, instead of standing pinned against the camera edge failing to
    reach it (user, in Portuguese: "a IA nesse caso deve-se andar para o
    centro do ecrã para os 'chamar', ter um comportamento mais humano").

    See ``WalkToScreenCenter``'s own docstring for the stuck-in-a-corner
    mechanism this answers. Gated entirely by
    ``_actor_pinned_for_screen_center`` -- see that function for why each of
    its conditions is necessary; in particular, never while any enemy is
    genuinely on screen, so this can only ever compete with the *same*
    stalled ``WalkToNearEnemy`` candidate for the tick, never with the
    ordinary on-screen approach or any combat verb (per the user's own "não
    dês muita prioridade, atacar o inimigo em caso de perigo é mais
    imperativo").
    """

    verbs: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if not _actor_pinned_for_screen_center(context, actor):
            continue
        verbs.add(WalkToScreenCenter(actor_slot=actor.slot))
    return verbs


def could_call_police(context: Context) -> Context:
    verbs: set[Token] = set()
    if find(context, DebugNoPolice) is not None:
        # The harness's --no-police (user: "just don't test with the police on").
        return verbs
    if live_twins(context) or live_mr_x(context):
        # Never against the twins, not even as the panic button (user: "Do
        # not call the police ... must not be used as fallback strategies"),
        # nor Mr. X, fought the same way ("fazer o mesmo tipo de
        # optimização").
        return verbs
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
    """Only when about to die: the special is the last resort, not a plan.

    User: "A AI está a depender muito da chamada da polícia!". The two laxer
    reasons this used to add -- boxed in, and any live boss, both under 60%
    health -- made it a routine move: the boss one fired in every one of the
    eight baseline round-1 fights, as soon as the second kick left the actor
    at 50%. What is left is the panic threshold (``POLICE_HEALTH_PERCENT_
    THRESHOLD``, or the wider ``_LAST_LIFE`` one when a KO means a continue
    screen), still with at least one live enemy to sweep.

    Against Souther and Antonio exactly as anywhere else (user: "The police
    is allowed for Souther/Antonio, just don't test with the police on"): a
    fight is *scored* with the harness's ``DebugNoPolice``, which removes the
    verb outright in ``could_call_police``, so a measured fight never leans on
    it. Their hold loops never need it -- 4 damage every ~55 frames against a
    call that puts the caller in action ``$3`` for the whole ``$16AEC`` delay
    -- which is why it is only ever the panic button there.
    """

    if not _has_live_enemy(context):
        return False
    threshold = (
        POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE
        if actor.lives <= 1
        else POLICE_HEALTH_PERCENT_THRESHOLD
    )
    return actor.health_percent < threshold


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
      in lane, inside the kick's free-flight range, past punch outer),
      never at Antonio (``EngageAntonio`` owns him), the "never launch into
      a committed attack" gate, and
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
        if 0x20 <= (actor.action_state & 0xFE) <= 0x24 or (actor.action_state & 0xFE) in (0x4A, 0x4C, 0x4E):
            # The rear attack ($322A), not a jump: Adam's is a hop ($22 ->
            # $24; armed $4C -> $4E), airborne for 14 updates, and a B pressed
            # in it is no kick
            # -- measured live against the twins, the airborne follow-through
            # below pressed at them through 135 ticks of his chords.
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
        if not actor.is_airborne:
            # Antonio is taken in a hold, never hopped at. His kick box sits
            # at head height on its long frames (z -50..-32, 12..84 px out),
            # so a flight meets it rather than clearing it -- every hit the
            # hop-based plan took landed with the actor in the air -- and his
            # gate reads a jump's own +$1C as walking in. EngageAntonio owns
            # him; a flight already in the air still finishes below.
            for antonio in find_all(context, Antonio):
                target_slots.discard(antonio.slot)
            # Bongo neither: the flame rides at head height (z -78..-32)
            # ahead of him, which is where a flight meets it, and a kick is a
            # strike that turns his grab contact into a hit. EngageBongo.
            for bongo in find_all(context, Bongo):
                target_slots.discard(bongo.slot)
            # Abadede neither: a kick knocks him down for 2 points and puts a
            # whole charge between the actor and the next hold. EngageAbadede.
            for abadede in find_all(context, Abadede):
                target_slots.discard(abadede.slot)
            # Jack neither: his juggle rides in front of him, where a flight
            # comes down, and most of the baseline's hits on him landed in
            # the air. EngageJack.
            for jack in find_all(context, Jack):
                target_slots.discard(jack.slot)
            # The twins neither: a kick turns the actor at them and leaves it
            # in the air where the grab twin's jump-in lands. EngageTwins.
            for twin in find_all(context, Onihime):
                target_slots.discard(twin.slot)
            # Mr. X neither: a kick is 1-2 points and his retreat, and the
            # landing is where his lunge or a bullet finds a locked actor.
            for mr_x in find_all(context, MrX):
                target_slots.discard(mr_x.slot)
            for helper in office_helpers(context):
                target_slots.discard(helper.slot)
        if actor.is_airborne and not target_slots:
            twins = {twin.slot for twin in find_all(context, Onihime)}
            nearest = min(
                (enemy for enemy in live if enemy.slot not in twins),
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
            if not actor.is_airborne and target_slot in threatening:
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


def could_engage_souther(context: Context) -> Context:
    """Close on Souther for the hold -- the whole approach to him, one verb.

    One candidate per live, on-screen ``Souther`` while the actor is free to
    move (not mid-animation, not held, not holding a body, not airborne).
    ``souther.plan_engage`` decides where the actor stands and when it walks
    in; the hold is the contact result of that walk, and the loop that follows
    is ``could_hold_actions``'.

    Armed or not: ``$AAA0``'s grab code never looks at the carried weapon (it
    wants a walking attack box, ``+$34`` clear, ``+$4C`` clear and 8 px of
    elevation), and ``loc_235A`` releases an armed holder into the armed walk
    ``$30``, so the whole loop runs with a weapon in hand. Handing an armed
    actor to the generic approach instead walked it down his lane inside the
    commit band -- the one hit in the validation batch.
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
        for enemy in reach.on_screen_enemies(context):
            if isinstance(enemy, Souther):
                verbs.add(EngageSouther(actor_slot=actor.slot, target_slot=enemy.slot))
    return verbs


def could_engage_antonio(context: Context) -> Context:
    """Close on Antonio for the hold -- the whole fight against him, one verb.

    One candidate per live ``Antonio`` while the actor is free to move (not
    mid-animation, not held, not holding a body, not airborne), armed or not
    for the same reason as ``could_engage_souther``: ``$AAA0``'s grab never
    reads the carried weapon, and ``loc_235A`` releases an armed holder into
    the armed walk. ``antonio.plan_engage`` picks the stick every tick from a
    lookahead over his own AI; the hold is the contact result of that walk,
    and the loop that follows is ``could_hold_actions``'.

    Not limited to the visible screen or the actor's own lane band, unlike
    ``live_enemies``' users: he fights from lanes the actor cannot stand in
    (``$17AB8`` clamps him to ``$00``, the player to ``$02``) and walks back
    on from off-camera (tactical 9), and both are exactly when the actor
    should already be taking its position rather than walking off down the
    street -- which is what the old approach did for 21% of a fight.
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
            verbs.add(EngageAntonio(actor_slot=actor.slot, target_slot=antonio.slot))
    return verbs


def could_engage_bongo(context: Context) -> Context:
    """Take a hold on Bongo -- the whole fight against him, one verb.

    One candidate per live ``Bongo`` while the actor is free to move (not
    mid-animation, not held, not holding a body, not airborne), armed or not
    for ``could_engage_souther``'s reason: ``$AAA0``'s grab never reads the
    carried weapon. ``bongo.plan_engage`` picks the stick every tick from a
    lookahead over his AI and his flame; the hold is the contact result of
    that walk, and the loop that follows is ``could_hold_actions``'.

    Not limited to the visible screen or the lane band either: his charge
    runs him 48 px past the camera's edge ($17744 lets him stand there), and
    the next one is decided by where the actor stands while he turns and
    walks back in.
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
        for bongo in find_all(context, Bongo):
            if bongo.is_defeated:
                continue
            verbs.add(EngageBongo(actor_slot=actor.slot, target_slot=bongo.slot))
    return verbs


def could_engage_abadede(context: Context) -> Context:
    """Take a hold on Abadede -- the whole fight against him, one verb.

    One candidate per live ``Abadede`` while the actor is free to move (not
    mid-animation, not held, not holding a body, not airborne), armed or not:
    ``$AAA0``'s grab never reads the carried weapon (armed, the plan only
    loses its punch). ``abadede.plan_engage`` picks the stick every tick from
    a lookahead over his AI; the hold is the contact result of that walk, and
    the loop that follows is ``could_hold_actions``'.

    Not limited to the visible screen: his run carries him to its edges, and
    the next one is decided by where the actor stands while he backs off.
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
        for abadede in find_all(context, Abadede):
            # His lethal tests branch `bgt`: 0 is dead too, and he is on his
            # way to $0C (the death) from there.
            if (
                abadede.is_defeated
                or abadede_plan.signed_health(abadede) <= 0
                or abadede.primary_state == abadede_plan.PRIMARY_DYING
            ):
                continue
            verbs.add(EngageAbadede(actor_slot=actor.slot, target_slot=abadede.slot))
    return verbs


def could_engage_twins(context: Context) -> Context:
    """Fight Onihime and Yasha -- the whole fight against both, one verb.

    One candidate while any live twin exists and the actor is free to move
    (not mid-animation -- the rear attack's own frames included --, not held,
    not holding a body, not airborne), armed or not: the armed chord
    (``$4A``) plays the same animation, box and damage as the bare one.
    ``twins_plan.plan`` picks the stick and the B+C press every tick.
    """

    verbs: set[Token] = set()
    twins = live_twins(context)
    if not twins:
        return verbs
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.is_airborne:
            continue
        nearest = min(twins, key=lambda t: abs(t.world_x - actor.world_x))
        verbs.add(EngageTwins(actor_slot=actor.slot, target_slot=nearest.slot))
    return verbs


def live_twins(context: Context) -> list[Onihime]:
    """Every twin still fighting: not dead (``$17C36``'s lethal test is
    ``<= 0``, so 0 health is the death blow) and not yet removed."""

    return [
        twin
        for twin in find_all(context, Onihime)
        if not twin.is_defeated and (twin.health or 0) > 0 and twin.primary_state != 0
    ]


def could_engage_mr_x(context: Context) -> Context:
    """Take a hold on Mr. X -- the whole fight against him, one verb.

    One candidate per live ``MrX`` while the actor is free to move (not held,
    not holding a body, not airborne, not mid-animation -- the punch's own
    frames included), armed or not: ``$AAA0``'s grab never reads the weapon.
    ``mr_x_plan.plan`` picks the stick and the punch every tick; the hold loop
    is ``could_hold_actions``'s (``mr_x_plan.hold_step``).

    ``EngageMrX`` only ever names a live Mr. X. With none on the map and his
    helpers up (the office's first waves) the one verb is ``FightMrXOffice``,
    aimed at the nearest helper: the same plan, with nobody else in it.
    """

    verbs: set[Token] = set()
    targets = live_mr_x(context)
    helpers = office_helpers(context)
    if not targets and not helpers:
        return verbs
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.is_airborne:
            continue
        for mr_x in targets:
            verbs.add(EngageMrX(actor_slot=actor.slot, target_slot=mr_x.slot))
        if not targets:
            # The office's first waves: he is not there yet, and the room hands
            # off to him only once they are dead.
            nearest = min(
                helpers,
                key=lambda g: (abs(g.world_x - actor.world_x) + abs(g.world_y - actor.world_y), g.slot),
            )
            verbs.add(FightMrXOffice(actor_slot=actor.slot, target_slot=nearest.slot))
    return verbs


def office_helpers(context: Context) -> list[Garcia]:
    """Mr. X's helpers: the office's type-$22 Garcias, alive, their slot's
    bytes observed (``MapEntity.raw``)."""

    if find(context, MrXOffice) is None:
        return []
    return [
        g for g in find_all(context, Garcia)
        if g.type_id == garcia_model.OFFICE_TYPE and g.raw and not g.is_defeated
    ]


def is_office_helper(context: Context, enemy: Enemy | None) -> bool:
    return (
        isinstance(enemy, Garcia)
        and enemy.type_id == garcia_model.OFFICE_TYPE
        and find(context, MrXOffice) is not None
    )


def office_sims(context: Context, actor, *, exclude: str = ""):
    """The office from the context's raw slots, as ``mr_x_plan`` plays it:
    (the actor, Mr. X or None, his Garcias alive -- less ``exclude`` --, his
    bullets in flight), or None without the actor's bytes or a camera."""

    camera = find(context, CameraRange)
    if camera is None or not getattr(actor, "raw", b""):
        return None
    cam_x = int(camera.left) - mr_x_model.PLAYER_X_MIN_OFFSET
    him = next(iter(live_mr_x(context)), None)
    m = mr_x_model.MrXSim.from_bytes(him.raw, slot=_slot_number(him.slot), cam_x=cam_x) if him else None
    garcias = [
        garcia_model.GarciaSim.from_bytes(g.raw, slot=_slot_number(g.slot), cam_x=cam_x)
        for g in office_helpers(context)
        if g.slot != exclude
    ]
    bullets = [
        mr_x_model.BulletSim.from_bytes(p.raw, slot=_slot_number(p.slot), cam_x=cam_x)
        for p in find_all(context, Projectile)
        if p.type_id == mr_x_model.BULLET_TYPE and p.raw
    ]
    a = mr_x_model.actor_from_bytes(actor.raw, cam_x=cam_x)
    a.punch = None
    return a, m, [g for g in garcias if g.alive], [b for b in bullets if b.state == 1]


def _office_threat(context: Context, actor, *, exclude: str = "") -> tuple[int, bool] | None:
    """``mr_x_plan.garcia_threat`` for a holder: the first update a Garcia of
    the office (``exclude`` the one in hand) lands on it where it stands."""

    camera = find(context, CameraRange)
    if camera is None or not getattr(actor, "raw", b""):
        return None
    cam_x = int(camera.left) - mr_x_model.PLAYER_X_MIN_OFFSET
    sims = [
        garcia_model.GarciaSim.from_bytes(g.raw, slot=_slot_number(g.slot), cam_x=cam_x)
        for g in office_helpers(context)
        if g.slot != exclude
    ]
    if not sims:
        return None
    return mr_x_plan.garcia_threat(mr_x_model.actor_from_bytes(actor.raw, cam_x=cam_x), sims)


def _slot_number(slot: str) -> int:
    return int(slot[3:]) if slot.startswith("obj") and slot[3:].isdigit() else 0


def live_mr_x(context: Context) -> list[MrX]:
    """Mr. X while he fights: out of his entrance's set-up, health above 0
    (``$13F9A`` goes to ``$E``, his death, at 0 or less), not dying."""

    return [
        mr_x
        for mr_x in find_all(context, MrX)
        if not mr_x.is_defeated
        and (mr_x.health or 0) > 0
        and mr_x.primary_state != mr_x_model.PRIMARY_DYING
        and bool(mr_x.raw)
    ]


def could_engage_jack(context: Context) -> Context:
    """Take a hold on Jack from where no axe of his reaches -- one verb per Jack.

    One candidate per live ``Jack`` in the camera while the actor is free to
    move (not mid-animation, not held, not holding a body, not airborne),
    armed or not: ``$AAA0``'s grab never reads the carried weapon.
    ``jack.plan_engage`` picks the stick every tick from a lookahead over him
    and every axe on screen; the hold is the contact result of that walk, and
    the loop that follows is ``could_hold_actions``' (``jack.hold_step``).

    Knocked down or looking about he is still produced for: the plan's WAIT
    stands off behind him, where his next state's axes do not point.
    """

    verbs: set[Token] = set()
    camera = find(context, CameraRange)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.is_airborne:
            continue
        for jack in find_all(context, Jack):
            # Only a negative health word is lethal for an ordinary enemy
            # ($A13A's `bmi`): a Jack at 0 is alive, still throwing, and one
            # knee from dead. Dropping him there left the first live run with
            # no verb at all for 90 s while he killed the actor.
            if jack.is_defeated or jack.state == jack_plan.ST_DYING:
                continue
            if camera is not None and not (
                camera.left - 0x40 <= jack.world_x <= camera.right + 0x40
            ):
                continue
            verbs.add(EngageJack(actor_slot=actor.slot, target_slot=jack.slot))
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
        if actor.held_weapon_type:
            # Armed, B is the weapon's swing, not a punch: it commits the
            # actor for ~26 frames and connects only near its peak, and
            # nothing here times it (kinematics gives it the punch's 3-5
            # frame startup). Measured live (Adam, armed): the swing went out
            # early, whiffed, and the boomerang landed while it recovered.
            # The engage keeps off his throw lane instead (antonio._end_danger).
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


def could_hit_table(context: Context) -> Context:
    """Punch round 8's thrown table (type ``$45``) at the moment it would
    hit the actor.

    Same shape as ``could_hit_antonio_boomerang``, minus the attach filter:
    the table has no "still on its thrower's desk" phase -- object_catalog.
    style_for_object only classifies it a ``Projectile`` once its own +$30
    leaves 0, and by then it is already in real flight
    (reach.TABLE_TYPE_ID). One candidate per in-flight table ``Projectile``
    that is heading at the actor (or already inside the punch box) and whose
    projected position at punch-connect time still sits in that box.
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
        if actor.held_weapon_type:
            # Armed, B is the weapon's swing, not a punch -- see the
            # identical exception in could_hit_antonio_boomerang.
            continue
        for projectile in find_all(context, Projectile):
            if projectile.type_id != reach.TABLE_TYPE_ID:
                continue
            if not reach.projectile_threatens(projectile, actor) and not reach.table_in_punch_band(
                actor, projectile.world_x, projectile.world_y
            ):
                continue
            frames = kinematics.connect_frames(HitTable, actor, projectile)
            if not any(
                reach.table_in_punch_band(
                    actor,
                    round(projectile.world_x + projectile.vel_x * frame),
                    projectile.world_y,
                )
                for frame in frames
            ):
                continue
            verbs.add(HitTable(actor_slot=actor.slot, target_slot=projectile.slot))
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


def _in_throw_envelope(actor: PlayableCharacter, target: Enemy, verb_cls=ThrowPepper) -> bool:
    """In front, and where the thrown weapon meets a body, at this position.

    B is read with the facing the actor already has (a turn on the same
    press is sampled after ``$3084``), so a target behind is a throw the
    other way. The knife flies level to the screen's edge on a lane band of
    ``KNIFE_THROW_LANE_Y``; the pepper can's arc keeps the old envelope."""

    if not reach.enemy_in_front(actor, target):
        return False
    dx = abs(target.world_x - actor.world_x)
    dy = abs(target.world_y - actor.world_y)
    if verb_cls is ThrowKnife:
        return dy <= KNIFE_THROW_LANE_Y and dx >= KNIFE_THROW_MIN_X
    if dy > KNIFE_RANGE_Y:
        return False
    return KNIFE_MELEE_X < dx <= KNIFE_RANGE_X


def knife_would_stab(actor: PlayableCharacter, context: Context | None = None) -> bool:
    """Whether the knife's B, pressed now, is the stab rather than the throw.

    The ROM's own answer is ``knife_cone_occupied``, read off the object
    table. Every object the context knows of is tested as well -- enemies,
    items, props, projectiles, which that scan counts all the same -- so a
    context built without the table still sees the body the knife is aimed
    at. Players are not in the scan (their slots sit before it).
    """

    if actor.knife_cone_occupied:
        return True
    if context is None:
        return False
    for token in context:
        if isinstance(token, PlayableCharacter) or not isinstance(
            token, (Enemy, Pickup, Weapon, Breakable, Projectile)
        ):
            continue
        if knife_cone_contains(
            actor.world_x, actor.world_y, actor.facing_left, token.world_x, token.world_y
        ):
            return True
    return False


def thrown_weapon_would_connect(
    actor: PlayableCharacter, enemy: Enemy, verb_cls, context: Context | None = None
) -> bool:
    """True when B really throws, and the throw meets ``enemy`` whatever it does.

    The no-whiff rule, as for the strikes (``reach.strike_lands``): in the
    envelope now *and* at the interception, and never at a body a throw
    passes through (``reach.can_be_struck``). For the knife, B is a throw only
    while its cone is empty (``knife_would_stab``): with anything in it --
    the target itself 40-90 px out, the old envelope -- B is the stab, into
    the air. The flight crosses the screen, and the candidates are the
    on-screen enemies (``_could_throw_ranged_weapon``).
    """

    if not reach.can_be_struck(enemy):
        return False
    if verb_cls is ThrowKnife:
        if knife_would_stab(actor, context):
            return False
    return _in_throw_envelope(actor, enemy, verb_cls) and _in_throw_envelope(
        actor, thrown_weapon_impact_point(actor, enemy, verb_cls), verb_cls
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
            if thrown_weapon_would_connect(actor, enemy, verb_cls, context):
                verbs.add(verb_cls(actor_slot=actor.slot, target_slot=enemy.slot))
    return verbs


def could_throw_knife(context: Context) -> Context:
    return _could_throw_ranged_weapon(context, weapon_type=0x08, verb_cls=ThrowKnife)


def could_throw_pepper(context: Context) -> Context:
    """Pepper spray is attack-thrown on every B (``$3084`` never stabs with
    it; ``$21E6``, command 3), but its own effective throw range has not been
    separately measured, so this keeps the envelope the knife once used
    (``KNIFE_MELEE_X``/``KNIFE_RANGE_X``/``KNIFE_RANGE_Y``) as the closest
    available evidence, in front of the actor only."""

    return _could_throw_ranged_weapon(context, weapon_type=PEPPER_SPRAY_TYPE, verb_cls=ThrowPepper)


def _a_weapon_would_disarm_the_plan(context: Context) -> bool:
    """Whether picking a weapon up would cost more than it could ever pay.

    True while a live Souther is on screen. The plan against him is the hold
    loop (``souther.py``), which never swings a weapon -- a swing sets
    ``+$34`` and turns the grab contact into a hit -- so a weapon buys nothing
    in this fight, and walking to one is time spent inside his commit band
    rather than in the corridor. Before the hold loop existed the detour was
    measured as pure loss too: ``WalkToWeapon`` took 137 to 223 ticks of five
    of ten scored fights while ``MeleeWeaponAttack`` fired zero times.

    A weapon the actor walks into the arena with is kept: the ROM's grab
    ignores it, and the engage and the hold run the same armed or not.

    Antonio too, now that his fight has the same shape: the engage runs armed
    or not, nothing in it swings, and the detour is a walk that ignores him.
    The same refusal measured no better for him twice before, but that fight
    still had a hop in it, which an armed actor cannot throw; this one has
    none.
    """

    return (
        _souther_is_alive(context)
        or _antonio_is_alive(context)
        or _bongo_is_alive(context)
        or _abadede_is_alive(context)
        or bool(live_twins(context))
        or bool(live_mr_x(context))
        # His office, from the offer on: armed, B is a swing the plan does
        # not time, so the punch that out-reaches a Garcia's jab is gone for
        # the whole fight -- measured, a pipe picked up in the first waves
        # left the actor trading jabs with both Garcias at the street's edge.
        or find(context, MrXOffice) is not None
    )


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
    # The twins too (user: "Do not use recovery items" -- not even as a
    # fallback: a fight that survives by eating is not the plan).
    return _antonio_is_alive(context) or bool(live_twins(context)) or bool(live_mr_x(context))


def _souther_is_alive(context: Context) -> bool:
    return any(not souther.is_defeated for souther in find_all(context, Souther))


def _antonio_is_alive(context: Context) -> bool:
    return any(not antonio.is_defeated for antonio in find_all(context, Antonio))


def _bongo_is_alive(context: Context) -> bool:
    return any(not bongo.is_defeated for bongo in find_all(context, Bongo))


def _abadede_is_alive(context: Context) -> bool:
    return any(not abadede.is_defeated for abadede in find_all(context, Abadede))


def _life_items_refused(context: Context) -> bool:
    """Whether health and extra lives are off the table this tick.

    True while a live Souther is on screen (user: "do not use police attacks
    or life-gaining items"): the fight is scored on the health the round left
    the actor, and a plan that only survives by eating is not a plan.
    """

    return _souther_is_alive(context) or bool(live_twins(context)) or bool(live_mr_x(context))


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
        refuse_life = _life_items_refused(context)
        useful = [
            p
            for p in pickups
            if _pickup_is_useful(actor, p)
            and not (leave_the_food and isinstance(p, HealthPickup))
            and not (refuse_life and isinstance(p, (HealthPickup, LifePickup)))
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


def breakable_strike_inner_x(actor: PlayableCharacter, prop: Breakable) -> int:
    """The nearest the actor may stand to ``prop`` and still hit it with B.

    Unarmed, the punch box's own inner edge (``punch_usable_inner_x``). With a
    bat or pipe, the swing's: its box only exists near the peak
    (``MELEE_WEAPON_SWING_PEAK_X``) and reaches ``MELEE_WEAPON_SWING_BACK_X``
    back from there, so the prop must reach out to meet it -- with its box on
    the far side of its origin, or its wall when the box is unknown. Shared
    by ``in_smash_range`` and by the executor's approach and facing nudge, so
    where the actor stops and whether it swings can never disagree.
    """

    inner = punch_usable_inner_x(actor.character_id)
    if actor.held_weapon_type not in MELEE_WEAPON_TYPES:
        return inner
    peak = MELEE_WEAPON_SWING_PEAK_X.get(actor.character_id, DEFAULT_MELEE_WEAPON_SWING_PEAK_X)
    box = prop.hitbox
    if box is not None and not box.is_degenerate:
        far = box.x1 - prop.world_x if prop.world_x >= actor.world_x else prop.world_x - box.x0
    else:
        far = prop_solids.solid_half_width(prop.type_id)
    return max(inner, peak - MELEE_WEAPON_SWING_BACK_X - far)


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
    life -- and 22 shorter stalls in the same run. With a bat or pipe in hand
    the inner edge is the swing's, further out (``breakable_strike_inner_x``).
    """

    dx = abs(prop.world_x - actor.world_x)
    if not (
        breakable_strike_inner_x(actor, prop) <= dx <= breakable_smash_outer_x(prop)
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
        | could_engage_souther(context)
        | could_engage_antonio(context)
        | could_engage_bongo(context)
        | could_engage_abadede(context)
        | could_engage_jack(context)
        | could_engage_twins(context)
        | could_engage_mr_x(context)
        | could_hit_antonio_boomerang(context)
        | could_hit_table(context)
        | could_walk_to_advance_stage(context)
        | could_walk_to_screen_center(context)
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
