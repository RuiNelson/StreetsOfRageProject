# Developer Journey and Project Structure

[Back to the README](../README.md)

<p align="center">
 <img src="firstlevel.webp" width="400">
</p>

## Project structure

| Submodule / directory                                                   | Purpose                                                                                                                |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| [`MegaDriveEnvironment/`](../MegaDriveEnvironment/)                     | SDL3-based Mega Drive host runtime and reusable C++ library                                                            |
| [`StreetsOfRageRecompilation/`](../StreetsOfRageRecompilation/)         | Generated and hand-written C++, analysis data, build scripts, and the `sor` executable                                 |
| [`RageDecompiler/`](../RageDecompiler/)                                 | Python tools for disassembly, recompilation, label generation, and runtime discovery                                   |
| [`MegaDriveEnvironmentSampleGame/`](../MegaDriveEnvironmentSampleGame/) | A small game targeting both the PC runtime and real Mega Drive hardware                                                |
| [`autoplay/`](../autoplay/)                                             | Python remote observer and symbolic AI player for a running `sor` host                                                 |
| [`StreetsOfRageBuilder/`](../StreetsOfRageBuilder/)                     | Guided installer that sets up the tools, builds the game from your ROM and adds shortcuts to the game and its launcher |

The playable host expects `MegaDriveEnvironment`, `RageDecompiler`, and
`StreetsOfRageRecompilation` to remain sibling directories. This is the layout
created by the meta-repository.

## Acknowledgments

