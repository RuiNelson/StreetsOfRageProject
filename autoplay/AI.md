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
  descendant.

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

**`IncomingProjectile`** encapsulates the trajectory of a projectile
already in flight, allowing the AI to react to it before it reaches the
character.

**`ClosingEnemy`** flags an ordinary enemy whose own velocity — not just
its current position — puts it on course to close into rear-attack range
within the next few ticks, even though it is not there yet. Ordinary
enemies steer toward the player on both axes at once, so a fast diagonal
approach can otherwise go from "outside every reaction band" to "already
attacking" between two RAM polls with no warning, since the band checks
elsewhere are purely instantaneous-position. Reference-only, like
`AnimationInProgress`: its mere presence for a given enemy is the signal.

Note: no `could_*` function currently consumes it. An earlier attempt had
`could_rear_attack` fire on it directly, before the enemy was actually
within `RearAttack`'s real range — live testing showed that backfires,
since a Mega Drive attack only hits by current position: the early commit
was a guaranteed whiff that left the character locked in its own recovery
frames exactly when the still-closing enemy arrived and landed a free hit.
Consuming this token usefully needs a genuine evasive reaction (e.g. a
sidestep/reposition verb), not an early commit to the same
reactive-only attack.

**`TargetInReach`** answers, once per tick and per (actor, enemy) pair,
"which of my moves can reach that enemy from here". It is abstract; its
concrete descendants are one per move family — `InPunchReach` (a forward
strike would connect: inside the punch band *and* actually in front),
`InRearReach` (inside the `$322A` chord's real reach on the enemy's own
side), `InJumpAttackReach` (in front, beyond punch outer, inside the
kick's free-flight range) and `ActionableTarget` (some attack the AI
already has would really fire on this enemy now — the "stop walking, you
can already hit it" signal). The geometry behind them lives in `reach.py`,
shared with the verb and ranking stages, so all three agree on one
definition of every band instead of each recomputing it.

**`IncomingMelee`** is the melee counterpart of `IncomingProjectile`: an
on-screen enemy in a committed attack phase, close enough that its hit can
actually land on the actor. A dangerous phase alone is not a threat and
neither is proximity alone, so this is a judgment, not a copy of every
attacking enemy on screen.

**`PunishWindow`** flags an enemy that cannot defend itself right now —
knocked down, blocked, grabbed, in move recovery, or **stunned**. It
carries `frames_left` when the ROM exposes a countdown, which today means
a stunned `Grunt`'s own `+$50` timer (`$18` frames for hitstun, `$A0` for
the pepper-spray immobilization).

**`Surrounded`** flags an actor boxed in by a crowd rather than facing a
queue: three or more live enemies inside the close box around it, or a
pincer with at least one on each side. It is what makes the police special
worth spending on something other than imminent death.

**`SafeSpot`** answers "back off to *where*" for an actor that has an
`IncomingMelee`: the best of a few candidate steps around it, judged by
clearance from every live enemy and rejected outright when it leaves the
playable lane or the camera, or lands on a `Pit`. `RetreatFromDanger`'s
executor steers here when it exists and falls back to stepping straight
back on X when it does not.

**`WeaponUpgrade`** flags a ground `Weapon` that is in camera, still
usable, and better than what the actor is carrying, carrying the rank and
the rank gain so nothing downstream re-reads the damage table.

**`InGrabReach`** and **`GrabOpportunity`** are the two halves of the grab
question — can I, and should I. They are described in
[Grabbing an enemy](#grabbing-an-enemy) below.

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

Those are exactly the two `GrabOpportunity` descendants —
`GrabToClearRear` and `GrabIntoDeadZone`. The second is derived from the
extracted `AttackRange`s rather than from the enemy's class, so a corrected
extraction changes the AI's behaviour without changing any code. They are subclasses rather
than one token with a reason field, per this document's own rule, and they
rank differently: clearing the rear beats every strike on an enemy that can
still act, while the whip case is an improvement on an ordinary exchange
and ranks just above a jump kick.

`InGrabReach` answers the other half — whether walking in would actually
reach — and, like every other `TargetInReach`, comes from one geometry
definition in `reach.py`. `could_grab_enemy` requires both, because a grab
that is possible is not automatically a grab that is worth taking, and
neither is the reverse.

This list is meant to grow. Any further situation where a hold beats a
strike belongs here as another `GrabOpportunity` subclass with its own
tier, not as a new field on an existing one.

## Process

One instance of this loop runs per player-controlled character; a session
with the AI enabled for both players therefore runs two such instances
concurrently, each producing its own `Myself`. Each instance should apply
its own individual rules to avoid colliding with the other running
instance — for example, preferring to leave a health item on the floor
for the partner if the partner needs it more than `Myself` does. This
coordination is a low priority, however, since the AI being enabled for
both players at once — as opposed to one AI-controlled character alongside
one human-controlled one — is not an expected scenario.

The AI operates according to the following iterative loop:

```python
context: set[Token] = set()

# Information tokens
context |= generate_direct_observation_tokens(game_ram)
context |= generate_inference_tokens(context)

# Verb tokens
context |= generate_verb_tokens(context)
context = determine_priority_verb(context)

# UI
inform_hud(context)

verbs = [token for token in context if isinstance(token, Verb)]

if not verbs:
    press_no_button()
else:
    verb, = verbs
    execute_verb(verb, context)

sleep_until_next_ram_poll()
```

### `generate_direct_observation_tokens`

This function performs direct observation of the game state, as its name
indicates. The existing HUD system already performs an effective, albeit
incomplete, analysis of the game RAM in order to construct a world view;
this effort must not be duplicated. Consequently, this function must reuse
the HUD's own RAM poll, and the analysis it already performs on that poll
must itself be extended to produce the corresponding `Information` tokens,
rather than being polled or analysed a second time.

### `generate_inference_tokens`

This function invokes a set of subordinate functions, each of which reads
the directly observed tokens and derives further tokens from them.

Each such function is named with the prefix `check_for_`, for example
`check_for_incoming_projectiles`. Every one of these functions produces a
focused set of `Information` descendants — often no more than one — which
is appended to the context.

Most of them read only directly observed tokens and are therefore
independent of one another; `check_for_safe_spots` is the exception, since
a safe spot only means anything relative to a threat, so it runs last and
reads the `IncomingMelee` tokens produced earlier in the same call.

The `could_*` functions below, and the `_emergency_*` functions that rank
their output, consume these tokens rather than re-deriving the same
judgment from raw coordinates. That is the point of the stage: a band is
computed once per tick, in one place, and every later stage sees the same
answer.

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
than some other candidate action.

Most such functions must additionally decline to produce a token whenever
an `AnimationInProgress` token for the relevant character is present in
the context, since the character cannot act on a new verb until its
current animation concludes.

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
priority than advancing to the next stage.

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

Because the `MegaDriveEnvironment` remote access interface supports
pressing and holding buttons but not reading which buttons are currently
pressed, a virtual gamepad must be introduced to maintain this state and
mediate communication with the interface.

### `sleep_until_next_ram_poll`

This function suspends execution until the next scheduled RAM poll, so
that the cadence of the loop matches the polling interval already
established for game-state observation, rather than running unconstrained.