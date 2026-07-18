# Streets of Rage Sound System

**Manuscript:** reverse-engineering notes from the recompilation project  
**Scope:** music, sound effects (SFX), and PCM/DAC playback in *Streets of Rage* (Mega Drive)  
**Primary sources:** `StreetsOfRageRecompilation/output/sor.asm`, `code-analysis/`, ROM `rom/SOR.bin`, and `MegaDriveEnvironment` host emulation  

This document describes how the game produces audio: who owns the sequencer, how the 68000 and Z80 cooperate, how game code requests sounds, and how channel data is stored and advanced each frame.

---

## 1. Executive summary

*Streets of Rage* does **not** run a classic Z80-only SMPS-style music driver for the whole mix. The division of labour is:

| CPU | Role |
|-----|------|
| **68000** | Full music + SFX sequencer; writes **YM2612 (FM)** and **SN76489 (PSG)** registers directly |
| **Z80** | **DAC / PCM only** — streams 8-bit samples through YM2612 channel 6 (DAC path) |

Game logic never programs the chips itself for ordinary events. It posts **sound IDs** into a small work-RAM queue. Once per **VBlank**, a 68000 sound engine drains that queue, updates channel state machines, and talks to hardware (and to the Z80 mailbox for PCM).

```
  Gameplay / UI / level flow
           │
           │  write sound ID → $FFF00A..$FFF00C  (3-slot queue)
           │  optional: stop/fade → $FFF002
           ▼
  ┌────────────────────────────────────────┐
  │  68000 sound engine  sub_$72914        │
  │  (called from VBlank handler $19D16)   │
  │                                        │
  │  • command dispatch + priority         │
  │  • FM / PSG / DAC channel tick         │
  │  • YM2612 + PSG port writes            │
  └──────────────┬─────────────────────────┘
                 │
     FM / PSG ───┼── BUSREQ + $A0400x / $C00011
                 │
     PCM ────────┼── write Z80 RAM $1FFF (command)
                 ▼
  ┌────────────────────────────────────────┐
  │  Z80 DAC driver (Kosinski @ ROM $795A2)│
  │  • ROM bank via $A06000                │
  │  • YM2612 DAC enable $2B / sample data │
  └────────────────────────────────────────┘
```

---

## 2. Hardware map (Mega Drive)

Relevant I/O as labelled in `code-analysis/addresses.csv`:

| Address | Name | Notes |
|---------|------|--------|
| `$A04000`–`$A04003` | YM2612 addr/data (parts 0 and 1) | FM + DAC control |
| `$A06000` | Z80 bank register | 9-bit bank into 68000 address space |
| `$A07F11` | PSG via Z80 window | rarely used by this driver path |
| `$A11100` | Z80 BUSREQ | `$0100` = request bus |
| `$A11200` | Z80 RESET | `$0000` held in reset; `$0100` run |
| `$A00000`–`$A01FFF` | Z80 RAM (8 KiB) | driver image + mailboxes |
| `$C00011` (+ mirrors) | SN76489 PSG | tone / noise / volume |

Work-RAM audio control (game side):

| Address | Name | Notes |
|---------|------|--------|
| `$FFF002` | `stop_music` | fade-out / stop BGM |
| `$FFF00A` | `play_se` | first slot of a **3-byte** command queue (`$FFF00A`–`$FFF00C`) |

---

## 3. Bootstrapping the Z80 DAC driver

### 3.1 Loader: `sub_0001061C` ($1061C)

Called from early init / level start paths (including `init_levelstart` at $106EA). Sequence:

1. Assert **Z80 RESET** and **BUSREQ**; spin until the bus is granted.
2. Kosinski-decompress the blob at **ROM `$795A2`** into work RAM **`$FF7000`** (`kosinskidec` at $85A2).
3. Copy **`$1EC7` bytes** (`move.w #$1EC6,d2` + `dbf`) from `$FF7000` into **Z80 RAM `$0000`**.
4. Seed the sample bank pointer at Z80 **`$1FF8`–`$1FFB`** with `00 80 07 80`.
5. Pulse RESET low then high; release BUSREQ so the Z80 begins at `$0000`.

### 3.2 Z80 driver behaviour (mailbox DAC player)

After decompression, the Z80 program is a compact PCM player, not a multi-channel sequencer. Observed behaviour from the decompressed image and 68000 call sites:

