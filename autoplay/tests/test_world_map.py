import unittest

from sor_autoplay.memory_map import (
    OBJ_CHARACTER_ID,
    OBJ_FLAGS,
    OBJ_HEALTH,
    OBJ_INTERACTION,
    OBJ_ITEM_PARAM,
    OBJ_JACK_WEAPON_ATTACHED,
    OBJ_POS_X,
    OBJ_POS_Y,
    OBJ_POS_Z,
    OBJ_PRIMARY_STATE,
    OBJ_OUTGOING_DAMAGE,
    OBJ_SCRIPT_PARAM,
    OBJ_SUBTYPE,
    OBJ_TYPE,
    OBJECT_SLOT_SIZE,
)
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


if __name__ == "__main__":
    unittest.main()
