# Playing

[Back to the README](../README.md)

- [Starting the game](#starting-the-game)
- [Game modes](#game-modes)
- [Default controls](#default-controls)
- [Configure keyboard and gamepad bindings](#configure-keyboard-and-gamepad-bindings)
- [Pausing](#pausing)
- [Video settings](#video-settings)
- [Quality-of-life settings](#quality-of-life-settings)
- [Widescreen (Mode 48)](#widescreen-mode-48)
- [Pre-rendered soundtrack](#pre-rendered-soundtrack)
- [Host keyboard shortcuts](#host-keyboard-shortcuts)
- [Debug utility hotkeys (Cheats)](#debug-utility-hotkeys-cheats)
- [Startup flags](#startup-flags)

## Starting the game

If you used the Builder, double-click its **StreetsOfRageRecompilation** shortcut, or
**StreetsOfRageRecompilation Launcher** for the window with all the options.

If you [built by hand](BuildingDesktop.md#building-by-hand), run these from the
meta-repository root (on Windows, `py .\scripts\NAME.py`):

```bash
./scripts/play.py
```

opens that same window, and

```bash
./scripts/run.py
```

starts the game directly, passing any option after it on to `sor`. See
[Startup flags](#startup-flags).

## Game modes

The menu offers **1 PLAYER**, **2 PLAYERS**, **1 PLAYER AI ASSIST** and **OPTIONS**, followed
by **QUIT**, which ends the game.

**1 PLAYER AI ASSIST** is a two-player game with
[the AI](DeveloperJourney.md#1-player-ai-assist) on the second player: choose your character,
then the one for the `COMPUTER`. Without the AI's code the mode is not on the menu.

## Default controls

The game reads the keyboard and gamepads itself and binds them to actions. Each player has a control scheme:

- **ORIGINAL 3** (the default): Special, Punch and Jump, the original
  three-button game (Punch picks items up, Punch+Jump is the back attack);
- **ENHANCED 6**: also Back Attack, Pick Item and Throw Knife; Punch never picks up, and Punch with a knife always stabs and never throws.

**Default bindings for keyboard**

| Action                   | Player 1                           | Player 2        |
| ------------------------ | ---------------------------------- | --------------- |
| Directions               | Arrow keys                         | `W` `S` `A` `D` |
| Special (police call)    | `Z`                                | `H`             |
| Punch                    | `X`                                | `J`             |
| Jump                     | `C`                                | `K`             |
| Back Attack (ENHANCED 6) | `V`                                | `Y`             |
| Pick Item (ENHANCED 6)   | `B`                                | `U`             |
| Throw Knife (ENHANCED 6) | `N`                                | `I`             |
| Start                    | `V` (ORIGINAL 3), `M` (ENHANCED 6) | `L`             |

**Default bindings for gamepad**

ENHANCED 6:

<p align="center">
 <img src="6buttons.webp" alt="ENHANCED 6 gamepad layout">
</p>

For the ORIGINAL 3, the Special attack moves to the R1/RB button.

Player 1 gets the first gamepad found and player 2 the next one, if not configured to a specific gamepad.

## Configure keyboard and gamepad bindings

In the game, open **OPTIONS > CONTROLS** and choose **PLAYER 1** or
**PLAYER 2**:

| Entry             | What it does                                                                            |
| ----------------- | --------------------------------------------------------------------------------------- |
| SCHEME            | ORIGINAL 3 or ENHANCED 6 (Left/Right or confirm)                                        |
| DEVICE            | AUTO (the first free gamepad), one of the detected gamepads, or NONE                    |
| BIND GAMEPAD      | Press a button for each action in turn (only with a gamepad)                            |
| BIND KEYBOARD     | Press a key for each direction, action and Start in turn (only with a keyboard)         |
| JOYSTICK DEADZONE | Shows the left stick and its tilt; Left/Right change the deadzone (only with a gamepad) |
| BACK              | Back to CONTROLS                                                                        |

Any keyboard or gamepad moves through these screens: the arrows or the D-pad
(or either player's direction keys), Enter, the South button or any Punch,
Jump or Special binding to confirm, and Start or Esc to go back. While
binding, a key or button already given to an earlier action is refused, and
Start (on any gamepad) or Esc cancels without changing anything.

The controls are saved at once in
`~/.config/StreetsOfRageProject/controls.yaml`
(`%USERPROFILE%\.config\StreetsOfRageProject\controls.yaml` on Windows),
which is created with the defaults above on the first run.

## Pausing

Start pauses the game and opens a menu. **RESUME**, or Start again, goes back to the game. **FORFEIT** asks "ARE YOU
SURE PLAYER N?", with the cursor on NO. Saying YES takes away that player's continues and lives, and they die at once:
GAME OVER. With two players each is asked in turn and answers only for themself, so one can give up while the other
plays on. In 1 PLAYER AI ASSIST the first player answers for both. With the pre-rendered soundtrack the music keeps
playing, a little quieter, while the game is paused.

## Video settings

In the game, open **OPTIONS > VIDEO**:

| Entry             | What it does                                                                                                                                                                                                                                                                             |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| VSYNC             | `AUTO` keeps the game's own speed on any screen, with no tearing, and is the one to use unless you have a reason not to. `VSYNC`, `VSYNC HALF` and `VSYNC THIRD` tie the speed to the screen, every 1, 2 or 3 refreshes; the screen tells you your refresh rate and the speed that gives |
| PICTURE           | `ORIGINAL 4:3`, or `WIDESCREEN 16:9` for a [wider view of the game](#widescreen-mode-48)                                                                                                                                                                                                 |
| DISPLAY           | `WINDOW` or `FULLSCREEN`                                                                                                                                                                                                                                                                 |
| INTEGER SCALING   | Sharp, even pixels, with borders around the picture                                                                                                                                                                                                                                      |
| RESET TO DEFAULTS | Puts the defaults back on the screen; they count only after SAVE AND APPLY                                                                                                                                                                                                               |
| SAVE AND APPLY    | Uses the settings at once and keeps them for next time                                                                                                                                                                                                                                   |
| CANCEL            | Leaves without changing anything (Start or Esc do the same)                                                                                                                                                                                                                              |

They are saved in `video.yaml`, next to `controls.yaml`. An option given on the command line
wins over the file for that run; the screen still shows it and can change it, and SAVE AND APPLY saves what it shows.
`Ctrl+F` switches between window and fullscreen for the current session only.

## Quality-of-life settings

Changes to the original game, all off by default. In the game, open **OPTIONS > QUALITY-OF-LIFE**. It has two pages (the PAGE row, Left/Right turn it).

Page 1:

| Entry                    | `--qol`  | What it does                                                                                                                                                                                                                                                                                                              |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ROLL CAMERA EARLIER      | `cam`    | The camera rolls with the player at 30% of the screen instead of past the middle (55%), so more of the street is ahead. On round 8, which scrolls left, at 70% instead of 45%                                                                                                                                             |
| FRIEND GRAB KEEPS WEAPON | `grab`   | A friend who grabs you no longer makes you drop your weapon: it is hidden during the hold and back in your hand after it. An enemy's grab, and any hit (a friend's throw too), still drop it                                                                                                                              |
| ENEMY DAMAGE CIRCLES     | `damage` | A regular enemy that has taken damage shows a see-through ring over it, in a colour for each kind of enemy (Garcia blue, Nora red, Signal yellow, Haku-Ro purple, Jack dark grey), with a disc inside that grows with the damage and fills the ring when the enemy dies. Bosses keep the bar the original game gives them |
| CHEAT ENABLED            | `cheat`  | OPTIONS always has the lives and starting-round rows, which the original game hides behind a secret button combination. Turning it on in the menu asks for Special+Punch+Jump+Right (Start, or OPTIONS on the console, to give up). The choices last until the game closes                                                |

Page 2:

| Entry             | `--qol`  | What it does                                                                                                                                                                                                                                                              |
| ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SAVE HIGH SCORES  | `scores` | The high-score table is kept between runs in `highscores.yaml`, next to `controls.yaml`. SAVE AND APPLY with it off deletes the file                                                                                                                                      |
| PLAYER 1 INITIALS | none     | Set on an on-screen keyboard. A player with initials skips the name entry on a high score and goes straight to the continue prompt; without them, the original screen. Saved in `qol.yaml`. PLAYER 2 INITIALS is the same; under 1 PLAYER AI ASSIST the AI is always `AI` |

The switches are saved in `qol.yaml`, next to `controls.yaml`, with SAVE AND APPLY. `--qol a,b,c` turns those options on for that run,
over the file; the screen still shows them and can change them, and SAVE AND APPLY saves what it shows.

## Widescreen (Mode 48)

`--widescreen`, or PICTURE in [the video settings](#video-settings), swaps Mode 40 (320×224)
for Mode 48, a host-only VDP mode that real hardware does not have. The picture is 48×27 tiles
(384×216, 16:9). The game logic is unchanged, so the extra columns show whatever the game
already leaves in the planes and sprite table:

- every layer shows 4 more tiles on each side: layers A and B, and the sprites
  (X 96-480), so sprites stay exactly where they are on their background;
- the window plane keeps its 40 columns, centred on screen;
- the first tile row of every layer is not displayed;
- the gameplay HUD loses its yellow frame and gray plate and moves one tile
  down, so it clears the hidden first row.

Remote-access framebuffer snapshots and debug PNGs are 384×216 too. The development record is
in the [widescreen log book](WidescreenLogBook.md).

## Pre-rendered soundtrack

The game makes its music on the 68000 and spends a lot of CPU in bus
handshakes with the Z80 that cost nothing on the console, so the host's
real-time chip emulation sounds worse than an accurate emulator. Instead, `sor`
plays a soundtrack pre-rendered from your ROM by
[Genesis Plus GX](https://github.com/ekeeke/genesis-plus-gx) with the Nuked
OPN2 core (YM3438, no low-pass filter, 48 kHz, lossless FLAC): every music
track (looping forever from its own loop point, like on the console), every
sound effect and every PCM voice. It is extracted with
`scripts/render_soundtrack.py`, the last step of the build for your platform
([Windows](BuildingDesktop.md#build-on-windows), [macOS](BuildingDesktop.md#build-on-macos),
[Linux](BuildingDesktop.md#build-on-linux)); it takes about four minutes and writes ~265 MB to
`StreetsOfRageRecompilation/rom/soundtrack/`, next to the ROM.

A soundtrack folder is the FLAC files plus their `manifest.tsv`. By default
`sor` reads `soundtrack/` next to the ROM; point it at another folder with
`--soundtrack DIR` (for example a second render with the other chip):

```bash
./scripts/run.py --soundtrack ~/sor-audio
```

```bash
./scripts/run.py --sound emulated   # the real-time chips instead
```

`render_soundtrack.py` takes two options for such a second render:
`--chip ym2612` renders Nuked's Model 1 YM2612 instead of the default YM3438, and
`--out DIR` writes to another folder.

In the `scripts/play.py` window the same choices are the **Sound** and
**Soundtrack folder** fields of the host panel (empty folder = next to the
ROM; the `...` button opens a folder chooser). The command line keeps a missing
soundtrack as a warning: `sor` then emulates the chips. On the PS5 there is no such
fallback: the title says what to copy and closes.

The renders come from the copyrighted ROM, so they stay next to it and are
never versioned. The game's own sound engine still runs; only its chip output
is replaced, so music starts, fades, the pause jingle and the stop commands
happen on the same frames as on hardware. Each music track is stored as two
stems that add up to the full mix, the FM channels and the drums (DAC) plus
PSG, because the game's fade treats them differently: the drums and the PSG
stop at once while the FM fades out over 1.3 seconds. One difference is deliberate: on the
console a sound effect borrows a music channel while it plays, here the music
keeps playing under it. Under `--turbo` the music stays at normal speed.

## Host keyboard shortcuts

These shortcuts operate at the host-runtime level and are independent of the
gamepad bindings:

| Shortcut | Availability    | Effect                                                                                                            |
| -------- | --------------- | ----------------------------------------------------------------------------------------------------------------- |
| `Ctrl+F` | Always          | Toggle desktop fullscreen                                                                                         |
| `Ctrl+Q` | Always          | Request an orderly shutdown                                                                                       |
| `Ctrl+R` | `--debug-utils` | Cold-restart the game while preserving the process and remote TCP connection                                      |
| `Ctrl+P` | `--debug-utils` | Save the composited frame as `screenshot_NNN.png`                                                                 |
| `Ctrl+S` | `--debug-utils` | Save a complete VDP diagnostic view as `vdp_NNN.png`, including the frame, tile sheets, nametables, and registers |

The capture files are written to the process's current working directory.
`Ctrl+R`, `Ctrl+P`, and `Ctrl+S` are inactive unless `--debug-utils` is set.

## Debug utility hotkeys (Cheats)

When started with `--debug-utils`, the host also exposes optional keyboard
cheats. Hold **Alt** on Windows/Linux or **Option** on macOS and press the
corresponding key. The unmodified key alone has no effect; gamepad modifier
chords are not handled by these host-side cheats.

| Shortcut           | Effect                                                                                                                                                                           |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Alt/Option+L`     | Add one Player 1 life, capped at `0xFF`                                                                                                                                          |
| `Alt/Option+S`     | Add one Player 1 special attack, capped at `0xFF`                                                                                                                                |
| `Alt/Option+P`     | Toggle Player 1 punch damage ×12, capped at the cartridge's maximum damage nibble                                                                                                |
| `Alt/Option+K`     | Kill all instantiated enemies, including bosses, through their normal lethal states                                                                                              |
| `Alt/Option+W`     | Call the police for the active player without consuming a special attack                                                                                                         |
| `Alt/Option+1`–`8` | Jump to levels 1–8 and enter the corresponding level-intro state                                                                                                                 |
| `Alt/Option+G`     | Kill every instantiated **Garcia** (types `$20`–`$23`)                                                                                                                           |
| `Alt/Option+N`     | Kill every instantiated **Haku-Ro** — the ninja (types `$25`, `$2A`)                                                                                                             |
| `Alt/Option+B`     | Kill every instantiated **Signal** (type `$24`)                                                                                                                                  |
| `Alt/Option+J`     | Kill every instantiated **Jack** (type `$27`)                                                                                                                                    |
| `Alt/Option+U`     | Kill every instantiated **Nora** (type `$26`)                                                                                                                                    |
| `Alt/Option+X`     | Round 8: kill every enemy and boss instantiated on the way to **Mr. X** -- does nothing once his office scene is up (types `$33`-`$35`), so his Garcias and he are left to fight |

The per-family kills put each enemy through the same forced-death sweep as
`Alt/Option+K`, so score, HUD, and cleanup run exactly as they do for a normal
defeat. They cover ordinary enemies only: bosses have their own lethal paths
and no family cheat names one (`Alt/Option+X` is the one exception, for the
rush before Mr. X). Each letter is the enemy's own initial where
that was free — Signal takes `B` and Nora takes `U`, since `S` already adds a
special attack and `N` is the ninja.

These are host debugging facilities, not part of the original cartridge input
protocol. Use them only when investigating runtime behavior or exercising
specific game paths.

## Startup flags

The `sor` executable accepts the following command-line options, grouped as in its
`--help`, which prints the CLI11-generated help screen. `--version` prints the executable
version. On Windows, `sor` opens a console only for `--debug-utils`, `--debug-log`,
`--call-log`, `--aux-addr-file`, `--help` or `--version`.

**Game**

| Flag            | Meaning                                                                                                                                                                 |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--rom PATH`    | ROM image to load; default: `rom/SOR.bin`                                                                                                                               |
| `--lang jp\|en` | Console language pin: `jp` is Japanese/domestic; `en` is overseas (English); default: `en`                                                                              |
| `--hz 50\|60`   | Console video-standard pin: `60` is NTSC/low and `50` is PAL/high; default: `60`                                                                                        |
| `--qol A,B`     | Turn on quality-of-life options for this run, separated by commas: `cam`, `grab`, `damage`, `scores`, `cheat`; see [Quality-of-life settings](#quality-of-life-settings) |
| `--default-qol` | Ignore `qol.yaml` for this run: the defaults, plus anything `--qol` turns on. For scripts and measurements                                                              |

**Video**

| Flag                                                | Meaning                                                                                                                                                                                                                                                                 |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--fullscreen`, `--windowed`                        | Start in desktop fullscreen, or in a window; default: as in `video.yaml`, see [Video settings](#video-settings)                                                                                                                                                         |
| `--widescreen`, `--no-widescreen`                   | Use VDP Mode 48 (48×27 tiles, 384×216) instead of Mode 40; a host-only mode the hardware does not have, see [Widescreen](#widescreen-mode-48)                                                                                                                           |
| `--integer-scaling`, `--no-integer-scaling`         | Scale the picture by whole multiples only, centred with borders (320×224 in a 1920×1080 window or monitor is drawn 4× at 1280×896 instead of filling the height), nearest-neighbour                                                                                     |
| `--frame-sync auto\|vsync\|vsync-half\|vsync-third` | What sets the game's speed: `auto` (the default in `video.yaml`) is the internal timer, on any monitor, without tearing, and VRR monitors can follow it (use fullscreen for VRR); `vsync`, `vsync-half` and `vsync-third` follow the monitor, every 1, 2 or 3 refreshes |
| `--default-video`                                   | Ignore `video.yaml` for this run: the defaults, plus any other video option given. For scripts and measurements                                                                                                                                                         |

**Audio**

| Flag                            | Meaning                                                                                                                                                                                                                                                                    |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--silent`                      | Disable audio output completely by dropping audio-chip writes (no pre-rendered soundtrack either)                                                                                                                                                                          |
| `--sound prerendered\|emulated` | Audio source: `prerendered` plays the FLAC soundtrack rendered by `scripts/render_soundtrack.py` (default; falls back to `emulated` when it is missing), `emulated` runs the YM2612, PSG and Z80 DAC in real time; see [Pre-rendered soundtrack](#pre-rendered-soundtrack) |
| `--soundtrack DIR`              | Pre-rendered soundtrack directory; default: `soundtrack/` next to the ROM                                                                                                                                                                                                  |

**AI**

| Flag            | Meaning                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `--ai-path DIR` | Folder holding the Python AI's code (the `sor_ai` package); default: `ai-code` in the current folder, and `scripts/run.py` passes the repository's |
| `--ai-assist`   | The second player is the Python AI from launch, whichever mode is chosen                                                 |

**Development**

| Flag                   | Meaning                                                                                                                                |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `--debug-utils`        | Enable debug hotkeys, host cheats, and remote access                                                                                   |
| `--port PORT`          | With `--debug-utils`, select the remote-access TCP port; default: `6969`; `0` disables remote access                                   |
| `--turbo N`            | Run the internal VDP at `60 × N` Hz, on the timer unless `--frame-sync` says otherwise; `N` must be a positive integer                 |
| `--debug-log`          | Log CPU and VDP state once per second                                                                                                  |
| `--call-log PATH`      | Write every 68000 subroutine entry and call to a typed CSV log (six-digit hexadecimal ROM addresses); the file is replaced on startup; see [Call-map database](Researching.md#call-map-database) |
| `--aux-addr-file PATH` | Discovery mode: append an unknown indirect-dispatch address to this file and exit with status `42` instead of aborting                 |
| `--console-menus`      | Show the PS5's menus on the desktop, for testing                                                                                       |
