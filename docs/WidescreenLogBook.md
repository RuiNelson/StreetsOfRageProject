# Widescreen log book

Condensed record of the `--widescreen` feature: what it is, what was decided, where it lives, and the traps found
on the way. Keep it short; update it when the feature changes.

## What it is

`sor --widescreen` switches the VDP from Mode 40 (320×224) to **Mode 48**, a host-only mode real hardware does not
have: 48×27 tiles, **384×216** (16:9; 5× is 1920×1080). Without the flag nothing changes: every game-side
difference is gated on it, and the plain gameplay frame is byte-identical to before.

## Mode 48 (MegaDriveEnvironment)

Selected by `VDP::setWidescreen` / `MegaDriveEnvironment::setWidescreen` (host setting, not a register); it only
applies while the game has selected H40, so H32 is untouched. Timing, DMA slots, sprite limits and registers stay H40.

| Layer | Behaviour |
| --- | --- |
| Planes A/B | 48 cells from plane pixel 0: **8 more tiles on the right**, scroll unchanged |
| Window | keeps its 40 columns, **centred** (output columns 32-351); its **colour-0 pixels are transparent over plane A** (hardware: they replace it) |
| Sprites | X 96-480 visible (hardware 128-448): raw X 128 lands on **output column 32** |
| Vertical | game still runs 224 lines; the **first tile row (8 lines) is not output** (still evaluated for SOVR/SCOL) |
| Output | framebuffer, SDL texture, remote snapshots and debug PNGs are 384×216 |

Decision (B): backgrounds are not shifted, sprites are. A sprite keeps its place relative to the screen centre but
sits 32 px right of its background compared to Mode 40. Sprites do not interact with the background, so this is fine.

Code: `VDPState` (`widescreenActive()`, `hardwareWidth()`, `centerOffsetX()`, `spriteOriginX()`, `topCropLines()`),
`VDPRenderer` (planes, centred window, sprite origin, crop), `VDP::setWidescreen` (window sizing), debug sheets in
`VDPRendererDebug`. Tests: `tests/vdp_renderer_test.cpp`. Docs: `MegaDriveEnvironment/README.md` ("Mode 48").

**Rule: game-specific behaviour never goes into MegaDriveEnvironment.** A window colour-key feature (a game's plate
colour) was added there for the HUD and reverted; the game clears its plate colour itself. What stays in Mode 48 is the
generic rule above, which lets the HUD show the level instead of a black box (visible in rounds 5 and 7, where the
art reaches up under the window).

## Gameplay HUD (StreetsOfRageRecompilation, `SoRManualFunctions.cpp`)

The HUD is the window plane, rows 0-3 at VRAM `$D000`. Wanted: no yellow frame, no gray plate, one tile lower
(row 0 is the hidden row).

- `$8064 (vdp_copy_stride)` is a manual function. In widescreen it recognises the two HUD uploads (static `$FF8000`,
  40×4 at `$50000003`; per-VBlank `$FF6000` block, 40×3 at `$50800003`), blanks the frame tiles `$6D4`-`$6D7`, drops
  the bottom edge and writes the rest one window row lower. Work RAM is untouched (digit writers, `autoplay`).
- **Boss bar**: while a boss is registered `$10F80` also loads bundle 9 (`$FFF510`, every VBlank): 40×2 at
  `$51800003` = window row 3 (the boss bar row with its frame) and row 4 (bottom edge); the game then sets the window
  to 5 rows (`$9205`). Unshifted it overwrote the shifted HUD's last element row. `vdp_copy_stride` now reshapes it
  like the other two uploads (one row down, frame tiles blanked, bottom edge dropped), so the bar lands on row 4.
  Checked live only with the bundle forced on (`$FFF500`=1: HUD intact); a real boss fight is not run.
- The plate is also palette 0 **colour 2 inside every glyph/digit/bar tile**. The first block upload after the
  level-start upload rewrites tiles `$6BE`-`$6FF` and `$7C0`-`$7F3` with colour 2 -> 0 through the VDP ports.
- `$10F80 (vblank_update_gameplay_health_bars)` is a manual port so the bar tile rows use a transparent plate row
  (the ROM long at `$110A8`).

## Traps

- **Do not patch the ROM**: it fails the boot checksum and the game hangs at game state 0.
- Tiles `$780`-`$7BF` are VRAM `$F000`-`$F7FF` = **sprite table and h-scroll table**; scrubbing them corrupts sprites
  and scrolling. Level background art does not live in the HUD tile ranges, but check before widening them.
- The emulated VDP data port **does not prefetch** on an address set (hardware does), so the first read is stale.
  Read VRAM through `VDP::stateSnapshot()` instead.
- VBlank handlers run on the CPU thread while the renderer waits, so VRAM edits made there cannot flicker.
- Use `--silent` for every debug run.
- `generated/` is ignored: after editing `code-analysis/manual_functions.txt` run `./scripts/generate_cpp.py`.

## Verifying

Live check (bounded, silent): start `sor --widescreen --debugUtils --silent --port N`, press Start with
`megadrive_remote` until round 1, `read_framebuffer()` (384×216), view the PNG. Compare against a plain run to prove
the default path is unchanged.

## Status

| Area | State |
| --- | --- |
| Mode 48 VDP | done, tested |
| `--widescreen` flag | done |
| HUD (frame, plate, one tile down) | done |
| Gameplay arena (player bounds, spawn edges, on-screen tests) | ports done; verified live in round 1 only, see below |
| `autoplay` (HUD camera box, `CameraRange`, walk clamp) | follows `GET_FLAGS` flag 0, models widened for the ported tests only (`autoplay/CLAUDE.md`) |

