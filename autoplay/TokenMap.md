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

    Observed <|-- Enemy
    Enemy <|-- Garcia
    Enemy <|-- Signal
    Enemy <|-- HakuRo
    Enemy <|-- Nora
    Enemy <|-- Jack
    Enemy <|-- Boss
    Boss <|-- BespokeBoss
    BespokeBoss <|-- Abadede
    BespokeBoss <|-- MrX
    Boss <|-- LaterBoss
    LaterBoss <|-- Souther
    LaterBoss <|-- Antonio
    LaterBoss <|-- Bongo
    LaterBoss <|-- Onihime

    Decision <|-- Walk
    Walk <|-- WalkToNearEnemy
    Walk <|-- WalkToAdvanceStage
    Walk <|-- WalkToWeapon
    Walk <|-- WalkToPickup
    Walk <|-- WalkToBreakable

    Decision <|-- Attack
    Attack <|-- Punch
    Attack <|-- ThrowKnife
    Attack <|-- Supplex
    Attack <|-- KneeStrike
    Attack <|-- ThrowHeldEnemy
    Attack <|-- FlipHold
    Attack <|-- ReleaseGrab
    Attack <|-- JumpAttack
    Attack <|-- SmashBreakable
    Attack <|-- RearAttack
    Attack <|-- CounterGrab

    Decision <|-- CallPolice
```
