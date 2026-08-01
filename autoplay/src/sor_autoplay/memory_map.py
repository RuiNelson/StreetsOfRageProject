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

# Object field used by Mr. X choice UI (bit3 = side, bit4 = choice active).
OBJ_PLAYER_FLAGS_59 = 0x59

# Offsets within a player / generic object
OBJ_TYPE = 0x00
OBJ_FLAGS = 0x01  # bit0 set => hidden from SAT (see enqueue_object_render_bucket)
OBJ_FACING = 0x09  # ordinary enemies: bit1 left/right (enemy-ai.md)
OBJ_POS_X = 0x10  # long 16.16 world X; integer is the high word (unsigned)
OBJ_POS_Y = 0x14  # long 16.16 lane / depth Y
OBJ_POS_Z = 0x18  # long 16.16 height
# Primary state: player uses low byte action; ordinary enemies use a *word*
# in $0100 steps ($0100 normal … $0700 blocked). Bosses use a *byte* index.
OBJ_PRIMARY_STATE = 0x30
OBJ_ACTION_STATE = 0x30  # alias (player action byte = low of word)
OBJ_HEALTH = 0x32
OBJ_OUTGOING_DAMAGE = 0x34  # active hit descriptor low nibble when attacking
# Ordinary enemy: target player object pointer (low 16 bits of address).
OBJ_TARGET_PTR = 0x42
# Later bosses ($55-$58): abs X distance to target (word), pair role, tactical.
OBJ_BOSS_DIST_X = 0x50  # also Abadede linked helper / character id on players
OBJ_CHARACTER_ID = 0x50  # player character id (same offset, different meaning)
OBJ_BOSS_DIST_LANE = 0x52
OBJ_PAIR_ROLE = 0x5D  # later-boss pair role 1/2; player combo state reuses $5D
OBJ_COMBO_STATE = 0x5D  # player combo / action chain
OBJ_HELD_PTR = 0x5E  # word pointer to grabbed/held object
OBJ_HELD_TYPE = 0x60  # nonzero while holding weapon or grab target type
OBJ_BOSS_TACTICAL = 0x67  # later-boss tactical substate (and Abadede police latch)
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
ACTION_JUMP = 0x10
ACTION_ATTACK = 0x18
ACTION_REAR = 0x20
ACTION_GRAB = 0x28
ACTION_GRAB_THROW = 0x44
ACTION_HURT_MIN = 0x50
ACTION_HURT_MAX = 0x5F

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
