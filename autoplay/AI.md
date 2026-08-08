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
documenting the findings as manuscripts under `ai-analysis`. These
manuscripts will serve as the primary reference for the AI's
implementation. Analysis of the game will continue in parallel, refining
and correcting the manuscripts as well as the subroutine labels recorded in
`labels.csv`. The call map feature and the accompanying `call_map.py` tool
will likewise be used to develop a clearer understanding of the game's
control flow.

## Data Structures

### Token Hierarchy

The AI system is founded on a single abstract base class, `Token`, from
which two further abstract classes descend: `Information` and `Decision`.
Each of these abstract classes is expected to accumulate numerous
subclasses over the course of implementation.

Tokens are required to contain only the data strictly necessary for their
purpose; there is no constraint on the number of tokens that may be
introduced, including subclasses of subclasses. Generic discriminator
properties, such as `enemy.type`, are to be avoided, as they would
complicate the implementation as the system grows; subclassing is the
preferred mechanism for expressing such distinctions.

A `Token` must never embed another `Token` by value. Since the context is
a flat collection, any relationship between two tokens — for instance, a
`WalkToNearEnemy` decision naming the enemy it targets, or a `DangerZone`
naming the enemies that produced it — must be expressed as a reference to
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

### `Decision`

Whereas `Information` represents the present state of the game, `Decision`
represents a projected future state. A `Decision` cannot be translated
directly into a control signal; rather, it represents a deliberated and
parametrized intent that precedes any concrete action.

`Decision` comprises two principal abstract branches, `Walk` and `Attack`,
together with a single concrete descendant, `CallPolice`, which activates
the police special attack:

- `Walk` — for example, `WalkToCoordinate`, `WalkToNearEnemy`,
  `WalkToAdvanceStage`, `WalkToWeapon`, and `WalkToPickup`; grabbing a
  lay-down weapon or consumable is a `Walk` descendant. `Sidestep` — a
  short evasive step away from an incoming attack — likewise belongs here,
  since the game affords no blocking action; evasion is achieved purely
  through movement.
- `Attack` — for example, `Punch`, `JumpAttack`, `Supplex`, `ThrowKnife`,
  `RearAttack` (simultaneous B+C rear/escape chord), and `CounterGrab`
  (enemy-held C then B sequence), each parametrized with the target or
  coordinate to which the attack applies where applicable. There is no
  separate `Combo`/`GrabEnemy` input; repeated `Punch` contact produces
  both.
- `CallPolice` — the sole concrete `Decision` descending directly from the
  abstract class.

Weapon upgrade ranking follows ROM damage constants (`items-and-weapons.md`):
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
camera. It is read directly from RAM, and is consulted by most `should_*`
functions to determine which otherwise directly observed tokens —
enemies, weapons, hazards — are actually on screen and may therefore be
acted upon.

**`AnimationInProgress`** is carried by a `PlayableCharacter` whenever that
character's current animation, as observed directly from RAM, has not yet
finished (for example, the startup or recovery frames of an attack). Its
mere presence in the context signals to `generate_decision_tokens`,
described below, that the corresponding character cannot presently act on
a new decision.

**`IncomingProjectile`** encapsulates the trajectory of a projectile
already in flight, allowing the AI to react to it before it reaches the
character.

**`DangerZone`** designates an area the player should avoid, or react to,
because it is surrounded by enemies; it encapsulates a coordinate
rectangle and an associated threat level. More elaborate inferences are
also anticipated here — for example, a cluster of `Enemy` tokens
positioned in close proximity to one another may be consolidated into a
`DangerZone` whose threat level is proportional to the number and
relative strength of the enemies it references, even before any of them
has initiated an attack.

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

# Decision tokens
context |= generate_decision_tokens(context)
context = determine_priority_decision(context)

decisions = [token for token in context if isinstance(token, Decision)]

if not decisions:
    press_no_button()
