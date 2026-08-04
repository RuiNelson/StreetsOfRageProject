# Streets of Rage Autoplay — AI Specification

**Living document.** This file and the code under `src/sor_autoplay/agent/`
are the same contract. Every behaviour change must update both in the same
change set.

| If you…                                  | Then you must…                    |
| ---------------------------------------- | --------------------------------- |
| Edit a rule, threshold, or priority here | Implement it in the listed module |
| Change agent code behaviour              | Update the matching section here  |

Numbers, action bytes, and orderings below are **normative**. Soft language is
only for readability; when a number and a sentence conflict, the number wins.

Implementation root: `src/sor_autoplay/agent/`.

---

## 0. Glossary

| Term                  | Meaning                                                                        |
| --------------------- | ------------------------------------------------------------------------------ |
| **Decision**          | One call to `decide_actions` → one `AgentDecision` (P1/P2 masks + notes)       |
| **Seat**              | Player 1 or player 2 independently                                             |
| **map_x / map_y**     | Camera-relative X; lane Y from object `+$14` (world lane)                      |
| **world_x / world_y** | Absolute world position used for walk goals                                    |
| **action_base**       | Player `+$30` action byte with facing bit cleared (`value & 0xFE` where noted) |
| **action_state**      | Full player action byte; **bit 0 set = face left**                             |
| **Intent**            | High-level buttons for one decision before mask conversion                     |
| **Hard constraint**   | Boolean that forbids an action; fuzzy scores cannot override it                |
| **Commitment**        | At most one multi-frame skill owning a seat                                    |
| **Front hold**        | Grabbing a body while facing them (`action_base` often `$60`)                  |
| **Back hold**         | Grabbing a body from behind (`action_base` often `$66`) → suplex with **B**    |
| **Crossover**         | Hold + **C**: vault to the opposite side of the held body                      |
| **Suplex**            | Back hold + **B**: high-damage throw launch                                    |

Coordinate conventions:

- **Up** on D-pad = smaller lane Y (back of stage).
- **Down** = larger lane Y (front of stage).
- CRT width = **320**. Player walk band camera X = **[32, 288]**.
- Lane Y playable band: **[2, 112]** default; **[2, 160]** on level index 6.

---

## 1. Purpose and I/O contract

### 1.1 Role

Scripted, **deterministic** policy (not learned). Per enabled seat:

1. Read one coherent `GameSnapshot`.
2. Produce an `Intent` with a human-readable `note`.
3. Convert to a standard-control button mask.
4. Apply co-op attack gate, then send to the host.

### 1.2 Allowed actuators

| Physical           | Mask bit         | Role                                      |
| ------------------ | ---------------- | ----------------------------------------- |
| LEFT/RIGHT/UP/DOWN | D-pad            | Move                                      |
| **B**              | attack / confirm | Punch, pickup, knee, weapon, menu confirm |
| **C**              | jump             | Jump; hold-vault crossover                |
| **A**              | special          | Police call                               |
| **B+C**            | rear_attack      | Rear attack only (never jump-kick)        |

Hard bans:

- Never press **Start**.
- Never use host `--altControls` (scheme ≠ 0 / remapped A–Y).
- Never write play-state RAM to “win”; evaluation may seed RNG/frame only as
  **test setup** (`$FFFFFF40`, `$FFFFFB08`).

### 1.3 Jump-kick vs rear attack

| Chord                                                        | Meaning     |
| ------------------------------------------------------------ | ----------- |
| Same decision: **B and C**                                   | Rear attack |
| Decision N: **C only**; later decision: **B** in free-flight | Jump-kick   |

Jump-kick decisions are **solver-backed** (`agent/jump_kick.py`): a discrete
ROM physics model (5-frame crouch, character \(v_z\), air steer, lighter fall
gravity while kicking, per-character attack boxes) predicts:

- launch direction and facing;
- free-flight frame to press **B** (mapped onto agent decision delays);
- landing world X;
- which live enemies the kick AABB will hit (multi-enemy packs score higher).

Policy **must** use the predicted effect (hit count, total damage, ally clip,
landing) when choosing jump vs punch/grab — not FAQ distance bands alone.

### 1.4 Grab mechanics (ROM rules)

Players and enemies can grab each other (player↔enemy, player↔partner, enemy→player).
These are **ROM rules** the agent must respect; agent policy that uses them is in
§4.1–§4.3 and free-ladder combat (§9).

#### 1.4.1 How a seat starts a grab

1. Close on the target from the **front or the back**.
2. Do not get hit on the approach (a hit breaks the attempt).
3. Contact on the correct side latches a hold (agent: walk-in + **B** when
   grabbable / back-exposed — see free ladder and `grab_walk`).

#### 1.4.2 While this seat holds someone (enemy or partner)

| Input                            | Effect                                                                                                                                             |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C**                            | Vault over the held body; **stay grabbing**; finish on the **opposite side** (front hold ↔ back hold). May repeat any number of times (crossover). |
| **B**, front hold                | Knee / punch combo on the held body.                                                                                                               |
| **B**, back hold                 | **Suplex**: high damage and launches the body in a throw direction. Useful to clear or throw bodies into other enemies.                            |
| Walk **away** from the held body | Release the grab (no button required).                                                                                                             |

Suplex throw direction is controlled with the D-pad when throwing (agent hold
tree: §4.3.4).

#### 1.4.3 Partner hold (co-op)

A seat may grab the other player the same way as an enemy (including dealing
damage). Extra tool:

1. Grab partner.
2. **C** → vault to the opposite side (still holding).
3. **C** again (jump off / higher launch) then **B** in free-flight → **higher
   jump-kick** than a normal ground jump.

Co-op attack gate (§6) still forbids B/B+C that would hit a live partner when
the intent is hostile, not this intentional partner-boost sequence.

#### 1.4.4 When this seat is grabbed by an enemy (from behind)

ROM `ENEMY_HOLD` family (agent skill `EnemyGrabEscape`, §4.1):

| Input | Effect                                                                          |
| ----- | ------------------------------------------------------------------------------- |
| **C** | Attack an enemy in **front** of the seat, if the grabber does not punish first. |
| **B** | Throw the grabber **forward** (crowd tool).                                     |

Never press **B+C** on the same decision while escaping a hold (§4.1).

### 1.5 Session config (`AgentConfig`)

| Field                       | Default | Meaning                                            |
| --------------------------- | ------- | -------------------------------------------------- |
| `p1_enabled` / `p2_enabled` | false   | Seat driven by AI                                  |
| `hold_frames`               | 2       | Fallback press length on old hosts                 |
| `police_threshold`          | **4.5** | Min pressure score (0–10) for A, after eligibility |

Toggles: HUD, keys `1`/`2`, CLI `--agent-p1` / `--agent-p2`.

### 1.6 Session-level steady (no seat input)

Clear all tactical seat memory and emit mask `0` when any of:

| Condition                                    | Note        |
| -------------------------------------------- | ----------- |
| No seat enabled, or `not snapshot.connected` | —           |
| `snapshot.paused`                            | `steady`    |
| `snapshot.police_special_active`             | `steady`    |
| `snapshot.game_state ∉ {0x14, 0x16}`         | `menu idle` |

---

## 2. Pipeline (exact order)

Per enabled seat, one decision:

```text
1. build DecisionContext + classify PlayerMode
2. if DIALOG        → Mr. X NO path; return
3. if CONTINUE_UI   → name entry / continue Yes path; return
4. if NOT_PLAYABLE  → idle; return
5. try_start_mode_skill   # ENEMY_HELD → EnemyGrabEscape; HURT → clear+idle
6. ensure_perception()    # tactical graph + pressure (requires live entity)
7. try_crossover_suplex   # commitment; before police
8. police special?        # A if eligible + grounded-ready
9. try_hold_resolve       # HOLDING / GRAB_ANIM / weapon tree
10. 2P air assist?         # both agents + partner jump-family nearby → B+C
11. _decide_free          # free tactical ladder
12. coop.guard_attack_intent  # strip B/B+C if partner hit risk
13. mask_from_intent
```

`decide_actions` also decrements each seat’s `attack_cd` once per decision
after both seats are resolved.

### 2.1 Free ladder (`_decide_free`) — exact sub-order

Only reached when steps 2–9 did not return:

