import unittest

from tests.test_attack_ranges import _animation_set, _shape_tables

from sor_autoplay.memory_map import (
    OBJ_CHARACTER_ID,
    OBJ_FLAGS,
    OBJ_HEALTH,
    OBJ_INTERACTION,
    OBJ_ITEM_PARAM,
    OBJ_JACK_WEAPON_ATTACHED,
    OBJ_WEAPON_HOLDER,
    OBJ_POS_X,
    OBJ_POS_Y,
    OBJ_POS_Z,
    OBJ_ORDINARY_STUN_TIMER,
    OBJ_PRIMARY_STATE,
    OBJ_OUTGOING_DAMAGE,
    OBJ_SCRIPT_PARAM,
    OBJ_SUBTYPE,
    OBJ_TYPE,
    OBJ_VEL_LANE_ORDINARY,
    OBJ_VEL_X,
    OBJ_VEL_X_ORDINARY,
    OBJ_VEL_Z,
    OBJECT_SLOT_SIZE,
)
from sor_autoplay.hitboxes import OBJ_CACHED_BODY_BOX
from sor_autoplay.object_catalog import player_style, style_for_object, style_for_type
from sor_autoplay.phases import CombatPhase
from sor_autoplay.world_map import (
    ACTORS_BYTES,
    CAMERA_BYTES,
    CAMERA_X_MIN,
    CAMERA_X_SPAN,
    LANE_Y_MAX_DEFAULT,
    LANE_Y_MAX_ROUND7,
    OBJECT_TABLE_BYTES,
    SCREEN_WIDTH,
    lane_y_max_for_level,
    parse_world_map,
    project_to_map,
)


