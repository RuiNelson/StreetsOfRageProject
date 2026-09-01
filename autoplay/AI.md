# Symbolic AI that Plays Streets of Rage

## Overview

This project introduces an artificial intelligence capable of playing
Streets of Rage autonomously. The AI can be enabled or disabled at will,
independently for player 1, player 2, or both, via a UI control. It is
implemented as a component of the "autoplay" Python application.

The AI is required to be both effective and performant. It is permitted to
read RAM directly to obtain information not otherwise observable, but it is
not permitted to write to RAM; all actions must be issued through the
standard game controller inputs, as a human player would. At present, only
the original control scheme is supported (buttons A, B, and C); support for
the six-button `--altControls` scheme is planned for a future iteration.

## Approach

Because the game's source code has been mapped in considerable detail, it
can be used to inform the AI's predictions of enemy attacks and stage
hazards, as well as its assessment of each character's strengths and
weaknesses. Testing the AI against a running instance of the game is
time-consuming and difficult to debug, and this approach should therefore
be minimized wherever practical.

Substantial effort has already been invested in analysing the game and
documenting the findings as manuscripts under
`StreetsOfRageRecompilation/ai-analysis/` (sibling of this `autoplay/`
tree in the meta-repository). These manuscripts will serve as the primary
reference for the AI's implementation. Analysis of the game will continue
in parallel, refining and correcting the manuscripts as well as the
subroutine labels recorded in `labels.csv`. The call map feature and the
accompanying `call_map.py` tool will likewise be used to develop a clearer
understanding of the game's control flow.

## Data Structures

### Token Hierarchy

The AI system is founded on a single abstract base class, `Token`, from
which two further abstract classes descend: `Information` and `Verb`.
Each of these abstract classes is expected to accumulate numerous
subclasses over the course of implementation.

Tokens are required to contain only the data strictly necessary for their
purpose; there is no constraint on the number of tokens that may be
introduced, including subclasses of subclasses. Generic discriminator
properties, such as `enemy.type`, are to be avoided, as they would
complicate the implementation as the system grows; subclassing is the
preferred mechanism for expressing such distinctions.

**Exception.** When several sibling subclasses share exactly the same
fields, the same production function, and the same scoring formula — that
is, the only difference between them is which constant or branch a
consumer selects, never an `isinstance` check outside a simple
enum-to-value mapping — a discriminator field (an `Enum`) is preferable to
`N` classes whose sole reason to exist is to serve as a dispatch key. One
case in `tokens/` fits this exactly and was merged on that basis:
`MeleeWeaponAttack` (`weapon_type`, replacing `SwingBatOrPipe` /
`StabWithKnifeOrBottle` / `SprayPepper`, which shared every `could_*`,
`_emergency_*` and `state_machine_*` function outright). This exception is
narrow: it does not reopen the door to generic discriminators like
`enemy.type` on `Enemy`, where concrete behaviour (fields, production
conditions, or per-class dispatch) genuinely differs. Subclassing remains
the default for everything else.

