# Token Map

Mermaid class diagram of the AI token hierarchy under
`src/sor_autoplay/ai/`: the token classes and their inheritance only.
Keep this diagram in sync with the `ai/` sources — see `CLAUDE.md`.

```mermaid
classDiagram
    direction LR

    Token <|-- Information
    Token <|-- Decision

    Information <|-- Observed
    Information <|-- Inferred

    Observed <|-- Stage
    Observed <|-- CameraRange
    Observed <|-- AnimationInProgress

    Observed <|-- Projectile
    Inferred <|-- IncomingProjectile
    Observed <|-- Breakable

    Observed <|-- Weapon
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

    Decision <|-- Walk
    Walk <|-- WalkToNearEnemy
    Walk <|-- WalkToAdvanceStage
    Walk <|-- WalkToWeapon
    Walk <|-- WalkToPickup
    Walk <|-- WalkToBreakable

    Decision <|-- Attack
    Attack <|-- MeleeAttacks
    Attack <|-- GrabMechanics
    MeleeAttacks <|-- Punch
    Attack <|-- WeaponAttacks
    WeaponAttacks <|-- ThrowKnife
    GrabMechanics <|-- Supplex
    GrabMechanics <|-- AttackHeldEnemy
    GrabMechanics <|-- ThrowHeldEnemy
    GrabMechanics <|-- FlipHold
    GrabMechanics <|-- ReleaseGrab
    MeleeAttacks <|-- JumpAttack
    Attack <|-- SmashBreakable
    MeleeAttacks <|-- RearAttack
    GrabMechanics <|-- CounterGrab

    Attack <|-- CallPolice
```
