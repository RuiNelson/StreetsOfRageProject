# Streets of Rage Autoplay — AI Specification

**Living document.** This file and the code under `src/sor_autoplay/agent/`
describe the same agent. When behaviour changes, update both:

- Edit this document to define intended behaviour; implement that change in code.
- Change code only when the new behaviour is reflected here.

Prefer plain English here. Code identifiers appear only where they help map a
rule to a module. Implementation lives under `src/sor_autoplay/agent/`.

---

## 1. Purpose and scope

The autoplay AI is a **scripted, deterministic policy** that plays *Streets of
Rage* on a live recompilation host. It is **not** a neural network. It:

1. Reads a coherent snapshot of game state (players, map entities, flags).
2. Decides controller input for one or both seats (P1 and/or P2).
3. Emits an explainable note string for the HUD and traces.

It attaches through `megadrive_remote` to a running `sor` process. The observer
HUD can run without agents; agents are optional and toggled per seat.

### 1.1 What the AI may and may not do

| Allowed | Forbidden |
| --- | --- |
| Press D-pad, A, B, C (standard layout) | Press Start (agents never pause) |
| Hold directions between polls | Use host `--altControls` layout |
| Pulse face buttons for ROM input edges | Cheat via direct RAM writes for play |
| Read RAM for perception | Invent button sequences illegal for the current ROM action |

**Evaluation lockstep** may seed RNG and frame phase for comparable tests;
those writes are test setup only. Live play uses controller inputs alone.

### 1.2 Control scheme (standard only)

OPTIONS control scheme **0**. Host must **not** use `--altControls`.

| Physical button | Meaning |
| --- | --- |
| **B** | Attack, pickup, knee while holding, weapon swing/throw |
| **C** | Jump; crossover vault while holding an enemy |
| **A** | Call the police special |
| **B + C together** | Rear / back attack (never used as a jump-kick) |
| **D-pad** | Move (up = back of stage / smaller lane Y) |

Jump-kick is **C first, then B on a later decision while airborne** — never
C and B on the same tick (that is the rear attack).

---

## 2. Architecture overview

Each enabled seat, each decision tick:

```text
GameSnapshot
  → DecisionContext (perception bag + seat memory)
  → PlayerMode (exclusive ROM partition)
  → Commitment / multi-frame skills (at most one per seat)
  → police special (when free enough)
  → free tactical path (air, props, fight/loot/progress, combat, nav)
  → Intent
  → co-op attack gate
  → button mask → host (hold_buttons / press_buttons)
```

### 2.1 Session configuration

- **P1 / P2 enabled**: independent toggles (HUD buttons or keys `1` / `2`, or
  CLI `--agent-p1` / `--agent-p2`).
- **Police threshold**: default pressure score **4.5** (0–10 scale) before A
  is considered, subject to hard eligibility rules below.
- **Hold frames**: fallback pulse length for older hosts without sticky holds.

### 2.2 Per-seat memory (not ROM state)

Each seat keeps mutable policy memory:

- **Walk latch** — world-space goal and locked D-pad signs until arrival.
- **Nav memory** — hole detours, breakable side choice, stuck recovery.
- **Goal memory** — last fight/loot/progress choice and target (hysteresis).
- **Grab / enemy-grab-escape latches** — bridge one missing observation sample.
- **Auto-planner** — multi-step crossover → suplex plan.
- **Commitment** — which multi-frame skill currently owns the seat.
- **Attack cooldown** — short tick counters so B is not spammed every poll.
- **Last note** — human-readable reason for the last decision.

When agents are off, the game is paused, a police special is already playing,
or the game is outside live combat states, tactical memory is cleared and the
agent emits **no input** (steady).

---

## 3. Decision pipeline (priority order)

The following is the **authoritative behaviour order**. Higher items win.

### 3.1 Session-level steady (no seat logic)

Emit empty masks when:

- neither agent is enabled, or remote is disconnected; or
- the game is **paused**; or
- a **police special** is already active; or
- game state is not a live in-game combat/progression state.

### 3.2 Per-seat exclusive modes

