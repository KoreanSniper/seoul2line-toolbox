import unittest
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from app.games.micro_warfare.model import Battlefield, Camera, Unit, WarfareGame
from app.games.micro_warfare.storage import load_game, restore, save_game, snapshot


class BattlefieldTests(unittest.TestCase):
    def test_seeded_generation_and_starting_zones(self):
        first = Battlefield.generate(7)
        self.assertEqual(first.tiles, Battlefield.generate(7).tiles)
        self.assertNotEqual(first.tiles, Battlefield.generate(8).tiles)
        self.assertEqual({tile for row in first.tiles for tile in row}, {"grass", "forest", "rock", "water"})
        self.assertTrue(first.walkable(6 * 32, 8 * 32))
        self.assertFalse(first.walkable(-1, 0))
        self.assertFalse(first.contains(first.pixel_width, 0))

    def test_camera_clamps_pan_and_resize(self):
        camera = Camera(2560, 1920)
        camera.pan(-100, -100)
        self.assertEqual((camera.x, camera.y), (0, 0))
        camera.pan(99999, 99999)
        self.assertEqual((camera.x, camera.y), (1760, 1320))
        camera.resize(4000, 4000)
        self.assertEqual((camera.x, camera.y), (0, 0))

    def test_zoom_keeps_cursor_world_position_and_limits(self):
        camera = Camera(2560, 1920, x=500, y=400)
        before = camera.to_world(200, 150)
        camera.zoom_at(1.5, 200, 150)
        self.assertEqual(camera.to_world(200, 150), before)
        sx, sy = camera.to_screen(*before)
        self.assertAlmostEqual(sx, 200)
        self.assertAlmostEqual(sy, 150)
        camera.zoom_at(100, 200, 150)
        self.assertEqual(camera.zoom, 2.5)
        camera.zoom_at(0.001, 200, 150)
        self.assertEqual(camera.zoom, 0.5)


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.game = WarfareGame(ai_enabled=False)

    def test_click_drag_and_shift_selection_do_not_select_enemy(self):
        worker = self.game.units[0]
        self.game.select(worker.x, worker.y, worker.x, worker.y)
        self.assertEqual(self.game.selected_ids, {worker.id})
        other = self.game.units[1]
        self.game.select(other.x, other.y, other.x, other.y, additive=True)
        self.assertEqual(len(self.game.selected_ids), 2)
        self.game.select(0, 0, 99999, 99999)
        self.assertEqual(self.game.selected_ids, {1, 2, 3, 4})
        self.game.select(-20, -20, -20, -20)
        self.assertFalse(self.game.selected_ids)

    def test_move_units_and_keep_formation(self):
        self.game.select(0, 0, 99999, 99999)
        self.assertTrue(self.game.issue_move(280, 350))
        for _ in range(100):
            self.game.update(0.1)
        self.assertTrue(all(unit.target is None for unit in self.game.selected_units))
        positions = {(round(unit.x), round(unit.y)) for unit in self.game.selected_units}
        self.assertEqual(len(positions), 4)
        self.assertEqual(positions, {(270, 350), (290, 350), (270, 370), (290, 370)})

    def test_reject_invalid_order_and_never_cross_obstacles(self):
        self.assertFalse(self.game.issue_move(200, 200))
        self.game.selected_ids = {1}
        self.assertFalse(self.game.issue_move(-1, 0))
        worker = self.game.units[0]
        self.game.world.tiles[8][7] = "water"
        self.assertTrue(self.game.issue_move(300, worker.y))
        self.game.update(10)
        self.assertAlmostEqual(worker.x, 300)
        self.assertAlmostEqual(worker.y, 8 * 32 + 16)
        self.assertIsNone(worker.target)

    def test_astar_unreachable_goal_and_dynamic_obstacle(self):
        worker = self.game.units[0]
        self.game.selected_ids = {worker.id}
        self.game.world.tiles = [["grass"] * self.game.world.width for _ in range(self.game.world.height)]
        self.assertTrue(self.game.issue_move(400, worker.y))
        self.game.world.tiles[8][8] = "rock"
        for _ in range(100):
            self.game.update(.1)
            self.assertTrue(self.game.walkable(worker.x, worker.y))
        self.assertAlmostEqual(worker.x, 400)
        for row in range(self.game.world.height):
            self.game.world.tiles[row][15] = "water"
        self.assertFalse(self.game.issue_move(600, worker.y))
        self.assertIsNone(worker.target)


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.game = WarfareGame(ai_enabled=False)
        self.game.selected_ids = {1, 2, 3, 4}

    def test_mine_carry_deposit_loop_conserves_resources(self):
        node = self.game.resources[0]
        node.amount = 100
        initial = self.game.stock["ore"] + node.amount
        self.assertTrue(self.game.issue_harvest(node))
        for _ in range(1200):
            self.game.update(0.1)
        self.assertAlmostEqual(node.amount, 0)
        self.assertAlmostEqual(self.game.stock["ore"], initial)
        self.assertTrue(all(unit.cargo == 0 for unit in self.game.units))

    def test_full_storage_keeps_cargo_and_resumes_after_spending(self):
        worker = self.game.units[0]
        worker.x, worker.y = self.game.depot
        worker.cargo, worker.returning = 20, True
        self.game.storage_capacity = sum(self.game.stock.values()) + 5
        self.game.update(0.1)
        self.assertEqual(worker.cargo, 15)
        self.game.stock["ore"] -= 20
        self.game.update(0.1)
        self.assertEqual(worker.cargo, 0)

    def test_cancel_harvest_retains_carried_resources(self):
        worker = self.game.units[0]
        worker.cargo, worker.resource_id = 10, 1
        self.game.issue_move(worker.x, worker.y + 32)
        self.assertIsNone(worker.resource_id)
        self.assertEqual(worker.cargo, 10)
        self.game.issue_deposit()
        for _ in range(100):
            self.game.update(0.1)
        self.assertEqual(worker.cargo, 0)
        self.assertEqual(self.game.stock["ore"], 210)


