"""Token classes (including ABCs), split by kind.

Mirrors the former flat ``ai/`` module layout: base tokens, character and
enemy observations, essential scene tokens, hazards, pickups, and the
``Decision`` branches. Pipeline modules and tests may import everything
from this package, e.g. ``from sor_autoplay.ai.tokens import Myself``.
"""

from __future__ import annotations

from .attack_decisions import (
    Attack,
    AttackHeldEnemy,
    CounterGrab,
    FlipHold,
    GrabEnemy,
    GrabMechanics,
    JumpAttack,
    MeleeAttacks,
    MeleeWeaponAttacks,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
    WeaponAttacks,
)
from .character import (
    MELEE_WEAPON_TYPES,
    PUNCH_RANGE_Y,
    REAR_ATTACK_Y,
    Character,
    Myself,
    Partner,
    PlayableCharacter,
    punch_inner_x,
    punch_outer_x,
    rear_attack_behind_max_x,
    rear_attack_front_max_x,
)
from .enemy import (
    Abadede,
    ActionableTarget,
    Antonio,
    Bongo,
    Boss,
    ClosingEnemy,
    Enemy,
    Garcia,
    GrabOpportunity,
    GrabToClearRear,
    GrabToNeutralizeWhip,
    Grunt,
    HakuRo,
    InGrabReach,
    InJumpAttackReach,
    InPunchReach,
    InRearReach,
    IncomingMelee,
    Jack,
    MrX,
    Nora,
    Onihime,
    PunishWindow,
    Signal,
    Souther,
    Surrounded,
    TargetInReach,
    enemy_class_for_type,
)
from .essential import AnimationInProgress, CameraRange, Essential, Stage
from .hazard_tokens import (
    Breakable,
    IncomingProjectile,
    Pit,
    Projectile,
    SafeSpot,
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
    WeaponUpgrade,
    build_pickup_token,
    is_pickup_type,
    is_weapon_type,
    pickup_class_for_type,
    weapon_rank,
)
from .police_decision import CallPolice
from .recovery_decisions import Recovery, TechRecover
from .tokens import (
    Context,
    Decision,
    Information,
    Inferred,
    Observed,
    Token,
    find,
    find_all,
)
from .walk_decisions import (
    RetreatFromDanger,
    Walk,
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
