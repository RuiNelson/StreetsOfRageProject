import unittest

from sor_autoplay.ai.character import Myself, Partner
from sor_autoplay.ai.enemy import Abadede, Enemy, Garcia, Jack, Souther
from sor_autoplay.ai.essential import AnimationInProgress, CameraRange, Stage
from sor_autoplay.ai.hazard_tokens import Projectile
from sor_autoplay.ai.observe import generate_direct_observation_tokens
from sor_autoplay.ai.pickup_tokens import Weapon
from sor_autoplay.ai.tokens import find, find_all
from sor_autoplay.phases import CombatPhase
from sor_autoplay.state import GameSnapshot, PlayerSnapshot
from sor_autoplay.world_map import MapEntity, WorldMap


def _player_snapshot(
    *,
    index: int,
    is_playable: bool = True,
    character_id: int | None = 0,
    character_name: str = "Axel",
    health: int | None = 50,
    health_percent: float | None = 100.0,
    lives: int = 3,
    specials: int = 2,
) -> PlayerSnapshot:
    return PlayerSnapshot(
        index=index,
        mode_active=is_playable,
        object_type=1 if is_playable else 0,
        character_id=character_id,
        character_name=character_name,
        health=health,
        health_percent=health_percent,
        lives=lives,
        specials=specials,
        score=0,
        score_text="000000",
        continues=0,
        out_flag=0,
        is_playable=is_playable,
    )


def _player_entity(
    *,
    slot: str,
    world_x: int = 800,
    world_y: int = 64,
    action_state: int = 0,
    held_type: int = 0,
    facing_left: bool = False,
    combat_phase: CombatPhase = CombatPhase.NORMAL,
) -> MapEntity:
    return MapEntity(
        kind="player",
        family="Player",
        symbol=slot[-1],
        color="#4da3ff",
        label=f"{slot} Axel",
        type_id=1,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x - 768),
        map_y=float(world_y),
        health=50,
        slot=slot,
        action_state=action_state,
        held_type=held_type,
        facing_left=facing_left,
        combat_phase=combat_phase,
    )


def _enemy_entity(
    *,
    slot: str = "obj00",
    type_id: int = 0x20,
    world_x: int = 900,
    world_y: int = 64,
    health: int | None = 6,
    kind: str = "enemy",
    combat_phase: CombatPhase = CombatPhase.NORMAL,
    facing_left: bool = False,
    family_state: int = 0,
    tactical: int = 0,
    pair_role: int = 0,
    boss_dist_x: int = 0,
    boss_dist_lane: int = 0,
    mode_flags: int = 0,
    target_unavailable: int = 0,
    phase_timer: int = 0,
    ground_z: int | None = None,
    vel_x: float = 0.0,
    vel_z: float = 0.0,
) -> MapEntity:
    return MapEntity(
        kind=kind,
        family="Garcia",
        symbol="G",
        color="#7dffa0",
        label="Garcia",
        type_id=type_id,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x - 768),
        map_y=float(world_y),
        health=health,
        slot=slot,
        combat_phase=combat_phase,
        facing_left=facing_left,
        family_state=family_state,
        tactical=tactical,
        pair_role=pair_role,
        boss_dist_x=boss_dist_x,
        boss_dist_lane=boss_dist_lane,
        mode_flags=mode_flags,
        target_unavailable=target_unavailable,
        phase_timer=phase_timer,
        ground_z=ground_z,
        vel_x=vel_x,
        vel_z=vel_z,
    )


def _weapon_entity(
    *,
    slot: str = "obj10",
    type_id: int = 0x08,
    world_x: int = 850,
    world_y: int = 64,
    interaction: int = 0,
    item_param: int = 0,
) -> MapEntity:
    return MapEntity(
        kind="weapon",
        family="Weapon",
        symbol="w",
        color="#ffd24d",
        label="Knife",
        type_id=type_id,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x - 768),
        map_y=float(world_y),
        health=None,
        slot=slot,
        interaction=interaction,
        item_param=item_param,
    )


def _projectile_entity(
    *,
    slot: str = "obj09",
    world_x: int = 900,
    world_y: int = 64,
    vel_x: float = -1.5,
    vel_z: float = 0.0,
) -> MapEntity:
    return MapEntity(
        kind="projectile",
        family="Debris",
        symbol=".",
        color="#8e8e93",
        label="Bottle shard",
        type_id=0x1E,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x - 768),
        map_y=float(world_y),
        health=None,
        slot=slot,
        vel_x=vel_x,
        vel_z=vel_z,
        combat_phase=CombatPhase.ATTACKING,
    )


def _world_map(entities: tuple[MapEntity, ...]) -> WorldMap:
    return WorldMap(
        camera_x=768,
        camera_y=0,
        camera_left=32.0,
        camera_right=288.0,
        camera_top=0.0,
        camera_bottom=112.0,
        view_left=0.0,
        view_right=320.0,
        view_top=0.0,
        view_bottom=112.0,
        entities=entities,
    )