class BuildingTests(unittest.TestCase):
    def setUp(self):
        self.game = WarfareGame(ai_enabled=False)
        self.game.selected_ids = {1}

    def advance(self, seconds):
        for _ in range(int(seconds * 10)):
            self.game.update(0.1)

    def test_construction_cost_progress_and_capacity(self):
        self.assertTrue(self.game.issue_build("warehouse", 8, 5))
        building = self.game.buildings[-1]
        self.assertFalse(building.complete)
        self.assertEqual(self.game.stock, {"ore": 140, "wood": 70})
        self.advance(15)
        self.assertTrue(building.complete)
        self.assertEqual(self.game.storage_capacity, 3000)
        self.assertFalse(self.game.walkable(*building.center))

    def test_invalid_placement_and_funds_do_not_change_stock(self):
        before = self.game.stock.copy()
        for col, row in ((-1, 0), (5, 5), (6, 8), (11, 8)):
            self.assertFalse(self.game.issue_build("warehouse", col, row))
        self.assertEqual(self.game.stock, before)
        self.game.stock["wood"] = 0
        self.assertFalse(self.game.issue_build("barracks", 8, 5))
        self.assertEqual(len(self.game.buildings), 2)

    def test_upgrade_cost_timer_level_and_capacity(self):
        self.game.selected_building = 1
        self.assertTrue(self.game.upgrade())
        self.assertEqual(self.game.stock, {"ore": 120, "wood": 90})
        self.assertFalse(self.game.upgrade())
        self.advance(6)
        self.assertEqual(self.game.buildings[0].level, 2)
        self.assertEqual(self.game.storage_capacity, 4000)

    def test_interrupted_construction_can_resume(self):
        self.assertTrue(self.game.issue_build("warehouse", 8, 5))
        self.game.issue_move(200, 300)
        self.advance(10)
        self.assertEqual(self.game.buildings[-1].progress, 0)
        self.game.selected_building = self.game.buildings[-1].id
        self.assertTrue(self.game.resume_build())
        self.advance(15)
        self.assertTrue(self.game.buildings[-1].complete)


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.game = WarfareGame(ai_enabled=False)
        self.game.selected_building = 1
        self.game.stock = {"ore": 5000.0, "wood": 5000.0}

    def advance(self, seconds):
        for _ in range(int(seconds * 10)):
            self.game.update(0.1)

    def test_hq_queue_is_serial_and_cancel_refunds(self):
        self.assertTrue(self.game.enqueue("worker"))
        self.assertTrue(self.game.enqueue("worker"))
        self.advance(2)
        self.assertEqual(len(self.game.units), 5)
        self.assertEqual(self.game.buildings[0].queue[1].progress, 0)
        self.assertTrue(self.game.cancel_production(1))
        self.assertEqual(self.game.stock, {"ore": 4950, "wood": 4980})
        self.advance(3)
        self.assertEqual(len(self.game.units), 6)
        self.assertFalse(self.game.buildings[0].queue)
        self.assertEqual(self.game.units[-1].role, "worker")

    def test_limits_wrong_building_and_funds(self):
        self.assertFalse(self.game.enqueue("soldier"))
        for _ in range(5):
            self.assertTrue(self.game.enqueue("worker"))
        self.assertFalse(self.game.enqueue("worker"))
        self.advance(5)
        self.assertTrue(self.game.enqueue("worker"))
        self.assertFalse(self.game.enqueue("worker"))  # Population reserved reaches 10.
        self.assertFalse(self.game.cancel_production(-1))
        self.game.cancel_production(0)
        self.game.stock = {"ore": 0, "wood": 0}
        self.assertFalse(self.game.enqueue("worker"))

    def test_blocked_exit_retains_finished_order_until_space_is_available(self):
        self.game.enqueue("worker")
        self.game.world.tiles = [["water"] * self.game.world.width for _ in range(self.game.world.height)]
        self.advance(10)
        self.assertEqual(len(self.game.units), 5)
        self.assertEqual(len(self.game.buildings[0].queue), 1)
        self.game.world.tiles[4][4] = "grass"
        self.game.update(0.1)
        self.assertEqual(len(self.game.units), 6)
        self.assertFalse(self.game.buildings[0].queue)

    def test_barracks_construction_then_soldier_production(self):
        self.game.selected_ids = {1}
        self.assertTrue(self.game.issue_build("barracks", 8, 5))
        self.game.selected_building = self.game.buildings[-1].id
        self.assertFalse(self.game.enqueue("soldier"))
        self.advance(15)
        self.assertTrue(self.game.enqueue("soldier"))
        self.advance(7)
        self.assertEqual(self.game.units[-1].role, "soldier")
        self.assertEqual(self.game.units[-1].owner, 0)