| Z80 address | Role |
|-------------|------|
| `$1FF8`–`$1FFB` | Sample base / bank setup written by the 68000 at load |
| `$1FF6` | Status / busy-related flag polled by the 68000 DAC channel |
| `$1FFD` bit 7 | Busy lock while the Z80 owns YM2612 DAC setup/stream |
| `$1FFF` | **Command byte** posted by the 68000 |

Startup sketch (decompressed driver):

- `LD SP,$1FF4`
- Clear busy at `$1FFD`
- Program the bank register at `$6000` from `$1FF8`–`$1FFB`
- Main loop: read `$1FFF`
  - if command **&lt; `$81`**: idle / non-play path
  - if command **≥ `$81`**: play a sample:
    - set busy `$1FFD = $80`
    - wait for YM2612 ready; write **register `$2B = $80`** (DAC enable)
    - `SUB $81` → sample index; bank ROM and stream sample bytes into the DAC data path

The host emulator (`MegaDriveEnvironment` Z80 core) explicitly accounts for the 68000 sound driver hammering BUSREQ while waiting on the Z80 DAC busy flag — a real hardware handshake.

---

## 4. How game code requests sound

### 4.1 Fire-and-forget queue

Ordinary game code posts an ID with the high bit set (IDs are in the `$80`–`$FF` range):

```asm
move.b #$87, (play_se_).w     ; request ID $87
```

There is also a small helper **`sub_0001069E`**: given an ID in `d7`, it scans the three queue slots at `play_se`, skips if the ID is already queued, otherwise stores it in the first free slot (byte `0`).

### 4.2 Level BGM table

`sub_00011B12` loads music from a per-level table at **ROM `$11B44`** (unless special flags force alternate IDs such as `$87` / `$90`):

| Level | Sound ID |
|------:|----------|
| 0 | `$81` |
| 1 | `$8B` |
| 2 | `$84` |
| 3 | `$8C` |
| 4 | `$85` |
| 5 | `$89` |
| 6 | `$86` |
| 7 | `$88` |

Other call sites found in disassembly (non-exhaustive):

| ID | Typical context |
|----|-----------------|
| `$E0` | Level-flow / transition — fade or stop current BGM |
| `$90` | Sting / jingle on certain sequence ends |
| `$87` | Alternate BGM on some transitions |
| `$BD`, `$BF` | Event SFX |

---

## 5. The 68000 sound engine

### 5.1 When it runs

The VBlank IRQ handler **`vblank_handler`** ($19D16) always invokes the engine before `RTE`:

```asm
jsr (sub_00072914).l
rte
```

So channel timing is **frame-based** (one tick per vertical blank), not a free-running Z80 tempo thread.

### 5.2 Top-level: `sub_00072914` ($72914)

Each frame (simplified):

1. **`sub_00072D08`** — drain `play_se` queue (unless music stop/fade blocks start paths).
2. **`sub_00073066`** — advance `stop_music` fade state.
3. Walk active channels (header **bit 7** set):

| Work RAM base | Count | Kind | Tick routine |
|---------------|------:|------|--------------|
| `$FFF040` | 5 | Music FM | `sub_00072B08` |
| `$FFF130` | 1 | Music **DAC** | `sub_00072A4E` |
| `$FFF160` | 3 | Music PSG | `sub_0007388C` |
| `$FFF1F0` | 2 | SFX FM | `sub_00072B08` |
| `$FFF2B0` | 2 | SFX PSG | `sub_0007388C` |
| `$FFF340` | 1 | Extra FM | `sub_00072B08` |

Each channel control block is **`$30` bytes** (sequence pointer, duration counter, pitch, volume/attenuation, modulation state, flags, etc.).

`$FFF006` is a phase flag used while updating (music vs SFX sections) so SFX can temporarily own hardware channels without the music tick fighting it.

### 5.3 Command dispatch: `sub_00072D08` ($72D08)

1. Read up to three queue bytes from `$FFF00A`.
2. Accept only values with **bit 7 set**.
3. Map `ID − $81` through priority table **ROM `$72824`**; keep the request with the **highest priority** in `$FFF009` / `$FFF000` scratch.
4. Clear the queue slots.
5. Branch on ID range:

