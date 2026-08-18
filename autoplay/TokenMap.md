# Token Map

Mermaid class diagram of the AI token hierarchy under
`src/sor_autoplay/ai/`: the token classes and their inheritance only.
Keep this diagram in sync with the `ai/` sources — see `CLAUDE.md`.

```mermaid
classDiagram
    direction LR

    Token <|-- Information
    Token <|-- Verb

    Information <|-- Observed
    Information <|-- Inferred

    Observed <|-- Essential
    Essential <|-- Stage
    Essential <|-- CameraRange
    Essential <|-- AnimationInProgress
    Essential <|-- InContinueMenu
    Essential <|-- InMrXDialog

    Observed <|-- Projectile
    Inferred <|-- IncomingProjectile
    Inferred <|-- SafeSpot
    Observed <|-- StageObjects
    StageObjects <|-- Breakable
    StageObjects <|-- Pit

    Observed <|-- Weapon
    Inferred <|-- WeaponUpgrade
    Observed <|-- Pickup
    Pickup <|-- HealthPickup
    Pickup <|-- LifePickup
    Pickup <|-- SpecialPickup
    Pickup <|-- ScorePickup

    Observed <|-- Character
    Character <|-- PlayableCharacter
    PlayableCharacter <|-- Myself
    PlayableCharacter <|-- Partner

    Character <|-- Enemy
    Enemy <|-- Grunt
    Grunt <|-- Garcia
    Grunt <|-- Signal
    Grunt <|-- HakuRo
    Grunt <|-- Nora
    Grunt <|-- Jack
    Enemy <|-- Boss
    Boss <|-- Abadede
    Boss <|-- MrX
    Boss <|-- Souther
    Boss <|-- Antonio
    Boss <|-- Bongo
    Boss <|-- Onihime

    Inferred <|-- ClosingEnemy
    Inferred <|-- IncomingMelee
    Inferred <|-- PunishWindow
    Inferred <|-- Surrounded
    Inferred <|-- TargetInReach
    Inferred <|-- GrabOpportunity
    Inferred <|-- AntonioIsGoingToKick
    Inferred <|-- SoutherIsGoingToSlash
    Inferred <|-- SoutherPunishesJump

    Verb <|-- Walk
    Walk <|-- WalkToNearEnemy
    Walk <|-- WalkToAdvanceStage
    Walk <|-- WalkToWeapon
    Walk <|-- WalkToPickup
    Walk <|-- RetreatFromDanger
    Walk <|-- ProjectileSidestep
    Walk <|-- DodgeAntonioKick
    Walk <|-- DodgeSoutherSlash

    Verb <|-- Attack
    Attack <|-- MeleeAttacks
    Attack <|-- GrabMechanics
    MeleeAttacks <|-- Punch
    MeleeAttacks <|-- HitAntonioBoomerang
    Attack <|-- MeleeWeaponAttack
    Attack <|-- WeaponAttacks
    WeaponAttacks <|-- ThrowKnife
    WeaponAttacks <|-- ThrowPepper
    GrabMechanics <|-- GrabEnemy
    GrabMechanics <|-- Supplex
    GrabMechanics <|-- AttackHeldEnemy
    GrabMechanics <|-- ThrowHeldEnemy
    GrabMechanics <|-- FlipHold
    GrabMechanics <|-- ReleaseGrab
    MeleeAttacks <|-- JumpAttack
    Attack <|-- OpenBreakable
    MeleeAttacks <|-- RearAttack
    GrabMechanics <|-- CounterGrab

    Attack <|-- CallPolice

    Verb <|-- Dialog
    Dialog <|-- HandleContinueMenu
    Dialog <|-- HandleMrXDialog

    Verb <|-- Recovery
    Recovery <|-- TechRecover
```