| Mode | When | Behaviour |
| --- | --- | --- |
| **Dialog** | Mr. X end offer is live | Always select **NO**, then confirm |
| **Not playable** | No player entity or seat not playable | Idle |
| **Enemy held** | Player actions in the enemy-grab family (`$78–$7E`) | Own the full escape: C to cross, wait, B in the counter window |
| **Hurt** | Player is in a hurt reaction | Clear plans and walk; wait (no input mash) |
| **Grab animation** | Closed throw/knee anims | Hold ownership with empty input (do not re-fire B) |
| **Airborne** | Jump action family | Aim toward target; B only in free-flight, never launch/land |
| **Holding** | Player holds a weapon or an enemy | Hold-resolve skill (after police when applicable) |
| **Free** | Grounded, not held, not exclusive above | Full free tactical path |

Mode classification order: dialog → not playable → enemy held → hurt → grab
animation → airborne → holding → free.

### 3.3 Multi-frame skills (commitment)

At most **one** skill owns a seat at a time. A skill keeps ownership until it
finishes or its preconditions fail. Soft preference scores never start an
illegal skill; hard ROM state gates ownership.

#### Enemy grab escape

When an enemy holds the player:

1. Wait through acquire / closed animations.
2. In the held state, press **C** to start the crossover.
3. Wait through the crossover animation.
4. When the counter window flag is set, press **B** for the counter throw.
5. Never press B and C on the same tick for this protocol.

Retries are rate-limited so a rejected edge is not re-fired every poll.

#### Crossover suplex (back protection while *we* hold)

When **we** hold an enemy from the front and another live hostile is **behind**
us:

1. Expert rules infer goal “crossover suplex”.
2. Planner presses **C** (vault to the enemy’s back).
3. Wait until back-hold is confirmed.
4. Press **B** for the suplex.
5. Plan times out safely; tolerates **one** missing hold observation; retries
   crossover at most **twice**, then falls back to a direct B strike.

This skill runs **before** police special and ordinary hold resolve so back
protection is not delayed by A or knee spam.

#### Hold resolve (ordinary hold / weapon)

After police special check:

- **Enemy hold**: mostly **B** knees; every third pulse (or under crowd /
  partner pressure) **B + away** for a throw. Away = opposite of facing.
  Prefer throw side that does not fling the body into a co-op partner.
- **Back hold** (`$66`): B for suplex.
- **Weapon hold**: only attack when a live foe is in usable lane/range;
  otherwise return control to free movement. No B spam through weapon anims.
  Bat/pipe = melee swing; knife/bottle/pepper = throw (Blaze dumps weak weapons).
- **Closed grab animations**: empty input lockout even if pointers clear.
- **Orphan contact**: exact front-hold with only a stale contact pointer gets
  one B to release, then idle.

Hold detection requires strong evidence: a reciprocal grabbed-enemy link to this
player, or a non-weapon held type. Contact pointer or weapon projectile pointer
alone is **not** enemy-grab evidence. A reciprocal grab overrides a stale weapon
type.

### 3.4 Police special

After crossover planning, before ordinary hold:

Call **A** only when **all** of:

1. Special stock remaining (and not round 8 / level index ≥ 7).
2. Player can start a grounded action (input-ready ground or weapon-ready).
3. Situation is **eligible**:
   - any reachable live **boss**, or
   - at least **four** nearby enemies, or
   - health ≤ **40%** with at least one nearby enemy;
4. Fuzzy pressure **score ≥ threshold** (default 4.5).

Boss presence forces maximum pressure urgency. Conserve specials in small
full-health skirmishes even if the fuzzy score is noisy.

Pressure factors (fuzzy, with fired-rule trace): crowd size, hunters targeting
this seat, active attacks, surrounded geometry, bosses, low/critical health.

### 3.5 Two-player air assist

When **both** seats are agent-controlled and the partner is in a **jump action
family** nearby: emit **B+C** intentionally for the co-op air throw.

**Never** use elevation (`world_z`) for this test — standing ground Z is always
large and would false-trigger forever.

