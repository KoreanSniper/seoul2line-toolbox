import unittest

from app.games.micro_warfare.model import Battlefield, Camera, WarfareGame


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
        self.game = WarfareGame()

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
        self.assertLess(worker.x, 7 * 32)
        self.assertIsNone(worker.target)


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.game = WarfareGame()
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
        self.game = WarfareGame()
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
        self.game = WarfareGame()
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


if __name__ == "__main__":
    unittest.main()
