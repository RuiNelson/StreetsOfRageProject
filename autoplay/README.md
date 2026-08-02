# SoR Autoplay

Python app that attaches to a running
[`StreetsOfRageRecompilation`](../StreetsOfRageRecompilation/) host through the
[`MegaDriveEnvironment`](../MegaDriveEnvironment/) remote-access library
(`megadrive_remote`).

**Current milestone:** live observer HUD **and** optional scripted agents that
play with **standard controls only** (no host `--altControls`).

Agent goals and rules: [`AgentSpecs.md`](AgentSpecs.md).

## Features

### Observer

- game mode, level, wave, timer
- P1/P2 character, health %, lives, specials, scores
- pause / police-special flags, floor holes
- **2D world map** (wide view + exact camera box):
  - letter-only markers with a square **outline** for state
  - players `1`/`2`, enemies `G/S/H/N/J`, bosses `B`, weapons/pickups
  - dashed camera rect = true 320×lane viewport; off-camera actors still drawn

### Agents

Per-player toggle (HUD button or keys **1** / **2**):

- **Face-then-hit combat**: punch only when same lane (±12 Y), in strike range,
  and facing the foe (player action-state bit 0). Turn one tick if wrong-way.
- No air punches: match lane before closing X; queue ordinary combo hits through
  the ROM's action flag; jump-kick B only in the `$12/$13` free-flight state
- No generic jump-ins: jumps are reserved for explicit enemy-family counters
- A typed tactical knowledge graph separates observation from actionability:
  dormant, off-camera, and out-of-lane actors may remain visible on the HUD but
  cannot become combat goals. Round-1 enemies staged at lane Y `0` are ignored
  until the ROM materializes them. Boss activation points get a narrow X
  margin because they can lock scrolling just outside the 320 px viewport.
  Signed-negative-health floor objects are marked `DEFEATED` and cannot be
  revived as targets by a stale attack-family byte; exact zero health remains
  targetable for the ROM-required finishing hit. Allocated corpses remain
  visible for diagnosis with the gray death outline instead of green punish.
- Fuzzy, phase-aware target utility balances distance, lane access, immediate
  peril, ranged attacks, punish windows, bosses, and who is targeting the
  player. At equal geometry its symbolic tier is boss, Jack, Nora, Signal,
  Haku-Ro/ninja, then Garcia; a much closer or actively attacking lower-tier
  enemy can still win. Goal/target hysteresis prevents indecisive switching.
- A constrained utility solver arbitrates **fight / loot / progress**. Bosses
  block progress, immediate danger vetoes loot, and safe valuable nearby items
  can win after combat instead of being chased unconditionally.
- Fuzzy special pressure combines crowds, active attackers, hunters,
  surrounding geometry, bosses, and health, retaining the fired-rule trace.
  It conserves police calls during small healthy fights, spends for crowds of
  four or more or low health under threat, and fires immediately when a
  reachable boss appears and stock remains.
- Held weapons are conserved until a live foe is in the weapon's usable lane
  and range, without repeated B during weapon animations; Signal's low sweep
  is countered by jumping (and by an airborne B attack when unarmed)
- Ground weapons have ROM-backed fuzzy value (damage, range, control, and
  character preference), so an armed player replaces a weapon only with a
  material upgrade and does not detour for a downgrade.
- Family-specific counters (Signal, Haku-Ro, Nora, Jack, all bosses, Mr. X):
  Nora closes for grab+knee/throw; Signal prefers mid/far C→B jump kicks;
  back security grabs a legal front foe for crossover-suplex when a hostile
  is behind. Jack is punchable while armed but **not** grabbable until the
  throw window (`$0E`) or unarmed; type-`$28` `$01` is attached (not target),
  `$02-$04` launched are projectile threats.
- **Grab/throw trees**: guarded input windows, bounded orphan recovery, and a
  crossover/suplex plan; stale weapon/contact fields cannot leak B into closed
  `$62-$6E` animations. If an enemy holds the player, `$7A` emits C, `$7C`
  waits, and the returned `$7A` `+$58.bit7` counter window emits B for `$7E`.
- Character-tuned ranges (Axel / Adam / Blaze), measured from the live attack
  hitboxes rather than estimated sprite distance
- Police special under pressure; pickups use the ROM's X/Y/Z interaction box
  with co-op fairness
- Stage rules include vertical Stage-4 pit detours, a no-horizontal-progress
  Stage-7 elevator hold, and Stage-8 leftward travel; Mr. X is always **NO**.
  Later-round breakables are lifecycle-filtered, and Stage-8 moving damaging
  props are evaded until safe or smashed only from grounded strike range.

