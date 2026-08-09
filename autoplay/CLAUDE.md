# SoR Autoplay — agent notes

## Role

`autoplay/` is a Python project that attaches to a running
`StreetsOfRageRecompilation` (`sor`) process via
`MegaDriveEnvironment`'s `megadrive_remote` client.

**Current scope:** window **observer** (mode, characters, health,
lives, specials, timer, level, scores, 2D world map, floor holes, police-special
flags), plus an opt-in **symbolic AI** (`ai/` — Phase A of the design in
[`AI.md`](AI.md)) that can control P1 and/or P2 through controller input only
(never RAM writes). The AI is off by default and enabled per player via
`--agent-p1`/`--agent-p2` or the HUD's click-to-toggle label. See `ai/`'s
module docstrings and [`AI.md`](AI.md) for the Token/Information/Decision
pipeline and manuscript-grounded combat facts already wired in. Still future
work: two-player coordination, six-button `--altControls`, and deeper
per-boss tactics.

## Ownership

- Project-owned directory in the StreetsOfRageProject workspace.
- Prefer keeping implementation here; do not fork the remote protocol.
- Consume `MegaDriveEnvironment/python` (`megadrive_remote`) as a library
  (`PYTHONPATH` or install). Do not copy wire-protocol code.

## Commands

```bash
# Host (meta-repo root)
./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debugUtils --port 6969

# Observer (meta-repo wrapper; defaults host 127.0.0.1 port 6969)
./scripts/autoplay
./scripts/autoplay --once
./scripts/autoplay --poll-ms 33

# Or direct module invoke
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

## Observer surface

| Piece | Role |
| --- | --- |
| `app.py` | CLI (`--host`, `--port`, `--poll-ms`, `--hud-ms`, `--once`, `--agent-p1`, `--agent-p2`), poll loop, AI dispatch |
| `state.py` | Work-RAM / remote reads → `GameSnapshot` |
| `world_map.py` | Camera + actors → map entities (incl. hunt targets) |
| `object_catalog.py` | Type → symbol / color / family |
| `memory_map.py` | Known addresses |
| `hazards.py` | Pause, police special active, floor holes |
| `phases.py` | Combat-phase decode for map outlines and AI danger checks |
| `hud.py` | Tk window: State / P1 / P2 + world map + AI toggle labels; restores last window size/position |
| `bcd.py` | Packed-BCD helpers |
| `AI.md` | Architecture for the symbolic AI (Token / Information / Decision) |
| `TokenMap.md` | Mermaid class diagram of the token hierarchy (classes and inheritance only); keep in sync with the `ai/` sources |
| `ai/` | Symbolic AI implementation — see "AI surface" below and [`AI.md`](AI.md) |

### CLI

- `--host` / `--port` — remote endpoint
- `--poll-ms` — wall-clock remote sample period (default 33 ms)
- `--hud-ms` — GUI paint period only
- `--once` — one snapshot to stdout, no GUI
- `--agent-p1` / `--agent-p2` — start with the AI controlling that player
  (off by default; also toggleable at runtime from the HUD)

There are no hold-frame knobs, police-special suppress flags, or evaluation
entry points in this tree.

### HUD

- Keys: **Esc** / **Q** quit
- Columns: State · P1 · P2 (health, lives, specials, score, hunt count,
  winning-`Decision` label, one extra pending-decision label, AI toggle label)
- Map outlines use `phases.py` combat-phase colours
- Click a player's "AI: OFF/ON" label to toggle that player's AI at runtime
- Window size/position is persisted to `~/.config/sor-autoplay/window.json`
  (`$XDG_CONFIG_HOME` when set): each launch restores the last geometry
  instead of maximizing. Maximize only happens on first run (no saved file).
  A maximized (zoomed) close never overwrites the saved normal geometry.
  Apply geometry after the UI is built — scheduling it with `after_idle` at
  construction time makes the first deiconify/focus flush the idle callback
  before the layout exists, so the window drops to its minimum size.

### AI surface (`ai/` — see [`AI.md`](AI.md))

| Piece | Role |
| --- | --- |
| `tokens/` | All token classes (including ABCs), split by kind; the package `__init__` re-exports everything. `tokens/tokens.py` (`Token`/`Information`/`Decision` base classes, `Context`, `find`/`find_all`; `Information` splits into `Observed` (directly read from RAM) and `Inferred` (derived from observed tokens)); `tokens/character.py` (`Character` common actor base (`slot`, position, health, facing, combat phase); `Myself`/`Partner` (`player_index`, `action_state`, `action_flags`, `is_airborne`, punch inner/outer helpers)); `tokens/enemy.py` (`Enemy` (a `Character`; adds `type_id`, `targets_player`) + subclasses: `Grunt` (ordinary types `Garcia`/`Signal`/`HakuRo`/`Nora`/`Jack`), `Boss` → direct subclasses `Abadede`/`MrX`/`Souther`/`Antonio`/`Bongo`/`Onihime` (tactical fields with defaults on `Boss`); `enemy_class_for_type`); `tokens/essential.py` (`Essential` (scene-wide observations `Stage`/`CameraRange`/`AnimationInProgress`)); `tokens/hazard_tokens.py` (`Projectile`/`IncomingProjectile`, `StageObjects` (`Breakable`, `Pit`)); `tokens/pickup_tokens.py` (`Weapon` + consumable `Pickup` hierarchy + `weapon_rank`); `tokens/walk_decisions.py` (`WalkToNearEnemy`, `WalkToAdvanceStage`, `WalkToWeapon`, `WalkToPickup`, `WalkToBreakable`); `tokens/attack_decisions.py` (`Punch`, `SmashBreakable`, hold moves (`AttackHeldEnemy`/`ThrowHeldEnemy`/`FlipHold`/`Supplex`/`ReleaseGrab`), `JumpAttack` (horizontal only), `RearAttack`, `CounterGrab`; `MeleeAttacks` groups weaponless close combat (`Punch`/`JumpAttack`/`RearAttack`); `GrabMechanics` groups all grab/anti-grab moves; `WeaponAttacks` groups attacks requiring a held weapon (`ThrowKnife`)); `tokens/police_decision.py` (`CallPolice` — an `Attack` descendant, health-critical only) |
| `observe.py` | Direct observation from an already-fetched `GameSnapshot` (never re-polls RAM); free-to-act phases include `HOLDING` and `HELD_BY_ENEMY` |
| `inference.py` | Threat-filtered `IncomingProjectile` (approaching + in-lane + impact window); non-playable `Actors` are filtered by not being `Myself`/`Partner`/`Enemy` |
| `walk_decisions.py` | `WalkToNearEnemy`, `WalkToAdvanceStage`, `WalkToWeapon`, `WalkToPickup`, `WalkToBreakable` |
| `attack_decisions.py` | `Punch`, `SmashBreakable`, hold moves (`AttackHeldEnemy`/`ThrowHeldEnemy`/`FlipHold`/`Supplex`/`ReleaseGrab`), `JumpAttack` (horizontal only), `RearAttack`, `CounterGrab`; `MeleeAttacks` groups weaponless close combat (`Punch`/`JumpAttack`/`RearAttack`); `GrabMechanics` groups all grab/anti-grab moves; `WeaponAttacks` groups attacks requiring a held weapon (`ThrowKnife`) |
| `police_decision.py` | `CallPolice` — an `Attack` descendant (health-critical only; below `POLICE_HEALTH_PERCENT_THRESHOLD`) |
| `decide.py` | `should_*` generators; on-screen-only chase; stage advance gated on *every* live enemy (on-screen or not), not just on-screen ones; hold always acts |
| `priority.py` | Emergency scores (counter-grab 100, call-police 88, rear 60/55, supplex 68, throw-held 70, knee 64, flip 66, release 50, knife 25, jump 28/18, punch 60/20, stage-advance 12, weapon 8, pickup tiers) — the max wins, with the `priority` field breaking ties; hold throws outrank knees; stage advance when no live enemy remains |
| `gamepad.py` | `VirtualGamepad`/`SharedGamepadState` — the only code allowed to call `hold_buttons`/`press_buttons`/`release_buttons`; never `write_memory`/`write_value` |
| `execute.py` | `execute_decision` dispatch to controller input |
| `loop.py` | `AgentLoop.tick` — gates on pause/non-gameplay/not-playable first, then runs the full pipeline; fills a thread-safe `DecisionState` (winning + every pending candidate) via `inform_hud` every tick and clears it on gate; returns the winning `Decision` (or `None`) for informational use |

Verified button mapping for the original (non-altControls) scheme (see
`execute.py`'s module docstring): **Attack/Punch is physical B** (also
`Supplex`'s finishing press, `ThrowKnife`, and `CounterGrab`'s B edge),
**Jump is physical C** (`JumpAttack` launch, `Supplex` front→back crossover,
`CounterGrab` crossover, half of `RearAttack`), **Police special is physical
A** — the reverse of the naive "A=attack" assumption. **RearAttack** is the
simultaneous B+C chord (`$322A`).

Out of scope, per [`AI.md`](AI.md)'s own text: two-player coordination rules
("low priority... not an expected scenario") and the six-button
`--altControls` scheme ("planned for a future iteration"). Also out of
scope: bespoke per-boss combat tactics beyond the subclass hierarchy
existing and being populated correctly (e.g. Antonio's boomerang dodge
timing).

## TokenMap (keep updated)

`TokenMap.md` holds the Mermaid `classDiagram` of the full token hierarchy
under `ai/`: the token classes and their inheritance only (no notes, no
members). It is a living reference, not a historical snapshot. Any change
to the token classes — adding, renaming, removing a class — must update
`TokenMap.md` (class name and inheritance edges) in the same delivery.
Likewise, editing the diagram alone should only happen together with the
corresponding source change.

Add concrete tokens as subclasses rather than generic discriminator fields,
per [`AI.md`](AI.md), so the diagram and the class tree stay aligned.

## Token docstring convention

Every token class docstring follows the same normalized shape.

1. **First line:** a short, concise, human-readable description of the token.
   It may include technical details.
2. **Inferred descendants add a second line** describing clearly and shortly
   under what conditions they are generated and which function generates
   them (e.g. "Built by ``generate_inference_tokens`` when the projectile is
   approaching, in the player's lane, and within the impact window").
3. **Decision descendants add a second line describing when they are
   produced** — the ``should_*`` generator that creates them and the
   conditions under which it fires (e.g. "Produced by ``should_punch`` when
   an enemy sits within the actor's punch band").
4. **Decision descendants add a third line** describing how they can be
   ranked **in emergency**. This is *not* a static number: the static
   ``priority`` field only breaks ties between decisions that rank as
   equally emergent. Emergency is calculated from the *presence of other
   tokens*, or from the presence of another token *under certain
   conditions*. Format:

   ```text
   Raises emergency: InferredToken1×100, InferredToken2×50, (Weapon when distance is less than 32)×150
   ```

   Planned inferred tokens to reference from these lines:
   ``EnemyNearTheRearOfMyself``, ``ClusterOfEnemies``.

## Snapshot cadence

- **Snapshot cadence is wall-clock polling**, not VSync waits.
- The poller reconnects with backoff on link failure and surfaces errors in the
  HUD / offline snapshot.

## Observation notes (keep these)

- Lives / specials: packed-BCD bytes at `$FFFF20+`
- Pause / police special: `$FFFA1A` nonzero (+ caller `$FFFA1C`)
- Elevation `world_z` (`+$18`) is stored on map entities but **not** used on the
  map plot
- Dormant ordinary enemies and police-special sweep controllers are filtered by
  `object_catalog` / map build rules as documented in those modules
- Combat phase decode lives in `phases.py` for HUD outline colours

## Validation

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

Unit tests cover snapshot decoding, BCD, hazards, phases, world map,
`ObserverApp.stop()` client handoff, and the full `ai/` pipeline (tokens,
observation, inference, decisions, priority ranking, execution, the
pause/non-gameplay gate). The token-class tests live in
`tests/ai/tokens/` (`test_tokens.py`, `test_character.py`, `test_enemy.py`,
`test_essential.py`, `test_hazard_tokens.py`, `test_pickup_tokens.py`),
mirroring the `ai/` module split; pipeline tests stay in `tests/ai/`.
There is no live host requirement for the unit suite.

After changing `TokenMap.md`, validate the Mermaid syntax by rendering it
(requires Chrome + `mmdc` from `@mermaid-js/mermaid-cli`):

```bash
awk '/^```mermaid/{f=1;next} /^```/{if(f){f=0;exit}} f' TokenMap.md > /tmp/tokenmap.mmd
PUPPETEER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  mmdc -i /tmp/tokenmap.mmd -o /tmp/tokenmap.svg
```

## History: the old agent stack, and the new one in `ai/`

An earlier, ad-hoc scripted AI stack (`src/sor_autoplay/agent/`, `evaluation.py`,
`scenarios.py`, the `sor-autoplay-eval` entry point, HUD key-1/2 toggles,
`--agent-hold-frames`/`--no-police-special` flags) was deliberately removed
from this branch because it predated and did not follow the Token/Information/
Decision architecture in [`AI.md`](AI.md). Observation (RAM → snapshot →
HUD/map) was unchanged by that removal.

`ai/` (see "AI surface" above) is a **fresh implementation** against that
architecture, not a revival of the removed stack — the CLI flag names
(`--agent-p1`/`--agent-p2`) are reused because they're the obvious names, not
because any removed code came back. Do not look to the old stack (it no
longer exists) for how the new one should work; follow [`AI.md`](AI.md) and
the module docstrings under `ai/` instead.
