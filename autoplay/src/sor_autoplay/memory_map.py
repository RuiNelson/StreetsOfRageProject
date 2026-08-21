"""Work-RAM symbols for the Streets of Rage observer.

Addresses match ``StreetsOfRageRecompilation/code-analysis/addresses.csv`` and
the AI analysis notes under ``StreetsOfRageRecompilation/ai-analysis/``.
"""

from __future__ import annotations

# --- Global campaign / HUD state (word-aligned globals near $FFFF00) ---
ADDR_GAME_STATE = 0xFFFF00
ADDR_LEVEL = 0xFFFF02
ADDR_WAVE = 0xFFFF04
ADDR_SCORE_P1 = 0xFFFF08
ADDR_SCORE_P2 = 0xFFFF10
ADDR_PLAYER_MODE = 0xFFFF18
ADDR_P1_CONTINUES = 0xFFFF1A
ADDR_P2_CONTINUES = 0xFFFF1C
ADDR_P1_CHARACTER_ID = 0xFFFF1E
ADDR_P2_CHARACTER_ID = 0xFFFF1F
ADDR_P1_LIVES = 0xFFFF20
ADDR_P1_SPECIALS = 0xFFFF21
ADDR_P1_OUT_FLAG = 0xFFFF22
ADDR_P2_LIVES = 0xFFFF23
ADDR_P2_SPECIALS = 0xFFFF24
ADDR_P2_OUT_FLAG = 0xFFFF25

# --- Round clock ---
# game_timer is the live countdown (BCD-like word: $40/$50/$60 at wave start).
# round_timer_bcd is the two-digit HUD digit source updated once per game second.
ADDR_GAME_TIMER = 0xFFFB00
ADDR_ROUND_TIMER_BCD = 0xFFFB02
ADDR_MILLI_SECOND = 0xFFFB58
ADDR_STOP_CLOCK = 0xFFFA79

# --- Fixed player object slots (128 bytes each) ---
ADDR_P1_OBJECT = 0xFFB800
ADDR_P2_OBJECT = 0xFFB880
OBJECT_SLOT_SIZE = 0x80

# General gameplay object table (enemies, items, props, bosses).
# update_objects_and_build_sprites walks 66 slots (moveq #$41,d7 + dbf).
# Older analysis notes that said "32" under-count the live table.
ADDR_OBJECT_TABLE = 0xFFB900
OBJECT_TABLE_SLOTS = 66

# Primary camera / plane structure.
ADDR_PRIMARY_CAMERA = 0xFFE000
ADDR_CAM_X = 0xFFE002  # integer high word of camera X (16.16)
ADDR_CAMERA_Y = 0xFFE00E  # camera Y/depth long (16.16)
ADDR_PRIMARY_BLOCKMAP_STRIDE = 0xFFE02E

# Level collision (packed two 4-bit classes per byte). Class 0 ≈ open/hole.
ADDR_LEVEL_COLLISION_CLASS_MAP = 0xFFA000

# Pause / police special (see addresses.csv + ai-analysis).
ADDR_POLICE_SPECIAL_ACTIVE = 0xFFFA1A
ADDR_POLICE_SPECIAL_START_PULSE = 0xFFFA1B
ADDR_POLICE_SPECIAL_CALLER = 0xFFFA1C
ADDR_PAUSE_TEXT_FLAG = 0xFFFA46
# pause_text_flag: 0 = running; nonzero = paused (3 on enter, then often 1).
PAUSE_FLAG_PAUSED = 0x03

# Mr. X final offer (round 8); see story-mode-and-campaign-flow.md.
ADDR_MR_X_OFFER_FLAG = 0xFFDE00
ADDR_MR_X_OFFER_STATE = 0xFFDE04
ADDR_BAD_ENDING_SELECTED = 0xFFDE10

# OPTIONS control layout (0 = standard A=special, B=attack, C=jump).
ADDR_CONTROL_SCHEME = 0xFFFFC8

