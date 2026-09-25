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
work: two-player coordination, six-button `--altControls`, and per-boss
tactics beyond Antonio, Souther, Abadede, Bongo, the twins (Onihime and
Yasha: rear attacks from an edge, **Onihime and Yasha: the ROM model and the
plan**) and Mr. X with his Garcias (**Mr. X: the ROM model and the plan**).
One ordinary enemy has a
plan of its own, Jack (`ai/jack.py`, **Jack: the ROM model and the plan**). Antonio is **a lookahead over his own
AI, then knee, knee, release, re-grab until he dies**: `ai/antonio.py`
replays his state-1 code update by update -- gates, tacticals, the kick's
frame-by-frame boxes -- and `EngageAntonio` holds the stick that takes the
hold soonest without his kick box ever meeting the actor (see **Antonio: the
ROM model and the plan**).
Souther is **engage once, then knee, knee, release, re-grab until he dies**:
close X in a corridor his side-dependent commit gate cannot use (15px above
him, or 38px below), walk into him from the grab's lane -- contact is the
hold, and `$AAA0` tests the grab before his claw -- then two knees, a release
by holding back, and straight back into him. Armed or not; the police special
and life-gaining items are never used while he lives (user). See **Souther:
the ROM model and the plan**).

**Never hurt the partner** (user, playing P1 with the AI on P2: "The AI
grabbed me and supplexed me, it shouldn't, because it should never hurt it's
partner!"). This covers holds, not only strikes. Walking into the other
player takes a hold on them exactly as walking into an enemy does -- with no
damage out, `$4478 (resolve_player_vs_player_collision)` negotiates grab
contact, and `$3266` takes the front `$60` / back `$66` hold and links `+$4C`
to the partner's object -- and the hold family's nearest-enemy fallback then
aimed knee, `FlipHold` and `Supplex` at a bystander while the ROM delivered
them to the partner. A hold on the partner
(`PlayableCharacter.is_holding_player`) now offers only `ReleasePartner`
(hold back, never B or C, until `loc_235A` lets go), and
`partner.do_not_harm_partner` withdraws every hold move while `+$4C` names
the partner, plus `CounterGrab` while the partner is the one holding the AI
(`$34EA`/`$34E6` put the held player in `$78`/`$7A`, which reads
`HELD_BY_ENEMY`, and the counter's C then B throws the holder).

The AI no longer walks into the partner in the first place. While a
`Partner` is on screen `execute_tick` hands the winning verb's handler a
wrapped pad (`_partner_safe_gamepad`), and every D-pad mask it holds or
presses loses any walk whose walking box would reach the partner's body
within the tick (`reach.walking_box_would_grab`) *before* it reaches the
link -- stripping it after the handler's own `hold_buttons` would already
have sent a vblank's worth of it. First the X step toward them goes (the
press that turns the box onto them: after `ReleasePartner` the ROM leaves
the AI facing away, and the next walk back toward an enemy beyond them used
to re-grab), then the lane step toward their lane, then -- while still
inside their contact band -- a lane step out of it; otherwise nothing, the
one input that can never grab. `navigation.partner_obstacles` puts the same
zone in the router's danger set (and in `WalkToAdvanceStage`'s otherwise
danger-free plan), so a partner on the AI's lane is gone round rather than
waited behind. Deliberately not filtered: the pit escape (a fall costs a
life, a grab a moment), anything with A/B/C in it (strikes, jumps, hold
moves -- friendly fire stays `do_not_harm_partner`'s), a hold's own
directions (`ReleasePartner`'s back press *is* the release), airborne
ticks, and `Dialog` verbs.

The ROM facts behind it were decoded, not measured. `$4478` grabs only when
the `$45D4` table (indexed by action >> 1) reads 1 for *both* players --
idle `$02`, every walk `$06`-`$0F`, the armed ground family `$30`-`$3B`;
jumps read 2 (they hit, they never grab). `$450C`'s compares are inclusive,
so lanes 16 apart still touch. The walking box is the walk animation's own
(`$1F20` holds each character's set, `$2F2C` maps walks to animations 4/5,
armed 24/25): Axel 0..16, Adam 0..20, Blaze 0..19 -- the Souther lab's
measured 19. Idle plays animation 0, which has no attack box, so standing
still never grabs. **A lane walk grabs too**: `$2D00` sends Up alone to
`$0A` and Down alone to `$0E` through `$2EE8`, which keeps the facing bit,
and both play the same walk animation -- an Up/Down step into the partner's
lane while facing them within reach is a hold just as an X press is. Not
yet run live against a human partner; the unit tests pin the geometry.

**Items the partner needs more** (user: "a IA a usar um item de recuperação
de vida quando o partner precisa mais dele. A IA só deve usar items de
recuperação se estiver sem partner, ou se tiver partner, a personagem dela
precisar mais do item que o partner. O mesmo para armas, só apanhar uma arma
se tiver na mão nenhuma ou uma pior, e se o partner não tiver uma melhor (no
caso de empate, tentar pegar)"). Read as "who needs it more", in one place,
`partner.item_is_the_partners`: food only while the AI is *strictly* the
hurter (equal health leaves it); a weapon unless the partner is strictly the
worse armed, so a tie -- both unarmed included -- is the AI's to try (the old
rule left every weapon to an unarmed partner even with the AI unarmed too);
a 1UP to the one with fewer lives. The walks to such items are withdrawn, and
so is the pickup nobody asked for: **any grounded B press is a pickup when an
item lies within ±20 px on X and ±16 on the lane** (`$3136`, first in slot
order -- `reach.item_a_b_press_takes`), so a punch thrown beside the
partner's food ate it. The partner pad now turns that press into a step that
clears the box (`execute._redirect_b_press` / `_step_off_item`). Without a
partner, nothing changes.

**The jump kick, measured** (user: "a IA não tem bem ideia do ataque de
pontapé no ar, estudar bem esse ataque para ser previsível para a IA, não só
para quando tem um partner, mas também para ser usado no resto para calcular
os ataques"). `ai/jump_kick.py` is the ROM's flight (`$1FC0` crouch, `$1FDC`
free flight, `$2000` kick, `$21B4` hit freeze, `$3E78` landing), and it
reproduces `tools/jump_kick_lab.py`'s lockstep traces **bit for bit** -- every
16.16 position and every `+$64` box, all variants, all three characters. What
the lab found that nothing here knew:

- **every object moves at 30 Hz**: `$AD8E` waits a VBlank itself between the
  players and the object slots. The crouch is 5 updates = 10 frames (not 5),
  and every ROM rate is per update;
- launch v_z -7.5 / -8.5 / -9.5, v_x +-3.0; free flight: gravity +0.90625,
  then air steer +-0.375 (cap 3.5, turns the facing), then the B edge; the
  kick: no steering, gravity +0.53125 once v_z >= 0; a hit freezes the flight
  4 updates; kicked flights land 67.1 / 77.3 / 84.0 px on (19 / 23 / ~24
  updates), apex -34.9 / -44.2 / -54.7;
- kick box x 14..42 / 17..72 / 3..49, z -46..-19 / -43..-14 / -38..-6, lane
  +-8; Axel/Adam from the edge's own update, **Blaze 6 updates later**;
  standing bodies z -51 / -53 / -48 .. 0;
- so the box clears a standing body near the apex, and reaches it as far as
  ~110 px out on the way down -- the old 60/69/75 band under-stated the kick
  by half, which is how kicks aimed at an enemy landed on the partner.

Wired into: `reach.in_jump_attack_band` (policy gates + the simulated hit,
max dx the kicked landing), `do_not_harm_partner`'s launch test (any update,
`$450C` inclusive, partner carried at their velocity + 8/4 px), the partner
pad's airborne B hold-back (`execute._hold_back_kick`, `JumpAttack` only --
the pit hop keeps its kick), `navigation.partner_obstacles` (a kick the
partner is flying is danger), `reach.partner_is_engaging`, and a small
multi-hit bonus (+2 per extra body, up to +4). New token fields: `world_z`,
`vel_z` (`+$24`), `ground_z` (`observe.GroundTracker`, the floor a flight
lands on); `kinematics.enemy_projected` now carries the hitbox with the body.
**The 30 Hz time axis: fixed, measured, not kept.** `kinematics` treats
the ROM's per-update velocities (walk tables, enemy `+$1C`/`+$20`, thrown
weapons, Souther's dash, Antonio's boomerang) as per 60 Hz frame, so every
projection and intercept runs 2x fast, and `JUMP_CROUCH_FRAMES = 5` is
really 10 frames (`ai/jump_kick.py` already simulates it correctly). A root
fix -- one `OBJECT_UPDATE_FRAMES = 2` dividing every ROM rate, each horizon
keeping its meaning in frames -- was scored with `tools/boss_fight.py`
(Blaze, turbo 4, 8 fights a side, a fresh host per fight):

| Batch | Antonio hits/fight, mean (median) | lives lost | Souther hits, `--no-food` |
| --- | --- | --- | --- |
| HEAD, then the fix | 2.50 (2) vs 4.25 (4.5) | 2 vs 6 | 1 in 8 vs 0 |
| paired, lane-edge fix in both | 3.38 (3.5) vs 3.88 (3.5) | 4 vs 3 | 0 vs 0 |

Pooled over 16 Antonio fights, the fix took 65 hits to HEAD's 47 and never
came out ahead. For Antonio the only projection it changes is his
boomerang's (a `Boss` has no `grunt_vel`), and the extra hits come neither
from the entrance (20 vs 23 in the first 4 s) nor from the boomerang (11 vs
9 with `HitAntonioBoomerang` in the last 30 verbs). They sit in three long
fights (73-82 s), two confirmed with Antonio in tactical 9 on lane 0 --
HEAD's longest was 29 s. The first batch was also skewed by the lane-edge
freeze below (walk stalls in 3 candidate runs of 8, 1 of 8 for HEAD).
Under "keep it only if it is not worse" it was reverted. For a retry: the
horizons are tuned to the 2x-fast projection, so the unit fix has to be
retuned as a whole against these numbers, not dropped in.

**Leave the partner's fight to them** (user: "a IA a tentar atacar o mesmo
inimigo que o partner já está a atacar ou perto de atacar, estuda bem o
assunto e evita isso!"). `reach.partner_is_engaging` reads it off the
partner: holding the enemy, a kick in flight that lands on it, a strike of
theirs that reaches it, or facing it on their lane within 24 px of that reach
("perto de atacar"). `partner.PartnerFightTracker` (owned by the loop) turns
that into `PartnerFight` tokens, remembered 45 frames past the last tick it
held so a body knocked back between two hits stays theirs; `do_not_harm_partner`
withdraws the AI's attacks and walks at it (`WalkToNearEnemy`, `Punch`,
`MeleeWeaponAttack`, grounded `JumpAttack`, `GrabEnemy`, `RearAttack`, the two
throws, `EngageSouther`). Exceptions: **self-defence** (the enemy's committed
attack is about to land on the AI, `reach.is_incoming_melee`) and a kick
already in the air. With only the partner's enemies left, the AI waits
rather than joins. Two AIs on one enemy would each yield to the other until
the memory lapses -- the AI does not know whether its partner is a human, and
the human is the case this is for.

**Calling an off-screen enemy into view** (user, in Portuguese: "Por vezes a
IA fica presa a um canto do ecrã a tentar chegar a inimigos que estão fora
do campo visível no ecrã, a IA nesse caso deve-se andar para o centro do
ecrã para os 'chamar' (ter um comportamento mais humano), cria um token
para essa ação, mas não dês muita prioridade, atacar o inimigo em caso de
perigo é mais imperativo."). `could_walk_to_near_enemy`'s off-screen
fallback (`decide.py`, its own docstring: "the next wave, tracked on the
world map but not yet in camera") aims a `WalkToNearEnemy` straight at a
target's `world_x` past `navigation.world_rect`'s own bound -- deliberately
just the camera plus `navigation.WORLD_MARGIN_X` (96px, `navigation.py:144`),
since "planning across all of that would route around things that are not
on screen". Once the actor's own position reaches `CameraRange`'s walk-clamp
edge (the ROM's `$43AA`, `camera_x+$20..+$120`) there is no further lattice
position toward an off-screen target for `plan_route` to find, and the
straight-line fallback (`execute._walk_to_near_enemy_target`) is zeroed the
same tick by `execute._clamp_mask_to_camera` (`execute.py:426-444`), which
strips the blocked direction within `MOVE_DEADBAND_X` (5px) of the clamp.
`determine_priority_verb` kept picking that stalled `WalkToNearEnemy`
anyway -- nothing else in the pipeline ever proposed heading back toward the
middle of the screen -- so the AI held position in the corner indefinitely:
the reported bug.

The fix is a new lowest-priority `Walk`, `WalkToScreenCenter`
(`tokens/walk_verbs.py`), produced by `decide.could_walk_to_screen_center`
only when `decide._actor_pinned_for_screen_center` holds: nothing in
`reach.on_screen_enemies` (never while a real fight is on screen), a live
enemy still waits ahead in the stage's own scroll direction (the exact
off-screen fallback target), and the actor already sits within
`decide.PINNED_AT_CAMERA_EDGE_MARGIN` (5px, mirroring
`execute.MOVE_DEADBAND_X`) of `CameraRange`'s own edge in that direction.
`execute.state_machine_walk_to_screen_center` routes it through the same
`navigation.plan_route`/`nav.advance_goal` every other `Walk` uses, at a
strip centred on `(camera.left + camera.right) / 2`.

Scoring keeps the user's "não dês muita prioridade" literally:
`WalkToScreenCenter` is flat at `priority._EMERGENCY_WALK_TO_SCREEN_CENTER`
(9), and the stalled `WalkToNearEnemy` it replaces is capped to
`priority._EMERGENCY_WALK_TO_NEAR_ENEMY_PINNED_CEILING` (8, its own natural
distance floor) whenever the identical pinned condition holds -- both read
`decide._actor_pinned_for_screen_center`, so the two can never tie and
`WalkToScreenCenter` wins the exact tick it exists for, never before (while
there is still room to close in, the ordinary fallback keeps its full
distance score, up to 12 for a target just past the visible strip) and
never after (nothing raises the capped score back up). It stays under every
pickup, weapon, retreat and real attack tier -- a `ScorePickup` tie at 9 is
broken by `WalkToScreenCenter`'s own low `priority` field (4) -- so danger
response and any genuine progress always win, per the user's own "atacar o
inimigo em caso de perigo é mais imperativo".

**Avoiding the "hold the arena centre" mistake again:** see **The
entrance**, in the Antonio section below -- an earlier "hold the arena
centre" verb misread `CameraRange` (the walk clamp) as the visible CRT and
measured worse for it. This verb reads `CameraRange` twice, for two different and
correctly separated questions: `_pinned_at_camera_edge` asks `reach.
in_camera`'s own question, "may the actor stand any further this way" (the
walk clamp is exactly right there), while the walk's *target* is
`(camera.left + camera.right) / 2` read as the visible screen's centre --
correct only because `reach.in_visible_screen` widens `CameraRange` by
`reach.SCREEN_STRIP_X` (32px) symmetrically on both sides, so the two
midpoints coincide. `WalkToScreenCenter`'s own docstring and
`tokens/walk_verbs.py` spell this out so the distinction is not lost again.

**Holding a boss (user: "a IA não consegue lidar bem com o boss de
primeiro nível"; "os jogadores profissionais são bem fãs de agarrar e fazer
supplex, é muito importante evitar o ataque de pontapé" -- the grab-and-
suplex chain is the *intended* answer to Antonio, and taking his kick is the
thing to design against):** the round-1 fight was *unwinnable*, and not for any
tactical reason. The AI reached Antonio, walked in, and took a real front
hold `$60`/`$61` — then issued **no verb at all** for the rest of the round,
because `_is_holding_enemy` asked `+$60` (`OBJ_HELD_TYPE`). `+$60` is the
*weapon* link (`$3136`); the grab path leaves it reading `$00`, or the pipe
the actor is still carrying, and nothing times a boss hold out. Measured
twice: 70 s and 90 s of a completely static hold, Antonio on full health,
ending with the stage timer killing the player.

The fix reads the ROM's own hold link instead — player `+$4C`
(`world_map.MapEntity.contact_slot`, the field `$AAA0` requires to be zero
before it will issue a fresh grab), plus the `$60-$6F` action family, plus
the C crossover `$76`/`$80` (`PlayableCharacter.is_holding_enemy`).
`reach.held_enemy` names *which* body is in hand for the whole pipeline, and
`priority._target_is_in_hand` replaces the `CombatPhase.GRABBED`-only gate
that collapsed every hold move to emergency 0 against a boss: a **held later
boss reads primary `$04`**, the same byte as his ordinary hit reaction
(`ai-analysis/enemy-ai.md`, "Being held by a player"). Three further
consequences, each measured:

- the C crossover is 28 ticks long and ignores fresh edges, and the AI used
  to spend them on `WalkToNearEnemy` and the `$322A` chord *between its own
  `FlipHold` and the `Supplex` it was setting up* — `could_hold_actions` now
  skips that family like the other animation locks;
- `reach.grab_reasons` returns nothing at all while the actor is already
  holding, which is `$AAA0`'s own rule rather than a heuristic;
- item detours are refused while Antonio's kick gate covers the actor
  (`priority._boss_attack_gate_is_live`, health pickups excepted): four of
  the eight hits he landed across three fights arrived while `WalkToPickup`
  or `WalkToWeapon` held the tick, and a pipe is worth nothing against him
  anyway since `_could_melee_strike` refuses every grounded B on him.

Measured with `tools/boss_fight.py --level 1 --boss-type 0x56`, Blaze,
turbo 4, three fights per configuration (five for the shipped one):

| | boss killed | damage taken | fight length |
| --- | --- | --- | --- |
| before | 0/1 (stalled, timer death) | a whole life | 70 s+ |
| hold link | 3/3 | 40 / 160 / 40 | 29 / 80 / 28 s |
| + crossover | 3/3 | 60 / 40 / 40 | 30 / 29 / 21 s |
| + item gate (shipped) | 5/5, no deaths | 20 / 40 / 40 / 60 / 40 | 13-29 s |

The suplex chain carried the fight from there (2-3 suplexes plus knees per
fight, against 0 before) until the hold loop replaced it: knee, knee,
release, re-grab (**Antonio: the ROM model and the plan** below).
`tools/antonio_diag.py` is the per-tick diagnostic that found all of this:
it runs the real pipeline and logs every candidate verb with its emergency
next to Antonio's own bytes.

The hold link and the three consequences above are all still in place under
that plan. The item gate reads the ROM's own kick gate now
(`antonio.kick_gate_open`), and the one open item this section ended on --
hits landing in the armed hop `$3C`-`$42` -- went with the jump-kick plan:
the engage never jumps at him.

**The arena's food is left where it is while he is alive (user):** "não
comer a comida, a maioria dos jogadores precisa dela depois de enfrentar os
inimigos do 1º stage". `decide._food_is_spoken_for` drops every
`HealthPickup` from `could_walk_to_pickup`'s candidates while a live Antonio
is on screen -- food only (a `LifePickup` is still taken) and only until he
dies. It also overrides `_boss_attack_gate_is_live`'s old "health is the one
thing worth a kick" exemption for him.

This was worth checking rather than assuming, because the AI had been
leaning on that pickup: over ten fights of the lane-offset plan (**What the
earlier Antonio plans taught**, below), the one that took four hits survived
only by eating at 20 HP. Five fights with the food left alone:
killed 5/5, **no deaths**, hits taken `[1,2,2,2,3]` (mean 2.0, max 3)
against the ten-fight `[3,1,1,1,2,1,2,2,2,4]` (mean 1.9, max 4), and 19.6 s
mean against 22.8. So the crutch cost nothing to remove -- and the rule
holds cleanly: the only heal in the five landed at `t=12.6` with
`boss_hp=0`, after he was already dead.

**Antonio: the ROM model and the plan** (user: "We need to significantly
upgrade the AI to deal with the Antonio enemy (first level boss) ... You need
first to think and devise a sound strategy to deal the enemy, then update the
AI code"; during the work: "A AI está a depender muito da chamada da
polícia!" and "The police is allowed for Souther/Antonio, just don't test with
the police on"). Everything the AI does against him is `ai/antonio.py`, and
the plan is Souther's: **take one hold, and never give him back a turn.**
What is new is how the hold is reached. Every earlier Antonio plan was a
hand-written approach -- hop, lane offset, dodge -- tuned against a model of
him that was wrong where it mattered: his kick's lane gate is `< 8` above his
lane and `< 16` level or below (not 16 both ways), its X window depends on
the target's own `+$1C` and side, everything runs at 30 Hz, and his tactical
0 parks a target 18-21 px *below* him while rushing one above. This one is a
**lookahead over his own AI**, read from the disassembly
(`ai-analysis/enemy-ai.md`, "Antonio"):

- `antonio.boss_update` replays one update of his state-1/state-2 code from
  the object's own bytes: the screen test (off-screen, tactical 9 walks him
  back on with both gates skipped), the `$16E74` dash gate, the `$16EAE`
  kick gate, every handler of the `$16F42` tactical table with its lane
  keeping (`$179AC`, `$1797E`) and integration, the kick's attack and body
  boxes frame by frame (latched by the renderer before the frame steps, so
  the frame on screen is the one that collides), `$179F8`'s "target
  unavailable" re-read off the target every update, `$17CF2`'s pending hold,
  and `$AAA0`'s contact order: the walking box against his body first, so a
  walk into his leaning body takes the hold even through a kick already on
  its frames. `antonio.actor_update` walks the actor by `$3614`'s tables
  (`kinematics.walk_speeds`), with its boxes where `$4140` caches them --
  before `$43AA`'s camera clamp;
- **his boomerang** (`BoomerangSim`, `$17262`'s four states): frame 2 of his
  throw launches it 64 px in front of him at 14 px an update; out, it slows
  and dives down the street for 32 updates, then comes back homing on the
  top of the street -- the turn means to aim it at the target's lane, but its
  `lea $64(a0),a1` reads the boomerang's own `+$78` -- while tactical 7 walks
  him toward that lane and catches it at his hand. Back below tactical 6
  with it still out, he takes a fresh one (`$17206`) and the old one flies
  on unlinked, still able to hit. Every one of them flies in every rollout,
  and `_boomerang_path` follows them past the horizon for the end state;
- `antonio.plan_engage` tries the nine stick positions, each either held for
  two updates and then handed to a tail policy that walks at `engage_aim`, or
  held for the whole horizon, 14 updates ahead -- and each **twice**, with
  his update reaching the actor before the stick does and after, since a
  snapshot can land on either side of `$AD8E`'s VBlank wait. A candidate
  scores by the worse of the two: a grab by how soon, a hit below everything
  else by how soon, the rest by distance to the aim, the aim's mode and
  whether his gate or kick is live where it ends. The simulated hit is 2 px
  wider and a lane deeper than the ROM's, the grab is exact, and a hit
  reaction's immunity is assumed to be over already;
- `EngageAntonio` holds the winning stick every tick, and the hold loop is
  Souther's: two knees, `ReleaseToRegrab` (he lands 40 px in front of the
  actor, `$17D76`), straight back in, and a finisher only when it kills
  (`antonio.hold_step` is `souther.hold_step`).

Nothing hard-codes the geometry the lookahead keeps finding: **8-16 px above
his lane** is kick-proof (the gate needs `< 8` there) and grab-ready (the
contact reaches 16), and the engage walks in along it.

Scored with `tools/boss_fight.py --level 1 --boss-type 0x56 --no-food`,
turbo 4, a fresh host per fight (a hit is 20 damage; four kill from full
health):

| | fights | killed | hits taken | lives lost | holds | fight length |
| --- | --- | --- | --- | --- | --- | --- |
| previous plan (hop, lane offset, walk-in grab), Blaze | 8 | 8 | 2, 2, 6, 2, 2, 3, 3, 6 (mean 3.25) | 2 | 1-3 | 13.0-32.3 s |
| lookahead, executor clamped to the camera, Blaze | 8 | 8 | 2, 2, 0, 0, 2, 2, 3, 3 (mean 1.75) | 0 | 5 | 4.2-6.1 s |
| lookahead, Blaze | 8 | 8 | **0 in every fight** | 0 | 5 | 2.4-4.4 s |
| lookahead + model fixes, Blaze | 5 | 5 | **0 in every fight** | 0 | 5 | 2.4-4.2 s |
| lookahead + model fixes, Axel | 5 | 5 | **0 in every fight** | 0 | 5 | 2.2-4.3 s |
| lookahead + model fixes, Adam | 5 | 5 | 0, 0, 0, 1, 0 (mean 0.20) | 0 | 5 | 2.2-3.8 s |
| + the boomerang model, Blaze | 5 | 5 | **0 in every fight** | 0 | 5 | 2.4-4.4 s |
| + the boomerang model, Axel | 5 | 5 | **0 in every fight** | 0 | 5 | 2.5-9.0 s |
| + the boomerang model, Adam | 5 | 5 | 0, 0, 0, 1, 0 (mean 0.20) | 0 | 5 | 2.4-30.5 s |

The previous plan's batch ran with the police allowed, and its old 60% boss
gate called it ten times in eight fights -- in every fight, right after his
second kick; no lookahead fight called it. The second row is the one bug
worth remembering: `execute._clamp_mask_to_camera` stripped the RIGHT press
at the camera's right edge, which is both the direction that walks into him
as he walks back on screen (tactical 9) and the walking box a re-grab needs
at the moment of contact -- every hit of that batch landed there.
`state_machine_engage_antonio` holds the plan's stick unclamped.

**The first Adam hit was the boomerang, not the kick.** One from an earlier
throw, coming back up the street, landed on an armed Adam standing 130 px
out and 5 px below his lane. Two things let it through: the lookahead did
not model the boomerang at all, so standing there looked fine; and
`HitAntonioBoomerang`, which punches it away, pressed B with a weapon in
hand -- the swing, ~26 frames committed and only live near its peak -- on
the punch's 3-5 frame timing, projecting the boomerang with the wrong
velocity besides (`Projectile.vel_x` read `+$20`, which for this object is
its lane). The swing went out early and the boomerang landed during its
recovery. Now the boomerang is modelled from the ROM (the bullet above), the
counter is offered unarmed only, and a `$96`'s `vel_x` is its `+$1C`.

**Still open: the corner.** The last Adam batch took one hit in five fights,
and it is a different failure: a 30-second fight whose first hold came at
28 s. He sat a lane or two above the actor near the top of the street,
where the pocket 12 px above him runs out of street, and pushed it right
with dash-kick cycles -- the dash closing 4 px, the kick at 117 px landing
nowhere, again -- until the actor was pinned at the camera's right edge and
the top lane, 7 px above his lane, and a kick from 70 px landed. Adam climbs
lanes at 1.25-1.5 px an update against the 4 px rush a target above him
gets, so he is the one it catches (Blaze and Axel took none in 18 and 10
fights since the camera-edge fix). The lookahead's 14 updates cannot see a
trap that forms over seconds; what should fix it is a term for being boxed
in against the camera and the street's edge with him between the actor and
the open side. Not written yet.

`tools/antonio_lab.py` checks the model against the ROM in lockstep, one of
his updates at a time. With a seeded walk that never attacks (`--actor
wander`, which takes him through every state he has) the first run compared
702 updates field by field and turned up four things the model did not do:
`$179F8`'s re-read of `+$77`, `$AA34` skipping a player in a hit reaction
(`+$59` bit 1) or with a contact code still latched in `+$7C` (23 kicks
"landing" on a player lying on the floor), the `$17CF2` hold, and the boxes
cached before the camera clamp. With them in, two more wander runs (578 and
648 updates) left nothing on the side that matters. The model predicts kick
hits the ROM does not land -- 7 and 10: kicks from behind, where it takes the
actor's body at its widest reach on both sides; a player already in the air
or down in a hit reaction, since it has no height axis; frame 1's short box
at its very edge -- and it never missed a kick that landed.

The boomerang went through the same lab once it was modelled. The first
comparison ran into a second boomerang -- the fresh one he takes while an
old one is still out, which the lab had been confusing with it -- and, once
both were told apart by his `+$6E` link, a launch read one update early
(it reads his frame before the renderer steps it). Since those two, two
runs -- 461 and 449 of his updates with a boomerang in flight, launches
among them -- have matched position, velocity, box, turn, homing and state
exactly, and tactical 7's walk toward its lane with them. What the model still over-predicts is
height, which it does not have: the boomerang flies 48 px up and its box
reaches down to exactly Blaze's head (-48), 3 px into Axel's and 5 into
Adam's -- 11 boomerang "hits" on the lab's Blaze landed nowhere, while
Adam's live one did -- so the plan treats a boomerang in reach as a hit
for everyone. The same lab showed the camera edge's box rule holds on the
lane: four grabs the model predicted at the top of the street -- a walk held
up into lane 2, sixteen lanes above him -- never happened, because `$43AA`
clamps the lane too, after `$4140` cached the box a step higher. The
player's `+$20` lane velocity now moves the box past the lane clamp as
`+$1C` does past the camera's (added after the last scored batch; a unit
test and the final wander run cover it). Left besides: the mirror bit of his animation
(twice a run, cause not found). With the real pipeline playing (`--actor
engage`) he died in 165 frames: 0 hits, 4 holds, and not one kick started.

**What the earlier Antonio plans taught**, each paid for in runs:

