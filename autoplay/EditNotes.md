# AI.md Changelog and reasons

- Removed `Sidestep` is a more advanced feature that will be added later in development
- Removed `WalkToCoordinate`, as it represents an action, not an intention, all `Decison` are intents.
- Removed `DangerZone`, is too complicated for now, will be added later in development.
- `inform_hud` added, replace the current mecahnism that passes the winning decision to the HUD with this one.
- Added the `TargetInReach` family, `IncomingMelee`, `PunishWindow`,
  `Surrounded`, `SafeSpot` and `WeaponUpgrade` as `Inferred` tokens, and
  documented them beside `IncomingProjectile`/`ClosingEnemy`. The `could_*`
  and `_emergency_*` functions now read them instead of each recomputing the
  same geometry; the geometry itself moved to `ai/reach.py`.
- Documented `CombatPhase.STUNNED` for ordinary enemies (ROM states `$0200`
  hitstun and `$0400` pepper-spray immobilization, both counting `+$50`
  down), keeping the police-special sweep on `SCRIPTED`.
- `Sidestep` is still not a decision of its own; `SafeSpot` gives
  `RetreatFromDanger`'s executor somewhere deliberate to go instead.
- A stun *lowers* the emergency of attacking that enemy instead of raising
  it: `Attack` on a stunned `Grunt` is capped between the `Walk` tiers and a
  plain strike, so a live enemy (or the `RearAttack` escape) always comes
  first, but the AI still finishes the stunned one off rather than walking
  away. Knockdown keeps the full punishable tier.