```text
A. if airborne action family → air branch; return
B. if reachable breakable with outgoing_damage > 0 → moving-prop branch; return
B2. if type-$42 press is crush threat or blocks progress corridor → detour then advance past housing; return
C. select_pickup + select_target + solve_goal (fight|loot|progress)
D. if LOOT wins and item set → loot walk/B; return
E. combat vs target (if any) → may return
F. static breakable (if any) → may return
G. progress_goal + walk  # press solids always in routing holes
```

### 2.2 Per-seat memory (`SeatMemory`)

| Field               | Role                              | Key constants                                                  |
| ------------------- | --------------------------------- | -------------------------------------------------------------- |
| `walk`              | Latched world goal + dir signs    | eps default 10×8; stuck 12 ticks / 2 px; goal refresh slack 14 |
| `nav`               | Hole detour, break side, unstuck  | stuck 8 ticks / 3 px; escape hold 18; ban TTL 48               |
| `goal`              | Last GoalKind + target_slot + age | +0.08 utility if retained                                      |
| `grab`              | Hold latch                        | HOLD_LATCH_TICKS=2; THROW_EVERY=3; retry 4 ticks               |
| `enemy_grab_escape` | Escape edge rate-limit            | retry 4 ticks                                                  |
| `planner`           | Crossover→suplex SM               | timeout 24; lost hold 2; max crossover attempts 2              |
| `commitment`        | Active skill name                 | at most one                                                    |
| `attack_cd`         | Suppress re-B                     | set 1–4 on attacks                                             |
| `last_note`         | HUD / trace                       | —                                                              |

`clear_tactical()` clears walk, planner, goal, nav, grab latches, commitment.

---

## 3. Mode classification (`classify_mode`)

First matching wins:

| Order | Mode           | Predicate                                          |
| ----- | -------------- | -------------------------------------------------- |
| 1     | `DIALOG`       | `is_mr_x_offer(snapshot)`                          |
| 2     | `CONTINUE_UI`  | `player_snap.object_type == $0F` (continue object) |
| 3     | `NOT_PLAYABLE` | `me is None` or `not player_snap.is_playable`      |
| 4     | `ENEMY_HELD`   | `action_base ∈ {0x78,0x7A,0x7C,0x7E}`              |
| 5     | `HURT`         | `me.is_hurt`                                       |
| 6     | `GRAB_ANIM`    | `action_base ∈ {0x62,0x64,0x68,0x6A,0x6C,0x6E}`    |
| 7     | `AIRBORNE`     | `action_base ∈ [0x10,0x17] ∪ [0x3C,0x42]`          |
| 8     | `HOLDING`      | grab context `holding` true (weapon or enemy grab) |
| 9     | `FREE`         | else                                               |

`STEADY` is session-level only (pause/police/menu), not seat classification.

Seat is driven when `is_playable` **or** `mode_active` **or**
`object_type == $0F`. After a full life stock is lost the ROM clears the
player-mode bit and converts the slot to type `$0F`, so continue/name-entry
input would otherwise be skipped.

### 3.1 Continue UI and high-score name entry (`CONTINUE_UI`)

When lives hit zero, `$2B48 (resolve_player_death)` sets the player object to
type `$0F`. If the score beats the current 10th-place entry, `object+$4B` bit7
is set and `$56E6 (high_score_name_entry_dispatcher)` runs first; otherwise the
normal continue table at `$5236` runs immediately.

Name-entry input is **not** the same as continue confirm. `$5218` remaps the
joypad into `object+$54/+55`, then `$57D2` reads the press-edge byte:

| `+$55` bit | Role on name entry |
| ---------- | ------------------ |
| bit 4 (attack / **B**) | **Backspace** (only if a letter is already placed) |
| bit 5 or 6 (jump **C** / special **A**) | **Place** current glyph |
| bits 2–3 (LEFT/RIGHT) | Cycle glyph index `0…$1A` (END is `$1A`) |
| bit 7 (Start) | Finish early (agent never presses Start) |

Three successful places advance the slot cursor to `$06` and finish; placing
while the glyph is END also finishes. Completing clears bit7 so the continue
table can run.

| Phase | ROM signal | Agent action | Note |
| ----- | ---------- | ------------ | ---- |
| Name entry | type `$0F`, `+$4B` bit7 set | **C** (`jump`) | Place glyph; **not** B (B is backspace and stalls at empty name) |
| Continue Yes/No, NO selected | type `$0F`, bit7 clear, `+$63 ≠ 0`, continues > 0 | **UP** | UP/DOWN toggle `+$63`; 0 = YES, nonzero = NO |
| Continue Yes/No, YES selected | type `$0F`, bit7 clear, `+$63 == 0`, continues > 0 | **B** (`confirm`) | Any face button works on the global press buffer; agent uses B |
| Out / no continues | continues ≤ 0 or `out_flag` set | idle | Game over / out for that seat |

Rules:

- Always accept continue (**YES**) while continues remain. Never select **NO**.
- Name glyphs are irrelevant; any three letters (default cursor) are fine.
- Name entry places with **C** (or **A**); never **B**.
- Continue confirm uses the standard **B** pulse path (fresh edge).
- Clear walk / planner / goal / commitment on entry (same as dialog / not-playable).
- Session-level `police_special_active` already idles all seats; the ROM also
  freezes type-`$0F` updates while a police special is running.

---

## 4. Skills (commitment)

Protocol: `valid` → keep ownership; `step` → Intent or None (done); `cancel` on fail.

Same-named active commitment is **continued**, not restarted, so latches survive.

### 4.1 EnemyGrabEscape (`enemy_grab_escape`)

Player is held by an enemy. ROM player-facing summary: §1.4.4.

**Valid when** `action_base ∈ ENEMY_HOLD_ACTIONS`.

ROM sequence (player `+$30` base):

| Action | Name          | Input                                            |
| ------ | ------------- | ------------------------------------------------ |
| `$78`  | acquire       | wait (empty)                                     |
| `$7A`  | held          | **C** if `+(+$58) bit7 clear`; **B** if bit7 set |
| `$7C`  | crossover     | wait                                             |
| `$7E`  | counter throw | wait                                             |

Rules:

- Never emit B+C on the same decision.
- Same command may not re-fire within **4** decision ticks.
- Clears walk, planner, goal memory, ordinary grab latch on step.

### 4.2 CrossoverSuplex (`crossover_suplex`)

Seat holds an enemy and needs back-side suplex (vault with **C**, then **B**).
ROM player-facing summary: §1.4.2. **Before police and hold resolve.**

Expert facts (`CombatExpert` + rule engine):

| Fact                    | Source                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `ENEMY_GRABBED`         | held enemy entity present                                                                                    |
| `FRONT_HOLD`            | we hold and `action_base == 0x60`                                                                            |
| `BACK_HOLD`             | we hold and `action_base == 0x66`                                                                            |
| `HOSTILE_BEHIND`        | nearest live enemy/boss behind facing, \|dx\|≤160, \|dy\|≤36, on-screen, not defeated/grabbed/death/scripted |
| `BACK_EXPOSED`          | inferred from `HOSTILE_BEHIND`                                                                               |
| `CROWD_PRESSURE`        | holding enemy and live enemy count ≥ **2**                                                                   |
| Goal `CROSSOVER_SUPLEX` | grabbed + front hold + (`BACK_EXPOSED` **or** `CROWD_PRESSURE`)                                              |
| Goal `SUPLEX`           | grabbed + back hold                                                                                          |

Crowd path uses vault→suplex so the throw launch helps clear multiple foes
(§1.4.2), not only back-shield.

Planner state machine (`AutoPlanner`):

| Phase              | Condition                                     | Emit                                 |
| ------------------ | --------------------------------------------- | ------------------------------------ |
| start CROSSOVER    | goal CROSSOVER_SUPLEX and action `$60`        | enter ISSUE_CROSSOVER                |
| ISSUE_CROSSOVER    | still `$60`                                   | **C**; go WAIT_CROSSOVER; attempts=1 |
| WAIT_CROSSOVER     | action in `{0x76,0x80}`                       | wait (`saw_crossover`)               |
| WAIT_CROSSOVER     | saw crossover and action `$66`                | **B**; go WAIT_SUPLEX_FINISH         |
| WAIT_CROSSOVER     | still `$60`, age≥2, attempts&lt;2             | **C** retry                          |
| WAIT_CROSSOVER     | still `$60`, attempts exhausted               | **B** fallback; reset plan           |
| WAIT_SUPLEX_FINISH | action `$68`                                  | wait until leave                     |
| any                | age &gt; **24** ticks                         | reset                                |
| any                | hold observation lost **2** consecutive ticks | reset                                |

