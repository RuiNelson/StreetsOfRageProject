"""duel.DuelStyle: the betrayal duel fought for a person to enjoy (user:
"Faz uma luta mais interessante, mais aleatória, com mais movimentos
diferentes. Menos eficiência fria." -- "Sem modificar o comportamento que a
IA terá com os inimigos.")."""

import random
import unittest
from collections import Counter

from sor_autoplay.ai import duel
from sor_autoplay.ai.decide import generate_verb_tokens
from sor_autoplay.ai.duel import DuelStyle
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    CameraRange,
    CounterGrab,
    DuelStep,
    FlipHold,
    GrabEnemy,
    JumpAttack,
    MrXOffice,
    PlayerDuel,
    Punch,
    Stage,
    Supplex,
    ThrowHeldEnemy,
    Verb,
    WalkToNearEnemy,
    find_all,
)
from sor_autoplay.phases import CombatPhase

from .test_decide import make_enemy, make_myself, make_rival


def _duel(*tokens) -> set:
    return {
        PlayerDuel(),
        MrXOffice(),
        Stage(level_index=7, direction="left"),
        CameraRange(left=0, right=400, top=0, bottom=200),
        *tokens,
    }


def _pick(style: DuelStyle, context: set) -> Verb:
    context = context | generate_verb_tokens(context)
    context = style.steer(context)
    verbs = find_all(determine_priority_verb(context), Verb)
    assert len(verbs) == 1, verbs
    return verbs[0]


def _style(seed: int = 0) -> DuelStyle:
    return DuelStyle(rng=random.Random(seed))


class OutsideTheDuelTests(unittest.TestCase):
    def test_enemies_are_never_restyled(self) -> None:
        # No PlayerDuel: the context comes back as it went in, verbs and all.
        context = {make_myself(), make_enemy(world_x=125), Stage(level_index=0, direction="right")}
        context |= generate_verb_tokens(context)
        style = _style()

        for _ in range(50):
            self.assertIs(style.steer(context), context)
        self.assertIsNone(style.tactic)

    def test_the_duel_ending_forgets_the_tactic(self) -> None:
        style = _style()
        _pick(style, _duel(make_myself(), make_rival(world_x=200)))
        self.assertIsNotNone(style.tactic)

        style.steer({make_myself()})
        self.assertIsNone(style.tactic)