### 3.6 Free tactical path

When no exclusive skill owns the seat:

1. **Airborne** handling (if still airborne in free path — same rules as mode).
2. **Moving damaging breakables** (round 8 type `$45`): evade lane within 220 px;
   smash only when already in grounded punch range; never chase like a static crate.
3. **Arbitrate goal**: fight vs loot vs progress (constrained utility).
4. If **loot** wins: walk into ROM pickup box, B only when grounded and ready.
5. **Combat** against selected target (face-then-hit, family counters, back security).
6. **Static breakables** when no combat target (side approach only).
7. **Stage progress** (right by default; left on stage 8; elevator hold on stage 7).

---

## 4. Perception: knowledge graph

Every free decision builds a **tactical knowledge graph** from one snapshot:
typed entities and hard relations. Soft scores never expand what the graph
marks impossible.

### 4.1 Relations (hard facts)

| Relation | Meaning |
| --- | --- |
| **Reachable** | Can interact: on-screen (or boss margin), playable lane, alive if combatant |
| **Defeated** | Signed-negative health / death — never target, chase, or treat as danger |
| **Targets player** | Enemy AI is hunting this seat |
| **Dangerous** | Decoded attack / wind-up phase (or launched projectile) |
| **Punishable** | Downed / open for free hits |
| **Behind player** | On the player’s rear arc relative to facing |
| **Same lane** | Lane Y within ±12 |
| **Near player** | Distance ≤ 160 |
| **Blocks progress** | Live combatant that should stop forward scroll chase |
| **Collectible** | Free ground weapon/pickup in loot camera band |
| **Armed / Throwing / Grabbable** | Jack weapon phases and grab affordances |
| **Attached / Launched** | Jack helper object phases |

### 4.2 Visibility and targeting rules

- **Combat / danger / pressure**: camera-relative X in **0..320** (strict CRT).
  Bosses get a small right margin (~64 px) because they can lock scroll just
  outside the viewport (Antonio observed ~328).
- **Loot**: only free ground items in the walk band ± pickup reach
  (`map_x` roughly **16..304**). Off-camera map markers are never loot goals.
- **Playable lane**: entities outside the level’s lane band are not reachable.
- **Dormant spawns** (e.g. round 1 actors at lane Y 0 with inactive state) stay
  on the diagnostic map but are **not** targets until the ROM activates them.
- **Zero health** remains targetable until the finishing hit / death state
  (ROM needs the underflow). **Signed-negative** health is hard **Defeated**.

### 4.3 Fuzzy scores vs hard guards

Fuzzy membership is used only for graded concepts (near, low health, crowd,
target utility). **Hard constraints always win**: unreachable, defeated, grab
windows, input-ready actions, co-op friendly-fire geometry.

---

## 5. Goal arbitration (fight / loot / progress)

From the graph, enumerate legal goals and pick the **deterministic maximum
utility** with hysteresis.

### 5.1 Feasibility

| Goal | Feasible when |
| --- | --- |
| **Fight** | A reachable combat target exists (or a blocker without a fresh target) |
| **Loot** | Collectible item exists **and** no boss blocks the arena **and** no near dangerous foe |
| **Progress** | Nothing blocks progress on the graph |

### 5.2 Utility ideas (plain English)

- **Fight**: target utility from combat scoring + pressure urgency; bosses and
  dangerous foes push utility very high; hunting the player adds a bonus.
- **Loot**: base value (life > special > weapon > health-need-scaled food) ×
  closeness × safety (inverse pressure).
- **Progress**: modest baseline when the screen is clear.
- **Hysteresis**: keep the same goal/target unless a challenger is materially
  better (~0.08 utility stickiness).

### 5.3 Loot and weapons

- ROM pickup box is about **±20 X, ±16 Y, ±8 Z**. The agent walks inside a
  slightly tighter box and only presses B when grounded and input-ready.
- Health / life / special pickups obey **co-op fairness** (see §8).
- Weapons always free for either player in fairness terms, but:
  - Only **free ground** weapons (not held/thrown/exhausted).
  - Fuzzy weapon value uses damage/range/control plus character preference.
  - Armed players pick a ground weapon only when it is a **material upgrade**.
  - Fight constraints outrank upgrades.