Two further cases — `GrabOpportunity` (`reason: GrabReason`) and
`TargetInReach` (`kind: ReachKind`) — were merged onto this same
discriminator-field exception first, then, once every one of their
producers turned out to already delegate its geometry to `reach.py`,
removed as tokens entirely: `GrabReason` survives only as the return type
of `reach.grab_reasons(context, actor, target, enemies) -> frozenset[
GrabReason]`, and `ReachKind` does not survive at all — each of its five
former band questions is now a direct call to the shared `reach.py`
predicate it used to wrap (`reach.punch_would_connect`, `reach.in_rear_
band`, `reach.in_jump_attack_band`, `reach.grab_would_connect`, `reach.
enemy_actionable`). See [Judging without a cache](#judging-without-a-cache)
below for why computing these fresh, on demand, at each of two or three
call sites per tick is preferable to writing them into the context once —
the same reasoning that took eleven of the twelve `Inferred` tokens this
document used to describe down to one (`Surrounded`).

A `Token` must never embed another `Token` by value. Since the context is
a flat unordered collection, any relationship between two tokens — for instance, a
`WalkToNearEnemy` verb naming the enemy it targets must be expressed as a reference to
the related token's identifier, to be resolved by looking it up in the
context, rather than by holding the related token itself.

### `Information`

An `Information` token represents a state of the game, whether directly
observed or inferred through calculation. It is defined as an abstract
class because its subclasses may differ substantially in structure. For
instance, a concrete `Enemy` class encapsulates properties such as position
and health, and may itself be further specialised into descendants such as
`Garcia` (a specific enemy type), which introduce additional properties,
such as the enemy's current behavioural state.

`Information` descendants may represent directly observed evidence, such as
enemies or weapons available for pickup on the floor, as well as the
products of derived calculations. A number of such tokens are concrete
and essential to the AI's decision-making regardless of character or
enemy type; these are described in [Essential Tokens](#essential-tokens),
below.

The class hierarchy established so far is as follows:

- `Character`
  - `PlayableCharacter`
    - `Myself` — the character controlled by the AI.
    - `Partner` — the co-operative partner character.
  - `Enemy`
    - `Garcia` — and other ordinary enemy types.
    - Boss encounters are represented the same way: each boss is its own
      `Enemy` subclass, on the same footing as ordinary enemy types.

`Myself` and `Partner` constitute the two most significant `Information`
descendants. Each encapsulates the corresponding character's position,
health, remaining lives, and related attributes, as well as:

- the identity of the character being played (for example, Axel or
  Blaze), held as a plain attribute rather than expressed through
  subclassing, since playable characters do not otherwise differ in
  token structure;
- the weapon currently held, if any;
- the number of special attacks currently available.

A further `Information` descendant, `Stage`, encapsulates information
concerning the current stage, namely its number and its direction of
progression. In stages 1 through 6, the player must proceed rightward; in
stage 7, progression does not require lateral movement; and in stage 8, the
player must proceed leftward. `Stage` does not encapsulate hazards or
collectable floor items, as these are represented by their own dedicated
tokens.

### `Verb`

Whereas `Information` represents the present state of the game, `Verb`
represents a projected future state. A `Verb` cannot be translated
directly into a control signal; rather, it represents a deliberated and
parametrized intent that precedes any concrete action.

`Verb` comprises two principal abstract branches, `Walk` and `Attack`:

- `Walk` — for example, `WalkToNearEnemy`,
  `WalkToAdvanceStage`, `WalkToWeapon`, and `WalkToPickup`; grabbing a
  lay-down weapon or consumable is a `Walk` descendant.
- `Attack` — for example, `Punch`, `JumpAttack`, `GrabEnemy`, `Supplex`,
  `ThrowKnife`, `RearAttack` (simultaneous B+C rear/escape chord), and
  `CounterGrab` (enemy-held C then B sequence), each parametrized with the
  target or coordinate to which the attack applies where applicable. There
  is no separate `Combo` input; repeated `Punch` contact produces the chain.
  Taking a hold, on the other hand, is its own verb and its own
  *absence* of an input — see [Grabbing an enemy](#grabbing-an-enemy).
  `CallPolice`, which activates the police special attack, is an `Attack`
  descendant. It only fires when health is running out (or the actor is
  surrounded below the laxer health gate), a special remains, **and** at
  least one live enemy is in context.

A third `Verb` branch, `Dialog`, answers game UI prompts rather than
acting in combat: `HandleContinueMenu` (always Yes, initials `AI `) and
`HandleMrXDialog` (always No).

Weapon upgrade ranking follows ROM damage constants
(`StreetsOfRageRecompilation/ai-analysis/items-and-weapons.md`):
**knife 5 > bat/pipe 4 > bottle 3 > pepper 2**. Consumable floor items are
their own `Information` tokens (`HealthPickup`, `LifePickup`,
`SpecialPickup`, `ScorePickup`), not folded into `Weapon`.

As with the `Walk` subclasses, the `Attack` subclasses are expected to be
precisely defined.

### Essential Tokens

The abstract structure described above is populated, in practice, by a
number of concrete `Information` tokens that are not tied to any specific
character or enemy type, but are nonetheless essential to the AI's
decision-making. The most important of these are described below.

**`CameraRange`** encapsulates the rectangle currently framed by the
camera. It is read directly from RAM, and is consulted by most `could_*`
functions to determine which otherwise directly observed tokens —
enemies, weapons, hazards — are actually on screen and may therefore be
acted upon.

**`AnimationInProgress`** is carried by a `PlayableCharacter` whenever that
character's current animation, as observed directly from RAM, has not yet
finished (for example, the startup or recovery frames of an attack). Its
mere presence in the context signals to `generate_verb_tokens`,
described below, that the corresponding character cannot presently act on
a new verb.

**`Projectile`** is a direct observation of a live projectile-kind object in
flight. Whether one *threatens* the actor — heading toward it, in lane,
within the impact window — is answered on demand by `reach.projectile_
threatens(projectile, actor)`, not by a second token; see [Judging without
a cache](#judging-without-a-cache) below for why. Antonio's boomerang
(type `$96`) is withheld by `reach.antonio_still_holding_boomerang` while
it is still attached to him — punching his hand is standing still in front
of him, which is how his kick starts. Souther's claw and afterimage (types
`$98`/`$99`) are withheld *unconditionally* by `reach.is_souther_claw`:
they are animation-synchronized attack objects re-created from his own
position every dash tick, with no flight to intercept, so his own state is
the only honest thing to read.

Antonio's ROM kick gate at `$16EAE` (already satisfied, or committed to
primary state 2, the close-range power kick) is answered by `reach.
antonio_will_kick(antonio, actor)`. Standing still in front of him is one
of the trigger paths — the player's own signature while throwing a ground
combo, and equally the signature of a standing punch. The human answer is
a jump kick to put him in later-boss hitstun (primary `$03`/`$04`,
decoded as `RECOVERY`), then a grab and a suplex. A grounded B is
refused entirely: the first punch stood in the same window as a combo
and lost the ranking contest to the hop (20+boss vs 18+boss), which is
why the fight looked weak. Jump-kicking him is offered inside punch range as well as the usual
"past punch outer" band (~10px on Axel, too thin to fire) -- but only
when the kick would connect (same lane, in front, within free-flight
range). An X-only opener hopped from any lane and kicked empty air.
Off-lane, walking onto his lane is the approach. The hop also wins
the ranking (`priority._EMERGENCY_JUMP_ATTACK_ANTONIO_OPENER` 22).
From inside punch range the hop is in place, so the actor lands where
the grab can connect -- a directed hop from there lands on his far
side, facing away, and the hold never starts.
`DodgeAntonioKick` and the jump-over tier fire only
once the kick or the tactical-`$08` dash is actually locked in. A
predicted window is not a reason to leave hop range. Overlapping him on
X hops in place rather than punching. `HitAntonioBoomerang` punches the
thrown boomerang at punch-connect time when it would hit the actor.

Souther's commit gate at `$15EDA (souther_state1_active_combat)` — the
velocity-selected `$50`/`$58`/`$68` X windows, the `$1C` lane window, and the
`$18` inner abort that means he cannot *begin* the slash from inside 24px at
all — is answered by `reach.souther_will_slash(souther, actor)`. Only once
he is actually committed (primary `$02`) does `DodgeSoutherSlash` fire, and
it is a pure lane step — `$161C6 (souther_state2_claw_dash)` writes only
`+$1C`, so it cannot follow a lane change, and it resolves only with the
target within `$18` of its lane. The step is sized to that `$18` and nothing
wider: by the time it runs the claw is committed, so the commit gate's `$1C`
is no longer the number to clear, and every extra pixel is another tick
before the actor is out of the way.

The approach answers the same gate from the other side, and it is a
*corridor* rather than a dodge: `execute._lane_offset_while_closing` holds a
lane offset wider than `$1C` for the whole walk in, `_lane_release_dx` hands
the lane over at his own `$18` inner abort, and `_souther_pocket_stop_dx`
stops inside it — so the lane gate is unsatisfied while the X gap closes and
the inner abort is unsatisfied once it has, with an overlap rather than a gap
between them (ai-analysis/enemy-ai.md, "The uncommittable corridor").
Deleting it and walking straight down his lane instead was tried and measured
much worse: four to five times as many committed claws, and 3-4 lives a fight
against 1-2. What *had* made the corridor look like a stalemate was four
separate arrival bugs between it and the hold — see `autoplay/CLAUDE.md`,
"The fifth attempt".

`reach.souther_would_punish_jump(actor, context)` is the one predicate
keyed on the actor alone rather than on an actor/target pair, and the
reason is the ROM's own: `$162A4 (souther_flag_target_jump_attack)` watches
the *player's* action state (`$16`/`$17`/`$42`/`$43` — the unarmed and armed
jump attacks) and nothing about who the jump was aimed at, so `$16234
(souther_counter_jump_attack)` answers a hop aimed at an unrelated grunt
exactly as it answers one aimed at him: straight to primary `$02` with the
claw spawned, every distance band and gate bypassed. So the whole of
`could_jump_attack` is refused for that actor whenever a live,
non-punishable Souther is within `$78`-plus-free-flight on X — the exact
opposite of Antonio, whose fight *needs* the hop. Only the launch is
refused; an actor already airborne is committed and still gets a verb.

The predicate is named *punish* rather than *counter* because the counter is
only one of the two ways a jump loses, and conflating them is a mistake this
codebase actually made: the first version gated the refusal on `$16234` being
on his call path and on the ROM's `$12` lane window, and the AI was reported
jumping straight into the claws. Both gates were wrong for the same underlying
reason — they describe *him*, not the flight.

- `$1619E`/`$161C6` skip `$16234` **because he is already attacking**, with the
  type-`$98` claw live. "Not counter-armed" is the most dangerous window, not a
  safe one.
- The `$12` lane window bounds the flight correctly (a `JumpAttack` is
  horizontal) but not Souther, who closes lane at 4px/frame and erases 18px in
  about five of the flight's ~25 frames.

The only Souther worth hopping at is one who cannot act at all, and there a
grab reason of `SOUTHER_ON_PUNISH` outranks the hop anyway — as does
`SOUTHER_WALK_IN`, its everyday counterpart: a live Souther at contact range
is walked into for the hold rather than traded punches with, which is the
whole plan against him. The walk-in is timed out by
`PlayableCharacter.grab_stall_ticks` (`observe.GrabStallTracker`) so a hold
that is not happening hands the tick back to the strike, and the strike's own
hitstun is what `SOUTHER_ON_PUNISH` then grabs from.

**`InContinueMenu`** is observed when this player's object is the type-`$0F`
continue / high-score name-entry UI (the slot is no longer playable).
`HandleContinueMenu` always chooses Yes and types the initials `AI `
(A, I, then Start so the third character stays the cleared-to-zero space).

**`InMrXDialog`** is observed when Mr. X's final offer is live *and* this
player's object `+$59` bit 4 marks the choice UI as active.
`HandleMrXDialog` always answers No (held Down, then a face button).
Accepting writes the bad ending.

"Which of my moves can reach that enemy from here" is answered directly by
`reach.py`'s band predicates, one per move family — `reach.punch_would_
connect` (a forward strike would connect: inside the punch band *and*
actually in front), `reach.in_rear_band` (inside the `$322A` chord's real
reach on the enemy's own side), `reach.in_jump_attack_band` (in front,
beyond punch outer, inside the kick's free-flight range), `reach.grab_
would_connect` (walking in would take a hold) and `reach.enemy_actionable`
(some attack the AI already has would really fire on this enemy now — the
"stop walking, you can already hit it" signal). `decide.py` and
`priority.py` call these directly rather than reading a precomputed
judgment; see [Judging without a cache](#judging-without-a-cache) below.

"From here" is really "from here, when that move arrives": every band
except `enemy_actionable` is judged through `reach.connects`, against the
enemy projected forward by its own move's lead time — see
[Kinematics](#kinematics-attacking-where-the-target-will-be) — so these
answers are predictive rather than reactive. `enemy_actionable` is the
deliberate exception: it is not "would this hit" but "stop walking, you can
already hit it", and a future-tense answer to that halts the approach
while the enemy is still out of range.

`reach.is_incoming_melee(actor, enemy)` is the melee counterpart of
`reach.projectile_threatens`: true for an on-screen enemy in a committed
attack phase, close enough that its hit can actually land on the actor —
or, on the enemy's own current velocity, soon will be. A dangerous phase
alone is not a threat and neither is proximity alone, so this is a
judgment, not a copy of every attacking enemy on screen.

The predictive half exists because not every committed attack has a static
reach to test: Signal's slide (`enemy-ai.md` "Signal's slide is velocity,
not a hitbox") sets its own velocity directly and carries no attack shape
anywhere in its animation set, so `Enemy.attack_ranges` stays empty for it
and a purely instantaneous-position check would never see it coming until
it had already arrived. `reach.enemy_will_close_soon` re-tests the same
caution predicate a short horizon (`reach.CLOSING_ENEMY_THREAT_FRAMES`)
ahead by projecting the enemy's own `grunt_vel_x`/`grunt_vel_y`, and a
stationary enemy projects to itself, so this never promotes anything the
current-position test would not already have caught. `reach.souther_dash_
arrives_soon` is a third path, for the one enemy invisible to both the
other tests: a `Boss` populates neither `attack_ranges` nor `grunt_vel_*`,
so Souther's committed claw dash (`$161C6`, 8px/frame) would otherwise go
undetected by either.

Whether an enemy cannot defend itself right now — knocked down, blocked,
grabbed, in move recovery, or **stunned** — is `phases.is_punishable`,
read directly off the enemy's own `combat_phase`; a stunned `Grunt`'s
remaining time is its own `stun_timer` field (`$18` frames for hitstun,
`$A0` for the pepper-spray immobilization), read directly rather than
copied into a second token.

**`Surrounded`** flags an actor boxed in by a crowd rather than facing a
queue: three or more live enemies inside the close box around it, or a
pincer with at least one on each side. It is what makes the police special
worth spending on something other than imminent death. This is the one
judgment still computed once per tick and written into the context — see
[Judging without a cache](#judging-without-a-cache) for why it, alone,
earns that.

Backing off to a safe spot, given a threat worth leaving, is `execute.
_find_safe_spot(actor, context)`: the best of a few candidate steps around
the nearest such threat, judged by clearance from every live enemy and
rejected outright when it leaves the playable lane or the camera, lands on
a `Pit`, or has no reachable route. `RetreatFromDanger`'s executor
(`_retreat_from_danger_target`) calls it directly, lazily, only for the
actor it is actually steering this tick, and falls back to stepping
straight back on X when it returns nothing.

Whether a ground `Weapon` is an upgrade — in camera, still usable, and
better than what the actor is carrying — is `reach.weapon_upgrade_rank
(actor, weapon, camera)`, returning the rank itself (not just a bool) so
`priority._emergency_walk_to_weapon` can score by how much of an upgrade
it is.

Whether walking in would take a hold, and whether it is worth taking, are
the two halves of the grab question — can I, and should I. They are
described in [Grabbing an enemy](#grabbing-an-enemy) below.

### Judging without a cache

Through most of this project's early life, every judgment above lived in
its own `Inferred` token, written into the context once per tick by
`generate_inference_tokens` so that `decide.py` (`could_*`) and
`priority.py` (`_emergency_*`) never had to agree about a band by each
recomputing it. That reasoning was sound, but it bundled two different
things into one mechanism: *sharing one definition* of a judgment, and
*caching* that judgment's result for the tick. Only the first one was ever
load-bearing. `reach.py` (and `kinematics.py` for timing) already existed
as the one shared definition every stage called into — the cache on top of
it saved a recomputation, nothing more, and at the AI's own scale (a
handful of enemies, polled every ~33ms) that recomputation is cheap enough
not to matter.

The token layer, meanwhile, cost real complexity: a token class per
judgment, a `check_for_*` producer, careful `|`-chain ordering whenever one
judgment read another's output within the same tick (`generate_inference_
tokens`'s own docstring used to spend a paragraph on this), and a second
place every geometry change had to be kept in sync. Eleven of this
project's twelve `Inferred` tokens have since been removed on exactly this
basis — `ClosingEnemy`, `PunishWindow`, `AntonioIsGoingToKick`, `SoutherIs
GoingToSlash`, `SoutherPunishesJump`, `WeaponUpgrade`, `TargetInReach`,
`IncomingMelee`, `IncomingProjectile`, `GrabOpportunity`, `SafeSpot` — each
folded into a `reach.py` (or, for `SafeSpot`, `execute.py`) function called
directly by whichever `could_*`/`_emergency_*`/state machine needs the
answer, on demand, several times a tick rather than once. The rule that
replaces the old cache: **whenever two stages need the same judgment for
the same thing, both call the same function** — never each recomputing its
own abbreviated version. That is what continues to prevent divergence; the
cache never was.

`Surrounded` is the one exception, and deliberately so: it is read by three
or more call sites in a single tick (`priority._emergency_call_police`,
`decide.py`'s police threshold, `reach.grab_reasons`'s `WHILE_SURROUNDED`
case) and its own computation — a full enemy-count scan per actor — is
heavier than a two-enemy geometry check, so it genuinely benefits from
being computed once and shared, the way the whole `Inferred` stage used to
justify itself.

### Hitbox and AttackRange

Two formal objects carry the geometry the AI used to approximate.

**`Hitbox`** is an object's real collision AABB, in absolute world
coordinates. Enemies cache nothing, so it is *reconstructed* from the ROM's
shape tables exactly as `$AB24` builds it; a `PlayableCharacter` caches its
own body box at `+$70` every frame (`$4140`) and needs no ROM tables at all
-- it is simply read. Every `Enemy`, `Breakable`, `Weapon`, `Myself` and
`Partner` carries exactly one (`None` when it is not available this tick,
never a guessed rectangle).

**`AttackRange`** is one attack an enemy can reach with, in pixels ahead of
its own origin. An enemy carries as many as its animations select, plus one
for whatever it is holding. They are extracted from the ROM: each animation
frame names an attack box id, and the shape table turns that id into
geometry (`graphics-engine.md` §8.3). Nothing here is tuned.

Both are **value objects, not tokens**. The rule that a token may never embed
another token by value is about relationships between independent
observations; a body box and a reach are properties *of* the enemy that
carries them, meaningless on their own, and resolving them through the
context would be indirection for its own sake.

What this buys the AI is a real answer to two questions it previously
guessed at:

- *how close is too close?* — the enemy's own reach, rather than a margin
  derived from the **actor's** punch range, which had nothing to do with it;
- *is there anywhere safe to stand?* — an `AttackRange` has a minimum as
  well as a maximum, so an enemy whose every attack starts further out than
  contact has a dead zone. Pressing into it is safe, and grabbing from
  inside it is free.

An unknown reach is `None`, never zero: bosses have no labelled animation
set, and a session with no ROM access has no ranges at all. Callers fall
back on their own margins there rather than treating the enemy as harmless.

### Kinematics: attacking where the target *will* be

`Hitbox` and `AttackRange` answer where things are. They are not enough on
their own, because nothing in this game happens at the instant the AI
decides: a punch arms 3 frames later (5 for Blaze), the `$322A` chord takes
3 for Axel and **21** for Adam, a jump kick costs a 5-frame crouch plus a
whole flight at 3 px/frame, a thrown knife travels at 16 px/frame and pepper
spray at only 6 — and the AI's own poll adds a frame or two on top of all of
them. An enemy walks through every one of those windows. Aiming an attack at
a position the target has already left is how a move whiffs and leaves the
actor standing in its own recovery frames, which is precisely what
`controls-and-input.md` warns about for the chord: *"a caller that presses
B+C once the target is already in range arms the hit after the target has
walked through the box"*.

So every enemy answers `predict_position_after_n_frames(n)` — its own
velocity (the ROM's `+$1C`/`+$20`, which `$17AB8` integrates once per 60 Hz
frame) extrapolated at constant speed. The unit is a **game frame**, never an
AI poll tick; a tick is about two frames, and treating one as the other is a
silent factor-of-two error. A `Boss` predicts to where it stands, since it
never populates those fields — "no better guess", not "stationary".

`ai/kinematics.py` turns that into a lead time per move, from measured ROM
timings and, for the moves that are really approaches, the ROM's own
walk-speed tables. Two rules keep it honest, and both were learned by
sweeping the pipeline and comparing:

- **A prediction may only ever add an attack, never take one away.** An
  attack is not an instant — a punch damages for 10 frames, Adam's chord for
  18 — so the band is tested at the observed position *as well as* at the
  frame the hit arms, and the union decides. Judging only the future instant
  projected an enemy walking into Axel from 20px into the punch's own inner
  dead zone: the strike vanished, the walk verb took the tick, and the actor
  walked into enemies it should have been hitting, reaching for the slow
  point-blank chord instead.
- **A move leads by its dead time, not by its whole reach.** A jump kick
  leads by the 5-frame crouch it spends on the ground, because that is the
  part the launch decision cannot see; how far the flight itself carries is
  already what the kick's band measures. Leading by the full interception
  instead launched kicks from over 100px, betting that the target would keep
  walking in for all 25 frames — airborne, committed, and short if it stopped.

Bodies also stop at contact rather than passing through one another, so an
approaching enemy is never projected through the actor.

`reach.connects` evaluates each move's band across that move's own
timeline, which is what makes most of `reach.py`'s band predicates
predictive rather than reactive. `reach.enemy_actionable` is the
deliberate exception: it is not "would this hit" but "stop walking, you can
already hit it", and a future-tense answer to that halts the approach while
the enemy is still out of range.

Every concrete `Attack` declares its model in `ATTACK_LEAD_FRAMES`, and a
test fails if one does not. Some models are legitimately zero, and that is a
kinematic result rather than an omission: a held enemy travels with the actor
(zero relative velocity), a `Breakable` does not move at all, and
`CallPolice` — a screen-wide scripted sweep — has no aim point to lead.

### Hitting is box-against-body, and a body is not a corpse

Two geometry facts the AI got wrong for a long time, both visible from the
sofa as "it attacks thin air".

`$450C` tests the attacker's attack box against the victim's **body** box,
which is about 13px wide — so the usable reach runs a little past the box's
measured edges at *both* ends. `controls-and-input.md` draws that conclusion
for the outer edge; it matters far more at the inner one. Treating the
measured inner edge as the dead zone made the AI refuse to punch a foe ten
pixels in front of it, walk away to re-establish "proper" range, turn around
in doing so, re-classify the same enemy as behind it, turn back — and
oscillate there forever, in punching range of an enemy it never touched. The
same false dead zone is what made the slow B+C chord look "warranted" at
point-blank range. The correction is derived, never tuned
(`tokens/character.py`'s `BODY_OVERLAP_X`), and it also makes the punch's
*behind* tolerance fall out as zero: a box that starts 8–18px in front cannot
reach a body centred behind the actor, whatever the slack.

And an enemy stops being a target three different ways, all of which have to
be checked: its phase says so, its **health word** says so, or it stands
somewhere unreachable. The middle one is the ROM's signed lethal check —
`$8000`–`$FFFF` is already dead while the object sits in its slot with an
action family that has not caught up. Reading only the phase left the AI
chasing, ranking and punching corpses.

### Committing to a jump

A jump kick is the one move the AI cannot change its mind about. The
trajectory is fixed at takeoff, so once airborne there is nothing left to
decide except whether to press B — and pressing it is free, while not
pressing it means landing having done nothing.

The **grounded** launch is also a pathfinder question
(`navigation.jump_landing_is_safe`). A jump has no mid-air lane control,
so the planner is asked whether a body can slide to the landing X on the
actor's current Y without hitting a pit. Three answers: the lane is
clear (jump); a 2D walk can get there by leaving the lane (do not jump —
`WalkToNearEnemy` will go around); no walk reaches and the landing is
solid (hop *over* the pit). A landing inside a `Pit` is never launched.
Stage 4's bridge gaps are the case this exists for: a kick toward an
enemy across a hole used to fly in, and `execute_tick`'s pit override
then froze X mid-air because `pit_endangers` is a lane-plane test.
Airborne, that override is skipped so a hop that is already clearing
the gap keeps its launch velocity. `WalkToAdvanceStage` uses the same
planner: when `plan_route` cannot walk the 40px strip (a pit spans the
playable Y) it hops via `hop_landing_x` if the far side is in kick
range, and never injects raw RIGHT/LEFT into the hole.

That makes the *airborne* question categorically different from the grounded
one, and conflating them cost more than half of all jumps: the verb was kept
alive only while the reach band still held, so a target that walked out of
it, drifted a lane, or was simply flown past deleted the verb mid-flight. A
tick with no verb releases the controller, which loses the kick **and** the
launch direction if it happens during the crouch — a jump straight up,
landing on nothing. So the AI now stays committed to the nearest live enemy
for the whole flight.

The same section of the ROM explains the input shape: the direction is read
once, at the end of a fixed 5-frame crouch, and the kick needs a *rising
edge* of B in free flight. Neither survives being routed through the
smoothing that serves ordinary walking, and a B pressed during the crouch is
simply still held when free flight begins, so no edge ever arrives.

### Stunned enemies

`Grunt` carries the ROM's own stun counter (`+$50`) and reads as
`CombatPhase.STUNNED` while it is running. Two different ROM paths produce
it, and both are timed states the enemy cannot act out of:

- **hitstun**, state `$0200`, whose own handler `$9B88` seeds `+$50` with
  `$18` (24 frames) and does nothing but count it down before writing
  `$0100` back;
- **pepper-spray immobilization**, state `$0400` through the shared
  handler `$A43E`, seeded with `$A0` (160 frames) — a far longer free-hit
  window than any knockdown.

State `$0400` is also what the police special forces on every ordinary
enemy while sweeping them off the board, with health `$FFFF`; that case
stays `SCRIPTED` so nothing chases or waits for a body that is being
removed.

A stun does not raise the urgency of hitting that enemy — it caps it, and
the two stuns cap it differently, because they are not the same
situation. The remaining frames tell them apart: the timer can only ever
count down from one of the two seeds above, so anything above `$18` is a
pepper stun.

- **Hitstun** is the middle of a combo. The ROM's own 3-hit chain is what
  knocks an enemy down, and each landed hit re-seeds the timer, so
  attacking a hitstunned enemy stays just *above* a plain strike — the AI
  finishes the combo instead of turning to a fresh enemy that happens to
  be equally punchable.
- **The pepper stun** parks the enemy for nearly three seconds. Attacking
  it drops *below* a plain strike, so anything that can still act gets
  dealt with first. (A pepper stun that has counted down into hitstun
  range is about to end, and is treated as a combo window again.)

Both stay far below the `RearAttack` escape, so a live enemy at the
actor's back interrupts either one, and both stay above every `Walk`
tier, so the AI never walks off mid-stun to fetch another enemy. This is
strictly a ceiling: an attack already ranked lower — an unwarranted
`RearAttack`, say — keeps its own lower score.

### Nora's post-attack recovery

Nora's own combat states are not the generic ordinary-enemy ones: her whip
engage-and-swing and her scripted lunge are their own ROM states
(`phases.py`'s per-type table), and after either one ends she is simply
back to `NORMAL` — not a ROM-confirmed punishable phase (`phases.is_
punishable`) the way a knockdown or a stun is. `Nora.ticks_since_last_
attack` (cross-tick memory, see `generate_direct_observation_tokens`
above) is what lets `JumpAttack` still treat her as worth rushing for a
short, deliberately conservative window after that: a jump kick covers
ground fast enough to land before she can commit to another attack, which
a routine walk-in cannot promise. This is a probabilistic opening, not a
guaranteed one, so it ranks below a real punish window and above the plain
default — see `priority._emergency_jump_attack`.

### Grabbing an enemy

A hold is not a button. `$AAA0`, the shared contact routine, compares the
actor's own attack box against an enemy's body box and reports contact code
3 — the grab code — only when three things are true at once: the actor's
outgoing damage `+$34` is **zero**, the actor is not already holding
anything (`+$4C == 0`), and the two are within 8px of elevation. `$3266`
then converts that code into a hold *at the top of the ground-action
priority chain*, before any button is read at all: front hold `$60` when
the two face each other, back hold `$66` — one B away from a suplex — when
the actor is behind the enemy facing the same way.

So the AI grabs by **walking into an enemy without attacking**. A strike is
not how a grab happens, it is what prevents one: an active attack frame has
a nonzero `+$34` and reports the damage code 2 instead. The same test also
reads the actor's attack box first, and that box only exists on a moving
frame, so the walk-in has to keep going rather than stop on contact.

Why it is worth spending an attack on:

- a held enemy is a **weapon against the ones behind you**. `FlipHold`
  turns the actor around and `ThrowHeldEnemy` (B + back) throws the held
  body backwards, into whatever was closing in from that side;
- an enemy whose **every attack has a dead zone** cannot answer a body
  pressed against it. Holding it converts its best distance into its worst.
  The ROM picks out exactly one today: `Nora`, whose only attacking
  animation reaches 32 to 80 pixels ahead and nothing closer.

Those are two of the reasons `reach.grab_reasons(context, actor, target,
enemies) -> frozenset[GrabReason]` can return — `CLEAR_REAR` and
`DEAD_ZONE`. The second is derived from the extracted `AttackRange`s rather
than from the enemy's class, so a corrected extraction changes the AI's
behaviour without changing any code. A third, `JACK_FROM_BEHIND`, fires
when the actor is already on Jack's back (he is facing away): take the
hold before the axe or the lunge turns around. A fourth, `ANTONIO_ON_
PUNISH`, fires when Antonio is in later-boss hitstun (`RECOVERY`, primary
`$03`/`$04` after `$17C36 boss_apply_pending_damage`): walk in without
attacking, then flip-hold into a suplex. Standing still to punch him is the
`$16EAE` zero-velocity kick trigger, so every grounded B is refused and the
hold is the punish. Its counterpart on a *ready* Antonio is `ANTONIO_WALK_
IN`, produced from contact range only: the alternative there is not a punch
but a hop, and a hop is 45 committed airborne frames for about 2 damage —
the window every hit he lands arrives in — while the hold denies him
everything he owns. The approach that reaches that range keeps a lane offset
wider than his `$10` kick and `$14` dash windows (`execute._approach_lane_y`)
and converges only once alongside on X, so this is never a walk across his
kick range. A fifth, `SOUTHER_ON_PUNISH`, is its Souther counterpart on the same shared
later-boss `RECOVERY` states, and it is a separate reason rather than
sharing Antonio's because the *reason* differs: Antonio's is that a second
punch is his own kick trigger, Souther's is simply that `$15EDA (souther_
state1_active_combat)` cannot re-arm the claw from recovery, so the
walk-in is free — and with base health `$20` against Antonio's `$18`, the
suplex chain matters more, not less. A sixth, `SOUTHER_WALK_IN`, is the
Souther counterpart of `ANTONIO_WALK_IN`, and the plan against him rather
than a fallback: the ground a hold is taken from is the `$18` pocket, which
`$15EDA` cannot commit from, `$161C6` cannot resolve into, and `$15F98`
leaves at 1px/frame against the 2px/frame it is followed at. Unlike every
other reason it can be *withdrawn over time* — `PlayableCharacter.grab_stall_
ticks` (`observe.GrabStallTracker`) counts ticks spent in contact without a
hold, and past `reach.SOUTHER_WALK_IN_STALL_TICKS` the reason stops being
produced so a strike takes the tick. A walk-in that outranks every strike
and never converts is this project's worst recorded outcome against him, and
the guard is what makes offering the reason at all defensible. A seventh,
`WHILE_SURROUNDED`, fires
for any grabbable `Grunt` while the actor is `Surrounded`: being boxed in
is answered by a hold whichever side the crowd is on. It is the one
reason keyed on the actor's whole situation rather than on the candidate
enemy itself, which is why `grab_reasons` takes the actor's `Surrounded`
state as a fresh, on-demand check (`reach.actor_is_surrounded`) rather
than reading a value some earlier stage wrote — see [Judging without a
cache](#judging-without-a-cache).

`GrabReason` is an `Enum`, not a discriminator field on a token: it is the
return type of a pure function now, and `grab_reasons` returns every
reason that applies to a pair at once (a whip enemy in front *and* a body
at the actor's back both hold), so `priority._emergency_grab_enemy` takes
`max(_GRAB_REASON_SCORE[r] for r in reasons)` — "best tier among reasons
present" — over whatever the set contains. The tiers rank differently:
being surrounded is the only one that outranks the `$322A` escape chord (a
pincer's hold becomes a throw *into* the enemy the chord was aimed at),
clearing the rear beats every strike on an enemy that can still act,
catching Jack from behind is just under that, grabbing a stunned Antonio
or Souther sits above punching them again (the hold is the punish) and
above every strike on them, and the whip case is an improvement on an
ordinary exchange and ranks just above a jump kick.

`reach.grab_would_connect` answers the other half — whether walking in
would actually reach — from the same shared geometry definition every
other reach question in this document comes from. `could_grab_enemy`
requires both, because a grab that is possible is not automatically a grab
that is worth taking, and neither is the reverse.

`grab_reasons` returns the empty set outright while the actor is already
holding something. That is not a policy choice: `$AAA0` only issues its
grab code when the actor's own `+$4C` is clear, so walking into anything
from a live hold cannot become a grab. The hold family owns those ticks.

### Knowing that a hold exists at all

The three questions "am I holding", "what am I holding", and "is that thing
still in my hands" are answered from the ROM's own hold link, player `+$4C`
(`world_map.MapEntity.contact_slot` → `PlayableCharacter.held_enemy_slot`),
plus the `$60-$6F` action family and the `$76`/`$80` C crossover
(`PlayableCharacter.is_holding_enemy`), and `reach.held_enemy` for the
identity. **Not** `+$60`: that is the weapon/pickup link `$3136` writes, and
a hold on a later boss leaves it reading `$00` or the weapon the actor is
still carrying.

The distinction is not academic. Against a held later boss the enemy side
announces nothing either — a held Antonio sits in primary `$04`, the same
byte as his ordinary hit reaction — so a `CombatPhase.GRABBED` gate scores
every hold move at 0 and hands the tick back to the walk-in that already
succeeded. Measured live: the AI took a front hold on Antonio and then
issued no verb for 70 seconds, until the round clock killed it. See
`autoplay/CLAUDE.md`'s **Holding a boss**.

This list is meant to grow. Any further situation where a hold beats a
strike belongs here as another `GrabReason` member with its own tier and
its own branch in `grab_reasons`, not as a bespoke new token.

## Process

One instance of this loop runs per player-controlled character; a session
with the AI enabled for both players therefore runs two such instances
concurrently, each producing its own `Myself`. Each instance should apply
its own individual rules to avoid colliding with the other running
instance — for example, preferring to leave a health item on the floor
for the partner if the partner needs it more than `Myself` does. That
particular rule, and the harder constraint that an instance must not hit
the other player, are `do_not_harm_partner`, described below; the rest of
this coordination is a low priority, since the AI being enabled for
both players at once — as opposed to one AI-controlled character alongside
one human-controlled one — is not an expected scenario. The filter itself
is *not* limited to that scenario: friendly fire is just as real against a
human-controlled partner, which is the case it mostly exists for.

The AI operates according to the following iterative loop:

```python
context: set[Token] = set()

# Information tokens
context |= generate_direct_observation_tokens(game_ram)
context |= generate_inference_tokens(context)

# Verb tokens
context |= generate_verb_tokens(context)
context = do_not_harm_partner(context)
context = determine_priority_verb(context)

# UI
inform_hud(context)

verbs = [token for token in context if isinstance(token, Verb)]
verb = verbs[0] if verbs else None

execute_tick(verb, context)

sleep_until_next_ram_poll()
```

`execute_tick` is the single entry point that replaces choosing between
`press_no_button`/`execute_verb` itself — see that section below for why.

The loop normally skips a tick when the player is not playable, but the
type-`$0F` continue / name-entry object is the exception: `InContinueMenu`
and `HandleContinueMenu` still have to answer Yes and type the initials.
Mr. X's offer keeps the player playable, so `InMrXDialog` rides the
ordinary path.

### `generate_direct_observation_tokens`

This function performs direct observation of the game state, as its name
indicates. The existing HUD system already performs an effective, albeit
incomplete, analysis of the game RAM in order to construct a world view;
this effort must not be duplicated. Consequently, this function must reuse
the HUD's own RAM poll, and the analysis it already performs on that poll
must itself be extended to produce the corresponding `Information` tokens,
rather than being polled or analysed a second time.

It is otherwise a pure function of the `GameSnapshot` it is given, with one
deliberate exception: `Nora.ticks_since_last_attack` is cross-tick memory
(how long ago this specific Nora last held a dangerous phase), which no
single snapshot can answer on its own. `observe.NoraAttackTracker` supplies
it, owned one per `AgentLoop` instance and threaded in as an optional
argument — the same precedent `gamepad.py`'s own per-tick steering state
already set for the executor side of the loop.

### `generate_inference_tokens`

In practice, this is just `context | check_for_surrounded(context)`.
`Surrounded` is the one `Inferred` token this pipeline still writes into
the context once per tick — see [Judging without a
cache](#judging-without-a-cache) for why every other judgment this
function used to produce (`check_for_incoming_projectiles`, `check_for_
incoming_melee`, `check_for_grab_opportunities`, `check_for_targets_in_
reach`, and the rest) was removed in favour of a direct, on-demand
`reach.py` call at each site that needs the answer.

The AI's one prediction about the near future — measuring each move's band
at the moment that move would land, not at the moment the snapshot was
taken — still happens, just later: `decide.py`'s `_targets_in_reach` helper
calls `reach.connects(band, actor, enemy, kinematics.connect_frames(
verb_cls, actor, enemy))` for each `could_*` that needs it (see
[Kinematics](#kinematics-attacking-where-the-target-will-be)), instead of
a single upstream stage computing it for every band at once.

### `generate_verb_tokens`

This function likewise invokes a set of subordinate functions, each of
which reads the context and conditionally contributes a token, or a small
set of tokens, to it.

Each such function is named with the prefix `could_`, for example
`could_grab_enemy` or `could_walk` — deliberately not `should_`. Naming
these functions `should_*` would misstate what they do: they answer "is
this verb *possible*, and does it make some kind of sense to pursue",
never "is this verb the one to actually take right now". That second
question — the "should" of the loop — belongs entirely to
`determine_priority_verb`, described next: it alone weighs the
possible verbs this step produced against one another and picks the
one that should actually be executed. A `could_*` function must therefore
never concern itself with the relative importance of its verb, only
with whether the verb is possible in the first place and, if so,
whether it makes sense to pursue at all. For instance, a function should
produce a token for picking up a weapon only if the weapon is present on
the floor **and** within the `CameraRange` **and** an upgrade to the
current weapon held — never because it judges that upgrade more urgent
than some other candidate action. The same "does it make sense to pursue
at all" test rules out a target whose own position sits inside a `Pit`'s
danger zone (`reach.any_pit_endangers`): every walk toward a fixed point
(a nearby enemy, a weapon, a pickup, a breakable prop) skips a candidate
there, since reaching it means standing in the pit. Live testing found
the alternative — producing the walk and letting `execute_tick`'s pit
override fight it back out once the actor arrived — meant the two
disagreed every tick right at the pit's own edge, the walk pulling the
actor back in the moment the override let go: the actor turning left
then right in place, neither side ever winning.

Most such functions must additionally decline to produce a token whenever
an `AnimationInProgress` token for the relevant character is present in
the context, since the character cannot act on a new verb until its
current animation concludes.

### `do_not_harm_partner`

The one stage of the loop that only ever *removes* tokens, which is why it
assigns rather than unions: `context = do_not_harm_partner(context)`. It
runs after every `could_*` has spoken and before anything is ranked, so a
verb it withdraws is never scored, never executed, and never even shown as
a pending candidate. This is deliberately not a scoring penalty in
`determine_priority_verb`: hitting the partner is not a worse idea than the
alternatives, it is an idea that must not be on the table at all. Without a
`Partner` token in the context — the ordinary one-player case, and equally
a partner who is dead or not yet playable — it is a no-op and returns the
context it was given.

**Friendly fire is the ROM's own box-against-body test.** `$4478
(resolve_player_vs_player_collision)` runs once per gameplay frame and
compares the attacker's attack box `+$64` against the *other player's* body
box `+$70`, exactly as `$450C` does for an enemy, converting the attack
descriptor into the other player's reaction whenever the attacker's outgoing
damage `+$34` is nonzero (`player-health-lives-and-combat.md`,
"Player-versus-player contact"). That is the same geometry `reach.punch_
would_connect`, `reach.in_rear_band` and `reach.in_jump_attack_band` already
answer, so this filter asks *those* about the `Partner` rather than
measuring the boxes a second time — the rule from [Judging without a
cache](#judging-without-a-cache), applied to a second kind of body. Their
parameter is still named `enemy`, but it is typed `Character`.

One test per concrete `Verb` class, dispatched by `type(verb) → function`
the way `priority.py` and `execute.py` already dispatch:

- the forward strikes — `Punch`, `MeleeWeaponAttack`, `HitAntonioBoomerang`
  — are withdrawn while `punch_would_connect` holds for the partner;
- `OpenBreakable` only on the ticks it actually strikes (`decide.in_smash_
  range`). Withdrawing the approach as well would park the actor in front of
  a prop for as long as the partner stood nearby, and the next tick re-asks
  the question anyway;
- `JumpAttack` on the grounded launch only. Once airborne the actor is
  committed (see [Committing to a jump](#committing-to-a-jump)): a tick with
  no verb releases the controller, losing the kick *and* the launch
  direction, and not kicking does not un-fly the jump;
- `RearAttack` while the partner is inside the `$322A` chord's real band on
  the side it stands.

Four families are deliberately *not* filtered. `GrabEnemy` presses nothing
— that is what makes it a hold rather than a hit (see [Grabbing an
enemy](#grabbing-an-enemy)) — so its `+$34` is zero and `$4478` has nothing
to convert. `CallPolice` cannot be
friendly fire at all: `$4478` returns immediately while a police special is
active. The hold moves (`AttackHeldEnemy`, `Supplex`, `ThrowHeldEnemy`,
`FlipHold`) deal their damage to the body already in the actor's hands; a
thrown body is its own object with its own collisions and no decoded player
path, so nothing withdraws them today. Neither are the two attack-thrown
weapons (`$21E6 (player_release_thrown_weapon)` issues its throw command for
the knife `$08` and the pepper `$0C`, and for nothing else): an earlier
version of this filter withdrew a throw whose flight lane the partner shared,
and it was removed on the user's own call — catching the partner with a throw
is close to impossible in play, so the lane test only ever cost real throws.

The filter's second half is not about harm but about **not taking what the
partner needs more** — the coordination the [Process](#process) section
above asks for, expressed as a withdrawal for the same reason: a verb the
actor should not take is a verb that should never reach the ranking.

- `WalkToWeapon` is withdrawn while the partner is unarmed, or holds a
  weapon ranked below the actor's own (knife 5 > bat/pipe 4 > bottle 3 >
  pepper 2). `could_walk_to_weapon` only ever offers a genuine upgrade for
  `Myself`, so what is left to decide is which of the two needs it more;
- `WalkToPickup` is withdrawn for a `HealthPickup` while the partner's
  health is the lower of the two, and for a `LifePickup` while the partner
  has fewer lives left. A `SpecialPickup` and a `ScorePickup` are claimed by
  neither rule and stay collectable.

### `determine_priority_verb`

This is the "should" component of the loop: `generate_verb_tokens`'s
`could_*` functions establish everything the actor *could* do this tick;
this function alone decides what it *should* do, by ranking those
possibilities against each other. It constitutes the most demanding part
of the process.

It also performs target selection: when `generate_verb_tokens`
produces several instances of the same kind of `Verb` against
different enemies (for example, a `Punch` against each of two nearby
enemies), no separate selection step exists — the choice is made here,
as a consequence of ranking every `Verb` token in the context by
emergency and retaining only the highest-ranked one.

It ranks the `Verb` tokens present in the context — using the
`Information` tokens already present in that same context — by their
degree of **emergency**, and discards every `Verb` token other than
the one ranked highest. The `Information` tokens are left untouched: they
remain in the context because `execute_verb` (and its auxiliary
functions, described below) requires them in order to carry out the
surviving verb. For instance, executing a `WalkToNearEnemy` verb
requires knowing the targeted enemy's position, which is held by an
`Enemy` token already present in the context.

Because emergency is recomputed from the current game state on every
iteration of the loop, an exact tie between two `Verb` tokens is
expected to be transient in practice: as the game state evolves from one
poll to the next, the underlying `Information` — for example, the distance
to each of two candidate enemies — is very unlikely to remain identical
for long, and the tokens' emergency ranks will diverge on a subsequent
iteration.

Where multiple `Verb` tokens share the same rank of emergency
(typically because their emergency is zero), each `Token` additionally
carries a `priority` property, independent of the rest of the context,
used to break the tie — for example, picking up a weapon carries a higher
priority than advancing to the next stage. `WalkToAdvanceStage` itself
always has the lowest emergency of any verb that still scores, so a
pickup, a walk-in, or an attack will beat it whenever one is available.

Among enemy targets, a `Boss` outranks an armed ordinary enemy, and an
armed ordinary enemy (pickup `$08-$0C`, or Jack still juggling his axe)
outranks every other grunt. That class raise is applied to engagement
verbs and is large enough that distance cannot invert it.

Where multiple tokens still share the same emergency and the same
priority, the AI selects one of them at random. This is treated as a
recoverable exception: the occurrence must be logged, and a developer
should subsequently assign the affected tokens distinct priorities.

By the end of this function, the context retains all of its `Information`
tokens together with, at most, a single surviving `Verb` token; no
`Verb` token remains in the context if none applies.

### `inform_hud`

Pass a copy of the context to the HUD system. The HUD can use some tokens
to add some information visible to the user while the program runs.

### `press_no_button`

There are situations in which the AI need not act at all. This function
guarantees that no button is pressed under such circumstances.

### `execute_verb`

This function dispatches the surviving `Verb` token to one of a set of
auxiliary functions, one per concrete `Verb` subclass. Each such
function receives both the verb and the remaining context, since it
generally needs one or more `Information` tokens to carry out the
verb — for example, fulfilling a `WalkToNearEnemy` verb requires
reading the targeted enemy's position from the corresponding `Enemy`
token in the context.

None of these auxiliary functions should be understood as "issue the
sequence of controller inputs required to fulfil the verb." Rather,
each should steer the controller only as much as is necessary for the
verb to eventually be fulfilled, and should not consume more time
than required. For example, if the verb is to walk toward a given
point, the corresponding function need only set the controller to hold
the appropriate direction and return immediately.

This ensures that the AI remains reactive and can revise its verbs
promptly as events unfold.

### `execute_tick`

`execute_tick(verb, context, gamepad)` is what the process loop actually
calls every tick, instead of choosing between `press_no_button` and
`execute_verb` itself. It runs one override *before* either of those: when
the actor's own current position sits inside a `Pit`'s footprint (plus
`reach.PIT_AVOID_MARGIN`) — knocked there, or having walked or drifted in
while nothing else was contesting it — it takes over the controller
regardless of which `Verb` (if any) won this tick.

A pit is a rectangle, not a line, so the escape does not aim diagonally at
some point outside it: doing that can still cut back through the footprint
before the vertical half of the move finishes. Horizontal movement is held
at zero for as long as the actor's own current lane position still sits
inside the pit's band, and only once it has actually cleared — not merely
been asked to — does horizontal movement resume. Which way is up to
whichever half of the lane the actor is already in (toward the near edge),
the same rule `execute._movement_mask`'s own pit detour already uses below,
since this override hands that same logic a point on the far side of the
pit purely to make it recognise and take over — the geometry itself is
entirely `_movement_mask`'s. That target overshoots the danger boundary by
a real margin rather than landing exactly on it, and the override never
hands back an empty command while the actor still believes it is in
danger: live testing found both the exact-boundary target and a still-
possible empty mask could otherwise leave the actor frozen a few pixels
short of safety, convinced it needed to escape but commanding nothing.

This is deliberately *not* a `Verb` of its own for `generate_verb_tokens`
and `determine_priority_verb` to rank against every other candidate. Every
other pit-awareness this AI has — `execute._movement_mask`'s own detour
around a pit sitting on a walk verb's path, `inference.check_for_safe_
spots`'s rejection of a pit as a retreat *candidate* — only ever comes up
incidentally, while the actor is already walking somewhere for an unrelated
reason. Nothing reacted to the actor simply already standing in the danger
zone with no walk verb underway, which is precisely the gap `execute_tick`
closes: falling in a pit costs a full life
(player-health-lives-and-combat.md's `$01C0` fall-boundary check), so this
is a constraint on how the actor is allowed to move right now — the
executor's own responsibility — not a competing intent.

Because the `MegaDriveEnvironment` remote access interface supports
pressing and holding buttons but not reading which buttons are currently
pressed, a virtual gamepad must be introduced to maintain this state and
mediate communication with the interface.

### `sleep_until_next_ram_poll`

This function suspends execution until the next scheduled RAM poll, so
that the cadence of the loop matches the polling interval already
established for game-state observation, rather than running unconstrained.

## The executor is a state machine

`execute_verb`'s dispatch table (`_HANDLERS` in `execute.py`) is, by
design, a classic finite-state machine's output stage: the surviving
`Verb`'s concrete type is the state, and the table maps each state to the
function that produces this tick's controller output from that state and
the current `Context` — a Mealy machine's `output = f(state, input)`,
not a lookup that merely happens to resemble one.

The winning `Verb` is what **activates** a state machine. It does not
carry the state machine's own internal progress: `determine_priority_verb`
recomputes the winning `Verb` from scratch every tick from the live
`Context`, so which state machine runs next is decided fresh each
iteration, the same way the rest of the loop is. Each state machine's own
function is named `state_machine_*` (for example `state_machine_punch`,
`state_machine_open_breakable`), one per concrete `Verb` subclass or
shared across a family that issues the identical input (the four melee
strikes share `state_machine_melee_strike`, since the ROM resolves the
move from the held weapon type rather than the input differing).

A `state_machine_*` function still follows `execute_verb`'s existing
contract: steer the controller only as much as necessary for the verb to
eventually be fulfilled, and return immediately — never block or sleep
waiting for the move to play out. Where a single verb spans more than one
condition of the world (for example `OpenBreakable`, approach *or* strike
depending on `decide.in_smash_range`), that condition is the state
machine's own transition test, evaluated fresh against the current
`Context` on every call — there is no separate, longer-lived state kept
between ticks beyond the game's own RAM and the virtual gamepad's sticky
hold (`gamepad.py`), which every press-only state machine explicitly
clears via `_press` rather than treating as part of its state.