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
module docstrings and [`AI.md`](AI.md) for the Token/Information/Verb
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
| `world_map.py` | Camera + actors → map entities (incl. hunt targets); `MapEntity.stun_timer` is the ordinary-enemy `+$50` stun countdown, read only in the `kind=="enemy"` branch (the same offset is weapon wear / boss distance / player character id for other kinds) and only meaningful while `combat_phase` is `STUNNED`; `parse_world_map` takes `police_special_active` purely to disambiguate enemy state `$0400`; `MapEntity.hitbox` is the object's real body AABB -- for a player, `_object_geometry` reads it straight from the cached box at `+$70` and needs no `RomData` at all; for everything else it is rebuilt per tick from the ROM shape tables and `None` without `RomData` (*unknown*, never *no body*) -- and `MapEntity.attack_ranges` is every reach its type has (empty for a player, whose reach lives in `tokens/character.py` instead, and for bosses, whose animation sets are not labelled); `MapEntity.enemy_vel_x`/`enemy_vel_y` carry ordinary-enemy velocity (+$1C/+$20), read only in the `kind=="enemy"` branch -- distinct fields/offsets from the boss-only `vel_x`/`vel_z` (+$20/+$24) already on the same dataclass, left untouched |
| `object_catalog.py` | Type → symbol / color / family |
| `memory_map.py` | Known addresses; `OBJ_VEL_X_ORDINARY`/`OBJ_VEL_LANE_ORDINARY` (+$1C/+$20) are ordinary-enemy velocity per enemy-ai.md's object-layout table, corroborated live (a moving Garcia's +$1C tracked its actual displacement direction while +$20 stayed 0) -- distinct from the pre-existing boss-only `OBJ_VEL_X = 0x20`, which enemy-ai.md's own table implies is mislabeled (probably lane velocity) but is left untouched since boss AI is out of scope |
| `hitboxes.py` | Real collision AABBs, as the formal `Hitbox` value object. **Players cache theirs** at `+$64` (attack) / `+$70` (body) -- six absolute words `[x0,x1,y0,y1,z0,z1]`, written by `$4140`, whose only call site (`$1CC6` in `sub_001bdc`) is player code. **Enemies cache nothing**: `$AAA0` passes the enemy's per-frame box id (`+$2` attack / `+$3` body) to `$AB24`, which rebuilds the AABB from ROM tables on every test and discards it -- so an enemy hitbox must be *reconstructed*, not read (this is also why `enemy-ai.md` can list `+$64`/`+$70` as pointers for enemies without contradicting the player layout). Tables: `$1A68E` object shapes (5-byte records), `$1AB8E` lane extents (2-byte), `$1ABA8` player shapes; type `$58` is the one non-player that uses the player table. Both record bytes are sign-extended (`ext.w` in `$AB88`), box id 0 means no box, and mirroring is *not* applied here -- the shape table carries separate forward/backward records and the animation data picks one, so a rebuilt box is already oriented |
| `attack_ranges.py` | Every enemy type's real reach, extracted from the ROM's own animation sets (graphics-engine.md §8.3). Walks set → animation → frame record collecting each frame's attack box id, resolves it through `hitboxes`' shape table, and keeps only boxes that out-reach that same frame's *body* box by `MIN_REACH_GAIN` -- Garcia's and Signal's idle animations both present a body-sized contact box for `$AA22`'s grab path, which is not a strike. Even (right-facing) animations only, so every `AttackRange` is already forward-oriented and mirrors via `projected`. Held-weapon reach is **not** extracted (a weapon is its own object with its own attach table); `held_weapon_range` supplies the one measured value, bat/pipe 36px, and `None` for everything unmeasured |
| `rom_data.py` | `RomData` — shape tables + animation sets, read **once per connection** (ROM cannot change) and threaded through `read_snapshot` into `parse_world_map`. A read failure degrades to `None`: the observer keeps working without hitboxes or attack ranges rather than failing |
| `hazards.py` | Pause, police special active, floor holes |
| `phases.py` | Combat-phase decode for map outlines and AI danger checks. `CombatPhase.STUNNED` is the ordinary-enemy *timed* stun -- state `$0200` hitstun (handler `$9B88` seeds `+$50` with `$18` and only counts it down before restoring `$0100`) and state `$0400` pepper-spray immobilization (shared handler `$A43E`, `+$50 = $A0`). `$0400` is also the police-special sweep removal, which forces health `$FFFF` while the global flag is up -- that case stays `SCRIPTED`, which is why `ordinary_enemy_phase` takes `health`/`police_special_active`. Distinct from `RECOVERY`, the tail of a move the enemy itself chose |
| `hud.py` | Tk window: State / P1 / P2 + world map + AI toggle labels; restores last window size/position |
| `bcd.py` | Packed-BCD helpers |
| `AI.md` | Architecture for the symbolic AI (Token / Information / Verb) |
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
  winning-`Verb` label, one extra pending-verb label, AI toggle label)
