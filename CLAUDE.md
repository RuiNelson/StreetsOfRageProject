# Agent guide

Instructions for automated contributors working in the Streets of Rage
workspace.

## Start here

1. Inspect `git status` in the meta-repository and in every submodule that is
   in scope. Preserve unrelated changes.
2. Read the local `CLAUDE.md` before editing an owned submodule.
3. Identify whether the requested change belongs to the meta-repository or to
   one or more submodules. Do not place project code in the meta-repository.
4. Use the smallest relevant build or test first, then expand validation in
   proportion to the change.

## Repository map and ownership

This public meta-repository pins the repositories that make up the workspace:

| Path | Role | Ownership |
| --- | --- | --- |
| `MegaDriveEnvironment/` | C++23 Mega Drive host runtime and development library | Project-owned; editable |
| `MegaDriveEnvironmentSampleGame/` | Dual-target sample for PC and real Mega Drive hardware | Project-owned; editable |
| `RageDecompiler/` | Python disassembly and recompilation tools | Project-owned; editable |
| `StreetsOfRageRecompilation/` | Streets of Rage analysis, generated C++, native overrides, and host executable | Project-owned; editable |
| `autoplay/` | Python remote SoR observer + symbolic AI (`megadrive_remote`) | Project-owned; editable; **not a submodule** |
| `Genesis-Plus-GX/` | Upstream emulator used only as a behavioral reference | Upstream; never edit |

`Genesis-Plus-GX` is reference material only. Do not modify files, create
patches, reformat code, commit inside it, or update its gitlink. If comparison
with it is useful, perform read-only inspection and keep the implementation in
an owned repository. It is not currently checked out in this workspace (no
gitlink); the soundtrack renderer (`StreetsOfRageRecompilation/tools/soundtrack`)
fetches upstream at a pinned commit into its own build tree and compiles it
unmodified, which is the one sanctioned use of its code.

Unlike the other rows above, `autoplay/` is tracked directly in this
meta-repository (no entry in `.gitmodules`, no separate remote) despite this
table's wording — commit and push its changes as part of a normal
meta-repository commit, not through the submodule workflow below, and do not
attempt to update a gitlink for it.

## Submodule workflow

Clone the complete workspace with:

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
```

Initialize an existing plain clone with:

```bash
git submodule update --init --recursive
```

The checked-out submodule commits are part of the reproducible workspace.
Do not advance them casually. When a requested change spans an owned
submodule:

1. make and validate the change inside that submodule;
2. commit and push the submodule after validation unless the user explicitly
   asks not to publish;
3. update the meta-repository gitlink in the same delivery;
4. report both repositories and their validation.

After completing and validating requested changes, commit and push them to
`main` automatically unless the user explicitly asks not to publish. Never
include unrelated dirty files in a commit. Do not force-push, rewrite history,
or open a pull request unless the user explicitly requests that action.

## Build model

The playable port is built from `StreetsOfRageRecompilation/`, which consumes
the sibling `MegaDriveEnvironment/` checkout. Its `generated/` directory is
ignored by Git, so a fresh checkout must run the decompiler before CMake.

Requirements:

- CMake 3.24 or newer;
- a C++23 compiler;
- SDL3 development files;
- Git and network access for first-time CMake `FetchContent` dependencies;
- Python 3 and a compatible local ROM for the mandatory first C++ generation,
  analysis scripts, and Python tests.

On macOS and Linux, the preferred wrappers are:

```bash
./scripts/generate_cpp_and_build.py
./scripts/generate_cpp_and_build.py --release
```

After `generated/SoR.hpp`, `generated/SoR-common.hpp`, and the split
`generated/SoR-XXX.cpp` files exist locally, subsequent builds may omit
`--full`. Each source group uses the first three hexadecimal digits of its
first subroutine entry address. The portable CMake path, including Windows,
must be run only after that generation step:

```bash
cmake -S StreetsOfRageRecompilation \
  -B StreetsOfRageRecompilation/build \
  -DCMAKE_BUILD_TYPE=Debug