## Gameplay arena

The game logic assumes a 320-pixel screen. In sprite space (`x - cam_x`) the screen is `[0, $140)`; in
widescreen it is `[-$20, $160)`, so every edge the logic uses moves out by `$20` on its side. Object `+$28` is the
biased screen X (`x - cam_x + $80`): its screen is `[$80, $1C0)`, widescreen `[$60, $1E0)`.

Every manual function has a label in `labels.csv` (the former `sub_XXXXXX` ones are now `object_on_screen_margin_test`, `resolve_enemy_player_contact`, `resolve_enemy_registered_attacker_contact`, `abadede_state7_run_update`, `jack_retreat_to_screen_edge`, `ordinary_enemy_wait_until_on_screen` and `police_special_player_update_gate`); keep it that way when adding one. Each change is a hand-written port in `SoRWidescreenArena.cpp` (listed in `manual_functions.txt`) that behaves like
the ROM routine when the flag is off and widens the edge when it is on. **Not a ROM patch and not a generator
feature**: both were tried and rejected (a ROM patch fails the checksum and is a workaround; the generator
route was not wanted). Registers/flags that callers read are reproduced.

| Routine | What widens |
| --- | --- |
| `$43AA clamp_players_to_gameplay_bounds` | player X window `[cam+$20, cam+$120]` -> `[cam, cam+$140]` |
| `$0C60 spawn_single_object` | enemy entry points `cam+$148` / `cam-8` -> `cam+$168` / `cam-$28` |
| `$97CE object_on_screen_test`, `$97E6` | on-screen windows `[$80,$1C0)`, `[$70,$1D0)` by `$20` each side |
| `$AAA0`, `$ABA4` | attack hit window `[$78,$1C8)` by `$20` each side (calls the generated `$AB24`/`$ABF8`) |
| `$06A6 update_camera_scroll_if_needed` | locked-arena push-back edge (`cam-$20` -> `cam-$40`; round 8 `cam+$160` -> `cam+$180`) |
| `$14C38` | charging boss turns at screen X `$1C0`/`$80` -> `+$20`/`-$20` |
| `$F4A6` | enemy walks to the clamp edge (`cam+$120`/`cam+$20` -> `cam+$140`/`cam`) |
| `$A59C` | scripted-object activation, round 8 edge `cam+$144` -> `cam+$164` (the on-screen part is `$97E6`) |
| `$7546` | round 8 thrown table arming edges `cam-$20` / `cam+$160` -> `cam-$40` / `cam+$180` |
| `$40A6 police_special_player_update_gate` | the edge `cam+$160` -> `cam+$180`; **the Z flag it returns is what freezes the players during a police special** (the caller skips their update on `bne`), so every exit must set it like the ROM |
| `$0CC0 spawn_object_batch` | wave columns are placed at absolute X; one created beyond the old screen edge is now placed `$20` further out (left edge likewise) so it is still dormant until the camera brings it in. Before, the first enemy of round 1 was activated at once and appeared inside the right edge |
| `$B0FE cull_sprite_piece_x` | sprite pieces kept from raw X `$60` -> `$40` on the left (pieces were culled while still partly on screen: sprites vanished at the far left edge); the right bound `$1E0` is already widescreen's edge |

Verified live: player left limit `x-cam` 32 (plain) vs 0 (widescreen); new enemies first seen at `x-cam` 360 (right) and
-40 (left) in widescreen. Round 1 `grunt_fight.py --family all` (Blaze, turbo 2): plain with the ports 89.8 s, 32/32
killed, 5 hits; before the ports 89.2 s, 3 hits; widescreen 91.4 s, 8 hits (the AI still models a 320 arena).
One plain run with the ports stalled 52 s at the camera clamp on `WalkToNearEnemy` toward an off-screen HakuRo, the
open stall documented in `autoplay/CLAUDE.md` ("off-screen-enemy corner stall"); the other did not.

Round 2 reset the console at ~110-120 s in widescreen (autoplay `grunt_fight.py --level 2`, 4 of 4 runs): the `$CC0`
port moved a camera-gated Jack (`+$40` bit 7) from `$0DA8` to `$0DC8`, past the camera's lock at `$0DC0`, so `$A59C`
never woke him and `prepare_next_spawn_section`'s art check (`$884`) hit his unset tile word. Fixed: a camera-gated
object keeps its X. Widescreen round 2 now reaches Souther (2 of 2); round 1 unchanged.

Rounds 8 and 6 start and run in widescreen (live smoke test, no crash); the round 8 ports are otherwise unmeasured.

Looked at and deliberately left alone:
- `$6A70 delete_pickup_behind_camera`: not a subroutine entry (only reached by `jmp`), so it cannot be a manual
  function without changing the analysis inputs. Only a pickup cleanup margin (round 8: `cam+$168`, 8 px outside the
  widescreen edge); the left margin `cam-$60` is already outside.
- `$FEE4` (Jack's deflected axe aims at `cam` / `cam+$140`): a flight target, not a gameplay edge; porting it means a
  large function for no visible change.
- `$E9CC` (HakuRo rising from below deck, `cam+$80`/`cam+$100`) and the `$13188`/`$13886`/`$13B22` windows
  (`$B8`-`$188`): measured from the screen's centre or from the object's own position, and the centre of sprite space
  (`cam+$A0`) is the same in both modes.

Not done: the `autoplay` AI (it still believes the arena is 320 wide). Per the user: leave it until the widescreen
feature is complete and they say so.