- Map outlines use `phases.py` combat-phase colours
- Each marker square is sized from `MapEntity.hitbox` when present (projected
  through `hud._hitbox_to_canvas`, then floored to `MIN_MARKER_PX` so a tiny
  or zoomed-out box never disappears) rather than the old fixed per-kind
  radius, which is kept only as the fallback for an entity with no hitbox
  this tick (no `RomData`, or a frame whose body box id is 0). A translucent
  red square is drawn per `AttackRange` on an on-screen entity (`AttackRange.
  projected`, one square per range rather than a merged bounding box, so a
  dead zone like Nora's shows as a real gap between her body and where the
  square starts) — pooled and z-ordered under the entity markers the same
  way floor holes are pooled and raised above the camera plate. Translucency
  is `hud._blend_hex` (fill pre-mixed with the plot background at
  `_RANGE_FILL_ALPHA`, drawn as an opaque solid), not Tk's `stipple` option:
  `stipple` is this HUD's idiom for floor holes, but it silently renders as
  flat opaque fill on Aqua Tk (macOS) instead of dithering, and since
  `_blend_hex` produces one fixed opaque colour, two overlapping range
  squares do not compound into a darker shade — whichever draws last simply
  covers the other
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
| `tokens/` | All token classes (including ABCs), split by kind; the package `__init__` re-exports everything. `tokens/tokens.py` (`Token`/`Information`/`Verb` base classes, `Context`, `find`/`find_all`; `Information` splits into `Observed` (directly read from RAM) and `Inferred` (derived from observed tokens)); `tokens/character.py` (`Character` common actor base (`slot`, position, health, facing, combat phase); `Myself`/`Partner` (`player_index`, `action_state`, `action_flags`, `is_airborne`, punch inner/outer helpers, and their own `hitbox` -- read straight from the object's own cached box at `+$70`, never reconstructed, and carrying no `attack_ranges`: a player's reach is this module's punch/rear/jump-kick geometry, not a per-frame extraction)); `tokens/enemy.py` (`Enemy` (a `Character`; adds `type_id`, `targets_player`, the formal `hitbox`/`attack_ranges` value objects plus the `max_reach`/`min_reach` helpers derived from them -- value objects rather than tokens, since a token may never embed a token by value, `grunt_vel_x`/`grunt_vel_y` -- ordinary-enemy-only velocity, defaulted to 0 and unused by `Boss`, which keeps its own separately offset `vel_x`/`vel_z`) + subclasses: `Grunt` (ordinary types `Garcia`/`Signal`/`HakuRo`/`Nora`/`Jack`; carries the ROM's own `stun_timer` at `+$50` plus `is_stunned`, an ordinary-enemy-only field since both stun handlers are ordinary state-table entries), `Boss` → direct subclasses `Abadede`/`MrX`/`Souther`/`Antonio`/`Bongo`/`Onihime` (tactical fields with defaults on `Boss`); `enemy_class_for_type`; the `Inferred` judgments about enemies: `ClosingEnemy` (reference-only `slot`), `TargetInReach` → `InPunchReach`/`InRearReach`/`InJumpAttackReach`/`InGrabReach`/`ActionableTarget` (one per move family, per actor+enemy pair), `IncomingMelee`, `PunishWindow` (with `frames_left` from a stunned Grunt's timer), `Surrounded`, and `GrabOpportunity` → `GrabToClearRear`/`GrabIntoDeadZone` (why a hold beats a strike on this enemy; `Grunt`-only. `GrabIntoDeadZone` is derived from the extracted `min_reach > 0`, not from the enemy's class -- today the ROM picks out exactly `Nora`, whose whip shape `$22` starts 32px out) -- all produced by `inference.py`); `tokens/essential.py` (`Essential` (scene-wide observations `Stage`/`CameraRange`/`AnimationInProgress`)); `tokens/hazard_tokens.py` (`Projectile`/`IncomingProjectile`, `SafeSpot`, `StageObjects` (`Breakable` -- carries its real `hitbox`, `Pit`)); `tokens/pickup_tokens.py` (`Weapon` (with its real `hitbox`) + `WeaponUpgrade` (an `Inferred`) + consumable `Pickup` hierarchy + `weapon_rank`); `tokens/walk_verbs.py` (`WalkToNearEnemy`, `RetreatFromDanger` (back off from a dangerous enemy not yet actionable, instead of closing the last stretch into its committed attack), `WalkToAdvanceStage`, `WalkToWeapon`, `WalkToPickup`); `tokens/attack_verbs.py` (`Punch` (unarmed only), `SwingBatOrPipe`/`StabWithKnifeOrBottle`/`SprayPepper` (armed melee -- same B input as `Punch`, different ROM move/reach per held weapon), `OpenBreakable` (one verb for the whole prop interaction -- approach *and* strike, switching on `decide.in_smash_range`; replaced the former `WalkToBreakable`+`SmashBreakable` pair, which split one intent across two verbs that had to hand over to each other between ticks), `GrabEnemy` (walk into an enemy, unarmed and without attacking, to take the hold -- a grab is a *contact* result, not an input), hold moves (`AttackHeldEnemy`/`ThrowHeldEnemy`/`FlipHold`/`Supplex`/`ReleaseGrab`), `JumpAttack` (horizontal only), `RearAttack`, `CounterGrab`; `MeleeAttacks` groups unarmed close combat (`Punch`/`JumpAttack`/`RearAttack`); `MeleeWeaponAttacks` groups armed melee (`SwingBatOrPipe`/`StabWithKnifeOrBottle`/`SprayPepper`); `GrabMechanics` groups all grab/anti-grab moves (taking the hold included); `WeaponAttacks` groups the *thrown* weapon attacks (`ThrowKnife`/`ThrowPepper`, the only two the ROM attack-throws)); `tokens/police_verb.py` (`CallPolice` — an `Attack` descendant, health-critical only); `tokens/recovery_verbs.py` (`Recovery` groups actions that escape/shorten a bad state rather than act on an enemy/prop/held body; `TechRecover` — the C+Up bounce-cancel landing tech, armed only by specific special/boss hold-throw choreography (`PlayableCharacter.throw_tech_ready`), not an ordinary street-enemy throw) |
| `observe.py` | Direct observation from an already-fetched `GameSnapshot` (never re-polls RAM); free-to-act phases include `HOLDING` and `HELD_BY_ENEMY` |
| `inference.py` | Threat-filtered `IncomingProjectile` (approaching + in-lane + impact window); `ClosingEnemy` (a `Grunt` heading into its actor's *side-specific* rear-attack band -- behind vs front picked via the same facing test as `reach.enemy_behind_actor`, never their union, since Axel/Blaze have zero forward reach and a front-side union previously let a front-approaching enemy wrongly fire `RearAttack` for them -- within `CLOSING_ENEMY_THREAT_TICKS`, `check_for_closing_enemies`; never for `Boss`, out of scope; still never imports `decide.py` -- the shared geometry lives in `reach.py` instead) -- the early-warning signal for a fast diagonal closer that would otherwise go undetected by the purely instantaneous-position band checks; `check_for_targets_in_reach` (the `TargetInReach` family, one pass per actor+live enemy pair, using `reach.py`'s geometry so `decide.py` and `priority.py` cannot disagree about a band within a tick); `check_for_incoming_melee` (the melee counterpart of `IncomingProjectile`: committed phase **and** inside the caution box **and** on screen); `check_for_punish_windows` (`is_punishable`, with `frames_left` from a stunned Grunt's `+$50`); `check_for_surrounded` (3+ enemies in the close box, or a pincer -- reusing `rear_attack_is_warranted`'s own box so the two judgments cannot disagree); `check_for_grab_opportunities` (why a hold beats a strike on a given `Grunt`: `GrabToClearRear` when another live enemy sits in `rear_threats`' box behind the actor, so the hold becomes `ThrowHeldEnemy`'s backwards throw *into* it; `GrabIntoDeadZone` when the enemy's extracted `min_reach` is positive -- every attack it owns starts further out than contact, so closing in leaves it with nothing that connects. Derived from the ROM geometry rather than the enemy's class; today that picks out exactly `Nora`, whose whip shape `$22` reaches 32..80px. Gated on `GRABBABLE_PHASES` -- standing and walkable-into, so deliberately **not** `is_punishable`, which includes a KNOCKDOWN body on the floor and an already-GRABBED one, and never a committed ATTACKING/CHARGE enemy the walk-in would run into); `check_for_weapon_upgrades`; and `check_for_safe_spots`, which runs **last** because it reads the `IncomingMelee` tokens produced earlier in the same call -- `generate_inference_tokens` threads the context through in order rather than unioning independent snapshots |
| `walk_verbs.py` | `WalkToNearEnemy`, `RetreatFromDanger`, `WalkToAdvanceStage`, `WalkToWeapon`, `WalkToPickup` |
| `attack_verbs.py` | `Punch` (unarmed), `SwingBatOrPipe`/`StabWithKnifeOrBottle`/`SprayPepper` (armed melee, same B input, different ROM move/reach per held weapon), `OpenBreakable` (one verb for the whole prop interaction -- approach *and* strike, switching on `decide.in_smash_range`; replaced the former `WalkToBreakable`+`SmashBreakable` pair, which split one intent across two verbs that had to hand over to each other between ticks), `GrabEnemy` (walk into an enemy, unarmed and without attacking, to take the hold -- a grab is a *contact* result, not an input), hold moves (`AttackHeldEnemy`/`ThrowHeldEnemy`/`FlipHold`/`Supplex`/`ReleaseGrab`), `JumpAttack` (horizontal only), `RearAttack`, `CounterGrab`; `MeleeAttacks` groups unarmed close combat; `MeleeWeaponAttacks` groups armed melee; `GrabMechanics` groups all grab/anti-grab moves (taking the hold included); `WeaponAttacks` groups the *thrown* weapon attacks (`ThrowKnife`/`ThrowPepper`) |
| `police_verb.py` | `CallPolice` — an `Attack` descendant (health-critical only; below `POLICE_HEALTH_PERCENT_THRESHOLD`) |
| `recovery_verbs.py` | `TechRecover` — fires while `PlayableCharacter.throw_tech_ready` (armed `+$45` on a techable action `$5C`/`$72`/`$88`); `could_tech_recover` bypasses the generic `_blocked` gate like `could_counter_grab`, since the actor is airborne/hurt for the whole window |
| `reach.py` | The one definition of every band and target filter, shared by `inference.py`, `decide.py`, `priority.py` and `execute.py`: `live_enemies`/`on_screen_enemies`/`in_playable_lane`/`in_camera`, `enemy_behind_actor`, `in_punch_band` vs `punch_would_connect` (the raw box ignores facing; a forward strike cannot hit backwards), `in_rear_band` (side-specific, never the union), `in_jump_attack_band`, `grab_would_connect` (forward-only like the punch test, since the ROM's contact test reads the actor's own forward-pointing attack box; ranged by the actor's unarmed punch outer edge with the tighter `GRAB_RANGE_Y` lane tolerance -- not a hitbox measurement but "close enough that walking in is worth committing to"), `rear_threats`, `rear_attack_is_warranted`, `enemy_actionable`, `enemy_forward_dx`/`enemy_can_reach`/`in_enemy_dead_zone` (the enemy's *own* reach, answered exactly from its extracted `AttackRange`s -- `enemy_can_reach` returns `None` for "unknown", which callers must not read as "harmless"), `too_close_to_keep_approaching` (now the enemy's real reach when known, falling back to the old `punch_outer_x + RETREAT_CAUTION_MARGIN` caution box only when it is not -- that box was always an approximation built from the *actor's* punch range, which has nothing to do with how far the enemy can hit), and `targets_of` (the lookup for actor+target inference tokens, which have no single `slot` for `find`). These were private helpers in `decide.py`, imported across modules and duplicated in `inference.py`; nothing here reads RAM or produces tokens |
| `decide.py` | Every reach question is answered by the `TargetInReach` tokens `inference.py` produced this tick (`InPunchReach` for the four melee-strike siblings, `InRearReach` for the chord, `InJumpAttackReach` for the kick, `ActionableTarget` for "already hittable, stop walking"), and the same goes for `IncomingMelee` (retreat / don't-approach / don't-hop-into-it), `WeaponUpgrade` (`could_walk_to_weapon`) and `Surrounded` (`could_call_police`'s second gate, below `POLICE_HEALTH_PERCENT_THRESHOLD_SURROUNDED`, since the special is the one move that clears every side at once); `_actors` yields **only `Myself`**, never `Partner` -- one `AgentLoop` runs per AI-controlled player and executes the surviving verb on *that* player's own `VirtualGamepad`, so a `Partner`-parametrized verb would be carried out on the wrong pad (and out-rank `Myself`'s own candidates while doing it); `Partner` stays in the context as `Information` only; `could_*` generators never pre-select a single "best" candidate (per AI.md: that ranking is `determine_priority_verb`'s job alone) -- `could_walk_to_near_enemy`/`could_throw_knife`/`could_throw_pepper`/`could_walk_to_weapon`/`could_walk_to_pickup`/`could_open_breakable` each produce one Verb per valid possibility, not just the nearest/best; `_live_enemies` excludes any enemy outside the level's playable Y lane (`lane_y_max_for_level`) -- e.g. stage 1's scripted "behind a door" placeholder, a real tracked Enemy the player can never reach -- so it can't be targeted or block stage advance; `could_walk_to_near_enemy` prefers an on-screen chase but falls back to every live enemy ahead in the stage's own scroll direction when nothing is on-screen (never one behind, per `_ahead_in_stage_direction`) -- otherwise a live off-screen enemy holds back stage advance while nothing ever moves the camera toward it; stage advance gated on *every* live enemy (on-screen or not), not just on-screen ones -- except an off-screen enemy already at exactly 0 health (`_advance_blocking_enemies`), which nothing here will ever chase down to finish off; `could_rear_attack` deliberately does *not* also fire on a bare `ClosingEnemy` inference (a live-diagnosed regression: `$322A` only hits by current position, so an early commit while the enemy is still outside `_in_rear_band` is a guaranteed whiff that locks the actor in recovery frames exactly when the enemy arrives and lands its own hit for free) -- `ClosingEnemy` is real and tested (`inference.py`) but currently has no consumer; it needs a genuine evasive reaction, not an early commit to the same reactive-only attack; `could_rear_attack` still produces on rear-band membership alone (a `could_*` answers "possible?", not "best?") -- the de-preferring lives in `priority._emergency_rear_attack` via `_rear_attack_is_warranted`; `could_walk_to_near_enemy` offers the turn-around for a behind enemy (`execute._walk_to_near_enemy_target` aims past it so the D-pad flips facing) and `could_retreat_from_danger` skips behind enemies entirely, since fleeing something already at your back means running blind while it follows; `could_walk_to_near_enemy`'s "already in range, don't walk closer" skip uses `_enemy_actionable` (real rear band, or punch band *and* actually in front) rather than raw `_in_punch_band`/`_in_rear_band` -- live-diagnosed fix: `_in_punch_band` ignores facing, so an enemy sitting behind the actor but still inside the punch box by raw distance (beyond both the real rear band and `could_punch`'s 4px behind tolerance) used to make this skip producing any verb at all, leaving the actor standing still and undefended; `could_retreat_from_danger` produces `RetreatFromDanger` for a dangerous (ATTACKING/CHARGE), not-yet-`_enemy_actionable` on-screen enemy once it's inside `_too_close_to_keep_approaching`'s caution zone -- a **box** (`punch_outer_x` + `RETREAT_CAUTION_MARGIN` on X, `RETREAT_CAUTION_MARGIN_Y` on the lane axis), not an X-only band: an X-only zone made the AI back away from a committed enemy several lanes away that could never connect, and since `could_walk_to_near_enemy` skips proposing a candidate for that same enemy, it neither approached nor retreated; the Y margin stays below `execute.WALK_TO_ENEMY_LANE_SAFETY_Y` so that verb's own sidestep actually leaves the zone; `could_grab_enemy` needs both halves already in context -- an `InGrabReach` (possible) *and* a `GrabOpportunity` (worth it) for the same pair -- plus no `IncomingMelee` for it, since walking into a committed attack is how the actor takes the hit instead of the hold; it declines while armed (every held weapon's own melee move beats a bare hold, and closing to contact spends that advantage) and while airborne (`$AAA0` needs both bodies within 8px of elevation); `could_hold_actions` targets the enemy actually in `CombatPhase.GRABBED` (falling back to the nearest) rather than whichever live enemy is nearest, since every hold move's emergency is gated on its target being GRABBED; hold always acts |
| `priority.py` | Emergency is computed per concrete `Verb` class from the `Information` tokens present in `Context` (never from the verb's type alone), including the `Inferred` judgments: `PunishWindow` decides the punishable tier for melee strikes and jump kicks, `IncomingMelee` gates `RetreatFromDanger` (its threat is over → 0), `WeaponUpgrade` carries the rank `WalkToWeapon` scores with, `Surrounded` raises `CallPolice` to 80 above the health thresholds, and any `Attack` on a **stunned** `Grunt` is capped by how much stun is left (`_stunned_target_ceiling`, applied branch-wide in `_emergency` as a ceiling that can only lower a score, reading `PunishWindow.frames_left`): hitstun (<= `phases.HITSTUN_FRAMES`) caps at 21, just above a plain strike, so the ROM's 3-hit chain -- whose third hit is the knockdown -- is not abandoned for an equally punchable fresh enemy; anything longer is the `$A0` pepper stun and caps at 19, *below* a plain strike, since that body is parked for nearly three seconds. Both stay far below the `RearAttack` escape (55/60), which they beat at the punishable tier (60) before this, and above every `Walk` tier so the actor never walks off mid-stun. Only stuns are capped; a `KNOCKDOWN` keeps 60, since that window ends in a wake-up with invulnerability — one `_emergency_*` function per class (or a shared function for the four melee-strike siblings, or a `_held_enemy_emergency` factory for the five hold moves), dispatched by a `type(verb) → function` table; module constants are named contributions, not static outcomes. Scores: counter-grab 100 (Myself held by enemy), tech-recover 90 (Myself throw_tech_ready), call-police 88 (Myself health below a lives-aware threshold: POLICE_HEALTH_PERCENT_THRESHOLD, raised to POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE on the last life), rear 60/55 (target dangerous / not) only while `decide._rear_attack_is_warranted` -- boxed in between two enemies, or target inside the punch dead zone -- and 11/9 otherwise, since `$322A` costs up to 21 frames of startup and hits only by current position, so the `WalkToNearEnemy` turn-around (12..14 in the rear band) reaches the same enemy faster and outranks it; the chord stays produced on band membership alone and still wins when nothing better is on the table, grab-enemy 58 (a `GrabToClearRear` for the pair -- above every strike on an enemy that can still act and above the warranted chord against a *calm* rear enemy, below the 60 chord against one already committed) / 30 (`GrabIntoDeadZone`, an improvement on an ordinary fight rather than an escape from a bad one), 0 with no opportunity left, supplex 68 / throw-held 70 / flip 66 / knee 64 / release 50 (target `Enemy` actually `GRABBED`), knife/pepper 25 down to a floor of 21 (target beyond melee, within throw range, 1 point per 15px closer), jump 28/18 and melee-strike (punch/swing/stab/spray, shared formula) 60/20 (target punishable / not), open-breakable 16 in smash range, else 14 down to a floor of 8 (1 point per 15px closer) -- the two tiers the former SmashBreakable/WalkToBreakable pair carried, so the merge changed no ranking, weapon 3+rank (5..8, floor `Weapon` outranks the held one, better upgrade scoring higher), walk-to-near-enemy 14 down to a floor of 8 (1 point per 15px closer), retreat-from-danger 17 down to a floor of 15 (1 point per 25px closer -- above walk-to-near-enemy's base 14 so backing off an imminent threat outranks still approaching a different target, and below the *lowest* real attack tier, jump-attack's 18, so attacking always wins once actually possible; the earlier 30/20 band broke that invariant by beating punch 20, jump 18/28 and knife-throw 21..25), stage-advance 12 (no *blocking* `Enemy` anywhere -- `_advance_blocking_enemies` excludes an off-screen straggler stuck at 0 health), pickup tiers 50/15/12/9/3 — the max wins, with the `priority` field breaking ties; hold throws outrank knees. `could_*` generators never pre-select a single "best" candidate themselves (per AI.md's own principle) -- `_distance_emergency` is what lets several same-type candidates (near-enemy, thrown-weapon, breakable) rank against each other here instead; a first coarse-bucketed version was discarded after a live run showed clustered enemies tying every tick and the AI flip-flopping targets, so this scores near-continuously instead |
| `gamepad.py` | `VirtualGamepad`/`SharedGamepadState` — the only code allowed to call `hold_buttons`/`press_buttons`/`release_buttons`; never `write_memory`/`write_value` |
| `execute.py` | `execute_verb` dispatch to controller input; every press-only handler goes through `_press`, which drops the sticky directional hold first -- `hold_buttons` latches until changed and `SharedGamepadState.press` re-arms it, so a walk tick followed by an attack tick used to leave the actor walking through its own strike (past the enemy and out of its punch band, or over the pickup it had just pressed B to collect); a walk handler whose actor/target vanished from the context releases instead of coasting on the stale hold; `_movement_mask` steers every walk verb around on-screen `Breakable`s and `Pit`s (falling in a pit costs a full life — player-health-lives-and-combat.md) and around a dangerous enemy's exact lane while still approaching it -- `_walk_to_near_enemy_target` aims for that offset lane for the *entire* dangerous approach, not just once already on the enemy's exact lane (live-diagnosed: the old on-lane gate reacted too late, since the approach converges onto that lane over several ticks regardless of the gate); `_retreat_from_danger_target` steers to this actor's `SafeSpot` when inference found one (it already weighed the sidesteps against the straight retreat by clearance, lane/camera bounds and pits) and otherwise steps straight away from the target on X, holding the actor's current lane; `_execute_open_breakable` switches on the same `decide.in_smash_range` its emergency scores with, so the tier it won on and the action it takes can never describe different situations -- out of range it walks to `_walk_to_breakable_target`, which stops just inside smash range on whichever side the actor already occupies, since a Breakable is itself a solid obstacle and its exact center is unreachable; `_execute_grab_enemy` is the one walk handler that aims at the target's *exact* position with no stop buffer (overlapping is the point) and never presses a button -- a strike would make `+$34` nonzero and turn the grab contact code into a plain hit -- and falls back to the facing direction when the movement deadband would otherwise release, because `$AAA0` first requires a non-empty attack box, i.e. a *walking* frame |
| `loop.py` | `AgentLoop.tick` — gates on pause/non-gameplay/not-playable first, then runs the full pipeline; fills a thread-safe `VerbState` (winning + every pending candidate) via `inform_hud` every tick and clears it on gate; returns the winning `Verb` (or `None`) for informational use |

Verified button mapping for the original (non-altControls) scheme (see
`execute.py`'s module docstring): **Attack/Punch is physical B** (also
`SwingBatOrPipe`/`StabWithKnifeOrBottle`/`SprayPepper` via the shared
`_execute_melee_strike`, `Supplex`'s finishing press, `ThrowKnife`/`ThrowPepper`,
and `CounterGrab`'s B edge),
**Jump is physical C** (`JumpAttack` launch, `Supplex` front→back crossover,
`CounterGrab` crossover, half of `RearAttack`, half of `TechRecover`'s C+Up chord), **Police special is physical
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
3. **Verb descendants add a second line describing when they are
   produced** — the ``could_*`` generator that creates them and the
   conditions under which it fires (e.g. "Produced by ``could_punch`` when
   an enemy sits within the actor's punch band").
4. **Verb descendants add a third line** describing how they can be
   ranked **in emergency**. This is *not* a static number: the static
   ``priority`` field only breaks ties between verbs that rank as
   equally emergent. Emergency is calculated from the *presence of other
   tokens*, or from the presence of another token *under certain
   conditions*. Format:

   ```text
   Raises emergency: InferredToken1×100, InferredToken2×50, (Weapon when distance is less than 32)×150
   ```

   Inferred tokens available to reference from these lines:
   ``IncomingProjectile``, ``IncomingMelee``, ``ClosingEnemy``,
   ``PunishWindow``, ``Surrounded``, ``SafeSpot``, ``WeaponUpgrade``, and
   the ``TargetInReach`` family (``InPunchReach``, ``InRearReach``,
   ``InJumpAttackReach``, ``ActionableTarget``).

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
attack-range extraction (`tests/test_attack_ranges.py`, over synthetic
animation blocks -- the ROM is not versioned, so nothing may depend on it),
the enemy-reach predicates (`tests/ai/test_reach.py`),
`ObserverApp.stop()` client handoff, and the full `ai/` pipeline (tokens,
observation, inference, verbs, priority ranking, execution, the
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
Verb architecture in [`AI.md`](AI.md). Observation (RAM → snapshot →
HUD/map) was unchanged by that removal.

`ai/` (see "AI surface" above) is a **fresh implementation** against that
architecture, not a revival of the removed stack — the CLI flag names
(`--agent-p1`/`--agent-p2`) are reused because they're the obvious names, not
because any removed code came back. Do not look to the old stack (it no
longer exists) for how the new one should work; follow [`AI.md`](AI.md) and
the module docstrings under `ai/` instead.