---

## 6. Combat

### 6.1 Face-then-hit (core rule)

A grounded punch is legal only when:

1. **Same lane** — |ΔY| ≤ 12 (ROM front-interaction band).
2. **In strike range** on X for the character (with a small safety margin inside
   measured live hitboxes).
3. **Facing the foe** — action state bit 0 set means face left.

If geometry is ready but facing is wrong: **turn one tick** (D-pad only), then
punch. Do not reverse-punch or air-punch by closing X while off-lane.

**Match lane before closing X.** Off-lane “close enough” was the historical
air-punch bug.

### 6.2 Character profiles

| | Axel | Adam | Blaze |
| --- | --- | --- | --- |
| Identity | Strong combo, slower, short rear | Balanced, best rear range, loves bat/pipe | Fast, weak ground combo, best jump kick |
| Strike range (policy) | ~52 | ~50 | ~62 |
| Stand-off approach | ~46 | ~44 | ~56 |
| Jump kick | Short window | Good | Best — prefer often |
| Rear (B+C) | Short/fast only when close | Long range | Mid |
| Grab | Prefer spaced punches | Prefer throw / vault | Prefer throw / vault |
| Weapons | Average all | Prefer bat/pipe | Prefer bat/pipe; knife/bottle weak |

Measured first-punch live boxes reach about 57 / 54 / 68 px; policy keeps 4–6 px
inner margin. Stand at approach offset, not body-grab range (~≤18).

### 6.3 Target selection

Fuzzy target utility weighs: distance, lane access, danger/ranged attacks,
punish windows, boss status, who is targeting the player, and family tier.

At equal geometry, preferred tier is:

**Boss > Jack > Nora > Signal > Haku-Ro/ninja > Garcia**

A much closer or actively attacking lower-tier foe can still win. Stick with
the current target unless a challenger wins by a material margin.

### 6.4 Attack mix (deterministic)

Attack choice is **deterministic** (no random tick rolls). Mix labels include
punch, jump, grab walk, rear, hold. Jump-ins only when an enemy-family counter
explicitly asks (e.g. Signal, Haku-Ro), not from character reach alone.

Jump start: **C only** while facing, with **safe landing** (no pit under arc).
Airborne branch later emits B only in free-flight states.

### 6.5 Combo and busy states

- While the player is mid-attack animation: face the foe; queue next combo B only
  when the ROM still accepts an edge (ordinary `$18` with action flag clear).
- Do not spam B after the ROM has accepted the edge.
- Attack cooldown ticks prevent every-poll re-presses.

### 6.6 Family counters (summary)

| Family | Prefer |
| --- | --- |
| **Garcia** | Close combo / grab; intercept wind-ups early |
| **Signal** | Mid/far spacing; C→B jump kicks; jump early on low sweep |
| **Haku-Ro** | Jump intercept; do not chase teleports |
| **Nora** | Close for grab → knee/throw; distrust “downed” feints |
| **Jack** | Punch while armed; **do not grab** until throw window or unarmed; dodge launched helpers only |
| **Abadede / Bongo** | Sidestep charge/flame; no jump into them |
| **Antonio** | Outside mid attack window; re-align to boss lane if charging far away |
| **Souther** | Stay grounded; leave committed claw lane |
| **Onihime/Yasha** | Stay mobile; leave shared lane when both bracket the player |
| **Mr. X** | Mid-close pressure; rear escape when charged |

### 6.7 Back security (free combat)

If a second live hostile is behind the player:

1. Prefer **grab a legal front target** and convert to crossover-suplex.
2. Only use **rear B+C** when there is no grabbable front shield.
3. Never restore “air attack only” rules that block armed-body punches on Jack.

### 6.8 Preemptive defense

- Committed enemy attacks within ~100 px: interrupt with punch when aligned, or
  leave the lane; at lane edge retreat on X.