### 4.3 HoldResolve (`hold_resolve`)

Ordinary hold tree while this seat holds a weapon or enemy/partner body
(§1.4.2–§1.4.3). Runs **after** police. Does not interrupt active crossover
commitment.

**Valid when** closed grab anim **or** grab context `holding`.

#### 4.3.1 Hold detection (`context_from_player`)

| Evidence                                                                                                                 | Result                                                               |
| ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| Reciprocal GRABBED enemy linked to this seat (`attacker_ptr`/`target_ptr` low word = seat object, or close grabbed body) | `enemy_grab=True`; `weapon=False` even if `+$60` looks like a weapon |
| **Boss** grabbee: later-boss primary `$06–$09`, **or** player hold-family (`$60/$66`/grab anim) + body overlap (≤48×20) | `enemy_grab=True` (bosses never use ordinary `$0500` GRABBED)        |
| Other player body within \|Δx\|≤48, \|Δy\|≤20 while grab-family, and **no** linked enemy                                 | `partner_grab=True`                                                  |
| `held_type` in `$08–$0C` and not linked / partner                                                                        | `weapon=True`                                                        |
| `held_type ≠ 0` and not weapon type and not partner                                                                      | `enemy_grab=True`                                                    |
| `+$4C` or post-pepper `+$5E` alone                                                                                       | **not** enemy/partner grab                                           |

`holding = weapon ∨ enemy_grab ∨ partner_grab`. Enemy link wins over partner.

Boss note: without the boss path above, a successful boss grab left the seat in
`$60`/`$66` with `holding=false`, so the knee/suplex tree never ran.

#### 4.3.2 Closed animations

`action_base ∈ {0x62,0x64,0x68,0x6A,0x6C,0x6E}`: empty Intent (lockout), even if pointers clear.

#### 4.3.3 Orphan contact

Not holding, but `action_base ∈ {0x28,0x4A,0x60,0x66}`: one **B** after 4-tick spacing (exact `$60` + stale contact → “release stale contact”). Live path: `$60 → $6A → $02`.

#### 4.3.4 Enemy hold tree

Input-ready hold actions only: `{0x28, 0x4A, 0x60, 0x66}`.

| Case                                                         | Intent              |
| ------------------------------------------------------------ | ------------------- |
| action `$66`                                                 | B (suplex)          |
| pulse % 3 == 0, **or** crowd ≥ 2, **or** ally in body bubble | B + throw direction |
| else                                                         | B alone (knee)      |

Throw direction:

1. Default away from facing (bit0 set → throw right = +X intent).
2. If crowd ≥ 3: prefer progress direction (+1 if progress right else −1).
3. If ally nearby in lane: flip to side **away** from ally.

Latch: proven hold stays active through **1** missing observation sample only (`HOLD_LATCH_TICKS=2` clear ticks). Longer latch caused empty knee loops.

#### 4.3.5 Partner hold tree

When `partner_grab` (not enemy):

| Case | Intent |
| ---- | ------ |
| Default | Walk **away** from partner body (release grab, §1.4.2). No knee/throw. |
| Both agents + live foe with 36≤\|Δx\|≤110, \|Δy\|≤28, or boost SM already active | **Partner boost** (§1.4.3) |

Partner boost state machine (`GrabMemory.partner_boost_phase`):

| Phase | Condition | Emit |
| ----- | --------- | ---- |
| crossover | front hold `$60` | **C** |
| await_back | vault `$76`/`$80` | wait |
| jump | back hold `$66` | **C** (jump off) |
| air_kick | airborne | **B** |

Co-op gate allows intents whose note starts with `partner boost` (intentional tool).

#### 4.3.6 Weapon tree (`agent/weapons.py` + `grabs._weapon_tree`)

ROM math (see `StreetsOfRageRecompilation/ai-analysis/weapons-range-and-damage.md`):

| Type | D | Kind | Connect when |
| ---: | ---: | --- | --- |
| Knife `$08` | **5** | **melee or throw** (same **B**) | ROM `$3084`: **stab `$46`** if front \|ΔX\|&lt;**144**; else **throw `$44`**. Policy: always stab in cone; throw only past cone if **one-shot** (`H≤5`) or not conserving; else walk into stab range |
| Bottle `$09` | **3** | dump only (not attack-thrown) | \|ΔY\|≤12 and \|ΔX\| ≤ 36 |
| Bat/pipe `$0A/$0B` | **4** | melee | \|ΔY\|≤12 and \|ΔX\| ≤ **36** (live origin reach) |
| Pepper `$0C` | **2** | attack throw + immobilize 160 f | \|ΔY\|≤12 and (\|ΔX\|≤36 or 24–100) |

Utility for pickup/upgrade::

```text
U = 0.45·(D/5) + 0.35·range_score + 0.20·control_score
  ± profile preferred/weak; clamp 01
```

Hits to kill: `ceil(H / D)`.

Weapon stand-off (normative; free combat + weapon tree share these):

| Type | approach_stand_dx | too_close_dx | Notes |
| ---: | ---: | ---: | --- |
| Knife `$08` | **96** | **52** | Deep in ROM `$90` (144) stab cone; never park at punch range |
| Pepper `$0C` | **72** | **32** | Mid throw corridor |
| Bat/pipe `$0A/$0B` | **30** | **18** | Just inside origin reach 36 |
| Bottle `$09` | **28** | **14** | Dump needs body proximity |

| Condition | Behaviour |
| --- | --- |
| Airborne | return None → free path owns jump family `$3C–$42` |
| Not input-ready (`not (0x02–0x0E or 0x30–0x3A)`) | hold still if already facing; else face only (**no** walk-in D-pad) |
| No foe, or foe `DANGEROUS` | return None → free path / family counters |
| \|ΔY\| &gt; 12 | return None |
| Same lane and \|ΔX\| &lt; too_close_dx | D-pad **away** (reopen stand-off); no B |
| Ally in attack bubble (throw range if knife/pepper) | return None |
| Bat/pipe and \|ΔX\| ≤ 36 and facing | **B only** (no D-pad toward foe) |
| **Knife** and too_close ≤ \|ΔX\| ≤ **144** and facing | **B melee/stab** (ROM `$46`; keeps knife); no walk-in D-pad |
| **Knife** and **144 &lt; \|ΔX\| ≤ 160**, one-shot, facing | **B throw** (ROM `$44`); no walk-in D-pad |
| **Knife** and **144 &lt; \|ΔX\| ≤ 160**, multi-hit foe | return None → free combat walks to knife stand (96), not punch range |
| Knife and facing wrong way | face only (no B) |
| Pepper in corridor and facing | **B only** (no walk-in D-pad) |
| Bottle and \|ΔX\| ≤ 36 | **B dump** (not a projectile throw); no walk-in D-pad |
| Knife beyond 160 / pepper beyond band | return None (walk to weapon stand via free combat) |

Armed free combat: `_stand_point` / `adjust_approach` use `approach_stand_dx` (not unarmed `approach_offset`); `grabbable=False` while holding a weapon (no body-grab walk-in).

---

## 5. Police special

Checked after crossover plan, before hold resolve.

### 5.1 Hard gates (all required)

1. `specials > 0`
2. `level_index < 7` (round 8 has no usable specials)
3. `player_can_start_ground_action(me)` → base in `[0x02,0x0E] ∪ [0x30,0x3A]`
4. **Eligible**:
   - `boss_present` (any reachable live boss), **or**
   - `enemy_count ≥ 4` (local threats), **or**
   - `health_percent ≤ 40` and `enemy_count > 0`
5. `pressure.score ≥ police_threshold` (default **4.5**)

On fire: clear walk + commitment; Intent `special=True`.

### 5.2 Pressure score (`compute_pressure`)

Nearby threat window: \|ΔX\| ≤ **200**, \|ΔY\| ≤ **48**, strict on-screen X, REACHABLE if graph present.

Fuzzy facts (Sugeno, value 0–1 then ×10 for score):

