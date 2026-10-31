# SoR Autoplay — agent notes

Python project attached to a running `sor` through `MegaDriveEnvironment`'s `megadrive_remote`: a window **observer** plus an opt-in **symbolic AI** that controls P1 and/or P2 through controller input only, **never RAM writes**. Off by default; enabled with `--agent-p1`/`--agent-p2` or the HUD's label.

This file holds rules, user decisions and what the code does not say. Architecture: [`AI.md`](AI.md). Module details: docstrings. ROM decodes: `StreetsOfRageRecompilation/ai-analysis/`. Old run-by-run measurements were removed; rerun the named tool for a current number.

## Layout

User decision (2026-10-30): the AI runs in two places from one copy of the code, the external `autoplay` and inside `sor` (**1 PLAYER AI ASSIST**).

- `ai-code/sor_ai/` is the **core**: `ai/`, the snapshot (`state`, `world_map`, `hazards`, `hitboxes`), `memory_map`, `remote_input`, and `embedded` (P2 as the host runs it, `InProcessClient`). No HUD, sockets or `megadrive_remote`: `tests/test_core_isolation.py` enforces it. `sor --ai-path` points at `ai-code`.
- `src/sor_autoplay/` is the **observer**: `app`, `hud`, `SoRClient` (`sor_remote`), `reach_gameplay`, `debug_scenario`, `host_flags`, `pathfind_viewer`. It imports `sor_ai`, never the reverse.

Consume `MegaDriveEnvironment/python` as a library; do not copy or fork the wire protocol.

## Commands

```bash
# From the meta-repo root
./scripts/run.py StreetsOfRageRecompilation/rom/SOR.bin --debug-utils --port 6969
./scripts/autoplay.py                 # defaults to 127.0.0.1:6969; --once, --poll-ms 33
./scripts/play.py --preset turbo      # live AI testing
./scripts/play.py --preset lockstep   # AI-driven clock
./scripts/pathfind_viewer.py          # standalone Tk, no host

# Direct
cd autoplay
PYTHONPATH=src:ai-code:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
```

Use Python 3.11+ with Tk (`_tkinter`); Homebrew 3.13/3.14 here may lack it. Debug scenario options need the host's `--debug-utils`: `--start-level N`, `--only-enemy FAMILY`, `--kill-street-enemies`, `--kill-until-mr-x`.