**Standard control mapping** (OPTIONS scheme 0):

| Physical | Role |
|---|---|
| **B** | Attack / pickup |
| **C** | Jump |
| **A** | Police special |
| D-pad | Move |

Do **not** launch the host with `--altControls` when using the agents.

## Requirements

- Python 3.11+ with Tk (macOS Homebrew: `python@3.11` includes `_tkinter`)
- A running `sor` binary with remote access enabled
- Sibling checkout of `MegaDriveEnvironment` (for `megadrive_remote`), or the
  package installed into the active environment

## Launch the game host

From the meta-repository, with a legal ROM at
`StreetsOfRageRecompilation/rom/SOR.bin`:

```bash
./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debugUtils --port 6969
```

`--debugUtils` enables the remote server. Default port is `6969`.

## Run the observer / agents

From the meta-repository (preferred):

```bash
./scripts/autoplay
./scripts/autoplay --agent-p1
./scripts/autoplay --agent-p1 --agent-p2
./scripts/autoplay --host 127.0.0.1 --port 6969
./scripts/autoplay --once
```

Or directly:

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay --agent-p1
```

Options:

| Flag | Meaning |
| --- | --- |
| `--host 127.0.0.1` | Remote host |
| `--port 6969` | Remote TCP port |
| `--poll-ms 33` | Wall-clock remote poll period when agents are off |
| `--hud-ms 33` | GUI paint period only |
| `--agent-p1` / `--agent-p2` | Start with that seat's AI enabled |
| `--agent-hold-frames 2` | Frames each AI mask is held via `press_buttons` |
| `--once` | Print one snapshot to stdout (no GUI) |

When an agent is on, D-pad movement is kept continuous with `hold_buttons`.
Decisions containing A/B/C use `press_buttons` for at least three VSyncs to
produce a fresh ROM input edge, then re-latch their D-pad component. When agents
are off, sampling is wall-clock only.

Keys: **Esc** / **Q** quit · **1** / **2** toggle P1 / P2 AI.

The window starts maximized (title bar kept; not exclusive fullscreen). Layout:

1. **Top status row** — three equal columns: **State / P1 / P2** (AI buttons here)
2. **Map** — fills all remaining window space

## Tests

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

### Deterministic gameplay evaluation

The evaluator is the regression and future-learning boundary. It runs any
`GameSnapshot -> AgentDecision` policy in remote lockstep, advances exactly four
emulated frames per decision, and reads one coherent 64 KiB work-RAM image after
each step. It reports damage and damage events, lives lost, enemy damage and
defeats, pickup attempts/success/failure, ground-attack attempts/starts/failures,
jumps, progress, action counts, and a baseline reward. Optional thresholds make
the command exit `2` on a gameplay regression.

Start the host, then let the evaluator restart the ROM, navigate the menus, and
freeze the verified Round-1 start on the same connection it will evaluate. Once
lockstep is active, the setup seeds the ROM RNG and its frame-phase counter and
records a SHA-256 of the starting work RAM. This pins and exposes the ROM-side
episode inputs while thresholds remain robust to host state outside work RAM:

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay.evaluation \
  --restart-character axel \
  --restart-level 1 \
  --decisions 600 \
  --max-damage 12 \
  --max-damage-events 3 \
  --max-lives-lost 0 \
  --max-failed-pickups 0 \
  --max-failed-ground-attack-starts 0 \
  --max-weapon-air-attacks 0 \
  --max-missed-back-exposures 0 \
  --max-invalid-grab-attacks 0 \
  --max-missed-enemy-grab-escapes 0 \
  --max-defeated-enemy-attacks 0 \
  --max-defeated-enemy-pursuit 0 \
  --max-unreachable-enemy-stalls 0 \
  --max-loot-under-threat 0 \
  --max-boss-progress 0 \
  --max-boss-stalls 0 \
  --max-elevator-horizontal-progress 0 \
  --max-wasteful-specials 0 \
  --max-missed-boss-specials 0 \
  --max-missed-moving-breakables 0 \
  --min-enemy-damage 15 \
  --min-forward-progress 600 \
  --report /tmp/sor-autoplay-report.json \
  --trace /tmp/sor-autoplay-eval.jsonl
```

`--restart-character` prevents uncontrolled frames between setup and decision
zero; omit it only when deliberately evaluating the current live state.
`--restart-level 1..8` uses the host's debug level hotkey after the real menu
and character-selection path, verifies the requested level, then refreezes and
reseeds on the same connection. Use
`--scenario-seed` and `--scenario-frame-phase` to select another controlled
enemy pattern. The JSON report is suitable for CI artifacts. The compact
JSON-lines trace contains each observation, action, note, outcome, and visible
actor state for replay analysis, including ordinary-family byte `+$52` used by
Jack's weapon latch. A learned policy can be passed to
`LockstepEvaluator(policy=...)` while retaining the same measurements and
acceptance criteria, so improvements remain comparable with the scripted
baseline. If the host cannot complete a frame step, the evaluator emits a
partial failing report with the exact decision index instead of losing the
episode metrics in a traceback.