# --- Pre-gameplay menu navigation (story -> title -> menu -> character
# select -> level intro -> gameplay). Used by reach_gameplay.py to drive the
# real menus via joypad taps + bounded RAM waits, never RAM writes.
ADDR_SELECT_MENU_CURSOR = 0xFFB840  # W, 0 = one-player mode selected
ADDR_CHAR_SELECT_SLOT = 0xFFB858  # W, character-select screen order (Adam/Axel/Blaze)
ADDR_LEVEL_INTRO_ACTIVE = 0xFFFA1F  # B, nonzero while intro locks out controls
ADDR_SELECT_SCREEN_SUBSTATE = 0xFFFB0E  # W
ADDR_CHAR_SELECT_SUBSTATE = 0xFFF904  # W
ADDR_SOUND_MUSIC_VOICE_BANK = 0xFFF014  # L
ADDR_PLAY_SE = 0xFFF00A  # B, sound command queue slot 0

# Object field used by Mr. X choice UI (bit3 = side, bit4 = choice active).
OBJ_PLAYER_FLAGS_59 = 0x59

# Offsets within a player / generic object
OBJ_TYPE = 0x00
OBJ_FLAGS = 0x01  # bit0 set => hidden from SAT (see enqueue_object_render_bucket)
OBJ_FACING = 0x09  # ordinary enemies: bit1 left/right (enemy-ai.md)
# Family-local visual/subtype selector.  Several breakable dispatchers reuse
# their original object type for debris and distinguish the debris at +$0B.
OBJ_SUBTYPE = 0x0B
OBJ_POS_X = 0x10  # long 16.16 world X; integer is the high word (unsigned)
OBJ_POS_Y = 0x14  # long 16.16 lane / depth Y
OBJ_POS_Z = 0x18  # long 16.16 height
# Live velocities, signed 16.16, integrated by $17AB8. $15ABA writes them
# directly for the twins' jump attack: +$20 = +-$00010000 (X, sign from the
# lane byte +$61) and +$24 = $FFF8C000 (Z, -7.25) at phase timer 4, then adds
# $0000C000 (+0.75) to +$24 every later tick until +$18 meets +$4C.
OBJ_VEL_X = 0x20
OBJ_VEL_Z = 0x24
# Ordinary-enemy velocity, per enemy-ai.md's "object layout used by ordinary
# enemies" table ($1C/$20/$24 = X/lane/vertical velocity, evidenced by $973E,
# $9F96 ordinary_enemy_advance_x_bounded, $A00E
# ordinary_enemy_advance_lane_bounded; corroborated independently by the boss
# AI section citing +$1C(target) as a player target's X-velocity). This
# implies the existing OBJ_VEL_X=0x20 above is actually lane velocity for
# this family, not X -- but it is boss-only in practice today (Boss.vel_x/
# vel_z), so it is left untouched here; these are separate, correctly named
# constants for ordinary enemies only.
OBJ_VEL_X_ORDINARY = 0x1C
OBJ_VEL_LANE_ORDINARY = 0x20
# Lane sign latched at jump launch; selects the X velocity direction.
OBJ_BOSS_LANE_SIGN = 0x61
# Primary state at +$30:
# - Players: **byte** action/facing at +$30 (bit0 = face left). Live dump while
#   holding is $60 (grab/throw family), NOT the low byte of a BE word.
# - Ordinary enemies: **word** in $0100 steps ($0100 normal … $0700 blocked).
# - Bosses: **byte** primary index at +$30.
OBJ_PRIMARY_STATE = 0x30
OBJ_ACTION_STATE = 0x30  # player/boss: read as **byte** at +$30
OBJ_HEALTH = 0x32
OBJ_OUTGOING_DAMAGE = 0x34  # active hit descriptor low nibble when attacking
# Generic level-record parameters copied by the ELC object spawner.  The
# stage-8 type-$45 moving breakable uses +$40 to select its moving/damaging
# variant; most families interpret these bytes differently.
OBJ_SCRIPT_PARAM = 0x40
# Ordinary enemy: target player object pointer (low 16 bits of address).
OBJ_TARGET_PTR = 0x42
# Contact/grab partner pointer (word). Live hold used +$4C = enemy slot while
# +$5E held_ptr was zero — both must be checked.
OBJ_CONTACT_PTR = 0x4C
# Later bosses ($55-$58): abs X distance to target (word), pair role, tactical.
OBJ_BOSS_DIST_X = 0x50  # also Abadede linked helper / character id on players
OBJ_CHARACTER_ID = 0x50  # player character id (same offset, different meaning)
# Ground weapons: wear/exhaust counter (+$50 < 3 is still usable). Consumable
# pickups store their effect index here. Same offset, different meanings.
OBJ_ITEM_PARAM = 0x50
# Ordinary enemies: remaining stun frames, counted down by whichever state
# handler owns the stun. $9B88 (ordinary_enemy_apply_contact_damage, the
# $0200 handler) loads $18 on the hit that starts hitstun and does
# `subq.b #1,$50(a0)` every frame, returning to $0100 at zero. $A43E (the
# shared $0400 handler) does the same with $A0 for the pepper-spray
# immobilization. Same offset as the weapon wear / boss distance aliases
# above -- only meaningful for kind=="enemy".
OBJ_ORDINARY_STUN_TIMER = 0x50
# Weapons/pickups: nonzero means reserved, held, thrown, or mid-collect
# (ROM find_close_interaction_target at $3136 requires zero for a free ground
# weapon). Not the same as ordinary enemy family_state at +$52.
OBJ_INTERACTION = 0x51
OBJ_BOSS_DIST_LANE = 0x52
# Ordinary family-private byte at the same offset. Jack ($27) uses bit 0 as
# the weapon-attached latch: set while an axe/torch is in his hands and clear
# when state $0E launches it. Keep this distinct from the boss distance alias.
OBJ_FAMILY_STATE = 0x52
OBJ_JACK_WEAPON_ATTACHED = 0x52
# Weapon +$52: holder object pointer (low 16 of the 68000 address). Same
# offset as ordinary-enemy family_state / later-boss lane distance; only
# meaningful for kind=="weapon" while interaction==1 (held). Enemies do not
# store the weapon type at +$60 (that word is their scripted approach X).
OBJ_WEAPON_HOLDER = 0x52
# Type-$0F continue / high-score name-entry object (see player-health-lives-and-combat.md).
# Bit7 set → high_score_name_entry_dispatcher; clear → continue Yes/No table at $5236.
OBJ_CONTINUE_UI_FLAGS = 0x4B
OBJ_CONTINUE_NAME_ENTRY_BIT = 0x80
# Name-entry cursor ($57D2): word slot 0/2/4 for the three initials, word
# letter index 0..26 (A..Z then END). Only meaningful while bit7 of +$4B is set.
OBJ_CONTINUE_NAME_SLOT = 0x60
OBJ_CONTINUE_NAME_LETTER = 0x62
# Continue Yes/No selection: 0 = YES, nonzero (bit0) = NO. Toggled by UP/DOWN.
# Shared with the low byte of the name-entry letter word -- ignore unless
# name-entry bit7 is clear.
OBJ_CONTINUE_CHOICE = 0x63
# Mr. X offer-choice bits in object+$59 (story-mode-and-campaign-flow.md §7.4).
OBJ_MR_X_CHOICE_NO_BIT = 0x08  # bit 3 set → NO; clear → YES
OBJ_MR_X_CHOICE_ACTIVE_BIT = 0x10  # bit 4 set → this player's choice UI is live
OBJ_ACTION_FLAGS = 0x58  # player combo/action flags; bit5 queues next normal hit
# Throw-landing tech flags (controls-and-input.md "C+Up landing tech"):
# +$45 armed by special throw releases ($284A/$28A2/$2AA4); C-edge+Up latches +$46
# so $3F24 skips bounce and lands as jump $14.
OBJ_TECH_ARM = 0x45  # player: nonzero while bounce-cancel tech may be latched
OBJ_TECH_LATCH = 0x46  # player: set by C-edge+Up; consumed on floor land
OBJ_PAIR_ROLE = 0x5D  # later-boss pair role 1/2; player combo state reuses $5D
OBJ_COMBO_STATE = 0x5D  # player combo / action chain
OBJ_HELD_PTR = 0x5E  # word pointer to grabbed/held object (weapons / some grabs)
OBJ_HELD_TYPE = 0x60  # nonzero while holding weapon or grab target type
# Later bosses ($55-$58): ground/landing height snapshot. $15ABA tests the
# live height +$18 against this to decide "still airborne".
OBJ_BOSS_GROUND_Z = 0x4C
OBJ_BOSS_TACTICAL = 0x67  # later-boss tactical substate (and Abadede police latch)
# Later bosses ($55-$58): $179F8 writes 1 here when the selected player is
# unavailable (hurt/knockdown $5A-$5F or +$59/+$4B bit1 interaction flags).
# The twins' leap-to-grab ($15BE8) arms only while this is nonzero.
OBJ_BOSS_TARGET_UNAVAIL = 0x77
# Later bosses: multi-purpose phase timer (jump arc, throw timeline, init latch).
OBJ_BOSS_PHASE_TIMER = 0x78
# Later bosses: mode flags. Twin bit 1 selects the grab/throw AI path; init
# seeds it from pair role +$5D, and an unpaired survivor can set or clear it.
OBJ_BOSS_MODE_FLAGS = 0x7B
# Ordinary enemy: attacker/contact object pointer (low 16). Grabbed Signal had
# +$3E = $B800 (P1) while player +$60 was still zero.
OBJ_ATTACKER_PTR = 0x3E
# Abadede / Mr. X selected player pointer.
OBJ_BESPOKE_TARGET = 0x5C
# Later-boss selected player pointer word.
OBJ_LATER_BOSS_TARGET = 0x72

