# Specification for Agents

The agents can be activated or deactivated with a button in the UI at any time.

The main goals is to defeat the enemies as fast as they can, take the least damage, finish the level fast.

## Basics

- must know how to control the three characters and take advantages of their highs/lows
- must calculate "pressure" to call the police special (large number of enemies, low health)
- must handle specifics of the stages
  - try not to fall in stage 4
  - know it's an elevator in stage 7 and not fall from it
  - know they have to move left in stage 8
  - know to handle Mr. X dialog (always choose "NO")
- pick up weapons and items
- be steady when the police special is in action or the game is paused

## Combat

Must know how to all the moves.

Must have handle the various enemies AIs, including bosses, handle multiple enemies at the same time.

Read the game code for understanding the AIs and beat them.

Position themselves in a least perilous position.

In particular, do not remain in a front grab while another live enemy can
attack the player's back. Infer that tactical condition from facing and enemy
geometry, cross over the held enemy with C, wait until the game confirms the
back-hold state, then press B once to suplex. Never mash C or B through the
transition animations.

Combat intelligence is split into three reusable layers:

- an expert knowledge base expresses named tactical facts and production rules;
- a deterministic inference engine derives explainable goals and records which
  rules fired;
- a persistent autoplanner turns a goal into guarded controller steps across
  multiple observations, cancelling safely if its preconditions disappear.

The tactical choice layer uses complementary symbolic forms rather than a
single priority chain:

- a typed knowledge graph records `REACHABLE`, `DANGEROUS`, `PUNISHABLE`,
  `DEFEATED`, `TARGETS_PLAYER`, `BEHIND_PLAYER`, `COLLECTIBLE`,
  `BLOCKS_PROGRESS`, and enemy interaction affordances such as `ARMED`,
  `THROWING`, `GRABBABLE`, and `AIR_ATTACK_ONLY` from each coherent snapshot;
- fuzzy inference represents graded concepts such as special-attack pressure,
  target peril versus proximity, item value, safety, and travel cost;
- a deterministic constrained optimizer enumerates legal fight, loot, and
  progress goals, applies hard facts first, then maximizes fuzzy utility;
- goal and target hysteresis retain focus unless new evidence is materially
  better, avoiding oscillation without hiding the explanation trace.

Hard game facts always dominate fuzzy preference. An actor outside the playable
lane cannot be attacked even if RAM makes it look dangerous; a boss blocking
the arena forbids progress and loot; immediate danger forbids an item detour.
In Round 1, enemies pre-created at lane Y `0` are observed for diagnosis but
are unreachable until the player advances through their activation trigger.
Antonio remains a blocker when his activation point is just beyond the visible
screen edge.

Enemy lifecycle is also a hard fact. Ordinary enemies use a signed lethal
check: health `0` remains alive and needs a finishing hit, while
`$8000-$FFFF` is already defeated even if a stale attack state remains in the
same observation. A defeated object may stay allocated on the floor, but it
must never be reachable, dangerous, blocking, selected, chased, or attacked.

Jack (`$27`) has a hard, state-dependent interaction rule. While his carried
weapon latch is set he cannot be grabbed or hit with the ordinary grounded
approach; line up at jump-kick range and execute C followed by airborne B. His
weapon-throw state makes him temporarily grabbable and punchable, while the
separate thrown helper (`$28`) remains a projectile to evade. This legality
constraint must override fuzzy target and attack preferences.

A grab must always resolve. Controller inputs are issued only in confirmed
input-ready hold states, never through `$62-$6E` transition/throw animations.
The reciprocal grabbed-enemy relationship overrides stale weapon fields. If a
crossover is rejected, retry it a bounded number of times and fall back to a
direct strike/throw instead of waiting indefinitely.

When an enemy holds the player, the player action sequence `$78-$7E` has its
own guarded escape plan. At `$7A`, press C to enter crossover `$7C`; wait for
the ROM to return to `$7A` with action flag `+$58.bit7`, then press B within
that eight-tick window to enter the `$7E` counter throw. Do not send B+C as a
chord, and do not inject input during `$78`, `$7C`, or `$7E` animations.

This boundary must remain usable by future learning: learned components may
propose facts, goals, rule weights, or plan selection, while ROM-state guards
and the evaluator continue to enforce legal and reproducible execution.

## Testing and learning contract

Gameplay changes must be measurable in controlled lockstep, not judged only
from a real-time run. The common evaluator records damage, lives, enemy damage,
item collection failures, progress, jumps, actions, and reward from coherent
RAM snapshots, and supports explicit pass/fail thresholds plus per-step traces.
It also records exposed-back grab opportunities, missed responses, crossover
starts, and suplexes so tactical positioning is measurable rather than judged
only from video.

The evaluator also records invalid grab-animation attack edges, stalls caused
by unreachable observed enemies, loot choices made under immediate threat, and
progress choices made while a boss blocks the arena. Each has a zero-tolerance
acceptance threshold so symbolic rules remain testable as later learned
components are introduced.
Prolonged no-input boss guarding is measured after a short grace window, so a
legitimate defensive pause remains possible but a tactical fixed point fails.
It records grounded attacks against armed Jack, valid armed-Jack jump starts,
and grounded counters during Jack's throw window so this family rule remains
an acceptance gate for future learned policies.
Enemy-grab crossover/throw edges, missed escape responses, and attacks or
off-route pursuit toward defeated floor objects are also first-class metrics
and acceptance gates.

Future scripted or learned policies must use the same snapshot-to-decision
interface and evaluation metrics. Learning may replace policy selection and
reward shaping, but must not bypass the controlled scenarios or acceptance
criteria used to catch gameplay regressions.

## Two player interaction

The agents must be able to play the game alone, but must also be able to play the game cooperatively with another agent or with an human.

- be able to do the move that only two player can do (grapple/jump/attack mid-air)
- don't be greedy in life and special attack items, let the other player take them if the other player has less health
- get weapons from the floor if a better weapons is found, don't wait for the other player to pick up them