I would like to thank [ekeeke for the Genesis Plus GX](https://github.com/ekeeke/genesis-plus-gx), which served almost as technical documentation for the SEGA Mega Drive, and [gsaurus for the Streets of Rage](https://github.com/gsaurus/sor-disassemblies/) disassembly (and annotations), which provided an important starting point for the analysis of the game. And of course, my slaves: Claude, ChatGPT, and Grok 4.5. Without them, this work would be impossible for my meat brain to do as a side project!

## The `RageDecompiler` recompiler

`RageDecompiler` disassembles the ROM into assembly and also transpiles the
required routines into C++ for the desktop build.

Minimal code generation is a deliberate design goal: the tool should emit no
more code than is necessary to execute the game. Particular care has been
taken with the challenges of translating an assembly-language program that
relies on patterns such as jump tables.

The recompiler is designed to operate in concert with the executable it
produces. During bootstrap, it recompiles the routines reachable from address
`0x200` and from the interrupt autovectors, together with every routine reached
through a direct call from those entry points.

Some subroutines, however, are not reachable through direct calls. To account
for them, the disassembler/recompiler consumes the auxiliary file
`StreetsOfRageRecompilation/code-analysis/aux_addresses.txt`. This file records
call-site addresses and tells the recompiler where to look for additional
functions. At runtime, `sor --aux-addr-file FILE` appends an address that is
called but does not yet have an equivalent compiled function to that file, and
exits with status 42.

The initial assumption was that exercising the game would expose a small set
of entry points and that most of the remaining routines would be reached from
them. In practice, the control-flow structure is substantially more complex;
the same subroutine may also be referenced by multiple call sites.

The project therefore includes a speculative discovery mode. The recompiler
searches the ROM for plausible code, emits it, and provides support for
potential call sites. As the game runs, confirmed addresses are added to
`aux_addresses.txt`. This makes it possible to discover dozens or hundreds of
addresses in a single compilation without restarting the game.

The discovery loop is:

**exercise the game** → **record new addresses** → **recompile** → **play again**

The project supports both conservative discovery and a smart mode that uses
speculative addresses; see [Researching](Researching.md#discovering-entry-points).

## The `MegaDriveEnvironment` development and runtime library

Producing code that could execute directly on a PC would be impractical while
the recompilation still depends on the Mega Drive's video, audio, and input
subsystems.

`MegaDriveEnvironment` serves two closely related purposes. It can be used to
develop Mega Drive games as native PC applications: instead of targeting APIs
such as Vulkan or DirectX, the application uses an emulated Mega Drive VDP
(Video Display Processor). The same approach is used for controllers and
audio.

These emulated devices use SDL3 to communicate with the host operating
system's native APIs. As a result, between 90% and 100% of a Mega Drive game
can be developed as a PC application, while the same source can also produce a
ROM image for an emulator or original hardware. The source can likewise be
used to build a conventional application for Windows, macOS, or Linux.

The accompanying `MegaDriveEnvironmentSampleGame` demonstrates this
cross-platform workflow, including a basic resource-packaging system for tiles,
audio samples, and Z80 programs.

Beyond development support, `MegaDriveEnvironment` provides the emulated VDP,
audio, controllers, and related devices that allow the static Streets of Rage
recompilation to run before its rendering engine, audio system, and other
hardware-facing subsystems have been reimplemented.

The long-term roadmap is:

1. Reimplement every game procedure in C++.
2. Make that C++ readable — named routines, fields, and constants in place of
   translated opcodes — while preserving the original gameplay rules. The game
   state stays in the original Mega Drive work RAM, at the original addresses
   and in the original formats, and is updated on the same frames as before:
   the [`autoplay`](#the-autoplay-observer-and-symbolic-ai) AI reads the game
   by address, so moving that state into C++ objects or dynamic memory would
   blind it.
3. Remove the dependency on the hardware emulated by `MegaDriveEnvironment`
   and implement the graphics pipeline, audio (already bypassed),
   and input (already reimplemented) directly through SDL.
   This replaces the emulated devices, not the work-RAM layout.
4. Enable enhancements such as higher-resolution replacement assets and variable frame rates through rendering interpolation, so the
   game logic still advances one original frame at a time.

## The recompiled game in `StreetsOfRageRecompilation`

The combination of the preceding tools produces the recompiled game in
`StreetsOfRageRecompilation`. That repository also holds the results of several
lines of analysis:

### `output`

`RageDecompiler` can emit the recompiled game as C++ and can also produce an
assembly representation. The assembly is useful for human inspection and,
especially, for enabling LLMs to study the original program's behavior and
structure. It comes from the ROM, so this directory is ignored by Git:
`./scripts/disassemble_to_asm.py` creates it.

### `ai-analysis`

Contains analyses of the code produced by multiple frontier-level language
models.

### `code-analysis`

Contains the data that guides recompilation and analysis, including labels,
auxiliary addresses, and the list of manually reimplemented functions.

### `generated`

Contains the C++ generated from the ROM. This directory is ignored by Git and
must be recreated after a fresh clone or whenever the ROM, analysis data, or
recompiler changes.

### Hand-written code

More than a hundred routines have already been reimplemented, with assistance
from LLMs, while preserving maximum compatibility with the remaining
recompiler-generated code; `code-analysis/manual_functions.txt` lists them. They
include the compressor/decompressor, substitutes for the "wait for VBlank"
routines that use busy waiting, input, menus, the sound commands, and object and
boss routines.

## The `autoplay` observer and symbolic AI

![AI autoplay in action](ai_auto.webp)

`autoplay` is a Python application that attaches to a running `sor` executable
through the remote-access library shipped with `MegaDriveEnvironment`
(`megadrive_remote`). The game process remains the host; autoplay reads live
state over the remote connection and, when its AI is enabled, plays the game
through a virtual gamepad.

The app provides a live HUD that reports game mode, level, wave, timer, and
per-player status, together with a 2D world map of on-screen and off-camera
actors (including combat-phase outlines and hunt counts).

### 1 PLAYER AI ASSIST

The game's menu has a mode of its own: a two-player game with the same AI on the second
player, running inside the game instead of through a separate program. Choose your
character, then the one for the `COMPUTER`. `autoplay` can still run alongside, and only
the first player is then its to play. The Python code is in `autoplay/ai-code`;
`sor --ai-path DIR` names another folder (the default is `ai-code` in the current folder,
and `scripts/run.py` points at the repository's), and without one the option is not on the menu.

### The AI player

The AI is symbolic, not learned: there is no training and no neural network.
It is built on what the reverse-engineering uncovered — the disassembly, the
labels, and the `ai-analysis` manuscripts — so it can anticipate an enemy
because it knows the routine that drives that enemy. It can be switched on for
player 1, player 2, or both. It may read RAM freely but never writes it: every
action goes through the controller, exactly as a human player's would, with
whichever control scheme that player has set.

Each poll runs one pass of a pipeline built on *tokens*:

1. **Observe** — turn the snapshot the HUD already reads into `Information`
   tokens: both players, each enemy and boss as its own class, weapons, food,
   and hazards.
2. **Infer** — derive the few facts that need calculation, such as being
   surrounded.
3. **Propose** — generate every `Verb` that currently makes sense: walk,
   punch, jump-kick, grab and suplex, throw a knife, dodge a projectile, open a
   breakable, advance the stage, call the police.
4. **Filter** — withdraw any verb that would hit the other player, human or
   AI.
5. **Rank** — score each verb's urgency from the information present and keep
   the winner. The HUD shows it, along with the candidates it beat.
6. **Execute** — the winning verb selects a small, non-blocking state machine
   that produces this tick's buttons.

General rules only go so far in a fight, so the harder opponents get *ROM
models*: Python restatements of an enemy's state machine, timings, and
hitboxes, which the AI plays forward to choose its next move. The street
enemies (Garcia, Signal, Haku-Ro, and Nora) share one lookahead, while Jack and
every boss — Antonio, Souther, Abadede, Bongo, Onihime & Yasha, and Mr. X —
have a model and plan of their own. Movement relies on a standalone rectangle
path finder that steers around walls, floor holes, props, and round 6's drop
press.

No behaviour change ships without being measured against the running game.
The Python helpers put the AI straight in front of any round's boss
(`scripts/play.py --preset boss --level N`) or run it in turbo, and a recorded
stall can be replayed offline through the real pipeline.

The design is described in [`autoplay/AI.md`](../autoplay/AI.md); launch
instructions and CLI options are in [`autoplay/README.md`](../autoplay/README.md);
the ROM models, measurements, and test procedures are in
[`autoplay/CLAUDE.md`](../autoplay/CLAUDE.md).