| Fact              | Membership                                               |
| ----------------- | -------------------------------------------------------- |
| `crowd`           | rising(enemy_count, 2 → 6)                               |
| `hunters`         | rising(hunters, 0.5 → 3)                                 |
| `active_attacks`  | rising(charging, 0 → 2)                                  |
| `boss`            | 1 if any reachable live boss else 0                      |
| `surrounded`      | 1 if enemies both left and right of player and count ≥ 3 |
| `low_health`      | falling(hp%, 30 → 75)                                    |
| `critical_health` | falling(hp%, 12 → 35)                                    |
| `any_threat`      | 1 if any near enemy/boss                                 |

Rules (name → consequent): baseline 0; crowd 0.85; hunters 0.60; active-attacks 0.60; boss 0.55; surrounded 0.80; critical-health∧any_threat 0.85; low-health∧any_threat 0.80; crowd∧low_health 1.0; attack∧low_health 1.0; boss∧low_health 0.95.

If any reachable live boss: **urgency forced to 1.0** (`score = 10`).

---

## 6. Co-op

### 6.1 Geometry constants

| Name                | Value | Use                              |
| ------------------- | ----- | -------------------------------- |
| `ALLY_LANE_HALF`    | 28    | Shared lane band                 |
| `ALLY_BODY_X`       | 24    | Any B damages regardless of face |
| `ALLY_MELEE_RANGE`  | 80    | Front punch / bat cone           |
| `ALLY_THROWN_RANGE` | 140   | Knife/bottle/pepper              |
| `ALLY_REAR_RANGE`   | 48    | B+C rear                         |
| `ALLY_CLEAR_LANE`   | 30    | Vertical step off partner        |

### 6.2 `attack_would_hit_ally`

True if partner is a live other player, \|ΔY\| ≤ lane_half, \|ΔX\| ≤ range, and:

- \|ΔX\| ≤ body X, **or**
- partner is on the attack side (front for punch; rear side for rear_attack).

### 6.3 Final gate `guard_attack_intent`

Runs on **every** seat after policy. Strips `attack` and `rear_attack` if risky.

Exceptions:

- Intent is confirm-only (menu).
- Intentional 2P air assist (both agents, B+C, partner in jump **action** family within ΔX≤28, ΔY≤14). **Never** use `world_z`.

### 6.4 Item fairness

Health/food (`should_take_health_pickup`):

- My HP ≥ **95%** → false.
- No partner HP → true.
- My HP ≤ **30%** → true.
- Partner HP + 8 &lt; my HP → false (leave it).
- else true.

Life/special: same with critical threshold **40%**.

Weapons: not fairness-gated (still upgrade + graph COLLECTIBLE rules).

### 6.5 Throw away from ally

If ally in lane (±36 Y) and \|ΔX\| ≤ 100: throw direction is sign opposite ally X.

---

## 7. Knowledge graph

Built once per seat after exclusive modes when `me` exists (`build_tactical_graph`).

### 7.1 Reachability (`entity_reachable`)

| Kind                   | X rule                                  | Y rule                                | Extra                               |
| ---------------------- | --------------------------------------- | ------------------------------------- | ----------------------------------- |
| pickup / weapon        | `map_x ∈ [16, 304]` (loot camera)       | lane in [LANE_Y_MIN, lane_max(level)] | —                                   |
| enemy / boss           | `map_x ∈ [0, 320]` (+64 right for boss) | same lane band                        | not defeated / not ignore-as-target |
| projectile / breakable | combat X band                           | lane band                             | —                                   |

Boss margin exists because Antonio can lock scroll near map X ≈ 328.

### 7.2 Relations (emit when true)

| Relation                | Definition                                                       |
| ----------------------- | ---------------------------------------------------------------- |
| `DEFEATED`              | `entity.is_defeated` (signed-negative health / death lifecycle)  |
| `REACHABLE`             | `entity_reachable`                                               |
| `NEAR_PLAYER`           | hypot(Δx,Δy) ≤ **160**                                           |
| `SAME_LANE`             | \|Δy\| ≤ **12**                                                  |
| `BEHIND_PLAYER`         | behind facing with \|Δx\| deadzone 8                             |
| `TARGETS_PLAYER`        | `targets_player == seat`                                         |
| `DANGEROUS`             | dangerous projectile **or** (non-projectile and phase dangerous) |
| `PUNISHABLE`            | phase punishable                                                 |
| `BLOCKS_PROGRESS`       | reachable enemy/boss, not GRABBED, (boss or dist≤220)            |
| `COLLECTIBLE`           | reachable free ground pickup/weapon (`is_free_ground_item`)      |
| `ARMED` / `THROWING`    | Jack type `$27` phases                                           |
| `GRABBABLE`             | enemy/boss, `is_enemy_grabbable`, not GRABBED                    |
| `ATTACHED` / `LAUNCHED` | Jack helper type `$28` states `$01` vs `$02–$04`                 |

If `DEFEATED`, do **not** also emit danger/punish/block/grab edges from stale family state.

### 7.3 Jack hard rules

| Phase                                | Punch               | Grab                       | Helper               |
| ------------------------------------ | ------------------- | -------------------------- | -------------------- |
| ARMED (`+$52` bit0, not state `$0E`) | allowed             | **forbidden**              | —                    |
| THROWING (primary `$0E`)             | allowed             | preferred (grab_bias 0.75) | about to launch      |
| UNARMED                              | allowed             | allowed (grab_bias 0.40)   | —                    |
| Helper `$01` ATTACHED                | not a combat target | —                          | not dangerous        |
| Helper `$02–$04` LAUNCHED            | dodge plan          | —                          | dangerous projectile |

---

## 8. Goal arbitration (`solve_goal`)

Candidates: FIGHT, LOOT, PROGRESS. Winner = max (utility, priority) where priority FIGHT=3, LOOT=2, PROGRESS=1.

### 8.1 FIGHT

Requires selected target REACHABLE.

```text
utility = min(1, target_utility + 0.25 * pressure_urgency)
if boss: utility = max(utility, 0.98)
if DANGEROUS: utility = max(utility, 0.94)
if TARGETS_PLAYER: utility = min(1, utility + 0.10)
```

Fallback if no candidates: FIGHT utility 0.50 (“blocker-without-target”).

### 8.2 LOOT

Requires item COLLECTIBLE and **not** hard threat:

- any BLOCKS_PROGRESS boss, **or**
- any DANGEROUS entity that is NEAR_PLAYER

```text
base = weapon 0.58 | life 0.92 | special 0.78 | health 0.35+0.60*falling(hp,30,90) | other 0.25
closeness = falling(dist, 8, 180)
safety = 1 - pressure_urgency
utility = 0.52*base + 0.28*closeness + 0.20*safety
```

### 8.3 PROGRESS

Only if no BLOCKS_PROGRESS entities. Fixed utility **0.30**.

### 8.4 Hysteresis

If candidate matches memory kind + target_slot: utility += **0.08** (capped 1.0). Memory age increments when retained.

### 8.5 Loot execution

Pickup geometry (safe inside ROM `$3136` box ±20/±16/±8):

| Axis | Agent safe box        |
| ---- | --------------------- |
| X    | \|Δworld_x\| ≤ **16** |
| Y    | \|Δworld_y\| ≤ **12** |
| Z    | \|Δworld_z\| ≤ **6**  |

- Inside box + ground-ready → B (unless ally body-blocks).
- Inside box not ready → wait.
- Else walk to item world position (eps 3×3).

Weapon upgrade only if `weapon_value(candidate) ≥ weapon_value(held) + 0.08`.

Base weapon values: knife 0.62, bottle 0.32, bat/pipe 0.82, pepper 0.52; +0.12 preferred; −0.20 weak.

---

## 9. Combat

### 9.1 Character profiles (normative numbers)

Character IDs: 0 Axel, 1 Adam, 2 Blaze.

| Field               | Axel  | Adam     | Blaze        |
| ------------------- | ----- | -------- | ------------ |
| strike_range        | 52    | 50       | 62           |
| lane_align          | 12    | 12       | 12           |
| jump_kick_min..max  | 28–50 | 30–72    | 28–78        |
| rear_range_min..max | 8–30  | 18–52    | 12–40        |
| jump_attack_bias    | 0.40  | 0.45     | 0.60         |
| rear_attack_bias    | 0.40  | 0.32     | 0.28         |
| combo_bias          | 0.55  | 0.40     | 0.18         |
| grab_bias           | 0.10  | 0.10     | 0.15         |
| grab_knees          | 0     | 0        | 0            |
| prefer_throw        | true  | true     | true         |
| prefer_vault        | false | true     | true         |
| approach_offset     | 46    | 44       | 56           |
| caution_range       | 48    | 52       | 48           |
| preferred_weapons   | all   | bat/pipe | bat/pipe     |
| weak_weapons        | ∅     | ∅        | knife/bottle |