def _put_u8(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF


def _put_u16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = int(value & 0xFFFF).to_bytes(2, "big")


def _put_fixed16(buf: bytearray, offset: int, integer: int) -> None:
    buf[offset : offset + 2] = int(integer & 0xFFFF).to_bytes(2, "big", signed=False)
    buf[offset + 2 : offset + 4] = b"\x00\x00"


def _put_fixed1616_signed(buf: bytearray, offset: int, value: float) -> None:
    raw = int(round(value * 65536.0)) & 0xFFFF_FFFF
    buf[offset : offset + 4] = raw.to_bytes(4, "big")


class ObjectCatalogTests(unittest.TestCase):
    def test_player_colors(self) -> None:
        self.assertEqual(player_style(1, 0).color, "#4da3ff")
        self.assertEqual(player_style(2, 2).color, "#ff5c5c")

    def test_pickups(self) -> None:
        self.assertEqual(style_for_type(0x4B).symbol, "a")

    def test_later_round_breakable_types(self) -> None:
        expected = {
            0x18,  # Round 3
            0x1B,
            0x1C,
            0x1D,  # Round 4
            0x1F,  # Round 5
            0x41,  # Round 6
            0x45,  # Round 8 moving prop
        }
        self.assertEqual(
            {type_id for type_id in expected if style_for_type(type_id).kind == "breakable"},
            expected,
        )

    def test_round6_moving_hazard_is_not_a_breakable(self) -> None:
        style = style_for_type(0x42)
        self.assertIsNotNone(style)
        self.assertEqual(style.kind, "projectile")

    def test_antonio_boomerang_is_a_tracked_projectile(self) -> None:
        """Type $96 is Antonio's linked boomerang/attack object (see
        ai-analysis/enemy-ai.md "$16CF4 antonio family table"). Before this it
        had no catalog entry, so it never became a map entity and the agent
        pipeline could not see or dodge it."""

        style = style_for_type(0x96)
        self.assertIsNotNone(style)
        assert style is not None
        self.assertEqual(style.kind, "projectile")
        self.assertEqual(style.family, "Antonio")

    def test_mr_x_type_35_is_boss(self) -> None:
        """Final Mr. X body ($1306A) must plot and be hunt-able as a boss."""

        style = style_for_type(0x35)
        self.assertIsNotNone(style)
        assert style is not None
        self.assertEqual(style.kind, "boss")
        self.assertEqual(style.family, "Mr. X")
        # Office presentation objects must not masquerade as combatants.
        self.assertIsNone(style_for_type(0x33))
        self.assertIsNone(style_for_type(0x34))

    def test_same_type_debris_is_not_a_live_breakable(self) -> None:
        self.assertIsNotNone(
            style_for_object(0x18, action_state=1, subtype=0)
        )
        self.assertIsNone(
            style_for_object(0x18, action_state=2, subtype=1)
        )
        self.assertIsNone(
            style_for_object(0x11, action_state=2, variant=3)
        )


class ProjectionTests(unittest.TestCase):
    def test_map_is_lane_depth(self) -> None:
        self.assertEqual(project_to_map(800, 2, camera_x=768), (32.0, 2.0))
        self.assertEqual(project_to_map(800, 112, camera_x=768), (32.0, 112.0))

    def test_lane_clamp_from_rom(self) -> None:
        self.assertEqual(LANE_Y_MAX_DEFAULT, 0x70)
        self.assertEqual(LANE_Y_MAX_ROUND7, 0xA0)
        self.assertEqual(lane_y_max_for_level(0), 0x70)
        self.assertEqual(lane_y_max_for_level(6), 0xA0)


class WorldMapParseTests(unittest.TestCase):
    def _put_object(
        self,
        actors: bytearray,
        *,
        type_id: int,
        state: int = 1,
        subtype: int = 0,
        damage: int = 0,
        script_param: int = 0,
        slot_index: int = 0,
    ) -> None:
        base = 0x100 + slot_index * OBJECT_SLOT_SIZE
        _put_u8(actors, base + OBJ_TYPE, type_id)
        _put_u8(actors, base + OBJ_FLAGS, 0x00)
        _put_u8(actors, base + OBJ_PRIMARY_STATE, state)
        _put_u8(actors, base + OBJ_SUBTYPE, subtype)
        _put_u8(actors, base + OBJ_OUTGOING_DAMAGE, damage)
        _put_u8(actors, base + OBJ_SCRIPT_PARAM, script_param)
        _put_fixed16(actors, base + OBJ_POS_X, 800 + slot_index * 16)
        _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, base + OBJ_POS_Z, 0xA0)

    def test_later_round_intact_breakables_are_observed(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        late_types = (0x18, 0x1B, 0x1C, 0x1D, 0x1F, 0x41, 0x45)
        for index, type_id in enumerate(late_types):
            self._put_object(actors, type_id=type_id, slot_index=index)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )

        self.assertEqual(
            {entity.type_id for entity in world.entities if entity.kind == "breakable"},
            set(late_types),
        )

    def test_broken_original_and_same_type_debris_are_ignored(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        self._put_object(actors, type_id=0x18, state=2, subtype=1)
        self._put_object(actors, type_id=0x41, state=3, subtype=4, slot_index=1)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )

        self.assertFalse(any(entity.kind == "breakable" for entity in world.entities))

    def test_round8_moving_prop_exposes_active_damage_phase(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        self._put_object(actors, type_id=0x45, damage=3, script_param=2)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        prop = next(entity for entity in world.entities if entity.type_id == 0x45)

        self.assertEqual(prop.kind, "breakable")
        self.assertEqual(prop.outgoing_damage, 3)
        self.assertEqual(prop.script_param, 2)
        self.assertEqual(prop.combat_phase, CombatPhase.ATTACKING)

    def test_round6_moving_hazard_is_observed_as_dangerous(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        self._put_object(actors, type_id=0x42, state=3, damage=0x14)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        hazard = next(entity for entity in world.entities if entity.type_id == 0x42)

        self.assertEqual(hazard.kind, "projectile")
        self.assertEqual(hazard.combat_phase, CombatPhase.ATTACKING)

    def test_projectile_velocity_is_decoded(self) -> None:
        """Projectile-kind objects share the generic +$20/+$24 velocity fields
        with bosses; before this fix only the boss branch decoded them and a
        plain projectile (e.g. type $1E debris) always read vel_x/vel_z as
        0.0 regardless of the object's actual RAM contents."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x1E)  # bottle shard debris
        _put_u8(actors, base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, base + OBJ_POS_X, 800)
        _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, base + OBJ_POS_Z, 0xA0)
        _put_fixed1616_signed(actors, base + OBJ_VEL_X, -1.5)
        _put_fixed1616_signed(actors, base + OBJ_VEL_Z, 2.25)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        debris = next(entity for entity in world.entities if entity.type_id == 0x1E)

        self.assertEqual(debris.kind, "projectile")
        self.assertAlmostEqual(debris.vel_x, -1.5)
        self.assertAlmostEqual(debris.vel_z, 2.25)

    def test_ordinary_enemy_velocity_is_decoded(self) -> None:
        """Ordinary enemies (kind=="enemy") must expose their own +$1C/+$20
        velocity, distinct from the boss-only vel_x/vel_z at +$20/+$24 --
        before this fix a Grunt always read enemy_vel_x/enemy_vel_y as 0.0
        regardless of RAM contents, hiding fast diagonal closers from the AI."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x20)  # Garcia
        _put_u8(actors, base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, base + OBJ_POS_X, 800)
        _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, base + OBJ_POS_Z, 0xA0)
        _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0100)  # ENEMY_ST_NORMAL
        _put_u16(actors, base + OBJ_HEALTH, 10)
        _put_fixed1616_signed(actors, base + OBJ_VEL_X_ORDINARY, -3.5)
        _put_fixed1616_signed(actors, base + OBJ_VEL_LANE_ORDINARY, 1.25)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        garcia = next(entity for entity in world.entities if entity.type_id == 0x20)

        self.assertEqual(garcia.kind, "enemy")
        self.assertAlmostEqual(garcia.enemy_vel_x, -3.5)
        self.assertAlmostEqual(garcia.enemy_vel_y, 1.25)

    def test_ordinary_enemy_stun_state_and_timer_are_decoded(self) -> None:
        """State $0200 is the ROM's timed hitstun ($9B88 counts +$50 down and
        writes $0100 back at zero), so the enemy must read as STUNNED with
        its remaining frames exposed -- that window is free damage."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x20)  # Garcia
        _put_u8(actors, base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, base + OBJ_POS_X, 800)
        _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, base + OBJ_POS_Z, 0xA0)
        _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0200)  # ENEMY_ST_ALT
        _put_u16(actors, base + OBJ_HEALTH, 10)
        _put_u8(actors, base + OBJ_ORDINARY_STUN_TIMER, 0x11)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        garcia = next(entity for entity in world.entities if entity.type_id == 0x20)

        self.assertEqual(garcia.combat_phase, CombatPhase.STUNNED)
        self.assertEqual(garcia.stun_timer, 0x11)

    def test_scripted_state_is_pepper_stun_while_the_special_is_idle(self) -> None:
        """$0400 has two meanings ($A43E): pepper-spray immobilization (160
        frames, counted down at +$50) and police-sweep removal, which forces
        health $FFFF while the special runs. Only the first is a stun."""

        def _build(*, health: int, police: bool):
            actors = bytearray(ACTORS_BYTES)
            camera = bytearray(CAMERA_BYTES)
            _put_u16(camera, 0x02, 768)
            base = 0x100
            _put_u8(actors, base + OBJ_TYPE, 0x20)
            _put_u8(actors, base + OBJ_FLAGS, 0x00)
            _put_fixed16(actors, base + OBJ_POS_X, 800)
            _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
            _put_fixed16(actors, base + OBJ_POS_Z, 0xA0)
            _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0400)  # ENEMY_ST_SCRIPTED
            _put_u16(actors, base + OBJ_HEALTH, health)
            _put_u8(actors, base + OBJ_ORDINARY_STUN_TIMER, 0xA0)
            world = parse_world_map(
                actors_block=bytes(actors),
                camera_block=bytes(camera),
                police_special_active=police,
            )
            return next(e for e in world.entities if e.type_id == 0x20)

        peppered = _build(health=10, police=False)
        self.assertEqual(peppered.combat_phase, CombatPhase.STUNNED)
        self.assertEqual(peppered.stun_timer, 0xA0)

        swept = _build(health=0xFFFF, police=True)
        self.assertEqual(swept.combat_phase, CombatPhase.SCRIPTED)

    def test_boss_velocity_fields_are_unaffected_by_ordinary_enemy_offsets(self) -> None:
        """Boss's existing vel_x/vel_z (+$20/+$24) must stay untouched by the
        new ordinary-enemy-only enemy_vel_x/enemy_vel_y fields."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x35)  # Mr. X boss
        _put_u8(actors, base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, base + OBJ_POS_X, 800)
        _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, base + OBJ_POS_Z, 0xA0)
        _put_u16(actors, base + OBJ_HEALTH, 100)
        _put_fixed1616_signed(actors, base + OBJ_VEL_X, 2.0)
        _put_fixed1616_signed(actors, base + OBJ_VEL_Z, -4.0)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        boss = next(entity for entity in world.entities if entity.type_id == 0x35)

        self.assertEqual(boss.kind, "boss")
        self.assertAlmostEqual(boss.vel_x, 2.0)
        self.assertAlmostEqual(boss.vel_z, -4.0)
        self.assertEqual(boss.enemy_vel_x, 0.0)
        self.assertEqual(boss.enemy_vel_y, 0.0)

    def test_jack_weapon_latch_is_exposed_to_observation(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x27)
        _put_u8(actors, base + OBJ_FLAGS, 0x0C)
        _put_fixed16(actors, base + OBJ_POS_X, 848)
        _put_fixed16(actors, base + OBJ_POS_Y, 64)
        _put_fixed16(actors, base + OBJ_POS_Z, 160)
        _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0C00)
        _put_u16(actors, base + OBJ_HEALTH, 10)
        _put_u8(actors, base + OBJ_JACK_WEAPON_ATTACHED, 0x01)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        jack = next(entity for entity in world.entities if entity.type_id == 0x27)
        self.assertEqual(jack.family_state, 0x01)

    def test_enemy_held_weapon_is_stamped_from_the_weapon_holder_pointer(self) -> None:
        # Ordinary-enemy +$60 is the scripted approach X, not a weapon type.
        # The held bat lives as its own object with +$51==1 and +$52 pointing
        # at the enemy slot; parse_world_map copies that type onto the enemy.
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        enemy_base = 0x100
        _put_u8(actors, enemy_base + OBJ_TYPE, 0x20)
        _put_u8(actors, enemy_base + OBJ_FLAGS, 0x0C)
        _put_fixed16(actors, enemy_base + OBJ_POS_X, 848)
        _put_fixed16(actors, enemy_base + OBJ_POS_Y, 64)
        _put_fixed16(actors, enemy_base + OBJ_POS_Z, 160)
        _put_u16(actors, enemy_base + OBJ_PRIMARY_STATE, 0x0100)
        _put_u16(actors, enemy_base + OBJ_HEALTH, 10)

        weapon_base = 0x100 + OBJECT_SLOT_SIZE
        _put_u8(actors, weapon_base + OBJ_TYPE, 0x0A)  # bat
        _put_u8(actors, weapon_base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, weapon_base + OBJ_POS_X, 848)
        _put_fixed16(actors, weapon_base + OBJ_POS_Y, 64)
        _put_fixed16(actors, weapon_base + OBJ_POS_Z, 160)
        _put_u8(actors, weapon_base + OBJ_ITEM_PARAM, 0)
        _put_u8(actors, weapon_base + OBJ_INTERACTION, 1)
        # Object-table slot 0 lives at $FFB900; the ROM stores the low word.
        _put_u16(actors, weapon_base + OBJ_WEAPON_HOLDER, 0xB900)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        enemy = next(entity for entity in world.entities if entity.type_id == 0x20)
        self.assertEqual(enemy.slot, "obj00")
        self.assertEqual(enemy.held_type, 0x0A)

    def test_bottom_of_lane_is_bottom_of_camera(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        _put_u8(actors, OBJ_TYPE, 0x01)
        _put_u8(actors, OBJ_FLAGS, 0x08)
        _put_fixed16(actors, OBJ_POS_X, 800)
        _put_fixed16(actors, OBJ_POS_Y, 0x70)  # ROM max lane most rounds
        _put_fixed16(actors, OBJ_POS_Z, 160)
        _put_u16(actors, OBJ_HEALTH, 0x50)
        _put_u8(actors, OBJ_CHARACTER_ID, 0x02)

        world = parse_world_map(
            actors_block=bytes(actors),
            camera_block=bytes(camera),
            p1_character_id=2,
            level_index=0,
        )
        p1 = world.entities[0]
        self.assertEqual(world.camera_bottom, float(0x70))
        self.assertEqual(world.camera_left, float(CAMERA_X_MIN))
        self.assertEqual(world.camera_right, float(CAMERA_X_MIN + CAMERA_X_SPAN))
        self.assertEqual(p1.map_y, 112.0)
        # world_x 800, cam 768 → map_x 32 = left walk limit (ROM $43AA).
        self.assertEqual(p1.map_x, float(CAMERA_X_MIN))
        # At left walk limit → left edge of camera box.
        self.assertAlmostEqual(
            (p1.map_x - world.camera_left) / world.camera_width, 0.0
        )
        # At bottom of playable lane → bottom edge of camera box.
        frac = (p1.map_y - world.camera_top) / world.camera_height
        self.assertAlmostEqual(frac, 1.0)
        # Camera is the walk band; view pads outside it. CRT is still 320 wide.
        self.assertLess(world.view_left, world.camera_left)
        self.assertGreater(world.view_right, world.camera_right)
        self.assertEqual(world.camera_right - world.camera_left, float(CAMERA_X_SPAN))
        self.assertEqual(SCREEN_WIDTH, 320)

    def test_held_or_exhausted_weapons_are_not_free_ground_items(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        free_base = 0x100
        _put_u8(actors, free_base + OBJ_TYPE, 0x0A)  # bat
        _put_u8(actors, free_base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, free_base + OBJ_POS_X, 800)
        _put_fixed16(actors, free_base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, free_base + OBJ_POS_Z, 0xA0)
        _put_u8(actors, free_base + OBJ_ITEM_PARAM, 0)
        _put_u8(actors, free_base + OBJ_INTERACTION, 0)

        held_base = 0x100 + OBJECT_SLOT_SIZE
        _put_u8(actors, held_base + OBJ_TYPE, 0x0B)  # pipe
        _put_u8(actors, held_base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, held_base + OBJ_POS_X, 820)
        _put_fixed16(actors, held_base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, held_base + OBJ_POS_Z, 0xA0)
        _put_u8(actors, held_base + OBJ_ITEM_PARAM, 0)
        _put_u8(actors, held_base + OBJ_INTERACTION, 1)  # reserved/held

        worn_base = 0x100 + 2 * OBJECT_SLOT_SIZE
        _put_u8(actors, worn_base + OBJ_TYPE, 0x08)  # knife
        _put_u8(actors, worn_base + OBJ_FLAGS, 0x00)
        _put_fixed16(actors, worn_base + OBJ_POS_X, 840)
        _put_fixed16(actors, worn_base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, worn_base + OBJ_POS_Z, 0xA0)
        _put_u8(actors, worn_base + OBJ_ITEM_PARAM, 3)  # exhausted
        _put_u8(actors, worn_base + OBJ_INTERACTION, 0)

        world = parse_world_map(
            actors_block=bytes(actors), camera_block=bytes(camera)
        )
        by_type = {
            entity.type_id: entity
            for entity in world.entities
            if entity.kind == "weapon"
        }
        self.assertTrue(by_type[0x0A].is_free_ground_item)
        self.assertFalse(by_type[0x0B].is_free_ground_item)
        self.assertFalse(by_type[0x08].is_free_ground_item)

    def test_top_of_lane_near_top(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        _put_u8(actors, OBJ_TYPE, 0x01)
        _put_u8(actors, OBJ_FLAGS, 0x08)
        _put_fixed16(actors, OBJ_POS_X, 800)
        _put_fixed16(actors, OBJ_POS_Y, 2)
        _put_fixed16(actors, OBJ_POS_Z, 160)
        _put_u16(actors, OBJ_HEALTH, 0x50)

        world = parse_world_map(
            actors_block=bytes(actors),
            camera_block=bytes(camera),
            p1_character_id=0,
            level_index=0,
        )
        p1 = world.entities[0]
        frac = (p1.map_y - world.camera_top) / world.camera_height
        self.assertLess(frac, 0.05)

    def test_round7_taller_lane(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        world = parse_world_map(
            actors_block=bytes(actors),
            camera_block=bytes(camera),
            level_index=6,
        )
        self.assertEqual(world.camera_bottom, float(0xA0))
        self.assertAlmostEqual(
            world.camera_width / world.camera_height, CAMERA_X_SPAN / 0xA0
        )

    def test_hitstun_flash_does_not_drop_on_screen_enemy(self) -> None:
        """SAT blink toggles flags bit0; on-screen enemies must stay on the map."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        def put_enemy(*, flags: int) -> None:
            base = 0x100
            _put_u8(actors, base + OBJ_TYPE, 0x20)
            _put_u8(actors, base + OBJ_FLAGS, flags)
            _put_fixed16(actors, base + OBJ_POS_X, 800)  # map_x = 32
            _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
            _put_fixed16(actors, base + OBJ_POS_Z, 160)
            _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0100)
            _put_u16(actors, base + OBJ_HEALTH, 6)

        put_enemy(flags=0x0C)  # visible frame
        w1 = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))
        self.assertTrue(any(e.type_id == 0x20 for e in w1.entities))

        put_enemy(flags=0x0D)  # same enemy, flash frame (bit0 set)
        w2 = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))
        self.assertTrue(any(e.type_id == 0x20 for e in w2.entities))

    def test_stage2_hidden_uninitialized_enemy_is_not_observed(self) -> None:
        """Exact Stage-2-start signature must not become a phantom target."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x21)
        _put_u8(actors, base + OBJ_FLAGS, 0x09)
        _put_fixed16(actors, base + OBJ_POS_X, 848)  # camera-relative X = 80
        _put_fixed16(actors, base + OBJ_POS_Y, 80)
        _put_fixed16(actors, base + OBJ_POS_Z, 160)
        _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0000)
        _put_u16(actors, base + OBJ_HEALTH, 0)

        world = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))

        self.assertFalse(any(e.kind == "enemy" for e in world.entities))

    def test_a_wave_slot_written_before_it_is_hidden_is_not_observed(self) -> None:
        """The one-frame gap between the spawn table and ``$937A``.

        A wave's object slots are populated before the activation entry runs,
        so for a frame they hold a complete entity that is *not* hidden yet
        and whose primary state is still ``$0000``. Requiring the SAT-hidden
        bit as well as the state left exactly that frame observable: recorded
        live, five enemies appeared for one tick at state ``$00`` with zero
        health and zero velocity, spread across the level ahead, and the AI
        punched at the nearest -- 48px away, at nothing -- before they
        vanished again.
        """

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x21)
        _put_u8(actors, base + OBJ_FLAGS, 0x0C)  # visible: the hidden bit is clear
        _put_fixed16(actors, base + OBJ_POS_X, 848)
        _put_fixed16(actors, base + OBJ_POS_Y, 80)
        _put_fixed16(actors, base + OBJ_POS_Z, 160)
        _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0000)
        _put_u16(actors, base + OBJ_HEALTH, 0)

        world = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))

        self.assertFalse(any(e.kind == "enemy" for e in world.entities))

    def test_an_activated_enemy_at_zero_health_is_still_observed(self) -> None:
        """Zero health is not defeated -- the ROM counts it alive and wants a
        finishing hit -- so an *activated* enemy must survive the filter."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        base = 0x100
        _put_u8(actors, base + OBJ_TYPE, 0x21)
        _put_u8(actors, base + OBJ_FLAGS, 0x0C)
        _put_fixed16(actors, base + OBJ_POS_X, 848)
        _put_fixed16(actors, base + OBJ_POS_Y, 80)
        _put_fixed16(actors, base + OBJ_POS_Z, 160)
        _put_u16(actors, base + OBJ_PRIMARY_STATE, 0x0100)  # activated
        _put_u16(actors, base + OBJ_HEALTH, 0)

        world = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))

        self.assertTrue(any(e.kind == "enemy" for e in world.entities))


if __name__ == "__main__":
    unittest.main()


class RomGeometryTests(unittest.TestCase):
    """MapEntity carries the real hitbox and attack ranges when RomData is
    supplied, and stays silent about both when it is not.

    Uses synthetic ROM tables rather than the real dump: the ROM is not
    versioned, so no test may depend on it. The values here mirror Nora's
    real layout (a single 32..80 whip) so the wiring is exercised against
    the shape it will actually see.
    """

    def _rom(self):
        from sor_autoplay.rom_data import RomData

        tables = _shape_tables(
            {
                1: (32, 48, 0, -44, 24),  # whip-like: reaches 32..80
                2: (-9, 18, 0, -60, 60),  # body
            }
        )
        from sor_autoplay.attack_ranges import ANIMATION_SET_FOR_TYPE, AnimationSets

        return RomData(
            shapes=tables,
            animations=AnimationSets(
                blocks={ANIMATION_SET_FOR_TYPE[0x26]: _animation_set([[(1, 2)]])}
            ),
        )

    def _nora_actors(self) -> bytes:
        actors = bytearray(ACTORS_BYTES)
        base = 0x100
        actors[base + OBJ_TYPE] = 0x26  # Nora, whose set is the one _rom builds
        actors[base + OBJ_PRIMARY_STATE] = 0x01
        actors[base + 0x03] = 2  # hitboxes.OBJ_BODY_BOX_ID
        _put_fixed16(actors, base + OBJ_POS_X, 800)
        _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
        _put_fixed16(actors, base + OBJ_POS_Z, 0x00)
        _put_u16(actors, base + OBJ_HEALTH, 11)
        return bytes(actors)

    def _camera(self) -> bytes:
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        return bytes(camera)

    def _nora_entity(self, rom):
        world = parse_world_map(
            actors_block=self._nora_actors(), camera_block=self._camera(), rom=rom
        )
        enemies = [e for e in world.entities if e.kind == "enemy"]
        self.assertEqual(len(enemies), 1)
        return enemies[0]

    def test_body_hitbox_is_built_at_the_objects_own_position(self) -> None:
        entity = self._nora_entity(self._rom())

        self.assertIsNotNone(entity.hitbox)
        self.assertEqual(entity.hitbox.x0, entity.world_x - 9)
        self.assertEqual(entity.hitbox.x1, entity.world_x + 9)

    def test_attack_ranges_come_from_the_types_animation_set(self) -> None:
        entity = self._nora_entity(self._rom())

        self.assertEqual(len(entity.attack_ranges), 1)
        self.assertEqual(
            (entity.attack_ranges[0].forward_min, entity.attack_ranges[0].forward_max),
            (32, 80),
        )

    def test_without_rom_data_both_stay_empty(self) -> None:
        entity = self._nora_entity(None)

        self.assertIsNone(entity.hitbox)
        self.assertEqual(entity.attack_ranges, ())


class PlayerHitboxTests(unittest.TestCase):
    """Unlike an enemy, a player caches its body box at +$70 every frame
    ($4140) -- world_map only has to read it (hitboxes.cached_box), so this
    needs no RomData at all."""

    def _p1_actors(self, *, cached_body: tuple[int, int, int, int, int, int] | None) -> bytes:
        actors = bytearray(ACTORS_BYTES)
        _put_u8(actors, OBJ_TYPE, 0x01)  # OBJ_TYPE_ACTIVE_PLAYER
        _put_u8(actors, OBJ_FLAGS, 0x08)
        _put_fixed16(actors, OBJ_POS_X, 800)
        _put_fixed16(actors, OBJ_POS_Y, 0x40)
        _put_fixed16(actors, OBJ_POS_Z, 0)
        _put_u16(actors, OBJ_HEALTH, 0x50)
        _put_u8(actors, OBJ_CHARACTER_ID, 0x00)
        if cached_body is not None:
            for i, value in enumerate(cached_body):
                offset = OBJ_CACHED_BODY_BOX + i * 2
                actors[offset : offset + 2] = int(value).to_bytes(2, "big", signed=True)
        return bytes(actors)

    def _camera(self) -> bytes:
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        return bytes(camera)

    def _p1_entity(self, *, cached_body):
        world = parse_world_map(
            actors_block=self._p1_actors(cached_body=cached_body),
            camera_block=self._camera(),
            p1_character_id=0,
        )
        players = [e for e in world.entities if e.kind == "player" and e.slot == "P1"]
        self.assertEqual(len(players), 1)
        return players[0]

    def test_reads_the_cached_body_box_with_no_rom_data(self) -> None:
        entity = self._p1_entity(cached_body=(780, 820, 34, 50, -40, -8))

        self.assertIsNotNone(entity.hitbox)
        self.assertEqual(
            (entity.hitbox.x0, entity.hitbox.x1, entity.hitbox.y0, entity.hitbox.y1),
            (780, 820, 34, 50),
        )

    def test_degenerate_cached_box_is_no_box(self) -> None:
        # $4140's no-attack fill collapses every axis to zero width.
        entity = self._p1_entity(cached_body=(0, 0, 0, 0, 0, 0))

        self.assertIsNone(entity.hitbox)

    def test_never_carries_attack_ranges(self) -> None:
        # A player's reach lives in tokens/character.py's punch geometry,
        # not in this ROM-extracted field.
        entity = self._p1_entity(cached_body=(780, 820, 34, 50, -40, -8))

        self.assertEqual(entity.attack_ranges, ())