The combat policy has an explainable intelligence pipeline: a generic
forward-chaining inference engine evaluates expert production rules, then a
persistent autoplanner executes multi-frame tactics only when ROM action-state
guards permit each input. The first plan protects an exposed back during a
grab: C crosses over the held enemy, the planner waits through `$76/$77`, and B
is pressed once at the confirmed back hold `$66/$67` to enter suplex `$68/$69`.
Evaluator metrics expose the opportunity, response, and completion; use
`--max-missed-back-exposures 0` and `--min-suplexes 1` for a controlled scenario
that is known to present it.

Additional symbolic-policy gates make the reported behavior executable
as a regression contract: invalid B edges during grab animations, stalls on
observed-but-unreachable enemies, loot decisions under immediate threat, and
progress decisions while a boss blocks the arena. Enforce them with
`--max-invalid-grab-attacks 0`, `--max-unreachable-enemy-stalls 0`,
`--max-loot-under-threat 0`, and `--max-boss-progress 0`.
`--max-boss-stalls 0` rejects continued no-input `guard lane`
behavior after an eight-decision grace window, while allowing brief defensive
guards.

Resource, elevator, and moving-prop regressions have direct gates too.
`--max-wasteful-specials 0` rejects police calls outside the boss/crowd/
low-health rules, `--max-missed-boss-specials 0` requires the first legal boss
call, `--max-elevator-horizontal-progress 0` rejects left/right progress on
Round 7, and `--max-missed-moving-breakables 0` requires every reachable
damaging Round-8 prop step to be a smash, vertical evade, or safe-lane hold.
Breakables and their outgoing damage are retained in JSONL actor traces.

Enemy-held-player scenarios can additionally require
`--min-enemy-grab-escape-jumps 1 --min-enemy-grab-counter-throws 1`. The trace
includes the player action byte and `+$58` action flags, so a missed crossover
or eight-tick B window is reproducible rather than inferred from video.

In a controlled Jack encounter, `--min-jack-armed-ground-attacks 1` verifies
that the policy does not invent armor from the weapon latch. Armed jump starts
and throw-phase ground attacks remain separately observable metrics, but both
weapon phases use the normal combat and grab rules.

For a Stage 2 cheat episode, also require
`--min-signal-sweep-jumps 1`. Together with
`--max-weapon-air-attacks 0`, the report directly rejects both regressions
instead of relying on visual trace inspection.

## Layout

```text
autoplay/
  AgentSpecs.md
  pyproject.toml
  README.md
  CLAUDE.md
  src/sor_autoplay/
    app.py              # CLI + poll loop + agent I/O
    evaluation.py       # deterministic lockstep metrics + acceptance CLI
    scenarios.py        # restart/menu navigation + frozen scenario starts
    hud.py              # maximized Tk: status + map + AI toggles
    state.py            # RAM → snapshot
    world_map.py        # camera + actors → map entities
    object_catalog.py   # type → symbol/color/family
    memory_map.py       # addresses / names
    hazards.py          # pause, police, floor holes
    bcd.py              # packed-BCD helpers
    phases.py           # ordinary/boss/player combat phase decode
    agent/
      controls.py       # standard button mapping
      policy.py         # decide_actions(); mode → skills → free path
      context.py        # DecisionContext, PlayerMode, SeatMemory
      skills.py         # Skill protocol, Commitment, grab-family skills
      inference.py      # generic production-rule forward chaining
      expert.py         # tactical facts, rules, and explainable goals
      autoplanner.py    # persistent guarded multi-step combat plans
      bosses.py         # Souther/twin lane tactics
      fuzzy.py          # dependency-free fuzzy memberships + Sugeno rules
      knowledge.py      # typed entity/relation tactical knowledge graph
      arbiter.py        # constrained fight / loot / progress utility solver
      combat.py         # fuzzy phase-aware targeting / approach
      enemies.py        # family/boss counter plans
      grabs.py          # hold / knee / throw / weapon trees
      pressure.py       # fuzzy police-special pressure
      stage.py          # holes, elevator, stage 8, Mr. X
      navigation.py     # symbolic hole detours, side breakables, jump safety
      coop.py           # item fairness + 2P assist
      characters.py     # Axel / Adam / Blaze profiles
  tests/
```