# Ordinary-enemy primary state words (high byte = family index).
ENEMY_ST_NORMAL = 0x0100
ENEMY_ST_ALT = 0x0200
ENEMY_ST_KNOCKDOWN = 0x0300
ENEMY_ST_SCRIPTED = 0x0400
ENEMY_ST_GRABBED = 0x0500
ENEMY_ST_DEATH = 0x0600
ENEMY_ST_BLOCKED = 0x0700

# Player action-state families (bit0 often facing; compare with & ~1).
ACTION_IDLE = 0x02
ACTION_JUMP_START = 0x10
ACTION_JUMP_AIRBORNE = 0x12
ACTION_JUMP_LANDING = 0x14
ACTION_JUMP_ATTACK = 0x16
# Backwards-compatible family alias.
ACTION_JUMP = ACTION_JUMP_START
ACTION_ATTACK = 0x18
ACTION_REAR = 0x20
ACTION_GRAB = 0x28
ACTION_GRAB_THROW = 0x44
ACTION_HURT_MIN = 0x50
ACTION_HURT_MAX = 0x5F
# Throw-air families that can consume +$45/+46 bounce-cancel tech at $3F24.
ACTION_THROW_AIR_TECHABLE = frozenset({0x5C, 0x72, 0x88})
# Grab/throw reaction family used while holding an enemy (live: Axel $60/$6A/$6C).
ACTION_HOLD_REACT = 0x60
ACTION_HOLD_REACT_MAX = 0x6F
# Every base in that family, facing bit already cleared. controls-and-input.md
# "Grab, hold, throw": $60 (front) and $66 (back) are the *stable* holds that
# accept a new B/C edge; $62/$64/$68/$6A/$6C/$6E are the animation locks that
# ignore fresh edges. Both halves still mean "this actor has a body in its
# hands", which is the question ai/decide.py asks -- and the **only** signal
# that answers it for a later boss: +$60 (OBJ_HELD_TYPE) is written by the
# weapon/pickup path, and a held Antonio leaves it reading 0 (or the weapon
# still being carried). Measured live: the AI sat in $60/$61 holding Antonio
# for a whole round-1 fight, dealing no damage, until the stage timer killed
# it.
ACTION_HOLD_FRONT = 0x60
ACTION_HOLD_BACK = 0x66
ACTION_HOLD_BASES = frozenset(range(ACTION_HOLD_REACT, ACTION_HOLD_REACT_MAX + 1, 2))
# The crossover that C fires from a front hold: "$76 / $80 family -> back hold
# $66" (controls-and-input.md). It sits *outside* $60-$6F, and the actor is
# still holding the body throughout -- measured live on Antonio, the crossover
# ran 28 ticks in $76 during which the AI, believing itself free, issued
# WalkToNearEnemy and even the $322A rear chord in the middle of its own
# flip->suplex. The same family is also the co-op partner vault, which is *not*
# a hold, so callers must additionally require the ROM hold link +$4C to be
# set (PlayableCharacter.is_holding_enemy does).
ACTION_HOLD_CROSSOVER = frozenset({0x76, 0x80})
ACTION_HOLDING = ACTION_HOLD_BASES | ACTION_HOLD_CROSSOVER