else:
    decision, = decisions
    execute_decision(decision, context)

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

### `generate_decision_tokens`

This function likewise invokes a set of subordinate functions, each of
which reads the context and conditionally contributes a token, or a small
set of tokens, to it.

Each such function is named with the prefix `should_`, for example
`should_grab_enemy` or `should_walk`. A given function must not concern
itself with the relative importance of its decision; it must concern
itself only with whether the decision is possible in the first place, and,
if so, whether it makes sense to pursue. For instance, a function should
produce a token for picking up a weapon only if the weapon is present on
the floor **and** within the `CameraRange` **and** an upgrade to the
current weapon held.

Most such functions must additionally decline to produce a token whenever
an `AnimationInProgress` token for the relevant character is present in
the context, since the character cannot act on a new decision until its
current animation concludes.

### `determine_priority_decision`

This function constitutes the most demanding part of the process.

It also performs target selection: when `generate_decision_tokens`
produces several instances of the same kind of `Decision` against
different enemies (for example, a `Punch` against each of two nearby
enemies), no separate selection step exists — the choice is made here,
as a consequence of ranking every `Decision` token in the context by
emergency and retaining only the highest-ranked one.

It ranks the `Decision` tokens present in the context — using the
`Information` tokens already present in that same context — by their
degree of **emergency**, and discards every `Decision` token other than
the one ranked highest. The `Information` tokens are left untouched: they
remain in the context because `execute_decision` (and its auxiliary
functions, described below) requires them in order to carry out the
surviving decision. For instance, executing a `WalkToNearEnemy` decision
requires knowing the targeted enemy's position, which is held by an
`Enemy` token already present in the context.

Because emergency is recomputed from the current game state on every
iteration of the loop, an exact tie between two `Decision` tokens is
expected to be transient in practice: as the game state evolves from one
poll to the next, the underlying `Information` — for example, the distance
to each of two candidate enemies — is very unlikely to remain identical
for long, and the tokens' emergency ranks will diverge on a subsequent
iteration.

Where multiple `Decision` tokens share the same rank of emergency
(typically because their emergency is zero), each `Token` additionally
carries a `priority` property, independent of the rest of the context,
used to break the tie — for example, picking up a weapon carries a higher
priority than advancing to the next stage.

Where multiple tokens still share the same emergency and the same
priority, the AI selects one of them at random. This is treated as a
recoverable exception: the occurrence must be logged, and a developer
should subsequently assign the affected tokens distinct priorities.

By the end of this function, the context retains all of its `Information`
tokens together with, at most, a single surviving `Decision` token; no
`Decision` token remains in the context if none applies.

### `press_no_button`

There are situations in which the AI need not act at all. This function
guarantees that no button is pressed under such circumstances.

### `execute_decision`

This function dispatches the surviving `Decision` token to one of a set of
auxiliary functions, one per concrete `Decision` subclass. Each such
function receives both the decision and the remaining context, since it
generally needs one or more `Information` tokens to carry out the
decision — for example, fulfilling a `WalkToNearEnemy` decision requires
reading the targeted enemy's position from the corresponding `Enemy`
token in the context.

None of these auxiliary functions should be understood as "issue the
sequence of controller inputs required to fulfil the decision." Rather,
each should steer the controller only as much as is necessary for the
decision to eventually be fulfilled, and should not consume more time
than required. For example, if the decision is to walk toward a given
point, the corresponding function need only set the controller to hold
the appropriate direction and return immediately.

This ensures that the AI remains reactive and can revise its decisions
promptly as events unfold.

Because the `MegaDriveEnvironment` remote access interface supports
pressing and holding buttons but not reading which buttons are currently
pressed, a virtual gamepad must be introduced to maintain this state and
mediate communication with the interface.

### `sleep_until_next_ram_poll`

This function suspends execution until the next scheduled RAM poll, so
that the cadence of the loop matches the polling interval already
established for game-state observation, rather than running unconstrained.