class CombatTests(unittest.TestCase):
    def setUp(self):
        self.game = WarfareGame(ai_enabled=False)
        self.game.world.tiles = [["grass"] * self.game.world.width for _ in range(self.game.world.height)]
        self.game.units = [Unit(10, 0, 500, 500, "soldier"), Unit(11, 1, 620, 500, "soldier")]
        self.game.selected_ids = {10}

    def test_range_cooldown_and_death_cleanup(self):
        self.assertTrue(self.game.issue_attack(self.game.units[1]))
        self.game.update(.1)
        self.assertEqual(self.game.units[1].hp, 88)
        self.game.update(.1)
        self.assertEqual(self.game.units[1].hp, 88)
        self.game.units[1].hp = 1
        self.game.units[0].cooldown = 0
        self.game.update(.1)
        self.assertEqual([unit.id for unit in self.game.units], [10])
        self.assertEqual(self.game.selected_ids, {10})

    def test_chase_and_auto_acquire(self):
        self.game.units[1].x = 800
        self.assertTrue(self.game.issue_attack(self.game.units[1]))
        for _ in range(50):
            self.game.update(.1)
        self.assertLess(sum(unit.hp for unit in self.game.units), 200)
        self.assertGreater(self.game.units[0].x, 500)

    def test_rock_blocks_fire_and_ai_seeks_clear_shot(self):
        self.game.world.tiles[15][17] = "rock"
        self.game.update(.1)
        self.assertEqual(self.game.units[1].hp, 100)
        self.assertTrue(self.game.units[0].path)

    def test_building_destroyed_and_cannot_be_selected(self):
        building = self.game.buildings[1]
        self.game.units = [Unit(10, 0, building.center[0] - 120, building.center[1], "soldier")]
        building.hp = 1
        self.game.issue_attack(building)
        self.game.update(.1)
        self.assertNotIn(building, self.game.buildings)


class EnemyAITests(unittest.TestCase):
    def test_enemy_mines_builds_produces_and_launches_attack(self):
        game = WarfareGame()
        player_stock = game.stock.copy()
        game.selected_ids = {1}
        game.selected_building = 1
        for _ in range(900):
            game.update(.1)
        self.assertTrue(any(item.kind == "barracks" and item.owner == 1 and item.complete for item in game.buildings))
        self.assertTrue(any(node.id >= 3 and node.amount < 500 for node in game.resources))
        self.assertGreaterEqual(sum(unit.owner == 1 and unit.role == "soldier" for unit in game.units), 3)
        self.assertTrue(any(unit.owner == 1 and unit.attack_target is not None for unit in game.units))
        self.assertEqual(game.stock, player_stock)
        self.assertEqual(game.selected_ids, {1})
        self.assertEqual(game.selected_building, 1)
        self.assertTrue(all(amount >= 0 for amount in game.enemy_stock.values()))

    def test_no_free_enemy_production_without_resources(self):
        game = WarfareGame()
        game.enemy_stock = {"ore": 0, "wood": 0}
        game.resources = game.resources[:2]
        game.elapsed = 5
        game.plan_enemy_turn()
        self.assertEqual(len(game.buildings), 2)
        self.assertFalse(any(item.queue for item in game.buildings))


