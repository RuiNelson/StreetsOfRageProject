"""Small deterministic forward-chaining inference engine.

The engine knows nothing about Streets of Rage. Domain knowledge is expressed
as immutable facts and production rules in ``expert.py``. Keeping inference
generic gives scripted and future learned policies the same explainable fact
surface without coupling it to controller inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Hashable, Iterable, TypeVar


FactT = TypeVar("FactT", bound=Hashable)


@dataclass(frozen=True, slots=True)
class Rule(Generic[FactT]):
    """One production rule evaluated against the accumulating fact set."""

    name: str
    conclusions: frozenset[FactT]
    required: frozenset[FactT] = frozenset()
    forbidden: frozenset[FactT] = frozenset()
    salience: int = 0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("rule name must not be empty")
        if not self.conclusions:
            raise ValueError(f"rule {self.name!r} must have a conclusion")
        if self.required & self.forbidden:
            raise ValueError(f"rule {self.name!r} both requires and forbids a fact")

    def matches(self, facts: set[FactT]) -> bool:
        return self.required <= facts and not self.forbidden & facts


@dataclass(frozen=True, slots=True)
class InferenceResult(Generic[FactT]):
    facts: frozenset[FactT]
    fired_rules: tuple[str, ...]


class InferenceEngine(Generic[FactT]):
    """Reach a deterministic fixed point by forward chaining production rules."""

    def __init__(self, rules: Iterable[Rule[FactT]]) -> None:
        self.rules = tuple(sorted(rules, key=lambda rule: (-rule.salience, rule.name)))

    def infer(self, initial_facts: Iterable[FactT]) -> InferenceResult[FactT]:
        facts = set(initial_facts)
        fired: list[str] = []
        fired_names: set[str] = set()

        changed = True
        while changed:
            changed = False
            for rule in self.rules:
                if rule.name in fired_names or not rule.matches(facts):
                    continue
                additions = rule.conclusions - facts
                if not additions:
                    fired_names.add(rule.name)
                    continue
                facts.update(additions)
                fired.append(rule.name)
                fired_names.add(rule.name)
                changed = True

        return InferenceResult(frozenset(facts), tuple(fired))
