"""``generate_inference_tokens`` and its ``check_for_*`` derivation functions.

``Surrounded`` and ``EnemyCluster`` are the two tokens left here. Every
other judgment this pipeline used to precompute once per tick -- reach
bands, threat windows, grab opportunities, safe spots -- is now answered
directly against ``reach.py`` (and, for ``SafeSpot``, ``execute.py``) by
whichever ``could_*``/``_emergency_*``/state machine needs it, on demand,
rather than written into the context every tick for every actor.
``Surrounded`` stays here because it genuinely benefits from shared
computation: it is read by three or more call sites
(``priority._emergency_call_police``, ``decide.py``'s police threshold, and
any consumer wanting to know an actor's own crowd state). ``EnemyCluster``
(user: "Eu queria um token Inferred" for cluster inference, rather than a
bare ``reach.py`` function each caller recomputes) follows the same
reasoning: ``priority._hold_cluster_bonus`` reads it once per hold move
scored (``ThrowHeldEnemy``/``Supplex``, several times a tick between them),
and it exists as a token rather than staying a private helper so the same
judgment is available to anything else that wants "is this body part of a
cluster" -- the HUD, a future ``could_*``, another scorer -- without
recomputing it.
"""

from __future__ import annotations

from . import reach
from .tokens import Myself, Partner, PlayableCharacter
from .tokens import EnemyCluster, Surrounded
from .tokens import Context, Token, find

# A crowd, rather than a queue: this many live enemies inside the close box
# around the actor (or any pincer -- at least one on each side) is what makes
# it "surrounded". Two enemies arriving from the same side are an ordinary
# fight; the box is the same one RearAttack uses to decide it is boxed in.
SURROUNDED_MIN_ENEMIES = 3


def _actors(context: Context) -> list[PlayableCharacter]:
    return [actor for actor in (find(context, Myself), find(context, Partner)) if actor is not None]


def check_for_surrounded(context: Context) -> Context:
    """Judge whether an actor is boxed in rather than facing a queue.

    Judged with ``reach.SURROUNDED_NEAR_X``/``_Y`` -- the "part of this fight"
    box -- **not** the tighter ``REAR_THREAT_X``/``_Y`` this used to share
    with ``reach.rear_attack_is_warranted``. The two questions are different:
    the chord's box asks "can that enemy hit me while I turn", which is a
    hitting distance, while encirclement asks "are these enemies all in this
    exchange with me". Sharing the tighter one made the judgment collapse
    after a dozen pixels of the actor's own walking -- see that constant.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        near = [
            enemy
            for enemy in enemies
            if abs(enemy.world_x - actor.world_x) <= reach.SURROUNDED_NEAR_X
            and abs(enemy.world_y - actor.world_y) <= reach.SURROUNDED_NEAR_Y
        ]
        behind = sum(1 for enemy in near if reach.enemy_behind_actor(actor, enemy))
        in_front = len(near) - behind
        pincered = behind >= 1 and in_front >= 1
        if len(near) < SURROUNDED_MIN_ENEMIES and not pincered:
            continue
        tokens.add(Surrounded(actor_slot=actor.slot, in_front=in_front, behind=behind))
    return tokens


def check_for_clusters(context: Context) -> Context:
    """Flag every live, on-screen enemy that has at least one other live
    enemy clustered around it -- close enough that a wide attack landing on
    one plausibly lands on the others too.

    ``reach.nearby_enemies`` is the shared geometry (``Surrounded``'s own
    box, centred on the enemy instead of the actor); this just turns that
    into one ``EnemyCluster`` per anchor with at least one member, so
    ``priority._hold_cluster_bonus`` (and anything else that wants the same
    judgment) reads it rather than rescanning every enemy pair itself.
    """

    enemies = reach.on_screen_enemies(context)
    tokens: set[Token] = set()
    for enemy in enemies:
        nearby = reach.nearby_enemies(enemy, enemies)
        if nearby:
            tokens.add(
                EnemyCluster(
                    slot=enemy.slot,
                    member_slots=frozenset(other.slot for other in nearby),
                )
            )
    return tokens


def generate_inference_tokens(context: Context) -> Context:
    """Derive every ``Inferred`` token from direct observation.

    ``check_for_surrounded`` and ``check_for_clusters`` -- see the module
    docstring for why every other judgment moved out of this file.
    """

    return context | check_for_surrounded(context) | check_for_clusters(context)