Measured first-punch boxes ≈ 57 / 54 / 68; policy keeps 4–6 px inside.

### 9.2 Face-then-hit geometry

| Check              | Formula                                                                     |
| ------------------ | --------------------------------------------------------------------------- |
| Facing left        | `action_state & 1 ≠ 0`                                                      |
| Face deadzone      | \|Δmap_x\| ≤ **4** → facing already OK                                      |
| Lane hit           | \|Δmap_y\| ≤ **12**                                                         |
| Lane approach      | \|Δmap_y\| ≤ **16**                                                         |
| can_punch          | lane hit ∧ \|Δx\| ≤ strike_range ∧ (facing if required)                     |
| can_jump_kick      | Solver predicts primary hit (lane + arc + kick box); soft FAQ band is fallback only when no entity list is passed |
| jump_kick plan     | `solve_jump_kick` → hold_dir, kick_free_frame, landing_x, hits[], score; multi-hit (+1.35 per extra foe) drives attack_mix |
| can_rear_hit       | enemy behind ∧ rear_range_min ≤ \|Δx\| ≤ rear_range_max                     |
| behind             | same lane hit Y; 6 &lt; \|Δx\| ≤ max; on rear side of facing (±10 deadzone) |
| input-ready ground | base ∈ [0x02,0x0E] ∪ [0x30,0x3A]                                            |
| busy attacking     | base ∈ [0x18,0x1F] ∪ [0x20,0x27] ∪ ([0x44,0x4F] except 0x4A)                |
| combo queue        | base==0x18 ∧ `+(+$58) bit5` clear ∧ lane≤18 ∧ dx≤strike+20 ∧ facing         |

Stand-off for approach:

```text
if holding weapon type $08–$0C:
  dist = max(too_close_dx(held) + 4, approach_stand_dx(held))
  # knife 96, pepper 72, bat/pipe 30, bottle 28 — not unarmed punch range
else:
  dist = clamp(approach_offset, 22, strike_range - 2)
if low_hp: dist = max(dist, caution_range * 0.65)
stand_x = foe.world_x + side * dist   # side = away from foe
stand_y = foe.world_y                 # always match lane first
```

### 9.3 Target utility (`select_target`)

Only REACHABLE combatants; ignore non-dangerous Jack helpers; ordinary enemies dist≤220 (bosses unlimited in arena; projectiles ≤140).

```text
closeness = falling(dist, 20, 220|260 boss)
lane_access = falling(|dy|, 8, 72)
peril ∈ {0.15 baseline; 1.0 projectile/attacking; ≥0.82 targets-me; ≥0.70 boss; ≥0.62 contact band}
punish = 1 if punishable else 0
boss = 1 if boss else 0
forward = 1 if on progress side else 0
strike = 1 if can_punch(no face) else 0
priority = family membership (below)
utility = 0.24*closeness + 0.25*peril + 0.10*lane_access
        + 0.22*punish + 0.10*boss + 0.03*forward + 0.03*strike
        + 0.22*priority
floors: projectile ≥0.98; dangerous ≥0.82; boss ≥0.94
```

Family priority membership (equal geometry):

| Class      | Membership |
| ---------- | ---------- |
| projectile | 1.00       |
| boss       | 0.96       |
| Jack       | 0.90       |
| Nora       | 0.40       |
| Signal     | 0.50       |
| Haku-Ro    | 0.80       |
| Garcia     | 0.20       |
| other      | 0.28       |

Hysteresis: keep current target unless challenger utility ≥ current + **0.12**, or challenger is dangerous/projectile while current is not, or family priority jumps by ≥ **0.12**.

### 9.4 Family counter plans (biases)

| Family / type | range_scale | jump_bias | grab_bias | sidestep | no_jump | notes                 |
| ------------- | ----------- | --------- | --------- | -------- | ------- | --------------------- |
| Garcia        | 1.0         | 0         | 0.50      |          |         | pack                  |
| Signal        | 1.15        | **0.85**  | 0.00      | yes      |         | mid/far C→B           |
| Haku-Ro       | 1.1         | 0.50      | 0.50      |          |         | jump intercept        |
| Nora          | 0.75        | 0.50      | **0.85**  |          |         | grab; distrust downed |
| Jack          | 0.9         | 0.90      | phase     |          |         | see §7.3              |
| Abadede `$30` | 1.2         | 0         | 0.05      | yes      | yes     | charge                |
| Souther `$55` | 1.05        | 0         | 0.10      |          | yes     | grounded              |
| Antonio `$56` | 1.35        | 0         | 0.85      | yes      |         | midrange              |
| Bongo `$57`   | 1.25        | 0.90      | 0         | yes      | yes     | flame                 |
| Twins `$58`   | scene       | scene     | scene     | yes      | scene   | **§9.4b** full attack mix |
| Mr. X `$35`   | 1.0         | 0.50      | 0.50      | yes      |         | final                 |

Static fallback when no entity list is passed (unit helpers only): range 1.1,
jump 0, grab 0.10, sidestep, priority 2.6. Live combat always passes the world
entity list so §9.4b applies.

### 9.4b Scene composition — Onihime/Yasha (`agent/scene.py`)

Level-C layer: behaviour depends on the **set** of live type-`$58` bosses, not
only the selected target. Classification (`twin_composition`):

| Composition | Predicate | ROM meaning |
| ----------- | --------- | ----------- |
| `PAIR` | ≥ 2 living type-`$58` bosses | Linked pair (`+$5D` roles 1/2); split grab vs approach AI |
| `SURVIVOR` | exactly 1 living type-`$58` | Unpaired after `$17F9C` unlink (`+$5D=0`); can promote grab AI |
| `ABSENT` | 0 | No twin scene overlay |

Living = `kind==boss`, `type_id==$58`, not `is_defeated`.

**Pair doctrine:** finish **one** twin first. ROM has no enrage table — the
visible “phase 2” is simply the survivor without pair constraints, and it is
much easier. Combat **focus-fires the lowest-HP** twin with the **full attack
toolkit** (punch / jump-kick / grab / rear); partner jump/grab commits are
**evaded then returned to**, never used to retarget damage onto the partner.

#### Twin phase decode (`phases.boss_phase` type `$58`)

| Primary `+$30` | Tactical `+$67` | Phase | Meaning |
| --- | --- | --- | --- |
| `$02` | any | **ATTACKING** | Grab/throw commit `$15D0C` |
| `$01` | `$02` or `$03` | **ATTACKING** | Jump attack / leap-to-grab |
| `$01` | `$00` or `$01` | **NORMAL** | Idle / **chase walk** — free to strike |
| `$03`/`$04` | any | **RECOVERY** | Hit reaction — **punish** |
| `$0A` | any | RECOVERY | Police special |
| `$05` / ≥`$0C` | any | DEATH | |

**Critical:** chase (`+$67=$01`) must **not** be DANGEROUS. A prior generic
`t != 0 → ATTACKING` rule made the agent perpetual-evade and never attack.

#### ROM commit gates (`agent/twins.py`) — normative

The twins draw **no RNG**. Every attack is gated on player geometry and player
state, so the doctrine is **deny the gate**, not react to the animation. Gates
verified in `output/sor.asm`:

| Gate | ROM | Opens when |
| --- | --- | --- |
| Throw commit (`+$30` → `$02`) | `$159F8` | player available (`+$77 == 0`) **and** lane `+$52` ∈ [`$10`,`$20`) **and** X `+$50` < `$70` |
| Jump-attack arm | `$15A64` | X < `$60` — distance only, cannot be denied by lane |
| Leap-to-grab arm | `$15BE8` | player **staggered** (`+$77 != 0`) **and** X < `$90` |
| Grab jump-in | `$15C72` | X < `$40`, or `$40`–`$70` with player grounded, **closing and facing** |
| Grab finalize | `$15B2A` | contact, player available, at least one body grounded |

