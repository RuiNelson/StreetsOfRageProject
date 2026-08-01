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
  --min-enemy-damage 15 --min-forward-progress 600 \
  --trace /tmp/sor-autoplay-eval.jsonl
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

## Agent design (standard controls only)

Specs live in `AgentSpecs.md`. Implementation under `src/sor_autoplay/agent/`.

**Controls assumption:** OPTIONS scheme 0 and **no** host `--altControls`.

| Physical | Role | `Buttons` |
|---|---|---|
| B | Attack / pickup | `Buttons.B` |
| C | Jump | `Buttons.C` |
| A | Police special | `Buttons.A` |
| D-pad | Move | UP/DOWN/LEFT/RIGHT |

`--altControls` remaps A/X/Y and splits pickup from attack; agents do not support
that layout yet.

### Behaviour (priority)

1. Steady (no input) while paused or police special is active
2. Mr. X offer: always select **NO** (refuse) then confirm
3. **Expert inference + autoplanner** (`agent/inference.py`, `expert.py`,
   `autoplanner.py`): facts and salience-ordered production rules turn observed
   combat geometry into explainable tactical goals. If a front hold (`$60/$61`)
   leaves another live, on-screen hostile behind the player, protect the exposed
   back with the ROM-confirmed plan **C → wait → B**. C enters crossover
   `$76/$77` (or `$80/$81`), the planner waits without injecting more input,
   and B is emitted exactly once after the ROM reports the back hold `$66/$67`,
   entering suplex `$68/$69`. A pre-existing back hold is a direct suplex goal.
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
5. Police special when fuzzy pressure score ≥ threshold and specials remain
   (not round 8). Pressure combines crowd size, hunters, active attacks,
   surrounding geometry, bosses, and health and retains its fired-rule trace.
6. **Grab / weapon hold tree** (`agent/grabs.py`): normally **B+back throw**
   (away = opposite action-state facing bit0). A hold needs a dedicated held
   field or the grabbed enemy's reciprocal player link; the latch bridges only
   one missing observer sample so stale contact/reaction state cannot create an
   empty knee/throw loop. Exact orphan state `$60` with only a stale `+$4C`
   pointer gets one B edge; live this transitions `$60 -> $6A -> $02` in 16
   frames. Also knee fallback; bat/pipe swing; throwable weapons. A carried
   weapon is not a combat target or a reason to press B: with no live foe, or
   with a foe outside the weapon lane/range, weapon policy returns control to
   normal stage/combat movement. Weapon holds never enter the enemy-grab latch,
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
8. Pick up weapons/items only when the constrained solver selects loot;
   immediate danger and a blocking boss make loot infeasible. Health/life/
   special still obey co-op fairness.
   - ROM routine `$3136` accepts only X ±20, Y ±16, Z ±8. Walk inside a
     conservative X ±16, Y ±12, Z ±6 box, and emit B only from a grounded
     action state; otherwise wait for the current animation to finish
9. **Face-then-hit combat** (`agent/combat.py` + `enemies.py`):
   - Player facing = action-state `+$30` **bit 0** (set = face left)
   - Punch only when same lane (Y ≤ ±12), within strike range, and facing foe
   - Turn one tick before attack if facing the wrong way (no air / reverse punches)
   - During normal action `$18`, queue the next combo B edge only while player
     `+$58` bit 5 is clear; stop sending B after the ROM has accepted the edge
   - Match lane **before** closing X (off-lane "close" was the air-punch bug)
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
     clears `+$52` before launching the helper. Treat this as a hard symbolic
     affordance: `+$52.bit0` means `ARMED` and `AIR_ATTACK_ONLY`, so align and
     space into the character's measured jump-kick band, press C, then B only
     in free flight. State `$0E` means `THROWING`/`GRABBABLE` even if a sample
     catches the old latch; ordinary B/grab pressure is legal in that window
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
   - A committed attacker can be turned toward and punched in the same input;
     a separate four-frame facing decision is too slow. Lane evasion respects
     the ordinary-enemy `$02-$70` bounds and retreats on X at either edge
   - **Jump-kick = C, then B specifically in free-flight `$12/$13`** (never
     C+B together — that is rear attack). The ROM sequence is `$10` launch,
     `$12` free flight, `$16` air attack, `$14` landing. Do not send B during
     launch or landing. Airborne is action `$10–$17` (not world_z; ground Z is
     about `$A0`).
   - Breakables (phone booth / crate): walk in → smash (B) or mid-range
     jump-break; then loot spilled pickups/weapons
   - Deterministic attack choice; jump-ins only when an enemy-family counter
     explicitly asks for one (for example Haku-Ro), not from character reach
   - Fuzzy target utility weighs proximity, lane access, danger/ranged attacks,
     punishability, boss status, and `targets_player`; keep the current target
     unless a challenger wins by a material margin
   - Generic charge/sidestep retreat applies only inside the 100 px reaction
     radius. A distant Antonio is approached rather than fled from
   - A boss decoded as CHARGE but waiting in a distant Y lane is deliberately
     re-aligned with; do not enter the ordinary-enemy `guard lane` fixed point