cmake --build StreetsOfRageRecompilation/build --parallel
```

With the Visual Studio generator, select the configuration on both build and
test commands (`--config Release` and `ctest -C Release`); `CMAKE_BUILD_TYPE`
is for single-configuration generators. See `README.md` for platform-specific
prerequisites and exact Windows, macOS, and Ubuntu commands.

## ROM and generated code

The original ROM is copyrighted and is never versioned. A legally obtained
compatible dump may be placed at:

```text
StreetsOfRageRecompilation/rom/SOR.bin
```

`generated/` is ignored by Git. Generate it after a fresh clone and regenerate
it whenever ROM analysis or recompiler inputs change:

```bash
./scripts/generate_cpp.py
```

Do not commit ROMs, ignored generated C++, build trees, CMake download trees,
caches, screenshots, or transient discovery output.

## Pre-rendered soundtrack

The host's real-time sound emulation is not good enough for this game (the
68000 sequences the music and spends host CPU in BUSREQ/DAC-busy handshakes
that hardware never pays), so by default `sor` plays FLAC renders made from the
ROM by Genesis Plus GX instead (`sor --sound prerendered|emulated`). User
decisions: Nuked OPN2 **YM3438**, **no low-pass filter** (post-process later),
**48 kHz lossless**, music, sound effects and PCM voices all pre-rendered,
music at normal speed under `--turbo`, the hardware's
effect-steals-a-music-channel behaviour is not reproduced, and each music
track is two stems (FM, which the `$E0` fade attenuates, and DAC+PSG, which it
cuts at once) so the fade plays as on hardware. Render once after cloning (or when the
renderer changes) into `StreetsOfRageRecompilation/rom/soundtrack/`, which is
derived from the ROM and never committed. In `README.md` the extraction is build
step 4, right before the steps that run the recompiler (user request):

```bash
./scripts/render_soundtrack.py
```

The user chooses the folder: `sor --soundtrack DIR` (default `soundtrack/`
next to the ROM) and `render_soundtrack.py --out DIR`; `play.py` carries it as
the `sound` (`prerendered`/`emulated`) and `soundtrack` settings, which presets
do not touch. `--silent` (every debug/autoplay preset) still disables all
audio, so the measurement presets are unaffected. How the renders and their loop points are
made and how playback follows the ROM's engine: `StreetsOfRageRecompilation/CLAUDE.md`,
**Pre-rendered soundtrack**.

## Hand-written C++ keeps the original memory layout

Reimplemented routines make the code readable; they never move game state.
Every field stays in 68000 work RAM at its original address, width, and
encoding, updated on the same frame as the ROM, and data tables are still read
from the ROM. `autoplay` reads the game by address
(`autoplay/src/sor_autoplay/memory_map.py`, `rom_data.py`), so relocating
state into C++ objects or dynamic memory — the old roadmap's plan — is ruled
out. Details: `StreetsOfRageRecompilation/CLAUDE.md` (**Manual subroutines**)
and the `reimplement-subroutine` skill.



## Reverse-engineering tools

Run tools from the recompilation repository with the sibling decompiler on
`PYTHONPATH`:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

Prefer the repository entry points for common workflows:

```bash
./scripts/disassemble_to_asm.py
./scripts/discover_aux_smart.py
```

The static disassembler follows known control flow. Active runtime discovery
and `code-analysis/aux_addresses.txt` provide additional entry points for
indirect jumps and calls.

### Runtime call recording and call map

For **game analysis** (who calls whom at runtime, which labelled routines
actually run, callsites for a given flow), use the recompilation binary's
optional call log and `tools/call_map.py`. Full schema, flags, and agent
rules live in `StreetsOfRageRecompilation/CLAUDE.md` and the
`explore-call-map` skill; this is the workspace overview.

1. **Record** while playing or automating a bounded session of `sor`. Every
   emulated 68000 subroutine **entry** and `bsr`/`jsr` **call** is written as
   typed CSV (`event,source,callsite,target`). Addresses are six-digit hex
   ROM addresses. The file is truncated at startup.

```bash
StreetsOfRageRecompilation/build/sor \
  --rom StreetsOfRageRecompilation/rom/SOR.bin \
  --callLog calls.csv
```

2. **Collapse** one or more logs into a deduplicated SQLite call map. The
   tool always includes every routine from
   `StreetsOfRageRecompilation/code-analysis/labels.csv` (including zero
   activity), so labelled-only routines stay visible next to observed ones.

```bash
python3 StreetsOfRageRecompilation/tools/call_map.py calls.csv \
  --database StreetsOfRageRecompilation/call-map.sqlite \
  --labels StreetsOfRageRecompilation/code-analysis/labels.csv