`$179F8` sets `+$77 = 1` for a player in hurt/knockdown `$5A`–`$5F` or holding
the `+$59`/`+$4B` bit-1 interaction flags. `+$50`/`+$52` are the ROM's own
absolute deltas, so the thresholds apply directly to world coordinates.

Grab mode is `+$7B` bit 1 (`is_grab_mode`), seeded from pair role `+$5D` and
mutable at runtime; `pair_role == 2` is only the fallback when `+$7B` reads
zero.

Four normative rules follow:

1. **Never stand in the throw band.** Lane separation `$10`–`$1F` from any live
   twin inside `$70` on X is the single worst position in the fight. Coplanar
   (< `$10`) is *safer* than a half-step sidestep **and** is punch range —
   fight coplanar. Any lane leave must clear `$20`; `LANE_SAFE_CLEARANCE` is
   **40** px, and a lane is only safe when it clears the band for **every**
   live twin (`safe_lane`). This supersedes the old 28/22 px sidesteps, which
   parked the player exactly inside the trigger.
2. **Bait the grab twin, never walk into it.** `$15C72` needs the player
   closing on it, so at `$40`–`$70` the agent holds the lane and lets it chase
   in — `+$67 = $01` carries no attack. Overridden when the body is punishable.
3. **Break contact while staggered.** `$15BE8` arms only against a hurt player,
   so a hurt seat retreats past `$90` from every grab-mode twin before
   re-engaging (`retreat_goal`).
4. **Gate denial outranks damage.** A landed throw costs ~40 % of the health
   bar; a delayed punch costs one decision. `BossTactic.mandatory` marks the
   band exit and the leap escape, and policy walks them **before**
   `_twin_attack_intent`.

#### Pair plan (both present)

| Field | Value | Rationale |
| ----- | ----- | --------- |
| range_scale | **1.0** | Stand inside measured punch boxes |
| jump_bias | **0.15** | Measured: 6 jump kicks vs twins = 0 damage |
| grab_bias | **0.35** | &lt;0.5 so punches win in-range; grabs via close walk / back-shield |
| rear_bias | **0.55** | Rear B+C when twin is behind |
| sidestep | **true** | Lane leave only on real commits |
| no_jump | **true** | Jumping surrenders the grounded punch and denies no gate |
| priority | 2.9 | Slightly above static twin |
| note | `twins pair — focus-fire full mix (punch/jump/grab/rear)` | |

Target focus-fire bonus (`twin_focus_bonus`, added to utility, cap **0.18**).
Uses `twin_effective_hp` (defeated/lethal → `0x7FFF`; `health is None` → base
`$20` from `$17EDC`):

| Condition | Δ utility |
| --------- | --------- |
| unique lowest HP among live twins | **+0.18** |
| tied for lowest HP (e.g. both full) | **+0.10** |
| higher HP than another live twin | **0** |

**No mode tie-break.** Preferring the grab twin at equal HP is ROM-correct in
theory (while linked it is the only grab source) but measured worse: it dragged
the target onto the far body while the near twin stood in punch range, and the
seat walked past it. `twins.scene` orders focus by HP, then **distance**, then
grab mode. `twin_pair_should_stick` likewise releases the lock for a challenger
inside `TWIN_REACHABLE_DX` (**56** px) when the current focus is more than
twice as far.

**Not scored:** DANGEROUS phase, `pair_role`, `targets_player`. Those used to
thrash between bodies; partner commits are movement-only (§ below).

Target hysteresis while **PAIR** (`twin_pair_should_stick` in `select_target`):

1. Preferred combat target is a living twin → **stick** unless the challenger
   twin has **strictly lower** effective HP.
2. Strictly lower-HP twin challenger → **force switch** (bypass `switch_margin`;
   boss utility floors would otherwise hide the gap).
3. Partner twin DANGEROUS does **not** override stickiness or inflate peril to
   full attack weight (pair-twin peril cap **0.40**; no `utility ≥ 0.82`
   danger floor on pair twins).
4. Non-projectile non-twin challengers do not steal focus while both twins live.
5. Projectiles still may interrupt (dodge).

Boss movement while **PAIR** (`bosses.tactical_move` / `_twin_pair_tactic`):

Threats only — and only **true** DANGEROUS commits (see phase table). Chase
walk is NORMAL and must not trigger pressure evade.