| ID range | Class | Behaviour |
|----------|-------|-----------|
| `$81`–`$9F` | **Music** | Pointer table **`$7288C`** → arm FM + PSG (+ DAC track) channels |
| `$A0`–`$CF` | **SFX** | Pointer table **`$73B56`** → arm SFX channels; may steal music slots |
| `$D0`–`$DF` | **Direct PCM** | Write `(ID + $B6)` to Z80 **`$1FFF`** under BUSREQ |
| `$E0`–`$E3` | **Special** | `$E0` starts BGM fade (`loc_0007302E`) |
| else | Reset | Full silence / engine reset via `sub_00072F8A` |

Observed priorities (table `$72824`): music entries cluster around **`$80`**; SFX span roughly **`$2F`–`$7F`** (e.g. `$BD` / `$BF` at `$7F`); PCM commands **`$72`–`$78`**.

Music pointer table `$7288C` holds absolute long pointers for tracks `$81` upward (many valid headers through `$91`; later slots are stubs/empty). SFX table `$73B56` covers `$A0`–`$CF` with one header pointer each.

---

## 6. Music and SFX data formats

### 6.1 Music header

Example: track ID `$87` at ROM `$75B3A`:

```
+0  word   relative offset to FM instrument / voice bank
+2  byte   FM track count (commonly 6)
+3  byte   PSG track count (commonly 3)
+4  …      per FM track: word relative seq ptr, byte transpose
           per PSG track: word relative seq ptr, two meta bytes
```

The six “FM” tracks map onto five tonal FM channel slots plus the **DAC channel block** at `$FFF130` (sample events rather than FM key-on for that lane).

### 6.2 SFX header

Example: ID `$BF` at ROM `$743FA`:

```
+0  word   meta / offset field
+2  byte   routing / channel class
+3  byte   (often 2)
+4  word   relative offset to sequence stream
```

SFX setup uses base-address tables **`$72E74`** / **`$72E88`** to pick which SFX channel block to initialise and which music channel to mark stolen.

### 6.3 Sequence stream (shared FM / PSG style)

Tracker-style bytecode:

- **Byte &lt; `$F0`**: duration (bit 7 often means rest / key-off). If a note event, the next byte is pitch-related data.
- **Byte ≥ `$F0`**: **command** — dispatched by **`sub_000732EA`** (jump tables for FM vs PSG channel types).

Commands cover instrument change, jumps/loops, modulation, volume, PSG noise mode, track end, and similar control. Exact opcode map is a natural follow-up extraction task; the dispatcher lives at `$732EA` with FM table near `$73302` and PSG-oriented table near `$73342`.

### 6.4 Pitch tables

| Chip | ROM table | Use |
|------|-----------|-----|
| YM2612 FM | `$732D2` | 12 semitone period words → regs `$A0` / `$A4` + key-on `$28` |
| SN76489 PSG | `$73A64` | Period words → latch writes to `$C00011` |

PSG volume envelopes use another pointer table at **`$728D0`**.

---

## 7. Hardware write paths (68000)

### 7.1 BUSREQ + YM2612: `sub_00073298` / `sub_00073206`

Before FM register traffic:

1. `move.w #$0100, (z80_busreq)` and wait for acknowledge.
2. If Z80 **`$1FFD` bit 7** is set (DAC busy), release the bus and retry — avoid colliding with Z80 DAC setup.
3. Wait until YM2612 status bit 7 is clear.
4. Write address then data on part 0 (`$A04000`/`$A04001`) or part 1 (`$A04002`/`$A04003`) depending on channel.

Key-on / key-off use register **`$28`**. Operator TL and other params use the usual OPN register map with channel offsets derived from the channel block’s hardware index byte.

### 7.2 PSG: `sub_000731A2`, `sub_00073964`, `sub_000739B6`

- Silence all four PSG channels: `$9F $BF $DF $FF` on `$C00011`.
- Tone period: low nibble combined with channel latch, then high bits.
- Attenuation: channel latch + volume nibble (with envelope table support).

### 7.3 DAC channel tick: `sub_00072A4E`

Music DAC lane:

- Countdown duration; pull sequence bytes (same `$F0+` command idea).
- When a sample should start, under BUSREQ write the sample/command byte to **Z80 `$1FFF`**, watching **`$1FF6`**.
- Can force a “quiet” sample value (`$85`) when pausing/ducking the DAC lane.

Direct PCM command path (`$D0`–`$DF`) bypasses the music DAC sequencer and posts `(ID + $B6)` straight to `$1FFF`.

---

## 8. Stop / fade music

Command **`$E0`** (and the `stop_music` RAM path) does not hard-cut immediately:

1. Set `stop_music` to **`$10`**, subframe counter `$FFF003` to **4**.
2. Each engine frame (`sub_00073066`): every four frames, decrement `stop_music` and **raise FM attenuation** on music channels (`sub_000736DA` via `$9` in the channel block).
3. When the counter hits zero, call **`sub_00072F8A`**:
   - reset DAC-related YM state
   - key-off / max attenuation style cleanup
   - zero a large swath of the `$FFF000` audio workspace
   - silence PSG (`sub_000731A2`)

---

## 9. Clarification: `sync_z80_1` / `sync_z80_2`

Labels at `$10502` / `$10514` write **1** or **2** to **`$FFFA00`** and spin until it clears, with IRQs enabled (`sr = $2500`).

These are **not** sound-driver mailboxes to the Z80. The **VBlank handler** consumes `$FFFA00`, performs scroll/DMA work (often with BUSREQ around DMA), clears the byte, and only then runs the sound engine. The helpers are **“wait for VBlank (and associated bus-safe work)”** synchronisation used by game logic. Manual reimplementations live in `SorManualFunctions.cpp` (`sync_z80_1`, `sync_z80_2`) for the recompilation runtime.

---

## 10. Project file map

| Artifact | Location |
|----------|----------|
| Disassembly | `StreetsOfRageRecompilation/output/sor.asm` |
| Known addresses / labels | `StreetsOfRageRecompilation/code-analysis/addresses.csv`, `labels.csv` |
| Manual VBlank-sync hooks | `StreetsOfRageRecompilation/SorManualFunctions.cpp` |
| Generated 68000 recompile | `StreetsOfRageRecompilation/generated/Sor.cpp` |
| YM2612 + PSG host | `MegaDriveEnvironment/include/.../sound/Sound.hpp` (+ ymfm) |
| Z80 host + bank/BUSREQ | `MegaDriveEnvironment/include/.../z80/Z80.hpp`, `src/system/z80/Z80.cpp` |
| Original ROM (local, not versioned) | `StreetsOfRageRecompilation/rom/SOR.bin` |

Important ROM / RAM anchors:

| Symbol / role | Address |
|---------------|---------|
| Sound engine entry | `$72914` |
| Queue drain / ID dispatch | `$72D08` |
| Music pointer table | `$7288C` |
| SFX pointer table | `$73B56` |
| Priority table | `$72824` |
| Level BGM table | `$11B44` |
| Z80 driver (Kosinski) | `$795A2` |
| Z80 load routine | `$1061C` |
| VBlank handler | `$19D16` |
| Kosinski decompressor | `$85A2` |

---

## 11. Design takeaways

1. **68000-centric mixer** — tempo, music, and most SFX are frame-driven on the main CPU; the Z80 is specialised for sample streaming.
2. **Single public API** — almost all audio is “write an ID to `play_se`”; music and SFX share one queue and a priority table.
3. **Hardware arbitration** — BUSREQ plus Z80 `$1FFD` / `$1FF6` keep FM register writes and DAC streaming from stomping each other on the YM2612.
4. **Channel stealing** — SFX blocks sit in separate RAM and can suppress music lanes for the same physical FM/PSG channel.
5. **Fade, not only mute** — BGM stop is a multi-frame attenuation ramp, then a full workspace reset.

---

## 12. Open follow-ups

These were identified during analysis but not fully catalogued in this manuscript:

1. **Name every ID** `$81`–`$CF` (and PCM `$D0`–`$DF`) from call sites and auditory testing.
2. **Document the full `$F0+` command set** in `sub_000732EA` (FM vs PSG tables).
3. **Extract the Z80 sample directory** (offsets/lengths after `SUB $81`) and map PCM IDs to game events.
4. **Instrument bank format** behind the music header’s voice-bank pointer.
5. Cross-check against community sound rips / driver names (Koshiro / Ancient-era tooling) if a public name for this exact driver exists.

---

## 13. One-line summary

***Streets of Rage* runs a custom 68000 frame sequencer for FM and PSG music/SFX, uses a small work-RAM ID queue as the only game-facing API, and relegates the Z80 to a BUSREQ-guarded YM2612 DAC sample player driven by mailboxes in the top of Z80 RAM.**

---

*Generated for the StreetsOfRageProject meta-repository (`ai-analysis/`). Addresses and behaviours derived from disassembly and ROM inspection; treat confidence as high for structure and I/O, lower for human-readable track/SFX names until call-site naming is completed.*