10. Avoid floor holes (stage 4) and elevator edges (stage 7)
11. Progress right (stage 8: left) only when the graph has no blocker

Map entities carry full combat RAM for agents:

- `primary_state` (word +$30): ordinary `$0100` normal / `$0300` knockdown /
  `$0500` grabbed / `$0600` death / `$0700` blocked
- `tactical` (boss +$67), `pair_role` (+$5D), `target_ptr` (who they hunt)
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
  `jack_armed_ground_attacks`, `jack_armed_jump_starts`, and
  `jack_throw_window_ground_attacks`
  are first-class metrics; Stage-2 runs can enforce
  `--max-weapon-air-attacks 0 --min-signal-sweep-jumps 1`, plus
  `--max-jack-armed-ground-attacks 0 --min-jack-armed-jumps 1
  --min-jack-throw-counters 1`, for scripted or
  future learned policies. Back protection is likewise observable through
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
  A host `TimeoutError` during a decision produces a partial failing report
  with the exact decision index; do not discard the metrics/trace behind an
  unhandled exception.
- Use evaluator `--restart-character` for comparable episodes. It restarts,
  navigates menus, verifies the player/health/game state, and enables lockstep
  on the same connection before returning control; a separate setup process
  leaves an uncontrolled frame gap and is not a comparable scenario start.
- Round-1 evaluation seeds the ROM RNG long at `$FFFFFF40` and the VBlank frame
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
- Sprite CRT formula (`lane/2 + z`) lives in `project_to_screen()` for later use.
- Playable lane from `clamp_players_to_gameplay_bounds`: Y ∈ `[$02,$70]`  
  (or `[$02,$A0]` on level index 6). Camera box height uses that max.
- Dormant ordinary enemies are not observations or agent targets. At the start
  of round 2, for example, object 0 is type `$21`, flags `$09`, state `$0000`,
  health 0, and camera-relative X 80: RAM has a future spawn, but the renderer
  and player do not have an enemy. ROM activation `$937A/$A59C` holds flags
  bit0 while waiting; `$B1D6` advances +$30 to `$0100` on activation. Hidden
  enemies with nonzero state remain observed so hit-flash frames do not make a
  live target flicker out. Live off-screen actors can expand the **view** while
  the **camera** rect remains the visible 320×lane band. Agent targeting,
  danger, pickups, and police pressure use the strict camera-relative
  `0..320` X band; the ROM's wider `-16..336` activation band (`$A59C` /
  `$97E6`) is not player visibility. The tactical graph additionally rejects
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
- Mr. X offer: `$FFDE00` flag, `$FFDE04` state; player object `+$59` bit3=side,
  bit4=choice UI active (initial refuse path wants bit3=1 = NO)
- Styles live in `object_catalog.py`; extraction in `world_map.py`
- Agent modules: `agent/policy.py`, `inference.py`, `expert.py`,
  `autoplanner.py`, `knowledge.py`, `fuzzy.py`, `arbiter.py`, `combat.py`,
  `pressure.py`, `stage.py`, `coop.py`, `characters.py`, `controls.py`
- Deterministic evaluator: `evaluation.py` (metrics, JSONL trace, acceptance
  criteria, injectable policy callable)

## Next milestones

- Optional `--altControls` mapping (deferred)
- Per-family named move tables from animation callbacks (deeper TAS path)
- Attract-vs-real-play discrimination if needed
- Optional transparent overlay instead of black stage