def _snapshot(
    *,
    players: tuple[PlayerSnapshot, PlayerSnapshot],
    entities: tuple[MapEntity, ...] = (),
    level_index: int = 0,
) -> GameSnapshot:
    return GameSnapshot(
        connected=True,
        game_state=0x14,
        game_mode="In-game",
        level_index=level_index,
        level_display=level_index + 1,
        wave=0,
        player_mode=0x03,
        time_left=99,
        time_left_raw=0,
        round_timer_bcd=0,
        clock_stopped=False,
        timer_valid=True,
        players=players,
        world_map=_world_map(entities),
    )


class MyselfTests(unittest.TestCase):
    def test_myself_built_from_snapshot_and_entity(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entity = _player_entity(
            slot="P1", held_type=0x0A, facing_left=True, action_state=0x10
        )
        snapshot = _snapshot(players=(p1, p2), entities=(entity,))

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        myself = find(context, Myself)
        self.assertIsNotNone(myself)
        assert myself is not None
        self.assertEqual(myself.slot, "P1")
        self.assertEqual(myself.player_index, 1)
        self.assertEqual(myself.character_id, 0)
        self.assertEqual(myself.character_name, "Axel")
        self.assertEqual(myself.world_x, 800)
        self.assertEqual(myself.world_y, 64)
        self.assertEqual(myself.health, 50)
        self.assertEqual(myself.health_percent, 100.0)
        self.assertEqual(myself.lives, 3)
        self.assertEqual(myself.specials, 2)
        self.assertEqual(myself.held_weapon_type, 0x0A)
        self.assertTrue(myself.facing_left)
        self.assertEqual(myself.action_state, 0x10)
        self.assertTrue(myself.is_airborne)  # base 0x10 is in the jump range

    def test_myself_omitted_when_entity_absent(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        snapshot = _snapshot(players=(p1, p2), entities=())

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNone(find(context, Myself))


class PartnerTests(unittest.TestCase):
    def test_partner_present_when_playable(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, character_id=2, character_name="Blaze")
        entities = (_player_entity(slot="P1"), _player_entity(slot="P2"))
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        partner = find(context, Partner)
        self.assertIsNotNone(partner)
        assert partner is not None
        self.assertEqual(partner.slot, "P2")
        self.assertEqual(partner.character_name, "Blaze")

    def test_partner_omitted_when_not_playable(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (_player_entity(slot="P1"),)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNone(find(context, Partner))

    def test_partner_omitted_when_entity_missing_even_if_playable_flag_set(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2)  # is_playable True, but no P2 MapEntity
        entities = (_player_entity(slot="P1"),)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNone(find(context, Partner))


class EnemyObservationTests(unittest.TestCase):
    def test_enemy_included_when_alive(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (
            _player_entity(slot="P1"),
            _enemy_entity(slot="obj00", health=6),
        )
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        enemies = find_all(context, Enemy)
        self.assertEqual(len(enemies), 1)
        self.assertEqual(enemies[0].slot, "obj00")
        self.assertEqual(enemies[0].type_id, 0x20)

    def test_enemy_omitted_when_defeated(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        dead_enemy = _enemy_entity(slot="obj00", health=0x8000)
        self.assertTrue(dead_enemy.is_defeated)
        entities = (_player_entity(slot="P1"), dead_enemy)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertEqual(find_all(context, Enemy), [])

    def test_boss_kind_is_also_observed(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        boss = _enemy_entity(slot="obj01", type_id=0x30, kind="boss", health=100)
        entities = (_player_entity(slot="P1"), boss)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        enemies = find_all(context, Enemy)
        self.assertEqual([e.slot for e in enemies], ["obj01"])


class EnemySubclassObservationTests(unittest.TestCase):
    def test_garcia_type_produces_garcia_class(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (
            _player_entity(slot="P1"),
            _enemy_entity(slot="obj00", type_id=0x20),
        )
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        enemies = find_all(context, Enemy)
        self.assertEqual(len(enemies), 1)
        self.assertIsInstance(enemies[0], Garcia)

    def test_jack_type_derives_has_projectile_from_family_state_bit0(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)

        with_weapon = _enemy_entity(slot="obj01", type_id=0x27, family_state=0x01)
        snapshot = _snapshot(
            players=(p1, p2), entities=(_player_entity(slot="P1"), with_weapon)
        )
        context = generate_direct_observation_tokens(snapshot, player_index=1)
        jack = find(context, Jack, slot="obj01")
        self.assertIsNotNone(jack)
        assert jack is not None
        self.assertTrue(jack.has_projectile)

        without_weapon = _enemy_entity(slot="obj02", type_id=0x27, family_state=0x00)
        snapshot = _snapshot(
            players=(p1, p2), entities=(_player_entity(slot="P1"), without_weapon)
        )
        context = generate_direct_observation_tokens(snapshot, player_index=1)
        jack = find(context, Jack, slot="obj02")
        self.assertIsNotNone(jack)
        assert jack is not None
        self.assertFalse(jack.has_projectile)

    def test_bespoke_boss_produces_no_crash_and_right_class(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        boss = _enemy_entity(slot="obj03", type_id=0x30, kind="boss", health=100)
        entities = (_player_entity(slot="P1"), boss)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        found = find(context, Abadede, slot="obj03")
        self.assertIsNotNone(found)

    def test_later_boss_extra_fields_round_trip_from_entity(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        boss = _enemy_entity(
            slot="obj04",
            type_id=0x55,
            kind="boss",
            health=200,
            tactical=3,
            pair_role=1,
            boss_dist_x=40,
            boss_dist_lane=5,
            mode_flags=0x02,
            target_unavailable=1,
            phase_timer=12,
            ground_z=160,
            vel_x=1.5,
            vel_z=-0.5,
        )
        entities = (_player_entity(slot="P1"), boss)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        souther = find(context, Souther, slot="obj04")
        self.assertIsNotNone(souther)
        assert souther is not None
        self.assertEqual(souther.tactical, 3)
        self.assertEqual(souther.pair_role, 1)
        self.assertEqual(souther.boss_dist_x, 40)
        self.assertEqual(souther.boss_dist_lane, 5)
        self.assertEqual(souther.mode_flags, 0x02)
        self.assertEqual(souther.target_unavailable, 1)
        self.assertEqual(souther.phase_timer, 12)
        self.assertEqual(souther.ground_z, 160)
        self.assertEqual(souther.vel_x, 1.5)
        self.assertEqual(souther.vel_z, -0.5)


class WeaponObservationTests(unittest.TestCase):
    def test_free_ground_weapon_produces_weapon_token(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (_player_entity(slot="P1"), _weapon_entity(slot="obj10"))
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        weapons = find_all(context, Weapon)
        self.assertEqual(len(weapons), 1)
        self.assertEqual(weapons[0].slot, "obj10")
        self.assertEqual(weapons[0].weapon_type, 0x08)

    def test_held_or_reserved_weapon_is_not_a_weapon_token(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        held = _weapon_entity(slot="obj11", interaction=1)
        entities = (_player_entity(slot="P1"), held)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertEqual(find_all(context, Weapon), [])


class ProjectileObservationTests(unittest.TestCase):
    def test_projectile_included(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (_player_entity(slot="P1"), _projectile_entity())
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        projectiles = find_all(context, Projectile)
        self.assertEqual(len(projectiles), 1)
        self.assertEqual(projectiles[0].slot, "obj09")
        self.assertEqual(projectiles[0].vel_x, -1.5)


class AnimationInProgressTests(unittest.TestCase):
    def test_absent_when_action_normal(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (_player_entity(slot="P1", action_state=0x00, held_type=0),)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNone(find(context, AnimationInProgress, slot="P1"))

    def test_present_when_attacking(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        # base action 0x18 (punch family) -> ATTACKING
        entities = (_player_entity(slot="P1", action_state=0x18, held_type=0),)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNotNone(find(context, AnimationInProgress, slot="P1"))

    def test_absent_while_holding_a_grabbed_enemy(self) -> None:
        """Regression: HOLDING (grabbing an enemy or carrying a weapon) is
        not an animation lock -- the game accepts a new B/A input on the very
        next frame. Blocking should_* on this phase left the AI frozen the
        instant it grabbed an enemy."""

        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (_player_entity(slot="P1", action_state=0x00, held_type=0x20),)
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNone(find(context, AnimationInProgress, slot="P1"))

    def test_present_for_partner_independently(self) -> None:
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2)
        entities = (
            _player_entity(slot="P1", action_state=0x00),
            _player_entity(slot="P2", action_state=0x18),
        )
        snapshot = _snapshot(players=(p1, p2), entities=entities)

        context = generate_direct_observation_tokens(snapshot, player_index=1)

        self.assertIsNone(find(context, AnimationInProgress, slot="P1"))
        self.assertIsNotNone(find(context, AnimationInProgress, slot="P2"))


class StageAndCameraTests(unittest.TestCase):
    def _context_for_level(self, level_index: int):
        p1 = _player_snapshot(index=1)
        p2 = _player_snapshot(index=2, is_playable=False)
        entities = (_player_entity(slot="P1"),)
        snapshot = _snapshot(players=(p1, p2), entities=entities, level_index=level_index)
        return generate_direct_observation_tokens(snapshot, player_index=1)

    def test_stage_direction_early_levels(self) -> None:
        stage = find(self._context_for_level(0), Stage)
        assert stage is not None
        self.assertEqual(stage.level_index, 0)
        self.assertEqual(stage.direction, "right")

    def test_stage_direction_level_6_is_none(self) -> None:
        stage = find(self._context_for_level(6), Stage)
        assert stage is not None
        self.assertEqual(stage.direction, "none")

    def test_stage_direction_level_7_is_left(self) -> None:
        stage = find(self._context_for_level(7), Stage)
        assert stage is not None
        self.assertEqual(stage.direction, "left")

    def test_camera_range_present(self) -> None:
        context = self._context_for_level(0)
        camera = find(context, CameraRange)
        self.assertIsNotNone(camera)
        assert camera is not None
        self.assertEqual(camera.left, 32.0)
        self.assertEqual(camera.right, 288.0)
        self.assertEqual(camera.top, 0.0)
        self.assertEqual(camera.bottom, 112.0)


if __name__ == "__main__":
    unittest.main()