class GameModeTests(unittest.TestCase):
    def test_skirmish_victory_defeat_draw_and_game_stops(self):
        for removed, expected in (({1}, "victory"), ({0}, "defeat"), ({0, 1}, "draw")):
            with self.subTest(expected=expected):
                game = WarfareGame(ai_enabled=False)
                game.buildings = [item for item in game.buildings if item.owner not in removed]
                game.update(.1)
                self.assertEqual(game.result, expected)
                elapsed = game.elapsed
                game.update(10)
                self.assertEqual(game.elapsed, elapsed)
                self.assertFalse(game.issue_move(300, 300))
                self.assertFalse(game.enqueue("worker"))

    def test_annihilation_requires_all_units_and_buildings_to_be_destroyed(self):
        game = WarfareGame(ai_enabled=False, mode="annihilation")
        game.buildings = [item for item in game.buildings if item.owner == 0]
        game.update(.1)
        self.assertEqual(game.result, "running")
        game.units = [item for item in game.units if item.owner == 0]
        game.update(.1)
        self.assertEqual(game.result, "victory")

    def test_sandbox_no_enemy_economy_or_ending_and_pause_freezes_timers(self):
        game = WarfareGame(mode="sandbox")
        self.assertFalse(game.ai_enabled)
        game.buildings = [item for item in game.buildings if item.owner == 0]
        game.update(.1)
        self.assertEqual(game.result, "running")
        game.selected_building = 1
        game.enqueue("worker")
        game.paused = True
        game.update(10)
        self.assertEqual(game.buildings[0].queue[0].progress, 0)
        game.paused = False
        game.update(5)
        self.assertEqual(len(game.units), 6)


class StorageTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "user_data"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="warfare-test-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "battle.json"

    def test_roundtrip_preserves_active_orders_queues_and_future_simulation(self):
        game = WarfareGame()
        game.selected_ids = {1, 2}
        game.issue_harvest(game.resources[0])
        game.selected_building = 1
        game.enqueue("worker")
        for _ in range(20):
            game.update(.1)
        save_game(game, self.path)
        loaded = load_game(self.path)
        self.assertEqual(snapshot(loaded), snapshot(game))
        for _ in range(300):
            game.update(.1)
            loaded.update(.1)
        self.assertEqual(snapshot(loaded), snapshot(game))

    def test_invalid_saves_do_not_load(self):
        good = snapshot(WarfareGame())
        cases = []
        for field, bad in (("version", 999), ("units", [{}]), ("paused", "false"), ("next_unit_id", 1)):
            data = deepcopy(good)
            data[field] = bad
            cases.append(data)
        data = deepcopy(good)
        data["units"][0]["hp"] = float("nan")
        cases.append(data)
        data = deepcopy(good)
        data["buildings"][0]["queue"] = [{"kind": "soldier", "progress": 0}]
        cases.append(data)
        for data in cases:
            with self.subTest(data=str(data)[:60]), self.assertRaises(ValueError):
                restore(data)
        self.path.write_text("not json")
        with self.assertRaises(ValueError):
            load_game(self.path)

    def test_failed_save_keeps_previous_file_and_cleans_temporary(self):
        game = WarfareGame()
        save_game(game, self.path)
        original = self.path.read_bytes()
        game.elapsed = 999
        with patch("app.games.micro_warfare.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                save_game(game, self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_finished_game_and_statistics_restore(self):
        game = WarfareGame(ai_enabled=False)
        game.world.tiles = [["grass"] * game.world.width for _ in range(game.world.height)]
        enemy = game.buildings[1]
        enemy.hp = 1
        game.units = [Unit(1, 0, enemy.center[0] - 120, enemy.center[1], "soldier")]
        game.selected_ids = {1}
        game.issue_attack(enemy)
        game.update(.1)
        save_game(game, self.path)
        loaded = load_game(self.path)
        self.assertEqual(loaded.result, "victory")
        self.assertEqual(loaded.statistics[0]["damage_dealt"], 1)
        self.assertEqual(loaded.statistics[0]["buildings_destroyed"], 1)
        self.assertEqual(loaded.statistics[1]["buildings_lost"], 1)


if __name__ == "__main__":
    unittest.main()
