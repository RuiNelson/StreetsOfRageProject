"""``Walk``-branch ``Verb`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Verb


@dataclass(frozen=True, slots=True, kw_only=True)
class Walk(Verb, ABC):
    """A verb to move the actor somewhere or toward something."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToNearEnemy(Walk):
    """Walk to a nearby on-screen enemy to bring it into attack range.

    Produced by ``could_walk_to_near_enemy`` once per reachable enemy when
    at least one on-screen enemy exists and it is not yet actionable for
    this actor (``reach.enemy_actionable``:
    within rear range *and* worth the RearAttack chord there, or within
    punch range and actually in front -- not just inside the punch box's raw
    distance, which ignores facing and would otherwise make this skip a
    behind enemy Punch itself refuses to hit, leaving the actor
    undefended) -- never just the nearest;
    determine_priority_verb picks among the candidates. Falls back to
    every live enemy ahead in the stage's scroll direction when nothing is
    on-screen (e.g. the next wave, tracked on the world map but not yet in
    camera) -- never one behind, so this never walks backward for an
    abandoned off-screen leftover.

    For an enemy at the actor's *back* this verb is the turn-around:
    holding the D-pad toward it is what sets facing, after which
    ``could_punch`` covers it normally (see
    ``execute._walk_to_near_enemy_target``). That makes it the fast,
    reliable alternative to the slow, whiff-prone ``RearAttack`` chord --
    which is why the rear band no longer counts as actionable on its own
    (``reach.rear_attack_is_warranted``) and why the dangerous-enemy
    caution-zone skip below is front-only.

    Raises emergency: Enemy×14, closer scoring higher (distance-scored;
    see priority._emergency_walk_to_near_enemy). An armed ordinary enemy
    adds ``priority._EMERGENCY_ARMED_TARGET`` and a ``Boss`` adds
    ``priority._EMERGENCY_BOSS_TARGET``, so a far armed foe still outranks
    a close unarmed one and a boss outranks both.
    """

    priority: int = 20
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToAdvanceStage(Walk):
    """Walk in the stage's progress direction to scroll it.

    Produced by ``could_walk_to_advance_stage`` when no live Enemy token
    remains anywhere -- except an off-screen enemy already at 0 health,
    which nothing in this pipeline will ever chase down to finish off (see
    ``decide._advance_blocking_enemies``) -- no on-camera Breakable sits
    on the stage path (``decide._advance_blocking_breakables``), and the
    stage has a progress direction.

    Raises emergency: (no blocking Enemy or ahead Breakable)×1.

    Lowest emergency of any verb that still scores: per AI.md, "picking up
    a weapon carries a higher priority than advancing to the next stage"
    -- this is the fallback when nothing more specific applies, and it
    must lose to every other live candidate (including a ScorePickup).
    """

    priority: int = 5
    actor_slot: str
    direction: str  # "left" | "right"


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToScreenCenter(Walk):
    """Walk toward the visible screen's own horizontal centre to draw an
    off-screen enemy into view, rather than stand pinned against the camera
    edge failing to reach it.

    User (in Portuguese): "Por vezes a IA fica presa a um canto do ecrã a
    tentar chegar a inimigos que estão fora do campo visível no ecrã, a IA
    nesse caso deve-se andar para o centro do ecrã para os 'chamar' (ter um
    comportamento mais humano) ... não dês muita prioridade, atacar o
    inimigo em caso de perigo é mais imperativo."

    Produced by ``could_walk_to_screen_center`` once per actor gated on
    ``decide._actor_pinned_for_screen_center``: nothing in ``reach.
    on_screen_enemies`` (the ordinary approach owns any real on-screen
    fight untouched), a live enemy still waits ahead in the stage's own
    scroll direction -- exactly ``could_walk_to_near_enemy``'s own
    off-screen fallback target -- and the actor is already pinned against
    ``CameraRange``'s own walk-clamp edge in that direction. That is the
    point at which ``navigation.world_rect`` (bounded to the camera plus
    ``navigation.WORLD_MARGIN_X``, deliberately: "planning across all of
    that would route around things that are not on screen") and the
    executor's own camera clamp (``execute._clamp_mask_to_camera``) agree
    there is no further lattice position toward that target this tick --
    the stuck-in-a-corner bug reported above.

    The centre is read off ``CameraRange`` -- deliberately, and *not* the
    mistake ``autoplay/CLAUDE.md``'s "The entrance" warns against, where an
    earlier "hold the arena centre" verb misread the walk clamp as the
    visible screen. Here the two midpoints coincide: ``reach.
    in_visible_screen`` widens ``CameraRange`` by ``reach.SCREEN_STRIP_X``
    symmetrically on both sides, so ``(camera.left + camera.right) / 2`` is
    simultaneously the walk clamp's own centre and the visible CRT's, and
    it is the second reading this verb means (``execute.state_machine_
    walk_to_screen_center``).

    Raises emergency: flat, one point above ``WalkToNearEnemy``'s off-screen
    floor -- and that floor is itself capped whenever this verb's own
    condition holds (``priority._EMERGENCY_WALK_TO_NEAR_ENEMY_PINNED_
    CEILING``), so the two never tie and this always wins the exact tick it
    exists for, never before or after. Stays under every pickup, weapon,
    retreat and attack tier, per the user's own "não dês muita prioridade"
    (``priority._EMERGENCY_WALK_TO_SCREEN_CENTER``).
    """

    priority: int = 4
    actor_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToWeapon(Walk):
    """Walk to pick up a free ground weapon that outranks the held one.

    Produced by ``could_walk_to_weapon`` once per weapon
    ``reach.weapon_upgrade_rank`` judges an upgrade -- in camera, still
    usable, and better than what this actor holds -- never just the best
    one; determine_priority_verb picks among the candidates.

    Raises emergency: (weapon_upgrade_rank)×12+rank
    (rank 2..5, so a better upgrade among several outranks a lesser one, and
    every rank clears WalkToNearEnemy's floor(8) outright rather than merely
    tying it -- see priority._emergency_walk_to_weapon).
    """

    priority: int = 22
    actor_slot: str
    target_slot: str  # Weapon.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToPickup(Walk):
    """Walk to (and B-pickup) a free ground consumable.

    Produced by ``could_walk_to_pickup`` once per useful Pickup token in
    camera for the actor -- never just the best one; determine_priority_
    verb picks among the candidates via the already per-target emergency
    tiers below.

    Raises emergency: (HealthPickup when the actor's health is critical)×50,
    HealthPickup×15, LifePickup×12, SpecialPickup×11, ScorePickup×9.

    Priority sits above stage advance and below weapons: a needed health item
    outranks wandering, but a weapon upgrade is usually more durable value
    unless health is critical (emergency ranking handles that case).
    """

    priority: int = 18
    actor_slot: str
    target_slot: str  # Pickup.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class RetreatFromDanger(Walk):
    """Give up ground to a dangerous enemy, when the exchange is one the
    actor cannot currently afford to take.

    Produced by ``could_retreat_from_danger`` once per on-screen enemy
    ``reach.is_incoming_melee`` judges about to land on the actor (a
    dangerous phase, close enough that continuing to approach risks
    arriving right as its hit lands) that is not yet actionable -- not
    really hittable yet -- and **only while ``decide._retreat_is_worth_it``**:
    the actor is hurt (a crowd is answered with a hold, not by backing away
    -- ``reach.grab_reasons``' ``WHILE_SURROUNDED``). Danger alone is deliberately not
    enough, since no enemy can be defeated without standing in the range it
    hits back from. Never just the nearest; determine_priority_verb picks
    among the candidates.
    That same predicate decides which verb owns the enemy: while it holds,
    ``could_walk_to_near_enemy`` stands off; while it does not, that verb
    closes in and this one produces nothing. Exactly one of the two ever
    holds a given enemy, from whichever side it stands on.

    Raises emergency: (reach.is_incoming_melee for this target)×17, closer
    scoring higher (distance-scored; see
    priority._emergency_retreat_from_danger) -- higher than
    WalkToNearEnemy(14) so this wins over still approaching, lower than any
    real attack (the lowest being JumpAttack×18) so attacking always wins
    once actually possible.
    """

    priority: int = 21
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectileSidestep(Walk):
    """Step off an incoming projectile's own lane rather than stand in it.

    Produced by ``could_projectile_sidestep`` once per observed
    ``Projectile`` ``reach.projectile_threatens`` judges approaching, in
    lane, and within the impact window for this actor. Jack's thrown
    axe/torch (object_catalog.py type ``$28``) is the case this was built
    for -- an unarmed punch into the juggle trades hits (see
    ``could_punch``'s Jack exception; a held weapon still swings) and once
    he lets go, the axe/torch itself is a fast
    in-lane projectile with no answer but getting out of its way. While he
    is still juggling it, though, ``reach.jack_still_juggling`` keeps it out
    of consideration entirely -- the weapon's own spin can point its
    velocity straight at the actor without ever being thrown, and this verb
    has nothing to sidestep in that case. The verb still reacts to any other
    ``Projectile`` ``reach.projectile_threatens`` judges a threat, not just
    his.

    Raises emergency: (reach.projectile_threatens for this projectile)×45,
    sooner-to-impact scoring higher, floor 30 (see
    priority._emergency_projectile_sidestep) -- above every ordinary
    approach/retreat tier so the actor clears the lane before the weapon
    lands, below a guaranteed strike on a punishable target (60) and the
    RearAttack/CLEAR_REAR grab escapes, which stay the right answer even
    with a projectile also in flight.
    """

    priority: int = 23
    actor_slot: str
    target_slot: str  # Projectile.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageSouther(Walk):
    """Close on Souther to take a hold, never where his claw can start or land.

    Produced by ``could_engage_souther`` once per live, on-screen ``Souther``
    while the actor is free to move and not already holding a body -- armed
    or not, since ``$AAA0``'s grab never looks at the carried weapon.
    It is the whole approach against him -- the generic walk-in, strike,
    grab and dodge verbs all stand down for him -- and the hold it ends in is
    a contact result of walking into him, not an input
    (``souther.plan_engage`` owns where to stand and when to walk in).

    Raises emergency: a live Souther×62, plus the boss raise (14) -- 76,
    above every strike and grab tier on anything else (a stray grunt's chord
    once locked the actor mid-engage, and that was the one hit taken), below
    CounterGrab/TechRecover and the dialogs; the hold family (64-70) never
    coexists with it.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Souther.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageAntonio(Walk):
    """Take a hold on Antonio without ever standing where his kick lands.

    Produced by ``could_engage_antonio`` once per live ``Antonio`` while the
    actor is free to move and not already holding a body -- armed or not, on
    screen or walking back on. It is the whole fight against him: the strike,
    grab, hop, walk-in and retreat verbs all stand down for him, and the stick
    each tick is ``antonio.plan_engage``'s -- a lookahead over his own AI that
    keeps the move which takes the hold soonest without his kick box ever
    meeting the actor's body.

    Raises emergency: a live Antonio×62, plus the boss raise (14) -- 76, the
    same tier as ``EngageSouther`` and for the same reasons; below the
    incoming-boomerang punch (78), CounterGrab/TechRecover and the dialogs;
    the hold family never coexists with it.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Antonio.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageBongo(Walk):
    """Take a hold on Bongo without ever standing where his flame lands.

    Produced by ``could_engage_bongo`` once per live ``Bongo`` while the actor
    is free to move and not already holding a body -- armed or not, on screen
    or past its edge. It is the whole fight against him: the strike, grab,
    hop, walk-in, retreat and sidestep verbs all stand down for him and his
    flame, and the stick each tick is ``bongo.plan_engage``'s -- a lookahead
    over his own AI and his flame's that keeps the move which takes the hold
    soonest without the flame's box ever meeting the actor's body.

    Raises emergency: a live Bongo×62, plus the boss raise (14) -- 76, the tier
    of ``EngageSouther``/``EngageAntonio``; ×5 instead (19, just under a
    punch) while a grunt's committed strike is about to land
    (``reach.is_incoming_melee``) and his charge is not pressing
    (``bongo.charge_is_pressing``); below CounterGrab/TechRecover and the
    dialogs; the hold family never coexists with it.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Bongo.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageAbadede(Walk):
    """Take a hold on Abadede without ever standing where his run lands.

    Produced by ``could_engage_abadede`` once per live ``Abadede`` while the
    actor is free to move and not already holding a body -- armed or not. It
    is the whole fight against him: the strike, grab, hop, walk-in and
    retreat verbs all stand down for him, and the stick each tick is
    ``abadede.plan_engage``'s -- a lookahead over his own AI that keeps the
    move which takes the hold soonest (17-18 lanes off his run, or walking
    into him while he pauses) without his run's box ever meeting the actor's
    body, and punches into the run only when nothing else escapes it.

    Raises emergency: a live Abadede×62, plus the boss raise (14) -- 76, the
    tier of ``EngageBongo``; ×5 instead (19, just under a punch) while a
    grunt's committed strike is about to land (``reach.is_incoming_melee``)
    and his run is not pressing (``abadede.charge_is_pressing``); below
    CounterGrab/TechRecover and the dialogs; the hold family never coexists
    with it.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Abadede.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageTwins(Walk):
    """Fight Onihime and Yasha from an edge with rear attacks.

    Produced by ``could_engage_twins`` once while any live twin (type ``$58``)
    is on the level and the actor is free to move (not mid-animation, not
    held, not holding a body, not airborne) -- armed or not: the armed chord
    (``$4A``) plays the same animation, box and damage. It is the whole
    fight against them: the strike, grab, hop, walk-in, retreat and rear-chord
    verbs all stand down for the twins, and every tick's stick and B+C press
    are ``twins_plan.plan``'s -- a lookahead over both twins' own AI
    (``twins.py``) that keeps the actor at the edge with its back to them,
    holds or leaves the approach twin's lane, steps off its flying kick, and
    throws the rear attack on the update that lands it.

    Raises emergency: a live twin×62, plus the boss raise (14) -- 76, the tier
    of the other boss engages; below CounterGrab/TechRecover and the dialogs;
    the hold family never coexists with it.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # the nearest live twin's Onihime.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageMrX(Walk):
    """Take a hold on Mr. X -- the gun is walked into, the lunge stepped off.

    Produced by ``could_engage_mr_x`` once per live ``MrX`` (type ``$35``)
    while the actor is free to move (not mid-animation, not held, not holding
    a body, not airborne) -- armed or not: ``$AAA0``'s grab never reads the
    weapon -- and once with no target (``target_slot`` "") while his office's
    first waves are up (``MrXOffice``). It is the whole fight: the strike,
    grab, hop, walk-in, retreat and rear-chord verbs stand down for him and
    his Garcias, and every tick's stick and punch are ``mr_x_plan.plan``'s --
    a lookahead over his own AI, every bullet (``mr_x.py``) and every Garcia
    (``garcia.py``) that keeps the actor $80 or more away when he decides (so
    he goes to the gun), walks into him while his gun has no box out, steps
    off his lunge by the lane, punches a Garcia first when that lands, and
    takes no hold a Garcia's blow reaches before a knee is spent. The hold
    loop after the grab is ``mr_x_plan.hold_step``'s.

    Raises emergency: a live Mr. X×62, plus the boss raise (14) -- 76, the
    tier of the other boss engages; the same 76 in the office's first waves.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # MrX.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class EngageJack(Walk):
    """Take a hold on Jack from where none of his axes reaches.

    Produced by ``could_engage_jack`` once per live ``Jack`` in the camera
    while the actor is free to move and not already holding a body -- armed
    or not. It is the whole fight against him: the strike, grab, hop, walk-in
    and rear-chord verbs all stand down for him, and the stick each tick is
    ``jack.plan_engage``'s -- a lookahead over his state machine and every axe
    of his (juggled, tossed, thrown) that keeps the move which takes a hold
    soonest -- one no axe still in the air can reach -- without any axe box
    ever meeting the actor's body, or, where the actor can punch, the punch
    that stuns him and drops his juggle (thrown in the facing the actor has:
    the plan turns it by walking). In his dodge (``$07``) it waits mid-screen
    in the pocket above his juggle, or steps 88 px behind his walk when he is
    out of reach and cannot come back. His body never strikes; the axes are
    the whole threat.

    Raises emergency: a live Jack×30 less 1 per 40 px, plus the armed raise
    while he juggles; ×72 while an axe of his is out at the actor (a released
    throw coming its way, or one about to be released along its lane); ×5
    instead (just under a punch) while another enemy's committed strike is
    about to land (``reach.is_incoming_melee``) and no axe of his is out;
    below CounterGrab/TechRecover and the dialogs; the hold family never
    coexists with it.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Jack.slot