```

3. **Analyse** by querying SQLite (agents must not rely on the web viewer).
   Prefer the views `subroutine_activity`, `subroutine_flow`, and
   `callsite_flow`. Counts are runtime observations from the captured runs,
   not proof of every static path. Optional `--port` starts a localhost
   read-only viewer for humans only.

Call logs, `call-map.sqlite`, and similar artefacts are local analysis
output: do not commit them unless the user explicitly asks to version that
exact file. Use this map together with `ai-analysis/*.md` manuscripts and
`labels.csv` when mapping control flow for reverse engineering or AI work.

## Launching the game and autoplay: `scripts/play.py`

One launcher for `sor` plus `autoplay`; it replaced the old `both_*.py` and
`go_to_boss.py` wrappers (`run.py`, `autoplay.py`, `build.py` remain, and
`play.py` drives them).

```bash
./scripts/play.py                       # window: configure, Ctrl+R runs both
./scripts/play.py --last                # the saved settings, no window
./scripts/play.py --preset turbo        # turbo | watch | quiet | lockstep | p2 | boss
./scripts/play.py --preset boss --level 2 --dry-run   # print the command lines only
```

The window (Tk) saves its settings to `last_play_py_settings.yml` (repo root,
gitignored) on every change and reads them back on the next launch. The port
and the turbo factor are set once and feed both programs (`sor --port/--turbo`,
`autoplay --port`, and `--poll-ms 16` under turbo); changing the start level
under a street/Mr. X sweep also updates the sweep and `--no-food` for the
round. The host panel's **Sound** (`--sound`, ignored when silent) and
**Soundtrack folder** (`--soundtrack`, empty = next to the ROM, `...` opens a
folder chooser) fields warn when the folder has no `manifest.tsv`. Keys: `^R`/`^Return` run both, `^S` host only, `^A` autoplay only, `^B`
build first, `^1`-`^6` presets, `^N` silent, `^T` turbo, `^W` widescreen, `^X`
6-button, `^7`/`^8` AI P1/P2, `^L` lockstep, `^G` character, `^K` sweep,
`^=`/`^-` start level, `^E` extra args, `^0` reset, `^Q` quit. Command-line
runs start from the defaults plus the preset (never the saved file), do not
overwrite it, and pass unknown options on to autoplay. Agents use the
command-line form (it needs no Tk); `PRESETS` in `play.py` is the source of
truth for the session flags. Add a setting in `DEFAULTS` and the two argument
builders.

## Testing the symbolic AI live

No AI behaviour change ships unmeasured (user's no-regression rule): measure
it live before it goes to `main`. A change that could only be validated
offline (unit tests, offline sims) goes to a branch and says so.

Live sessions (not unit tests) must run the host in turbo with a matching
autoplay poll cadence. Use the preset:

```bash
./scripts/play.py --preset turbo
```

equivalent to `./scripts/run.py --turbo 2 --lang en --debugUtils --port 7777
--silent &` plus `./scripts/autoplay.py --poll-ms 16 --port 7777 --agent-p1
--reach-gameplay blaze`. `--turbo 2` is the ceiling on the development
machine (measured: `--turbo 4` also ran at 120 fps there, so anything paced
by the wall clock was off by two). `--poll-ms 16` keeps sampling at ~2
frames per tick under turbo — the 33 ms default would drop to one sample per
four frames and miss holds, jumps, and incoming attacks. `--silent` is
required whenever the game is launched for debug. Only start a live `sor`
session when necessary; prefer `autoplay` unit tests for logic changes.
The `turbo` entry of `PRESETS` in `scripts/play.py` is the source of truth for these
flags — update this section if its turbo factor or `--poll-ms` changes. Full rationale,
including frame-pacing details for timing moves, is in `autoplay/CLAUDE.md`
under **Live AI testing**.

`./scripts/play.py --preset watch` is the same pairing at normal speed with sound on
(no `--turbo`, no `--silent`, default poll cadence), for watching a session;
it is not a measurement preset. `--preset quiet` is the same, silent.

For frame-exact sessions where the AI drives the clock instead of the wall
clock (tick, step exactly 2 game frames as fast as they run, back to the
tick — no poll pacing), use the preset:

```bash
./scripts/play.py --preset lockstep
```

equivalent to `./scripts/run.py --lang en --debugUtils --port 6767 --silent &`
plus `./scripts/autoplay.py --lockstep --port 6767 --agent-p1 --reach-gameplay
blaze`. Own port (6767) so it runs next to the turbo sessions. Extra args
pass through to autoplay (`--start-level`, `--kill-street-enemies`,
`--no-food`, `--no-police`).

### Going straight to a boss

`scripts/play.py --preset boss --level LEVEL` puts the AI in front of one round's boss with
nothing else on screen: same turbo host and poll cadence as `--preset turbo`,
plus `--start-level LEVEL`, `--kill-street-enemies` (or `--kill-until-mr-x`
for round 8) and `--no-police` throughout. It automatically adds `--no-food`
for rounds 2-5 and 8.

```bash
./scripts/play.py --preset boss --level 1            # round 1, Antonio
./scripts/play.py --preset boss --level 2 --agent-p2 # extra args pass through to autoplay
./scripts/play.py --preset boss --level 5            # Onihime and Yasha
```

| Level | Boss |
| --- | --- |
| 1 | Antonio (`$56`) |
| 2 | Souther (`$55`), `--no-food` |
| 3 | Abadede (`$30`), `--no-food` |
| 4 | Bongo (`$57`), `--no-food` |
| 5 | Onihime & Yasha (`$58` pair), `--no-food` |
| 6 | Bongo (`$57`), then a Souther pair (`$55`) |
| 7 | none — the ELC stream has no terminal boss section |
| 8 | boss rush, `$56` → `$55` → `$30` → `$57` → `$58` → Mr. X (`$35`); `--kill-until-mr-x`, `--no-food` |

Sweeping and
`--no-police` are not optional for boss testing — the police call is a
last-resort option in play, never in a test. Quitting the HUD (Esc/Q) also
shuts the host down, so the port is free for the next run. Full rationale
(why `--no-food`/`--no-police`, the swept-but-not-chased Garcia grunt in
rounds 3-4) is in `autoplay/CLAUDE.md` under **Scoring a fight without the
food**.

### Replaying a live stall offline

`autoplay/tools/stage_walk_diag.py --raw FILE` records every tick's snapshot
reads; `autoplay/tools/snapshot_replay.py` rebuilds any tick so the real
pipeline can be run on it again without a host, and
`autoplay/tools/jack_sim.py` plays the Jack engage against his model from such
a recording. Recordings are local analysis output (~4 MB a second): never
commit them. Round 4's props, hole and Jack stalemate were found this way
(`autoplay/CLAUDE.md`, **Round 4: the bridge, its props and its Jack**).

### Testing against the twins, Mr. X, and Jack

Score/tune commands and the ROM model + plan for each boss are documented in
`autoplay/CLAUDE.md`, not duplicated here:

- Twins (round 5, `$58`) — **Onihime and Yasha: the ROM model and the plan**;
  with two players (one per edge, P2 joining with Start) scored by
  `autoplay/tools/twins_2p_fight.py` — **Two players against the twins**.
- Mr. X (round 8, `$35`, via `--kill-until-mr-x`) — **Mr. X: the ROM model
  and the plan**.
- Mr. X's betrayal duel (2P, one player says yes, the AI always no; P1 vs P2,
  `$FFFA43`) — scored by `autoplay/tools/mr_x_duel_fight.py` (two AIs, one
  given the harness's `--mr-x-accept`; `--cold P` turns seat P's duel style
  off) — **Mr. X's betrayal duel**. The survivor's second answer is NO, which
  is the bad ending (user). Against the other player the AI fights for a
  person to enjoy, not to win efficiently (user: "mais aleatória, com mais
  movimentos diferentes. Menos eficiência fria"; enemies are never fought
  differently) — `autoplay/src/sor_autoplay/ai/duel.py`, **Mr. X's betrayal
  duel: a fight, not a solver**.
- Jack (`$27`, never in round 1; appears rounds 2, 4, 5, 6, 8) — **Jack: the
  ROM model and the plan**.
- Round 6's Souther pair (two `$55`, via `play.py --preset boss --level 6` or `boss_fight.py
  --level 6 --boss-type 0x55`) — **Round 6: the Souther pair**; the replay
  of the free one is checked with `autoplay/tools/souther_pair_check.py`.

### Testing against the street enemies

Garcia (`$20`-`$23`), Signal, HakuRo and Nora are fought by one lookahead
(`autoplay/src/sor_autoplay/ai/grunt.py`, `grunt_plan.py`, the verb
`EngageGrunts`). Score it with `autoplay/tools/grunt_fight.py` (`--family
garcia|signal|hakuro|nora|jack|all`, `--level N`; food and police off, a
fresh host per run at `--turbo 2` with `--silent`), and check the models in
lockstep with `autoplay/tools/grunt_lab.py --check`. Results, ROM facts and
open items are in `autoplay/CLAUDE.md` under **The street enemies: Garcia,
Signal, HakuRo and Nora**.

## Validation and handoff

- Documentation-only changes: check Markdown structure, links, paths, command
  syntax, and consistency with CMake/scripts.
- C++ runtime changes: configure, compile, and run the narrow relevant tests.
- Python tooling changes: run the affected tests, then the repository suite
  when practical.
- Analysis/symbol changes: follow the synchronization and regeneration rules
  in `StreetsOfRageRecompilation/CLAUDE.md`.
- Cross-repository changes: validate each changed repository and inspect the
  final meta-repository gitlinks.

Finish by summarizing changed files, validation performed, and anything not
tested on the current host.

## Other rules

- do not consult git history
- Keep this file and the other `CLAUDE.md` files updated as you work
- Save in the `CLAUDE.md` all the information that charactizes the project that you obtain from the user.
- If running the game for debug, only run if **necessary**, remember to use `--silent` to silence the sound
- When testing the symbolic AI live, use turbo and a matching autoplay cadence (`./scripts/play.py --preset turbo`); see **Testing the symbolic AI live** above