- Basic pack enemies: intercept during approach within strike + ~24 px lead.
- Signal low sweep: start C within ~120 px when lane-aligned (if landing safe).
- Projectiles (launched): walk evade, do not punch the helper as a body.
- Charge/sidestep retreat only inside the reaction radius; distant bosses are
  approached, not fled.

### 6.9 Boss movement guards

Souther and the twins own special **leave the attack lane** movement even when
generic pursuit would walk back into the claw/grab choreography. Hold the safe
lane once clearance is enough.

### 6.10 Airborne sequence (ROM)

```text
$10 launch → $12 free flight → $16 air attack → $14 landing
```

B is accepted in free flight, not during launch or landing. Airborne is the
action family `$10–$17`, not world elevation.

---

## 7. Grabs, weapons, and holds

### 7.1 When we hold an enemy

See §3.3 Hold resolve and Crossover suplex.

### 7.2 When an enemy holds us

See §3.3 Enemy grab escape. Own the full sequence; do not mash random buttons.

### 7.3 Weapons as inventory

A carried weapon is **not** a permanent combat target and **not** a reason to
press B every poll. With no live foe, or a foe outside weapon lane/range,
weapon policy yields to normal movement/combat. Dangerous enemy phases also
yield so family counters (e.g. jump Signal sweep) win over a swing.

---

## 8. Co-op (two players)

Streets of Rage 1 has **friendly fire**. Agents must never intentionally hit
another live player.

### 8.1 Safety layers

1. **Body bubble** — partner very close: any B risks contact.
2. **Directional cone** — partner on the attack side in-lane for punch/throw/rear.
3. **Final gate** — every seat strips B / B+C after the policy if the attack
   would hit the partner (except intentional air assist).

When blocked, **clear the partner’s lane** (step vertically) rather than wait
forever or fire through them. Grab throws prefer the side away from the partner.

### 8.2 Item fairness

- Do not take health when nearly full.
- Prefer leaving life/special/health to a partner who is materially more hurt.
- Critical health overrides fairness for the needy player.
- Weapons are not rationed by fairness (still subject to upgrade rules).

---

## 9. Navigation and stages

### 9.1 Walk latch

Movement uses a **latched world-space goal**. The same D-pad signs are held
until the player arrives in the goal band or **passes through** the goal on
both axes. Combat in range, grabs, police, and hurt clear the walk.

Nearby goal refreshes must **not** re-aim every poll (that caused wall thrash).

### 9.2 Hole routing (stage 4)

Terrain facts from the collision-class map (class 0 = pit):

1. When horizontal progress meets a hole: **latch one safe detour lane**.
2. Finish vertical motion (**DETOUR**), then advance past the pit on X
   (**ADVANCE**).
3. Never recompute detour side every poll (UP/DOWN shakiness).
4. Emergency rewrite only when **already inside** a pit AABB.
5. Jump starts require **safe landing** cells under the arc.

### 9.3 Breakable approach

Smash boxes need **horizontal facing in the same lane**. Never approach pure
top/bottom:

1. Move to a horizontal stand-off at the current lane.
2. Then match the prop’s lane.
3. Score both stand-offs against holes; latch the only solid side.

### 9.4 Stuck recovery

If world position does not move by ~3 px for ~8 polls: cycle open-loop cardinal
escapes, ban failed headings, try the other crate side / detour lane. Walk
latches must not keep re-aiming into the same wall.

### 9.5 Stage special cases

| Stage | Rule |
| --- | --- |
| **Most stages** | Progress right when no blocker |
| **Stage 4** | Hole detours as above |
| **Stage 7 (elevator)** | No horizontal progress; center lane `$50`; no LEFT/RIGHT progression; class-0 cells are not holes |
| **Stage 8** | Progress **left**; Mr. X offer always **NO** |
| **Round 8 moving props** | Evade then smash only in range (see free path) |

### 9.6 Mr. X dialog

When the final offer UI is live: move selection to **NO**, then confirm. Never
accept the “join Mr. X” path.

---

## 10. Input delivery

Agents run on the same remote poll thread as RAM reads (one connection).

