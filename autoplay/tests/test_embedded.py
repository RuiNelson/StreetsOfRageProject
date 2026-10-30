"""``sor_ai.embedded.run``: what the ``sor`` host calls, against a fake host."""

from __future__ import annotations

import unittest

from sor_ai import embedded


class FakeHost:
    def __init__(self, polls_until_stop: int) -> None:
        self.polls_until_stop = polls_until_stop
        self.lines: list[str] = []

    def wait_stop(self, timeout: float) -> bool:
        self.polls_until_stop -= 1
        return self.polls_until_stop <= 0

    def log(self, text: str) -> None:
        self.lines.append(text)


class RunTests(unittest.TestCase):
    def test_runs_until_the_host_asks_it_to_end(self) -> None:
        host = FakeHost(polls_until_stop=3)
        embedded.run(host)
        self.assertEqual(host.polls_until_stop, 0)
        self.assertEqual(host.lines[-1], "ended")


if __name__ == "__main__":
    unittest.main()