HUD: **Esc**/**Q** quit (and shut the host down); click "AI: OFF/ON" to toggle. Geometry is saved in `~/.config/sor-autoplay/window.json`; apply it after the UI is built, or the window drops to its minimum size. Translucent squares use `hud._blend_hex`, not `stipple`, which renders opaque on Aqua Tk. A player's range square reuses `ai/reach.py`'s numbers via `hud._display_attack_ranges`; never invent a second set for display.

## Testing

### Live AI testing

**No AI behaviour change ships unmeasured (user's no-regression rule):** measure it live before it goes to `main`. Unit tests and offline sims are evidence, not the measurement; a change measurable only offline goes to a branch and says so.

Never use 1x with the default 33 ms poll: `./scripts/play.py --preset turbo` (`--turbo 2`, `--poll-ms 16`, ~2 frames a tick; `PRESETS` in `play.py` is the source of truth). 4x needs `--poll-ms 8` and a fresh measurement. Results "at turbo 4" recorded before 2026-10-28 ran at 2x (a presentation cap, since lifted). Use `--silent`. Start a live session only when necessary; prefer unit tests for logic.

**Lockstep** (`--lockstep`, `app.py`'s `_lockstep_loop`, `play.py --preset lockstep`, port 6767): the host is frozen while an AI is engaged in play and each tick steps exactly 2 frames, so the stick lands exactly. ~174 fps on the dev machine. Entry cannot latch during a run-to-completion ROM load: a 2 s engage timeout plus retry rides those out.

**Poll timing:** `GameSnapshot.raw["uptime_frames"]` gives `poll timing:` DEBUG lines (`_record_frame_timing`). `kinematics.FRAMES_PER_TICK` deliberately stays the nominal 2: the lookaheads' constants were tuned to it (**The 30 Hz time axis**).

**Testing the AI against a boss (user).** `play.py --preset boss --level LEVEL`, or `tools/boss_fight.py`. Always sweep every other enemy family (`DebugScenario(kill_street_enemies=True)`): a boss measured with waves alive mixes two questions. Do not add a "real waves" mode; it was tried and rejected.

### Scoring a fight without the food

`--no-food` (`tokens.DebugNoFood`) whenever a fight is *scored*: `damage_taken` is a running minimum, and a plan that survives only because it ate is not a plan (user).

**And without the police** (user: "The police is allowed for Souther/Antonio, just don't test with the police on"). `--no-police` (`tokens.DebugNoPolice`) removes `CallPolice`; `boss_fight.py` defaults to it unless `--police`, labs and diags always do. In play it is the last resort: only below `POLICE_HEALTH_PERCENT_THRESHOLD` (or `_LAST_LIFE`), never for a crowd or a boss alone, with one exception:

**The round-end boss draws the police on arrival** (user: only for end-of-level bosses, not intermediate ones). `decide.level_end_boss_is_up`: round 1 Antonio, 2 Souther, 3 Abadede, 4 Bongo, 5 the twins, 6 the Souther pair (once both are up or one has fallen, since one call sweeps both; same wait in rounds 1-4 with two players). Out: round 6's Bongo, all of round 8's rush, Mr. X (the police cannot be called on his level), the duel. Scored 88, whatever the health. Against the twins this is the only call (never a fallback). Stateless: a second special would be called again after the sweep.

### Tick budget

**User: no tick over 2 ms; a slower tick is blindness on a weaker machine.** `app.py` warns on a `slow lockstep tick` (>= 8 ms) with the winning verb, `route_nodes` and `reached`. `tick_bench.py`, `jack_plan_bench.py`, `grunt_plan_bench.py` replay `--raw` recordings.

- `plan_route` tries solids first; a failed proof cannot be avoided by exact means, since it costs the reachable lattice. `NAV_MAX_NODES` and `DANGER_MAX_NODES` are both 10 (user: "para o jogo que é, é mais que suficiente"). At 10 the danger pass finds no detour round a committed reach except a lane change then X.
- **Replay contexts in a fixed order:** a context is a set, and tie-breaks depend on hash order across processes (`PYTHONHASHSEED=0` is not enough on 3.11), so the tools sort by `repr`.
- **Presses do not block the tick.** Presses use `QUEUE_PRESS_BUTTONS`, replying at once with the release frame. Two rules: the press **replaces** the latch while it plays, and `AgentLoop.tick` **skips** while `VirtualGamepad.press_pending` (a decision mid-press is about a body the press has not acted on). `_in_scripted_entry` exempts a scripted entry from `_crossing_would_walk_into_the_swing`.
- **Jack's plan inside the 2 ms budget (user).** ~1.0 ms with one Jack, exact (`plan_world` bounds the second update order; `ExactPlanTests`). Two to four Jacks still reach 2.6 ms.
- **Cheaper ticks for weaker machines (user: "tenho medo que não corra em CPUs mais fracos").** Exact: `hazards._class_cells` cached on `_scanned_rows` (the buffer's tail is live player RAM), and simulation hot paths inlined (`_hi` is `math.floor`, `Outcome` aliases, `twins._slot_copier`).
- **The cheaper search (user: A/B it, then ship the combined cut).** `HORIZON` 18, `FIRST_DURATIONS` (2, 6), `FINALISTS` 4: no worse live, ~30% cheaper. `BUDGET_MS` 8 + `STAGE_2_GRACE` 5 means a weaker CPU plays a shorter plan. Still over 2 ms with enemies on screen. Watch round 2 times.
- **Sealed corridors (user).** `Lattice.sealed_between` proves a wall between start and goal; the search then keeps `SEALED_MAX_NODES` (100). No in-game effect at 10 nodes. An empty route was rejected: the advance walks its best-effort vector to a pit's edge before hopping. If `NAV_MAX_NODES` is raised, re-run `stage_walk_diag.py --level 4`.
- **What 10 nodes needed: a finish that aims at every arrival.** `search._best_yx_by_rows` gives the cheapest Y-then-X finish over every arrival (`FinishAimTests`). `jump_landing_is_safe` asks for `advance_goal`'s strip at the landing X. Effect: an open-space `WalkToNearEnemy` closes the lane, then X. Measured offline only at the time. Open: the planner's lane band and the executor's (`LANE_EDGE_MARGIN`) differ, so a pit leaving room only in that margin gets an unwalkable route; the fix moves every routed verb.

## Diagnostic tools (`tools/`)

Not part of the AI and never imported by it. Each drives the **real** pipeline; `--help` has the options. They write RAM only through the host's documented `--debug-utils` hotkeys (`DebugScenario`). **Mandatory stop conditions:** do not run it, or any tool that drives a live host, without a real stop condition. Do not commit `.jsonl` runs or recordings (~4 MB a second).

| Kind | Tools |
| --- | --- |
| Score a fight | `boss_fight.py`, `jack_fight.py`, `grunt_fight.py`, `twins_2p_fight.py`, `mr_x_duel_fight.py`, `ai_assist_fight.py` (P2 `embedded` or `socket`) |
| Lockstep model check | `antonio_lab.py`, `bongo_lab.py`, `abadede_lab.py`, `twins_lab.py`, `mr_x_lab.py`, `grunt_lab.py`, `jump_kick_lab.py`, `souther_hold_lab.py`, `souther_pair_check.py` |
| Offline play | `twins_sim.py`, `mr_x_sim.py`, `jack_sim.py`, `snapshot_replay.py` (rebuilds a `--raw` tick) |
| Benchmarks | `tick_bench.py`, `jack_plan_bench.py`, `grunt_plan_bench.py` |
| Traces | `stage_walk_diag.py` (`--raw`), `antonio_diag.py`, `souther_diag.py`, `breakable_diag.py`, `hakuro_emerge_diag.py`, `table_throw_diag.py`, `round2_death_diag.py`, `armed_combat_diag.py`, `hold_timing_diag.py`, `hold_threat_diag.py` |

`round2_death_diag.py` exists because four "lost" runs were the **console resetting**, the debug sweep writing a death into a spawning slot (fixed host-side).

## The AI pipeline

`AgentLoop.tick` (`loop.py`): gates on pause and non-gameplay, then `observe` -> `inference` -> `decide` (`could_*` verbs) -> `partner.do_not_harm_partner` (the only stage that removes verbs) -> `priority` -> `execute`. Only `gamepad.py` may call the pad commands. `reach.py` is the geometry, `kinematics.py` the time axis, `navigation.py` + `pathfind/` the routes (`pathfind/` imports nothing else from the project). `tokens/` holds the classes.

ORIGINAL 3 buttons: **B** attack (also the supplex's finish, throws, `CounterGrab`'s edge), **C** jump, **A** police, **B+C** rear attack (`$322A`); not the naive "A = attack". `HandleMrXDialog` always answers No; `HandleContinueMenu` answers Yes, initials `AI ` (confirm is C or A: `$57D2` treats B as backspace).

Plans follow one shape: a ROM model replayed update by update, checked in a lockstep lab, then a lookahead that owns the fight while generic verbs stand down.

### The hold ends when something is about to land

User: suplex or throw if the enemy is about to attack; calculate exactly how long each animation takes and decide on that. Every hold move locks and ignores fresh edges. Lengths measured with `hold_timing_diag.py`, in frames; **do not re-derive them from animation data**:

| move | Axel | Adam | Blaze | ends in |
| --- | ---: | ---: | ---: | --- |
| knee (B) | 17 | 18 | 18 | front hold |
| crossover (C) | 37 | 37 | 39 | back hold `$66` |
| suplex (B from `$66`) | 78 | 77 | 78 | free |
| throw (B+back) | 41 | 42 | 46 | free |

So under a clock the throw is the only ending that fits, and a knee is not started if the attack lands within its 17-18 frames. `reach.frames_until_melee_lands` is the clock, built from `is_incoming_melee`'s predicates so they cannot disagree. Measured with waves alive (`hold_threat_diag.py`): every grace was 5-12 frames, 8 of 8 threatened decisions threw, 0 knees.

## Behaviour: rules, ROM facts and open items

`Enemy`/`Boss` details not here are in the module and `ai-analysis/enemy-ai.md`. Unless stated, "scored" means Blaze, food and police off, a fresh `--turbo 2 --silent` host per fight.

### Playing with a partner

**Never hurt the partner** (user: "it should never hurt it's partner!"). Covers holds, not only strikes: walking into the other player takes
a hold (`$4478`, `$3266`, `+$4C`). A hold on the partner offers only `ReleasePartner`; `partner.do_not_harm_partner` withdraws hold moves and
`CounterGrab` on them. `execute._partner_safe_gamepad` strips any walk whose box would reach the partner within the tick, **before** it reaches the
link; `navigation.partner_obstacles` routes round them. Not filtered: the pit escape, A/B/C presses, a hold's own directions, airborne ticks, `Dialog`.
`$4478` grabs only when `$45D4` reads 1 for both players (idle, walks, armed ground; jumps hit, never grab). Walking box: Axel 0..16, Adam 0..20, Blaze
0..19; idle has none, so standing never grabs. **A lane walk grabs too.** Not run against a human.

**Items the partner needs more** (user). `partner.item_is_the_partners`: food only while the AI is strictly the hurter; a weapon unless the partner is
strictly worse armed (a tie is the AI's to try); a 1UP to whoever has fewer lives. **Any grounded B within ±20 px X, ±16 lanes of an item is a pickup**
(`$3136`, `reach.item_a_b_press_takes`), so the partner pad turns it into a step off (`execute._redirect_b_press`).

**Leave the partner's fight to them** (user). `reach.partner_is_engaging` + `partner.PartnerFightTracker` (`PartnerFight` tokens, remembered 45 frames);
`do_not_harm_partner` withdraws attacks and walks at that enemy, except **self-defence** (`reach.is_incoming_melee`) and a kick already airborne.
With only their enemies left, the AI waits.

**The enemy beside the partner is theirs to walk to** (user; confirmed live 2026-10-31). `partner._walks_to_the_partners_nearer_enemy` withdraws
that walk (`PARTNER_NEARER_MARGIN` 24 px) while another walk's enemy is nearer the actor than the partner.

**Following a partner who is ahead** (user). With a partner ahead, `CatchUpPartner` replaces `WalkToAdvanceStage`, at a reasonable distance. "Ahead" is the
round's (`Stage.direction`: right on 1-6, left on 8, none on the elevator; `decide.partner_lead_x`, `_partner_ahead_of`). Produced under the advance's gates
while the partner is more than `CATCH_UP_DISTANCE_X` (64 px, clears the grab reach of 33) ahead; closer, the AI waits. An AI ahead of its partner still
advances (the user's rule names only the partner being ahead). Not run live against a human.

### `WalkToAdvanceStage` only when walking can scroll, and `Centering`

User (2026-10-31): produce `WalkToAdvanceStage` only when it really must walk; `Centering` otherwise. Scroll test, ROM `$6A6`: `$FFE01A` - `$FFE01E` under 4 is
locked (wave gate or arena; `CameraRange.scroll_open`, `decide.scroll_is_open`). The wave flow opens a gate, not the player's position.

- The advance stands down while the scroll is locked. Never walk to the screen edge at a locked gate.
- `could_walk_to_near_enemy` takes on-screen enemies only (user: if off screen, Centering to lure them out). Off-screen enemies do not hold an open scroll back (user: the AI got stuck Centering when the level asked for a little advance).
- `decide.could_centering`: free to walk, any idle tick, not while advancing or with a partner ahead; X only, own lane, within 16 px of `centering_point_x`: camera centre, or with a `Partner` **a third of the screen from the back** (user). Lowest tier. **Never in Mr. X's office** (user).
- `$18F5C` (two players): the camera scrolls with the lead past camera + `$B0` and the rear at camera + `$90` or more, so a centred leader never scrolls and a rear AI at the third holds the camera until `CatchUpPartner` moves it. Round 8 mirrors this.

User accepted it live in AI Assist (2026-10-31); no scored A/B. `WalkToScreenCenter` was removed (user: "é inútil"). Watch: hits at locked gates.

### The jump kick, measured

User: must be predictable, and used everywhere. `ai/jump_kick.py` reproduces `tools/jump_kick_lab.py`'s lockstep traces bit for bit. **Every object moves at 30 Hz** (`$AD8E`
waits a VBlank): crouch 5 updates = 10 frames, every ROM rate is per update. Kicked flights land 67.1 / 77.3 / 84.0 px on (Axel, Adam, Blaze); Blaze's box opens 6 updates late.
The box clears a standing body near the apex and reaches it up to ~110 px out coming down. Used by `reach.in_jump_attack_band`, `do_not_harm_partner`, `execute._hold_back_kick`,
`partner_obstacles`, and a multi-hit bonus.

**The 30 Hz time axis: fixed, measured, not kept.** `kinematics` treats ROM per-update velocities as per 60 Hz frame, so projections run 2x fast. A root fix (`OBJECT_UPDATE_FRAMES = 2`)
was worse in 16 Antonio fights (65 hits vs 47) and reverted. Horizons are tuned to the 2x projection, so a retry must retune them as a whole.

### Holding a boss

User: the pros grab and suplex; avoid the kick. **A hold's link is `+$4C`** (`MapEntity.contact_slot`), with the `$60-$6F` family and the C crossover `$76`/`$80`
(`is_holding_enemy`), not `+$60`, which is the weapon link. `reach.held_enemy` names the body. **A held later boss reads primary `$04`**, as his hit reaction, so
`priority._target_is_in_hand` replaced a `GRABBED` gate. The crossover is 28 ticks, ignoring edges. `reach.grab_reasons` returns nothing while holding (`$AAA0`'s rule).
Item detours are refused while his kick gate covers the actor (`antonio.kick_gate_open`). `tools/antonio_diag.py` logs each candidate per tick.

### Antonio: the ROM model and the plan

User: think of a sound strategy first; "A AI está a depender muito da chamada da polícia!"; do not eat the arena's food (players need it later), so `decide._food_is_spoken_for` drops
`HealthPickup` while he lives. `ai/antonio.py`, `EngageAntonio`, decode in `ai-analysis/enemy-ai.md`, "Antonio". **Take one hold, and never give him back a turn**, reached by a **lookahead over his own AI**:

- Kick gate `< 8` above his lane, `< 16` level or below; so **8-16 px above his lane** is kick-proof and grab-ready. `$AAA0`: the walking box on his body comes first, so a walk in takes the hold even through a kick.
- `plan_engage`: nine sticks, held 2 updates then a tail, or the whole horizon (14 updates), each under both update orders, scored by the worse. His kick cannot be answered reactively (every hit within two ticks of primary `$02`; a hop needs ~45 frames).
- `BoomerangSim`: launched 64 px ahead at 14 px/update, dives, homes back on the street's top; a fresh one leaves the old one flying. `HitAntonioBoomerang` is unarmed only (a swing is ~26 committed frames).
- Hold: two knees, `ReleaseToRegrab` (lands 40 px ahead), back in, a finisher only if it kills.
- `state_machine_engage_antonio` holds the stick **unclamped**: clamping at the camera edge removed the walk into him.

Scored with `boss_fight.py --level 1 --boss-type 0x56 --no-food`: 0 hits for Blaze and Axel, 0.2 for Adam, 2.2-9 s (previously 3.25 hits, 13-32 s). Checked by `antonio_lab.py`.
Open: the corner: Adam pinned at the camera edge over seconds, beyond the 14-update horizon. Unmeasured: two players, the boss rush, waves alive.
Taught: the jump kick as a plan is slow (45 frames) and is where hits land; lane offset alone is not safety.

### Souther: the ROM model and the plan

User: grabbing him and dealing damage repeatedly is the strategy; prefer deterministic behaviour; no police or life items in tests. `ai/souther.py`, `EngageSouther`, decode in `ai-analysis/enemy-ai.md` and `controls-and-input.md`.

- **Commit gate is side-dependent:** `+$52 < $0A` above him, `< $1C` otherwise. So 11-15 px above is out of the gate and in grab range.
- The claw is his own attack box (0..86 px forward, lane -10..+24); type `$98` has none. **Grab beats hit** (`$AAA0`, never reads the weapon).
- **He never escapes a hold, and a release is the best move.** Holding back counts `+$63` from 3, dropping on the ~8th frame, 32 px in front: an immediate re-grab. One crossover per hold (`+$4B` bit 7).
- Plan: corridor 15 px above or 38 below, walk in. Knee, knee, `ReleaseToRegrab`, back in; finisher only if it kills (third knee at 3, suplex at 5). Generic verbs and items stand down; police is panic only.

`boss_fight.py --level 2 --boss-type 0x55 --no-food`, lab `souther_hold_lab.py`: 0 hits in 16 Blaze fights, 2-4 s (old plan: 2.15 hits, 17-27 s). `souther.WALK_BOX_REACH_X` keeps 14 for Axel and Adam (ROM: 16, 20) until a wider walk-in is measured.

Taught: measure in **hits over many fights** (identical code spread 0-12; a death counts +100 in `damage_pct`). Aligned on his lane at 24-104 px lost the game every fight. The police special freezes the caller ~5 s (`$16AEC`). `reach.in_targetable_lane`, `in_visible_screen`, `phases.boss_phase` (`$05` is the lethal gate, visited on every hit).

### Round 6: the Souther pair

User: two Southers at once are a problem. `ai/souther_pair.py`; rounds 2 and 8 do not reach it. Facts: **a holding actor is a target** (`$179F8`), and the hold roots it; a target facing away is **rushed** at 4 px/update, one facing him gets the band-restore; every `$78` updates an attack run. **`Boss.is_defeated` reads 0 as dead** for bosses, which test `<= 0` (ordinary enemies are signed).

Plan: one engage (`pick_target`); before each knee, replay the free one (`update`), and if he commits within a knee plus a throw (`commits_within`), **throw** the body (a release lands it inside its gate); a knee that kills is never traded; leave his live claw by lane. Rejected, measured worse: a lookahead over both, and a safety filter on the stick. The hold taken early is the protection.

Scored: 1.75 hits a fight, 0 games lost in 12 (before: 7.6, 3 of 9). Checked by `souther_pair_check.py`. Left: hits through the gate on the converge and at the opening; lanes `$02`-`$0D` untried.

### Bongo: the ROM model and the plan

User: efficient in time and life; no police or recovery items in tests. `ai/bongo.py`, `EngageBongo`, decode `ai-analysis/enemy-ai.md`, "Bongo".

- **He never touches anyone.** Only the flame, type `$97`: 32 on Normal, grows over 12 updates to x +4..+76, every lane from 14 above him to 36 below. It has no body box, so **a holder is not spared**: a front grab within 12 updates of a launch is the flame's hit (`_grab_is_burnt`). A back hold faces him away.
- Wind-up 21 updates from `$B0` (176 px) on X, the charge never re-aims and ends at a screen edge.
- Safe during a charge: **15-16 lanes above him** (exact, no lane margin), and behind once 9 px past. Before it: level on the bottom clamp.
- Plan: lookahead over his AI and the flame (44 updates, 5-7 ms); tail phases (`engage_mode`); hold is `souther.hold_step`.
- **The round's grunt** (user: do not focus on it, prevent imminent attacks; it respawns): `EngageBongo` falls from 76 to 19 under its committed strike unless `bongo.charge_is_pressing`. Nothing walks to it. A blow from behind during a hold gets Bongo thrown into it (Bongo only). A Garcia punching over the held Bongo from in front is taken.

`boss_fight.py --level 4 --boss-type 0x57 --no-food`, `--idle-seconds 3` exercises the rest; lab `bongo_lab.py`. 0 flame hits for all three, 3.3-4.4 s (before: 7 hits, 2 lives).

### Abadede: the ROM model and the plan

User: efficient; same test rules; proposed a *sweet area* against his run. `ai/abadede.py`, `EngageAbadede`, decode `ai-analysis/enemy-ai.md`, "Abadede".

- **Only the run hurts.** His closing punch is untouchable and lands on nobody.
- **The sweet area is a lane, and it is a grab:** 17-18 lanes off the run's lane (it never re-aims), walking at him, delivers him into a hold. On his lane only a punch gets there first.
- A punch is 1 point, a knee 2. Plan: lookahead (40 updates, 2-5 ms), tails SWEET/WALK_IN/READY/SET_UP/WAIT. **The punch is the user's move, as a fallback**, only when no rollout holds; thrown in the facing the actor has (**B with a turn on one press is thrown the old way**; the walk is the turn).
- Hold: knee, knee, release, but only on `reads_the_hold` (state `$B` substate 1). A back hold crosses over, except in state `$D`, where it frees him. `$3266` refuses a hold with him behind an actor facing his way (`Outcome.REFUSED`).
- The round's grunt (user): Bongo's rule. `phases.boss_phase`: `$0C` death, `$0E` a throw's flight, `$07` the run. Round 8's variant (`script_param`, `$146C4`) is modelled but never run.

`boss_fight.py --level 3 --boss-type 0x30 --no-food`, lab `abadede_lab.py`: 0 hits for all three, 2.4-5.6 s (before: 7 hits, 31 s). The host sometimes stops completing lockstep frames in round 3: `host_timeout`.

### Onihime and Yasha: the ROM model and the plan

User: go to an edge, keep the sisters behind, `RearAttack` when positioned; minimum time, then damage, then reliable; no police or recovery items, even as fallback; "não quero que dê ataques em falso"; "use turbo 2x at max". `ai/twins.py`, `ai/twins_plan.py`, `EngageTwins`; decode `ai-analysis/enemy-ai.md`, and `controls-and-input.md` for the chord.

- Two AIs. The approach twin keeps a lane gap of 32, backflips inside 96 px, and only flying-kicks (16-31 lanes off, inside 112 px, 28 updates). The grab twin walks into a turned back; jumps in only at one facing it.
- Rear attack per character: Blaze 5-53 px behind, 2 damage; Axel 8-40, 3; Adam a hop, 3. Every live frame knocks down 90 px, 39 updates. Twins have no body box in a backflip or jump-in.
- Plan: `choose_wall` is the edge away from the grab twin, facing the wall. Hold the approach twin's lane while the grab twin comes. Lookahead scored by the worst of five timings (`SCENARIOS`, because a tick is not an update). `PlanMemory` adds +150 to the last program (a chord to come is never carried). With a kick in the air, only the tail and chord. **A chord that can miss under any timing is dropped, not scored down.**
- Adam's chord: `could_jump_attack` skips it; armed `$4C` -> `$4E` -> `$40`.

Live, 2x: Blaze 46.6 s, Axel 44.6 s, Adam 32.6 s, no damage; 29 rear attacks, no whiff. The floor is the ~85-update knockdown cycle. `twins_lab.py --check`, `twins_sim.py`, `boss_fight.py` counts `chord_whiffs`. Not built: the boss rush's pair.

**Two players against the twins** (user, verbatim: "Se estivemos os dois na mesma coordenada X -> se eu for o primeiro jogador, vou para a esquerda, se for o segundo, vou para a direita. Senão: O jogador que estiver mais perto da extremidade direita, vai para extremidade direita, o jogador que estiver mais perto da extremidade esquerda, vai para a extremidade esquerda"; without a `Partner` nothing changes). `twins_plan.partner_wall`; a twin targeting the partner (`+$72`) is theirs and is filtered out. `twins_2p_fight.py`: 1 hit vs 17, 26.5 s vs 31.9. Not run against a human.

### Souther's counter to jump attacks

`$162A4` arms `+$79` from the player's jump-attack actions and `$16234` answers inside lane `$12` and X `$78` with the claw, bypassing every gate. So `could_jump_attack` refuses the launch **per actor, not per target**: a hop at an unrelated grunt in that box is countered too.

### Stage walking and props

**Target ranking (user).** `WalkToAdvanceStage` always has the lowest emergency of any verb that still scores.
Among enemies, a `Boss` outranks an armed ordinary enemy (pickup `$08-$0C`, or Jack juggling), which outranks
every other grunt.

**First-level breakables (user).** The yellow sidewalk trash can at round 1's first gate is background art, not an
object; the actor stops there because `$43AA` clamps the player to `camera_x+$20..+$120` until the wave clears.
Never hold into the camera's walk clamp. `in_smash_range` uses the punch box's own ±8 lane extent.

**Frozen on the edge of the lane band (user).** The lane band bounds the *origin*, the router the whole *body*:
`world_rect(body=, origin=)` restates the band for the body, or a body at the band's edge starts outside the world
and gets no route. The wait before a gate opens is the ROM's: the player is held until the wave's spawns are dead.

**Swinging a bat over a booth from too close (user).** A B press beside an item picks it up (`$3136`), and the swing
`$48` only connects near its peak. `decide.breakable_strike_inner_x` is the swing's inner edge (punch's with no bat or
pipe). Unmeasured: `MeleeWeaponAttack` at enemies still uses the punch's inner edge.

**Stage-4 pits (user).** The pathfinder is the authority: `navigation.jump_landing_is_safe` gates grounded launches
(walk round if a route exists; hop only if the landing is solid and no walk reaches), `WalkToAdvanceStage` hops via
`hop_landing_x` when `plan_route` fails, and the pit override does not run airborne.

**Stage-4 breakable (user).** Props take `$3C6A`'s record, so the wall is nearer than the sprite. A step into the
prop's wall is what turns the actor (`$3BAE` undoes the displacement and keeps the facing), so the facing nudge's route
leaves the target prop out of its obstacles.

**Round 4: the bridge, its props and its Jack (user).** Found with `stage_walk_diag.py --level 4`, **no sweep**, replayed
from `--raw`. Holes x 1664-1800 and 2240-2344 with props beside them. `decide._strike_stand_is_open` asks whether a
pocket either side lies inside the camera clamp, outside every pit's danger zone and every prop's wall (advance is
withheld while such a prop is up). `pathfind/search.py` tries an X-then-Y finish (`_best_xy_around`) only once a search
ended without arriving, so Y-then-X routes are unchanged. `execute._breakable_tie_side` picks the arrivable side. The pit
escape tests a hole's footprint, not its centre, against the clamp. Round-4 Jack stalemate: his `$07` reset off screen
loops him back into `$07`, so the wait stays inside `EVADE_CENTRE`, and in `$08`-`$0A` takes the lane next to his set-up
lane. Live: 5 of 5 reach Bongo in 121-133 s, 0 lives lost. Unmeasured: a Signal stalled behind props.

**A prop's stand no walk reaches (user).** The router's world runs 96 px past the clamp, so it planned round a wall off
camera and the clamp zeroed the stick, while the rear player also held the camera (`$18F5C`). `_strike_stand_is_open` also
asks `_walks_to_any`, a flood inside the clamp and band (0.3-1 ms a call, so a walled-off prop can pass the tick budget).
User accepted it live (2026-10-31).

**Round 8's thrown tables (user).** Type `$45`: state 0 hidden until a camera threshold, then a straight shot down the
target's lane at 5-6 px/tick (variant 0 never flies); state 1 flight; state 2 the arc. Decode: `ai-analysis/enemy-ai.md`.
`object_catalog` classifies it by `+$30`; a moving table is a `Projectile` (`ProjectileSidestep` flees, `HitTable` punches
when too close). `world_map` gives it `+$1C`/`+$20` velocity.

**Round 8's tables at rest (user: destroy them with high priority).** Most never fly. `observe._table_at_rest` builds them
as `Breakable`s and `priority._emergency_open_breakable` ranks them over enemy walks and plain strikes, under bosses.

**HakuRo rising from below deck (user).** Round 5: state `$13` adds 52 to `+$18` and waits until `cam_x+$80` reaches him, so
attacking him while he is frozen deadlocks the camera. `reach.enemy_still_emerging` (`world_z` vs `hazards.base_floor_z`,
generic) excludes him from `live_enemies`, so the stage walk resumes and the ROM finishes the rise.

**Round 6: the factory floor (user).** No holes in round 6. What a collision class means is the round's:
`hazards.FLOOR_TABLES`, `floor_kind`, `is_hole_class`, `is_wall_class` (class 2 is 160 px of machine housing, 3 and 4 belts;
rounds 1-5 share a table where 0, 3, 4 are holes; in round 7, 2 and 3 are walls). Walls are `Wall` tokens and router solids
(`navigation.wall_obstacles`), reported as exact rectangles, not a bounding box. Belts are not modelled.
**The round clock:** each section resets it to 50 (`$195F6`), a unit per 90 frames; at 00 the time-over (`$10976`) freezes
255 frames, writes **55** and takes 80 on the same frame, and the respawn puts the player at `cam_x`. So detect it with
the time-over byte `$FFFA49` (`round_clock` in `jack_fight.py`), never "the clock reads 00".

**The press hits under `WalkToAdvanceStage` (user).** `$42` is a drop press (`ai/press.py`): six on lane 112 at x 1832, 2632,
3688, 4520, 4776, 4904. Armed until a player's X is in `(x-48, x+96]`, shakes 11 updates, falls; 20 damage and a knockdown
from boxes `$F4` and `$EA`. Armed with nobody in the window stays walkable on purpose (else the walk waits forever). A body box
depends on the frame's facing, so zones are tested against `press.standing_envelope`; the escape holds at once (`snap_x`, not
the ramp); every verb's pad is wrapped by `execute._press_safe_gamepad`; planners testing only the origin get
`press.zones_for_origin`. Live: 0 press hits in 3 of 3, 107-113 s. Unmeasured: Axel, Adam, two players, waves alive.

### The street enemies: Garcia, Signal, HakuRo and Nora

User: these were the AI's biggest problems; a knife Garcia hits by touching; the AI walked into reach without "thinking" the enemy
would punch; "A IA tende a fugir muito dos inimigos ... podia ser mais eficiente em tempo". ROM model `ai/grunt.py`, lookahead
`ai/grunt_plan.py`, verb `EngageGrunts`; decode in `ai-analysis/enemy-ai.md`, "The street enemies, state by state".

- **Contact order:** `$AA34` registered attackers first, then per player `$AAA0`: the player's box on the enemy's body (a strike, or
  with no damage the hold), and only if that misses the enemy's box on the player.
- **Jab trigger:** Garcia `$22`/`$21` test box `$12` (0-40 px ahead, ±16 lanes) after every approach, wander and stand update.
  Walking in along his lane is his jab, never the actor's hold. A lying `$22` gets up within 80 px.
- **Knife:** `$20`'s entry run (personality 1, rounds 4-7) has his whole body as attack box; beyond 96 px on his lane he throws. A
  flying enemy knife is a `Projectile`, never a floor `Weapon`.
- **Others:** `$23` swings box `$18` (24-72 px) after 9 updates. Signal's touch is his hold (`$E7B0`). HakuRo walks to a point off the
  actor's spot, so chasing keeps him away. Nora's whip reaches 32-80 px, nothing inside 32.
- **The actor's own body moves when it strikes** (`grunt_plan.PUNCH_BODY`, `SWING_BODY`): a punch can walk it into a jab trigger.
- **A grab contact is the player's to accept** (`$3266`); `grunt.takes_hold` tells a hold from a slip.

Plan: programs (punch or swing on update 0-5, rear attack, stick held 2/6 updates then a tail) played through every modelled enemy in
`RELEVANT_DX` (160 px) and every flying knife, under six timings, the last soft (user's "fugir muito"); scored worst + mean/100. Two-staged
search within an 8 ms budget. `grunt_plan._kept` ends a kept program that has arrived or stopped moving (`$43AA` keeps the fraction, so a
walk at the clamp never arrives). `generate_verb_tokens` withdraws generic verbs at modelled enemies. Scripted entries (`grunt.ENTRY_STATES`)
are left to the stage walk.

Scored with `grunt_fight.py`, ten runs: street hits 131 -> 70. Models checked with `grunt_lab.py --check`. `--profile-ms N` prints slow ticks.
Open: `$20` and `$23` barely recorded; round 4's Jack `$07` stall under real waves.

Census from each round's ELC stream (one-player records):

| Round | Garcia `$22`/`$21` | knife `$20` (pers. 1) | bat `$23` | Signal | HakuRo `$25` (+`$2A`) | Nora | Jack |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 17/6 | 2 (0) | 1 | 3 | 2 | 4 | 0 |
| 2 | 16/11 | 4 (0) | 1 | 6 | 4 | 3 | 3 |
| 3 | 8/5 | 4 (0) | 2 | 5 | 3 (+1) | 8 | 0 |
| 4 | 8/7 | 8 (5) | 2 | 16 | 3 | 5 | 1 |
| 5 | 26/3 | 6 (4) | 3 | 6 | 12 (+2) | 7 | 6 |
| 6 | 10/8 | 4 (3) | 2 | 15 | 7 | 9 | 3 |
| 7 | 9/4 | 3 (1) | 1 | 15 | 15 | 5 | 0 |
| 8 | 6/8 | 3 (0) | 2 | 20 | 12 (+1) | 5 | 2 |

### Jack: the ROM model and the plan

User: handle every state he has, in the least time with the least damage; he does not appear in Stage 1. `ai/jack.py`, `EngageJack`,
decode in `ai-analysis/enemy-ai.md`, "Jack". The plan: **take the hold from where no axe reaches, keep it until his axes are gone, then spend it.**

- His body never strikes: every hit is a type-`$28` axe. Two axes juggled 8 lanes below him, 8-24 px in front. Dropped axes still hurt (`$FED6`).
- Throws: `$0E` three, `$0B` both juggled after `$0A`'s back-off. Personality (`+$40` low nibble): 0 juggle + aligned throw (rounds 2, 4, 6, 8), 1 retreat + ranged throw (6, 8), 2 jumps (5), 3 juggle walk (5).
- `$07` faces the target every update, so no "behind him" there. It resets only 80 px past the target; a reset off screen loops back to `$07`. The level's X bound (`$1510`) refuses his step and nothing else, so 88 px behind his walk resets him.
- Hold: he is placed 32 px in front of the holder (28 from behind) and his axes follow, so a front hold on a juggling Jack is a hit. The pose lags the grab by one update. Knees 2, 2, 3, suplex 5, throw 4. **Only a negative health word kills**: 0 is alive and still throwing.
- Plan: lookahead over him and every axe (nine sticks, both update orders); punch candidates (the walk is the turn; `$9B88` stuns 24 updates). Aim: out of the throw lane, out of the juggle band (9+ above, 25+ below), into his back; in `$07` wait mid-screen (`EVADE_CENTRE`) in the pocket `POCKET_DY` (13) above him, reachable only from above. `jack.hold_step`: back hold waits for axes; knee, knee, cross over, suplex; near a camera bound the finisher that leaves him closer.
- Ownership: `could_engage_jack` for every live Jack, 0 health included; generic verbs stand down. `EngageJack` ranks 30 less a point per 40 px plus the armed raise, 72 with an axe at the actor, 5 under another's committed strike **or a grunt >40 px closer** (user: too much priority over more imminent enemies; not measured live, `jack_fight.py` has no mixed mode).

Scored with `jack_fight.py --level N`. Round 2: 0 hits, 97 s (generic verbs: 13 hits, 105 s). Rounds 4, 5, 6: no life lost to him.

### Mr. X: the ROM model and the plan

User: minimum time and damage, reliably; no police, no recovery items even as a fallback, no attack that can miss; the flag must not kill him or his helpers. `ai/mr_x.py`, `ai/garcia.py` (the user's "Glasia" are type-`$22` Garcias), `ai/mr_x_plan.py`, `EngageMrX`. Decode: `ai-analysis/enemy-ai.md`.

`--kill-until-mr-x` (`DebugScenario`, host `Alt+X`) kills ordinary enemies and the boss rush, and stops once a type `$33`-`$35` exists or the offer flag `$FFDE00` was seen.

- Him: under `$80` on X he walks in and lunges (52 px, 8 lanes); further he goes to the gun (eight bullets, 20 each, no body box). Hold: knee, knee, release, about 4 points per 30 updates, and he never acts; 40 idle updates free him.
- Garcias: two, replaced as they die; 9 health, 8 a hit; four live punch stages. **Off screen the punch is refused** (`$92AC`), so the right clamp is a pocket. Thrown bodies (`$FFFB24`) knock them and him down.
- Blink: after a knockdown or respawn, 48 updates with no body (`$4F62`); nothing lands.
- Plan: lookahead over him, every bullet and Garcia; a hold is judged by what lands on the holder (`HOLD_KNEE_SAFE_UPDATES` 18). Home on the right clamp, facing the wall, so Garcias come into the rear attack. Never throw him (41-46 frame lock). A held Garcia is thrown only if nothing lands through the lock. Generic verbs stand down; police, food, 1UPs, weapons refused (armed, B is an untimed swing).

Checked with `mr_x_lab.py --check`, `mr_x_sim.py`. One live direction: 24.1 s, 21 holds, 8 hits, 1 life. Open: pincers after a release away from the clamp; Garcia knockdowns and replacements not modelled; Axel and Adam not run.

### Mr. X's betrayal duel

User: the AI always says NO; a human may say YES and then they must fight, and the survivor's second answer is **NO**, the bad ending (`story-mode-and-campaign-flow.md` §7.3-7.4). One player never gets it: YES is the round-6 restart, NO the fight.

While `$FFDE00` and `$FFFA43` are set and the offer's state is `$22`-`$29`, `observe` adds `PlayerDuel` and builds the other player as `RivalPlayer` instead of `Partner`, which turns every partner courtesy off. The state check matters: `$11E72` clears `$FFFA43` only if P2 is out, and the stale byte left the AI `Centering` (user-accepted 2026-10-31).

Measured with `mr_x_duel_fight.py`: only the punch lands on a player (chords and grounded kicks skip a `RivalPlayer`), and only from `RIVAL_PUNCH_MIN_X` (20) out (why is not decoded); `reach.punch_inner_for` is the shared edge. Two AIs continue at game over, so a duel between them never ends.

**Mr. X's betrayal duel: a fight, not a solver.** User: "mais aleatória, com mais movimentos diferentes. Menos eficiência fria"; "Sem modificar o comportamento que a IA terá com os inimigos". `ai/duel.py`'s `DuelStyle` replaces the tick's candidates only while `PlayerDuel` holds. Tactics, reactions and health-lead scaling are its module constants (`REACTION_TICKS`, `PRESSURE_REACTION_TICKS`, weights, `LEAD_SCALE`). `AgentLoop(duel_style=False)` / `--cold P` restore the pipeline. Loses about 3:1 to the cold pipeline, 11-15 verbs. Not played against a human; strength is the user's call.

### Crowds

**Being surrounded (user).** Answer a crowd by *taking a hold*, not trading strikes and **not by backing away**. `_retreat_is_worth_it` is health-only. `Surrounded` uses `SURROUNDED_NEAR_X`/`_Y` (96 x 32). `WHILE_SURROUNDED` outranks the `$322A` chord: the hold's throw sends the body into the enemy behind. Chain: front `$60` + rear threat -> `ThrowHeldEnemy`; else `FlipHold` -> `$66` -> `Supplex`.

**Cluster inference (user: an `Inferred` token).** `EnemyCluster` (`tokens/enemy.py`, `inference.check_for_clusters`) feeds `priority._hold_cluster_bonus` for `ThrowHeldEnemy`/`Supplex` only (+2 per body, up to +4), the same shape as `JumpAttack`'s `jump_kick.enemies_hit` bonus. It is a proximity estimate, not a landing model.

## Input through the execution data (`sor_remote.py`)

User decision (2026-10-30): the game binds **actions**, so it no longer reads the Mega Drive buttons of `MegaDriveClient`'s gamepad commands. Autoplay sends a binary `struct` document through the execution-data buffer (user: not YAML, no PyYAML on the system Python) and reads each player's state from the game-data buffer (`GET_GAME_DATA`), which only the game writes. The layout is `SoRRemoteInput.hpp`'s, mirrored in `sor_remote.py`: **change both together**.

- `SoRClient` keeps the old gamepad API and Mega Drive masks, mapping them by scheme (`md_buttons_to_actions`), so `ai/` is unchanged.
- **Schemes are detected, never set** (user). `SoRClient` queries `PLAYER_STATUS` on connect and when the reading is `SCHEME_REFRESH_S` (1 s) old. **A measurement's scheme is therefore the host's `controls.yaml`**: give the host a `HOME` whose file says what the run should play (no file = ORIGINAL 3).
- **A/B against an older build:** give its host a scratch `HOME`, or it plays the user's saved scheme.
- The game drops a client's input on disconnect or restart until the buffer changes, so every document has a new serial and clients start theirs at random.

## Six-button layout (ENHANCED 6)

`SixButtonLayout` (an `Essential` token, from that player's scheme) swaps presses (`controls-and-input.md`): rear attack **A** alone (user: not B+C), police **X**, pickup **Y**, knife throw **Z** (`execute.rear_attack_mask`, `police_mask`, `pickup_mask`, `knife_throw_mask`). B never picks up there, so `reach.item_a_b_press_takes` returns `None`. Pinned by `tests/ai/test_six_button.py`.

## Widescreen (`--widescreen`)

`ObserverApp.widescreen` (host flag 0) makes the walk clamp `[0, 320]` of the camera rather than `[32, 288]`. `CameraRange` carries `scroll_x` and `widescreen`. Sims in `ai/arena.py` widen **exactly the ROM tests `SoRWidescreenArena.cpp` ported** (`$AAA0`/`$ABA4`, `$97CE`, `$97E6`, `$14C38`, `$F4A6`); inline compares the ports left alone (`$92AC`, the bosses' own screen tests, Mr. X's `SCREEN_BAND_*`, the knife cull, Jack's `EVADE_CENTRE`) stay at 320 px. Widening those would be wrong.

## Observation notes

- Lives and specials: packed-BCD bytes at `$FFFF20+`. Pause or police special: `$FFFA1A` nonzero (+ caller `$FFFA1C`).
- Snapshots are wall-clock polling, not VSync waits; the poller reconnects with backoff.
- `world_z` (`+$18`) is on map entities but not used on the map plot. Dormant enemies and police sweep controllers are filtered by `object_catalog` and the map rules. `phases.py` decodes combat phases.

## Validation

```bash
cd autoplay
PYTHONPATH=src:ai-code:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

No live host and no pytest needed: **every test module is plain `unittest`** (a pytest-only module once failed to load and 75 tests silently never ran). Nothing may depend on the ROM, which is not versioned.

`tests/ai/test_stability.py` is the **multi-tick** suite: the pipeline is a closed loop and can oscillate while every tick is defensible. Add there, asserting direction reversals and target switches, when a change touches which verb or target *owns* a situation across ticks. `JumpKickFlightTests` does the same for the jump: `$3914` accepts only an edge in free flight, so a B held from the crouch never kicks.

After changing `TokenMap.md`, render it to validate the Mermaid:

```bash
awk '/^```mermaid/{f=1;next} /^```/{if(f){f=0;exit}} f' TokenMap.md > /tmp/tokenmap.mmd
PUPPETEER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" mmdc -i /tmp/tokenmap.mmd -o /tmp/tokenmap.svg
```

## TokenMap (keep updated)

`TokenMap.md` is the Mermaid `classDiagram` of the token hierarchy (classes and inheritance only). Any change to the token classes updates it in the same delivery. Add concrete tokens as subclasses rather than discriminator fields ([`AI.md`](AI.md)).

## Token docstring convention

1. **First line:** a short human-readable description.
2. **Inferred descendants, second line:** when generated and by what function. `Surrounded` and `EnemyCluster` are the only `Inferred` tokens left ([Judging without a cache](AI.md#judging-without-a-cache)); other judgments are direct `reach.py`/`execute.py` functions.
3. **Verb descendants, second line:** the `could_*` generator and its conditions.
4. **Verb descendants, third line:** how it ranks in emergency, which is computed from tokens or `reach.py`/`phases.py` predicates, not the static `priority` (a tie-break only):

   ```text
   Raises emergency: Surrounded×80, (reach.is_incoming_melee for this target)×17, (Weapon when distance is less than 32)×150
   ```
