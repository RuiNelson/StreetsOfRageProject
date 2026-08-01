"""Small dependency-free fuzzy inference primitives.

The autoplay policy uses fuzzy truth values for genuinely graded concepts such
as ``near``, ``dangerous`` and ``low health``.  Hard ROM constraints remain
ordinary predicates; fuzzy scores never make an impossible action legal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def rising(value: float, zero_at: float, one_at: float) -> float:
    """Linear membership that rises from zero to one."""

    if one_at <= zero_at:
        raise ValueError("one_at must be greater than zero_at")
    return clamp01((value - zero_at) / (one_at - zero_at))


def falling(value: float, one_at: float, zero_at: float) -> float:
    """Linear membership that falls from one to zero."""

    if zero_at <= one_at:
        raise ValueError("zero_at must be greater than one_at")
    return 1.0 - rising(value, one_at, zero_at)


def triangle(value: float, left: float, peak: float, right: float) -> float:
    """Triangular membership with a single full-truth peak."""

    if not left < peak < right:
        raise ValueError("triangle requires left < peak < right")
    if value <= left or value >= right:
        return 0.0
    if value == peak:
        return 1.0
    if value < peak:
        return rising(value, left, peak)
    return falling(value, peak, right)


@dataclass(frozen=True, slots=True)
class FuzzyRule:
    """Zero-order Sugeno rule over named fuzzy facts."""

    name: str
    antecedents: tuple[str, ...]
    consequent: float
    connective: str = "and"
    weight: float = 1.0

    def activation(self, facts: Mapping[str, float]) -> float:
        values = tuple(clamp01(facts.get(term, 0.0)) for term in self.antecedents)
        if not values:
            return clamp01(self.weight)
        if self.connective == "and":
            truth = min(values)
        elif self.connective == "or":
            truth = max(values)
        else:
            raise ValueError(f"unsupported fuzzy connective {self.connective!r}")
        return clamp01(truth * self.weight)


@dataclass(frozen=True, slots=True)
class FuzzyResult:
    value: float
    activations: tuple[tuple[str, float], ...]


class FuzzyInference:
    """Evaluate deterministic Sugeno rules and retain an explanation trace."""

    def __init__(self, rules: tuple[FuzzyRule, ...], *, default: float = 0.0) -> None:
        self.rules = rules
        self.default = clamp01(default)

    def infer(self, facts: Mapping[str, float]) -> FuzzyResult:
        numerator = 0.0
        denominator = 0.0
        fired: list[tuple[str, float]] = []
        for rule in self.rules:
            activation = rule.activation(facts)
            if activation <= 0.0:
                continue
            numerator += activation * clamp01(rule.consequent)
            denominator += activation
            fired.append((rule.name, activation))
        value = self.default if denominator == 0.0 else numerator / denominator
        return FuzzyResult(clamp01(value), tuple(fired))
