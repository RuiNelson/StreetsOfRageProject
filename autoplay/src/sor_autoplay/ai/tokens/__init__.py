"""Token classes (including ABCs), split by kind.

Mirrors the former flat ``ai/`` module layout: base tokens, character and
enemy observations, essential scene tokens, hazards, pickups, and the
``Verb`` branches. Pipeline modules and tests may import everything
from this package, e.g. ``from sor_autoplay.ai.tokens import Myself``.
"""

from __future__ import annotations

from ...attack_ranges import AttackRange
from ...hitboxes import Hitbox

from .attack_verbs import (
    Attack,
    AttackHeldEnemy,
    CounterGrab,
    FlipHold,
    GrabEnemy,
    GrabMechanics,
    HitAntonioBoomerang,
    JumpAttack,
    MeleeAttacks,
    MeleeWeaponAttack,
    OpenBreakable,
    Punch,
    RearAttack,
    ReleaseGrab,
    Supplex,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
    WeaponAttacks,
)
from .character import (
    BODY_OVERLAP_X,
    MELEE_WEAPON_TYPES,
    PUNCH_RANGE_Y,
    REAR_ATTACK_Y,
    Character,
    Myself,
    Partner,
    PlayableCharacter,
    punch_inner_x,
    punch_usable_inner_x,
    punch_outer_x,
    rear_attack_behind_max_x,
    rear_attack_behind_min_x,
    rear_attack_front_max_x,
)
from .enemy import (
    Abadede,
    Antonio,
    Bongo,
    Boss,
    Enemy,
    Garcia,
    GrabReason,
    Grunt,
    HakuRo,
    Jack,
    MrX,
    NORA_TICKS_SINCE_ATTACK_UNKNOWN,
    Nora,
    Onihime,
    Signal,
    Souther,
    Surrounded,
    enemy_class_for_type,
)
from .dialog_verbs import (
    CONTINUE_INITIALS,
    NAME_ALPHABET_SIZE,
    NAME_LETTER_A,
    NAME_LETTER_END,
    NAME_LETTER_I,
    Dialog,
    HandleContinueMenu,
    HandleMrXDialog,
)
from .essential import (
    AnimationInProgress,
    CameraRange,
    Essential,
    InContinueMenu,
    InMrXDialog,
    Stage,
)
from .hazard_tokens import (
    Breakable,
    Pit,
    Projectile,
    StageObjects,
)
from .pickup_tokens import (
    HEALTH_DELTA,
    PLAYER_MAX_HEALTH,
    WEAPON_DAMAGE,
    WEAPON_TYPE_MAX,
    WEAPON_TYPE_MIN,
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
    Weapon,
    build_pickup_token,
    is_pickup_type,
    is_weapon_type,
    pickup_class_for_type,
    weapon_rank,
)
from .police_verb import CallPolice
from .recovery_verbs import Recovery, TechRecover
from .tokens import (
    Context,
    Verb,
    Information,
    Inferred,
    Observed,
    Token,
    find,
    find_all,
)
from .walk_verbs import (
    DodgeAntonioKick,
    DodgeSoutherSlash,
    ProjectileSidestep,
    RetreatFromDanger,
    Walk,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
