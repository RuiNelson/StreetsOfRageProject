# Token Map

Mermaid class diagram of the AI token hierarchy under
`src/sor_autoplay/ai/`: the token classes and their inheritance only.
Keep this diagram in sync with the `ai/` sources — see `CLAUDE.md`.

```mermaid
classDiagram
    direction LR

    Token <|-- Information
    Token <|-- Decision

    Information <|-- Stage
    Information <|-- CameraRange
    Information <|-- AnimationInProgress

    Information <|-- Projectile
    Information <|-- IncomingProjectile
    Information <|-- Breakable

    Information <|-- Weapon
    Information <|-- Pickup
    Pickup <|-- HealthPickup
    Pickup <|-- LifePickup
    Pickup <|-- SpecialPickup
    Pickup <|-- ScorePickup

    Information <|-- Character
    Character <|-- PlayableCharacter
    PlayableCharacter <|-- Myself
    PlayableCharacter <|-- Partner

    Information <|-- Enemy
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
