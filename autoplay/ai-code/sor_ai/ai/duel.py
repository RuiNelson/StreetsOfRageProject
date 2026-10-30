"""Mr. X's betrayal duel, fought like a person rather than a solver.

User, in Portuguese: "Quando a IA luta contra um humano (quando há traição do
parceiro em frente ao Mr. X), é extremamente eficiente, mas não é uma luta
interessante para um humano. Faz uma luta mais interessante, mais aleatória,
com mais movimentos diferentes. Menos eficiência fria." -- and "Sem modificar
o comportamento que a IA terá com os inimigos."

The generic pipeline fights the other player (a ``RivalPlayer``) the way it
fights a grunt: walk to the punch's stop point, press B on the first tick the
band holds, every tick, and run the whole hold chain. Against a person that
is a machine: a superhuman reaction to every opening, the same move every
time, no footwork. ``DuelStyle`` sits between the ``could_*`` generators and
the ranking (``loop.AgentLoop.tick``) and, **only while ``PlayerDuel``
holds**, replaces the tick's candidates with one verb it picked itself from a
*tactic* it keeps for a while:

- ``press`` -- walk in and throw a short burst (1-4 presses, a human's
  rhythm between them); a rival standing behind may get the rear chord;
- ``grab`` -- walk into the rival's body for the hold, then a randomly picked
  hold script (knees and a throw, a flip and a suplex, a straight throw, a
  knee and letting go ...);
- ``jump_in`` -- back to a launch distance and jump-kick in;
- ``footsie`` -- keep a distance, drift between lanes, punish a careless
  walk-in only sometimes;
- ``circle`` -- walk round to another lane (and sometimes the other side)
  before pressing;
- ``wait`` -- stand and let the rival come;
- ``back_off`` -- give ground, usually right after a burst or when the rival
  swings;
- ``item`` -- go for a weapon or food the generic pipeline offers.

A rival stepping into reach unasked is answered after a person's reaction,
and not always with a punish; a rival swinging from inside reach is hit back
at once, whatever the tactic -- under pressure a person presses.

Each tactic is drawn from weights that lean on the health difference: the
further ahead the AI is, the calmer and slower it plays (more spacing and
waiting, longer reactions, shorter bursts); behind, it presses. A knocked
down rival is let up rather than met on the wake-up frame.

What it leaves to the generic pipeline: the dialogs, escaping a hold
(``CounterGrab``), the landing tech, a flight already in the air, every
reaction state of the actor's own, and everything outside the duel -- with no
``PlayerDuel`` in the context ``steer`` returns it untouched, so no enemy is
ever fought differently.

One tick here is one ``AgentLoop`` tick, ~2 game frames at every cadence the
harness runs (33 ms, ``--poll-ms 16`` under ``--turbo 2``, lockstep).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..phases import CombatPhase
from . import jump_kick
from . import navigation as nav
from . import reach
from .tokens import (
    AttackHeldEnemy,
    CounterGrab,
    DuelStep,
    FlipHold,
    GrabEnemy,
    HandleContinueMenu,
    HandleMrXDialog,
    JumpAttack,
    MeleeWeaponAttack,
    Myself,
    PLAYER_MAX_HEALTH,
    PlayerDuel,
    Punch,
    RearAttack,
    ReleaseGrab,
    ReleaseToRegrab,
    RivalPlayer,
    Supplex,
    TechRecover,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
    Verb,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
    find,
    find_all,
)
from .tokens import punch_outer_x

# Verbs the style never overrides: the dialogs, and the two escapes from a
# state the actor is already in.
_LEFT_TO_THE_PIPELINE = (HandleContinueMenu, HandleMrXDialog, CounterGrab, TechRecover)

# The jump family's states (execute.JUMP_*_ACTIONS): crouch, flight, kick,
# landing, unarmed and armed.
_JUMP_STATES = frozenset({0x10, 0x12, 0x14, 0x16, 0x3C, 0x3E, 0x40, 0x42})

PRESS = "press"
GRAB = "grab"
JUMP_IN = "jump_in"
FOOTSIE = "footsie"
CIRCLE = "circle"
WAIT = "wait"
BACK_OFF = "back_off"
ITEM = "item"
LET_UP = "let_up"  # not drawn: the rival is on the floor

# Base weights of each tactic, before the health lean.
_WEIGHTS = {
    PRESS: 3.0,
    GRAB: 2.0,
    JUMP_IN: 1.6,
    FOOTSIE: 2.0,
    CIRCLE: 1.4,
    WAIT: 1.0,
    BACK_OFF: 0.4,
}
# Right after a burst or a hold has landed: give the rival a moment.
_WEIGHTS_AFTER_A_COMBO = {
    BACK_OFF: 1.4,
    WAIT: 1.2,
    FOOTSIE: 1.5,
    CIRCLE: 1.0,
    PRESS: 1.0,
    GRAB: 0.8,
    JUMP_IN: 0.8,
}
_AGGRESSIVE = frozenset({PRESS, GRAB, JUMP_IN})
_PATIENT = frozenset({FOOTSIE, CIRCLE, WAIT, BACK_OFF})
# How hard the health difference leans the draw: a lead of LEAD_SCALE health
# (half the bar) halves the aggressive weights and adds 70% to the patient.
LEAD_SCALE = PLAYER_MAX_HEALTH / 2
AGGRESSIVE_LEAN = 0.5
PATIENT_LEAN = 0.7
ITEM_WEIGHT = 2.0

# Ticks a tactic may run before another is drawn.
PRESS_TIMEOUT = 90
GRAB_TIMEOUT = 80
JUMP_IN_TIMEOUT = 90
CIRCLE_TIMEOUT = 70
ITEM_TIMEOUT = 120
FOOTSIE_TICKS = (30, 80)
WAIT_TICKS = (12, 40)
BACK_OFF_TICKS = (6, 14)

# A person's reaction to the rival stepping into reach: 4-10 ticks, ~130-330
# ms; LEAD_REACTION more at a full half-bar lead.
REACTION_TICKS = (4, 10)
LEAD_REACTION = 4
# A press that walked in itself has planned its hit: it only settles this
# long on arriving (LEAD_REACTION more at a half-bar lead). The reaction
# above is for the rival stepping into reach unasked. Measured live, a press
# that waited out a full reaction on arrival took most of its hits standing
# in reach (state $02/$03), 121 and 135 of ~210 per run.
ARRIVAL_TICKS = (0, 2)
# Ticks between two presses of a burst: a thumb, not a turbo button.
PRESS_GAP_TICKS = (0, 2)
# Burst lengths (presses) and their weights; the lead shortens them.
BURST_LENGTHS = (1, 2, 3, 4)
BURST_WEIGHTS = (3.0, 3.0, 2.0, 1.0)
# Where a press stands when the generic walk is not offered: just past the
# measured nearest a punch lands on a player (reach.RIVAL_PUNCH_MIN_X, 20).
PRESS_STAND_X = 26
# A rival behind the actor inside the chord's reach gets it this often.
REAR_ATTACK_CHANCE = 0.3
# A rival who starts a swing this close is backed away from this often.
DODGE_DISTANCE_X = 48
DODGE_CHANCE = 0.2
# ... and not again for this many ticks.
DODGE_COOLDOWN_TICKS = 40
# A rival swinging at the actor from inside its own reach is answered, by
# any tactic but the grab's walk-in, after this many ticks: under pressure a
# person hits back. Measured live against the cold pipeline, a style that
# only reacted on its own schedule spent most of the duel in hit reactions
# ($55-$5F) and dealt 48 against 849.
PRESSURE_REACTION_TICKS = (1, 3)
# A rival walking into reach while the AI spaces or waits is punished this
# often (more when behind on health, less when ahead).
PUNISH_CHANCE = 0.55
# A weapon in hand gets thrown at a rival in the envelope this often a tick.
THROW_CHANCE = 0.08

FOOTSIE_SPACING_X = (36, 64)
FOOTSIE_LANE_JITTER_Y = 12
FOOTSIE_REDRAW_TICKS = (15, 30)
CIRCLE_LANE_Y = (24, 32)
CIRCLE_PAST_X = 30
CIRCLE_ARRIVAL = 8
CIRCLE_CROSS_CHANCE = 0.4
BACK_OFF_X = (36, 56)
LET_UP_SPACING_X = (40, 60)
# JUMP_IN backs off to a launch point this far past the punch's outer edge.
JUMP_LAUNCH_PAST_PUNCH_X = (10, 22)
# A launch the kick model will not bless after this many ticks at the
# launch point goes anyway: a jump that misses is still a move.
JUMP_IN_PATIENCE = 25

# Hold scripts and their weights; each step is pressed when the hold offers
# it, else whatever the hold does offer is taken (from a back hold that is
# only the suplex).
KNEE = "knee"
THROW = "throw"
FLIP = "flip"
SUPLEX = "suplex"
RELEASE = "release"
HOLD_SCRIPTS: tuple[tuple[tuple[str, ...], float], ...] = (
    ((KNEE, KNEE, THROW), 3.0),
    ((KNEE, FLIP, SUPLEX), 2.0),
    ((FLIP, SUPLEX), 1.5),
    ((KNEE, KNEE, KNEE), 1.2),
    ((THROW,), 1.0),
    ((KNEE, RELEASE), 0.7),
)
# Ticks a fresh hold waits before its first move: a person noticing it.
HOLD_HESITATION_TICKS = (0, 5)
_HOLD_VERBS = {
    KNEE: (AttackHeldEnemy,),
    THROW: (ThrowHeldEnemy,),
    FLIP: (FlipHold,),
    SUPLEX: (Supplex,),
    RELEASE: (ReleaseGrab, ReleaseToRegrab),
}
_ANY_HOLD_VERB = (AttackHeldEnemy, ThrowHeldEnemy, FlipHold, Supplex, ReleaseGrab, ReleaseToRegrab)


@dataclass(slots=True)
class _Tactic:
    name: str
    ticks_left: int
    # press
    burst: int = 0
    presses: int = 0
    gap: int = 0
    rear_rolled: bool = False
    # press / footsie / wait: ticks the rival has stood in reach, and how
    # long this tactic takes to answer it
    in_reach_ticks: int = 0
    reaction: int = 0
    # footsie / circle / back_off / jump_in / let_up: the walk's goal,
    # relative to the rival (dx signed, dy signed)
    goal_dx: int = 0
    goal_dy: int = 0
    redraw: int = 0
    waypoints: list[tuple[int, int]] = field(default_factory=list)
    # jump_in
    launched: bool = False
    at_launch_ticks: int = 0
    # wait / back_off: an absolute standing point
    stand: tuple[int, int] | None = None


@dataclass(slots=True)
class _Hold:
    script: tuple[str, ...]
    step: int = 0
    hesitation: int = 0


class DuelStyle:
    """One AI player's fighting style for the betrayal duel (cross-tick)."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._tactic: _Tactic | None = None
        self._hold: _Hold | None = None
        self._after_combo = False
        self._rival_was_attacking = False
        self._dodge_cooldown = 0
        self._pressure_ticks = 0
        self._pressure_reaction = 0
        self._context: set = set()

    @property
    def tactic(self) -> str | None:
        """The tactic being played, or ``None`` outside the duel."""

        if self._hold is not None:
            return GRAB
        return self._tactic.name if self._tactic is not None else None

    def reset(self) -> None:
        self._tactic = None
        self._hold = None
        self._after_combo = False
        self._rival_was_attacking = False

    def steer(self, context: set) -> set:
        """The context with its verbs replaced by the style's pick, while
        the duel lasts; ``context`` itself otherwise."""

        if find(context, PlayerDuel) is None:
            self.reset()
            return context
        verb = self.choose(context)
        if verb is None:
            return context
        return {token for token in context if not isinstance(token, Verb)} | {verb}

    # -- the pick ----------------------------------------------------------

    def choose(self, context: set) -> Verb | None:
        self._context = context
        actor = find(context, Myself)
        rival = find(context, RivalPlayer)
        candidates = find_all(context, Verb)
        if actor is None or rival is None:
            return None
        if any(isinstance(verb, _LEFT_TO_THE_PIPELINE) for verb in candidates):
            return None
        if actor.combat_phase in (CombatPhase.HELD_BY_ENEMY, CombatPhase.HURT_PLAYER, CombatPhase.KNOCKDOWN):
            self._hold = None
            return None

        if actor.is_holding_enemy:
            if actor.held_enemy_slot != rival.slot:
                return None
            return self._hold_move(actor, rival, candidates)
        if self._hold is not None:
            # The hold is over: the body is down or away.
            self._hold = None
            self._after_combo = True
            self._tactic = None

        if actor.is_airborne or actor.action_base in _JUMP_STATES:
            # A jump under way: keep the direction held through the crouch
            # and press the kick edge in free flight (execute's jump state
            # machine). The generic pipeline offers no JumpAttack at the
            # rival on the ground, crouch included, and losing the held
            # direction in the crouch launches straight up.
            if self._tactic is not None and self._tactic.name == JUMP_IN:
                self._tactic.launched = True
            return JumpAttack(actor_slot=actor.slot, target_slot=rival.slot)

        rival_attacking = rival.combat_phase is CombatPhase.ATTACKING
        swing_started = rival_attacking and not self._rival_was_attacking
        self._rival_was_attacking = rival_attacking
        if self._dodge_cooldown > 0:
            self._dodge_cooldown -= 1

        if rival.combat_phase is CombatPhase.KNOCKDOWN or rival.is_defeated:
            if self._tactic is None or self._tactic.name != LET_UP:
                self._tactic = _Tactic(name=LET_UP, ticks_left=1, goal_dx=self._side(actor, rival) * self._roll(LET_UP_SPACING_X))
            return self._step_to_rival_offset(actor, rival, self._tactic)
        if self._tactic is not None and self._tactic.name == LET_UP:
            self._tactic = None

        if (
            swing_started
            and abs(rival.world_x - actor.world_x) <= DODGE_DISTANCE_X
            and self._dodge_cooldown == 0
            and (self._tactic is None or self._tactic.name != BACK_OFF)
        ):
            self._dodge_cooldown = DODGE_COOLDOWN_TICKS
            if self._rng.random() < DODGE_CHANCE:
                self._tactic = self._new_tactic(BACK_OFF, actor, rival)

        strike = self._strike(actor, rival, candidates)
        if strike is not None and rival_attacking:
            if self._pressure_ticks == 0:
                self._pressure_reaction = self._roll(PRESSURE_REACTION_TICKS)
            self._pressure_ticks += 1
            if self._pressure_ticks >= self._pressure_reaction and (
                self._tactic is None or self._tactic.name not in (PRESS, BACK_OFF)
            ):
                self._tactic = self._new_tactic(PRESS, actor, rival)
                self._tactic.reaction = 0
        else:
            self._pressure_ticks = 0

        if self._tactic is None or self._tactic.ticks_left <= 0:
            self._tactic = self._draw(actor, rival, candidates)
        tactic = self._tactic
        tactic.ticks_left -= 1
        verb = self._play(tactic, actor, rival, candidates)
        if verb is None:
            # The tactic has nothing to do this tick (its target gone, a
            # timeout): the next tick draws another, and this one goes to
            # the generic pipeline.
            self._tactic = None
        return verb

    # -- drawing a tactic ----------------------------------------------------

    def _lead(self, actor, rival) -> float:
        """Health lead in [-1, 1]: + when the AI is ahead."""

        mine = actor.health if actor.health is not None else 0
        theirs = rival.health if rival.health is not None else 0
        return max(-1.0, min(1.0, (mine - theirs) / LEAD_SCALE))

    def _draw(self, actor, rival, candidates) -> _Tactic:
        weights = dict(_WEIGHTS_AFTER_A_COMBO if self._after_combo else _WEIGHTS)
        self._after_combo = False
        lead = self._lead(actor, rival)
        for name in weights:
            if name in _AGGRESSIVE:
                weights[name] *= max(0.1, 1.0 - AGGRESSIVE_LEAN * lead)
            elif name in _PATIENT:
                weights[name] *= max(0.1, 1.0 + PATIENT_LEAN * lead)
        if actor.held_weapon_type != 0:
            weights.pop(GRAB, None)
            weights.pop(JUMP_IN, None)
        if any(isinstance(verb, (WalkToWeapon, WalkToPickup)) for verb in candidates):
            weights[ITEM] = ITEM_WEIGHT
        names = list(weights)
        name = self._rng.choices(names, weights=[weights[n] for n in names])[0]
        return self._new_tactic(name, actor, rival)

    def _new_tactic(self, name: str, actor, rival) -> _Tactic:
        rng = self._rng
        lead = self._lead(actor, rival)
        side = self._side(actor, rival)
        reaction = self._roll(REACTION_TICKS) + round(LEAD_REACTION * max(0.0, lead))
        if name == PRESS:
            burst_weights = [w * (1.0 + max(0.0, lead) * (len(BURST_LENGTHS) - i - 1) / 2) for i, w in enumerate(BURST_WEIGHTS)]
            burst = rng.choices(BURST_LENGTHS, weights=burst_weights)[0]
            arrival = self._roll(ARRIVAL_TICKS) + round(LEAD_REACTION * max(0.0, lead))
            return _Tactic(name=name, ticks_left=PRESS_TIMEOUT, burst=burst, reaction=arrival)
        if name == GRAB:
            return _Tactic(name=name, ticks_left=GRAB_TIMEOUT)
        if name == JUMP_IN:
            launch = punch_outer_x(actor.character_id) + self._roll(JUMP_LAUNCH_PAST_PUNCH_X)
            return _Tactic(name=name, ticks_left=JUMP_IN_TIMEOUT, goal_dx=side * launch)
        if name == FOOTSIE:
            return _Tactic(
                name=name,
                ticks_left=self._roll(FOOTSIE_TICKS),
                goal_dx=side * self._roll(FOOTSIE_SPACING_X),
                goal_dy=rng.randint(-FOOTSIE_LANE_JITTER_Y, FOOTSIE_LANE_JITTER_Y),
                redraw=self._roll(FOOTSIE_REDRAW_TICKS),
                reaction=reaction,
            )
        if name == CIRCLE:
            lane_side = -1 if actor.world_y > rival.world_y else 1
            if abs(actor.world_y - rival.world_y) < 4:
                lane_side = rng.choice((-1, 1))
            dy = lane_side * self._roll(CIRCLE_LANE_Y)
            waypoints = [(side * CIRCLE_PAST_X, dy)]
            if rng.random() < CIRCLE_CROSS_CHANCE:
                waypoints.append((-side * CIRCLE_PAST_X, dy))
            return _Tactic(name=name, ticks_left=CIRCLE_TIMEOUT, waypoints=waypoints)
        if name == WAIT:
            return _Tactic(
                name=name,
                ticks_left=self._roll(WAIT_TICKS),
                stand=(actor.world_x, actor.world_y),
                reaction=reaction,
            )
        if name == BACK_OFF:
            away = 1 if actor.world_x >= rival.world_x else -1
            return _Tactic(
                name=name,
                ticks_left=self._roll(BACK_OFF_TICKS),
                stand=(
                    actor.world_x + away * self._roll(BACK_OFF_X),
                    actor.world_y + rng.randint(-FOOTSIE_LANE_JITTER_Y, FOOTSIE_LANE_JITTER_Y),
                ),
            )
        return _Tactic(name=ITEM, ticks_left=ITEM_TIMEOUT)

    # -- playing a tactic ----------------------------------------------------

    def _play(self, tactic: _Tactic, actor, rival, candidates) -> Verb | None:
        strike = self._strike(actor, rival, candidates)
        thrown = [verb for verb in candidates if isinstance(verb, (ThrowKnife, ThrowPepper))]
        if thrown and tactic.name in (PRESS, FOOTSIE, WAIT) and self._rng.random() < THROW_CHANCE:
            return min(thrown, key=repr)

        if tactic.name == PRESS:
            return self._press(tactic, actor, rival, candidates, strike)
        if tactic.name == GRAB:
            if rival.combat_phase is CombatPhase.ATTACKING and strike is not None:
                # Walking into a swing is taking the hit, not the hold: trade.
                self._tactic = self._new_tactic(PRESS, actor, rival)
                self._tactic.reaction = 0
                return self._press(self._tactic, actor, rival, candidates, strike)
            return GrabEnemy(actor_slot=actor.slot, target_slot=rival.slot)
        if tactic.name == JUMP_IN:
            return self._jump_in(tactic, actor, rival, candidates)
        if tactic.name == FOOTSIE:
            punish = self._maybe_punish(tactic, actor, rival, strike)
            if punish is not None:
                return punish
            tactic.redraw -= 1
            if tactic.redraw <= 0:
                tactic.redraw = self._roll(FOOTSIE_REDRAW_TICKS)
                tactic.goal_dx = self._side(actor, rival) * self._roll(FOOTSIE_SPACING_X)
                tactic.goal_dy = self._rng.randint(-FOOTSIE_LANE_JITTER_Y, FOOTSIE_LANE_JITTER_Y)
            return self._step_to_rival_offset(actor, rival, tactic)
        if tactic.name == CIRCLE:
            while tactic.waypoints:
                dx, dy = tactic.waypoints[0]
                goal_x, goal_y = rival.world_x + dx, rival.world_y + dy
                if math.hypot(goal_x - actor.world_x, goal_y - actor.world_y) > CIRCLE_ARRIVAL:
                    return self._step(actor, rival, goal_x, goal_y, tactic.name)
                tactic.waypoints.pop(0)
            # Round the rival: now go in.
            self._tactic = self._new_tactic(PRESS, actor, rival)
            return self._press(self._tactic, actor, rival, candidates, strike)
        if tactic.name in (WAIT, BACK_OFF):
            if tactic.name == WAIT:
                punish = self._maybe_punish(tactic, actor, rival, strike)
                if punish is not None:
                    return punish
            assert tactic.stand is not None
            return self._step(actor, rival, tactic.stand[0], tactic.stand[1], tactic.name)
        if tactic.name == ITEM:
            items = [verb for verb in candidates if isinstance(verb, (WalkToWeapon, WalkToPickup))]
            return min(items, key=repr) if items else None
        return None

    def _press(self, tactic: _Tactic, actor, rival, candidates, strike) -> Verb | None:
        if tactic.presses >= tactic.burst:
            self._after_combo = True
            tactic.ticks_left = 0
            return self._stand(actor, rival, tactic.name)
        if (
            not tactic.rear_rolled
            and reach.enemy_behind_actor(actor, rival)
            and reach.in_rear_band(actor, rival)
            and actor.held_weapon_type == 0
        ):
            tactic.rear_rolled = True
            if self._rng.random() < REAR_ATTACK_CHANCE:
                tactic.presses = tactic.burst
                return RearAttack(actor_slot=actor.slot, target_slot=rival.slot)
        if strike is not None:
            tactic.in_reach_ticks += 1
            if rival.combat_phase is CombatPhase.ATTACKING:
                tactic.reaction = min(tactic.reaction, PRESSURE_REACTION_TICKS[1])
            if tactic.presses == 0 and tactic.in_reach_ticks < tactic.reaction:
                return self._stand(actor, rival, tactic.name)
            if tactic.gap > 0:
                tactic.gap -= 1
                return self._stand(actor, rival, tactic.name)
            tactic.presses += 1
            tactic.gap = self._roll(PRESS_GAP_TICKS)
            return strike
        if tactic.presses > 0:
            # The rival left reach mid-burst: the burst is over.
            tactic.presses = tactic.burst
            return self._press(tactic, actor, rival, candidates, strike)
        tactic.in_reach_ticks = 0
        walks = [
            verb for verb in candidates
            if isinstance(verb, WalkToNearEnemy) and verb.target_slot == rival.slot
        ]
        if walks:
            return walks[0]
        # No walk offered (a rival just behind, in the rear band the generic
        # pipeline counts as actionable): turn by walking at them, else step
        # to a striking distance on this side.
        if reach.enemy_behind_actor(actor, rival):
            return self._step(actor, rival, rival.world_x, rival.world_y, tactic.name)
        side = self._side(actor, rival)
        return self._step(actor, rival, rival.world_x + side * PRESS_STAND_X, rival.world_y, tactic.name)

    def _maybe_punish(self, tactic: _Tactic, actor, rival, strike) -> Verb | None:
        """The rival walked into reach while the AI spaced or waited."""

        if strike is None:
            tactic.in_reach_ticks = 0
            return None
        tactic.in_reach_ticks += 1
        if tactic.in_reach_ticks != tactic.reaction:
            return None
        chance = PUNISH_CHANCE * (1.0 - 0.4 * self._lead(actor, rival))
        if self._rng.random() < chance:
            self._tactic = self._new_tactic(PRESS, actor, rival)
            self._tactic.reaction = 0
            return self._press(self._tactic, actor, rival, [], strike)
        self._tactic = self._new_tactic(BACK_OFF, actor, rival)
        assert self._tactic.stand is not None
        return self._step(actor, rival, self._tactic.stand[0], self._tactic.stand[1], BACK_OFF)

    def _jump_in(self, tactic: _Tactic, actor, rival, candidates) -> Verb | None:
        if tactic.launched:
            # Landed from the flight: done.
            self._after_combo = True
            tactic.ticks_left = 0
            return self._stand(actor, rival, tactic.name)
        in_front = reach.enemy_in_front(actor, rival)
        lane_ok = abs(rival.world_y - actor.world_y) <= reach.JUMP_ATTACK_RANGE_Y
        dx = abs(rival.world_x - actor.world_x)
        at_launch = abs(dx - abs(tactic.goal_dx)) <= 6 and lane_ok
        if at_launch:
            tactic.at_launch_ticks += 1
        blessed = in_front and reach.in_jump_attack_band(actor, rival)
        anyway = (
            in_front
            and lane_ok
            and tactic.at_launch_ticks >= JUMP_IN_PATIENCE
            and dx <= jump_kick.landing_distance(actor.character_id)
        )
        if (blessed or anyway) and nav.jump_landing_is_safe(self._context, actor, rival.world_x):
            tactic.launched = True
            return JumpAttack(actor_slot=actor.slot, target_slot=rival.slot)
        return self._step_to_rival_offset(actor, rival, tactic)

    def _hold_move(self, actor, rival, candidates) -> Verb | None:
        offered = [verb for verb in candidates if isinstance(verb, _ANY_HOLD_VERB)]
        if self._hold is None:
            scripts = [script for script, _ in HOLD_SCRIPTS]
            weights = [weight for _, weight in HOLD_SCRIPTS]
            self._hold = _Hold(
                script=self._rng.choices(scripts, weights=weights)[0],
                hesitation=self._roll(HOLD_HESITATION_TICKS),
            )
            self._tactic = None
        hold = self._hold
        if not offered:
            # Inside a hold animation: nothing to press.
            return None
        if hold.hesitation > 0:
            hold.hesitation -= 1
            return self._stand(actor, rival, GRAB)
        wanted = hold.script[min(hold.step, len(hold.script) - 1)]
        hold.step += 1
        matching = [verb for verb in offered if isinstance(verb, _HOLD_VERBS[wanted])]
        if not matching and actor.action_base == 0x60 and wanted != SUPLEX:
            # A front hold takes every one of these (the generic pipeline
            # offers the throw only under a threat, and never the release):
            # the knee is B, the throw B+back, the flip C, the release back.
            matching = [_HOLD_VERBS[wanted][0](actor_slot=actor.slot, target_slot=rival.slot)]
        if matching:
            return min(matching, key=repr)
        return self._rng.choice(sorted(offered, key=repr))

    # -- helpers ---------------------------------------------------------

    def _roll(self, bounds: tuple[int, int]) -> int:
        return self._rng.randint(bounds[0], bounds[1])

    @staticmethod
    def _side(actor, rival) -> int:
        """+1 when the actor stands right of the rival, else -1."""

        return 1 if actor.world_x >= rival.world_x else -1

    @staticmethod
    def _strike(actor, rival, candidates) -> Verb | None:
        for verb in candidates:
            if isinstance(verb, (Punch, MeleeWeaponAttack)) and verb.target_slot == rival.slot:
                return verb
        return None

    def _step(self, actor, rival, goal_x: int, goal_y: int, tactic: str) -> DuelStep:
        return DuelStep(
            actor_slot=actor.slot,
            target_slot=rival.slot,
            goal_x=int(goal_x),
            goal_y=int(goal_y),
            tactic=tactic,
        )

    def _stand(self, actor, rival, tactic: str) -> DuelStep:
        return self._step(actor, rival, actor.world_x, actor.world_y, tactic)

    def _step_to_rival_offset(self, actor, rival, tactic: _Tactic) -> DuelStep:
        return self._step(
            actor, rival, rival.world_x + tactic.goal_dx, rival.world_y + tactic.goal_dy, tactic.name
        )