- **The jump kick as the plan** (user: "os jump-kicks são seguros, mas é
  lento e perigoso atacar dessa maneira... ainda dominam a maneira da IA
  lutar"): 45 committed airborne frames for about 2 damage, and the place
  every hit landed. The hold replaced it at contact range first; now the
  engage never jumps at him.
- **A lane offset is not safety** (user, after a lost life: not
  acceptable). The offset's side came from the band's midpoint, so the
  approach crossed his lane to reach it; fixed, it still took a mean 1.9
  hits over ten fights, max 4. Every one of the 19 hits in those fights
  arrived within two agent ticks of primary `$02`, and a hop needs ~45
  frames: **his kick cannot be answered reactively**, only by never
  standing where it can start -- which is what the lookahead plans.
- **The entrance** (user: "a IA começa logo por levar dois pontapés
  evitáveis. Enquanto espera pelo Boss, devia ficar no meio da camara
  visível e estar aware de inimigos fora da camara visível"): 7 of those 19
  hits came in the first three seconds. Three ways of waiting for him all
  measured worse -- exempting a boss from the lane filter froze the pipeline
  with no verb at all, a "hold the arena centre" verb read `CameraRange` (the
  walk clamp) as the visible screen, and waiting as a standing preference
  was passivity. What removed those hits was the lookahead treating his walk
  back on screen as the grab it is, and the camera-edge bug above.
- **Measured no better and reverted**, under the old plan: refusing the
  weapon detour whenever he is on screen, lifting the grab's armed
  exclusion for him alone, and widening the hop's withdrawal to its whole
  band. Armed, the engage now simply walks in (`$AAA0` never reads the
  weapon; one of the eight shipped Blaze fights started armed) and the
  detour stays refused while he lives
  (`decide._a_weapon_would_disarm_the_plan`).
- **The police** (user: "A AI está a depender muito da chamada da
  polícia!"): the panic threshold only, and never on in a test -- see **And
  without the police**.

Not measured yet: two players, the round-8 boss rush's Antonio, and Antonio
with the street waves alive (deliberately -- see **Testing the AI against a
boss**).

**Souther: the ROM model and the plan** (user: "We need to substantially
improve the AI's performance against the Level 2 boss, Souther ... It is
already understood that grabbing Souther and repeatedly dealing damage to him
is an effective strategy"; "do not use police attacks or life-gaining items";
prefer deterministic behaviour; do not preserve old behaviour for its own
sake). Every attempt before this one tuned lane margins against a model of him
that was wrong in three places. The rewrite started from the disassembly and a
lockstep lab, and the whole plan now lives in one module, `ai/souther.py`.

What the ROM says (full decode in `ai-analysis/enemy-ai.md`, "The claw box,
the side-dependent gate, and holding him", and `ai-analysis/controls-and-
input.md`, "The knee chain, the release, and the one crossover"):

- **The commit lane gate is side-dependent**: `+$52 < $0A` when the target is
  above him and `< $1C` otherwise (`+$61`, from `$17B2C`). Every earlier
  attempt used 28px for both sides. 11-15px above him is outside the gate and
  inside grab range at once.
- **The claw is his own attack box** (set `$2E44A`, animation 4): 0..86px
  forward over lane -10..+24, with his body leaning 36-42px forward while it
  swings. The type-`$98` object has no box, and the old dodge's clearances
  were computed from it. An ordinary claw swings in place; the lane-blind
  8px/frame dash only follows the jump counter.
- **Grab beats hit**: `$AAA0` tests the player's attack box against his body
  before his attack box against the player, and never reads the carried
  weapon. Walking into him with the walking box out is a hold, even through a
  swinging claw, whenever that box reaches his leaning body first. A strike
  (`+$34` set) is a hit instead, and his hitstun `$03` cannot be grabbed.
- **He never escapes a hold, and a release is the best move in it.** Holding
  back counts `+$63` down from 3 and drops the hold on the ~8th frame; he goes
  straight to primary 1, 32px in front of the actor on its lane -- in reach of
  an immediate re-grab. The third knee (`$6E`), the throw and the suplex all
  put him 90-165px away, which is the re-approach every earlier plan paid for.
  One crossover per hold (`+$4B` bit 7); a second one drops him free next to
  the actor, measured as a claw three frames later.
- He updates at 30Hz, so every per-frame rate in the old notes is per update.

The plan (`souther.plan_engage`, `souther.hold_step`):

1. **Engage** (`EngageSouther`, emergency 62 plus the boss 14): close X in a
   corridor 15px above him (inside the grab lane, outside the 10px gate) or
   38px below (past the 28px gate and the claw's 32px deep side), on the side
   the actor is already on; converge from below only inside `$18`; leave a
   live claw's band by lane only; and once in the grab lane within 48px, walk
   into him with the toward bit held every frame.
2. **Hold loop**: knee, knee (4 damage), then `ReleaseToRegrab` presses back
   for exactly the countdown's frames and holds toward him, and the engage
   walks straight back in. A back hold crosses over once, then releases. A
   finisher is used only when it kills (third knee at 3 health or less, suplex
   at 5).
3. **Nothing else aims at him**: `Punch`/`MeleeWeaponAttack`, `GrabEnemy`,
   `RearAttack`, `WalkToNearEnemy`, `RetreatFromDanger` and the jump all stand
   down for him; `HealthPickup`/`LifePickup` are refused while he lives, and
   the police is only ever the panic button (tests run with `--no-police`).

Measured with `tools/souther_hold_lab.py` in lockstep (Blaze): the re-grab
lands 4-6 frames after each release, six cycles running, no damage; with two
frames of injected input delay he commits 3 frames after the release and the
lean-contact grab still takes him at frame 6. Then `tools/boss_fight.py
--level 2 --boss-type 0x55 --no-food`, turbo 4, a fresh host per fight:

| | fights | killed | lives lost | hits taken | fight length |
| --- | --- | --- | --- | --- | --- |
| previous plan (the n=20 baseline in the lessons below) | 20 | 20 | 2 | median 2, mean 2.15, worst 7 | clean fights 16.8-26.7 s |
| engage + hold loop, Blaze | 16 | 16 | 0 | 0 in every fight | 2.1-4.1 s |
| engage + hold loop, Axel / Adam | 2 / 2 | 4 | 0 | 0, 0 / 0, 1 | 2.4-6.7 s |
| + the engage armed too, Axel / Adam | 3 / 3 | 6 | 0 | 0 in every fight | 4.2-4.5 s, 7 holds each |

The one hit in that table: Adam walked into the arena armed,
`could_engage_souther` still excluded an armed actor, and the generic armed
approach walked his lane 31px below him inside `[$18, $68)` -- exactly the
ground the corridor avoids. The engage now runs armed too. None of the six
fights after that change happened to start armed, so the armed path rests on
the ROM read (`$AAA0` never consults the weapon) and the unit tests, not yet
on a live fight.

Axel's and Adam's walking-box reach is no longer unknown: the ROM's walk
animations give 16 and 20 (`reach.WALK_BOX_REACH_X`, decoded for **Never
hurt the partner** above). `souther.WALK_BOX_REACH_X` still carries Blaze's
19 alone, with the narrower 14 for the other two, because adopting the wider
figures widens their walk-in and no fight has measured that yet. Not
measured yet: that, the round-6 Souther pair, and two players.

**What the earlier attempts taught**, kept because each one was paid for in
runs:

- **Measure in hits, over many fights.** Identical code spread 0-12 hits a
  fight, so nothing here was decided on fewer than five runs a side, and the
  baseline took twenty. `damage_pct` counts a death as +100 points, which made
  the baseline look bimodal; one life is four hits.
- **Aligned on his lane anywhere in 24-104px lost the whole game in every
  fight**, three variants of it (the chase with every protection cut, the
  lane alone, the lane plus a nearest-edge dodge; 15-17 hits a fight). That
  range is his commit band. The user asked for the alignment repeatedly ("eu
  quero que o Y do inimigo e do jogador se alinhem"); the plan aligns inside
  the grab band, which is outside his gate on the upper side.
- **Measured worse and reverted**: refusing the strike from outside the
  pocket (and demoting it), holding the lane offset while a claw is out, three
  more lane aims, and holding him until the suplex would kill -- the `$6E`
  stage alone took ~160 ticks, which is what the release now avoids.
- **Four arrival bugs** made the old corridor look like a stalemate, and
  their fixes are still in place: the enemy-side lane band
  (`reach.in_targetable_lane` -- he fights from lanes 0-1, below the player's
  floor), the visible-screen band (`reach.in_visible_screen`), and
  `phases.boss_phase` reading `$05` (the lethal gate, visited on every hit) as
  death and a walking primary `$01` as attacking.
- **The police special freezes the caller** for the shared `$16AEC` delay
  (~5 s) and was most of the damage in one batch (user: "a maioria do dano
  deve-se a ataques de polícia, não usar ataques de polícia"). Since then the
  rule is: allowed in play as the panic button, never on in a test (user:
  "The police is allowed for Souther/Antonio, just don't test with the police
  on") -- see **Scoring a fight without the food**.
- The user's other asks over those sessions -- "e essencial agarrar o boss",
  "tem muita precaução, simplesmente tem de ir atrás do boss e tentar
  agarrá-lo", "deve evitar o seu ataque, mas só apenas o suficiente para não
  apanhar dano" -- are what the plan above does in the form the ROM allows:
  the hold is the plan, the approach is direct, and the only evasion is
  staying out of the claw's own box.

**Bongo: the ROM model and the plan** (user: "Neste momento a IA lida muito mal
com o inimigo Bongo, o boss do stage 4 ... Deves primeiro pensar bem para chegar
a uma estratégia para o derrotar de forma eficiente em termos de tempo decorrido
e vida perdida"; "Nos testes, não te esqueças de não usar o ataque especial
(chamar a polícia), e de não consumir items de recuperação de vida"). Everything
the AI does against him is `ai/bongo.py`, and the plan is Antonio's shape:
**take one hold, and never give him back a turn.** Before it, a scored fight
(Blaze, `--no-food`, police off) lost two lives in 19 s and took him from 30 to
23: the generic walk-in ate seven 32-point flames, every one of them in his
charge.

What the ROM says (full decode in `ai-analysis/enemy-ai.md`, "Bongo"):

- **He never touches anyone himself.** No animation he fights in (set
  `$2EF62`) has an attack box, and `$174E0` clears his `+$34` every update.
  His one weapon is the **flame**, type `$97` (`$1781E`): born the update his
  charge launches, placed 20 px ahead of him on his lane + 4 at head height
  (`$178D0`), carrying his `+$4A` -- **32 on Normal: three kill from full
  health**. Its box grows through the ignition (`$9D`/`$9F`/`$A1`, four updates
  each) to `$A3`: x +4..+76 ahead of him, lane -6..+28 of his -- against a +-8
  body, **every lane from 14 above him to 36 below**. No body box.
- **State 1** (`$175BA`): a target on his back side costs a 10-update turn
  standing still; otherwise he walks at it 0.5 px an update and keeps the lane
  gap in `[$50, $60)`, stepping away when closer (a level target counts as below
  him: he steps up). Inside `$B0` (176 px) on X he winds up.
- **State 2** (`$17682`): the wind-up is tacticals 0-2 (5, 5, 10 updates on
  `+$68`), drifting at state 1's last velocities -- 21 updates from the gate to
  the launch. The launch: X 2 px an update on his facing, lane `+$52 / (+$50 /
  2)` toward the target's lane (he would reach it as he reaches the target),
  capped at 6. Tactical 3 adds 0.125 to both every update (to 6), the lane only
  while `+$52 >= 8`, and **never re-aims**. Past the target by `$50`, tactical 4
  runs 20 more updates or until his screen X leaves `[$50, $1F0)`, then state 1
  facing away: a turn. So every charge ends at a screen edge on a lane clamp.
- **Grab first, flame after** (`$AAA0`): his update tests the walking box
  against his body before the flame -- in a later slot -- tests its box on the
  player's body. But the flame has **no body box**, so `$AAA0` never enters the
  grab path that shields a holder from Antonio's kick: **a holding player is
  not spared.** An igniting flame stays placed on him whatever he does
  (`$17858` retires it only from anim `$3C`), and a front hold stands him 32 px
  out facing the holder -- so a front grab in the first 12 updates after a
  launch is the flame's hit. A back hold (`$17E22`) stands him facing away.

Out of that, two safe places during a charge: **15-16 lanes above him** (the
flame's top edge is 14, the grab reaches 16 -- exact, so the flame is simulated
with no lane margin: a margin of one leaves only 16, which Blaze's 1.625 px lane
step does not always land on) and **behind him** once his origin has run 9 px
past the actor. And one set-up before a charge: with him on the bottom clamp,
level with him at the launch (lane velocity 0), so the charge runs along the
clamp and the pocket above it holds still.

The plan (`bongo.plan_engage`, `EngageBongo`,
`execute.state_machine_engage_bongo`):

1. **A lookahead over his AI and the flame** (`boss_update`, 2.4 us an update):
   the nine sticks, each held for 2, 8, 16 updates or the whole 44-update
   horizon and then a phase-aware tail (`_Tail`), each under both update orders
   and scored by the worse -- a hold by how soon, a hit below everything, and a
   burnt grab (`_grab_is_burnt`: the hold's first passes played out) as the hit
   it is. About 5-7 ms a tick.
2. **The tail's phases** (`engage_mode`): WALK_IN whenever contact comes before
   his launch -- the entrance (he spawns 40 px off, facing away: turn plus
   wind-up is 31 updates) and every release; STALK while he walks in (a few
   lanes above him, beyond his gate, his X taken where the edge nudge `$17744`
   will put him); LEVEL/DIVE through a wind-up; POCKET/BEHIND through a charge,
   with the dodge lane worked out once from his predicted path -- above him
   first when it is reachable before the flame, else below.
3. **The hold loop is Souther's** (`souther.hold_step`): knee, knee,
   `ReleaseToRegrab` -- he lands 32 px out facing the actor and goes straight
   into a wind-up, 21 updates in which the walking box, already touching his
   body, takes him again. Nothing about the flame belongs in the hold: the
   answer to a burnt grab is not to take it.
4. **The round's grunt** (user: "no stage 4, existe sempre um inimigo Grunt que
   pode atacar a IA pelas costas, se esse inimigo for derrotado, o jogo instancia
   um novo inimigo idêntico. Portanto, não se focar nesse inimigo, mas prevenir
   ataques iminentes"): Garcia-family types `$20`-`$22` keep arriving through the
   fight (`bongo_lab.py`'s rows; the harness sweep kills each and the next
   comes). `EngageBongo` drops from 76 to 19 -- just under a punch on it (20),
   above walking to it (8-14) -- while its committed strike is about to land
   (`reach.is_incoming_melee`) and his charge is not pressing
   (`bongo.charge_is_pressing`: running, or its launch 6 updates away or less).
   Nothing ever walks to it. In a hold, a strike landing from **behind**
   sooner than a knee finishes (`reach.frames_until_any_melee_lands` against
   `kinematics.hold_knee_frames`, with `reach.rear_threats`) gets Bongo thrown
   back into it (`ThrowHeldEnemy`) -- Bongo only; Souther's and Antonio's
   rounds are swept clean and their loops were measured without it. What the
   live runs actually met was the other side: a type-`$22` Garcia walking in
   from the camera's right edge (its approach `$09`, `$E124`) and punching
   (`$0A`, `$E190`: two stages, forward 0..+40 then +16..+51) from 57-62 px
   *in front* of the holder, over the held Bongo, for 8. Nothing a hold has
   answers that one: the throw goes backward and locks the actor 41-46 frames
   against a punch that lands in 5-12, and letting go gives up the 21-update
   wind-up that makes the re-grab safe for a flame worth 32. So it is taken;
   the entrance fights end before any grunt arrives.
5. The rest stands down for him: `Punch`/`MeleeWeaponAttack`, `RearAttack`,
   `GrabEnemy`, `WalkToNearEnemy`, `RetreatFromDanger`, the grounded
   `JumpAttack`, the weapon detour, and `ProjectileSidestep` on the flame.

The model was checked in lockstep before anything was built on it
(`tools/bongo_lab.py --actor wander`, two seeds): 2253 of his updates, ten
charges, every field of states 1 and 2 and of the flame matching the ROM, bar
two updates where the player's respawn knocked him back. On contact it missed
no hit; it over-predicts on a player lying down (a low body box) or at the
+-12 edge of the body -- the safe side. With the real pipeline playing
(`--actor engage`) he died in 389 frames: no hit, seven holds, not one charge
launched, and the 29 of his updates spent outside a hold all matched.

**What the live runs taught.** The first scored fight on the plan killed him in
9.4 s with nine holds and took three hits, all with him *held* -- each a front
grab 2-8 updates after a launch, the flame still igniting on him. That is how
"a holder is not spared" was found; `_grab_is_burnt` came out of it, and
offline (40 randomized sim-vs-sim fights: entrance, far, turn, wind-up and
mid-charge starts, all three characters) the planner went from 19 hits to 2
with the longer stick holds and the predicted dodge, then to none with the
burnt grab.

Scored with `tools/boss_fight.py --level 4 --boss-type 0x57 --no-food`, turbo
4, police off, a fresh host per fight (a hit is 32 damage; three kill):

| | fights | killed | hits taken | lives lost | first hold | fight length |
| --- | --- | --- | --- | --- | --- | --- |
| before (generic approach), Blaze | 1 | 0 (two lives lost) | 7 | 2 | 0.47 s | 19.1 s |
| plan, grab not yet checked for the flame, Blaze | 1 | 1 | 3 | 1 | 0.63 s | 9.4 s |
| plan, Blaze | 4 | 4 | **0 in every fight** | 0 | 0.44-0.46 s | 3.3 s |
| plan, Axel | 4 | 4 | **0 in every fight** | 0 | 0.47-0.48 s | 3.3 s |
| plan, Adam | 4 | 4 | **0 in every fight** | 0 | 0.53-0.83 s | 3.3-4.0 s |
| plan, hands off for the first 3 s (`--idle-seconds 3`), Blaze | 4 | 4 | no flame; one 8-point grunt punch in 3 fights | 0 | 0.99-1.01 s | 3.9-4.4 s |
| plan, hands off for the first 3 s, Axel | 4 | 4 | no flame; one 8-point grunt punch in each | 0 | 1.00-1.01 s | 4.3-4.4 s |
| plan, hands off for the first 3 s, Adam | 4 | 4 | **none** | 0 | 0.92-0.94 s | 3.7-3.8 s |

Every scored fight on the plan is decided at the entrance: the hold comes
before his first launch and the loop never lets him go. The idle rows are the
same fight joined after the AI stood still through his first charge -- the
start that exercises the pocket, the dodge and the burnt-grab refusal live --
and every one of their holds was taken from his charge without a flame: all
seven hits in them are the round's grunt, the type-`$22` punch from in front
of the holder over the held Bongo (4 above), 8 points each, at 1.5-2.0 s. An
earlier idle batch handed the pad over mid-charge and took two unavoidable
flames within 0.04 s, which is why `--idle-seconds` now waits him out of it.

**Abadede: the ROM model and the plan** (user: "Neste momento a IA lida muito
mal com o inimigo Abaded, o boss do stage 3 ... Deves primeiro pensar bem para
chegar a uma estratégia para o derrotar de forma eficiente em termos de tempo
decorrido e vida perdida"; and for the tests, as for Bongo: no police, no
life-giving items). Everything the AI does against him is `ai/abadede.py`,
and the plan is the other bosses' shape: **take one hold, and never give him
back a turn.** Before it, a scored fight (Blaze, `--no-food`, police off)
killed him in 31 s but took seven 32-point hits and two lives, every one of
them in his run (state 7), 27-52 px out and within 13 lanes of him.

The user proposed a *sweet area* against his run: he backs off, runs, and
ends the run with a punch nothing touches -- so stand where the run arrives
and punch him while he runs, when he can be hit. The ROM agrees about the
run and about the sweet spot, and adds three things that change what to do
in it (`ai-analysis/enemy-ai.md`, "Abadede", decoded for this):

- **Only the run hurts.** His contact code 1 is his hit in the run and his
  grab-and-throw in the approach and the pause (a lane +-2 walk box: 10
  lanes), is dropped in the retreat, and in the punch that ends the run
  `$14CDC` clears the target's `+$7C` in the same update: the punch is
  untouchable (no body box) and lands on nobody.
- **The sweet area is a lane, and it is a grab.** His body is lane +-10 and
  the run's box lane +-8: against a player's +-8 the walking box meets his
  body up to 18 lanes away while his box reaches 16. **17-18 lanes off the
  lane his run keeps (it never re-aims), walking at him, the run delivers him
  into a hold.** On his lane the run's box is met 13 px before any walking
  box can reach his body; only a punch (Blaze's box ends 68 px out) gets
  there first.
- **A punch is 1 point; a knee is 2.** A punch he runs into buys 11 updates
  of shake and then a retreat -- and his run again a second later -- while a
  hold runs the loop below: 4 points a cycle, and no turn of his.

The plan (`abadede.plan_engage`, `EngageAbadede`,
`execute.state_machine_engage_abadede`):

1. **A lookahead over his AI** (`boss_update`: states 1, 2, 3 and 7, the
   shake, getting up and a released hold, update by update, from `+$5B` and
   `+$54` as well as his usual bytes): the nine sticks, each held for 2, 6
   or 14 updates or the whole 40-update horizon and then a phase-aware tail
   (`engage_mode`), plus a punch pressed on one of the next seven updates,
   standing or after walking toward him (below, 3), each under both update
   orders and scored by the worse -- a hold by how soon, a punch landing on
   his run next, a hit below everything. 2-5 ms a tick.
2. **The tail's phases**: SWEET while his run is coming (17-18 lanes off its
   lane by whichever step lands in the band, straight or diagonal, and the
   walking box at him); WALK_IN while he walks in or pauses (into him from
   11-15 lanes: outside his walk box, inside his gate); READY while he cannot
   collide and is grabbable next (the brake, the punch, the shake, a released
   hold: in front of him, walking in lane with the box on his body); SET_UP
   while he backs off (13-15 lanes off, so the pause decides a run with the
   band a step or two away); WAIT through a knockdown.
3. **The punch is the user's move, as the fallback**: pressed only when no
   rollout reaches a hold and one reaches his run with it -- caught on his
   lane with the run too close to leave. `can_punch` is off armed (B swings)
   and with an item underfoot (B picks it up -- food, in a fight scored
   without it). **It is thrown in the facing the actor already has**: the
   ROM samples the facing a punch starts with, so B and a turn on one press
   is thrown the old way -- a committed miss facing away (`execute.
   _facing_prop`; traced live against Jack, five punches whiffed). The first
   plan turned the rollout's actor to him on the punch and `execute` pressed
   B with the turn; now the rollout keeps the facing, six more candidates
   walk toward him (`antonio.actor_update` turns the actor on a walk) before
   a punch on updates 1-6 -- the plan's stick is that walk until then -- and
   `execute` presses B alone. Found in the code, by Jack's trace; no Abadede
   fight has been scored since.
4. **The hold loop** (`abadede.hold_step`) is Souther's -- knee, knee,
   release, walk straight back in -- with one ROM rule of his own: he reads
   the holder's `+$7D` only in state `$B` substate 1, and a knee's damage is
   the holder's `+$34` on that read, while each knee costs him 12 updates of
   shake in which he reads nothing. So every knee and the release wait for
   that substate (`reads_the_hold`). The release leaves him in state 3 on his
   feet where he stood, and that state's first contact test is the re-grab;
   the finisher only when it kills (third knee at 3, suplex at 5). A back
   hold crosses over (he reads 9 as "held on") -- except in state `$D`, where
   a crossover frees him.
5. **The round's grunt** (user: "existe sempre um Grunt atrás da personagem
   controlada, mesmo que seja derrotado, aparece outro, a AI deve-se proteger
   desse inimigo, sem se desviar o objetivo principal, o boss"): Bongo's rule
   -- `EngageAbadede` drops to 19 while a grunt's committed strike is about
   to land and his run is not pressing (`abadede.charge_is_pressing`), so the
   punch on the grunt wins, and nothing walks to it. In a hold nothing
   changes: throwing him carries him into nobody (his thrown state tests no
   contact), and a holder hit while holding him sends him on the throw's
   flight -- 4 points to him.
6. The rest stands down for him: `Punch`/`MeleeWeaponAttack`, `RearAttack`,
   `GrabEnemy`, `WalkToNearEnemy`, `RetreatFromDanger`, the grounded
   `JumpAttack` and the weapon detour. `phases.boss_phase` reads his real
   table: `$0C` is his death and `$0E` a throw's flight (the old decode had
   `$0E` as the death, so every throw read as a kill), `$07` the run, `+$67`
   his one-update police latch.
7. Round 8's Abadede is a variant (a non-zero low nibble of his `+$40`, the
   ELC spawn parameter, now carried on every `Boss` token as
   `script_param`): his pause decides on a `$18` lane gap and never backs
   off first (`$146C4`). The model plays that branch; no round-8 fight has
   been run.

Scored with `tools/boss_fight.py --level 3 --boss-type 0x30 --no-food`, turbo
4, police off, a fresh host per fight (a hit is 32 damage; three kill from
full health):

| | fights | killed | hits taken | lives lost | first hold | fight length |
| --- | --- | --- | --- | --- | --- | --- |
| before (generic approach), Blaze | 1 | 1 | 7 | 2 | 0.15 s | 31.0 s |
| plan, Blaze | 4 | 4 | **0 in every fight** | 0 | 0.07-0.13 s | 2.4-4.4 s |
| plan, hands off for the first 3 s (`--idle-seconds 3`), Blaze | 3 | 3 | **0 in every fight** | 0 | 0.36-0.99 s | 4.6-5.6 s |
| plan, Axel | 3 | 3 | **0 in every fight** | 0 | 0.09-0.12 s | 4.3 s |
| plan, Adam | 3 | 3 | **0 in every fight** | 0 | 0.12-0.13 s | 4.3-4.4 s |
| plan, hands off for the first 3 s, Axel | 1 | 1 | **0** | 0 | 1.00 s | 5.2 s |
| plan, hands off for the first 3 s, Adam | 1 | 1 | **0** | 0 | 0.64 s | 2.9 s |

A fight on the plan from the entrance is decided there: he walks in, pauses
13 lanes off, the walk-in takes him, and the loop never lets go -- 7 holds,
16 knees of 2 points, each release re-held two updates later. The idle rows
are the fight joined wherever he had got to while the actor stood still (he
had run into it, or the respawn's landing had knocked him down), and they
exercise the rest of the plan live: three times (Blaze twice, Adam) the pad
came back in his brake or punch, and READY stood in front of him and took
him on his retreat's first contact test; twice (Blaze, Axel) he got up from
the respawn's knockdown, walked in, paused and ran -- once from 150 px -- and
the actor climbed to 18 lanes off the run's lane and took him **in the run**
(state 7 straight to `$B`): the sweet area, as a hold. (One more Axel idle
fight lost its host before the boss appeared -- the connection closed
mid-round -- and was run again; it is not in the table.)

Offline, the planner against the model (80 randomized starts in every state
he fights in, all three characters, from any lane): 80 holds, no hit, a
median of 12 updates to contact; the plan takes 2.3 ms a tick (4.4 at p95,
5.4 worst). An earlier sweep of 60 put the punch to work twice -- starts on
his lane with the run already close -- and took no hit either.

`tools/abadede_lab.py --actor wander` checked the model in lockstep: two
3000-frame runs (seeds 2 and 3) checked 2036 of his updates outside state 8
(his hold and throw of the player, which the model does not replay), and
2026 matched field by field -- every state it replays, all four charge
substates, the hold, the knockdown, getting up. Seven of the other ten are
run updates the model called a hit that the ROM did not land: the model
takes the actor's body at its widest (`PLAYER_BODY_REACH_X`, +-12 for
Blaze), and the `+$70` the lab logs put a walking Blaze's at 10 px wide
(-2..+8 facing right, -5..+5 facing left) -- the model errs toward the hit.
The other three are knockdowns the player's respawn landing gave him.

The first idle fight showed the one grab rule the first model lacked:
`$3266` refuses a hold with him *behind* an actor facing his way -- the code
lands, he stands up 24 px in front of the actor and backs off, which cost
four updates there. The model now plays it (`Outcome.REFUSED`, a contact the
rollout goes on through).
The host itself stops completing lockstep frames now and then in round 3
(three runs of five, never on the same frame); the lab ends such a run as
`host_timeout` and keeps its checks.

**Onihime and Yasha: the ROM model and the plan** (user: "Improve the Stage 5
boss AI ... Move the controlled character toward either the far left or far
right side of the screen ... Keep the sisters behind the controlled character
... When the positioning and timing are correct -- close enough for
`RearAttack` to connect, but far enough to avoid being hit -- execute
`RearAttack` ... Optimize the entire encounter for: 1. Minimum elapsed combat
time. 2. Minimum damage received. 3. Reliable and repeatable execution";
"Do not call the police. Do not use recovery items ... must not be used as
fallback strategies"; and on testing: "take care with the game running
speed, the AI pooling speed, and the 'emulated' game frame pacing!", "use
turbo 2x at max, this PC can't handle turbo 4x at full speed"). The model is
`ai/twins.py`, the plan `ai/twins_plan.py`, the verb `EngageTwins`. Before
it the generic verbs lost the whole game in 74 s (three lives, one twin at
17 of 32).

What the ROM says (`ai-analysis/enemy-ai.md`, "Onihime and Yasha", rewritten
for this -- the earlier decode had the approach twin's jump and the grab
twin's "leap" backwards):

- **Two AIs.** The twin that links second (role 2) starts on the grab path
  (`+$7B` bit 1), the other on the approach path; they spawn on either side
  of the arena (grab twin at `cam+52`, approach twin at `cam+412`,
  off-screen).
- **The approach twin never walks into anyone.** Its chase (4 px an update)
  keeps the lane gap at the edge of 32 -- toward the target's lane from 32
  out, *away* inside it -- and inside 96 px it **backflips away** (84 px;
  `$15ABA` sets `+$1C` with `$17942`, the negation of `$1792C`). Its box in
  state 1 is cancelled on contact. Its one attack is the **flying kick**:
  committed 16-31 lanes off inside 112 px, 28 updates of flight at 2.667 px,
  1/16 of the lane gap an update (it crosses the launch lane on update 16 and
  goes on to 1.75x), the kick box from update 19, low enough to land from 23.
- **The grab twin walks into a turned back** at 2 px an update, homing the
  lane; its walking box on the body is the grab (the throw is 32). It jumps
  in only at a target that *faces* it, and backflips away from a staggered
  one.
- **The rear attack** (update by update: `ai-analysis/controls-and-input.md`,
  "The chord update by update"): Blaze's box 3-10 updates after the press,
  5-53 px behind, 64..24 up, 2 damage; Axel's 1-5, 8-40 px, 72..40 up, 3;
  Adam's is a hop -- box 10-18 updates after the press, 42 px behind to 14 in
  front, 3. Every live frame knocks down: **90 px and 39 updates** on the
  floor, applied on the twin's next update. The strike is tested before the
  twin's box. Blaze's body box moves *behind* her during the chord.
- The twins are Blaze's sprites and use the player shape table (`$1ABA8`);
  a backflip and a jump-in have no body box at all.

The model (`ai/twins.py`: both twins' states 1/2/3/5 and the renderer tail,
the actor walking and chording, `$AAA0`'s contact order) was checked field
by field against lockstep recordings with `tools/twins_lab.py --check`:
2,744 (Blaze, the plan), 2,494 (Axel), 1,912 (Adam) and 3,941 (a wander)
twin updates, no field off outside the held throw, a respawn's knock-back
(`$9494` sets `$FFFA53`) and a dead twin's frame timer, none of which the
plan needs. The actor's side was checked the same way (positions, cached
boxes, damage, the chord's frames, Adam's hop height for height).

The plan (`twins_plan.plan`, every tick):

1. **The edge and the back.** `choose_wall` makes home the camera edge on
   the side away from the grab twin, and the actor faces that wall: the
   grab twin is never given its jump-in. Standing is preferred to walking
   into the wall (Blaze's idle body sits 7 px further from a twin behind her
   than her walking one).
2. **The approach twin by the lane.** While the grab twin is coming, the
   tail holds the approach twin's lane (gap under 10), which denies its kick;
   with the grab twin down or far, it is let commit, and the kick is met by
   the rear attack on its way down or stepped off by the lane (`kick_threats`
   reads its ballistic path). The lane band's edges are kept free (24 lanes)
   for the step.
3. **The rear attack on the update it lands.** The lookahead plays a
   handful of programs -- the tail from now (first, so it wins ties), the
   chord now, a stick held 1/5/12 updates, a chord after 2/4/6 -- through
   both twins' own AI for 30 updates (40 while a kick is in the air), and
   scores each by its worst of five timings (below): a hit or grab below
   everything, a strike by how soon, a chord that lands on nothing -300.
4. **Continuity** (`PlanMemory`): the last tick's program, advanced a tick,
   is scored again with +150. Without it a receding horizon picked a
   different near-tie every tick and walked a trajectory none of them had
   predicted -- an intercept that lost a tick three times over. A chord still
   to come is never carried (a tick is not exactly an update: a kept "chord
   in 4" fired three ticks later as a whiff into a flying kick).
5. **A kick in the air belongs to the tail.** While one is flying, the
   programs are only the tail and the chord (now or after 2/4/6, standing):
   a held stick that steps toward the kick's path "for now" was chosen again
   every tick and the step off never came.
6. **No rear attack that can miss** (user, watching a live fight: "Vi que a
   IA dá vários `BackAttack` em falso, não quero que dê ataques em falso").
   A program whose first update presses B+C -- the chord now, or the tail
   pressing it -- is kept only if the rollout shows that press striking a
   twin under every one of the five timings; otherwise it is dropped, not
   scored down (with nothing left, the actor stands). The -300 a whiff cost
   was not enough: a chord pressed at a grab twin still 92 px out (Blaze's
   box ends at 53) missed under every timing and still won, because the
   tail's next chord struck one update sooner than waiting did
   (`test_a_chord_that_can_miss_is_never_pressed`). Offline, with the rule
   switched off, 9 of 38 chords whiffed in one start; with it, none in 390
   (below). `tools/boss_fight.py` counts `chords` and `chord_whiffs` live: a
   start of the chord action with no twin losing health before the next.

**Frame pacing** (user, above). Measured on the development machine: the
host ran 120 fps at `--turbo 4` *and* at `--turbo 2`, a snapshot takes ~2.2
ms, and a tick with the plan ~20 ms -- about one player update a tick at 2x.
So the stick a tick writes lands on the next player update or the one after,
with either the player's or the objects' update next (`$AD8E` alternates
them), and a late tick holds the last stick an update longer. The plan
scores every program under all five (`SCENARIOS`), the held stick playing
the lead (`committed`). The offline simulator
(`tools/twins_sim.py`) plays the same: a tick about every update, one in
four half an update or a whole one late, and the stick landing 0-1 updates
late. The scripts now run `--turbo 2 --poll-ms 16` (both_turbo, go_to_boss).

Measured, round 5, Normal, police and food off:

| | Blaze | Axel | Adam |
| --- | --- | --- | --- |
| before (generic verbs), real time | game over in 74 s, one twin at 17 | -- | -- |
| lockstep lab, `--actor engage` | 46.2 s, no damage, 32 strikes from 33 chords | 47.4 s, no damage | 32.1 s, no damage, 22 strikes from 26 chords |
| real time 2x, first batches (15 fights) | 5 of 5 without damage, 46.6-70.4 s | 3 of 5 (a flying kick in each other) | 3 of 5 (the two bugs below) |
| real time 2x, final code | 46.6 s, no damage | 44.6 s, no damage | 32.6 s, no damage |
| offline, 36 starts, harsh timing | 34-35 of 36 clean, ~47-50 s | 33 of 36, ~49-55 s | 33 of 36, ~36 s |

The offline figure plays the worst of the timing: half its ticks' sticks land
an update late and a quarter of its ticks come late; with the lab's exact
timing (`--lockstep`) the same planner is clean in 12 of 12 (Blaze, Axel) and
11 of 12 (Adam). Every remaining offline miss is a flying kick.

With the no-whiff rule (6, above), offline: lockstep timing, Blaze 4 of 4
and Adam 4 of 4 clean, **no whiff in 118 and 84 chords**; harsh timing, six
starts each, Blaze, Axel and Adam 5 of 6 clean (47.9, 50.3 and 37.4 s),
**no whiff in 156, 121 and 113 chords**. Live, real time at 2x (Blaze,
armed -- the chord is `$4A`): both twins killed, no damage, **29 rear
attacks and not one whiff**, 27 s of wall clock (~54 s of game time).

The floor this strategy has: a knockdown throws a twin 90 px and keeps it 39
updates, and it comes back to the distance it was met at, so each twin's
cycle is ~85 updates whatever the actor does at the edge; Blaze needs 16
strikes a twin (2 damage), Axel and Adam 11 (3). Both twins struck every
cycle is ~45 s for Blaze and ~31 s for Axel and Adam -- Blaze and Adam fight
at it. Axel loses time to the approach twin: his box (8-40 px, 72..40 up)
cannot meet a kick launched from the chase before it lands (it reaches from
49 px on the update his box can first reach 45), so it is stepped off and
the approach twin is struck less often while the grab twin lives.

What the live runs taught, each found in a trace:

- **Adam's rear attack is a hop**, so he reads as airborne: the generic
  airborne jump-kick follow-through pressed B at the twins through 135 ticks
  of his chords. `could_jump_attack` now skips the chord actions and the
  twins.
- **Armed, his chord is `$4C` -> `$4E` -> `$40`** (the action table gives
  them the same animations): the model knew only `$4C` and read him free in
  the hop. `twins.chord_step_from` maps all six.
- **The hop lifts his body into a kick's higher path**: the tail's "a kick
  lands during my chord" test only counted the kick's low updates; for a
  hopping chord it counts its whole box-out path now.
- **A corner is a trap**: a dodge into the band's edge came back up into the
  kick as a late tick held the stick an extra update. The fifth timing
  (`SCENARIOS`: the first decision held one update longer) and a softer
  corner term fixed it (Axel offline 19 of 36 clean -> 27, then 33 with the
  kick-in-the-air rule).

Wiring: `could_engage_twins` offers one `EngageTwins` while any twin lives
(armed or not: the armed chord `$4A` is the same move); Punch/weapon swing,
`RearAttack`, `GrabEnemy`, `WalkToNearEnemy`, `RetreatFromDanger` and the
jump (grounded and airborne -- Adam's chord is a hop, and the airborne
follow-through pressed at the twins through 135 ticks of it) stand down for
them; `CallPolice`, food, 1UPs and the weapon detour are refused while they
live. `EngageTwins` ranks 62 plus the boss raise.

Not built: two players (the twins' target is taken to be the actor), the
round-8 boss rush's pair, and a start with the approach twin *in front*
(between the actor and the wall) is only waited out: its kicks are stepped
off until it crosses over.

**First-level breakables (user):** Round-1 phone booths (`$11`) and the
type-`$19` family share the shallowest ROM solid (14px on lane vs a 16px
body, walkable in front of the feet). The 1px conversion of that rule
overlaps a body standing legally just in front -- that is a graze, not
"already inside". The path finder may only ignore an obstacle whose
interior contains the body's centre. Dropping any overlapping wall made
the actor lose the booth, hold UP into the real solid, and freeze.

The *first* thing the AI meets on round 1 is not a smashable object. The
yellow sidewalk trash can at the first wave gate is background art (never
in the object table). The actor stops at world x=1504 because `$43AA`
clamps the player to `camera_x+$20..+$120` until the wave clears;
`WalkToAdvanceStage` used to keep holding RIGHT into that edge. The first
real breakable is a type-`$11` booth at (2016, 32). Never hold into the
camera walk clamp. `in_smash_range` must use the punch box's own ±8 lane
extent -- 16 fired B from a corner the box cannot reach, so the booth
never broke.

**Frozen on the edge of the lane band (user):** "in round 1 the AI stops
in the middle of the level, no enemies, and will not walk on until I touch
the pad". Traced at round 1's third wave gate (camera `$0AC0`, the player
clamped at x=3036): the actor follows a type-`$26` that enters at y=0 up to
`LANE_Y_MIN`, the sweep kills it, the camera scrolls on -- and
`WalkToAdvanceStage` held `0x0` on every tick. 5 traced walks of 6 froze
there for the 25 s the trace allowed; scored runs lost a life to the round
clock. The lane band bounds the *origin* (`$43AA`), but `pathfind` keeps
the whole *body* inside `world_rect`, so a body reaching 8 px past an
origin on either edge of the band started outside the world and the search
could not take one step (`steps=()`, `reached=False`).
`world_rect(body=, origin=)` now restates the band for the body, the
conversion `partner_obstacles` and `strike_goal` already make. After it,
the 3 traced walks of 6 that reached y=2-3 (115-205 ticks there) never got
an empty route and all walked on. Two executor tests that expected a
diagonal had encoded the bug: their goal, at y=0, lay outside the old world.
The wait *before* that gate opens is the ROM, not the AI: the player is
held at `camera_x+$120` until the wave's six spawns -- swept, so never on
screen -- are dead, about 5-7 s at turbo 4.

**Swinging a bat over a booth from too close (user, same report):** the
other cause of "stops in the middle of round 1". Blaze's `OpenBreakable` B
landed on the bat at her feet (`$3136` picks an item up instead of
striking), swapping out her pipe, and she then swung 93 times in 25 s from
x=2903 at the type-`$11` booth at 2920 without touching it; a scored run
stalled on the same spot and lost a life to the round clock. The swing
(`$48`) only connects near its peak: the held weapon's origin runs from
w_x-p_x = 6 out to 53 for Blaze (36 for Axel, weapons-range-and-damage.md
§5), and its box reaches about 18 px back from there. The booth (box ±16)
broke from 19 px, and from 27-36 px in every other walk, but never from
17 px -- yet `in_smash_range` used the punch's inner edge (12 px for Blaze).
`decide.breakable_strike_inner_x` is now the swing's inner edge (peak - 18
- the prop's box past its origin; the punch's own with no bat or pipe),
shared by `in_smash_range`, the approach's `inner_dx` and the facing
nudge's headroom. After it, 6 traced walks of 6 broke every booth with
swings from 22-35 px, the bat included. The same peak puts a ±6 px enemy
under Blaze's swing closer than ~29 px, and `MeleeWeaponAttack` now uses the
swing's band too (**Seven fixes: weapons, the floor, Jack, Mr. X, the camera
and no whiffs**, below).

**Target ranking (user):** `WalkToAdvanceStage` always has the lowest
emergency of any verb that still scores. Among enemy targets, a `Boss`
outranks an armed ordinary enemy, and an armed ordinary enemy (pickup
`$08-$0C`, or Jack still juggling his axe) outranks every other grunt --
except that a juggling Jack now waits while a nearer grunt able to act is in
the fight's box (user, later: "A IA dá muita prioridade ao EngageJack, mesmo
quando tem muitos mais outros inimigos mais iminentes que o Jack"; see the
**Seven fixes** section).

**Being surrounded (user):** a crowd is answered by *taking a hold*, not by
trading strikes with it and **not by backing away** -- `_retreat_is_worth_it`
is now gated on health alone; being surrounded used to be a second reason to
retreat ("the only fix is space") and that clause is gone. `Surrounded` is
judged with `reach.SURROUNDED_NEAR_X`/`_Y` (96 x 32), *not* the chord's
`REAR_THREAT_X`/`_Y` (56 x 24) it used to share: the tight box collapsed after
about a dozen px of the actor's own walking, which killed the grab mid-walk-in
and is why the first attempt at this had no visible effect. A committed charge
coming in from *behind* a grabbable body -- the user's "an enemy in front, and
behind it, a Signal" -- is `reach.grab_reasons`' `DODGE_CHARGE`; Signal's slide is velocity
with no attack shape (enemy-ai.md), so there is nothing to sidestep, and the
answer is to hold the body in front and suplex it. Otherwise, a crowd is
answered by trading strikes with it — grab an enemy and suplex or throw it. The throw is
especially good when the thrown body hits other enemies. So the
`WHILE_SURROUNDED` grab reason outranks the `$322A` escape chord
(`_EMERGENCY_GRAB_WHILE_SURROUNDED` 61 vs `_EMERGENCY_REAR_ATTACK_DANGEROUS`
60), which reverses an earlier assumption that a committed enemy behind was
"not something to turn your back on": in that exact pincer,
`could_hold_actions` answers with `ThrowHeldEnemy` (B+back), which throws the
held enemy backwards into the very enemy the chord was aimed at. The hold
*chain itself* already did the right thing before this — front hold `$60`
with a rear threat → `ThrowHeldEnemy` (70), without one → `FlipHold` (66) →
back hold `$66` → `Supplex` (68) — the missing piece was only ever taking the
hold in the first place.

**Cluster inference for JumpAttack/Supplex/ThrowHeldEnemy (user: "quero que
a IA saiba inferir clusters de inimigos que estão perto uns dos outros e
podem ser atacados com ataques como JumpAttack, Supplex ... e
ThrowHeldEnemy"):** the paragraph above already banked on "the throw is
especially good when the thrown body hits other enemies" as a fixed
constant (`_EMERGENCY_HOLD_THROW` 70, `_EMERGENCY_HOLD_SUPPLEX` 68) with
nothing actually reading whether a cluster was there. `JumpAttack` was the
one move with a real answer already: `jump_kick.enemies_hit` sweeps its
*actual* flight box against every on-screen enemy (**The jump kick,
measured**, above), and `priority._jump_attack_extra_hits_bonus` scores +2
per extra body it lands on, up to +4 -- so `could_jump_attack`'s one verb
per in-band target already ranks a kick into a cluster above an otherwise
identical kick at a lone target. `Supplex` and `ThrowHeldEnemy` had no
equivalent: neither move's landing spot is modelled the way the kick's
flight is (that would need the same per-boss/per-character ROM decode and
lab work the jump kick, Bongo's flame, etc. each took), so
`reach.nearby_enemies` is a deliberately shallower proximity estimate
instead -- other live enemies within `Surrounded`'s own "part of this
fight" box (`SURROUNDED_NEAR_X`/`_Y`, 96 x 32), centred on the *held body*
rather than the actor. `priority._hold_cluster_bonus` counts them (capped
at 2, `_EMERGENCY_HOLD_CLUSTER_EXTRA_HIT` x2 = up to +4, the same shape as
the kick's bonus) and `_held_enemy_emergency`'s new `cluster_bonus` flag
adds it only for `ThrowHeldEnemy`/`Supplex` -- not `FlipHold`,
`AttackHeldEnemy`, `ReleaseGrab` or `ReleaseToRegrab`, none of which send
the body anywhere near anyone. The ROM fact behind counting it at all is
`$FFFB24`, already decoded for Mr. X's Garcias ("Thrown bodies knock
Garcias and Mr. X down") and generic to any thrown/slammed body, not just
his office. Since decide.py's own branches never offer `Supplex` and
`ThrowHeldEnemy` for the same held body on the same tick (back hold vs.
front hold, or Bongo's/Mr. X's mutually exclusive `step` chains), the bonus
can only ever raise the one move already chosen -- it does not change
which finisher `souther.hold_step`/`abadede.hold_step`/`mr_x_plan.
garcia_hold_step` pick, only how urgently the winning one outranks
everything else on the board. Covered by `tests/ai/test_reach.py`'s
`NearbyEnemiesTests` and `tests/ai/test_priority.py`'s cluster-bonus cases
under `DetermineEmergencyWinnerTests`.

**...as an `Inferred` token (user: "Eu queria um token Inferred"):** the
cluster judgment above shipped as a private `priority._hold_cluster_bonus`
calling `reach.nearby_enemies` directly -- exactly the shape every other
`reach.py` judgment in this project takes, per **Judging without a
cache**'s own rule. The user wanted it as a token instead, so it is now
`EnemyCluster` (`tokens/enemy.py`, next to `Surrounded`), produced by
`inference.check_for_clusters` and unioned into the context by
`generate_inference_tokens` the same way `Surrounded` is; `priority.
_hold_cluster_bonus` reads `find(context, EnemyCluster, slot=held_slot)`
rather than rescanning enemies itself. `reach.nearby_enemies` did not go
away -- it is still the one shared geometry `check_for_clusters` calls
once per on-screen enemy to build the token, the same relationship
`check_for_surrounded` has with `reach.SURROUNDED_NEAR_X`/`_Y`. `AI.md`'s
**Judging without a cache** section now documents `EnemyCluster` as the
second (and only other) exception, with its own reasoning: several
call sites a tick and a same-cost-class scan as `Surrounded`'s, per that
section's own bar for keeping a token rather than a bare function. A test
(`test_priority.py`'s `test_no_bonus_without_running_inference_first`)
pins the one behaviour change this caused: a context that skips
`generate_inference_tokens`
before scoring now scores the bare tier, since the token, not a live
recomputation, is what the bonus reads -- true of every other `Inferred`
consumer already (`Surrounded`), never true of the ordinary `reach.py`
functions this rule is otherwise an exception to.

**Stage-4 pits (user):** The AI walked/jumped into a pit on the bridge
(round 4). `JumpAttack` was blind to holes -- a kick toward an enemy
across a gap flew in -- and `execute_tick`'s pit override then froze X
mid-air (`pit_endangers` is lane-plane, so overlapping the hole in X/Y
looked like "already in"). `WalkToAdvanceStage`'s `or RIGHT` fallback
did the same when the pathfinder could not walk around a full-width
gap. The pathfinder is now the authority: `navigation.jump_landing_is_safe`
gates grounded launches (walk around if a 2D route exists; hop over only
if the landing is solid and no walk reaches); `WalkToAdvanceStage` hops
via `hop_landing_x` when `plan_route` fails and the far side is in kick
range, otherwise stalls at the wall; the pit override does not run
while airborne.

**Stage-4 breakable (user: "Vi a IA a ficar presa num breakable desse stage e
a não conseguir progredir!"):** reproduced in both swept walks of round 4
(`tools/breakable_diag.py --level 4 --sweep`, Blaze and Axel): 61 s at x=1617
beside a type-`$1B` prop at (1656, 96), facing away, `OpenBreakable` winning
7000 ticks, until the round clock took a life. Round-4 props take `$3C6A`'s
default record, so the wall runs x 1620..1692 over lanes 76..100 -- 28 px
nearer than the sprite box -- and the facing nudge's 16 px toward-step sat
inside it. Routed around that wall the nudge went UP (lane 80 -> 78, out of
the punch's lane), the approach came back DOWN, and so on. The nudge's route
now leaves the target prop out of its own obstacle set: a step into the
prop's wall is exactly what turns the actor (`$3BAE` undoes the displacement
and keeps the facing), and the next tick punches. After it the same swept
walk reached Bongo in 55 s with no life lost (115 s and one or two lives
before). `tests/ai/test_execute.py`'s `_walk` now undoes a step into a prop's
wall the way `$3BAE` does -- the facing kept -- which is what a trail
through that nudge has to look like.

**Mr. X: the ROM model and the plan** (user: "Agora fazer o mesmo tipo de
optimização, mas para o boss Mr. X (o último nível). A estratégia das Twins já
não serve, é claro. O Mr X está no fim do último nível, um nível bastante
longo, com muitos inimigos e muitos bosses, é melhor haver uma flag para
automaticamente eliminar todos os inimigos e bosses que aparecem até o Mr X
estar no ar. No combate com o Mr X, tem vários Glasia que aparecem para o
ajudar, ter em atenção para essa flag não automaticamente matar esses
ajudantes nem o Mr X"; then "The AI seems to fight mr x better than the
garcias..."; and, closing the session, "a performance da luta é
suficientemente boa por hoje"). The twins' goals and rules carry over:
minimum time, minimum damage, reliability; no police and no recovery items,
not even as a fallback; no attack that can miss. The model is `ai/mr_x.py`
and `ai/garcia.py` (the user's "Glasia" are the office's type-`$22` Garcias),
the plan `ai/mr_x_plan.py`, the verb `EngageMrX`.

The flag: `--kill-until-mr-x` (`DebugScenario(kill_until_mr_x=True)`, the
host's `Alt/Option+X`, `StreetsOfRage.cpp`'s `killEnemiesUntilMrX`) kills every
ordinary enemy and every boss of the rush -- Abadede through his police latch,
`$55`-`$58` through their lethal path -- and returns without touching anything
once a type `$33`-`$35` object exists; the scenario stops sending it for good
once the offer flag (`$FFDE00`) or Mr. X has been seen (`note_snapshot`).
`scripts/go_to_boss_8` passes it with `--no-food`.

What the ROM says (`ai-analysis/enemy-ai.md`, "Mr. X, state by state" and
"The office's helpers"):

- **Him**: the bespoke-boss frame, 30 Hz. Decide (3): under `$80` on X he
  walks in (6: 8 px an update on the far axes) and lunges (2: a 52 px dash,
  box 64 px ahead and only 8 lanes either side, 34 on Normal); from further
  he goes to the gun (7: up to lane 2.5, a 21-update wait, eight bullets --
  20 each -- and **no box of his own out**). The retreat's first update (5,
  substate 0) tests contact where he stands, before he moves.
- **His hold** (`$A`): he reads the holder's `+$7D` on substate 1 only; a knee
  there is 2 and 10 updates of shake, a release sends him to the retreat,
  whose first update is the re-grab. Knee, knee, release: 4 points about
  every 30 updates, and he never acts. 40 updates in substate 1 without a
  move free him (`$13598`). A body thrown into him while held knocks him
  down out of the hold.
- **The Garcias**: two with him, replaced as they die; 9 health, 8 a hit. They
  walk at a point 32 px short of the target at 4.5 px an update (faster than
  any player), jab when box `$12` (0-40 ahead) meets the target's cached body,
  and their punch has four live stages -- once caught inside it, a player
  takes two to four in a row. **Off screen the punch is refused** (`$92AC`),
  which makes the camera's right clamp a pocket: a Garcia coming from the
  right aims at screen X `$1C0` and turns to `$DBCC` instead. Thrown bodies
  (`$FFFB24`) knock Garcias and Mr. X down.
- **The player's blink**: after getting up from a knockdown and on a respawn,
  48 updates with no body (`$4F62`, `+$4B` bit 1, `+$49`): nothing lands, and
  no Garcia's jab triggers on it.

The plan (`mr_x_plan.plan`, every tick; `hold_step`, `garcia_hold_step`):

1. **A lookahead over him, every bullet and every Garcia**: the nine sticks
   held 1/3/6/12 updates then a tail, a punch on update 0-5 (standing or
   walking toward a target first -- the walk is the turn), the rear attack on
   update 0-5, each under the twins' five timings and scored by the worst
   (the mean in the re-grab window). A punch or rear attack pressed now must
   strike under every timing. A hold on him is scored by what lands on the
   holder standing there (`holder_blow`): a blow before a knee and the release
   after it are spent (`HOLD_KNEE_SAFE_UPDATES`, 18) makes it a burnt grab, one
   before the release could free the actor a hit; a hold on a Garcia by what
   lands through a knee and a release, his lunge included.
2. **The tail**: in his decision, stand `$80`+16 away so he goes to the gun
   -- on the right clamp when he is that far to its left, facing the wall, so
   the Garcias that can strike all come into the rear attack; walk into the
   gun and into the retreat's first update; 17 lanes off the lunge; the
   street's edges avoided (a Garcia corners an actor there). Before he
   appears (the office's first waves, `MrXOffice`): home, facing the wall --
   played by `FightMrXOffice`, the same plan with no Mr. X in it; `EngageMrX`
   only ever names a live Mr. X (user: "A IA emite EngageMrX, mesmo quando o
   Mr. X não está no contexto").
3. **The hold**: knee, knee, release on his read (`hold_step`); a Garcia whose
   blow reaches the holder before `HOLD_KNEE_SAFE_UPDATES` (`garcia_threat`,
   played through `garcia.py`) gets the hold let go at once -- never the
   throw: it locks the holder 41-46 frames, and his flight hops 48 px at its
   apex, over a Garcia close behind. A Garcia in hand while he lives is thrown
   only when nothing lands through the throw's lock, else kneed if a knee
   fits, else let go (`garcia_hold_step`).
4. **Ownership**: every generic verb stands down for him and his Garcias; his
   bullets are the engage's; police, food, 1UPs and weapons are refused while
   he lives, and weapons from the offer on (armed, B is a swing the plan does
   not time, and the punch is gone).

The model was checked in lockstep (`tools/mr_x_lab.py --check`): every one of
his updates in two runs outside the states it does not replay, every bullet
step, grab and hit; the Garcias 3,488 updates, three off. Offline
(`tools/mr_x_sim.py`, 30 shifted starts from a wander recording, harsh
timing): 23 holds, one real hit; the other six end in a Garcia held on the
way, which the sim does not play on.

Live, round 8, Blaze, `--turbo 2`, `--poll-ms 16`, police and food off, one
fight each (so a direction, not a score -- the Garcias' `$DBCC` legs are
random and the office's first waves set the health he is fought on):

| | office waves (HP) | Mr. X killed in | hits in his fight | lives lost |
| --- | --- | --- | --- | --- |
| the plan without the Garcias | -- | 25.8 s | three of his lunges (34) after generic punches at Garcias | 2 |
| + the Garcias in the lookahead | 61 → 45 | 14.7 s, 14 holds | 5, all Garcias (40) | 0 |
| + burnt grabs, a held Garcia thrown at once | 65 → 65 | 28.8 s | 8, three of them his lunge during a Garcia throw | 1 |
| + the throw only when nothing lands, no weapon in the office | 65 → 41 | 33.5 s | 19 | 3 |
| + the blink, home on the right clamp, the rear attack | 65 → 41 | 24.1 s, 21 holds | 8, 8 rear attacks and no whiff | 1 |

What the runs taught, each found in a trace (`boss_fight.py`'s raw rows
through `mr_x_sim.py --replay`):

- **The rollout stopped at the grab**, so a hold a Garcia walked in on scored
  as a hold: the burnt grab.
- **The hold let go too late**: a jab 9 updates away left no time to be free
  and strike first; the threat horizon is now a knee, the release and a step.
- **Throwing a held Garcia with him walking in was his lunge**, three times in
  one fight: the throw is taken only when nothing lands through its lock.
- **A pipe picked up in the office's first waves** switched the punch off
  for the whole fight; weapons are refused there now.
- **The blink**: the plan rebuilt a body on the first update of every
  rollout, so it saw a Garcia jab at a blinking actor on the wrong update and
  walked away -- into the jab when the blink ended.
- **Most hits are pincers**: both Garcias arriving from opposite sides at
  once, after a release in the middle of the room or at the street's top or
  bottom edge, where nothing any program does avoids the jab. That is what
  the right-clamp home is for.

Still open, measured on: the pincer after a release away from the clamp (a
release is taken where he stands); the knockdowns of the Garcias are held
still in the model rather than played (flight, floor, getting up), and a
dead Garcia's replacement is not modelled; a whole-fight offline simulator
(hold loop, hit reactions, respawns) was started from `$1353A`'s decode and
not finished; Axel and Adam have not been run live against him.

**Round 8's thrown tables** (user: "No nível 8, de vez em quando o jogo
atira umas mesas contra o jogador, a IA deve detetar se estão em linha com
ela, e se for o caso, fugir delas, ou se for estiver demasiado perto,
dar-lhes um murro para que elas não atinjam a IA"; confirmed right at the
level's start: "as mesas são atiradas logo de início"; and, on the ROM
family: "as mesas do nível 8 também são um 'breakable'" -- true of its
*idle* state only, below). Full decode in `ai-analysis/enemy-ai.md`, "Round
8's thrown office table (`$45`)".

`object_type_update_jt` (`$B236`) confirms type `$45` is one real object,
dispatched at `$7534 (round8_table_dispatcher)` through a 3-entry
per-`+$30`-state table: **state 0** (`$7546
(round8_table_state0_wait_and_arm)`) sits hidden at its spawn point until a
camera-relative proximity threshold trips, then arms -- an X velocity from a
per-variant (`+$40`) table at `$75DC` (variants 1-4 measured `+5`, `+6`,
`-5`, `-6` px/tick; variant 0 never arms and never flies, so not every `$45`
is a real throw) and a lane (`+$14`) copied from whichever player is the
current target *at that instant* (a straight shot down that lane, not a
homer). **State 1** (`$75E6 (round8_table_state1_flight)`) integrates
velocity and runs a hit-check shared with other props (`sub_00007392`) that
explicitly special-cases type `$45` for a stronger vertical recoil when
punched -- the ROM's own "punch it away" mechanic, found in the
disassembly independent of any live run. **State 2** (`$75EE
(round8_table_state2_bounce)`) is the gravity arc, rise then fall, on its
own after launch or after a punch. Live-captured (`autoplay/tools/table_
throw_diag.py`, new, `hakuro_emerge_diag.py`'s shape, `DebugScenario(start_
level=8)`, no sweep needed -- the very first live sample already had an
armed table): ~5-6 world px/tick, lane-locked to the player at arm time, a
168->117->166 `z` arc. Reproduced the report exactly: `p1_hp` 80 -> 77 with
no answer for it, because `object_catalog.py` tagged every `$45` a
`Breakable` regardless of state -- invisible to `reach.projectile_
threatens`/`ProjectileSidestep` for its whole flight, and for the one tick
its state read 1, misread as an *intact* one (`_INTACT_BREAKABLE_STATE`'s
same numeric value, unrelated reason).

Fixed: `object_catalog.TABLE_TYPE_ID`/`style_for_object` now classify `$45`
by its own `+$30` -- `None` at state 0 (unchanged), a `"projectile"`-kind
`EntityStyle` at any other state -- and `world_map.py` gives it the same
`+$1C`/`+$20` ordinary-layout velocity correction Jack's axe already needed
(the projectile-kind default `+$20`/`+$24` reads a straight throw's real
speed as 0). `reach.table_in_punch_band` mirrors `decide._boomerang_in_
punch_band`; `HitTable` (`ai/tokens/attack_verbs.py`, wired through
`decide.py`/`priority.py`/`execute.py`/`kinematics.py`/`ai/partner.py`) is
`HitAntonioBoomerang`'s exact shape with no attach-phase filter -- the
table has none, it is already in real flight by the time it is observed at
all. `ProjectileSidestep` needed no changes: once `$45` is a real
`Projectile` with a real `vel_x`, its existing `reach.projectile_threatens`
gate already covers the flee half. A second live run against the fixed AI
produced 36 `ProjectileSidestep`s and 13 `HitTable`s with no hit
attributable to an armed, in-lane table.

**Jack: the ROM model and the plan** (user: "A AI tem sérias dificuldades em
lidar com o inimigo do tipo Jack ... É essencial construir uma estratégia para
lidar com este inimigo ... O objetivo é lidar com este inimigo de forma
eficiente, no menor tempo possível, com o menor dano sofrido. A IA deve lidar
com todos os ataques, estados, etc. que este inimigo pode ter"; "o inimigo não
aparece no Stage 1"). Everything the AI does against him is `ai/jack.py`, and
the plan is the bosses' shape: **take the hold from where no axe of his
reaches, keep it until his axes are gone, then spend it.** The earlier rules
(grab him from behind through `GrabReason.JACK_FROM_BEHIND`, the rear chord
when he faces the actor, the armed swing and the jump kick at him, no unarmed
punch while he juggled) are gone: they were written without the ROM model,
and they took 13 of his hits in the baseline below.

What the ROM says (full decode in `ai-analysis/enemy-ai.md`, "Jack"):

- **His body never strikes.** No animation of his carries a strike box and no
  state tests one: every hit is a type-`$28` axe. His extracted "reach" was a
  thrown-body box (`attack_ranges.CONFIRMED_TYPE_SHAPES[0x27]` is now empty)
  and his `$08`-`$0A` were read as a lunge; `phases.py` reads all his states
  NORMAL but the knockdown.
- **The juggle**: two axes, 8 updates apart, riding 8 lanes below him and
  8-24 px in front, each arc pinned to absolute z 128 (apex 96, 15 updates,
  then 4 px an update back to his hand; ~20 a cycle). On a floor at 160 (round
  2) the box meets a standing body only near the bottom of the arc and on the
  way back. An arc that *ends* with his pose off the juggle stance drops the
  axe; the walk back to his hand never looks, and restarts a whole arc.
- **The throws**: waiting 64 px over his head, then 10 px an update from 32 px
  in front of him along his lane - 1, at head height. `$0E` throws three, 12
  updates apart (the actor within 64 px on X aborts it into `$07`); `$0B`
  throws both juggled axes after `$0A`'s diagonal back-off onto the actor's
  lane.
- **Personalities**: `+$40`'s low nibble picks the state every reset lands in
  (`$F2DE`): 0 juggle approach + aligned throw (rounds 2, 4, 6, 8), 1 retreat +
  ranged throw (6, 8), 2 jumps (5), 3 juggle walk (5).
- **`$07` faces the target every update** (`$9E4C`): there is no "behind him"
  there -- walk past him and he turns, and the next arcs start on the actor's
  side. `$DBCC` takes him to lane `$58`/`$18` away from the target's half
  (round 4 always up, round 6 always down), then walks legs of 2.5-5 px an
  update toward and past the target and resets only 80 px beyond it -- and a
  reset off screen fails `$0C`'s entry test and lands straight back in `$07`.
  The level's X bound (`$9F96`: below `$1510`) refuses the step and does
  nothing else, so a Jack walking into it waits there until the target is 80
  px behind him.
- **The hold**: he is placed 32 px in front of the holder (28 from behind) and
  his flying axes follow him, so a *front* hold on a juggling Jack is itself a
  hit, and a back hold keeps them on the far side. The grab only writes his
  state -- `$A04A` places and poses him on his next update -- so an arc ending
  on the grab's own pass walks back through a front holder. No escape from a
  hold; knees 2, 2, 3, suplex 5, throw 4; **only a negative health word
  kills** (0 is alive). The third knee and the crossover's suplex land him the
  way the front holder faced, the B+back throw behind it.
- **A dropped axe still hurts**: `$FED6` (an arc cut short when his pose
  leaves the juggle stance, a toss he does not catch) only moves it and drops
  it at 1.125 an update to the floor, but its box stays in the player's hit
  test and keeps its damage; only a strike's knocked-off copy carries none.

The plan (`jack.plan_engage`, `EngageJack`, `execute.state_machine_engage_jack`,
`jack.hold_step`):

1. **A lookahead over him and every axe on screen** (`world_update`: his
   states `$01`-`$12` with their approach points, gates and re-facings, the
   juggle, the toss, the throws and their release frames), the nine sticks
   held 2 updates then a tail policy, or held all 16, each under both update
   orders and scored by the worse: a hold by how soon -- unless
   `hold_is_burnt` (the axes still up, played over the hold's first 22
   updates with the one-update pose lag) says an axe meets the holder, which
   scores as the hit it is; a hit below everything else; the rest by the time
   to `engage_aim`'s point and whether the end sits in a live juggle's band or
   a throw's lane. 2.4 ms a tick with one Jack, 9 with eight. **The punch**
   (when `abadede_can_punch`): thirteen more candidates stand, or walk toward
   him -- the walk is the turn: B with a turn on one press is sampled
   pre-turn, a committed miss -- and punch on update 0-6; a strike (`$9B88`: 1 damage, 24 updates of stun, his
   juggle off so its axes drop, a 2 px push) scores under a hold and over the
   rest, and the rollout plays on from it -- an axe on the locked actor still
   counts; at 0 health it kills. No second punch while the stun has more than
   8 updates to run (`REPUNCH_T50`). The round (`Stage.level_index`) goes in
   as `level`: his `$07` lane direction and X bound depend on it.
2. **The aim** (`engage_aim`): out of a throw's lane band first; out of the
   juggle's band by the nearer lane (9+ above his lane, 25+ below); past him on
   that side; back to his lane only 16+ px behind his origin, and into his
   back. In `$07`: mid-screen (`EVADE_CENTRE`, so his reset lands on screen),
   `POCKET_DY` (13) lanes above him -- out of the juggle, in the punch's reach;
   only from above his band, from below the actor waits below it -- with no
   tie-break drift toward him; out of reach and pinned at the level's bound,
   88 px behind his walk, where `$DBCC` resets him at once; out of reach and
   walking on, stand -- his walk makes the 80 px, and going after him keeps it
   short (`_evade_exit`). With no axe of his out, straight in from
   the front. Down, looking about or held: stand off behind him.
3. **The hold** (`jack.hold_step`): a back hold waits while a juggled axe is
   still up (they drop at the end of their arcs); a front hold crosses over
   out of one about to land (lets go when the crossover is spent). Then knee,
   knee, cross over, suplex -- 9, which leaves a round-2 Jack (9) alive at 0,
   so the punch before it makes one hold a kill; from a back hold the suplex
   when it kills, else the crossover and the knees. Near a camera bound,
   whichever finisher leaves him less far out of the actor's reach: the
   crossover's suplex lands him 136 px on the way the actor faced (58 of
   flight, 78 of slide), the B+back throw 270-278 px behind it. Another
   enemy's blow landing sooner than a knee finishes gets the throw, as for
   any grunt.
4. **Ownership**: `could_engage_jack` for every live Jack in the camera,
   armed or not, at 0 health too. `Punch`/`MeleeWeaponAttack`, `GrabEnemy`,
   `RearAttack`, `WalkToNearEnemy` and the grounded `JumpAttack` stand down for
   him, and `ProjectileSidestep` for a live Jack's axes (`reach.jack_still_juggling`
   now reads the axe's own `+$30`/`+$31`: the old distance guess called a throw
   released point-blank "still juggling"). `EngageJack` ranks 30 less a point
   per 40 px plus the armed raise, 72 while an axe of his is out at the actor
   (`jack.axe_threatens`), 5 under another enemy's committed strike, a flat 6
   while a nearer grunt able to act is in the fight's box
   (`reach.presses_sooner_than`); `partner.do_not_harm_partner` withdraws it
   on the partner's Jack. Armed, the plan's strike candidates are the weapon's
   own move (`jack.strike_specs`), not the punch: see **Seven fixes**.
5. **Observation**: `world_map` reads Jack's `+$31`, animation, approach point
   and speed, timers and fine position, and the axe's own state, flags, `+$54`
   offset, owner (`+$42` -> `owner_slot`), fine z and its real X velocity
   (`+$1C` -- `vel_x` used to read `+$20`, the lane, so a thrown axe looked
   motionless).

The model was checked against the ROM before anything was built on it: the
baseline's per-tick trace replayed offline, axe by axe, update by update --
3,939 of 3,950 single-update steps exact (the arc, the drift, the walk back,
the restart, the thrown flight); the 11 misses are 1-3 px while he walks, the
object pass reading his position before or after his own update.

Scored with `tools/jack_fight.py --level 2` (Blaze, turbo 4, no food, no
police, every other ordinary family swept; round 2 has three personality-0
Jacks):

| | Jack hits (damage) | lives lost | round | notes |
| --- | --- | --- | --- | --- |
| before (generic verbs) | 13 (156) | 1 | 105 s | 11 juggled-axe hits; `JumpAttack` 1839 ticks at him |
| plan, first run | 28 (320) | 4, game over | -- | a Jack at 0 health was dropped as dead: no verb for 90 s |
| + 0 health is alive | 2 (24) | 0 | 81 s | both in `$07`: he turned as the actor walked past |
| + `$07` faces every update | 2 (24) | 0 | 85 s | one aim through the juggle's band, one front hold burnt by the pose lag |
| + band exit, hold pose lag, wait for axes in flight | 1 (12) | 2, both the round clock | 210 s | a `$07` stalemate: the actor walked along with him and he reset off screen |
| + `$07` waits mid-screen | 0 (0) | 0 | 112 s | kills took 34, 31 and 21 s |
| + the punch | 0 (0) | 1, the round clock | 162 s | in `$07` the actor kept to lane 2 while he walked lane 91 for 50 s |
| + `$07` pocket, exit and X bound | 3 (36) | 0 | 81 s | kills 10, 17, 30 s; a punch thrown facing away, one from below his band, one unexplained |
| + punch turns by walking, pocket from above | 1 (12) | 0 | 92 s | kills 12, 31, 20 s; a dropped axe on a front holder |
| + dropped axes fall, camera-bound throw | 1 (12) | 0 | 87 s | kills 14, 26, 15 s; the hit came from an axe 47 px off, which the `$2B` box cannot reach |
| + stand while he walks on out of reach | 0 (0) | 0 | 97 s | kills 16, 33, 26 s |

The harness logs the round clock from the "punch turns by walking" runs on.
Before that, "the round clock" in these tables is read off a full-health,
no-attacker loss at the end of a long stalemate; a pit looks the same. The
clock's own reading cannot name one either: the time-over writes 55 on the
frame it takes the life, so `jack_fight.py` now reads the time-over byte
(`$FFFA49`) and files such a loss as `round_clock` (**Round 6: the factory
floor**).

Round 5 (`--level 5`: four personality-2 Jacks at once, one with 14 health,
then a personality-3 one near the level's right X bound):

| | Jack hits (damage) | lives lost | to the boss | notes |
| --- | --- | --- | --- | --- |
| the punch | 1 (12) | 1, the round clock | 161 s | the p3 Jack stood 65 s at X 5390 in `$07`, pinned by `$1510` |
| + `$07` pocket, exit and X bound | 0 (0) | 0 | 93 s | p2 Jacks 10-19 s each, the p3 Jack 6 s |
| + punch turns by walking, pocket from above | 0 (0) | 0 | 132 s | a p2 Jack suplexed past the camera's right bound took 45 s |
| + dropped axes fall, camera-bound throw | 0 (0) | 0 | 94 s | p2 Jacks 8-15 s each, the p3 Jack 12 s; three camera-bound throws |

Round 4 (`--level 4`: one personality-0 Jack, whose `$07` always goes up),
with everything above: no hit, no life lost, Bongo reached in 65 s, the Jack
dead 8 s after he appeared.

Round 6 (`--level 6`: one personality-1 Jack, the retreat and ranged throw,
whose `$07` always goes down): no hit from him, dead 10 s after he appeared
-- each time his retreat aborted into `$07` with the actor inside 64 px, and
the hold followed. The round's losses were not his: four 20-point hits from
the round's drop presses (type `$42`), and a life to the round clock after
the stage walk had stood 70 s at X 2557 against a machine housing the router
could not see. Not a pit -- round 6 has none -- and the clock read 55 because
the time-over writes 55 on the frame it takes the life (**Round 6: the factory
floor**, below).

**What the live runs taught**, each found in a trace (`jack_fight.py` logs
every Jack and axe byte per tick, and a hit names the axe from the player's
`+$7E`):

- a Jack at 0 health is alive and still throwing (`$A13A`'s `bmi`): the first
  run dropped him and stood still for 90 s;
- in `$07` he turns every update: two "back" grabs became front holds;
- the held pose lags the grab by one update: an axe whose arc ends then walks
  back to his hand -- through a front holder -- and restarts a whole arc;
- the pocket above his lane is not the way out from below it: 17 lanes below
  him the aim climbed through the juggle while 8 lanes down cleared it;
- his `$07` must be waited out mid-screen: an actor that walked along with him
  let him reset off screen, straight back into `$07`, until the round clock
  ran out;
- keeping out of his band is not enough either: an actor that did only that
  sat at lane 2 while he walked lane 91 to and fro for 50 s. The pocket above
  him is where the punch ends it;
- the level's X bound holds his walk and nothing else: pinned at X 5390 with
  the actor held by the camera at 5344, a round-5 Jack stood 65 s; 88 px
  behind his walk resets him;
- a punch pressed with a turn is thrown the old way: facing away in the
  pocket, five punches whiffed while he walked into the actor, and his walk
  through it took a front hold with both axes up;
- the pocket is only reachable from above: from below, a punch on the way,
  15 lanes under him, landed, and an axe finishing its arc hit the locked
  actor;
- a dropped axe still hurts: the arc a front hold cut short fell 128, 137,
  147, 158 onto the holder 22 px away -- the model had deleted it, so
  `hold_is_burnt` called that hold clean;
- at a camera bound the finisher's landing side matters: cross over and
  suplex threw a round-5 Jack past the right bound, and his jumps kept him
  out of reach for 30 s.

**Round 6: the factory floor** (user, after a live `jack_fight.py --level 6`
run: from t≈40 s to 109 s "the actor stood at world x=2557 with the verb
`WalkToAdvanceStage` every tick and no enemy on screen", then lost a life with
no attacker at x≈2474 while the logged clock read 55, and took four 20-point
hits from a type-`$42` object; "Find out why ..., fix it in autoplay with unit
tests, and document the causes"). Three causes, and none of them a pit:
round 6 has no hole at all.

- **What a collision class is, is the round's.** The class map holds a
  nibble per 8x8 cell; `sub_00019BD8` points `$FFFC34`/`$FFFC38` at the
  round's own kind and surface tables (`$19C04`), and `sub_0000AD30` reads a
  point as `kinds[class]` when the probe's z is at or below
  `surfaces[class]`, else as nothing (z grows downward; a standing player's z
  is its floor's surface, `$3E78`). Under the feet (`$3D34`) kind 0 is no
  floor -- a fall until `$358C` takes a life at z `$1C0` -- 1 floor, 2 and 3
  floor carrying the player +1/-1 px an update (`$3E4A`/`$3E52`). Ahead of
  the mover (`$3C92`: 8 px along its X velocity, on its own lane, 8 px above
  its feet) any floor that high undoes the whole step: a wall. Round 6:
  class 0 no floor, 1 the street (z 160), **2 floor at z 0 -- 160 px of
  machine housing**, 3 and 4 the belts. Rounds 1-5 share one table, in which
  0, 3 and 4 are all holes; in round 7's, 2 and 3 are walls. `hazards.py`
  took class 0 for the hole and every class from 2 up for a "barrier" in
  every round -- round 6's belts were barriers, rounds 1-5's classes 3-4
  floor. It reads the transcribed tables now (`hazards.FLOOR_TABLES`,
  `floor_kind`, `is_hole_class`, `is_wall_class`), and its scans start on a
  cell edge (a window starting mid-cell reported each region up to 7 px off).
- **The stall was a housing the router could not see.** `floor_barriers` was
  built on every snapshot and read by nothing in `ai/`. The first housing past
  Bongo's arena covers lanes 0-63, its left edge at x 2512 on lanes 0-7 and 8
  px further right per row down to 2568 on lanes 56-63, its right edge at 2680:
  on lanes 56-63 the probe meets it from x 2560 -- the report's 2557, one row
  above free floor. `WalkToAdvanceStage` planned straight RIGHT (the route
  "reached", nothing in its way) and `$3C92` undid every step until the clock
  ran out. Not a scroll lock: after Bongo the camera scrolls to 2752, and the
  reproduction, which happened to take lane 87 there, walked straight on.
  Walls are `Wall` tokens now (`observe`, from `floor_barriers`) and solids for
  every routed verb (`navigation.wall_obstacles`: the cells grown by the
  probe's 8 px on X, restated for the body like a prop's point rule).
  `find_collision_barriers` reports them exactly -- one rectangle per run of
  cells along a row, merged down the rows while the run keeps its extent --
  because the housing's bounding box covers the floor its steps leave free,
  and an actor standing there, centre inside the box, has the whole obstacle
  dropped by the path finder. `tests/ai/test_round6.py` walks Blaze from
  (2530, 60) under the ROM's own probe: blind to the housing she stops at
  2557 with over 100 steps undone; with it she goes under.
- **The life was the round clock, and the harness could not tell.** Each
  section resets the clock to 50 (`reset_wave_timer`, `$195F6`), a unit every
  90 frames -- about 55 s of a turbo-4 run. At 00 the time-over (`$10976`)
  freezes every object for 255 frames, then writes **55** to the clock and
  takes 80 from the player (`$109DE`) on the same frame; the respawn
  (`player_spawn_or_respawn`, `$1E0E`) puts the player at `cam_x` (lane 104 in
  round 6) and drops it in. So the loss is logged with the clock at 55 and,
  once respawned, at the camera's left edge -- 2474, 83 px behind where the
  actor stood. `jack_fight.py` now watches the time-over byte (`$FFFA49`,
  `mm.ADDR_TIME_OVER_SEQUENCE`) and files a loss within 15 s of it as
  `round_clock`, with the tick before it (`clock_before`, `p1_before`): "the
  clock only if it reads 00" could never fire.
- **The `$42` object is a drop press** (`ai/press.py`, from `sub_00007A6C`):
  six on lane 112, the bottom of the street, at x 1832, 2632, 3688, 4520, 4776
  and 4904, 96 px up. Armed until a player's X is in `(x - 48, x + 96]` (any
  lane), it shakes 11 updates and falls -- 2 px an update, half a pixel more
  every update -- and every update of the fall tests two boxes against both
  players, 20 damage and a knockdown: `$F4`, 16..56 px ahead and 8 lanes above
  to 40 below it, and `$EA`, 48 px behind and **12 to 48 lanes above** it.
  Each is 16 px tall at the press's own height, so only the last ~6 of the
  fall's 16 updates reach a standing body; then four bounces, 50 updates
  down, the climb, 50 up, armed again, and none of that tests contact.
  Catalogued as a projectile, it came through `projectile_threatens`'
  zero-velocity branch -- within 24 lanes of its own lane -- while `$EA`
  reaches 48 lanes up: both hits in the reproduction (x 1811 lane 71 under
  the press at 1832, x 4503 lane 87 under 4520) were `$EA`, from 25-41 lanes
  above. It is its own kind now (`"hazard"`, a `Press` token, `ATTACKING` on
  the map while it shakes and falls): a committed press's zone -- shaking,
  falling, or armed with a player already in its window -- is a solid to the
  router (`navigation.press_obstacles`), and an actor already in one walks out
  the soonest way (`execute._press_escape_mask`, after the pit escape: every
  direction played at the character's walk, with the lane band, the camera
  clamp, walls and pits refusing steps). Armed with nobody in its window it
  stays walkable on purpose: the window starts where `$EA` does, so a walk
  kept out of the zone would never set it off and would wait on it forever.
- Not modelled: the belts. At +-1 px an update they slow a walk (Blaze's is
  3.25) and carry a standing actor, and nothing measured has needed more.

Live, `tools/jack_fight.py --level 6` (Blaze, turbo 4, no food, no police,
only Jack kept; one run each, so a direction, not a score):

| | press hits | lives lost | notes |
| --- | --- | --- | --- |
| before (the report) | 4 (80) | 1, the round clock | 70 s at X 2557 against the housing |
| before, `stage_walk_diag.py` | 2 (40) | 0 | took lane 87 under the housing; both hits `$EA`, 25-41 lanes above the press |
| walls, press zones, the escape | 1 (20) | 0 | Souther pair in 88 s; a crossover in a hold on the Jack landed under the press at 4520 and the back hold kept the actor there |
| + no crossover or jump landing in a live press's reach | **0** | 0 | Souther pair in 92 s, no hit of any kind; the Jack dead 11 s after he appeared |

`tools/stage_walk_diag.py` is the trace that found all this: every tick's
position, held mask, verb, route, camera bounds, class under the actor,
time-over byte and object census, plus the class map whenever it changes.

**HakuRo: rising from below deck (user, in Portuguese): "No nível 5 há um
bug que a AI fica presa num inimigo que é detetado (e bem), mas está por
debaixo do chão do estágio (o estágio é num barco e o inimigo sai a
saltar), a IA fica presa a tentar dar murros no inimigo, mas este ainda não
está disponível."** Reproduced at round 5, wave 3 (0-indexed, the 4th
wave). The enemy is **HakuRo, type `$25`** -- an earlier attempt at this
bug misidentified it as Nora (type `$26`, symbol `"N"`; HakuRo is `"H"`,
`ai/tokens/enemy.py`'s `HakuRo(Grunt)`, types `$25`/`$2A`), the numerically
adjacent slot in `object_catalog.py`. This capture confirmed HakuRo on
every row (`type: "0x25"`).

The ROM fact (full decode, `StreetsOfRageRecompilation/ai-analysis
/enemy-ai.md`, "HakuRo: rising from below deck"): `haku_ro_type25
_dispatcher`'s state `$13` handler (`$0000E952`) makes the object visible
and adds a fixed `$34` (52px) to its elevation (`+$18`) the moment the wave
activates it, then **does not touch elevation again on any subsequent
update** until `cam_x+$80` (or `+$100`) reaches the object's own X -- a
literal early return every tick until then. Nothing else in the ROM scrolls
the camera except stage-forward player progress, so an AI that parks itself
in front of the (fully visible, fully ordinary-looking) frozen HakuRo and
keeps attacking it never advances the stage, the camera never scrolls, the
gate never clears, and the enemy never actually rises: a genuine ROM-native
deadlock, not merely a slow animation. Live capture
(`tools/hakuro_emerge_diag.py`, round 5 jumped to directly with every other
ordinary family swept, `--turbo 2`) measured three of five wave-3 HakuRo
frozen at exactly `world_z=212` -- bit-exact, zero jitter -- for the entire
33+ second capture window, while the real pipeline repeatedly issued
`WalkToNearEnemy`/`MeleeWeaponAttack` at them; 212 is precisely 160 (the
round's own base street surface) + 52, confirming the decode against the
running game. `phases.py` has no per-type table entry for HakuRo at all, so
state `$13` decodes as `CombatPhase.UNKNOWN` -- not one of
`should_ignore_as_target`'s phases -- so nothing already in the pipeline
excluded it from targeting.

The fix does not touch `phases.py`: `Enemy.world_z` (`tokens/enemy.py`,
+$18, now threaded onto every ordinary enemy and boss the same way
`observe.py` already threaded it for Jack alone) is read by a new
`reach.enemy_still_emerging` predicate against `hazards.base_floor_z`
(`hazards.py`, the same round's-own-street-surface reference
`is_wall_class` already measures a raised class against) and wired into
`reach.live_enemies` as a fourth exclusion alongside
`should_ignore_as_target`/`is_defeated`/`in_targetable_lane`. Deliberately
**generic**, not HakuRo- or round-5-specific: the ROM fact behind it (a
body's `world_z` *is* its floor's surface once landed) holds for any
ordinary enemy in any round, and a `Boss` never populates `world_z` (it
tracks its own elevation as `ground_z`/`vel_z`), so the predicate is always
false for one. Once excluded from `live_enemies`, the frozen HakuRo also
stops blocking `could_walk_to_advance_stage` (`decide._advance_blocking
_enemies` iterates the same list), so the AI naturally resumes walking the
stage forward -- which is exactly what satisfies the camera gate and lets
the ROM's own handler finish the rise. No extra plumbing was needed for
that half: it falls out of the existing stage-advance gate reusing
`live_enemies`.

Verified live, before and after, on the same wave-3 scenario
(`--turbo 2 --poll-ms 16`, `--kill-street-enemies`-equivalent
`--only-enemy hakuro`, a hard wall-clock backstop and an instant
`level_index` stop on every tick): before the fix, wave 3 never progressed
in over 33s of capture (hakuro count held at 5 the whole time); after, the
same wave completed cleanly in ~27.5s (hakuro count 5 -> 3 -> 0, wave
advancing to 4), with `WalkToAdvanceStage` appearing prominently in the
verb log and the previously-frozen slots' later `JumpAttack`/
`MeleeWeaponAttack` verbs landing only once their own `world_z` read back
at the floor -- confirming the gate does not over-suppress a HakuRo that
has actually landed. Unit coverage:
`tests/ai/test_reach.py`'s `EnemyStillEmergingTests`.

**Seven fixes: weapons, the floor, Jack, Mr. X, the camera and no whiffs**
(user, in Portuguese, with "liberdade ampla para acrescentar e modificar o
que for preciso"). Seven reports, one pass; every one is pinned by unit tests
and **none has been run live yet** (no ROM on the machine the change was
written on). In the user's order:

1. **Armed, Jack can be struck through his juggle** ("A IA não sabe que
   quando tem armas, pode atacar o Jack, mesmo que ele tenha tochas/machados,
   porque ao contrário de ataques só com os punhos, com armas, acertam no Jack
   sem ferir a personagem"). The model already had the mechanism: `$AAA0`
   tests a live strike box first, and an axe whose box meets it is struck
   (`jack._punch_meets_axe`), not the actor. Armed, `EngageJack`'s lookahead
   now plays the weapon's own move instead of standing its punch down
   (`jack.strike_specs`, `execute.jack_strikes`): a bat/pipe swing's box at
   its peak (`peak - 18 .. peak`), 4 damage (knife 5, bottle 3; pepper none,
   its B throws), locked 13 updates. The swing's live updates are
   unmeasured, so every strike is played under three live windows
   (`jack.SWING_LIVE_WINDOWS`, inside `MELEE_WEAPON_SWING_LIVE_UPDATES`) and
   scored by the worst -- a swing is pressed only when all of them land and
   nothing reaches the actor through the lock. `PunchSpec` carries the damage
   (`World.damage`). With the knife, only while B is the stab (item 4).
2. **`EngageJack` yields to nearer fights** ("A IA dá muita prioridade ao
   EngageJack, mesmo quando tem muitos mais outros inimigos mais
   iminentes que o Jack"). `reach.presses_sooner_than`: an ordinary non-Jack
   enemy that can act and be struck (not down, stunned or held), nearer than
   him, inside the fight's box (`SURROUNDED_NEAR_X`/`_Y`) or committed and
   closing (`is_incoming_melee`). While one exists `EngageJack` is a flat 6,
   no armed raise -- under the walk to it (8-14) and everything aimed at it,
   above `WalkToAdvanceStage`. An axe of his out at the actor still takes the
   tick (72).
3. **No `EngageMrX` without Mr. X** ("A IA emite EngageMrX, mesmo quando o
   Mr. X não está no contexto"). The office's first waves were an `EngageMrX`
   with an empty target. They are `FightMrXOffice` now (the nearest helper
   named as the target, the same `mr_x_plan.plan` with no Mr. X, the same
   76); `EngageMrX` only ever names a live `MrX`.
4. **The weapons' reach, the knife above all** ("A IA não sabe bem o
   alcance das armas, especialmente da faca"). Read from `$3084
   (player_held_object_attack_input)`, reimplemented by hand in
   `StreetsOfRageRecompilation/SoRInteractions.cpp` (`hasNearbyObjectInFront`):
   the knife's B is the **stab** (`$46`) whenever *any* object of the first 32
   slots -- any type but `$00`/`$16`: enemies, items, props, projectiles,
   effects -- is in front under 144 px on a lane in `[y - 12, y + 12)`, and the
   **throw** (`$44`) only when none is; pepper's B is always the throw; a bat
   or pipe always swings (`$48`). So the old `ThrowKnife` envelope (40-90 px)
   was a stab into the air every time. Now: `WorldMap.front_scan` carries the
   scan's slots, `PlayableCharacter.knife_cone_occupied` the ROM's answer, and
   `decide.knife_would_stab` also tests every object token the context holds;
   `ThrowKnife` needs an empty cone, the target in front (B is sampled before
   a turn) on the lane band (`KNIFE_THROW_LANE_Y` 8) -- so 144 px out or more
   on the actor's lane; `MeleeWeaponAttack` with a knife needs the target in
   the cone (a stab); pepper never melee-strikes. The bat/pipe band is the
   swing's (`tokens/character.py`: `swing_peak_x`, `swing_inner_x`): Axel 12..36,
   Blaze 29..53 (it was 12..36 for everyone -- Blaze swung under her own
   swing), Adam estimated as Axel (unmeasured). The approach stops inside it
   (`execute._enemy_stop_dx`, the strike goal's `inner_dx`). Still unmeasured,
   and marked so: the knife/bottle stab's reach (kept at the punch's), every
   weapon's live frames, Adam's swing.
5. **Nothing is struck on the floor** ("A IA não reage bem quando um inimigo
   não pode ser atacado (por exemplo quando está no chão), e tenta atacar esse
   inimigo, mesmo que seja impossível"). `is_punishable` names KNOCKDOWN, so a
   punch at a body on the floor scored 60 and hit nothing: the ordinary
   knockdown (`$0300`, `$991A`/`$99A2`) runs no contact test. `reach.
   can_be_struck` (not KNOCKDOWN, DEATH or SCRIPTED, not dead by its health
   word) gates every strike, thrown weapon and `enemy_actionable`; the walk to
   a downed enemy is capped at 7 (`_EMERGENCY_WALK_TO_DOWNED_ENEMY`): the
   actor fights anything standing first and otherwise waits in striking
   position for it to get up.
6. **The camera's limits and the corridor's** ("A IA não tem bem noção dos
   limites esquerda/direita de câmara (janela visível) e até onde pode se
   deslocar no mundo do jogo"). `CameraRange` now carries the walk clamp
   (`left`/`right`, `$43AA`), the visible screen (`visible_left`/`_right`, 32
   px wider) and how far a walk can go before the next wave gate
   (`reach_left`/`reach_right` = the clamp at `$FFE01E`/`$FFE01A`, read into
   `WorldMap.scroll_min_x`/`scroll_max_x`; `world_left`/`world_right`,
   `scrolls_left`/`scrolls_right`). `navigation.world_rect` no longer plans
   `WORLD_MARGIN_X` past an edge the camera cannot scroll past (unknown bounds
   keep the margin), and bounds the origin restated for the body on X as on
   the lane. Pinned on the clamp facing away from an enemy behind it, the
   walk's press into the clamp is kept for the one tick that turns the actor
   (`_clamp_mask_to_camera(facing_left=...)`, `turn_at_clamp`); it used to be
   stripped, leaving the actor facing away for good.
7. **No attack that does not land** ("A IA dá muitos ataques em falso, a IA
   só deve atacar quando esse ataque resultar"). `reach.strike_lands`
   replaces the additive `reach.connects` for every strike (`Punch`,
   `MeleeWeaponAttack`, `RearAttack`, `JumpAttack`; the grab walk-in keeps
   `connects`): the band must hold where the target stands *and* where its
   velocity carries it by the time the hit arms -- projected at 30 Hz
   (`kinematics.updates_in`; the rest of `kinematics` keeps its 2x-fast
   frames, **The 30 Hz time axis**) and never through the actor. A punch at a
   body still walking in waits a tick; one at a body walking out is not
   thrown. The jump kick must land whether the body stops or keeps its `+$1C`
   for the whole flight (`jump_kick.launch_hits`); the thrown weapons must
   meet it now and at the interception; the bat arms at the end of its live
   span. Together with items 4 and 5.

**...and the wake-up strike** (user, after the above: "A IA espera que o
inimigo recupere do 'stun', mas o problema é que logo depois da recuperação,
o inimigo lança logo um murro (pelo menos com o Garcia que observei) e a IA
perde. A IA tem de mandar o murro e antes que ele recupere do stun, para o
inimigo não ter hipótese de mandar ele o murro"). Items 5 and 7 had the actor
wait where it should strike first, two ways:

- **A body on the floor**: item 5 left it at a walk into striking position
  and nothing more, so the punch only went out once it stood -- with its
  startup still to run while the Garcia's punch came. `observe.
  KnockdownTracker` (per `AgentLoop`, like `NoraAttackTracker`) counts the
  ticks each ordinary enemy has lain on the floor (`Grunt.floor_ticks`:
  KNOCKDOWN, back at `hazards.base_floor_z`, still) and learns, per type, the
  shortest floor time before one got up alive (`Grunt.wake_expected_ticks`) --
  the knockdown's timer is not decoded and its landing delay has a random
  part (`$9A32`). `reach.wake_up_strike_due` offers `Punch`/
  `MeleeWeaponAttack` at the body where it lies once the floor time plus the
  strike's own lead (and one tick) reaches that, and every tick after; before
  any is learned, from the landing on. Scored at the combo's tier
  (`_EMERGENCY_ATTACK_WAKE_UP`, 21; 10 while another enemy's strike is
  coming), so the box is out as it stands.
- **A body in hitstun**: `$9B88` and `$A43E` only count `+$50` down, but a
  `+$1C` left from before the hit made `strike_lands` project it walking out
  of reach and refuse the punch until the stun had run out. A stunned body is
  now projected in place for the stun's remaining frames. And where the walk
  skipped a body as "already in reach" while no strike was offered on it (in
  the band, walking out), the tick had no verb at all: `decide.
  _actionable_targets` now also asks for a strike that lands.

Scoring to do: `tools/jack_fight.py` armed (a round-2 pipe), a whiff count
for grunts (a strike pressed with no enemy's health moving), the wake-up
strike against a round-1 Garcia (who hits first as it gets up), and the
round-8 office walk to Mr. X.

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

# Live AI testing (turbo host + matching poll cadence; see below)
./scripts/both_turbo

# Path-finding viewer (standalone Tk; connects to nothing, so no host/port)
./scripts/pathfind_viewer
./scripts/pathfind_viewer --width 480 --height 200 --step 4 --body 24

# Or direct module invoke
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

### Scoring a fight without the food

`--no-food` (autoplay and `tools/boss_fight.py`; `scripts/go_to_boss_2`,
`_3` and `_4` pass it) leaves every `HealthPickup` on the floor for the whole session.
Use it whenever a fight is being *scored*: `boss_fight.py`'s `damage_taken`
is a running minimum, so every hit landed after a heal costs nothing on
paper, and a plan that survives only because it ate is not a plan (user).
It arrives as `tokens.DebugNoFood`, a harness token that can only ever
remove an option -- a session without it behaves exactly as before.

**And without the police** (user: "The police is allowed for Souther/Antonio,
just don't test with the police on"). `--no-police` (autoplay; passed by
`scripts/go_to_boss` for every round) arrives as `tokens.DebugNoPolice`,
which removes `CallPolice` outright; `tools/boss_fight.py` runs with it on
unless `--police` is given, and the labs and diags always do. In play the
special is the last resort and nothing more: only below
`POLICE_HEALTH_PERCENT_THRESHOLD` (or `_LAST_LIFE`), never for a crowd or a
boss on its own (user: "A AI está a depender muito da chamada da polícia!" --
the old live-boss gate, under 60% health, fired in all eight baseline
Antonio fights, right after his second kick).

### Live AI testing

When exercising the symbolic AI against a running host (not unit tests), do
not use 1× speed with the default 33 ms poll. Turbo the host and raise the
poll cadence so the agent still samples about two game frames per tick.
`./scripts/both_turbo` is the canonical recipe (meta-repo root):

```bash
./scripts/run --turbo 2 --lang en --debugUtils --port 7777 --silent &
./scripts/autoplay --poll-ms 16 --port 7777 --agent-p1 --reach-gameplay blaze
```

`--poll-ms 16` is ~2 frames at 120 Hz (`--turbo 2`). 2x is the ceiling on
the development machine (user: "use turbo 2x at max, this PC can't handle
turbo 4x at full speed"; measured, `--turbo 4` ran at 120 fps there too, so
a 4x poll cadence sampled twice per frame and the wall clock lied). Leaving
the default 33 ms under turbo makes the AI see every fourth frame. Keep
`scripts/both_turbo` as the source of truth for these flags. Use `--silent`
whenever the game is launched for debug. Only start a live session when
necessary; prefer the `autoplay` unit tests for logic changes.

**Testing the AI against a boss (user):** the meta-repo's
`scripts/go_to_boss_1` … `go_to_boss_8` do exactly this and are the intended
entry point — turbo host, matching poll cadence, `--start-level N` and
`--kill-street-enemies` in one command. Always run with the debug flags
that kill every enemy family except the boss -- `tools/boss_fight.py` and
`tools/antonio_diag.py` already do this through
`DebugScenario(kill_street_enemies=True)`, and it is not optional. A boss
fight measured with the street waves still alive mixes two different
questions (how the AI fights the boss, and how much health the level left
it) and neither answer comes out of the run. Do not add a "real waves" mode
to these tools; that was tried and rejected.

**Poll timing is now measured, not just assumed (user: "sugestões para
melhorar o timing do autoplay, mais preciso com as atualizações da host
application sem tornar a host application lenta para jogadores reais?").**
`ObserverApp._poll_loop` (`app.py`) already re-bases its sleep off elapsed
work time each iteration, so one slow tick does not stack onto the next, but
it had no visibility into how many emulated frames a poll actually covered
-- only the wall-clock `--poll-ms` it asked for. `state.read_snapshot` now
also calls the remote protocol's existing `get_game_uptime_frames()` (already
used by every offline lockstep lab, just never by live play) and carries it
in `GameSnapshot.raw["uptime_frames"]`; `ObserverApp._record_frame_timing`
diffs it against the previous poll and logs a rolling `frames/tick
min/mean/max` + `poll work min/mean/max` line at DEBUG every few seconds --
purely diagnostic, read by nothing else. This does not touch the host's own
`--turbo`/`--vsync` pacing (`VDP::renderLoop`'s `nextFrameDeadline`
accumulator in `MegaDriveEnvironment`), which stays a real-time loop for
human players regardless of `--poll-ms`.

Deliberately **not** done yet: swapping `kinematics.FRAMES_PER_TICK`'s
nominal 2 for this measured, per-tick value inside the prediction math
itself. That module's own docstring calls `FRAMES_PER_TICK` "the nominal
figures every measured constant below was taken at," and this codebase has
already paid once to learn that lesson the hard way -- see **The 30 Hz time
axis: fixed, measured, not kept** above (`OBJECT_UPDATE_FRAMES`): a
dynamically-correct time axis was built, scored with `boss_fight.py`, and
reverted because it came out worse, not better, against Antonio and Souther.
Wiring live jitter into every boss lookahead's tuned lead time needs the same
measure-first discipline before it touches combat, not a guess. The frame
counter above is step one -- watch `poll timing:` lines under real load
before deciding whether `--poll-ms 16` at `--turbo 2` is actually drifting
enough to be worth it. A further, larger option surfaced by that
investigation and also not started: the remote protocol's
`SET_LOCKSTEP`/`STEP_INPUT` primitive (`MegaDriveEnvironment`, used by every
`*_lab.py` tool) could drive live AI-controlled play frame-exactly (poll →
decide → step N frames → poll) instead of wall-clock sleeping, with zero
effect on the human-player `--vsync` path since it is a separate protocol
call the AI alone would use.

## Diagnostic tools (`tools/`)

Not part of the AI and never imported by it: each one drives the **real**
pipeline (the same functions `AgentLoop.tick` calls, in the same order)
against a live host and writes JSONL for offline analysis. None of them
writes RAM beyond the host's own documented `--debugUtils` hotkeys through
`debug_scenario.DebugScenario`. Their output is local analysis material --
do not commit `.jsonl` runs.

| Tool | Role |
| --- | --- |
| `boss_fight.py` | **Scores** one boss fight: plays the level for real, then reports killed/died, damage taken, fight length and the verb histogram. `--level`/`--boss-type` select the fight (`--level 1 --boss-type 0x56` is Antonio, `--level 2 --boss-type 0x55` Souther, the default; `--level 3 --boss-type 0x30` Abadede, `--level 4 --boss-type 0x57` Bongo, `--level 5 --boss-type 0x58` the twins -- a pair: killed when every twin seen is dead, and the summary counts the rear attacks, `chords`, and those no boss lost health to, `chord_whiffs`). `--idle-seconds N` keeps the pad released -- no tick, nothing scored -- for N s after the boss appears, and past that until a Bongo is out of his charge (handed the pad with a flame already on the actor, no plan has a move left) or an Abadede out of his run's set-up and run: a start other than the entrance. Each row also carries the nearest ordinary enemy (`grunt`: type, x, lane, state), which is how round 4's grunt was caught punching over a held Bongo. `--level 8 --boss-type 0x35` is Mr. X: the walk runs `--kill-until-mr-x`, and every row -- the office's waves before him too, as `pre` rows -- carries the raw slots of the player, him, his bullets and every Garcia (`tools/mr_x_sim.py --replay`). Boss death is the raw signed health word only (zero counts for the later bosses `$55`-`$58`, whose `$17C36` lethal test is `<= 0`, and for Abadede, whose own damage paths branch the same way) -- both `phases.boss_phase`'s `DEATH` decode and `MapEntity.is_defeated` false-positive on the transient `$164FC` lethality test, twice confirmed live |
| `jack_fight.py` | **Scores** the Jacks of one round (`--level`, 2 by default): jumps to it, keeps every other ordinary family swept (`DebugScenario(only_enemy="jack")`), food and police off, and plays it through with the real pipeline until a boss appears, the level changes or the game is over. Every tick with a Jack or an axe on screen logs both objects' bytes (state, flags, position and fine height, velocities, `+$54` offset, owner, approach point, timers); a hit is attributed through the player's `+$7E` to the axe that landed it -- read from the previous tick when the axe has already removed itself -- with its state and its owner's. The summary gives hits by source and by Jack state, each Jack's life span and personality, and the verb mix while a Jack lived. A loss with no attacker within 15 s of a time-over (`$FFFA49`) is filed as `round_clock`, with the tick before it (`clock_before`, `p1_before`): the time-over writes 55 to the clock on the frame it takes the life, and a respawn moves the player to `cam_x` |
| `twins_lab.py` | **Records, and checks the model against,** Onihime and Yasha in lockstep: the real pipeline plays to round 5's pair, then one of four actors plays a frame at a time -- `engage` (the real pipeline, ticked every two frames), `edge` (a scripted edge-and-chord actor), `wander` (a seeded walk that never attacks) or `stand` -- and every frame's row carries the input, the camera and the raw bytes of the player and both twins. `--check FILE` replays a recording through `twins.twin_update`, update by update in slot order, and reports every field that differs (`twins.check_recording`). `--character` picks who plays |
| `twins_sim.py` | **Plays whole twin fights offline**, `twins_plan.plan` against `twins.py`, from a recording's frame with the actor's start shifted around (`--starts N`, seeded): events alternate as `$AD8E` runs them, a tick about every player update (sometimes half an update or a whole one late), the stick landing 0-1 updates after the tick. Per start: strikes per twin, the first hit (the model plays no hit reaction), the time to kill both, ms a plan; `--trace U` prints every program's score per timing at update U |
| `mr_x_lab.py` | **Records, and checks the model against,** Mr. X in lockstep: the real pipeline walks round 8 with `--kill-until-mr-x`, then one of four actors plays a frame at a time -- `engage` (the real pipeline), `hold` (a scripted knee/release loop), `wander` or `stand` -- and every frame's row carries the input, the camera, a census, and the raw bytes of the player, him, his bullets and every Garcia. `--check FILE` replays it through `mr_x.check_recording` (and the Garcias through `garcia.check_recording`) |
| `mr_x_sim.py` | **Plays the approach to Mr. X offline**, `mr_x_plan.plan` against `mr_x.py` and `garcia.py`, from a lab recording's frame with the actor shifted around (`--starts N`, seeded), `twins_sim.py`'s timing; per start the first hold (marked `burnt` when a Garcia's blow reaches the holder before a knee is spent), the first hit, a Garcia held, punches and chords. `--replay FILE --at T` runs the plan on one row of a `boss_fight.py` recording (its raw slots) and prints every program's worst and mean -- why the live pipeline did what it did |
| `hakuro_emerge_diag.py` | **Traces** round 5's wave-3 HakuRo group tick by tick while the real pipeline plays, with every other ordinary family swept (`--only-enemy hakuro`): every HakuRo's raw type/position/elevation/state/health/animation, the winning verb and its target, and the wave counter, all to JSONL; stops the instant `level_index` leaves round 5, on a wave past the target, on a wall-clock backstop past the target wave, or a hard overall backstop -- see **HakuRo: rising from below deck**. Found the camera-gated freeze (`world_z` pinned bit-exact for 30+s) that `reach.enemy_still_emerging` now excludes from targeting |
| `stage_walk_diag.py` | **Traces** a round's stage walk tick by tick (`--level`, 6 by default; `--only-enemy FAMILY` or `--kill-street-enemies`), for stalls with nothing on screen: the actor's position, height, action and velocities, the mask the pad holds, the winning verb and whether its route arrived, the camera and its scroll bounds (`$FFE01A`/`$FFE01E`), the class under the actor, pits and walls, the round clock, the time-over byte and a census of every object slot; the class map (lane-band rows only -- more runs into `$FFB800`) is written as its own row whenever it changes. Runs past a mid-round boss unless `--stop-at-boss`. Found round 6's housings, belts and presses (**Round 6: the factory floor**) |
| `antonio_diag.py` | **Explains** a round-1 fight tick by tick: every candidate `Verb` with its own emergency, the actor's hold state (`+$4C` link and the action byte behind it), every byte of Antonio's AI state that `ai/antonio.py` replays (primary, tactical, `+$78`, `+$5C`, screen X, animation frame, countdown and latched box ids, velocities, 16.16 position), `antonio.kick_gate_open`, and `antonio.plan_engage`'s stick, mode and predicted outcome. First written for, and found, the front-hold stall in **Holding a boss** above |
| `antonio_lab.py` | **Lockstep lab** for round 1: plays to Antonio in real time, then steps the host one frame at a time with the real `AgentLoop` ticking every two frames (its pad recorded and replayed through `step_input`), and on every frame his object updates replays `antonio.boss_update` from the previous frame's work RAM and compares every field -- position, lane, primary, tactical, both timers, both velocities, animation, countdown, latched boxes, screen X -- the same for every boomerang of his while it flies (his linked one by his `+$6E`, older ones by slot), plus the contact outcome against the player's own `+$7C`. `--actor wander` swaps the pipeline for a seeded walk that never attacks, to run the model through all of his states; `--input-delay` adds latency. Scores the fight too (hits, holds, kicks started) |
| `bongo_lab.py` | **Lockstep lab** for round 4, `antonio_lab.py`'s shape: the real pipeline plays to Bongo, then every frame his object updates is checked against `bongo.boss_update` field by field -- position, lane, primary, tactical, `+$68`, `+$79`, both velocities, the animation, its countdown, the latched boxes, screen X -- and his flame (`$97`) the same while it exists, plus the contact outcome against the player's `+$7C` (3 grab, 1 flame hit). `--actor wander` walks a seeded path that never attacks, to run the model through every state; rows also carry the other enemies alive (how the round's grunt was identified) |
| `abadede_lab.py` | **Lockstep lab** for round 3, `bongo_lab.py`'s shape: the real pipeline plays to Abadede, then every one of his updates is checked against `abadede.boss_update` field by field -- position, lane, primary, substate `+$5B`, `+$54`, both velocities, the animation, the latched boxes, screen X -- in the states the model replays, plus the contact outcome against the player's `+$7C` (3 grab, 1 his hit, 2 a strike on him; not while the actor's own strike is live). His updates are the frames his own fields change on: the object pass keeps no fixed frame parity (a first version locked one, and a third of its checks landed on frames he had not updated on). `--actor wander` walks a seeded path that never attacks; every row carries the player's action, `+$7D` and `+$34` and his health, which is how the hold's reads were timed. Steps wait up to 15 s: the client's 1.05 s default ran out twice on a frame his run landed on |
| `hold_timing_diag.py` | **Measures** how long each hold move commits the actor for, in 60 Hz frames: the AI plays until it holds a body, then the host enters **lockstep** and the move is issued on frame 0 with the player's `+$30` sampled every frame until it settles. One fresh hold per session -- a throw and a suplex both end the hold, and re-entering lockstep on one that is already ending measures the ending. Feeds `kinematics.HOLD_*_FRAMES`; a lockstep step is one game frame regardless of `--turbo` |
| `hold_threat_diag.py` | **Checks** the other half live: plays an ordinary level with the waves left **alive** (no sweep, deliberately) and logs every tick the actor is holding a body -- action base, the winning verb, live enemy count, and `reach.frames_until_any_melee_lands` with the held body excluded. Summarises the decision ticks only ($60/$66; the animation locks in between ignore fresh edges, so counting them would dilute the question), and reports `knees_while_threatened`, which must be 0 |
| `souther_diag.py` | The round-2 equivalent: `dx`/`dy`, `souther.plan_engage`'s mode, `souther.can_commit_on`, the holder's knee chain and release countdown, and whether he is untouchable, per tick. Stops on the boss's own death (raw signed health, like `boss_fight.py`) or a level reset after the boss was seen, with a `--fight-seconds` backstop -- do not run it, or any tool that drives a live host, without a real stop condition. |
| `souther_hold_lab.py` | **Lockstep lab** for the Souther hold loop: the AI plays to its first hold, then the host steps one frame at a time through scripted experiments (`--experiments`, comma-separated, one fresh hold each: `release_regrab`, `release_loop`, `second_crossover`, `throw`, `suplex`), logging both bodies' bytes every frame; `--regrab-delay` injects input latency into the walk back in. Sweeps the street families itself every 30 frames, since lockstep stops the ordinary sweep. It measured the release countdown, the one-crossover rule and the re-grab timing `souther.py` is built on |
| `round2_death_diag.py` | **Traces** a whole round-2 run tick by tick (`--trace`) and stops the moment the game leaves the level for the title, which is what four lost measurement runs actually were: not the AI dying but the **console resetting**, caused by the debug sweep writing a death into an object slot that was still spawning (fixed host-side -- see `StreetsOfRageRecompilation/CLAUDE.md`). Records every `Pit` with `reach.pit_endangers` per tick, which is how the pit theory was ruled out: round 2 has none |
| `breakable_diag.py` | Breakable stalls, per tick while a `Breakable` is in context. Round 1 by default, with **real** enemies (the sweep did not reproduce that stall); `--level N` jumps to a round first, `--sweep` keeps the ordinary families swept (the walk `scripts/go_to_boss` and the boss harnesses make -- how the round-4 stall was reproduced), `--heartbeat-s` logs a position row that often with no breakable around (so a stall anywhere shows), `--until-boss` stops at the boss |
| `armed_combat_diag.py` | Held-weapon reach and swing timing |

## Observer surface

| Piece | Role |
| --- | --- |
| `app.py` | CLI (`--host`, `--port`, `--poll-ms`, `--hud-ms`, `--once`, `--agent-p1`, `--agent-p2`), poll loop, AI dispatch. `_record_frame_timing` logs measured frames/tick at DEBUG (**Poll timing is now measured, not just assumed**, above) -- diagnostic only, never read by the AI |
| `state.py` | Work-RAM / remote reads → `GameSnapshot`. `snapshot_from_memory_blocks` skips both `hazards.holes_for_level` and `hazards.barriers_for_level` on the elevator stage (`level_index == 6`, stage 7): its moving platform is not represented by the class-0/2 collision map the same way ordinary terrain is, so both reads would be class-map noise rather than real hazards. Barrier solids were skipped first ("class map noise cannot invent walls on the lift"); holes got the identical carve-out once a phantom `Pit` reached the AI pipeline (`ai/observe.py` builds one per `snapshot.floor_holes` entry, unconditionally) and the HUD drew a hole that was never there. `snapshot.floor_holes`/`floor_barriers` are therefore always `()` on stage 7, which is the one place both the HUD and the token pipeline need to change to make pits disappear there — everything downstream already just reads the snapshot |
| `world_map.py` | Camera + actors → map entities (incl. hunt targets); `MapEntity.stun_timer` is the ordinary-enemy `+$50` stun countdown, read only in the `kind=="enemy"` branch (the same offset is weapon wear / boss distance / player character id for other kinds) and only meaningful while `combat_phase` is `STUNNED`; `MapEntity.held_type` on an ordinary enemy is the pickup weapon `$08-$0C` it is carrying, resolved from a held weapon object's `+$52` holder pointer (`interaction==1`) -- enemies do not store the type at `+$60` (that word is their scripted approach X); `parse_world_map` takes `police_special_active` purely to disambiguate enemy state `$0400`; `MapEntity.hitbox` is the object's real body AABB -- for a player, `_object_geometry` reads it straight from the cached box at `+$70` and needs no `RomData` at all; for everything else it is rebuilt per tick from the ROM shape tables and `None` without `RomData` (*unknown*, never *no body*) -- and `MapEntity.attack_ranges` is every reach its type has (empty for a player, whose reach lives in `tokens/character.py` instead, and for bosses, whose animation sets are not labelled); `MapEntity.character_id` (0/1/2 = Axel/Adam/Blaze, `None` for non-players) is threaded through from `parse_world_map`'s own resolved `char_id` purely so a display-side consumer (today, `hud.py`'s `_display_attack_ranges`) can look up a player's per-character punch reach -- it is not read anywhere in `world_map.py` itself; `_is_dormant_combatant` drops a combatant whose **primary state is still `$0000`** whether or not the SAT-hidden bit is set: a wave's object slots are populated before `$937A` runs, so for one frame they hold a complete, *visible*, uninitialised entity -- recorded live, five of them appearing for a single tick at state `$00` with zero health and zero velocity, spread across the level ahead, and the AI punched at the nearest of them (48px away, at nothing) before they vanished. The hidden bit is a symptom `$937A` sets while testing eligibility, not the definition of dormancy. `MapEntity.enemy_vel_x`/`enemy_vel_y` carry ordinary-enemy velocity (+$1C/+$20), read only in the `kind=="enemy"` branch -- distinct fields/offsets from the boss-only `vel_x`/`vel_z` (+$20/+$24) already on the same dataclass, left untouched. `MapEntity.contact_slot` resolves the player's `+$4C` hold link to a slot name -- the ROM's own "which body am I holding", and the only field that answers it for a later boss (see **Holding a boss**); meaningful only while the action byte is in a grab/hold family, which is why `observe.py` and `is_grabbing` both gate on that |
| `object_catalog.py` | Type → symbol / color / family. Antonio's boomerang (`$96`), Bongo's flame (`$97`) and Souther's claw/afterimage (`$98`/`$99`) are catalogued so the linked boss attack objects become map entities at all (the flame reads the later-boss layout like the boomerang: animation, countdown, latched box, `+$6E`); the claw pair is then withheld **unconditionally** from being a projectile threat (`reach.is_souther_claw`), unlike the boomerang, which is only withheld while attached (`reach.antonio_still_holding_boomerang`) -- they are animation-synchronized visuals re-created from Souther's own position every tick, with no flight to intercept and no box of their own (the claw's hit is his own attack box; `ai-analysis/enemy-ai.md`) |
| `memory_map.py` | Known addresses; `OBJ_VEL_X_ORDINARY`/`OBJ_VEL_LANE_ORDINARY` (+$1C/+$20) are ordinary-enemy velocity per enemy-ai.md's object-layout table, corroborated live (a moving Garcia's +$1C tracked its actual displacement direction while +$20 stayed 0) -- distinct from the pre-existing boss-only `OBJ_VEL_X = 0x20`, which is in fact the lane velocity for the later-boss object family (`$17AB8` adds `+$1C` to X and `+$20` to the lane) -- still what `vel_x` reads for a boss and for most projectiles, while Antonio's `$96` boomerang reads its X velocity from `+$1C` (`OBJ_BOSS_VEL_X`) |
| `hitboxes.py` | Real collision AABBs, as the formal `Hitbox` value object. **Players cache theirs** at `+$64` (attack) / `+$70` (body) -- six absolute words `[x0,x1,y0,y1,z0,z1]`, written by `$4140`, whose only call site (`$1CC6` in `sub_001bdc`) is player code. **Enemies cache nothing**: `$AAA0` passes the enemy's per-frame box id (`+$2` attack / `+$3` body) to `$AB24`, which rebuilds the AABB from ROM tables on every test and discards it -- so an enemy hitbox must be *reconstructed*, not read (this is also why `enemy-ai.md` can list `+$64`/`+$70` as pointers for enemies without contradicting the player layout). Tables: `$1A68E` object shapes (5-byte records), `$1AB8E` lane extents (2-byte), `$1ABA8` player shapes; type `$58` is the one non-player that uses the player table. Both record bytes are sign-extended (`ext.w` in `$AB88`), box id 0 means no box, and mirroring is *not* applied here -- the shape table carries separate forward/backward records and the animation data picks one, so a rebuilt box is already oriented |
| `prop_solids.py` | The rectangle a **solid prop** stands behind, which is not the box `hitboxes.py` rebuilds. `sub_00003B8A` walks the object table per moving object (skipping any slot without bit 0 of `+$3A`, the solid flag -- set on every intact breakable sampled live) and `sub_00003BAE` tests the mover's **own position** -- a point, never its body box -- against `prop.x + rec[0] .. + rec[1]` on x and `prop.lane + rec[2] .. + rec[3]` on lane, strictly on all four edges (two `bcc` exits per axis), undoing that frame's whole displacement (`+$1C`/`+$20`) on a hit. `rec` is one of five records at `$3C6A`, picked by the type compare chain at `$3BC4`-`$3C00`, which ends in `nop` rather than a branch -- so every type it does not name (the round-4 props among them) uses the last record. Every record ends 4px *past* the prop's lane origin: a prop is solid behind its feet and walkable in front of them. The distinction is not academic -- a round-5 prop (`$1F`) at lane 96 draws its body box at lane 86..106, in front of its origin, while the wall that stops a player runs 76..100, twenty px behind it, so routing off the sprite plans straight through solid ground. Verified live on stage 5's 2x2 fence: from the corridor between the rows, UP stops at lane 60 (`56 + 4`, exact) and DOWN at 75, one walk step short of the predicted 76 |
| `attack_ranges.py` | Every enemy type's real reach, extracted from the ROM's own animation sets (graphics-engine.md §8.3). Walks set → animation → frame record collecting each frame's attack box id, resolves it through `hitboxes`' shape table, and keeps only boxes that out-reach that same frame's *body* box by `MIN_REACH_GAIN` -- Garcia's and Signal's idle animations both present a body-sized contact box for `$AA22`'s grab path, which is not a strike. Even (right-facing) animations only, so every `AttackRange` is already forward-oriented and mirrors via `projected`. Held-weapon reach is **not** extracted (a weapon is its own object with its own attach table); `held_weapon_range` supplies the one measured value, bat/pipe 36px, and `None` for everything unmeasured |
| `rom_data.py` | `RomData` — shape tables + animation sets, read **once per connection** (ROM cannot change) and threaded through `read_snapshot` into `parse_world_map`. A read failure degrades to `None`: the observer keeps working without hitboxes or attack ranges rather than failing |
| `hazards.py` | Pause, police special active, floor holes and walls. **What a class is, is the round's**: `FLOOR_TABLES` transcribes `$19C04`'s per-round kind and surface tables (`sub_0000AD30`), so a hole is a class with no floor (`is_hole_class`: 0, 3 and 4 in rounds 1-5, 0 in round 6) and a wall one whose floor stands 8+ px above the street's (`is_wall_class`: round 6's class 2, 160 px of machine housing; round 6's 3/4 are belts). `find_collision_barriers` reports walls exactly, one rectangle per run of cells along a row -- a housing's bounding box covers floor its stepped edge leaves free (see **Round 6: the factory floor**) -- and every scan starts on a cell edge. The collision map is **exactly `stride * 16` px wide and `len(cmap) // stride` rows tall**, and both scanners deliberately sweep wider than that (`holes_for_level`/`barriers_for_level` cover `camera_x - 512 .. camera_x + 832`), so the off-map bound must be applied in `_find_class_regions` -- it cannot be left to the class value, because `collision_class_at` reports 0 off the map and 0 is *also* the pit class. Before that bound existed, `row * stride + col` with `col >= stride` silently read the **next lane row**'s terrain, so the tail past a level's own width scanned as one enormous hole and reached the AI as a phantom `Pit` (rerouting, `_pit_escape_mask` shoves) and the HUD as a hole that was never there |
| `phases.py` | Combat-phase decode for map outlines and AI danger checks. `CombatPhase.STUNNED` is the ordinary-enemy *timed* stun -- state `$0200` hitstun (handler `$9B88` seeds `+$50` with `$18` and only counts it down before restoring `$0100`) and state `$0400` pepper-spray immobilization (shared handler `$A43E`, `+$50 = $A0`). `$0400` is also the police-special sweep removal, which forces health `$FFFF` while the global flag is up -- that case stays `SCRIPTED`, which is why `ordinary_enemy_phase` takes `health`/`police_special_active`. Distinct from `RECOVERY`, the tail of a move the enemy itself chose. `_TYPE_SPECIFIC_MOVE_PHASES` (formerly `_GARCIA_MOVE_PHASES` -- renamed once it grew a non-Garcia entry) covers states outside the generic `$00`-`$07` table per ordinary type; Nora (`$26`) was previously entirely absent from it, so every one of her own states (whip engage-and-swing at `$08`, the shared "damaging special" entry `$0A`, post-hit recovery `$0B`/`$0C`/`$0F`, knockdown-trigger `$10`, blocked-delegate `$12`, lunge windup `$13`/`$14`, and the lunge itself at `$15`) fell through to `UNKNOWN` and the AI could not tell she was dangerous, closing, or genuinely stunned at all -- confirmed by dumping her primary-state dispatch table directly from the ROM (word table at `$10362`, referenced by `nora_type26_dispatcher` `$F038`; table entry *N* is state byte *N*, the same alignment `$991A`/`ordinary_enemy_begin_knockdown` at entry 3 already confirms for every ordinary type). State `$15` (`$F6BC`) writes `+$1C`/`+$20` (`grunt_vel_x`/`grunt_vel_y`) directly to ~2.75/2.125 px per 60 Hz frame toward the target on entry -- a scripted lunge with no attack shape of its own, the same pattern as Signal's slide but faster on both axes, and now visible to `reach.enemy_will_close_soon`'s velocity projection the same way. Jack (`$27`) shares that identical lunge toolkit (enemy-ai.md "A second scripted lunge, shared with Jack": his own table at `$1037C` reuses the same `$F5F2`/`$F64A`/`$F6BC` addresses) but at his own state numbers `$08`/`$09`/`$0A` rather than Nora's `$13`/`$14`/`$15` -- was previously absent from `_TYPE_SPECIFIC_MOVE_PHASES` entirely, so his lunge fell through to `UNKNOWN` (invisible to `is_dangerous`/`enemy_will_close_soon`) the same way every one of Nora's own states did before she got a table |
| `hud.py` | Tk window: State / P1 / P2 + world map + AI toggle labels; restores last window size/position. Also draws the path finder's own plan for whichever agent is on -- green arrows through `Path.positions()`'s merged vectors, red when `Path.reached` is false, a ring at the final planned position. Sourced from `VerbState.route` (`ai/loop.py`), filled from `execute_tick`'s `route_trace` param -- a `ContextVar` set only for the duration of that call, since the routed handlers are reached through `_HANDLERS`' generic `(verb, context, gamepad)` dispatch and cannot carry an extra parameter without widening every other handler to match. `route=None` means "nothing to route" (drawn as nothing); an *empty* `Path` (arrived already) is a real, different value and is not confused with it |
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
- `--start-level N` / `--only-enemy FAMILY` / `--kill-street-enemies` —
  debug scenario (requires the host `--debugUtils`). The last kills every
  ordinary family so a boss fight can be isolated.
- `--kill-until-mr-x` — round 8: every enemy and every boss dies (the host's
  `Alt/Option+X`) until Mr. X's office scene is up, and nothing after; not
  combinable with the other sweeps (`DebugScenario(kill_until_mr_x=True)`).

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
  covers the other. `hud._display_attack_ranges` is what actually feeds this
  loop (both the pool-sizing pass and the draw pass), not `entity.
  attack_ranges` directly: `world_map.MapEntity.attack_ranges` is, by design,
  always empty for a `kind=="player"` entity (that reach lives in
  `tokens/character.py`'s punch geometry, not a per-frame ROM extraction), so
  without this the HUD drew a player's real body-AABB hitbox outline but
  never its hit-range square, which visually read as "the HUD shows the
  hitbox as if it were the hit-range" -- a live-reported symptom. The helper
  appends one synthesized `AttackRange` (unarmed punch, or the same
  `MELEE_WEAPON_PUNCH_OUTER_X` reach an enemy's own held bat/pipe gets, when
  `MapEntity.held_type` is a melee weapon) built from `tokens.character.
  punch_inner_x`/`punch_outer_x`/`PUNCH_RANGE_Y` keyed by `MapEntity.
  character_id` -- the exact numbers `ai/reach.py`'s own band tests already
  use, never a second set invented for display -- for `kind=="player"` only;
  every other kind is returned unchanged
- A closing-threat arrow (`hud._closing_projection`, orange `_CLOSING_COLOR`,
  same as `phases.phase_color`'s `CHARGE`) is drawn from an on-screen
  ordinary enemy's current position to where its own `enemy_vel_x`/
  `enemy_vel_y` projects it `ai.reach.CLOSING_ENEMY_THREAT_FRAMES` ahead
  (60 Hz frames, the unit those velocity fields are in),
  whenever that enemy is in a committed phase (`phases.is_dangerous`) and
  actually moving — deliberately distinct from the `AttackRange` squares:
  Signal's slide (enemy-ai.md "Signal's slide is velocity, not a hitbox")
  has no attack shape anywhere in its animation set, so nothing would ever
  paint a range square for it without this. Gated on the committed phase
  (not velocity alone) so a routine approach, which has real velocity too,
  does not bury the one case this exists to surface; `kind == "enemy"` is
  belt-and-braces on top of that, since `world_map.py` never populates
  `enemy_vel_x`/`enemy_vel_y` for a `boss` entity in the first place
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
| `tokens/` | All token classes (including ABCs), split by kind; the package `__init__` re-exports everything. `tokens/tokens.py` (`Token`/`Information`/`Verb` base classes, `Context`, `find`/`find_all`; `Information` splits into `Observed` (directly read from RAM) and `Inferred` (derived from observed tokens)); `tokens/character.py` (`Character` common actor base (`slot`, position, health, facing, combat phase); `Myself`/`Partner` (`player_index`, `action_state`, `action_flags`, `is_airborne`, punch inner/outer helpers, `vel_x` from player `+$1C` -- the word Antonio's kick gate reads -- and their own `hitbox` -- read straight from the object's own cached box at `+$70`, never reconstructed, and carrying no `attack_ranges`: a player's reach is this module's punch/rear/jump-kick geometry, not a per-frame extraction)); `tokens/enemy.py` (`Enemy` (a `Character`; adds `type_id`, `targets_player`, the formal `hitbox`/`attack_ranges` value objects plus the `max_reach`/`min_reach` helpers derived from them, `is_defeated` (the ROM's lethal check is **signed**, so a health word of `$8000`-`$FFFF` is already a corpse while the object sits in its slot with a stale action family -- judging "still a target" from `combat_phase` alone kept the AI walking to, ranking and punching bodies, which is what "attacking enemies that are not there" looks like from the sofa; zero health is *not* defeated and still owes a finishing hit) -- value objects rather than tokens, since a token may never embed a token by value, `held_weapon_type` (pickup `$08-$0C` while this enemy is holding one, else 0 -- ordinary enemies do not store this at `+$60`; observe copies `MapEntity.held_type`, which `world_map` resolves from the held weapon's `+$52` holder pointer), `grunt_vel_x`/`grunt_vel_y` -- ordinary-enemy-only velocity, defaulted to 0 and unused by `Boss`, which keeps its own separately offset `vel_x`/`vel_z` -- and `predict_position_after_n_frames(n)`, the enemy's own constant-velocity extrapolation in **60 Hz game frames** (the unit `$17AB8` integrates `+$1C`/`+$20` in, *not* AI poll ticks, which are ~2 frames each at the 33ms default), which every lead time in `ai/kinematics.py` is built on and which a `Boss` answers with its current position since it never populates those fields) + subclasses: `Grunt` (ordinary types `Garcia`/`Signal`/`HakuRo`/`Nora`/`Jack`; carries the ROM's own `stun_timer` at `+$50` plus `is_stunned`, an ordinary-enemy-only field since both stun handlers are ordinary state-table entries; `Nora` additionally carries `ticks_since_last_attack`, cross-tick memory maintained by `observe.NoraAttackTracker` -- not a RAM field, defaulted to `NORA_TICKS_SINCE_ATTACK_UNKNOWN` for any `Nora` built without going through the tracker), `Boss` → direct subclasses `Abadede`/`MrX`/`Souther`/`Antonio`/`Bongo`/`Onihime` (`Boss` also carries `primary_state`, the `+$30` byte Antonio's kick is); `enemy_class_for_type`; `Surrounded`, the one `Inferred` judgment left about enemies (three or more live enemies inside the close box around the actor, or a pincer with one on each side; produced by `inference.check_for_surrounded`, the only function `inference.py` still has); `GrabReason` -- `CLEAR_REAR`/`DEAD_ZONE`/`WHILE_SURROUNDED`/`DODGE_CHARGE` -- an `Enum`, not a token field: it is the return type of `reach.grab_reasons(context, actor, target, enemies) -> frozenset[GrabReason]`, why a hold beats a strike; most reasons are `Grunt`-only, and neither boss with a plan has one: `EngageAntonio` and `EngageSouther` walk into them themselves, so no `GrabEnemy` is ever produced for either. `WHILE_SURROUNDED` is the only reason keyed on the actor's own situation (`reach.actor_is_surrounded`) rather than on the candidate enemy -- see `AI.md`'s "Judging without a cache" for why this, and every other judgment formerly produced by `inference.py`'s `check_for_*` functions (`ClosingEnemy`, `TargetInReach`/`ReachKind`, `IncomingMelee`, `PunishWindow`, `IncomingProjectile`, `WeaponUpgrade`, `AntonioIsGoingToKick`, `SoutherIsGoingToSlash`, `SoutherPunishesJump`, `SafeSpot`), is now a direct `reach.py` (or, for `SafeSpot`, `execute.py`) function call at each site that needs the answer instead of a token written into the context once per tick; `tokens/essential.py` (`Essential` (scene-wide observations `Stage`/`CameraRange`/`AnimationInProgress`/`InContinueMenu`/`InMrXDialog`)); `tokens/dialog_verbs.py` (`Dialog` groups UI-prompt verbs `HandleContinueMenu`/`HandleMrXDialog` -- always Yes + initials `AI `, always No to Mr. X); `tokens/hazard_tokens.py` (`Projectile` -- Antonio's `$96` boomerang also carries the rest of its later-boss object, `vel_x` being its `+$1C`, for `antonio.BoomerangSim` --, `StageObjects` (`Breakable` -- carries its real `hitbox`, `Pit`)); `tokens/pickup_tokens.py` (`Weapon` (with its real `hitbox`) + consumable `Pickup` hierarchy + `weapon_rank`); `tokens/walk_verbs.py` (`WalkToNearEnemy`, `RetreatFromDanger` (give up ground to a dangerous enemy not yet actionable -- only while hurt or `Surrounded`, per `decide._retreat_is_worth_it`; danger alone is not enough), `ProjectileSidestep` (step off a projectile's own lane rather than block its path, once `reach.projectile_threatens` judges it a threat -- built for Jack's thrown axe/torch (type `$28`), but reacts to any projectile judged a threat), `EngageAntonio` (the whole approach to Antonio, planned by `antonio.plan_engage`'s lookahead over his own AI; the hold is the contact result of the walk, armed or not), `EngageSouther` (the whole approach to Souther -- corridor, lane escape, walk-in -- planned by `souther.plan_engage`; the hold is the contact result of the walk, armed or not), `WalkToAdvanceStage`, `WalkToWeapon`, `WalkToPickup`); `tokens/attack_verbs.py` (`Punch` (unarmed only), `HitAntonioBoomerang` (timed B-punch that knocks his type-`$96` boomerang away the moment it would hit), `MeleeWeaponAttack` (armed melee -- same B input as `Punch`, different ROM move/reach per held weapon), `OpenBreakable` (one verb for the whole prop interaction -- approach *and* strike, switching on `decide.in_smash_range`; replaced the former `WalkToBreakable`+`SmashBreakable` pair, which split one intent across two verbs that had to hand over to each other between ticks), `GrabEnemy` (walk into an enemy, unarmed and without attacking, to take the hold -- a grab is a *contact* result, not an input), hold moves (`AttackHeldEnemy`/`ThrowHeldEnemy`/`FlipHold`/`Supplex`/`ReleaseGrab`/`ReleaseToRegrab`, and `ReleasePartner` -- the only one offered while the body in hand is the other player), `JumpAttack` (horizontal only), `RearAttack`, `CounterGrab`; `MeleeAttacks` groups unarmed close combat (`Punch`/`JumpAttack`/`RearAttack`); `MeleeWeaponAttack` is the armed melee sibling; `GrabMechanics` groups all grab/anti-grab moves (taking the hold included); `WeaponAttacks` groups the *thrown* weapon attacks (`ThrowKnife`/`ThrowPepper`, the only two the ROM attack-throws)); `tokens/police_verb.py` (`CallPolice` — an `Attack` descendant, health-critical only and only with at least one live enemy); `tokens/recovery_verbs.py` (`Recovery` groups actions that escape/shorten a bad state rather than act on an enemy/prop/held body; `TechRecover` — the C+Up bounce-cancel landing tech, armed only by specific special/boss hold-throw choreography (`PlayableCharacter.throw_tech_ready`), not an ordinary street-enemy throw) |
| `observe.py` | Direct observation from an already-fetched `GameSnapshot` (never re-polls RAM); free-to-act phases include `HOLDING` and `HELD_BY_ENEMY`. Fills `PlayableCharacter.held_enemy_slot` from `MapEntity.contact_slot` while the action byte is in the hold family (`$60-$6F` or the `$76`/`$80` crossover), and `HoldTracker` counts `hold_ticks` over that same family so a knee or a flip passing through an animation lock does not restart the knee budget. Also emits `InContinueMenu` from a type-`$0F` player object and `InMrXDialog` when `$FFDE00` is set and this player's `+$59` bit 4 is live. `NoraAttackTracker` is the one deliberate exception to `generate_direct_observation_tokens` otherwise being a pure function of its snapshot argument: cross-tick memory (keyed by enemy slot, one instance per `AgentLoop`) of ticks since each on-screen Nora last held a dangerous phase, reset to 0 while dangerous and incremented otherwise, feeding `Nora.ticks_since_last_attack`; `forget_missing` drops a slot the moment it stops being observed as a live Nora so a slot the game later reuses for a different enemy never inherits a stale count. `GrabStallTracker` (the old Souther walk-in timeout) is gone with the grab reason it guarded; the hold loop reads the holder's own bytes instead (`PlayableCharacter.knees_in_chain`/`hold_release_countdown`/`crossover_spent`, from `+$58`/`+$61`, `+$63` and `+$4B`) |
| `inference.py` | `check_for_surrounded` (3+ enemies in the close box, or a pincer -- reusing `rear_attack_is_warranted`'s own box so the two judgments cannot disagree) and `generate_inference_tokens` (in practice, just `context | check_for_surrounded(context)`), the only two functions left here. Every other judgment this file used to compute once per tick and write into the context -- threat-filtered incoming projectiles, closing enemies, per-move reach bands, incoming melee, punish windows, grab opportunities, weapon upgrades, Antonio's kick gate, Souther's slash gate and jump counter, safe spots -- was removed and folded into a `reach.py` (or, for the safe-spot search, `execute.py`) function called directly by whichever `could_*`/`_emergency_*`/state machine needs the answer, several times a tick rather than once; see that row below and `AI.md`'s "Judging without a cache" for the reasoning and the full list of removed tokens |
| `walk_verbs.py` | `WalkToNearEnemy`, `RetreatFromDanger`, `ProjectileSidestep`, `EngageAntonio`, `EngageSouther`, `EngageBongo`, `EngageAbadede`, `EngageJack`, `EngageTwins`, `EngageMrX`, `FightMrXOffice` (the office's waves before Mr. X), `WalkToAdvanceStage`, `WalkToWeapon`, `WalkToPickup` |
| `attack_verbs.py` | `Punch` (unarmed), `HitAntonioBoomerang` (timed punch of Antonio's type-`$96` boomerang), `MeleeWeaponAttack` (armed melee, same B input, different ROM move/reach per held weapon), `OpenBreakable` (one verb for the whole prop interaction -- approach *and* strike, switching on `decide.in_smash_range`; replaced the former `WalkToBreakable`+`SmashBreakable` pair, which split one intent across two verbs that had to hand over to each other between ticks), `GrabEnemy` (walk into an enemy, unarmed and without attacking, to take the hold -- a grab is a *contact* result, not an input), hold moves (`AttackHeldEnemy`/`ThrowHeldEnemy`/`FlipHold`/`Supplex`/`ReleaseGrab`/`ReleaseToRegrab`, and `ReleasePartner` -- the only one offered while the body in hand is the other player), `JumpAttack` (horizontal only), `RearAttack`, `CounterGrab`; `MeleeAttacks` groups unarmed close combat; `MeleeWeaponAttack` is the armed melee sibling; `GrabMechanics` groups all grab/anti-grab moves (taking the hold included); `WeaponAttacks` groups the *thrown* weapon attacks (`ThrowKnife`/`ThrowPepper`) |
| `police_verb.py` | `CallPolice` — an `Attack` descendant (health-critical only; below `POLICE_HEALTH_PERCENT_THRESHOLD`; also requires at least one live enemy) |
| `dialog_verbs.py` | `HandleContinueMenu` / `HandleMrXDialog` — UI-prompt verbs (always Yes + initials `AI `; always No to Mr. X). Name-entry confirm is C (or A): `$57D2` accepts `+$55` bits 5+6 and treats bit 4 (B) as backspace, a no-op on the first slot -- pressing B to "type A" left the AI stuck on the first initial |
| `recovery_verbs.py` | `TechRecover` — fires while `PlayableCharacter.throw_tech_ready` (armed `+$45` on a techable action `$5C`/`$72`/`$88`); `could_tech_recover` bypasses the generic `_blocked` gate like `could_counter_grab`, since the actor is airborne/hurt for the whole window |
| `kinematics.py` | The AI's **time** axis, next to `reach.py`'s geometry: where a target will be when a move actually *arrives*, so no attack is aimed at a position its own startup has already invalidated. Built on `Enemy.predict_position_after_n_frames` plus measured ROM timings -- punch startup 3/3/5 and `$322A` chord startup 3/21/7 frames (controls-and-input.md's two "Measured" tables), the jump's fixed 5-frame crouch and 3.0 px/frame launch velocity, thrown knife 16 px/frame and pepper 6 px/frame (weapons-range-and-damage.md section 4), and ground walk speeds **read from the ROM's own tables** at `$3670`/`$3706`/`$379C` (3.0/2.5/3.25 px/frame on X, 2.375/1.5/1.625 on lane): `$3614` indexes them by the character id at `+$50` and the action with its facing bit cleared, one signed byte per axis scaled by /16, entry `$06` being the straight horizontal walk -- not currently in any manuscript, extracted here. `intercept_frames` is the shared one-dimensional pursuit solve (gap over approach speed *minus* the target's own velocity along it), reporting `MAX_LEAD_FRAMES` for a target that would never be caught so the projection simply fails the band check instead of returning infinity. **A strike must land under every timing** (`reach.strike_lands`: the band at the observed position *and* at the arming frame with the target's velocity at 30 Hz; the grab walk-in keeps the additive union, `reach.connects`), which is why `connect_frames` always includes frame 0 -- the observed position, the answer the pipeline gave before any of this existed -- and why a stationary move leads only by its own startup, not by its damaging span. Both rules are scar tissue, measured by sweeping the pipeline against the previous commit: judging the punch at a single future instant projected an enemy walking into Axel from 20px straight into the punch's *inner dead zone*, deleting the `Punch`, handing the tick to `WalkToNearEnemy` and having the actor walk into enemies it should have hit -- while promoting the point-blank `RearAttack` chord, since a target inside the dead zone is exactly what makes that chord "warranted"; and sweeping the whole 10-frame damaging span instead had Axel punching at a target 74px away because it would arrive by the last frame, flailing in place rather than closing. `enemy_projected_without_crossing` is the third: straight-line extrapolation walks an approaching body through the actor and out the other side, which no enemy does (`$AAA0` resolves the contact first), so an approach is clamped at `BODY_CONTACT_GAP_X` -- clamping to the actor's exact X was not enough, since dx=0 sits inside the degenerate zero-width front band Axel and Blaze have and produced the same phantom chord a different way. Everything is in **60 Hz frames**, never poll ticks (`FRAMES_PER_TICK` is the one conversion point), and `AI_LATENCY_FRAMES` is the pipeline's own one-poll delay on top of every startup. `ATTACK_CONNECT_FRAMES` maps every concrete `Attack` to the frames its band should be tested at (`inference` takes the union) and `tests/ai/test_kinematics.py` fails if one is missing -- several are legitimately just `(0,)` and say why (`held_target_lead_frames`: a held body travels with the actor, so the relative velocity is zero; `static_target_lead_frames`: a `Breakable` does not move; `no_aim_point_lead_frames`: `CallPolice` sweeps the whole screen and `CounterGrab` is resolved by input timing, not geometry). A jump kick leads by its 5-frame crouch and **not** by its flight: how far the flight reaches is already what `reach.in_jump_attack_band` measures, and solving the full interception there launched kicks from over 100px on the assumption the target kept closing for all 25 frames. It also owns the **hold move** durations -- `HOLD_KNEE_FRAMES`/`HOLD_CROSSOVER_FRAMES`/`HOLD_SUPLEX_FRAMES`/`HOLD_THROW_FRAMES` (17-18 / 37-39 / 77-78 / 41-46 per character), measured by `tools/hold_timing_diag.py` under lockstep rather than derived from the animation records, whose `frames x delay` product is not an action's length -- plus `hold_finisher_frames` (a suplex costs the crossover too from a front hold, ~115 against a throw's 41-46) and `hold_knee_budget_frames` (three knees, the unthreatened budget that replaced a six-*tick* one). Imports only `tokens`, so `reach.py`/`inference.py`/`decide.py`/`priority.py`/`execute.py` can all share it |
| `reach.py` | **Walking into the other player** (`walking_box_would_grab`, with `walk_box_reach_x` / `player_body_span_x`): `$4478` makes a walking box on the other player's body a hold on them, so this answers whether one tick of a walk would make that contact -- the walk animation's box decoded from the ROM (`WALK_BOX_REACH_X`: Axel 16, Adam 20, Blaze 19, the longest when unknown), the body's widest ground reach (`PLAYER_BODY_REACH_X`) widened by the live `+$70` box, `PLAYER_CONTACT_LANE_Y` 16 (inclusive), a lane walk keeping the current facing, all swept over `WALK_SWEEP_FRAMES` at the ROM walk speed and the other player's own `+$1C`. The one definition of every band and target filter, shared by `inference.py`, `decide.py`, `priority.py` and `execute.py`: `live_enemies` (three independent ways to stop being a target, all needed: the phase says so, `Enemy.is_defeated` says so -- the health word, which the phase can lag far behind -- or the lane is unreachable)/`on_screen_enemies`/`in_playable_lane`/`in_camera`, `enemy_behind_actor`, `in_punch_band` vs `punch_would_connect` (the raw box ignores facing; a forward strike cannot hit backwards). The band predicates and the two facing helpers take a `Character` rather than an `Enemy` (their parameter keeps the name `enemy` for every caller that has one), because `$4478 (resolve_player_vs_player_collision)` runs the identical box-against-body test against the *other player* -- so `partner.py` asks these about the `Partner` instead of restating the geometry. Both now judge **box against body**, the way `$450C` does: `punch_usable_inner_x` is the measured inner edge less `tokens.character.BODY_OVERLAP_X`, because a ~13px-wide body centred just inside the box still overlaps it. Treating that as a dead zone was a measured disaster -- the AI refused to punch a foe 10px in front of Axel, `could_walk_to_near_enemy` took the tick and aimed 46px away to re-establish "proper" range, walking away turned the actor around, the enemy then read as *behind* it, the turn-around branch aimed back, and the actor shuffled between two points forever in punching range of an enemy it never hit. The same false dead zone is `rear_attack_is_warranted`'s first clause, so it also promoted the point-blank B+C chord as the "escape" from a situation a plain punch answers. `punch_behind_tolerance_x` is likewise **derived** rather than chosen (and evaluates to 0 for all three characters): the box starts 8-18px in front, so no body centred behind can reach it -- the old flat 4px of slack had Adam, who lands 4px past an enemy after a jump kick, standing there punching forward into empty air indefinitely. The grab keeps its own `GRAB_BEHIND_TOLERANCE_X`, since its contact test reads a walking frame's box, which starts at the actor's own origin, `in_rear_band` (side-specific, never the union; `rear_attack_behind_min_x` is the chord's *inner* edge -- Axel's box is X -40..**-8**, Blaze's -53..**-5** -- body-corrected like the punch, and a zero-width **front** band now refuses to match at all: `<=` against Axel's and Blaze's 0px forward reach still matched `dx == 0`, which is exactly where a jump kick landing on its target leaves the actor, so the AI answered "nothing can hit this" with a backfist aimed the other way), `in_jump_attack_band` (its min-dx launch gate -- no point hopping somewhere a punch already reaches -- applies only while grounded; once the actor is already airborne and committed to its free-flight trajectory, that gate is dropped so the follow-through B edge still lands even after the flight has carried the actor closer than that edge), `grab_would_connect` (forward-only like the punch test, since the ROM's contact test reads the actor's own forward-pointing attack box; ranged by the actor's unarmed punch outer edge, and by the punch band's own `GRAB_RANGE_Y == PUNCH_RANGE_Y` lane tolerance -- `$AAA0` reads that same box, and the two pixels the grab band used to give up sat exactly where `_actionable_targets` stops the approach, so the hold was unreachable from the position the AI itself chose to stop at), `rear_threats`, `rear_attack_is_warranted`, `enemy_actionable` (answered about the observed position only, unlike `connects`, which sweeps a move's own timeline -- see `kinematics.connect_frames`), `enemy_forward_dx`/`enemy_can_reach`/`in_enemy_dead_zone` (the enemy's *own* reach, answered exactly from its extracted `AttackRange`s -- `enemy_can_reach` returns `None` for "unknown", which callers must not read as "harmless"), `too_close_to_keep_approaching` (now the enemy's real reach when known, falling back to the old `punch_outer_x + RETREAT_CAUTION_MARGIN` caution box only when it is not -- that box was always an approximation built from the *actor's* punch range, which has nothing to do with how far the enemy can hit; its optional `extra_margin` widens whichever of the two the caller lands on, and exists solely for the hysteresis band below), `APPROACH_RELEASE_MARGIN` (the approach half of the retreat/approach decision suppresses itself until this far *beyond* the caution zone, instead of resuming the instant the retreat trigger clears -- approach and retreat used to switch on one shared boundary, which is a textbook limit cycle and reproduced as a one-tick direction reversal when the pipeline was driven over synthetic ticks; between the two thresholds the actor holds its ground, and the whole suppression lifts by itself once the enemy leaves its dangerous phase), `CLOSING_ENEMY_THREAT_FRAMES` (the shared "how far ahead is a committed velocity trusted" horizon -- in 60 Hz frames; it was a *tick* count multiplied straight into a per-frame velocity, i.e. half the ~200ms its own comment described), `enemy_projected` (re-exported from `kinematics.py`, which owns it now: an `Enemy` rebuilt at `predict_position_after_n_frames` via `dataclasses.replace`; a stationary enemy, and every `Boss`, projects to itself), `enemy_will_close_soon` (re-tests `too_close_to_keep_approaching` at that projected position -- the predictive half of `is_incoming_melee`, built specifically for a committed attack with no static reach to test at all: Signal's slide, per enemy-ai.md's "Signal's slide is velocity, not a hitbox") and `souther_dash_arrives_soon` (the third path into `is_incoming_melee`, for the one enemy invisible to the other two: a `Boss` populates neither `attack_ranges` nor `grunt_vel_*`, so his committed claw dash, `$161C6` at 8px/frame, would otherwise go undetected), `is_incoming_melee` (the union of all three, plus the dangerous-phase gate, shared by `grab_reasons`' own `DODGE_CHARGE` charging check, `decide.py`'s approach/retreat/grab gates, and `priority._other_enemy_is_incoming`/`_emergency_retreat_from_danger`) and `incoming_melee_targets` (the per-actor convenience: slots of on-screen enemies `is_incoming_melee` judges a threat, replacing the old `IncomingMelee` token's presence/absence lookup), `pit_endangers` (the one definition of "standing in a `Pit`'s danger zone", shared by `execute._find_safe_spot`'s candidate filter and `execute._pit_escape_mask`'s own standalone override), `any_pit_endangers` (the same check against every `Pit` in context at once, used by `decide.py`'s `could_walk_to_near_enemy`/`could_walk_to_weapon`/`could_walk_to_pickup`/`could_open_breakable` to refuse a target sitting in one), `projectile_threatens`/`projectile_ticks_to_impact` (an observed `Projectile` heading toward the actor, in lane, within the impact window -- the latter shared by `decide.could_projectile_sidestep`'s gate and `priority._emergency_projectile_sidestep`'s score so neither recomputes the other's number), `antonio_still_holding_boomerang`/`is_souther_claw`/`jack_still_juggling` (withhold an attached/unthrowable object from `projectile_threatens`'s callers), `souther_would_punish_jump` (the boss-specific gate `decide.py` reacts to directly -- Antonio's live gate is `antonio.kick_gate_open`, and the rest of him is `antonio.py`'s lookahead), `weapon_upgrade_rank` (a ground `Weapon`'s rank if it is a genuine upgrade for `actor` right now, else `None` -- the rank itself, not a bare bool, since `priority._emergency_walk_to_weapon` scores by how much of an upgrade it is), `actor_is_surrounded` (a live `Surrounded` judgment for one actor slot) and `grab_reasons` (`context, actor, target, enemies) -> frozenset[GrabReason]`, every reason a hold on `target` beats a strike right now -- `CLEAR_REAR`/`DEAD_ZONE`/`JACK_FROM_BEHIND`/`WHILE_SURROUNDED`/`DODGE_CHARGE`, shared by `decide.could_grab_enemy`/`could_rear_attack`'s `on_jacks_back` check and `priority._emergency_grab_enemy`'s `max` over the returned reasons). These were private helpers in `decide.py`, imported across modules and duplicated in `inference.py`; nothing here reads RAM or produces tokens. `held_enemy`/`in_held_contact` name the body already in the actor's hands -- the ROM's `+$4C` link first, then a `GRABBED` phase, then contact -- and `grab_reasons` returns nothing at all while the actor is holding, which is `$AAA0`'s own rule (it refuses a grab code unless `+$4C` is clear) |

| `navigation.py` | **Walls and a committed press are solids** (`wall_obstacles`, `press_obstacles`, both in `solid_obstacles`): a `Wall` is `$3C92`'s point rule -- the cells grown by the probe's 8 px on X, restated for the body -- and `wall_probe_blocks` is the probe itself; a committed press's drop zone is a body test and goes in as it is, only while committed (armed with nobody in its window it must stay walkable, or nothing sets it off). `jump_landing_is_safe` also refuses a landing in a live press's reach (see **Round 6: the factory floor**). **The partner's grab zone is danger** (`partner_obstacles`): every actor origin from which the walking box would touch the partner's body, one pixel past `$450C`'s inclusive contact, expressed for the actor's own body rectangle -- part of `danger_obstacles`, and the one danger `WalkToAdvanceStage`'s plan takes, so a partner on the lane is gone round rather than waited behind (see **Never hurt the partner**). **Jumps use this planner too**: `pit_obstacles` (holes only, no crates), `plan_lane_route` (Y-locked corridor -- a jump has no mid-air lane control), `jump_landing_is_safe` (clear lane / walk around / hop over), `hop_landing_x` (far side of the nearest blocking pit if it is in kick range). The **only** place that turns this game into `pathfind/`'s vocabulary: tokens in, rectangles out, a route back. Reads no RAM, touches no gamepad, emits no tokens. Decides three things. **What is solid**: breakables and pits are geometry, enemies and their reaches are *danger*, and the two are planned in separate passes (`plan_route` tries solids+danger first and falls back to solids alone, because a busy screen can have no danger-free route and an AI that stops moving when the room is busy is worse than one that accepts risk). Both a crate and a pit are **origin** rules -- the ROM tests the moving object's own position against them, never its box (`prop_solids`, `reach.pit_endangers`) -- so both are restated through `_OriginRule` into the rectangle a *body* may not overlap, and a crate's rectangle comes from `prop_solids`, not from `Breakable.hitbox`. The restatement is exact and uses the body's real offsets from the origin, not half its width: a cached player box is not centred on the actor (Axel's spans -7..+3 facing left), and assuming it was left a 2px sliver of wall the route stepped into and the ROM refused -- recorded live as 42 seconds held against a round-5 prop, the same symptom this model was written to remove. A rule shallower than the body is deep (the phone booth's is 14px) cannot be restated exactly at all and gets a one-px floor, which over-states it slightly rather than letting the lattice drop it as no wall at all. The pit rect also grows by one px because that predicate is inclusive and collision is not. Measured on the sweep: without the inset an actor standing safely beside a pit read as inside it, left the lane to escape a hole it was never in, and lost every attack in the run. An idle enemy's *reach* is **not** an obstacle (`is_dangerous` gates it): every enemy could swing, and routing around that potential turned a 20-tick approach into a 60-tick detour. **Where arrived is**: `strike_goal` builds a `RegionGoal` inset by half the body on each axis, so "the body overlaps it" means "my origin is within `stop_dx`/`lane_slack` of the target's" -- the same sentence `in_punch_band`/`in_smash_range` already say -- and its lane-overlap *contact* is the alignment the blow depends on, which is what makes `enough_contact` read as "px of lane margin to spare" and `maximize_contact` as "line up square". With an `inner_dx` the ground is an annulus (two bands, a hole between), so standing on top of a target is correctly not "in range"; `side` narrows it to one band when a caller must insist. When the band is thinner than the body is wide -- `stop_dx` inside the strike's own dead zone plus a body, which is exactly the Souther pocket -- there is no region left, and the fallback aims at the **stand point** (`stop_dx` out, on the side the approach comes from) as a one-px-wide region that keeps the lane band. It used to be a `PointGoal` at the *target's own position* with `tolerance=max(stop_dx, lane_slack)`, which is "be within 16px per axis of the boss" -- satisfied standing 24px out and 24px off-lane, holding no button, which is most of what round 2's stalemate was. A `PointGoal`'s `contact` is also `inf`, so that fallback silently disabled `enough_contact` and let the approach settle on the loose edge of its own band. `NAV_STEP` is 4px, finer than the executor's deadbands on purpose: the pockets to land in are ~10px deep and a coarser lattice reports them unreachable rather than steering badly. **`world_rect`'s `WORLD_MARGIN_X` must exceed every goal offset a routed verb can place beyond the actor's own position** -- `WalkToAdvanceStage`'s fixed 40px lookahead, a strike goal's `stop_dx` up to ~56px -- or the goal itself can fall outside the plannable world with no lattice position ever able to satisfy it, so `plan_route` reports `reached=False` forever rather than merely a worse route. Live-diagnosed at 32px: an actor at the camera's own trailing edge got a lookahead point 8px past `world_rect`'s right bound and stalled dead there -- not badly routed, unable to progress at all, since advancing is exactly what would have scrolled the camera and made the goal reachable again. Now 96px, comfortably past every such offset and still well inside what `world_map` already tracks past each camera edge (two screens). **Nothing tactical** -- which side, how far to stop short, whether to wait out a swing all stay in `execute.py` |
| `pathfind/` | **Standalone** rectangle path finding on a bounded cartesian plane — imports nothing from the rest of `sor_autoplay` (no tokens, no snapshot, no RAM) so it can be tested exhaustively without a running `sor`, and so the caller that turns a route into d-pad input stays the only code that knows about the game. `geometry.py` (`Rect`/`Segment`/`Point`/`Edge`/`Direction`, y grows **downwards** like the lane axis, so `UP` is towards smaller y; **touching is not overlapping**, so a body may stop flush against a crate), `goals.py` (`RegionGoal`, an *area* rather than a boundary — reached by overlapping it, contact measured on a named axis, and several regions may be alternatives so an annulus "close enough to reach, far enough not to be standing on it" is expressible. It exists because the other three are measure-zero targets: on a lattice of whole steps an exact touch is essentially never achievable, so anything meaning "close enough to act" aimed at one got best-effort routes forever. `PointGoal`, reached by *covering* the point, with an optional `tolerance` — a body cannot land its centre on an arbitrary point when every move is a multiple of the step; `SegmentGoal`, reached only by the **named** edges of the body, since touching a threshold with your right edge and having walked through it until your left edge touches are opposite outcomes of the same line; `RectGoal`, a whole rectangle as destination, defined by `(own_edge, target_edge)` **pairs** rather than by distance — `RectGoal.horizontal(crate)` is "arrive stacked above or below it" (my bottom on its top, or my top on its bottom), `RectGoal.vertical` the side-by-side pairing, a single-pair `RectGoal` forces one approach side, and `RectGoal.of` builds the full cross product, which deliberately *also* includes the aligned pairings two same-height boxes satisfy just by standing side by side. A rect goal says nothing about not overlapping the target: pass the same rectangle in `obstacles` too and the body stops flush, which is exactly where the edges meet), `grid.py` (the lattice of body positions, **anchored at the start rect** so every move is a whole multiple of the step with no ragged first hop; whole-body collision, swept moves so a step cannot tunnel through an obstacle thinner than itself, no diagonal corner cutting, and obstacles the body *already* stands in dropped for the whole search so a body inside a crate is not planned as permanently stuck), How *well* the edges meet is a separate, opt-in question, because by default any contact counts — including corner to corner, which satisfies a goal and is useless in practice (a body clipping the top corner of a crate cannot act on it). Two parameters, deliberately different tools: `enough_contact` is a **requirement** that raises the bar for arrival itself (at least N px of shared edge, else the position does not count and an unmeetable bar returns the usual best effort with `reached=False`), while `maximize_contact` is a **preference** that leaves arrival alone and makes the search prefer the flushest arrival, scoring each one `cost + alignment_weight * misalignment` and stopping only when no unexplored node can beat it (`f` is a lower bound on any route through a node, and every arrival has `h == 0`, so arrivals are popped in cost order and the test is exact). `alignment_weight` must exceed 1 to do anything at all — a px of extra overlap costs at least a px of walking, so at exactly 1 they cancel — hence the default of 2. Contact is measured **along the shared edge**: for a side-by-side pairing it is the boxes' *heights* that cap it, not their widths. `Path.contact`/`Path.misalignment` report the achieved values whether or not the search was told to care; both are `inf`/0 for goals with nothing to measure (a point, an oblique segment), so a contact requirement can never silently make those unreachable. `search.py` (ordinary A*, but **mid-search a Y-then-X finish**: after a node is expanded, if the goal is reachable from there by one axis-aligned run or by walking the lane (Y) and then the street (X), the route is the A* prefix plus those legs and the search stops; this is how a beat-em-up body actually closes, and a free-space diagonal is rejected even though it is shorter. A start boxed in still walks around with A* and only straightens once a node can see the goal that way. `maximize_contact` still requires the two legs to arrive flush, otherwise a corner clip would hide the around-the-crate walk the rest of A* is there to find. The search itself is A* with the octile heuristic — exactly the free-space optimum for these move costs, so admissible *and* consistent; consecutive cells in one direction merge into a single vector, because a d-pad wants "hold right for 88px", not eleven 8px hops; a failed search returns the **best-effort** route to the closest position reached with `reached=False`, since an AI that must act every tick is better served by walking part-way and re-planning; open-list ties are broken by insertion order, not at random, so the same world always plans the same route — and since neighbours are pushed in `geometry.ALL_DIRECTIONS`' order, that order is also which move wins an equal-`f` tie. `ALL_DIRECTIONS` is `CARDINALS + DIAGONALS`, so a straight step wins a tie over a diagonal one, keeping routes on the lattice's own axes and reserving diagonals for a move that genuinely needs one — a `DIAGONALS + CARDINALS` ordering was tried and reverted the same session: on a viewer example routing past a stacked pair of obstacles with a gap between them, diagonal-first took a longer up-and-over route (`RIGHT 48, UP_RIGHT 16, RIGHT 88, DOWN_RIGHT 24`) instead of threading the gap and using one diagonal only to line up with the target's own row at the end). `viewer.py` is a **standalone Tk window** for looking at the result — draw a body, draw obstacles, pick a destination and see the vectors, with the lattice, the merged step lengths, the arriving body edges and the best-effort route all drawable. It is not connected to anything: no remote, no RAM, no import of `hud.py` or any other `sor_autoplay` module, so the package stays dependency-free. Needs Tk, hence `python3.11`; launch it with the meta-repo wrapper `./scripts/pathfind_viewer` (which finds a Tk-capable Python the same way `./scripts/autoplay` does and sets `SOR_PATHFIND_PROG` so `--help` names the script), or directly with `cd autoplay && PYTHONPATH=src python3.11 -m sor_autoplay.ai.pathfind.viewer`; optional `--width/--height/--step/--body`; no test imports it, so the suite still runs on any Python. Not wired into `decide.py`/`execute.py` — the AI still steers as it did |
| `decide.py` | **No crossover under a live press**: `could_hold_actions` refuses a `FlipHold` whose landing -- the mirror of the actor across the body in hand -- stands in a press's reach (`press.lands_in_reach`), in Jack's loop, the bosses' and a grunt's; the hold keeps to B, which leaves the actor where it is (see **Round 6: the factory floor**). Grounded `could_jump_attack` also requires `navigation.jump_landing_is_safe` (pathfinder: do not launch through a pit the 2D walk can go around; hop over only when the landing is solid and no walk reaches); airborne follow-through skips that gate. Every reach question is answered directly against `reach.py`'s band predicates -- `punch_would_connect` for the four melee-strike siblings, `in_rear_band` for the chord, `in_jump_attack_band` for the kick, `enemy_actionable` for "already hittable, stop walking" -- and the same goes for `reach.is_incoming_melee` (retreat / don't-approach / don't-hop-into-it), `reach.weapon_upgrade_rank` (`could_walk_to_weapon`), while `could_call_police` has a single gate left -- the panic threshold, with at least one live enemy, and nothing at all under `DebugNoPolice`; `could_handle_continue_menu` / `could_handle_mr_x_dialog` fire from their Observed tokens without needing `Myself`; `_actors` yields **only `Myself`**, never `Partner` -- one `AgentLoop` runs per AI-controlled player and executes the surviving verb on *that* player's own `VirtualGamepad`, so a `Partner`-parametrized verb would be carried out on the wrong pad (and out-rank `Myself`'s own candidates while doing it); `Partner` stays in the context as `Information` only; `could_*` generators never pre-select a single "best" candidate (per AI.md: that ranking is `determine_priority_verb`'s job alone) -- `could_walk_to_near_enemy`/`could_throw_knife`/`could_throw_pepper`/`could_walk_to_weapon`/`could_walk_to_pickup`/`could_open_breakable` each produce one Verb per valid possibility, not just the nearest/best; `could_walk_to_near_enemy`/`could_walk_to_weapon`/`could_walk_to_pickup`/`could_open_breakable` all skip a target whose own position is inside a `Pit`'s danger zone (`reach.any_pit_endangers`) -- live-diagnosed: without this, a target sitting in a pit produced a walk verb aimed squarely at it every tick, which `execute._pit_escape_mask` fought right back out of the moment the actor arrived, reading as the actor turning left then right forever at the pit's own edge; the fix is refusing to generate that verb at all rather than patching the tug-of-war after the fact; `_live_enemies` excludes any enemy outside the level's playable Y lane (`lane_y_max_for_level`) -- e.g. stage 1's scripted "behind a door" placeholder, a real tracked Enemy the player can never reach -- so it can't be targeted or block stage advance; `could_walk_to_near_enemy` prefers an on-screen chase but falls back to every live enemy ahead in the stage's own scroll direction when nothing is on-screen (never one behind, per `_ahead_in_stage_direction`) -- otherwise a live off-screen enemy holds back stage advance while nothing ever moves the camera toward it; stage advance gated on *every* live enemy (on-screen or not), not just on-screen ones -- except an off-screen enemy already at exactly 0 health (`_advance_blocking_enemies`), which nothing here will ever chase down to finish off -- and on an on-camera `Breakable` sitting on the stage path (`_advance_blocking_breakables`, same ahead/camera/pit filters as `could_open_breakable`): producing `WalkToAdvanceStage` next to `OpenBreakable` was a limit cycle, the HUD flipping between them (the old name WalkToBreakable still shows up in reports) because the approach score (14 down to 8) used to cross the advance's then-flat 12 around 30-45px, and the around-path walking off a same-X crate made that hypot grow until advance won, walked back in, and handed it over again -- advance is now 1 (and 0 while a blocking crate exists), so the cycle cannot return from ranking alone; `could_open_breakable` no longer falls back to behind-only crates (walking back to one, then advancing past it, is the same cycle); `could_rear_attack` deliberately does *not* fire early on an enemy merely closing toward the rear band, only on one already inside it (a live-diagnosed regression: `$322A` only hits by current position, so an early commit while the enemy is still outside `in_rear_band` is a guaranteed whiff that locks the actor in recovery frames exactly when the enemy arrives and lands its own hit for free); `could_rear_attack` still produces on rear-band membership alone (a `could_*` answers "possible?", not "best?") -- the de-preferring lives in `priority._emergency_rear_attack` via `_rear_attack_is_warranted`; `could_walk_to_near_enemy` offers the turn-around for a behind enemy (`execute._walk_to_near_enemy_target` aims past it so the D-pad flips facing); both its threat skips and `could_retreat_from_danger` are deliberately **side-agnostic**, so a dangerous close enemy is owned by exactly one of them no matter which way the actor faces. An earlier version paired a front-only skip here with a behind-skip in the retreat ("fleeing something at your back means running blind"), and that pairing is a *facing-feedback limit cycle*: retreating holds the D-pad away from the threat, holding a direction sets facing, `reach.enemy_behind_actor` reads facing, so the same enemy re-classified as "behind" every other tick and was handed back and forth between the retreat and the turn-around -- the commanded direction reversed on **every single tick** (19 reversals in 20, measured) for as long as one enemy stayed committed nearby, with the walk verb's lane sidestep riding on top so it read as darting up/down too. Covered end-to-end by `tests/ai/test_stability.py`; `could_walk_to_near_enemy`'s "already in range, don't walk closer" skip is **per-enemy**, not global. It used to be `if any(enemy is actionable): continue`, which suppressed the approach for *every* enemy the moment one was in range -- live-reported as "ataca o outro inimigo": with a grunt in punch range and Souther two steps behind it, **no verb was produced for Souther at all**, so the grunt's punch won by default and the AI hit the sideshow while the boss walked in. Ranking is what should settle that contest (the walk-in carries `_EMERGENCY_BOSS_TARGET`), and it cannot settle one it is never shown. The skip's *predicate* uses `_enemy_actionable` (real rear band, or punch band *and* actually in front) rather than raw `_in_punch_band`/`_in_rear_band` -- live-diagnosed fix: `_in_punch_band` ignores facing, so an enemy sitting behind the actor but still inside the punch box by raw distance (beyond both the real rear band and `could_punch`'s 4px behind tolerance) used to make this skip producing any verb at all, leaving the actor standing still and undefended; `could_retreat_from_danger` is gated on `_retreat_is_worth_it` -- **hurt** (below `RETREAT_HEALTH_PERCENT_THRESHOLD`, i.e. `HEALTH_CRITICAL_PERCENT`) or **`Surrounded`** -- because backing off is a concession, not a reflex: no enemy can be defeated without standing in the range it hits back from, so treating "a committed enemy is within caution distance" as a reason to flee refuses the only exchange that ever wins the fight (the AI backs off, the enemy follows, the round goes nowhere) *and* supplied both limit cycles above with the verb they oscillated against. Healthy and one-on-one, `could_walk_to_near_enemy` owns that same enemy and walks in; the attack tiers (jump 18, punch 20) outrank the walk (14) so it strikes the moment it is in range. That one predicate is also the **single owner test**: when it holds, retreat claims the enemy and the walk stands off; when it does not, the walk claims it and retreat produces nothing -- exactly one of the two ever holds a given enemy, which is structurally what stops them handing it back and forth. Otherwise it produces `RetreatFromDanger` for a dangerous (ATTACKING/CHARGE), not-yet-`_enemy_actionable` on-screen enemy once it's inside `_too_close_to_keep_approaching`'s caution zone -- a **box** (`punch_outer_x` + `RETREAT_CAUTION_MARGIN` on X, `RETREAT_CAUTION_MARGIN_Y` on the lane axis), not an X-only band: an X-only zone made the AI back away from a committed enemy several lanes away that could never connect, and since `could_walk_to_near_enemy` skips proposing a candidate for that same enemy, it neither approached nor retreated; the Y margin stays below `execute.WALK_TO_ENEMY_LANE_SAFETY_Y` so that verb's own sidestep actually leaves the zone; `could_grab_enemy` needs both halves -- `reach.grab_would_connect` (possible) *and* a non-empty `reach.grab_reasons` (worth it) for the same pair -- plus `reach.is_incoming_melee` not holding for it, since walking into a committed attack is how the actor takes the hit instead of the hold; it declines while armed (every held weapon's own melee move beats a bare hold, and closing to contact spends that advantage) and while airborne (`$AAA0` needs both bodies within 8px of elevation); `could_hold_actions` targets the enemy actually in `CombatPhase.GRABBED` (falling back to the nearest) rather than whichever live enemy is nearest, since every hold move's emergency is gated on its target being GRABBED; hold always acts; `could_jump_attack` splits the grounded and airborne questions: from the ground it needs `reach.in_jump_attack_band` (and the "never launch into a committed attack" `reach.is_incoming_melee` gate), but **once airborne it is committed** and keeps producing a `JumpAttack` for the nearest *live* enemy -- on screen or not -- even when no band target remains. Depending on the band mid-flight was a measured failure: the target walks out of it, drifts a lane, or the flight carries the actor past it, and a tick with no verb reaches `press_no_button`, which *releases the directional hold* -- so the jump both lands without ever pressing B and (when it happens during the 5-frame crouch) goes straight up, since `$384E` reads no direction at launch. On the flight harness that was **211 of 587 launched jumps producing no kick at all**, now 0. `_could_melee_strike` refuses to fire while airborne for the mirror-image reason: mid-air B *is* the kick (`$3914`), so a `Punch` there outranked `JumpAttack` (20 vs 18) and pressed B straight through its state machine, firing the kick by accident of timing rather than by design. `could_jump_attack` also declines **while holding a weapon**, like every other `MeleeAttacks` sibling: an armed jump runs the ROM's *parallel* `$3C-$43` family, a different move with a different reach, whose kick edge nothing here models -- the band is the unarmed free-flight range and `execute`'s state machine names the unarmed states. Recorded live with a bat in hand: 246 of 4859 ticks sat in `$42`, the armed jump attack, while the pipeline believed it was performing an ordinary jump kick. Armed, the answer is the weapon's own swing, reached by walking in. The two thrown weapons are the one attack family whose reach question `decide` still answers itself, and it answers it at the **interception point** as well as the current one: `thrown_weapon_impact_point`/`thrown_weapon_would_connect` (shared with `priority._emergency_thrown_weapon`, so the verb that gets produced and the score it is ranked by cannot be measured about different instants) solve the flight at the weapon's own speed -- pepper's 6 px/frame lets a target walk a real distance mid-flight where a knife's 16 px/frame does not -- and take the union with the observed position, the same additive rule the bands follow; `_could_melee_strike` (the shared body behind `could_punch`/`could_swing_bat_or_pipe`/`could_stab_with_knife_or_bottle`/`could_spray_pepper`) additionally refuses a `Jack` currently juggling his axe/torch (`Jack.has_projectile`) as a target for all four -- closing in on him mid-juggle trades hits with the spinning weapon instead of landing cleanly, so only `could_jump_attack`'s kick (arrives from above) and `could_rear_attack`'s from-behind chord (he isn't juggling toward his own back) stay live answers on him until he lets the weapon go; `could_projectile_sidestep` produces one `ProjectileSidestep` per observed `Projectile` `reach.projectile_threatens` judges a threat (gated like `could_retreat_from_danger`: not mid-animation, not held by an enemy, not itself holding one) -- once Jack actually throws the axe/torch it is a fast in-lane `Projectile` with no melee answer at all, only getting out of its lane; a threat judgment is itself withheld for Jack's axe/torch specifically while he is still juggling it -- live-diagnosed regression: the weapon's own object exists (and is judged as a `Projectile`) for the whole juggle, not only once thrown, so its spin's instantaneous velocity can momentarily point straight at the actor and satisfy the same in-lane/heading/impact-window test a genuine throw would, making the AI sidestep an axe that never left Jack's hand. `reach.jack_still_juggling` (`Projectile.type_id == $28`, matched to a live `Jack` with `has_projectile` true within `JACK_JUGGLE_ATTACH_RADIUS`) filters those out, so only a released throw ever produces a sidestep |
| `jump_kick.py` | The unarmed jump kick's flight, update by update: `launch_arc` (a jump launched now, direction held, kick edge on a given free-flight update) and `airborne_arc` (the rest of a flight already in the air, from `world_z`/`vel_x`/`vel_z`/`ground_z`), each a list of `KickStep`s (frame from now, origin, the kick box out on that update); `landing_distance` (67.1/77.3/84.0, cached per character); `launch_hits`/`airborne_hits` against an enemy (`$AB88` strict) and `launch_hits_player`/`airborne_hits_player` against the other player (`$450C` inclusive, their body carried at `vel_x` plus `PARTNER_MARGIN_X`/`_Y`); `enemies_hit` (every body on the flight path); `swept_area`. Reproduces `tools/jump_kick_lab.py`'s lockstep traces bit for bit. Objects move at 30 Hz (`UPDATE_FRAMES = 2`): see **The jump kick, measured** |
| `twins.py` | Onihime and Yasha's ROM model: both twins' states 1 (approach and grab paths, every tactical), 2 (the flying kick), 3 (hitstun, knockdown flight and bounce) and 5 (getting up), the renderer's tail (`+$28`, the latched box ids, the frame timer reloading from `+$0C`), `$17AB8`'s integration, `boss_apply_pending_damage`; the actor walking (`$3614`'s speeds, `$43AA`'s word-only clamp) and throwing the rear attack from `CHORD_SCHEDULES` (per character, per update); `$AAA0`'s contact order in one object pass. `twin_from_token` / `actor_from_token` build it from the context; `check_recording` replays a `tools/twins_lab.py` recording |
| `twins_plan.py` | The plan against the twins: `choose_wall` (home is the edge away from the grab twin), the reactive `tail_action` (the chord when a twin's body will be in its box, the approach twin's lane held while the grab twin comes, a step off a flying kick's path, the wall faced), the programs played through both twins' AI under five timings (`SCENARIOS`), a chord pressed only when it strikes under all five, `PlanMemory`. See **Onihime and Yasha: the ROM model and the plan** |
| `mr_x.py` | Mr. X's ROM model (`$13F9A`'s bespoke-boss frame: states 0-9 and the released hold, 30 Hz), his gun's bullets (`$36`, set up a pass late below his slot), `$AAA0`'s contact order, the actor walking, punching and throwing the rear attack (`twins.CHORD_SCHEDULES`), and the blink (`+$4B` bit 1, `+$49`: no body). `check_recording` replays a `tools/mr_x_lab.py` recording |
| `garcia.py` | The office's type-`$22` Garcia (`$DD78`): the approach to a point 32 px short, the jab trigger, the four-stage punch refused off screen, `$DBCC`'s evade and legs, hitstun, a knockdown on a knockdown strike. `check_recording` checks it against a lab recording |
| `mr_x_plan.py` | The plan against Mr. X and his Garcias: the lookahead (`plan`: sticks, punches and rear attacks under five timings, the no-whiff rule, a grab scored by what lands on the holder before a knee is spent), the tail (keep away so he goes to the gun, walk into the gun and the retreat's first update, 17 lanes off the lunge, home on the right clamp), `hold_step` (knee, knee, release on his read), `garcia_threat` and `garcia_hold_step`. See **Mr. X: the ROM model and the plan** |
| `press.py` | Round 6's drop press (type `$42`, `sub_00007A6C`), from the disassembly: its states (1 armed, 2 shaking 11 updates, 3 falling, 4-8 down and back up), its trigger window `(x - $30, x + $60]` on either player's X, and the fall's two boxes (`$F4` ahead and below it, `$EA` behind and 12-48 lanes *above* it; 20 damage). `is_committed` (shaking, falling, or armed with a player in its window), `drop_zones` (the boxes plus a walk's margin -- a body test, as `$AB88`'s), `committed_zones` (what `navigation.press_obstacles` makes solid), `lands_in_reach` (a live press under where a jump or a crossover sets the actor down -- `navigation.jump_landing_is_safe` and `decide.could_hold_actions` refuse it) and `escape_step` (the direction out of a zone soonest, every one played at the character's walk with the ROM's refusals, for `execute._press_escape_mask`). See **Round 6: the factory floor** |
| `partner.py` | `do_not_harm_partner` -- the only stage of the loop that **removes** verbs, between `generate_verb_tokens` and `determine_priority_verb` (so a withdrawn verb is never ranked, never executed, and never listed as a pending candidate on the HUD). A no-op without a `Partner` token, which is every one-player session. Two halves. **Friendly fire**: `$4478 (resolve_player_vs_player_collision)` tests the attacker's attack box `+$64` against the *other player's* body box `+$70` exactly as `$450C` does for an enemy, whenever the attacker's `+$34` is nonzero (player-health-lives-and-combat.md), so the same `reach.punch_would_connect`/`in_rear_band`/`in_jump_attack_band` the rest of the pipeline uses are asked about the `Partner` rather than the geometry being measured a second time -- withdrawing `Punch`/`MeleeWeaponAttack`/`HitAntonioBoomerang` in the punch box, `RearAttack` in the chord's band, `OpenBreakable` **only** on the ticks `decide.in_smash_range` says it actually strikes (withdrawing the approach too would park the actor in front of a prop for as long as the partner stood near it), and `JumpAttack` **only** on the grounded launch (airborne is committed -- a tick with no verb releases the pad and loses the kick *and* the launch direction). Also withdrawn: the hold moves (`AttackHeldEnemy`/`Supplex`/`ThrowHeldEnemy`/`FlipHold`/`ReleaseToRegrab`) while `+$4C` names the partner -- walking into the other player takes the same hold `$3266` takes on an enemy, and those moves act on whatever body is in hand; `decide.could_hold_actions` offers `ReleasePartner` alone there -- and `CounterGrab` while the partner's own `+$4C` names the actor (the held player reads `HELD_BY_ENEMY`, and the counter throws the holder). `GrabEnemy` (presses nothing, so `+$34` stays zero), `CallPolice` (`$4478` returns outright while a police special is active), the hold moves on an *enemy* and the two attack-thrown weapons are deliberately never withdrawn -- the throw filter existed briefly (partner sharing the flight lane in front, nearer than the target) and was **removed on the user's call**: "it's almost impossible to hit the partner", so the lane test only cost real throws. **Item courtesy** (the user's rule, `item_is_the_partners`): `WalkToWeapon` unless the partner is strictly worse armed than the actor (`weapon_rank`; a tie, both unarmed included, is the actor's), `WalkToPickup` on a `HealthPickup` unless the actor is strictly the hurter, and on a `LifePickup` while the partner has fewer lives -- `SpecialPickup`/`ScorePickup` are claimed by neither; the same rule keeps a grounded B from picking such an item up (`$3136`, the partner pad's `_redirect_b_press`). **The partner's fight** (`PartnerFightTracker` → `PartnerFight`): the actor's attacks and walks at an enemy the partner is fighting or about to are withdrawn, bar self-defence (`reach.is_incoming_melee`) and a kick already airborne. `JumpAttack`'s friendly-fire test is the flight itself (`jump_kick.launch_hits_player`), not a band |
| `priority.py` | Emergency is computed per concrete `Verb` class from the `Information` tokens present in `Context` (never from the verb's type alone), including judgments answered directly against `reach.py`: `phases.is_punishable` decides the punishable tier for melee strikes and jump kicks, `reach.is_incoming_melee` gates `RetreatFromDanger` (its threat is over → 0), `reach.weapon_upgrade_rank` carries the rank `WalkToWeapon` scores with, `CallPolice` scores 88 below the panic threshold and nothing otherwise (a crowd and a live boss used to raise it too -- see **And without the police**), and any `Attack` on a **stunned** `Grunt` is capped by how much stun is left (`_stunned_target_ceiling`, applied branch-wide in `_emergency` as a ceiling that can only lower a score, reading the stunned `Grunt`'s own `stun_timer`): hitstun (<= `phases.HITSTUN_FRAMES`) caps at 21, just above a plain strike, so the ROM's 3-hit chain -- whose third hit is the knockdown -- is not abandoned for an equally punchable fresh enemy; anything longer is the `$A0` pepper stun and caps at 19, *below* a plain strike, since that body is parked for nearly three seconds. Both stay far below the `RearAttack` escape (55/60), which they beat at the punishable tier (60) before this, and above every `Walk` tier so the actor never walks off mid-stun. A `KNOCKDOWN` keeps 60 **while nothing is incoming**, since that window ends in a wake-up with invulnerability and really does have to be used now -- but while `reach.is_incoming_melee` holds for another enemy it is capped by `_EMERGENCY_ATTACK_PARKED_UNDER_THREAT` like a stun, and for a sharper version of the same reason: a body on the floor that is about to become invulnerable anyway is the worst thing on screen to trade a hit for. Live-reported against Souther -- with the claw committed two steps away, punching a knocked-down grunt scored 60 against the (since retired) claw dodge's 46 and won the tick. A third ceiling, `_EMERGENCY_ATTACK_PARKED_UNDER_THREAT` (10), applies to a stunned target while `reach.is_incoming_melee` holds for **another** enemy against the same actor (`_other_enemy_is_incoming`): the two above are both over `WalkToNearEnemy`'s realistic 11..14, so nothing ever interrupted a combo on a parked body and the AI took punches in the back -- user-reported, and exactly the situation the whole ceiling exists for ("a stunned enemy cannot act, cannot retaliate, and will still be standing there in a moment"). Sitting just under the walk's own base hands the tick to the turn-and-face while the threat is genuinely close (inside ~60px) and leaves the punish winning over a distant one. Measured over six 90s recordings against a running host: hits taken fell from 5.2 to 3.1 per minute at an unchanged attack rate (157 attacks started on each side) — one `_emergency_*` function per class (or a shared function for the four melee-strike siblings, or a `_held_enemy_emergency` factory for the five hold moves), dispatched by a `type(verb) → function` table; module constants are named contributions, not static outcomes. Scores: counter-grab 100 (Myself held by enemy), tech-recover 90 (Myself throw_tech_ready), call-police 88 (Myself health below a lives-aware threshold: POLICE_HEALTH_PERCENT_THRESHOLD, raised to POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE on the last life), rear 60/55 (target dangerous / not) only while `decide._rear_attack_is_warranted` -- boxed in between two enemies, or target inside the punch dead zone -- and 11/9 otherwise, since `$322A` costs up to 21 frames of startup and hits only by current position, so the `WalkToNearEnemy` turn-around (12..14 in the rear band) reaches the same enemy faster and outranks it; the chord stays produced on band membership alone and still wins when nothing better is on the table, grab-enemy 58 (reason `CLEAR_REAR` for the pair -- above every strike on an enemy that can still act and above the warranted chord against a *calm* rear enemy, below the 60 chord against one already committed) / 30 (`DEAD_ZONE`, an improvement on an ordinary fight rather than an escape from a bad one), 0 with no opportunity left, supplex 68 / throw-held 70 / flip 66 / release 50 (target `Enemy` actually `GRABBED`) / knee -- `_emergency_attack_held_enemy`, not the generic `_held_enemy_emergency` factory the other four hold moves share -- 67 while `actor.hold_ticks <= HOLD_KNEE_TICKS` (6, `observe.HoldTracker`'s cross-tick count of ticks since this actor's current hold began; no ROM escape counter is decoded, so this is a heuristic in the same category NoraAttackTracker already is) and `_EMERGENCY_DEFAULT` once past it, so a fresh hold mils a few knees (67 clears FlipHold's fixed 66) before FlipHold's own constant tier finishes it -- live-reported as the AI grabbing and flipping straight to Supplex with zero knees landed, since the old fixed 64 never cleared 66. Pinned as a sequence, not a single tick, by `tests/ai/test_stability.py`'s `HoldSequenceStabilityTests` (a lone-tick test cannot distinguish "grab then finish" from "grab, knee, knee, finish"), verified to reproduce the exact reported symptom (`['FlipHold', 'Supplex']`) against the old scoring, knife/pepper 25 down to a floor of 21 (target beyond melee, within throw range, 1 point per 15px closer), jump 28/24/18 (target punishable / a `Nora` not currently dangerous within `NORA_RECOVERY_PUNISH_TICKS` (10) of her own `ticks_since_last_attack` -- see `observe.NoraAttackTracker` -- / neither) and melee-strike (punch/swing/stab/spray, shared formula) 60/20 (target punishable / not), open-breakable 16 in smash range, else 14 down to a floor of 8 (1 point per 15px closer) -- the two tiers the former SmashBreakable/WalkToBreakable pair carried, so the merge changed no ranking, weapon 12+rank (14..17, every rank clearing walk-to-near-enemy's own floor of 8 outright rather than merely tying it, floor `Weapon` outranks the held one, better upgrade scoring higher), walk-to-near-enemy 14 down to a floor of 8 (1 point per 15px closer), retreat-from-danger 17 down to a floor of 15 (1 point per 25px closer -- above walk-to-near-enemy's base 14 so backing off an imminent threat outranks still approaching a different target, and below the *lowest* real attack tier, jump-attack's 18, so attacking always wins once actually possible; the earlier 30/20 band broke that invariant by beating punch 20, jump 18/28 and knife-throw 21..25. This ranking only ever comes up when `decide._retreat_is_worth_it` already let the verb be produced -- hurt or surrounded -- so it means "while conceding, backing off beats approaching", not "danger outranks engaging"), projectile-sidestep 45 down to a floor of 30 (1 point per 2 ticks-to-impact closer, `_emergency_projectile_sidestep` reusing `_distance_emergency` with a tick count standing in for its usual pixel distance -- above every ordinary approach/retreat tier so a confirmed incoming throw is answered before it lands, below a guaranteed punishable strike (60) and the rear/grab-clear-rear escapes (55/58/60), which stay right even with a projectile also in flight), engage-souther 62 (plus the boss raise, 76: above every strike and grab tier on anything else -- a stray grunt's `RearAttack` chord once locked the actor mid-engage -- and below `CounterGrab`/`TechRecover`; the hold family never coexists with it), engage-antonio the same 62 (76) for the same reasons, with `HitAntonioBoomerang` at a flat 78 above it, release-to-regrab 69 (the Souther hold loop's hand-back; his knees are exempt from the knee budget, since `souther.hold_step` counts them itself), release-partner 72 (only while `PlayableCharacter.is_holding_player` -- the body in hand is the other player; it tops the whole hold family so no move that would land on the partner can outrank it), stage-advance 1 (lowest of any verb that still scores -- must lose to every other live candidate, including a ScorePickup at 9; no *blocking* `Enemy` anywhere -- `_advance_blocking_enemies` excludes an off-screen straggler stuck at 0 health -- and no on-camera ahead `Breakable`, `_advance_blocking_breakables`; either gate scores the verb 0 so an injected candidate cannot outrank `OpenBreakable`), engagement verbs (walk-in / strike / grab / throw) add `_EMERGENCY_ARMED_TARGET` (7) when the target is an ordinary enemy holding a pickup weapon `$08-$0C` or a Jack still juggling his axe, and `_EMERGENCY_BOSS_TARGET` (14) when the target is a `Boss` -- sized to dominate WalkToNearEnemy's 6-point distance span so a far armed foe still beats a close unarmed one and a far boss still beats a close armed one; bosses are excepted from the armed raise, pickup tiers 50/15/12/11/9 (health-critical/health/life/special/score -- special and score both raised from their original 9/3 to clear walk-to-near-enemy's floor of 8, which they could not otherwise ever beat while any enemy existed anywhere on screen) — the max wins, with the `priority` field breaking ties; hold throws outrank knees. `could_*` generators never pre-select a single "best" candidate themselves (per AI.md's own principle) -- `_distance_emergency` is what lets several same-type candidates (near-enemy, thrown-weapon, breakable) rank against each other here instead; a first coarse-bucketed version was discarded after a live run showed clustered enemies tying every tick and the AI flip-flopping targets, so this scores near-continuously instead. **Remaining exact ties are broken deterministically and stably (`min(tied, key=repr)`), never at random.** `random.choice` was defensible per tick -- equally scored candidates really are equally good -- and disastrous over a run of them: the whole decision is remade every poll, so re-rolling turned "either target is fine" into swapping between them ~15 times a second, and since tied candidates are overwhelmingly the *same verb class aimed at different targets* (one per enemy, by the no-pre-selection rule above) whose targets lie in different directions, each swap re-aimed the D-pad. Near-continuous scoring made ties rarer but they stay routine at any distance-band floor and at every flat tier, so rarer was never enough on its own; `repr` gives a total order over frozen dataclasses that depends only on field values, so the same candidate set yields the same winner every tick. Covered by `tests/ai/test_stability.py`. `_emergency_thrown_weapon` scores the knife/pepper candidates by their **flight** distance through `decide.thrown_weapon_impact_point`, not by the current gap, so a target running away ranks below one standing still at the same instantaneous distance -- and never scores 0 for being outside a range `decide` never measured it against `_target_is_in_hand` is the gate every hold move scores through -- `CombatPhase.GRABBED`, or `reach.held_enemy` naming this target, which is the only thing that works for a boss; `_boss_attack_gate_is_live` drops a non-health item detour to 0 while Antonio's kick gate covers the actor |
| `gamepad.py` | `VirtualGamepad`/`SharedGamepadState` — the only code allowed to call `hold_buttons`/`press_buttons`/`release_buttons`; never `write_memory`/`write_value`. `VirtualGamepad` also owns the virtual left/right **axis** (`steer_x`, `AXIS_RAMP_TICKS`): callers no longer assert a D-pad direction directly for walking -- they request "more left"/"more right"/"center" every tick, and the axis only reports an edge (which `execute._hold_steered` then turns into an actual `LEFT_MASK`/`RIGHT_MASK` press) once that request has held for `AXIS_RAMP_TICKS` (3) consecutive ticks. Reversing all the way from one edge to the other therefore takes `2 * AXIS_RAMP_TICKS` ticks (it has to cross center), while a single contrary or neutral tick only steps the axis one place back rather than resetting it. This exists because immediately translating each tick's raw direction decision into a press is itself an oscillation source once `decide.py`'s target/side picks flip even occasionally (a target swap, a facing re-read, ordinary jitter): the axis is a deliberate low-pass filter in front of the D-pad, on top of (not a replacement for) `execute.py`'s existing deadbands/hysteresis, which still decide *what* direction is wanted each tick. `release()` resets the axis to 0 immediately, rather than letting it ramp down. Per-tick state, so it depends on one `VirtualGamepad` persisting across ticks the way `AgentLoop`/`app.py` already do; `tests/ai/test_stability.py`'s multi-tick harness has to build its `VirtualGamepad` once per run for the same reason (a fresh one every tick can never reach an edge) |
| `execute.py` | **The press escape** (`_press_escape_mask`, in `execute_tick` right after the pit escape): an actor whose body is in a committed press's drop zone walks out by `press.escape_step`'s direction -- the soonest way out at its own walk, with the lane band, the camera clamp, walls and pits refusing steps -- whatever verb won; grounded only, and not filtered by the partner pad (see **Round 6: the factory floor**). **The partner guard** (`_partner_safe_gamepad` / `_keep_off_partner`): while a `Partner` is on screen `execute_tick` hands the winning handler a wrapped pad that filters every D-pad-only mask *before* it reaches the link whenever `reach.walking_box_would_grab` says the walk would take hold of them -- drop the X step toward them, then the lane step toward their lane, then (still inside their contact band) take a lane step out of it, else hold nothing; skipped for the pit escape, masks carrying A/B/C, holds (`ReleasePartner`'s back press is the release), airborne ticks and `Dialog` verbs (see **Never hurt the partner**). **`WalkToAdvanceStage` hops when `plan_route` cannot walk the lookahead** (`hop_landing_x` + `_jump_toward`); if the gap is wider than the kick it stalls at the wall and never injects raw RIGHT/LEFT into the hole. `execute_tick`'s pit override does **not** run while airborne (lane-plane `pit_endangers` would freeze a hop mid-gap). **`WalkToNearEnemy` and `OpenBreakable` steer by planned route** (`_routed_mask` -> `navigation`): the whole path is rebuilt every tick and only its **first vector** used, because the world moves under a plan (enemies walk, crates break, phases flip) while a search of this playfield costs well under a millisecond against a 33 ms tick. An empty mask means either "arrived, stand still" or "boxed in", and only the second falls back to `_movement_mask`'s straight line. The enemy approach uses `enough_contact` (a floor -- a moving target is not worth perfecting an alignment for) and closes on X in the actor's *own* lane, converging only once `alongside`, because the enemy being approached is exempt from its own danger set; the crate approach uses `maximize_contact` (it does not move, so lining up square with its face is free) and keeps the crate in its own obstacle set, since dropping it routes the actor straight down through it. Facing a crate to hit it is `_face_prop_mask`, a raw sign test with the stage direction as the dead-centre tie-break, *not* `_face_toward_mask`: the hysteresis there exists because two bodies in melee sit on top of each other and jitter flips the sign every tick, which a target that cannot move does not do -- and answering 0 inside the band is a stall, measured live as 2,300 punches thrown into empty air over 76 seconds from exactly `DIRECTION_HYSTERESIS_X` away, facing the wrong way, on a prop the same run had already broken from 11px while facing it. Ties on which side to stand are still broken by the measured anchors (facing within `DIRECTION_HYSTERESIS_X`, the stage direction for a crate) -- a cost tie picked arbitrarily put the actor *past* a crate, where `could_open_breakable` stops calling it "ahead" and hands the tick to WalkToAdvanceStage, back into the crate. **`RetreatFromDanger`, `ProjectileSidestep`, `WalkToWeapon`/`WalkToPickup` and `WalkToAdvanceStage` route too**, each reusing `_routed_mask` with the destination logic in `_retreat_from_danger_target`/`_projectile_sidestep_target`/etc. left untouched -- only *how* the actor gets there changed, never *where* or *which side*. Three things differ per verb and are worth knowing before touching any of them: `RetreatFromDanger` and `ProjectileSidestep` treat **every** live enemy as danger (no target exemption -- fleeing is never trying to stand in anyone's reach, unlike an approach); `WalkToWeapon`/`WalkToPickup` use `nav.strike_goal(..., inner_dx=0)` rather than a `PointGoal` with a scalar tolerance, because a tolerance wide enough to satisfy `PICKUP_RANGE_X` let the goal read "reached" up to 4px short on the narrower `PICKUP_RANGE_Y`, freezing the actor there forever (`_routed_mask` never falls back once `goal.is_reached` is true) -- `strike_goal`'s region is built from the same asymmetric `abs(dx) <= stop_dx and abs(dy) <= lane_slack` sentence the arrival check already states, so the two cannot disagree; `WalkToAdvanceStage` routes **solids only, never danger** -- its goal is a vertical strip 40px ahead spanning the lane (Y is free -- a point on the actor's own Y that landed in or behind a pit made every covering cell sit in the hole, so best-effort walked straight in on a lane that had room above or below) that slides forward with the actor every tick rather than a real destination, and once a nearby dangerous enemy's own reach box is wide enough to contain that strip, `nav.plan_route`'s danger-aware pass can never "reach" it (arriving there means standing inside the thing being avoided) and silently falls through to the danger-blind solids-only pass, walking the actor straight at the enemy -- confirmed on a synthetic sweep before reverting to solids-only, which is exactly the obstacle set the pre-routing ad-hoc dodge already covered here. `WalkToAdvanceStage` also keeps its `routed_mask or mask` short-circuit (not a bitwise merge): the router's own vector wins whenever it produces one -- including a pure Y-only pit dodge with no lateral bit, which `PitDodgeSideStabilityTests` explicitly requires -- and `mask` (the raw `RIGHT_MASK`/`LEFT_MASK`) only substitutes on total router failure, preserving the one guarantee this verb cannot give up: the D-pad always carries `verb.direction`'s bit unless the router legitimately needed the tick for a pure dodge. `_find_safe_spot` (this file) gates its own candidates the same way -- see that function's own docstring above. Everything else still steers straight-line; that is future work. `execute_tick(verb, context, gamepad)` is the actual per-tick entry point `loop.py` calls -- it runs the pit-escape override (below) before choosing between `press_no_button` and `execute_verb`, so `execute_verb`'s own dispatch to controller input is reached only once that override declines. Every press-only handler goes through `_press`, which drops the sticky directional hold first -- `hold_buttons` latches until changed and `SharedGamepadState.press` re-arms it, so a walk tick followed by an attack tick used to leave the actor walking through its own strike (past the enemy and out of its punch band, or over the pickup it had just pressed B to collect); a walk handler whose actor/target vanished from the context releases instead of coasting on the stale hold; `_movement_mask` steers every walk verb around on-screen `Breakable`s and `Pit`s (falling in a pit costs a full life — player-health-lives-and-combat.md), but only *incidentally*, while some other walk verb's path happens to cross one. The `Breakable` dodge nudges `to_y` around the prop while still closing `to_x` in the same tick (a fixed point margin is enough to clear with a diagonal step); the `Pit` dodge cannot do that — a pit is a rectangle wide/tall enough that a diagonal command can still cut through the footprint before Y finishes moving, live-diagnosed — so instead it freezes `to_x` at the actor's own current X (no L/R bit at all) for as long as `from_y` still sits inside the pit's own band (`reach.PIT_AVOID_MARGIN` past its `lane_y`/height), and only lets X resume once `from_y` has actually cleared it, not merely been asked to; recomputed fresh every tick from the live position, so a drift back in self-corrects. The Y dodge target itself overshoots that same boundary by `PIT_DODGE_OVERSHOOT` rather than landing exactly on it -- live-diagnosed: aiming precisely at the boundary meant that once `from_y` drifted to within `MOVE_DEADBAND_Y` of it (well before actually crossing it, since both the deadband check and the "not cleared" check share that one point), the Y mask bits went quiet on a `from_y` the danger check still called "not cleared" while X stayed frozen -- a 0 mask, the actor frozen a few pixels short of escaping while `pit_endangers` still read true. **Which** side that Y target aims for is `_pit_dodge_target_y`, and it comes from the pit's own danger edges -- the nearer one that still clears inside the lane -- never from the lane midpoint. The dodge freezes X, so nothing else is moving to break a tie and an unstable side pick here is *permanent*, unlike the Breakable dodge above which keeps closing X and walks past the prop regardless. The old rule read `from_y < (lo + hi) / 2`, a midpoint that has nothing to do with the pit, routinely falls **inside** its danger band, and which the rule then steered the actor *toward* (upper half aimed below, lower half above) -- so the actor crossed it, the pick flipped, and it crossed back forever. Reproduced on the tick harness with a 96x40 pit at lane 40..80 (danger 32..88, midpoint 57, inside it): the actor stopped dead at the pit's edge alternating UP/DOWN between y=56 and y=60, X frozen at 394, never advancing the stage -- 120 of 288 swept pit/lane/direction configurations failed that way, now 0. The nearer danger edge is stable because it is *self-reinforcing*: its flip point is the band's own centre and the chosen direction always moves the actor **away** from it, so a pick cannot undo itself; it is also the shortest way out. A side only counts when its aim point survives the lane clamp still clear of the band, since otherwise `_clamp_target_y` drags it back inside and the mask collapses to 0 -- which for `state_machine_walk_to_advance_stage` is worse than a stall, its `or mask` fallback then commanding the raw lateral direction straight into the pit. The dodge's own "already clear on Y" test is **strict** (`<`/`>`) so it means exactly what `reach.pit_endangers`' inclusive band means: with `<=`/`>=` the two disagreed about the single boundary pixel, the escape stopped there, and `_pit_escape_mask` -- still reading `pit_endangers` as true -- shoved the actor laterally back off the pit's centre. `_pit_escape_mask`'s own last-resort fallback now derives its direction from that same `_pit_dodge_target_y` (it previously pushed *toward* the pit's centre, the exact opposite of its documented job). `execute_tick`'s own pit override (`_pit_escape_mask`, `reach.pit_endangers`) is the standalone reaction to the actor's own current position already sitting inside a pit's danger zone with no walk verb underway to steer it -- knocked there, or having simply drifted in — and takes over the controller before either `press_no_button` or `execute_verb` runs, regardless of which `Verb` (if any) won the tick; it hands `_movement_mask` a point on the far side of the pit along X purely to make that same dodge logic recognise and take over — the actual escape (freeze X, clear Y toward whichever half of the lane is nearer) is entirely `_movement_mask`'s own, so both paths agree by construction — and never returns 0 while `pit_endangers` holds regardless: on the rare chance `_movement_mask` still resolves to an empty mask, it falls back to a direct, deadband-free push away from the pit's own center on Y, since this is the one place in the pipeline "the actor believes it is in a pit" is known for certain, and refusing to hand back "do nothing" for that belief is a categorical guarantee, not just a consequence of the current margin/deadband numbers; `state_machine_engage_souther` holds `souther.plan_engage`'s mask directly (no axis ramp: the walk-in needs the walking box out every frame, and the plan never presses away from him); `state_machine_engage_antonio` holds `antonio.plan_engage`'s stick the same way and deliberately not through `_clamp_mask_to_camera` (see **Antonio: the ROM model and the plan**); `state_machine_release_to_regrab` presses *back* for `souther.release_press_frames(countdown)` frames and then holds toward him, so the re-grab walk starts on the release frame. `_walk_to_near_enemy_target` stops *inside* an enemy's own dead zone when it has one (`_dead_zone_stop_dx`, from the extracted `Enemy.min_reach`): some enemies cannot hit what is pressed against them, and today the ROM picks out exactly one -- Nora, whose whip (shape `$22`) covers 32..80px. Stopping at the actor's own punch edge instead, 46px for Axel, parks it squarely inside that band; measured against a real Nora in her attacking phase, the AI settled at 51px, spent 108 of 120 ticks inside her reach and threw **zero** attacks, which is what "the AI cannot deal with Noras" looks like in play. Aiming for `min_reach - REACH_SAFETY_MARGIN` instead (floored at the punch's own usable inner edge, since closer than that is the grab's business) takes it to the pocket she has no answer to: 9px, 22 of 120 ticks in the band, and it attacks throughout. Enemies with no dead zone -- every other type -- are unaffected. `_crossing_would_walk_into_the_swing` is the other half: with the approach aiming for the pocket, a live recording had Nora land **9 of her 10 hits at ~80px**, the far edge of her reach, catching the actor as it set off across the band. So the crossing waits out a live swing -- but only from outside her whole reach, only for an enemy that *has* a dead zone, and only while the actor is in the lane her attacks actually sweep (`reach.enemy_lane_covers`). Each of those three conditions was paid for: holding ground against an ordinary enemy is passivity (measured: -20% damage dealt, more taken), and gating on the X gap alone made the AI sit out swings it was never in the line of, costing half its stage progress (1487px against 2579-3674). `_walk_to_near_enemy_target`'s **lane aim never depends on the enemy's combat phase**, which is what stopped the approach darting up and down. It has three branches: arrived on X (`dx <= stop_dx`) converges onto the enemy's lane, the one place that aims at it, since the punch needs `dy` inside `PUNCH_RANGE_Y`; still approaching *and* standing inside a committed enemy's line (`dy < WALK_TO_ENEMY_LANE_SAFETY_Y`) aims at a **fixed** offset lane, so repeated ticks converge on one point instead of stepping away forever; otherwise it holds the actor's current lane. The old version converged onto the enemy's lane from any distance and sidestepped off it while the enemy was committed, so every crossing of `is_dangerous` -- every few ticks in a real fight -- flipped the lane aim by a full `2 * WALK_TO_ENEMY_LANE_SAFETY_Y` (56px) and the whole walk-in alternated UP/DOWN. Holding the lane serves the original "never walk down its line of attack" intent more directly than the sidestep did, by not converging onto that line in the first place; `_retreat_from_danger_target` steers to `_find_safe_spot`'s result when it finds one (computed lazily, right here, rather than for every actor every tick: it weighs the sidesteps against the straight retreat by clearance, lane/camera bounds and pits) and otherwise steps straight away from the target on X, holding the actor's current lane; `_projectile_sidestep_target` is a pure lateral step -- holds X at the actor's current position (the danger is entirely about sharing the projectile's Y column, not its X) and steps `PROJECTILE_SIDESTEP_DISTANCE` (40, comfortably past `inference.PROJECTILE_LANE_SLACK`'s 24) off whichever lane edge is nearer, the same "away from the nearer edge" pick `_movement_mask`'s own prop/pit dodges use -- deliberately not "away from the projectile's Y", since the actor already shares that Y (that's what made it a threat) and stepping away from it is not a stable direction, it would flip on ordinary walk jitter; `decide.in_smash_range` has an **inner** edge as well as an outer one (`punch_usable_inner_x`): a punch box starts 16px in front of Axel, so a prop the actor is standing on top of cannot be hit at all. Its outer edge is `breakable_smash_outer_x`, not `BREAKABLE_PUNCH_X` flat: that constant is an origin-to-origin distance, meaningful only while the prop is narrower than the punch reaches, and a round-6 prop's wall already reaches exactly 36px from its own origin -- so a flat 36 would call every position the ROM allows out of range and the verb would approach a prop it could never report arriving at, the same stall from the other side. The reach therefore grows with the wall and only with the wall (`SMASH_WALL_CLEARANCE_X` past it, clearing both `NAV_STEP` and `MOVE_DEADBAND_X` so a lattice or deadband stop just outside still counts as arrived); every prop whose wall is already inside `BREAKABLE_PUNCH_X` keeps exactly the reach it always had. Without it the executor pressed B instead of repositioning, and the attack animation then blocked every verb on the next tick -- which reaches `press_no_button`, releasing the controller and resetting the steering axis, so the actor never walked away either. Recorded live: **94 seconds** of a 7-minute run spent punching one type-$11 prop from 1px away, ~430 presses, ending in a lost life, plus 22 shorter stalls in the same run; afterwards the longest stall in a comparable run was 10.8s. `_walk_to_breakable_target` picks which side of a prop to stop on from the **stage's own progress direction** when the actor is standing essentially on it, not from `actor.facing_left`: a prop, unlike an enemy, never moves to break the symmetry, so reading the side off facing is a feedback loop -- press left, facing goes left, the stop point jumps to the far side, press right, and back. Measured live: 107 seconds of a 200s run at one prop with LEFT held on 244 ticks and RIGHT on 240, the virtual steering axis cancelling almost all of it (2242 ticks with nothing on the pad) while the actor never moved a pixel on X. The stage direction is fixed for the whole level, so it cannot oscillate, and it leaves the actor already lined up to carry on. Stage 7 (`AI.md`: no lateral progress required) reports `Stage.direction == "none"`, which used to fall through to that same `actor.facing_left` read and reproduce the identical 107s oscillation for every stage-7 breakable approached near dead-center on X; fixed by giving `"none"` the same fixed, non-input-derived side as `"right"` rather than a live facing compare -- stable matters more than which side, and either one reaches smash range equally well from directly on top of the prop. Smash range is only a *side* pocket (`decide.in_smash_range`: same lane, X offset); a straight line from above or below the crate to that pocket cuts through the solid, so while the actor still shares the prop's blocking X column (`_breakable_block_x`, read from `prop_solids` -- origin-space, which is exactly what the caller compares `actor.world_x` against) the Y target is held at the actor's own lane and only X walks out to the smash pocket. The next tick, now beside it, converges on Y. Without that around-path the actor pinned itself against the body and never arrived at a point that could punch -- reported from play as not knowing how to handle a breakable sitting on a different lane. `at_smash_x` is the escape for a stop point that still lands inside the column plus its slack: once X has arrived, Y must be allowed to move or the actor freezes off-lane. The stop point itself is clamped outside the prop's own wall (`BREAKABLE_WALL_GAP_X`), because `breakable_smash_outer_x` minus the deadband buffer alone lands *inside* it for every prop whose wall is wider than that, leaving the actor to arrive by bumping into it. The incidental prop dodge in `_movement_mask` aims at the wall's real edges too (`BREAKABLE_AVOID_Y` is now a clearance measured from them, not a margin around the origin): the ROM's boxes reach up to 28px behind an origin and only 4px in front, and stage 5 stacks two rows of props with a 16px corridor between them, so a symmetric margin aimed one prop's dodge straight into the next one down. `state_machine_open_breakable` also passes the target's slot as `_movement_mask(..., ignore_slots=...)` so the incidental prop dodge -- which treats any breakable on the walk's X span as an obstacle on the way to something else -- does not push Y off the smash lane while the walk-in closes X. `WalkToNearEnemy`/`RetreatFromDanger`/`ProjectileSidestep` share one `_walk_toward_target` lookup/guard/steer shell (actor+target lookup, release on either missing, then `_hold_steered`/`_movement_mask` on a `compute_target` callback) instead of repeating it three times; `WalkToWeapon`/`WalkToPickup` likewise share `_walk_to_item` (identical PICKUP_RANGE arrival test, differing only in the target token type) and `ThrowKnife`/`ThrowPepper` share `_throw_ranged_weapon` (differing only in the frame count). `state_machine_open_breakable` switches on that same `decide.in_smash_range` its emergency scores with, so the tier it won on and the action it takes can never describe different situations -- out of range it walks to `_walk_to_breakable_target`, which stops just inside smash range on whichever side the actor already occupies, since a Breakable is itself a solid obstacle and its exact center is unreachable; `state_machine_grab_enemy` is the one walk handler that aims at the target's *exact* position with no stop buffer (overlapping is the point) and never presses a button -- a strike would make `+$34` nonzero and turn the grab contact code into a plain hit -- and falls back to the facing direction when the movement deadband would otherwise release, because `$AAA0` first requires a non-empty attack box, i.e. a *walking* frame; `_hold_steered` is the one place every walk handler's final `gamepad.hold(mask)` goes through -- it reads the mask's L/R bits as this tick's axis request, replaces them with whatever `gamepad.steer_x` reports, and holds the result, so the deadband/hysteresis logic above is unchanged and only the very last step is smoothed. Deliberately **not** applied anywhere in `state_machine_jump_attack`, which holds directions through `gamepad.hold` directly: that handler is now a four-state machine over the ROM's own jump family (`JUMP_CROUCH_ACTIONS` / `JUMP_ATTACK_ACTIONS`) because the four states take four different inputs. **Grounded** presses C plus the travel direction; **crouch (`$10`)** holds the direction and *presses nothing*; **free flight (`$12`)** presses B alone and re-holds the direction; **already kicking (`$16`)** and **landing (`$14`)** press nothing, since the kick stays active until touchdown and a B read on the landing frame comes out as an ordinary punch aimed where the kick was heading -- a swing at empty air 100px from anything, recorded live. Each state is matched by its own action id rather than by `is_airborne`, which spans all of them. Two ROM facts force that shape, and both were measured as failures first: `$384E` reads the held direction once, at the end of the 5-frame crouch, and the virtual X axis needs `AXIS_RAMP_TICKS` (3 ticks ≈ 6 frames) to reach an edge while `_press` clears the hold before every press -- so anything routed through `_hold_steered` arrives too late and the *first* jump of an encounter goes straight up and kicks the air where it stood; and `$3914` needs a **rising edge** of B in free flight, which a B pressed during the crouch cannot give, since `_press` holds each button 4 frames while the AI re-decides every 2, leaving it still held when free flight begins -- nor to any `_press`-based facing bit (`_face_toward_mask` inside an attack press), which is a one-shot instant press, not a continuous walking hold. The grab walk-in and the two throws aim through `_aim_point` (`kinematics.target_at_impact` for that verb's own class) rather than at the raw token -- a walk-in is a pursuit and a thrown weapon has a real flight time, so both lead their target. The melee strike and the jump kick deliberately do **not**: facing is set by holding a direction, and turning toward where a body *will* be is how the actor swings past one standing next to it; their movement is already covered by the damaging span that keeps frame 0 in `kinematics.connect_frames`. A stationary target aims at itself either way |
| `loop.py` | `AgentLoop.tick` — gates on pause/non-gameplay/not-playable first, then runs the full pipeline (`do_not_harm_partner` between the verb generators and the ranking, so the HUD's pending list never shows a withdrawn verb either); the not-playable gate **does not** fire while the player's object is the type-`$0F` continue UI (`InContinueMenu` / `HandleContinueMenu` still have to answer Yes and type the initials). Fills a thread-safe `VerbState` (winning + every pending candidate) via `inform_hud` every tick and clears it on gate; hands the winning `Verb` (or `None`) to `execute.execute_tick` rather than choosing between `press_no_button`/`execute_verb` itself, and returns it for informational use only -- the actual controller output may differ if `execute_tick`'s pit override took over. Owns one `observe.NoraAttackTracker` per instance, passed into `generate_direct_observation_tokens` every tick -- the same per-player granularity as its own `VirtualGamepad` |

Verified button mapping for the original (non-altControls) scheme (see
`execute.py`'s module docstring): **Attack/Punch is physical B** (also
`MeleeWeaponAttack` via the shared
`state_machine_melee_strike`, `Supplex`'s finishing press, `ThrowKnife`/`ThrowPepper`,
and `CounterGrab`'s B edge),
**Jump is physical C** (`JumpAttack` launch, `Supplex` front→back crossover,
`CounterGrab` crossover, half of `RearAttack`, half of `TechRecover`'s C+Up chord), **Police special is physical
A** — the reverse of the naive "A=attack" assumption. **RearAttack** is the
simultaneous B+C chord (`$322A`).

Out of scope, per [`AI.md`](AI.md)'s own text: two-player coordination rules
beyond `partner.py`'s harm/courtesy filter above
("low priority... not an expected scenario") and the six-button
`--altControls` scheme ("planned for a future iteration").

**Antonio (`$56`, round 1)** is the first later boss with a plan of his own,
and everything the AI does against him is `ai/antonio.py` (the ROM model and
the measurements are in **Antonio: the ROM model and the plan** above):

- `could_engage_antonio` produces one `EngageAntonio` per live Antonio while
  the actor is free (not held, not holding, not airborne, not mid-animation),
  armed or not. Every generic verb aimed at a body stands down for him -- the
  melee strikes (a strike turns the grab contact into a hit, and a punch
  standing still is his widest kick window), the `RearAttack` chord,
  `GrabEnemy`, `WalkToNearEnemy`, `RetreatFromDanger` and the jump -- so the
  engage is the only verb aimed at him: 62, plus the boss raise, 76.
- `state_machine_engage_antonio` holds `antonio.plan_engage`'s stick
  directly: no axis ramp, and **not** through `_clamp_mask_to_camera` (the
  bug in the table above).
- In a hold on him `could_hold_actions` asks `antonio.hold_step` -- the same
  knee, knee, release as Souther's, from the holder's own bytes.
- `HitAntonioBoomerang` (a flat 78) still punches the boomerang out of the
  air, above the engage -- unarmed only: armed, B is a swing nothing here
  times, and that was the one boomerang hit measured; `phases.boss_phase` decodes his primary 1 as
  `CHARGE` only in tactical 8 (the dash) and `NORMAL` otherwise; item detours
  are refused while `antonio.kick_gate_open` covers the actor, the food while
  he lives, and the police is the panic button only.

**Souther (`$55`, round 2)** is the second, and everything the AI does against
him is `ai/souther.py`: pure functions of the context that `decide`,
`priority` and `execute` all call, so the three cannot disagree (the ROM model
and the measurements are in **Souther: the ROM model and the plan** above).

- `could_engage_souther` produces one `EngageSouther` per live, on-screen
  Souther while the actor is free (not held, not holding, not airborne, not
  mid-animation), armed or not. Every generic verb stands down for him --
  `Punch`/`MeleeWeaponAttack` (a strike turns the grab contact into a hit),
  `GrabEnemy`, `RearAttack`, `WalkToNearEnemy`, `RetreatFromDanger` -- so the
  engage is the only verb aimed at him. `state_machine_engage_souther` holds
  `souther.plan_engage`'s mask directly, without the axis ramp: the walk-in
  needs the walking box out every frame, and the plan never presses away from
  him.
- `could_hold_actions` asks `souther.hold_step` in a hold on him:
  `AttackHeldEnemy` for the first two knees of a chain (`PlayableCharacter.
  knees_in_chain`, from the player's `+$58` bit 6 and `+$61`),
  `ReleaseToRegrab` after them, `FlipHold` from a back hold while the one
  crossover is unspent (`crossover_spent`, `+$4B` bit 7), and a finisher only
  when it kills. `state_machine_release_to_regrab` presses back for
  `souther.release_press_frames(hold_release_countdown)` frames (`+$63`) and
  then holds toward him.
- `HealthPickup`/`LifePickup` are refused while he lives, the police is the
  panic button only (as everywhere; tests run with `--no-police`), and the
  weapon detour stays refused (`_a_weapon_would_disarm_the_plan`).
- **He counters jump attacks.** `$162A4 (souther_flag_target_jump_attack)`
  arms `+$79` from the *player's* own action state — `$16`/`$17`/`$42`/`$43`,
  the unarmed and armed jump attacks — and `$16234
  (souther_counter_jump_attack)` answers it, inside lane `$12` and X `$78`, by
  forcing him straight to primary `$02` with the `$98` claw already spawned,
  bypassing every distance band, the `$18` inner abort and the `+$66`/`+$77`
  gates. So `could_jump_attack` refuses the whole launch for that actor —
  **per actor, not per target**, since a hop aimed at an unrelated grunt in the
  box is countered identically — with the X half of the box widened by the
  character's free-flight reach, because `+$79` stays set for the whole kick
  action and he re-tests every frame of the flight. Only the launch is refused;
  an airborne actor is still committed.

  **Two gates the ROM has here are deliberately not reproduced, and both were
  paid for live** (reported as "a IA salta diretamente para as gadanhas dele").
  The first version gated on `$16234` being armed (primary `$01`, or `$02` with
  tactical `$00`) and on the `$12` lane window, and both let the jump through:

    - `$1619E`/`$161C6` skip `$16234` *because he is already attacking*, with
      the claw swing live (his own attack box; the `$98` object is only its
      visual). Not being countered is not the same as not being hit — that
      window is the most dangerous one, not the safe one. The only genuinely
      safe Souther is one who cannot act (`is_punishable`), and there the
      engage owns him anyway.
    - The lane window is real for the *flight* (a `JumpAttack` is horizontal, so
      it cannot leave its lane) but not for **him**: he closes lane at up to
      4px per update, erasing 18px in about nine of the flight's ~25 frames.
      Off-lane launches were countered on arrival.

  Reproduced before fixing by sweeping `generate_inference_tokens` →
  `generate_verb_tokens` → `determine_priority_verb` over every
  (primary, tactical) × distance × lane combination: airborne, `JumpAttack` won
  in **every** Souther state, because the (since retired) `could_dodge_souther_slash` was
  suppressed in flight. Keep that sweep in mind when touching this — the ground cases all
  looked correct.

**The hold ends when something is about to land, and the decision is made in
frames** (user: "a IA deve fazer supplex ou atirar o inimigo se ele estiver
para atacar na IA... calcula exatamente o tempo que leva a fazer cada
animação para prever o futuro e decide com base nisso"). Every hold move is
an animation lock that ignores fresh edges for its whole length, so starting
one is a commitment, and the lengths are now **measured** rather than
guessed.

`tools/hold_timing_diag.py` measures them: the AI plays until it has a real
hold, then the host goes into **lockstep**, the move is issued on frame 0 and
the player's own `+$30` is sampled every frame until it settles. Same method
as `ai-analysis/controls-and-input.md`'s "Measured chord timing" table.

| move | Axel | Adam | Blaze | ends in |
| --- | ---: | ---: | ---: | --- |
| knee (B) | 17 | 18 | 18 | back at the front hold |
| crossover (C) | 37 | 37 | 39 | back hold `$66` |
| suplex (B from `$66`) | 78 | 77 | 78 | free |
| throw (B+back) | 41 | 42 | 46 | free |

Two things follow directly, and are the whole rule:

- **finishing from a front hold costs 41-46 as a throw and ~115 as a
  flip-into-suplex.** So under a clock they are not alternatives: the throw is
  the only ending that fits, and it puts the body between the actor and
  whatever is arriving;
- **another knee costs 17-18 frames of being unable to answer anything.** If
  the incoming attack lands sooner than that, the knee is not started at all.

`reach.frames_until_melee_lands` is the clock. It is deliberately built out
of the same predicates `is_incoming_melee` already uses -- inside its own
reach is 0, a committed Souther dash divides the gap by `$161C6`'s 8px/frame,
anything else walks the enemy's own ROM velocity forward a frame at a time
until the caution box is satisfied -- so "is it coming" and "when" cannot
disagree. Past `CLOSING_ENEMY_THREAT_FRAMES` the answer is "not coming".

Do **not** re-derive these numbers from the animation data: an animation
record's `frames x per-frame delay` is not an action's length, because the
ROM's action handlers advance on specific animation frames (`$23D6`'s
`cmpi.b #$0004,$a(a0)` is the shape of it). That product over-states Axel's
chord by 2x and Blaze's by 3.5x against the manuscript's own measured table.

Do **not** distrust these numbers because they were taken under `--turbo 4`
either (user: "cuidado com a medição de frames no modo turbo"): a lockstep
step is exactly one game frame at `--turbo 1` and `--turbo 4` alike, verified
against `get_game_uptime_frames` at both. Turbo scales wall clock, so
anything timed by wall clock or by *agent ticks* is turbo-dependent -- which
is precisely why the knee budget stopped being a tick count.

That budget (`priority.HOLD_KNEE_TICKS`, 6) was the last thing here decided
in ticks, and the arithmetic was wrong in a way only the measurement shows: 6
ticks is ~12 frames against a knee's 17, so it expired before the first knee
could finish and the flip won the very next tick. It is
`kinematics.hold_knee_budget_frames` now -- three knees' worth -- compared
against `kinematics.frames_for_ticks(hold_ticks)`.

One consequence worth stating, because it looks like dead code and is not:
with the horizon at 12 frames and a knee at 17-18, **every threat the AI can
see at all is too soon to knee through**, so the "throw instead" branch is
the only one that ever fires while something is coming. The comparison is
still written against the frame counts rather than folded away to "any
threat": widen the horizon and a knee becomes available inside it again,
which is the right answer rather than a regression.
`test_stability.HoldUnderThreatStabilityTests` pins the relationship so
moving either number is visible.

Three scored round-2 fights after the change: 25%, 200%, 75% damage and 0, 1,
0 lives, against the four before it at 50/200/200/75% and 0/1/1/0 -- no
regression (and no claim of an improvement: that is the same noise floor),
with the boss dead in all three and the fastest round-2 kill recorded here,
24 s. Those fights only exercise the *unthreatened* path, though: round 2 is
1v1, and the only enemy on screen is the body already in the actor's hands,
which is excluded from its own clock.

**The threatened branch is measured separately, with the waves left alive**
(`tools/hold_threat_diag.py`, no `DebugScenario` sweep -- the point is a hold
taken in a crowd). Two runs, Axel 150 s and Blaze 220 s, 877 hold ticks and
66 decision ticks between them:

| | Axel | Blaze |
| --- | --- | --- |
| decisions with a threat on the clock | 5 | 3 |
| of those, `ThrowHeldEnemy` | **5** | **3** |
| of those, a knee started | **0** | **0** |
| grace observed, in frames | 5, 7, 7, 8, 12 | 7, 9, 11 |
| decisions with nothing coming | 27 (21 knees, 3 flips, 1 suplex, 2 rear-throws) | 31 (24 knees, 5 flips, 1 suplex, 1 rear-throw) |

Two things in that table are the actual confirmation. Every observed grace is
**5-12 frames**, all of them under the knee's 17-18 -- which is the horizon
argument above, seen in real play rather than derived. And the throw is not
merely *offered*: the action byte goes `$60` -> `$62` (Axel) / `$64` (Blaze)
and stays there ~24 ticks, which at ~2 frames a tick is the 41-46 frames the
lockstep harness measured for that same move.

The samples are small (8 threatened decisions) because a hold taken *while
something else is already committed* is not a common tick -- but the rule is
an invariant rather than a rate, and the invariant held on every one of them. The
threatened path is covered by `tests/ai/test_decide.py` and the sequence
tests only.

Mr. X (`$35`) and his Garcias have their plan (**Mr. X: the ROM model and the
plan**); Onihime/Yasha
(`$58`) have their plan (**Onihime and Yasha: the ROM model and the plan**); Bongo (`$57`) and Abadede (`$30`) have their plans
(**Bongo: the ROM model and the plan**, **Abadede: the ROM model and the
plan**).

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
   them (e.g. "Built by ``inference.check_for_surrounded`` when at least
   ``SURROUNDED_MIN_ENEMIES`` live enemies are inside the close box around
   the actor"). ``Surrounded`` and ``EnemyCluster`` are the only ``Inferred``
   tokens left — see [Judging without a cache](AI.md#judging-without-a-cache)
   in `AI.md` for why every other judgment this convention used to describe
   as a token is now a direct `reach.py`/`execute.py` function call instead,
   documented per its own function docstring rather than a token docstring,
   and for why these two earn the exception.
3. **Verb descendants add a second line describing when they are
   produced** — the ``could_*`` generator that creates them and the
   conditions under which it fires (e.g. "Produced by ``could_punch`` when
   an enemy sits within the actor's punch band").
4. **Verb descendants add a third line** describing how they can be
   ranked **in emergency**. This is *not* a static number: the static
   ``priority`` field only breaks ties between verbs that rank as
   equally emergent. Emergency is calculated from the *presence of other
   tokens*, from a `reach.py` predicate's result, or from either *under
   certain conditions*. Format:

   ```text
   Raises emergency: Surrounded×80, (reach.is_incoming_melee for this target)×17, (Weapon when distance is less than 32)×150
   ```

   ``Surrounded`` and ``EnemyCluster`` are the only `Information` tokens
   available to reference this way; every other condition is named as the
   `reach.py`/`phases.py` function (or `GrabReason` member returned by
   `reach.grab_reasons`) that answers it, e.g. ``reach.is_incoming_melee``,
   ``reach.projectile_threatens``, ``phases.is_punishable``,
   ``(reach.grab_reasons includes DEAD_ZONE)``.

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
the enemy-reach predicates (`tests/ai/test_reach.py`), the co-op courtesy
filter (`tests/ai/test_partner.py`, which builds the post-`generate_verb_
tokens` half of a context by hand -- the filter's contract is what it
removes, not how the verbs were produced),
`ObserverApp.stop()` client handoff, and the full `ai/` pipeline (tokens,
observation, inference, verbs, priority ranking, execution, the
pause/non-gameplay gate). The token-class tests live in
`tests/ai/tokens/` (`test_tokens.py`, `test_character.py`, `test_enemy.py`,
`test_essential.py`, `test_hazard_tokens.py`, `test_pickup_tokens.py`),
mirroring the `ai/` module split; pipeline tests stay in `tests/ai/`.
There is no live host requirement for the unit suite, and no pytest
requirement either: every module under `tests/` is plain `unittest`, so the
canonical command above must run clean on an interpreter that has never
installed the `dev` extra. `tests/ai/pathfind/`'s three modules were the one
exception until they were converted -- written for pytest, they failed to
*load* rather than to assert, and the suite reported `FAILED (errors=3)`
while 75 real tests silently never ran. Do not reintroduce a pytest-only
test file for that reason.

`tests/ai/test_stability.py` is the one **multi-tick** suite and exists for
a reason worth preserving: every other test checks a single tick in
isolation, but the pipeline is a closed loop -- what it commands this tick
becomes part of what it observes next tick (position, and through the held
D-pad, *facing*) -- so it can oscillate while every individual tick remains
defensible. Two such limit cycles shipped undetected and were only ever
visible live, as the AI rapidly reversing direction against a single enemy;
both are now pinned here by driving the real pipeline over a run of ticks,
feeding each tick's output back the way the game would, and asserting on the
resulting sequence. It also covers the two *multi-enemy* sources found the
same way -- the random tie-break in `determine_priority_verb`, and the lane
aim following the enemy's combat phase -- via `_run_multi`, which staggers
each enemy's phase cycle the way a real group behaves.

`JumpKickFlightTests` is the same idea applied to the one move that spans
several ROM *states* as well as several ticks. `_run_jump` drives a whole
jump through the unarmed family (`$10` crouch → `$12` free flight → `$16`
kick → `$14` land), feeding each tick's output back in, over an
`_EdgeTrackingClient` that expires timed presses so a **held** button and a
fresh **edge** are distinguishable -- which is the whole point, since
`$3914` accepts only an edge and only in free flight. It pins the two
reported failures: a B issued during the crouch is still held when flight
begins (no edge, no kick ever), and a verb that evaporates mid-flight
reaches `press_no_button`, which releases the hold and costs both the kick
and the launch direction `$384E` samples at the end of the crouch. Measured
before the fix: 211 of 587 launched jumps produced no kick at all. Add to this file,
rather than a single-tick test, when a change touches which verb or target
*owns* a situation across ticks; the useful assertions here are counts of
direction reversals and target switches, not any single tick's output.

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
