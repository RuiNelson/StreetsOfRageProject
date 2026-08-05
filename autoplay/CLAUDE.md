# SoR Autoplay — agent notes

## Role

`autoplay/` is a Python project that attaches to a running
`StreetsOfRageRecompilation` (`sor`) process via
`MegaDriveEnvironment`'s `megadrive_remote` client.

**Current scope:** maximized-window observer (mode, characters, health, lives,
specials, timer, level, scores, 2D world map) **plus** optional scripted agents
that inject standard-control input through `press_buttons`.

## Ownership

- Project-owned directory in the StreetsOfRageProject workspace.
- Prefer keeping implementation here; do not fork the remote protocol.
- Consume `MegaDriveEnvironment/python` (`megadrive_remote`) as a library
  (`PYTHONPATH` or install). Do not copy wire-protocol code.

## Commands

```bash
# Host (meta-repo root) — do NOT use --altControls with the agents yet
./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debugUtils --port 6969

# Observer + AI (meta-repo wrapper; defaults host 127.0.0.1 port 6969)
./scripts/autoplay
./scripts/autoplay --agent-p1
./scripts/autoplay --agent-p1 --agent-p2
./scripts/autoplay --once
./scripts/autoplay --poll-ms 33

# Or direct module invoke
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
PYTHONPATH=src python3.11 -m unittest discover -s tests -q

# Deterministic live evaluation (host must already be running)
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay.evaluation \
  --restart-character axel --decisions 600 --max-damage 12 \
  --max-damage-events 3 --max-lives-lost 0 --max-failed-pickups 0 \
  --max-failed-ground-attack-starts 0 \
  --min-enemy-damage 15 --min-forward-progress 600 \
  --trace /tmp/sor-autoplay-eval.jsonl
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

## Agent design (standard controls only)

Code: `src/sor_autoplay/agent/`. The notes below are a quick checkpoint for
agents working in this tree.

**Controls assumption:** OPTIONS scheme 0 and **no** host `--altControls`.

| Physical | Role | `Buttons` |
|---|---|---|
| B | Attack / pickup | `Buttons.B` |
| C | Jump | `Buttons.C` |
| A | Police special | `Buttons.A` |
| D-pad | Move | UP/DOWN/LEFT/RIGHT |

`--altControls` remaps A/X/Y and splits pickup from attack; agents do not support
that layout yet.

### Behaviour pipeline (mode → skill → free)

Architecture migration in progress. Per seat, each decision is:

1. **`DecisionContext`** (`agent/context.py`) — one bag of snapshot, seat
   memory, profile, stage advice, coop, mode, graph, pressure.
2. **`PlayerMode`** (exclusive ROM partition) — `DIALOG`, `CONTINUE_UI`,
   `NOT_PLAYABLE`, `ENEMY_HELD`, `HURT`, `GRAB_ANIM`, `AIRBORNE`, `HOLDING`,
   `FREE`. `CONTINUE_UI` drives type-`$0F` high-score name entry (**C** to
   place; B is backspace in `$57D2`) then continue Yes (UP if needed, then
   B); seats remain drivable after the player-mode bit is cleared on death.
3. **`Commitment` / skills** (`agent/skills.py`) — at most one multi-frame
   skill owns the seat. First skills:
   - `EnemyGrabEscape` — `$78–$7E` C then B counter window
   - `CrossoverSuplex` — expert + `AutoPlanner` for exposed-back hold
   - `HoldResolve` — ordinary hold/weapon tree + grab-animation lockout
4. **Police special** (after crossover plan, before ordinary hold)
5. **`_decide_free`** — airborne, moving props, arbiter fight/loot/progress,
   combat, breakables, navigation (still a ladder; lift to skills later)

`AgentState` holds `SeatMemory` per seat (`p1`/`p2`) with walk, nav, planner,
goal, grab latches, and `commitment`. Attribute aliases (`p1_walk`, …) remain
for tests/HUD.

### Behaviour (priority — same outcomes as before the pipeline)

1. Steady (no input) while paused or police special is active
2. Mr. X offer: always hold **DOWN+A** to refuse (never idle on bit4 /
   “mr.x wait”; never YES)
3. **Enemy-held skill** then **expert + crossover-suplex skill**
   (`agent/skills.py` → `inference.py`, `expert.py`, `autoplanner.py`):
   If a front hold (`$60/$61`) leaves another live hostile behind the player,
   protect the back with **C → wait → B**. C enters crossover `$76/$77` (or
   `$80/$81`); B at confirmed back hold `$66/$67` enters suplex `$68/$69`.
   Plans persist across snapshots, tolerate one missing hold observation, time
   out safely, and take ownership before police and ordinary grab heuristics.
4. **Knowledge graph + fuzzy inference + constrained solver**
   (`agent/knowledge.py`, `fuzzy.py`, `arbiter.py`): build typed relations from
   each coherent snapshot, fuzzify genuinely graded facts, enumerate feasible
   fight/loot/progress goals, then choose the deterministic maximum utility.
   Hard reachability and progression constraints always precede preferences.
   Target and goal hysteresis add a small persistence bonus. Keep this boundary
   explainable and injectable so future learned models can propose weights or
   candidates without bypassing ROM-state guards.
4b. **Symbolic navigation** (`agent/navigation.py` + `NavMemory` in policy):
   terrain facts from the collision-class hole map drive a latched plan
   `DETOUR → ADVANCE` around pits (stage 4). Once a hole blocks progress,
   commit to one safe lane and finish vertical motion before resuming X —
   never recompute the detour side every poll (that caused UP/DOWN shakiness).
   Emergency escape only rewrites input when already inside a pit AABB.
   Breakables: side-only approach (`breakable_side_approach`) — when stacked
   on the prop's X, first move to a horizontal stand-off at the current lane,
   then match lane; never smash from pure top/bottom. Both stand-offs are
   scored against holes; a pit on one side (e.g. hole left of crate) latches
   the solid side only so the agent does not thrash. Jump starts (combat,
   Signal sweep, jump-break) require `jump_landing_safe` so kick arcs do not
   land in holes. **Stuck recovery**: if world position does not move by ≥3px
   for ~8 polls, cycle open-loop cardinal escapes (up/down/left/right) and
   ban failed headings. Walk latches no longer re-aim every `force` refresh
   (that kept holding into the same wall). Perpendicular unstuck headings are
   not cleared just because the goal shares the current lane Y/X.
5. Police special when fuzzy pressure score ≥ threshold and specials remain
   (not round 8). Pressure combines crowd size, hunters, active attacks,
   surrounding geometry, bosses, and health and retains its fired-rule trace.
   Conserve stock during small full-health skirmishes. Eligible spends are a
   crowd of at least four, health at or below 40% with a reachable threat, or
   any reachable live boss; a boss forces maximum pressure and the first legal
   grounded A edge immediately.
6. **Hold-resolve skill** (`agent/skills.py` → `grabs.py`, `weapons.py`): ROM
   hold finishes are **profile-driven**, not knee-spam by default:
   - **B+back throw** when `prefer_throw` (all three characters) or after
     `grab_knees` pulses; back = opposite action-state facing bit0.
   - **C vault → back hold → B suplex** when `prefer_vault` (Adam/Blaze) on
     front hold `$60`, unless co-op forces an immediate away throw.
   - Back hold `$66` always **B suplex**.
   - B alone / B+Up is only the knee path when a profile still requests knees
     (`grab_knees > 0` and not yet past that count).
   A hold needs a dedicated held field or the grabbed enemy's reciprocal player
   link; the latch bridges only one missing observer sample so stale
   contact/reaction state cannot create an empty knee/throw loop. Exact orphan
   state `$60` with only a stale `+$4C` pointer gets one B edge; live this
   transitions `$60 -> $6A -> $02` in 16 frames. Also bat/pipe swing; throwable
   weapons. A carried
   weapon is not a combat target or a reason to press B: with no live foe, or
   with a foe outside the ROM range band, weapon policy returns control to
   free combat (walk to weapon stand-off). Math lives in `agent/weapons.py`:
   damage 5/3/4/4/2, bat/pipe origin reach 36, preferred stand
   `approach_stand_dx` (knife 96, pepper 72, bat/pipe 30, bottle 28). Armed
   B is planted without D-pad walk-in; same-lane `too_close_dx` backs out
   before re-engaging. Free combat never parks armed seats at unarmed punch
   range or body-grab walks. Knife same B: ROM `$3084` picks melee `$46` if
   front ≤144 px else throw `$44`; policy stabs in-cone, throws past cone only
   for one-shot kills (else walks to knife stand 96). Pepper stun 160f; bottle
   not attack-thrown.
   Utility `U = 0.45·(D/5)+0.35·range+0.20·control` drives pickup upgrades;
   otherwise free stage/combat movement closes to the weapon stand. Weapon holds never enter the enemy-grab latch,
   and B is emitted only from input-ready ground actions (ordinary `$02–$0E`
   or held-weapon `$30–$3A`), never repeatedly through `$44/$6x` animations.
   After pepper spray fires, `+$60` clears but `+$5E` can keep pointing at its
   projectile; `+$5E` alone is therefore not enemy-grab evidence. Enemy holds
   require a reciprocal GRABBED link or a non-weapon `+$60` type.
   A reciprocal grabbed-enemy link overrides a stale weapon type. B/C inputs
   are legal only in confirmed hold windows; `$62/$64/$68/$6A/$6C/$6E` are
   unconditional animation locks even after pointers clear. Retry a rejected
   crossover twice, then resolve the hold with a direct B rather than waiting
   for the long planner timeout.
7. 2P mid-air assist when both agents and partner is airborne nearby
7b. **Never attack other players** (`agent/coop.py`): SoR1 has friendly fire.
   Body-close partners block any B; otherwise a wide directional strike/throw
   /rear cone applies. **Final `guard_attack_intent`** runs on every seat
   before `mask_from_intent`, so no combat/weapon/planner/grab path can emit
   B or B+C into a live partner. Prefer clearing their lane when blocked.
   Grab throws prefer the side away from the partner. The sole intentional
   near-partner attack is the 2P air assist, and only when the partner is in
   a jump **action** family — never `world_z` (standing elevation is always
   large and previously false-triggered assist forever).
8. Pick up weapons/items only when the constrained solver selects loot;
   immediate danger and a blocking boss make loot infeasible. Health/life/
   special still obey co-op fairness.
   - ROM routine `$3136` accepts only X ±20, Y ±16, Z ±8. Walk inside a
     conservative X ±16, Y ±12, Z ±6 box, and emit B only from a grounded
     action state; otherwise wait for the current animation to finish
   - Held weapons do not suppress weapon observations. Assign fuzzy value from
     ROM damage/range/control plus character preferences and pick a ground
     weapon only when it improves the carried type by a material margin. Fight
     constraints still outrank the upgrade.
9. **Face-then-hit combat** (`agent/combat.py` + `enemies.py`):
   - Player facing = action-state `+$30` **bit 0** (set = face left)
   - Punch only when same lane (Y ≤ ±12), within strike range, and facing foe
   - Turn one tick before attack if facing the wrong way (no air / reverse punches)
   - During normal action `$18`, queue the next combo B edge only while player
     `+$58` bit 5 is clear; stop sending B after the ROM has accepted the edge
   - `CounterPlan.max_combo_hits` caps combo depth per family/boss (seat
     `combo_hits`, reset to 1 on the fresh punch, `+= 1` per queued edge).
     Antonio caps at 2 (user-reported, not ROM-confirmed: his power kick can
     break a committed combo or grab) — refusing to chain at all was tried
     first and rejected: the ROM's own recovery lock already forces standing
     still through the first hit's animation regardless of what is pressed,
     so a single-hit cap bought no real safety while giving up most of the
     damage. Two fast hits, skip the combo's slower finisher, pending a live
     trace of the actual counter window
   - Match lane before **punching** (off-lane "close" was the air-punch bug).
     When off-lane, still walk to the horizontal stand-off (`foe.x ±
     approach_offset`), not pure-Y at the current X: a foe approaching on a
     diagonal closes X while pure-Y lane match arrives chest-to-chest for a
     free punch or body-grab. `can_punch` still refuses B until Y aligns
   - First-punch live hitboxes reach 57 px Axel, 54 px Adam, 68 px Blaze;
     policy strike ranges retain a 4–6 px inner margin and stand at
     `approach_offset` 44–56 rather than body-grab range (~≤18)
   - Ordinary enemy `+$30` is a byte state, with flags in `+$31`. Round-1
     Garcia type `$22` uses `$09` for approach/wind-up and `$0A` for its active
     punch. Decode both as dangerous: when aligned, start a grounded interrupt
     up to 24 px before static hitbox overlap so the closing enemy enters the
     active frame; at 13–20 px lane separation, move toward a fixed escape goal
     because enemy punches still connect there, then wait once safely off-lane
   - Type `$22` states `$0F/$10/$11/$13` and Signal `$24` states `$08-$0C`
     are also family charge/attack paths. Shared state `$02` is contact
     recovery, not a new attack. Basic enemies inside the 24 px startup lead
     are intercepted even if a whole short attack transition falls between
     four-frame observations
   - Signal state `$08` at `$E5EC` selects its attack and can enter the low
     sweep at state `$0B`; `$E80A` starts animation `$18` with X velocity
     `$00070000`. When lane-aligned within 120 px, start C before the generic
     punch interrupt. Unarmed `$12/$13` free flight then emits B for a jump
     kick. A held weapon changes grounded idle to `$30–$3A`; ROM routine `$3010`
     accepts C there and enters the `$3C–$42` weapon-jump family, which evades
     the sweep without injecting unsupported airborne weapon attacks
   - Jack type `$27` is a combatant, not a projectile; only its type `$28`
     helper uses the projectile-dodge plan. Dispatcher `$F27E` uses the table
     at ROM `$1037C`. Jack state `$0C` (`$F55E`) sets bit 0 of object `+$52`
     and creates/attaches a `$28` helper when needed. State `$0E` (`$F410`)
     clears `+$52` before launching the helper. **Punches land while armed**
     (ROM `$9B88` does not gate damage on `+$52`). **Grabs do not while
     armed**: `ARMED` is not `GRABBABLE`; `THROWING` (`$0E`) and unarmed are
     grabbable — close and grab during the throw window. Never restore an
     `AIR_ATTACK_ONLY` rule. Type-`$28` state `$01` is `ATTACHED` (not
     dangerous); `$02-$04` are `LAUNCHED`/`DANGEROUS`. Family counters: Nora
     prefers grab+knee/throw; Signal prefers mid/far C→B jump kicks; back
     security: when a rear hostile is inside the B+C window, free combat fires
     the rear chord first; only distant rear threats elevate grab→crossover
     on a legal front target.
   - Type `$22` state `$0B` dispatches through ROM table `$DD80` to `$E20A`
     and is dangerous; live it retained outgoing damage `$04` at zero health.
     Enemy health uses a signed lethal check: `0` is still active and needs a
     finishing hit to underflow to `$FFFF`. Keep zero-health objects visible
     and targetable until their attack ends and the lethal/death state appears.
     Once health is signed-negative (`$8000-$FFFF`), treat the allocated floor
     object as the hard graph fact `DEFEATED` regardless of any stale action
     family: it is never reachable, dangerous, blocking, selected, or chased
   - Enemy-held player actions are `$78/$7A/$7C/$7E`. ROM handlers
     `$2606` and `$26B0` prove the counter protocol: C in `$7A` starts `$7C`;
     `$7C` sets `+$58.bit7`, an eight-tick `+$62` window, and returns to `$7A`;
     B in that window enters counter throw `$7E`. Own the complete sequence,
     emit the two edges separately, and wait through the closed animations
   - **Throw victim / knockdown locks** (`PlayerMode.HURT`): action families
     `$50–$5F` (knockdown), `$70–$74` (ordinary throw air/recovery tail), and
     `$82–$8F` (special-throw choreography). Do **not** run free combat, walk,
     or B edges there — the ROM ignores voluntary attack/jump on those frames.
   - **Hold B routing** (`$2BA8`): B alone / B+Up / B+forward = knee `$6A`;
     **B+back** only = throw `$62`/`$64`. Up/Down never select the throw.
   - **C+Up landing tech** (bounce cancel): special throw releases arm player
     `+$45`; while air family `$5C`/`$72`/`$88` and `+$45` is set, HURT mode
     emits **Up held + C edge** to latch `+$46` so `$3F24` lands as jump `$14`
     instead of bounce → `$54`. Ordinary street throw `$84→$72` does **not**
     set `+$45` — stay idle. Observe `+$45`/`+$46` via world map
     `tech_armed`/`tech_latched`. Skill path:
     `grabs.decide_hurt_or_throw_reaction` / seat `throw_land_tech` memory.

### Player move coverage (agent vs ROM)

| Move | ROM input / actions | Agent |
|---|---|---|
| Walk / lane | D-pad | Yes (`walk` latch) |
| Punch / combo | B ground `$18+` | Yes (`combat` + combo bit5) |
| Rear / escape | B+C chord `$20+` (Adam `$22→$24`) | Yes (`rear_hit_window`) |
| Jump | C → `$10` | Yes |
| Jump-kick | C then B in `$12` | Yes (`jump_kick` solver) |
| Weapon jump | C while `$30–$3A` → `$3C+` | Yes (Signal sweep path) |
| Pickup | B near free item | Yes (loot arbiter + box) |
| Police special | A edge | Yes (pressure gate) |
| Grab (walk-in) | body contact → `$60` | Yes (approach / grab_bias) |
| Hold knee | B / B+Up / B+front → `$6A` | Yes only if `grab_knees` left |
| Hold throw | **B+back** → `$62`/`$64` | Yes (`prefer_throw`) |
| Hold vault | C → `$76`/`$80` → `$66` | Yes (`prefer_vault` + planner) |
| Suplex | B on `$66` → `$68` | Yes |
| Crossover-suplex plan | back threat / crowd | Yes (`CrossoverSuplexSkill`) |
| Partner vault boost | C off ally → high C → air B | Yes (`partner_boost`) |
| Enemy-held counter | C then B `$7A–$7E` | Yes (`EnemyGrabEscape`) |
| Throw-victim lock | `$50–$5F`, `$70–$74`, `$82–$8F` | Yes (`HURT` idle) |
| Land tech C+Up | `+$45` + C edge + Up | Yes (special throws only) |
| Knife melee/throw | same B; cone `$90` | Yes (`weapons`) |
| Pepper throw | B `$44` | Yes |
| Bat/pipe swing | B in reach | Yes |
| Bottle | not attack-thrown | Yes (melee dump only) |
| Mr. X offer | always NO (DOWN+A) | Yes |

**Not agent goals (by design):** B+Up as a distinct throw (ROM treats as knee);
air tech on ordinary street throws without `+$45`; 6-button `--altControls`.

   - A committed attacker can be turned toward and punched in the same input;
     a separate four-frame facing decision is too slow. Lane evasion respects
     the ordinary-enemy `$02-$70` bounds and retreats on X at either edge
   - **Jump-kick = C, then B specifically in free-flight `$12/$13`** (never
     C+B together — that is rear attack). The ROM sequence is `$10` launch,
     `$12` free flight, `$16` air attack, `$14` landing. Do not send B during
     launch or landing. Airborne is action `$10–$17` (not world_z; ground Z is
     about `$A0`). Solver: `agent/jump_kick.py` predicts multi-enemy hits and
     arms seat `jump_kick` memory so free flight fires B on the solved delay;
     `attack_mix` prefers packs when the plan scores ≥2 hits.
   - **Rear attack (B+C)** is a contact move, not a reaching one: attack box
     `+$70` is player X −7..+3 by Y ±8. Measured chord timeline (startup /
     damaging frames / damage / recovery): Axel 3/10/3/17, Blaze 7/17/2/30,
     Adam 23/21/3/44 — Adam's is a `$22→$24` hop landing in `$14`, not a
     backfist. `combat.rear_hit_window` therefore fires only when the foe is
     inside that body box, or will walk into it during startup+active frames;
     Adam additionally refuses a foe already at contact (his startup loses to
     the enemy's own strike). The chord holds the seat for its full recovery
     via `attack_cd`, and needs an input-ready ground action.
     `combat.enemy_is_behind`'s generic side-classification dead zone
     (`min_dist`, 10px default) must stay separate from this per-character
     `near` bound: `can_rear_hit` passes `min_dist=0` so a point-blank foe
     inside Axel/Blaze's small measured `near` (1px/0px) still connects —
     it previously fell through the generic 10px zone unhit.
   - **Rear B+C outranks front grab-shield** whenever `can_rear_hit` is true:
     free combat emits the chord before walking into a front hold while a
     hostile already sits on the back arc (main free-damage failure mode).
     Grab→crossover-suplex remains only for *distant* rear threats outside
     the chord window. Search uses `REAR_REACT_RANGE` (96 px), not the static
     box alone, so closing foes still arm the chord.

   - Breakables (phone booth / crate): walk in → smash (B) or mid-range
     jump-break; then loot spilled pickups/weapons
     - Later rounds use distinct ROM object families rather than the early
       type-`$11/$19` props: level indexes 2/3/4/5/7 use smashable types
       `$18`; `$1B/$1C/$1D`; `$1F`; `$41`; and `$45`, respectively. Intact
       props have primary byte `+$30 = $01`. Broken originals and same-type
       debris in later states are not targets; type `$11` fragments also use
       nonzero `+$31`, while `$18/$1D/$41` debris use nonzero `+$0B`.
     - Round-8 type `$45` records with nonzero script parameter `+$40` move
       horizontally, follow a player's lane, and expose outgoing damage 3.
       They remain smashable breakables but carry an ATTACKING observation
       phase while damage is active. Round-6 type `$42` is different: its
       moving vertical state machine exposes damage `$14` but has no
       player-hit destruction path, so observe it as an avoid-only **press**.
       The machine body is a solid navigation AABB (cannot walk through);
       same-lane approach or stand-under forces a lane leave before progress.
       Presses are excluded from combat targeting. A seeded live trace measured
       `$45` advancing 12 px per four-frame decision. Leave its lane inside
       220 px, hold the safe lane until it passes, and smash only when already
       in grounded punch range; never chase it with the static-crate stand point.
   - Deterministic attack choice; jump-ins only when an enemy-family counter
     explicitly asks for one (for example Haku-Ro), not from character reach
   - Fuzzy target utility weighs proximity, lane access, danger/ranged attacks,
     punishability, boss status, and `targets_player`. At equal geometry the
     tier is boss > Jack > Nora > Signal > Haku-Ro/ninja > Garcia, while a
     materially closer or immediately dangerous lower-tier foe can still win;
     keep the current target unless a challenger wins by a material margin
   - Generic charge/sidestep retreat applies only inside the 100 px reaction
     radius. A distant Antonio is approached rather than fled from
   - A boss decoded as CHARGE but waiting in a distant Y lane is deliberately
     re-aligned with; do not enter the ordinary-enemy `guard lane` fixed point
   - Antonio's linked boomerang/attack object is type `$96`
     (`ai-analysis/enemy-ai.md` "$16CF4 antonio family table" — follows him
     during wind-up/catch, independently active during the throw). It had no
     `object_catalog` entry, so it was never a `MapEntity` and the whole agent
     was blind to it; catalogued in `_BOSS_PROJECTILE_STYLES` as an
     always-dangerous `projectile` (no confirmed attached/launched split like
     Jack's `$28`, so no state-based exception) and dispatched by `type_id` in
     `enemies._TYPE_PLANS` — a family-label lookup would have returned
     Antonio's own body plan instead, since the object shares his "Antonio"
     family. Fixed alongside a real, previously-untested sign inversion in the
     generic projectile-dodge goal (`policy._decide_free`): it was walking the
     player *toward* `approach_vector`'s evade intent, not away from it,
     applying to every ranged dodge (Jack's axe/torch too, not just Antonio)
   - Souther (type `$55`) and Onihime/Yasha (type `$58`) both use primary
     state `$02` for live attacks even when tactical `+$67` is zero:
     `$16118` is Souther's claw/contact state and `$15D0C` is the twins'
     damaging jump/grab choreography. Keep grounded against Souther; leave a
     committed boss attack lane. Twin phase decode: only primary `$02` or
     tactical `$02`/`$03` is DANGEROUS — chase `$01` is NORMAL and must be
     struck (a prior `t!=0→ATTACKING` bug caused perpetual evade). The twins
     have **no dedicated AI**: they run through the generic combat ladder.
10. Route around floor holes (stage 4), factory presses (stage 6), and hold
    the elevator (stage 7)
    - Stage-4 horizontal progression must turn into a persistent vertical
      detour at a pit, cross beside it, then resume X; never reverse X forever
      at the first blocked collision cell
    - Round 6 (level index 5): type-`$42` is the crusher (damage / Z motion).
      The **path** is blocked by collision-class **2** machine walls on the
      upper lanes (class 1 floor stays free on lower lanes). Snapshot field
      `floor_barriers` is always merged into nav solids (except elevator).
      Also avoid standing in the `$42` crush band (`press_bypass_goal`).
    - Round 7 (level index 6) is a fixed moving elevator/gauntlet. Its platform
      is not represented by the static collision-class map, so class-0 cells
      are not holes. With no combat target, clear any old horizontal walk
      latch, center only on lane `$50`, and emit no LEFT/RIGHT progression
11. Progress right (stage 8: left) only when the graph has no blocker
12. **Mid-field hold on locked waves** (`combat.midfield_hold_goal`): ordinary
    enemies spawn on the progress edge and the camera will not scroll until
    the pack is dead. Chasing them pins the player against the walk clamp
    (map_x ≈ 288 / 32) and eats free damage. While a live ordinary foe is
    still more than ~110 px ahead on X, park at CRT mid (`map_x≈160`) and
    wait; close only after they enter that engage band. Bosses and
    projectiles never mid-hold (Antonio at the scroll boundary still
    approaches). A fight goal without an extractable target also parks mid
    rather than falling through to stage progress.

Map entities carry full combat RAM for agents:

- `primary_state` (word +$30): ordinary `$0100` normal / `$0300` knockdown /
  `$0500` grabbed / `$0600` death / `$0700` blocked
- `tactical` (boss +$67), `pair_role` (+$5D), `target_ptr` (who they hunt)
- `mode_flags` (later-boss +$7B), `target_unavailable`
  (+$77 from `$179F8`), `phase_timer` (+$78 jump/throw timeline)
- `boss_dist_x` / `boss_dist_lane` (later-boss geometry)
- `family_state` (ordinary `+$52`; Jack bit0 is weapon attached)
- `combat_phase` decoded in `phases.py` → map outline colours + agent punish/evade

HUD map: phase outline (green=down, orange=charge, red=atk…), hunt counts,
phase tallies in the map meta line.

### UI

- Per-player **AI ON/OFF** buttons in the P1/P2 columns
- Keys **1** / **2** toggle P1 / P2 agents
- CLI: `--agent-p1`, `--agent-p2`, `--agent-hold-frames N`

Input is applied on the same remote poll thread as RAM reads (one client
connection). Agents use sticky **`hold_buttons`** (remote command `0x14`) so
D-pad directions stay latched between polls — continuous walking. Any mask
containing A/B/C is sent as a blocking VSync `press_buttons` pulse so the ROM
sees a fresh `+$55` edge; its D-pad component is then re-latched. Notes never
select the input transport. `press_buttons` is also the fallback for older
hosts, where it releases after N frames and produces walk-taps.

**Rebuild** `MegaDriveEnvironment` + `sor` after pulling so the host serves
`HOLD_BUTTONS`. Without it the client falls back to `press_buttons`.

### Walk-to-(x, y)

`agent/walk.py` latches a **world-space** goal per player. While active, the
same D-pad signs are held every tick until the player is on the goal band or
has **passed through** it on both axes. Combat in range, grabs, police, and
hurt clear the walk. Progress / approach / loot only *set or refresh* the goal
(nearby refreshes keep the latch).

## Design constraints

- Prefer small multi-byte `read_memory` windows over many single-byte reads.
- **Snapshot cadence is wall-clock polling, not VSync waits** (when agents off).
  Default `--poll-ms 33` (~2 frames at 60 Hz).
- HUD must stay visually clear (corner status + map). Prefer maximized normal
  window over exclusive fullscreen.
- Do not commit ROMs, captures, or build artifacts.
- Never leave a background `sor` process running after local experiments; use
  `timeout -k` when scripting launches.
- Robust deterministic gameplay regression testing is a project requirement
  and the foundation for future learning. `evaluation.py` owns the stable
  lockstep boundary: policies consume `GameSnapshot` and return
  `AgentDecision`; tests and learned policies must retain its metrics and
  scenario thresholds so results remain directly comparable. Face buttons are
  pulsed for three frames and released for the remaining frame in every exact
  four-frame decision step. JSONL traces belong outside the repository.
  `weapon_attack_edges`, `weapon_air_attack_edges`, `signal_sweep_jumps`,
  `ground_attack_attempts`, `ground_attack_starts`,
  `failed_ground_attack_starts`,
  `jack_armed_ground_attacks`, `jack_armed_jump_starts`, and
  `jack_throw_window_ground_attacks`
  are first-class metrics; Stage-2 runs can enforce
  `--max-weapon-air-attacks 0 --min-signal-sweep-jumps 1`. A controlled Jack
  encounter can enforce `--min-jack-armed-ground-attacks 1` to prove that
  armed-body attacks remain legal for scripted or future learned policies.
  Enforce `--max-failed-ground-attack-starts 0` to catch cases where the policy
  emits B from an input-ready ground action but the ROM action handler never
  leaves an input-ready state.
  Back protection is likewise observable through
  `back_exposed_grab_opportunities`, `missed_back_exposure_responses`,
  `crossover_suplex_starts`, and `suplexes`; enforce it with
  `--max-missed-back-exposures 0` and, in a scenario known to contain the
  opportunity, `--min-suplexes 1`.
  Symbolic arbitration/execution regressions are first-class too:
  `invalid_grab_animation_attacks`, `unreachable_enemy_stall_steps`,
  `loot_under_threat_steps`, `boss_progress_steps`,
  `missed_enemy_grab_escape_responses`, `defeated_enemy_attack_edges`, and
  `defeated_enemy_pursuit_steps`;
  normally enforce all their corresponding `--max-*` thresholds at zero.
  Enemy-held-player scenarios additionally expose
  `enemy_grab_escape_jump_edges` and `enemy_grab_counter_throw_edges`, gated by
  `--min-enemy-grab-escape-jumps` and `--min-enemy-grab-counter-throws`.
  `boss_stall_steps` begins after eight consecutive input-ready `guard lane`
  decisions against a blocking boss; enforce `--max-boss-stalls 0` to catch
  the Antonio cross-lane fixed point without rejecting a brief guard.
  Special-resource and stage mechanics are first-class metrics:
  `special_calls`, `wasteful_special_calls`, `boss_special_opportunities`,
  `missed_boss_special_calls`, `elevator_horizontal_progress_steps`,
  `moving_breakable_threat_steps`, `moving_breakable_response_steps`, and
  `missed_moving_breakable_responses`. Normally enforce
  `--max-wasteful-specials 0 --max-missed-boss-specials 0
  --max-elevator-horizontal-progress 0 --max-missed-moving-breakables 0`.
  JSONL actors include intact breakables and their outgoing `damage`.
  A host `TimeoutError` during a decision produces a partial failing report
  with the exact decision index; do not discard the metrics/trace behind an
  unhandled exception.
- Use evaluator `--restart-character` for comparable episodes. It restarts,
  navigates menus, verifies the player/health/game state, and enables lockstep
  on the same connection before returning control; a separate setup process
  leaves an uncontrolled frame gap and is not a comparable scenario start.
- `--kill-non-bosses` clears ordinary enemies with the host `K` cheat on every
  decision where **no boss is alive**, so a boss episode does not spend its
  decisions on the waves in front of the encounter. The guard is mandatory:
  `killInstantiatedEnemies` sweeps bosses too. Measurement-setup only — it
  changes what the episode fought through, so do not compare a swept episode
  against an unswept one.
- `--restart-level 1..8` composes that path with the `--debugUtils` level
  hotkey, waits for spawn completion, verifies `$FFFF02`, then relocks and
  reseeds. Use it for repeatable later-round geometry, prop, and boss episodes.
- Deterministic evaluation seeds the ROM RNG long at `$FFFFFF40` and the VBlank frame
  phase word at `$FFFFFB08` after enabling lockstep. These writes are test
  setup only; the evaluated AI still acts solely through controller inputs.
  Reports include the starting 64 KiB work-RAM SHA-256. Use acceptance
  thresholds across episodes rather than assuming host state outside work RAM
  is bit-identical.

## Key RAM (verified from analysis)

See `src/sor_autoplay/memory_map.py` and
`StreetsOfRageRecompilation/code-analysis/addresses.csv`.

- Health: binary word `0..0x50` at player object `+$32`
- Lives / specials: packed-BCD bytes at `$FFFF20+`
- Scores: packed-BCD longwords at `$FFFF08` / `$FFFF10` (mask dirty high bits)
- Timer: `$FFFB00` BCD-like word; wave seeds `$40`/`$50`/`$60`
- Character IDs: 0=Axel, 1=Adam, 2=Blaze
- `player_mode`: bit mask, not a 1/2 enum alone
- Map actors: P1/P2 at `$FFB800`/`$FFB880`; **66**×`$80` table at `$FFB900`
- Map plot (top-down visualization):  
  `map_x = world_x - cam_x`, `map_y = lane_y` (`+$10` / `+$14`)  
  Elevation `world_z` (`+$18`) is stored for agents but **not** used on the map.
  HUD maps the wider **view** (camera + off-screen ring) and draws the true
  **camera** as a dashed 32..288 × 0..lane_max subset (ROM walk clamp, not the
  full 320 CRT). Off-camera markers stay visible (dim letters). Markers are a
  single letter plus a square **outline** for combat/item state (no filled
  discs, no phase letter suffix).
- Sprite CRT formula (`lane/2 + z`) lives in `project_to_screen()` for later use.
- Playable bounds from `clamp_players_to_gameplay_bounds` (`$43AA`):
  - X: `map_x ∈ [$20, $20+$100]` = `[32, 288]` (left = `cam_x+$20`, span `$100`)
  - Y: ∈ `[$02,$70]` (or `[$02,$A0]` on level index 6)
  Camera box uses that X band and the lane max for height. Live left-limit
  check: `world_x - cam_x == 32`. Agent on-screen checks still use `0..320`.
- Ground weapons/pickups: ROM `$3136` requires free objects — weapon `+$51==0`
  and `+$50<3`, pickup `+$51==0`. Exposed as `MapEntity.interaction` /
  `item_param` and `is_free_ground_item`; only free items inside
  `is_in_loot_camera` (walk band 32..288 ± 16) get `COLLECTIBLE`.
- Dormant ordinary enemies are not observations or agent targets. At the start
  of round 2, for example, object 0 is type `$21`, flags `$09`, state `$0000`,
  health 0, and camera-relative X 80: RAM has a future spawn, but the renderer
  and player do not have an enemy. ROM activation `$937A/$A59C` holds flags
  bit0 while waiting; `$B1D6` advances +$30 to `$0100` on activation. Hidden
  enemies with nonzero state remain observed so hit-flash frames do not make a
  live target flicker out. Live off-screen actors can expand the **view** while
  the **camera** rect remains the player walk band (32..288 × lane). Agent
  combat targeting, danger, and police pressure use the strict CRT-relative
  `0..320` X band; the ROM's wider `-16..336` activation band (`$A59C` /
  `$97E6`) is not player visibility. **Loot** is tighter: free ground
  weapons/pickups are only `COLLECTIBLE` inside the walk band ± pickup reach
  (`map_x ∈ [16, 304]` via `is_in_loot_camera`), so dim/off-camera markers on
  the map ring are never loot goals. The tactical graph additionally rejects
  actors outside the level's playable lane. This fixes the Round-1 actors
  pre-created at lane Y `0`: keep them on the diagnostic map, but do not target
  or wait for them before their walk-through activation. Bosses are the narrow
  exception to strict X reachability (`0..384`): Antonio was observed at map X
  328 while already locking player scroll, so `BLOCKS_PROGRESS` and targeting
  must remain active there.
- apple = type `$4B`
- Pause: `$FFFA46 (pause_text_flag)` **nonzero** (written as 3, then often 1
  after `bclr #1` on the first paused frame)
