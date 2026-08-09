# AI Emergency Refactor Prompt

Copy the block below into an LLM session to convert the emergency calculation
from fixed numbers to observation/inference-token-based scoring.

```text
Convert the emergency ranking in `autoplay/src/sor_autoplay/ai/priority.py` from hard-coded static numbers to a calculation driven by the `Information` tokens (observations + inferences) present in the `Context`.

## Background

`autoplay/` is a Python 3.11 observer + symbolic AI for a Streets of Rage recompilation. The AI pipeline (`src/sor_autoplay/ai/`) builds a per-tick `Context` (a `set[Token]`):

1. `observe.py` — `generate_direct_observation_tokens(snapshot, player_index)` reads an already-fetched `GameSnapshot` and emits `Observed` tokens (characters, enemies, weapons, pickups, breakables, pits, projectiles, `CameraRange`, `Stage`, …).
2. `inference.py` — `generate_inference_tokens(context)` derives `Inferred` tokens from observed ones (currently only `IncomingProjectile`).
3. `decide.py` — `generate_decision_tokens(context)` produces candidate `Decision` tokens via `should_*` generators (gated on `AnimationInProgress` etc.).
4. `priority.py` — `determine_priority_decision(context)` ranks the `Decision` tokens by **emergency**, keeps only the highest-ranked one (this doubles as target selection: several `Punch` candidates against different enemies collapse to one), and returns the context with all `Information` tokens plus the single surviving `Decision`.
5. `execute.py` — executes the surviving decision via the gamepad.

Token classes live in `src/sor_autoplay/ai/tokens/` (bases in `tokens.py`; `character.py`, `enemy.py`, `essential.py`, `hazard_tokens.py`, `pickup_tokens.py`, `walk_decisions.py`, `attack_decisions.py`, `police_decision.py`), all re-exported from `tokens/__init__.py`. Use `find(context, cls, slot=…)` / `find_all(context, cls)` to resolve tokens. The `Token.priority` field is a **static tie-breaker only** — it must play no role in emergency scoring.

## Current behaviour (numeric outcomes are the ground truth — preserve them)

`priority.py` `_emergency(decision, context)` returns 0–100 from module constants; some cases depend on the targeted token or the actor:

- `CounterGrab` 100 (always)
- `CallPolice` 88 (always)
- `RearAttack` 60 if its target `Enemy` is `is_dangerous(target.combat_phase)`, else 55
- `Punch` 60 if target `is_punishable(...)`, else 20
- `SmashBreakable` 16
- Hold moves, always when produced: `ThrowHeldEnemy` 70, `Supplex` 68, `FlipHold` 66, `AttackHeldEnemy` 64, `ReleaseGrab` 50
- `JumpAttack` 28 if target punishable, else 18
- `ThrowKnife` 25
- `WalkToNearEnemy` 14
- `WalkToAdvanceStage` 12 (only produced when no live enemy remains)
- `WalkToBreakable` 14
- `WalkToWeapon` 8
- `WalkToPickup`: 50 if target is `HealthPickup` and actor `health_percent < 40.0`; 15 if `HealthPickup`; 12 `LifePickup`; 9 `SpecialPickup`; 3 `ScorePickup` (fallback 3)

`tests/ai/test_priority.py` encodes these behaviours and must keep passing (update only to reflect the new architecture while asserting the same outcomes).

## The goal

Compute emergency from the **presence (or absence) of `Information` tokens** and from their attributes/conditions, instead of constants. Each concrete `Decision` class docstring already declares its intended formula in `Raises emergency: …` lines (see `CLAUDE.md` → "Token docstring convention") — those lines are the specification. Examples:

- `Punch`: `(Enemy when in a punishable phase)×60, Enemy×20` → 60 when the decision's target `Enemy` is punishable, else 20.
- `WalkToPickup`: `(HealthPickup when the actor's health is critical)×50, HealthPickup×15, LifePickup×12, SpecialPickup×9, ScorePickup×3` → score from the target `Pickup` subclass + actor health.
- `CounterGrab`: `(Myself when held by an enemy)×100` → e.g. `Myself.combat_phase == HELD_BY_ENEMY`.
- `WalkToAdvanceStage`: `(no live Enemy anywhere)×12` → the *absence* of live `Enemy` tokens.

Requirements:

1. Keep the same numeric outcomes for the same situations (docstrings + `test_priority.py` are ground truth). Do not retune the numbers.
2. Emergency must be a function of the `Context`'s `Information` tokens; conditions about a specific target must be evaluated against the decision's `target_slot` (look up with `find(context, Enemy, slot=…)` etc.).
3. Where a condition is naturally a derived/aggregate judgement — e.g. "rear threat behind the player" (`RearAttack`, `ThrowHeldEnemy`), "cluster of enemies pressing the actor" (`JumpAttack`, `Punch`) — introduce new `Inferred` tokens, at minimum `EnemyNearTheRearOfMyself` and `ClusterOfEnemies`: generated in `inference.py`, exported from `tokens/__init__.py`, added to `TokenMap.md`, with tests. Only add an inferred token that at least one formula actually consumes; if an existing observed token already expresses the condition, use it instead.
4. Do not change `decide.py`'s `should_*` generators — they decide *whether* a decision is possible; the new ranking decides *how urgent* it is.
5. Preserve `determine_priority_decision`'s contract from `AI.md` (section "`determine_priority_decision`"): rank by emergency, retain only the top `Decision`, break ties with the static `priority` field, and when still tied log a warning and pick at random.
6. Score each candidate decision against **its own** target (per-instance); where a docstring lists alternatives, use the applicable one (max/matching branch), never a sum across all tokens of a kind.

Suggested architecture (your call, keep it simple): one `_emergency` function per concrete `Decision` class or a dispatch table in `priority.py` that consults `Information` tokens; named weights at module scope of `priority.py` (they are only *contributions* to emergency, not emergency itself).

## Conventions & files to update

- Python 3.11; token dataclasses use `frozen=True, slots=True, kw_only=True`; no `type: ignore` without a reason; no unnecessary comments.
- Docstrings follow `CLAUDE.md` → "Token docstring convention" (line 1 description; Inferred line 2 = conditions + generating function; Decision line 2 = produced by `should_*` + conditions; Decision line 3 = `Raises emergency: …`). If a formula cannot be honoured, flag it instead of silently changing behaviour.
- Any new token class must be added to `TokenMap.md` (validate by rendering with `mmdc`).
- Update `CLAUDE.md`'s "AI surface" table rows (`priority.py`, `tokens/`, `inference.py`) if they become stale.
- Tests: extend `tests/ai/test_priority.py` for the token-driven scoring (punishable vs non-punishable target, critical vs full health pickup, rear-threat/cluster inferred tokens changing the winner); token-class tests for new inferred tokens in `tests/ai/tokens/`; keep the whole suite green.

## Validation

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

(no live host needed.) Report: files changed, the new emergency mechanism, new tokens (if any), test results, and any docstring formula you could not honour.
```