- **D-pad only**: sticky `hold_buttons` so walking is continuous between polls.
- **Any mask with A/B/C**: blocking VSync `press_buttons` pulse so the ROM sees
  a fresh input edge; then re-latch D-pad component.
- Older hosts without hold support fall back to press-only (walk taps).

Notes never select the transport. Rebuild the host so it serves `HOLD_BUTTONS`.

Default observer poll when agents are off: wall-clock ~33 ms (not VSync waits).

---

## 11. Evaluation and regression contract

`evaluation.py` is the stable boundary for tests and future learned policies:

- Policy type: **GameSnapshot → AgentDecision** (masks + notes).
- Lockstep: **four emulated frames per decision**; face buttons pulsed three
  frames and released one frame inside that step.
- Metrics and thresholds must remain comparable across episodes.
- Traces (JSONL) live outside the repository.

First-class failure modes (normally enforce at zero or scenario minimums)
include: failed pickups, failed ground-attack starts, weapon air attacks,
missed back-exposure responses, invalid grab-animation attacks, enemy-grab
escape misses, defeated-enemy attacks/pursuit, loot under threat, boss
progress while blocked, boss stall, wasteful specials, missed boss specials,
elevator horizontal progress, missed moving breakables, and related counters.

Comparable episodes use evaluator restart paths (character/level) that freeze
setup on the same connection before evaluation; do not leave an uncontrolled
frame gap between setup and measure.

---

## 12. Module map (code ↔ this document)

| Topic | Module(s) |
| --- | --- |
| Pipeline entry, free path | `agent/policy.py` |
| Modes, seat memory, decision bag | `agent/context.py` |
| Skills / commitment | `agent/skills.py` |
| Buttons and Intent | `agent/controls.py` |
| Knowledge graph | `agent/knowledge.py` |
| Fight/loot/progress solver | `agent/arbiter.py` |
| Fuzzy primitives | `agent/fuzzy.py` |
| Combat geometry & selection | `agent/combat.py` |
| Family counters | `agent/enemies.py` |
| Boss movement | `agent/bosses.py` |
| Grabs / weapons / enemy escape | `agent/grabs.py` |
| Expert back-protection goals | `agent/expert.py` |
| Crossover plan state machine | `agent/autoplanner.py` |
| Police pressure | `agent/pressure.py` |
| Co-op safety & fairness | `agent/coop.py` |
| Character ranges & biases | `agent/characters.py` |
| Stage advice, Mr. X | `agent/stage.py` |
| Holes, breakables, stuck | `agent/navigation.py` |
| Walk latch | `agent/walk.py` |
| Rule inference engine | `agent/inference.py` |
| Snapshot / RAM map | `state.py`, `memory_map.py`, `world_map.py`, `phases.py` |
| Evaluator | `evaluation.py` |

---

## 13. Design principles (do not violate lightly)

1. **Explainable**: every decision has a note; graphs and fired rules retain
   traces for pressure and expert goals.
2. **Hard ROM guards first**: soft scores cannot make illegal actions legal.
3. **Deterministic**: no random combat mixes; evaluation episodes comparable.
4. **Face-then-hit**: no air punches, no reverse punches, lane before X.
5. **Jump-kick is sequenced C then B**, never C+B (rear).
6. **Back security over greed**: protect rear before optimal front DPS.
7. **Never friendly-fire**: final co-op gate on every seat.
8. **Latched navigation**: no per-poll detour thrash or walk re-aim flicker.
9. **Injectable boundary**: future learned models may propose weights or
   candidates, but must not bypass ROM-state guards or this pipeline’s
   feasibility rules.
10. **This document tracks behaviour**: if you change a rule in code, change
    the matching section here in the same change set.

---

## 14. Out of scope / deferred

- Host `--altControls` (split pickup / remapped face buttons).
- Frame-perfect TAS scripts and full per-animation move tables.
- Neural policy training (evaluator is the intended future boundary).
- Attract-mode discrimination beyond current game-state gates.

---

*End of AI specification. Keep in sync with `src/sor_autoplay/agent/`.*