- Police special: `$FFFA1A` nonzero (+ caller `$FFFA1C`)
- Floor holes: `$FFA000` collision-class map, class 0 = open/pit
  (query matches `sub_0000AD30`: x>>4, lane>>3, stride `$FFE02E`)
- Mr. X offer: `$FFDE00` flag (can stay set after refuse), `$FFDE04` word
  state; dialog mode only while **no live enemy/boss**; player `+$59`
  bit3=side (DOWN=NO, UP=YES), bit4=lock/choice enable (not a wait gate);
  agent holds DOWN+A every dialog tick
- Styles live in `object_catalog.py`; extraction in `world_map.py`
- Final Mr. X body is object type `$35` (boss); office `$33`/`$34` are skipped
- Boss holds: ordinary `$0500` GRABBED does not apply — detect via later-boss
  grabbee primaries `$06–$09` or player hold-family + body overlap, else
  knee/suplex never runs after a successful boss grab
- Agent modules: `agent/policy.py`, `context.py`, `skills.py`, `inference.py`,
  `expert.py`, `autoplanner.py`, `knowledge.py`, `fuzzy.py`, `arbiter.py`,
  `combat.py`, `pressure.py`, `stage.py`, `navigation.py`, `coop.py`,
  `characters.py`, `controls.py`
- Deterministic evaluator: `evaluation.py` (metrics, JSONL trace, acceptance
  criteria, injectable policy callable)

## Next milestones

- Optional `--altControls` mapping (deferred)
- Per-family named move tables from animation callbacks (deeper TAS path)
- Attract-vs-real-play discrimination if needed
- Optional transparent overlay instead of black stage
