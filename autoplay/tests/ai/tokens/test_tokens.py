import unittest
from dataclasses import dataclass

from sor_autoplay.ai.tokens import Verb, Information, Token, find, find_all


@dataclass(frozen=True, slots=True, kw_only=True)
class _Widget(Information):
    slot: str
    value: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class _OtherWidget(Information):
    slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _Order(Verb):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class _UnusedVerb(Verb):
    pass


class TokenHierarchyTests(unittest.TestCase):
    def test_information_and_verb_are_tokens(self) -> None:
        self.assertTrue(issubclass(Information, Token))
        self.assertTrue(issubclass(Verb, Token))

    def test_default_priority_is_zero(self) -> None:
        widget = _Widget(slot="obj00")
        self.assertEqual(widget.priority, 0)

    def test_priority_is_settable_and_independent_of_other_fields(self) -> None:
        widget = _Widget(slot="obj00", value=7, priority=3)
        self.assertEqual(widget.priority, 3)
        self.assertEqual(widget.value, 7)

    def test_tokens_are_frozen_and_hashable(self) -> None:
        widget = _Widget(slot="obj00")
        with self.assertRaises(Exception):
            widget.value = 9  # type: ignore[misc]
        context = {widget, _Order()}
        self.assertIn(widget, context)


class FindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.widget_a = _Widget(slot="obj00", value=1)
        self.widget_b = _Widget(slot="obj01", value=2)
        self.other = _OtherWidget(slot="obj00")
        self.order = _Order()
        self.context = {self.widget_a, self.widget_b, self.other, self.order}

    def test_find_returns_a_match_by_type(self) -> None:
        found = find(self.context, _Order)
        self.assertIs(found, self.order)

    def test_find_returns_none_when_absent(self) -> None:
        self.assertIsNone(find(set(), _Order))

    def test_find_narrows_by_slot(self) -> None:
        found = find(self.context, _Widget, slot="obj01")
        self.assertIs(found, self.widget_b)

    def test_find_with_slot_ignores_tokens_without_a_slot_attribute(self) -> None:
        self.assertIsNone(find({self.order}, _Order, slot="anything"))

    def test_find_does_not_conflate_sibling_types_sharing_a_slot(self) -> None:
        found = find(self.context, _OtherWidget, slot="obj00")
        self.assertIs(found, self.other)

    def test_find_all_returns_every_match(self) -> None:
        results = find_all(self.context, _Widget)
        self.assertCountEqual(results, [self.widget_a, self.widget_b])

    def test_find_all_returns_empty_list_when_no_matches(self) -> None:
        self.assertEqual(find_all(self.context, _UnusedVerb), [])


if __name__ == "__main__":
    unittest.main()