0. **Mandatory gate denial first** (`_twin_gate_tactic`, both compositions):
   staggered with a grab twin inside `$90` → `twins leap escape (staggered)`;
   otherwise standing in any live twin's armed throw band → `twins leave throw
   band`. Both set `mandatory=True` and run before free combat.
1. Bracket on X **and** still on shared depth → sidestep; note `twins pair surround`. Clear → **None**.
2. Nearby twin with real commit **and** on that depth (clearance **40**) → sidestep; note `twins pair pressure`. Clear → **None** (never hold-freeze).
3. Non-focus twin almost on top of player (ΔX≤**36**, ΔY≤**12**) → sidestep partner; note `twins pair isolate`.
4. Else **None**.

Every sidestep destination is filtered through `safe_lane`, so leaving one
twin's lane can never land inside the other's throw band. Souther keeps his own
**28** px lane break — the band is a type-`$58` mechanic.

Policy free combat (`_twin_attack_intent`) runs **after** mandatory gate denial
but **before** soft sidesteps, and emits the full mix with notes `twin punch` /
`twin jump` / `twin grab` / `twin rear` / `twin face` / `twin bait walk-in`.
Never reengage into a twin commit lane (`enemy_attack_committed` reengage is
disabled for type `$58`).

Stand point while PAIR: park on the side of the focus **opposite** the partner
(`_twin_partner_side`).

#### Survivor plan (only one remains)

| Field | Value | Rationale |
| ----- | ----- | --------- |
| range_scale | **1.0** | Punch range |
| jump_bias | **0.45** | Jump still useful solo |
| grab_bias | **0.55** | Body grab / hold tree preferred |
| rear_bias | **0.45** | |
| sidestep | **true** | Leave jump-grab lane on commit |
| no_jump | **false** | Full toolkit |
| priority | 2.6 | |
| note | `twin survivor — full pressure (grab/punch/jump)` | |

Boss movement while **SURVIVOR**: mandatory gate denial still applies — a lone
twin can promote to grab mode. Otherwise only when the focused twin is
DANGEROUS → evade attack lane at clearance **40**; note `twin survivor
jump/grab`. Else free combat owns the tree (grab_walk / punch via survivor plan).

#### Twin engagement rules (measured)

Two ordinary-enemy heuristics must **not** apply to a live twin pair, because a
second boss makes their preconditions permanently true:

1. **Back-shield grab rewrite** (`back_exposed` → `grab_bias 0.9`): the partner
   is always behind, so every in-range decision became a body-to-body grab walk
   that never attacked. Skipped for type `$58`.
2. **Jump-kick solver**: 6 kicks vs the twins landed 0 damage while the solver
   kept selecting them whenever both bodies lined up (`no_jump=true`).

The pair stand point also stops re-deciding its side once inside strike range —
recomputing "opposite the partner" every decision made the seat orbit the focus.

`--no-police-special` (`AgentConfig.allow_police_special`) suppresses every
special spend; it exists to isolate melee competence in measurement, since the
special's flat 10-per-boss otherwise masks whether melee lands at all.

#### Twin fight skill (`skills.TwinFightSkill`) — exclusive ownership

The free-decision ladder holds many independent movement controllers, and a
live pair triggers most of them simultaneously; measured live they preempted
each other every other decision (129 approaches vs 82 pressure sidesteps) and
the seat never closed to punch range. While any type-`$58` boss is alive the
twin skill owns the seat instead, in fixed order:

1. ROM gate denial (armed leap escape, throw-band exit)
2. back attack on a **grounded** twin inside the rear band
3. feign — hold the back turned to a twin closing from behind (`$15C72`)
4. punch any **grounded** twin in range (either body, not a fixed focus)
5. space out of a committed twin inside `$60` (`$15A64` cannot be denied)
6. converge on coplanar strike distance

It runs after the police special and before the hold tree, so a successful
grab still converts to knee/throw. Steering is direct D-pad, not the walk
latch, which other controllers refresh.

**Airborne test:** `$15ABA` compares live height `+$18` against the body's own
ground snapshot `+$4C` (exposed as `MapEntity.ground_z`). The player's
elevation is the wrong reference — a standing twin does not share the player's
plane. Attacking mid-arc whiffs.

**Timing:** decisions are four frames apart, so a range check describes where
a body already is, not where the punch lands. The skill therefore leads the
target by one decision (`_will_be_in_range`, velocity from the previous
observation, clamped to 26 px) and keeps the combo alive by pressing B during
attack action `$18` while `+$58` bit 5 is clear, rather than waiting for idle.

**Status: still not working.** Measured over 495 live decisions: 0 damage
dealt, 128 taken, 2 deaths, 3 ground attacks. The distribution is the real
finding — 152 decisions in hitstun, 94 in animation lockout, 123 approaching,
47 spacing, 23 feigning, 13 combo continuations. The seat is being hit far more
often than it acts, so timing refinements cannot show up yet.

Next attempt should invert the engagement trigger: approach **only** into a
ROM punish window (hit reaction `$03`/`$04`, the ~10-tick post-landing idle
after `$15ABA`, or a whiffed `$15D0C` throw whose `+$78` timeline is still
running) and otherwise hold outside `$60`, where `$15A64` cannot arm at all.
Approaching whenever geometry allows is what feeds the hitstun.

#### Twin evaluation metrics

`evaluation.py` measures the doctrine directly: `twin_throw_band_steps` and
`twin_leap_exposure_steps` count decisions spent inside an armed `$159F8` /
`$15BE8` window, and `twins_defeated` counts bodies actually finished. A
competent Round-5 episode enforces
`--max-twin-throw-band 0 --max-twin-leap-exposure 0 --min-twins-defeated 2`.

Module: `plan_for(entity, entities=…)` applies the overlay; `select_target` and approach pass the full entity tuple.

### 9.5 Attack mix (`attack_mix`) — deterministic

Returns exactly one of: `rear` | `jump` | `grab_walk` | `punch` | `wait`.

Order:

1. If `behind` → `rear`.
2. If not `lane_ok` → `wait`.
3. `grab_pressure = max(plan.grab_bias, 0.9 if back_exposed and grabbable else 0)`.
4. Phase knockdown/blocked/recovery: grab_walk if grab_pressure≥0.5; else **jump if solver hit_count≥2**; else punch if in_range∧facing; else wait.
5. Phase charge/attacking with sidestep and not in_range: jump if (jump_bias≥0.5 ∨ hit_count≥1) and band in {jump,approach} and can_jump and not no_jump; else wait.
6. **Multi-enemy solver jump**: can_jump ∧ ¬no_jump ∧ hit_count≥2 ∧ score≥1.5 ∧ grab_pressure&lt;0.7 ∧ band in {jump,approach,close} → `jump`.
7. **Solved single/pack jump**: can_jump ∧ hit_count≥1 ∧ score≥1.2 ∧ grab_pressure&lt;0.7 ∧ band in {jump,approach} ∧ (jump_bias≥0.20 ∨ hit_count≥2 ∨ crowd≥2) → `jump`.
8. Jump if can_jump ∧ ¬no_jump ∧ jump_bias≥0.25 ∧ band in {jump,approach} ∧ grab_pressure&lt;0.7.
9. grab_walk if grab_pressure≥0.5 ∧ grabbable ∧ phase in {normal,recovery,knockdown,unknown}.
10. If not in_range or not facing → `wait`.
11. Else `punch`.

Engagement band:

| Band           | Condition                                        |
| -------------- | ------------------------------------------------ |
| far / approach | off-lane rules first                             |
| close          | on-lane and \|Δx\| ≤ strike_range                |
| jump           | on-lane and jump_kick window                     |
| approach       | on-lane and beyond jump window up to jump_max+40 |
| far            | else                                             |

### 9.6 Free-combat branch order (when target set)

Normative order inside combat (after LOOT lost arbitration):

1. **Rear threat without grab shield**: if closest_behind within min(rear_max+4, 44) and no grabbable distinct front → rear B+C if can_rear_hit; else clear ally / walk.
2. Evaluate back_exposed via expert rear_threat_slot ≠ current foe; grabbable from graph/Jack rules.
3. Projectile / PROJECTILE plan → evade walk (±40 X, ±18 Y).
4. Target GRABBED and we are not grabbing → skip progress walk.
5. Busy attacking → combo queue B or face-hold.
6. **Back-shield grab**: if back_exposed ∧ grabbable: walk to body; B when \|Δx\|≤24 ∧ lane ∧ face ∧ cd=0 ∧ ground-ready.
7. Boss tactical move (Souther / twins pair|survivor, §9.4b) if any.
8. Signal sweep threat (type `$24`, state `$08` or `$0B`, \|Δx\|≤120, \|Δy\|≤20): C if ground-ready and jump_landing_safe; else brace.
9. enemy_attack_committed (dangerous ∧ \|Δx\|≤100):
   - off-lane boss → reengage boss lane;
   - off-lane ordinary within react half 36: escape lane ±24 Y or X retreat at lane edge [2,112];
   - on-lane within strike+24: interrupt B.
10. should_intercept_basic_enemy (types `$20–$23`, not punishable, within strike+24, lane): B or face.
11. punch geometry, wrong face → face tick (cd=1).
12. attack_mix → rear / grab_walk / jump (safe landing) / punch.
13. Else walk to stand point (grab body / jump mid / approach_offset), with sidestep evade when dangerous∧sidestep∧band≠close∧\|Δx\|≤100; lane-first when off-lane.

Attack cooldowns commonly set: punch/interrupt 3; rear 4; jump start 1; combo 2.

### 9.7 Signal sweep

Type `$24`, primary states `$08` (selector) and `$0B` (low slide, anim `$18`, vel ≈7 px/frame). React at 120 X, 20 Y. Unarmed free-flight later emits B; held weapon may jump via `$3C–$42` without airborne weapon B spam.

### 9.8 Airborne branch

| action_base   | Phase                      | B?                     |
| ------------- | -------------------------- | ---------------------- |
| `$10` / `$3C` | launch                     | no; hold solver dir    |
| `$12`         | free flight (attack ready) | **yes** at solved delay if ally-safe |
| `$16`         | air attack anim            | no (already attacking) |
| `$14` / `$40` | landing                    | no; clear jump plan    |
| other air     | hold face / solver dir     | no                     |

Also weapon jump family `$3C–$42`. When a jump was started from a
`JumpKickPlan`, seat memory keeps `hold_dir`, `kick_free_frame`, and expected
hit count: launch holds that direction; free flight waits `0` or `1` agent
decision (from the solved free-flight frame) before B. Aim face toward combat
or breakable target when no plan is armed.

### 9.9 Boss movement guards

| Boss          | Trigger                                                       | Response                                            |
| ------------- | ------------------------------------------------------------- | --------------------------------------------------- |
| Souther `$55` | dangerous phase                                               | leave attack lane by ≥28 Y or hold if already clear |
| Twins `$58`   | scene **PAIR** / **SURVIVOR** (normative detail §9.4b)        | pair: surround / pressure / isolate trees; survivor: only on DANGEROUS |

Twins nearby window: \|Δworld_x\| ≤ **150**, \|Δworld_y\| ≤ **36**. Default lane clearance **28** (pair isolate uses **24**).

### 9.10 Moving breakables (before arbiter)

REACHABLE breakable with `outgoing_damage > 0` (round-8 type `$45` ≈ 12 px per 4-frame decision):

- can_break + ground-ready + cd=0 → B smash.
- else if \|ΔX\| ≤ 220 and \|ΔY\| &lt; 28 → walk to safer lane Y (prefer max distance from prop lane within [14, camera_bottom−12]).
- else if \|ΔX\| ≤ 220 → hold safe lane (no chase).

### 9.10b Stage presses / hydraulic machines (before arbiter)

Round-6 type `$42` (ROM `$7A6C` family, label **Press**):

- **Avoid-only**: no player-hit destruction path; never smash/target as combat.
- Outgoing damage `$14`; vertical Z state machine `$40` ↔ `$A0`.
- ROM arming gate: player X in **[press_x − 48, press_x + 96]**.
- **Solid housing (path blocker)**: AABB X = **[press_x − 48, press_x + 64]**, lane Y = press_y ± **36**. Merged into routing holes so progress/combat walks **cannot path through** the machine frame.
- **Committed bypass** (`press_bypass_goal`), not leave-lane-only:
  1. `leave press` / `detour press` — pure Y off the solid/crush band (hold X while under).
  2. `advance past press` — once on a free lane, walk to solid far edge + **24** X on that lane.
- **Crush / stand-under**: \|ΔX\| ≤ **48** and \|ΔY\| ≤ **16** → step 1.
- **Same-lane approach**: \|ΔX\| ≤ **100** and \|ΔY\| ≤ **20** → step 1 then 2.
- **Corridor block**: press ahead within **160** X / **56** Y of the progress probe, or goal segment hits solid → same bypass.
- Safer lane = free edge outside solid ± clearance (prefer the side already occupied).
- Exclude type `$42` from `select_target` so weak projectile dodge does not thrash under the frame.

### 9.11 Static breakables (after combat)

Side-only approach (`navigation.breakable_side_approach`):

1. Horizontal stand-off first (never pure top/bottom smash).
2. Match lane.
3. Score both sides vs holes; latch solid side.
4. Punch when side_ready ∧ can_break ∧ facing; jump-break only side_ready ∧ jump window ∧ safe landing.

---

## 10. Navigation and stages

### 10.1 Walk latch (`WalkState`)

- Goals in **world** coordinates.
- Latch dir_x/dir_y ∈ {−1,0,+1} until arrived or **passed through** goal on both axes.
- Same-neighbourhood refresh (Δgoal ≤ **14** on both axes): update coords, **do not re-aim** (preserves unstuck dirs).
- Default arrival eps: 10×8; combat often 3×6; progress 24×8.
- Walk stuck: move &lt; 2 px for 12 ticks → perpendicular re-aim (goal unchanged).

### 10.2 Symbolic nav (`NavMemory`)

Phases: IDLE → DETOUR (vertical to latched safe lane) → ADVANCE (hold lane, clear hole on X) → ESCAPE (unstuck).

Hole rules (stage advice `avoid_holes`):

- Collision class 0 = pit; margins 12–16 px.
- Latch one detour lane; do not recompute side each poll.
- Emergency input rewrite **only** if already inside hole AABB (margin 0).
- `jump_landing_safe`: sample arc at t ∈ {0.35,0.55,0.75,0.95,1.0}; refuse pit landings.

Nav stuck (independent of walk): move &lt; **3** px for **8** polls → cardinal escapes, ban failed dirs (TTL 48), alternate detour/crate side.

### 10.3 Stage advice (`stage_advice`)

| level_index | Round | progress_right | horizontal_progress | avoid_holes | elevator | note                           |
| ----------- | ----- | -------------- | ------------------- | ----------- | -------- | ------------------------------ |
| 3           | 4     | true           | true                | **true**    | false    | holes                          |
| 5           | 6     | true           | true                | false       | false    | type-`$42` presses (solid nav) |
| 6           | 7     | true           | **false**           | false       | **true** | elevator; preferred lane `$50` |
| 7           | 8     | **false**      | true                | false       | false    | leftward                       |
| other       | —     | true           | true                | false*      | false    | default                        |

\* Default `avoid_holes` is false except stages that set it true above. Elevator: class-0 cells are **not** holes; clear walk latch so no inherited LEFT/RIGHT; no horizontal progress goals.

**Collision barriers (class ≥ 2):** always merged into routing solids (except elevator index 6). Live stage-6 factory: class **2** columns are the machine housing walls — they block RIGHT on the upper lanes while type-`$42` crushers sit on a different Y. The navigator detours to a free class-1 lane then advances past the barrier AABB. Type-`$42` AABBs remain a crush-zone supplement, not the path model.

Progress lead when empty: **±160** world X.

### 10.4 Mr. X dialog

`is_mr_x_offer` (all must hold for dialog seat mode):

1. **No live enemies/bosses** on the world map (defeated bodies ignored). After
   refuse, combat spawns can resume while `$FFDE00` is still set — threats
   force the agent out of `DIALOG` into free combat.
2. And either `$FFDE00 (mr_x_offer_flag)` **or** (level 7 ∧ clock stopped ∧
   timer valid).

Choice UI: object `+$59` bit4 set while the offer control table locks / enables
choice; bit3 = side (**1 = NO**, 0 = YES). Do **not** idle when bit4 is clear —
that stuck the agent on `mr.x wait` between phases.

ROM `$120EC (poll_mr_x_offer_player_choice_input)` reads **held** `object+$54`
(then clears that word). Direction is applied **before** face confirm:

| Held input | Effect |
| ---------- | ------ |
| **UP** (bit 0) | Clear bit3 → YES |
| **DOWN** (bit 1) | Set bit3 → NO |
| Face bits `$70` (A/B/C after remap) | Register choice; bit5 latches “answered” |

Policy: every decision while the offer is live, hold **DOWN + A** (note
`mr.x refuse NO (DOWN+A)`). Same-frame DOWN+A is safe (NO is set before
confirm). Never hold UP. ROM ignores the pads outside choice-enabled states.

---

## 11. Input delivery (host)

| Intent content | Transport                                                                             |
| -------------- | ------------------------------------------------------------------------------------- |
| D-pad only     | sticky `hold_buttons` (0x14) between polls                                            |
| Any A/B/C      | VSync `press_buttons` for edge (≥3 frames in evaluator lockstep), then re-latch D-pad |
| Old host       | press-only fallback (walk taps)                                                       |

Agents share the remote poll connection with RAM reads. Notes do not select transport.

Observer without agents: wall-clock poll default **33 ms** (not VSync-locked).

---

## 12. Evaluation contract (`evaluation.py`)

| Item         | Value                                                                                                                                                 |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Policy type  | `GameSnapshot → AgentDecision`                                                                                                                        |
| Step         | exactly **4** emulated frames per decision                                                                                                            |
| Face buttons | pulse **3** frames, release **1**                                                                                                                     |
| Traces       | JSONL outside repo                                                                                                                                    |
| Setup        | `--restart-character` / `--restart-level` on same connection; seed RNG long `$FFFFFF40` and phase `$FFFFFB08` after lockstep; report work-RAM SHA-256 |

First-class metrics (enforce at 0 / scenario mins as appropriate): damage events, failed pickups, failed ground-attack starts, weapon air attacks, missed back exposures, invalid grab-animation attacks, enemy-grab escape miss, defeated-enemy attack/pursuit, unreachable stalls, loot under threat, boss progress, boss stalls (after 8 consecutive input-ready “guard lane”), wasteful specials, missed boss specials, elevator horizontal progress, missed moving breakables, crossover/suplex counters, etc.

---

## 13. Module ownership

| Spec section  | Code                                                                   |
| ------------- | ---------------------------------------------------------------------- |
| §1–2 pipeline | `policy.py`, `context.py`, `controls.py`                               |
| §3 modes      | `context.py`                                                           |
| §4 skills     | `skills.py`, `grabs.py`, `expert.py`, `autoplanner.py`, `inference.py` |
| §5 police     | `pressure.py`, `fuzzy.py`                                              |
| §6 co-op      | `coop.py`                                                              |
| §7 graph      | `knowledge.py`, `phases.py`, `world_map.py`                            |
| §8 arbiter    | `arbiter.py`                                                           |
| §9 combat     | `combat.py`, `enemies.py`, `characters.py`, `bosses.py`, `scene.py`    |
| §10 nav/stage | `navigation.py`, `walk.py`, `stage.py`, `hazards.py`                   |
| §11 I/O       | `app.py` + `megadrive_remote`                                          |
| §12 eval      | `evaluation.py`, `scenarios.py`                                        |

---

## 14. Non-negotiable principles

1. Hard ROM guards beat fuzzy scores.
2. Deterministic attack mix (no tick RNG).
3. Face-then-hit; lane before X; no reverse punches.
4. Jump-kick is C then later B; B+C is rear only.
5. Back security (crossover-suplex / grab shield) before greedy front DPS.
6. Final co-op gate on every seat.
7. Latched nav/walk — no per-poll detour thrash.
8. Explainable notes and retained fired-rule traces.
9. Future learned policies may propose weights/candidates only inside this feasibility shell.
10. This file and the code must describe the same behaviour after every change.

---

## 15. Out of scope

- `--altControls`
- Full TAS animation tables
- Neural training (evaluator is the boundary)
- Attract-mode heuristics beyond current game_state gates

---

*Normative AI specification for `src/sor_autoplay/agent/`.*