# Fixed object bases (for decoding target pointers).
ADDR_P1_OBJECT_LO = 0xB800  # low 16 of $FFB800
ADDR_P2_OBJECT_LO = 0xB880

# Match update_objects / enqueue_object_render_bucket: bit 0 of +$01 means
# "do not draw". ordinary_enemy_activate sets it while waiting off-screen.
OBJ_FLAG_HIDDEN = 0x01

# Health is a binary word clamped to 0..$50 (80 units) by adjust_player_health.
MAX_HEALTH = 0x50

# Object type bytes used by the player lifecycle
OBJ_TYPE_INACTIVE = 0x00
OBJ_TYPE_ACTIVE_PLAYER = 0x01
OBJ_TYPE_CONTINUE_UI = 0x0F

# Character IDs (in-game / post-confirm). Select-screen L→R is Adam, Axel, Blaze.
CHARACTER_NAMES = {
    0: "Axel",
    1: "Adam",
    2: "Blaze",
}

# Global game_state even values are init handlers; +2 is the matching update.
# Names follow story-mode-and-campaign-flow.md.
GAME_STATE_NAMES: dict[int, str] = {
    0x00: "Sega logo (init)",
    0x02: "Sega logo",
    0x04: "Story intro (init)",
    0x06: "Story intro",
    0x08: "Title (init)",
    0x0A: "Title",
    0x0C: "Hi-scores (init)",
    0x0E: "Hi-scores",
    0x10: "Mode menu (init)",
    0x12: "Mode menu",
    0x14: "In-game (init)",
    0x16: "In-game",
    0x18: "Round clear (init)",
    0x1A: "Round clear",
    0x1C: "Bad ending (init)",
    0x1E: "Bad ending",
    0x20: "Character select (init)",
    0x22: "Character select",
    0x24: "Good ending (init)",
    0x26: "Good ending",
    0x28: "Level intro (init)",
    0x2A: "Level intro",
}

# Compact mode labels for the HUD (collapse init/update pairs).
GAME_MODE_LABELS: dict[int, str] = {
    0x00: "Sega logo",
    0x02: "Sega logo",
    0x04: "Story intro",
    0x06: "Story intro",
    0x08: "Title",
    0x0A: "Title",
    0x0C: "Hi-scores",
    0x0E: "Hi-scores",
    0x10: "Mode menu",
    0x12: "Mode menu",
    0x14: "In-game",
    0x16: "In-game",
    0x18: "Round clear",
    0x1A: "Round clear",
    0x1C: "Bad ending",
    0x1E: "Bad ending",
    0x20: "Character select",
    0x22: "Character select",
    0x24: "Good ending",
    0x26: "Good ending",
    0x28: "Level intro",
    0x2A: "Level intro",
}

# player_mode is a live bit mask: bit0 = P1 active, bit1 = P2 active.
PLAYER_MODE_P1 = 0x01
PLAYER_MODE_P2 = 0x02

# Score longwords use packed BCD in the low digits; top bits may hold dirty flags.
SCORE_VALUE_MASK = 0x3FFFFFFF