class TacticTests(unittest.TestCase):
    def test_every_tick_names_one_verb_at_the_rival(self) -> None:
        style = _style(3)
        for x in range(60, 340, 7):
            verb = _pick(style, _duel(make_myself(), make_rival(world_x=x, world_y=100 + x % 20)))
            self.assertEqual(getattr(verb, "target_slot", None), "P2")

    def test_many_tactics_and_moves_over_a_fight(self) -> None:
        # The same scene, replayed tick after tick: a cold fight is one verb;
        # the style plays several tactics and several kinds of verb.
        tactics: Counter = Counter()
        kinds: Counter = Counter()
        for seed in range(12):
            style = _style(seed)
            for tick in range(240):
                rival_x = 100 + 20 + (tick * 3) % 70
                verb = _pick(style, _duel(make_myself(), make_rival(world_x=rival_x)))
                tactics[style.tactic] += 1
                kinds[type(verb).__name__] += 1
        self.assertGreaterEqual(len(tactics), 6, tactics)
        for kind in ("Punch", "DuelStep", "GrabEnemy", "WalkToNearEnemy"):
            self.assertIn(kind, kinds)
        self.assertLess(max(kinds.values()) / sum(kinds.values()), 0.7, kinds)

    def test_a_punch_waits_for_a_reaction(self) -> None:
        style = _style()
        style._tactic = style._new_tactic(duel.PRESS, make_myself(), make_rival())
        style._tactic.reaction = 5
        style._tactic.burst = 2
        picks = [_pick(style, _duel(make_myself(), make_rival(world_x=125))) for _ in range(5)]

        self.assertTrue(all(isinstance(v, DuelStep) for v in picks[:4]), picks)
        self.assertIsInstance(picks[4], Punch)

    def test_a_swing_from_inside_reach_is_answered(self) -> None:
        # Under pressure a person hits back, whatever they were doing -- or,
        # now and then, steps away from the swing.
        punched = 0
        for seed in range(10):
            style = _style(seed)
            style._tactic = style._new_tactic(duel.WAIT, make_myself(), make_rival())
            picks = [
                _pick(style, _duel(make_myself(), make_rival(world_x=125, combat_phase=CombatPhase.ATTACKING)))
                for _ in range(duel.PRESSURE_REACTION_TICKS[1] + 2)
            ]
            if any(isinstance(v, Punch) for v in picks):
                punched += 1
            else:
                self.assertEqual(style.tactic, duel.BACK_OFF, (seed, picks))
        self.assertGreaterEqual(punched, 7)

    def test_a_burst_ends_after_its_presses(self) -> None:
        style = _style(1)
        burst = style._tactic = style._new_tactic(duel.PRESS, make_myself(), make_rival())
        burst.reaction = 0
        burst.burst = 2
        punches = 0
        for _ in range(20):
            verb = _pick(style, _duel(make_myself(), make_rival(world_x=125)))
            if style._tactic is not burst:
                break
            punches += isinstance(verb, Punch)

        self.assertEqual(punches, 2)
        self.assertIsNot(style._tactic, burst)

    def test_a_knocked_down_rival_is_let_up(self) -> None:
        style = _style()
        for _ in range(20):
            verb = _pick(
                style,
                _duel(make_myself(), make_rival(world_x=125, combat_phase=CombatPhase.KNOCKDOWN)),
            )
            self.assertIsInstance(verb, DuelStep)
            self.assertGreaterEqual(abs(verb.goal_x - 125), duel.LET_UP_SPACING_X[0])

    def test_a_jump_under_way_keeps_its_kick(self) -> None:
        style = _style()
        for state in (0x10, 0x12):
            verb = _pick(style, _duel(make_myself(action_state=state), make_rival(world_x=150)))
            self.assertEqual(verb, JumpAttack(actor_slot="P1", target_slot="P2"))

    def test_the_jump_in_launches_a_kick(self) -> None:
        launched = False
        for seed in range(10):
            style = _style(seed)
            style._tactic = style._new_tactic(duel.JUMP_IN, make_myself(), make_rival())
            for _ in range(40):
                gap = abs(style._tactic.goal_dx) if style._tactic else 60
                verb = _pick(style, _duel(make_myself(), make_rival(world_x=100 + gap)))
                if isinstance(verb, JumpAttack):
                    launched = True
                    break
                if style.tactic != duel.JUMP_IN:
                    break
        self.assertTrue(launched)

    def test_grab_walks_into_the_body(self) -> None:
        style = _style()
        style._tactic = style._new_tactic(duel.GRAB, make_myself(), make_rival())

        self.assertEqual(
            _pick(style, _duel(make_myself(), make_rival(world_x=140))),
            GrabEnemy(actor_slot="P1", target_slot="P2"),
        )

    def test_escaping_a_hold_is_the_pipelines(self) -> None:
        style = _style()
        held = make_myself(combat_phase=CombatPhase.HELD_BY_ENEMY, action_state=0x78)

        verb = _pick(style, _duel(held, make_rival(world_x=110)))

        self.assertIsInstance(verb, CounterGrab)


class HoldScriptTests(unittest.TestCase):
    def test_the_hold_scripts_vary(self) -> None:
        firsts: Counter = Counter()
        for seed in range(40):
            style = _style(seed)
            holding = make_myself(action_state=0x60, held_enemy_slot="P2")
            rival = make_rival(world_x=118, combat_phase=CombatPhase.GRABBED)
            for _ in range(8):
                verb = _pick(style, _duel(holding, rival))
                if not isinstance(verb, DuelStep):
                    firsts[type(verb)] += 1
                    break
        self.assertIn(AttackHeldEnemy, firsts)
        self.assertIn(FlipHold, firsts)
        self.assertIn(ThrowHeldEnemy, firsts)

    def test_a_back_hold_still_suplexes(self) -> None:
        style = _style()
        style._hold = duel._Hold(script=(duel.KNEE,), step=0)
        holding = make_myself(action_state=0x66, held_enemy_slot="P2")

        verb = _pick(style, _duel(holding, make_rival(world_x=118, combat_phase=CombatPhase.GRABBED)))

        self.assertIsInstance(verb, Supplex)


class HealthLeanTests(unittest.TestCase):
    def _draws(self, my_health: int, rival_health: int) -> Counter:
        counts: Counter = Counter()
        style = _style(7)
        actor = make_myself(health=my_health)
        rival = make_rival(world_x=200, health=rival_health)
        for _ in range(3000):
            counts[style._draw(actor, rival, []).name] += 1
        return counts

    def test_a_lead_plays_calmer(self) -> None:
        ahead = self._draws(80, 20)
        behind = self._draws(20, 80)
        calm = (duel.FOOTSIE, duel.WAIT, duel.BACK_OFF, duel.CIRCLE)

        self.assertGreater(sum(ahead[t] for t in calm), sum(behind[t] for t in calm))
        self.assertGreater(behind[duel.PRESS], ahead[duel.PRESS])


if __name__ == "__main__":
    unittest.main()
