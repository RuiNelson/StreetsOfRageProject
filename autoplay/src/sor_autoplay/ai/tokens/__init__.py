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
    GrabMechanics,
    JumpAttack,
    MeleeAttacks,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
    Supplex,
    ThrowHeldEnemy,
    ThrowKnife,
    WeaponAttacks,
)
from .character import (
    PUNCH_RANGE_Y,
    Character,
    Myself,
    Partner,
    PlayableCharacter,
    punch_inner_x,
    punch_outer_x,
)
from .enemy import (
    Abadede,
    Antonio,
    Bongo,
    Boss,
    Enemy,
    Garcia,
    Grunt,
    HakuRo,
    Jack,
    MrX,
    Nora,
    Onihime,
    Signal,
    Souther,
    enemy_class_for_type,
)
from .essential import AnimationInProgress, CameraRange, Essential, Stage
from .hazard_tokens import Breakable, IncomingProjectile, Projectile
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
from .police_decision import CallPolice
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
    Walk,
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
