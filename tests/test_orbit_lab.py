import unittest
import math

from app.games.orbit_lab.model import G, OrbitSystem, SpaceCamera


class SpaceCameraTests(unittest.TestCase):
    def test_screen_world_roundtrip_with_negative_positions(self):
        camera = SpaceCamera(x=-500, y=250, zoom=.5)
        self.assertEqual(camera.to_world(*camera.to_screen(-400, -100)), (-400, -100))
        camera.resize(1000, 700)
        self.assertEqual(camera.to_screen(-500, 250), (500, 350))

    def test_zoom_anchor_and_limits(self):
        camera = SpaceCamera()
        before = camera.to_world(150, 200)
        camera.zoom_at(1.8, 150, 200)
        after = camera.to_world(150, 200)
        self.assertAlmostEqual(before[0], after[0])
        self.assertAlmostEqual(before[1], after[1])
        camera.zoom_at(100, 0, 0)
        self.assertEqual(camera.zoom, 8)
        camera.zoom_at(.0001, 0, 0)
        self.assertEqual(camera.zoom, .05)
        with self.assertRaises(ValueError):
            camera.zoom_at(float("nan"), 0, 0)

    def test_pan_is_measured_in_screen_pixels(self):
        camera = SpaceCamera(zoom=2)
        camera.pan(100, -50)
        self.assertEqual((camera.x, camera.y), (50, -25))


class BodyTests(unittest.TestCase):
    def test_add_planet_and_moon_with_initial_orbit(self):
        system = OrbitSystem()
        planet = system.add_body("planet", "새 행성", 2000, 20, -500, -200)
        moon = system.add_moon(planet.id, "새 위성", 2, 4, -400, -200)
        self.assertEqual(moon.parent_id, planet.id)
        self.assertAlmostEqual(moon.vy, math.sqrt(G * 2002 / 100))
        self.assertEqual(system.body_at(planet.x, planet.y), planet)

    def test_reject_invalid_mass_radius_overlap_and_missing_parent(self):
        system = OrbitSystem()
        for mass in (0, -1, float("nan"), float("inf")):
            with self.subTest(mass=mass), self.assertRaises(ValueError):
                system.add_body("planet", "실패", mass, 10, 500, 500)
        with self.assertRaises(ValueError):
            system.add_body("planet", "겹침", 1, 10, 0, 0)
        with self.assertRaises(ValueError):
            system.add_moon(999, "위성", 1, 2, 500, 0)
        self.assertEqual(len(system.bodies), 2)

    def test_mass_edit_and_parent_removal_keep_other_body(self):
        system = OrbitSystem()
        system.set_mass(1, 5000)
        self.assertEqual(system.bodies[0].mass, 5000)
        with self.assertRaises(ValueError):
            system.set_mass(1, -10)
        self.assertEqual(system.bodies[0].mass, 5000)
        system.selected_id = 1
        system.remove_selected()
        self.assertEqual(len(system.bodies), 1)
        self.assertIsNone(system.bodies[0].parent_id)


class GravityTests(unittest.TestCase):
    def test_inverse_square_and_mutual_force(self):
        system = OrbitSystem()
        system.bodies = []
        first = system.add_body("planet", "A", 100, 1, 0, 0)
        second = system.add_body("planet", "B", 10, 1, 10, 0)
        acceleration = system.accelerations()
        self.assertAlmostEqual(acceleration[first.id][0], .1)
        self.assertAlmostEqual(acceleration[second.id][0], -1)
        second.x = 20
        self.assertAlmostEqual(system.accelerations()[first.id][0], .025)

    def test_circular_orbit_conserves_energy_momentum_and_distance(self):
        system = OrbitSystem()
        initial_energy = system.energy()
        initial_momentum = system.momentum()
        planet, moon = system.bodies
        period = 2 * math.pi * math.sqrt(180 ** 3 / (G * (planet.mass + moon.mass)))
        for _ in range(20):
            self.assertAlmostEqual(system.advance(period / 20), period / 20)
        self.assertAlmostEqual(math.hypot(moon.x - planet.x, moon.y - planet.y), 180, delta=.02)
        self.assertLess(abs((system.energy() - initial_energy) / initial_energy), 1e-6)
        for before, after in zip(initial_momentum, system.momentum()):
            self.assertAlmostEqual(before, after, delta=1e-8)

    def test_empty_scene_invalid_duration_and_work_budget(self):
        system = OrbitSystem()
        self.assertAlmostEqual(system.advance(1, max_steps=2), .1)
        self.assertTrue(system.physics_limited)
        system.bodies.clear()
        self.assertEqual(system.advance(.1), .1)
        self.assertEqual(system.momentum(), (0, 0))
        with self.assertRaises(ValueError):
            system.advance(float("inf"))


class SimulationClockTests(unittest.TestCase):
    def test_speed_pause_and_single_step(self):
        system = OrbitSystem()
        system.set_time_scale(20)
        self.assertAlmostEqual(system.advance_real_time(.1), 2)
        self.assertAlmostEqual(system.elapsed, 2)
        system.paused = True
        before = [(body.x, body.y) for body in system.bodies]
        self.assertEqual(system.advance_real_time(.1), 0)
        self.assertEqual([(body.x, body.y) for body in system.bodies], before)
        self.assertAlmostEqual(system.single_step(), .05)
        self.assertAlmostEqual(system.elapsed, 2.05)
        system.paused = False
        self.assertEqual(system.single_step(), 0)

    def test_maximum_speed_and_stalls_have_bounded_work(self):
        system = OrbitSystem()
        system.set_time_scale(100)
        advanced = system.advance_real_time(100)
        self.assertLessEqual(advanced, 128 * .05 + 1e-9)
        self.assertTrue(system.physics_limited)
        self.assertAlmostEqual(system.effective_speed, advanced / 100)
        with self.assertRaises(ValueError):
            system.set_time_scale(3)
        self.assertEqual(system.time_scale, 100)


class SpacecraftTests(unittest.TestCase):
    def test_launch_outside_surface_inherits_velocity(self):
        system = OrbitSystem()
        planet = system.bodies[0]
        planet.vx, planet.vy = 2, 3
        ship = system.launch_ship(planet.id, 24, 90)
        self.assertEqual(ship.parent_id, planet.id)
        self.assertAlmostEqual(ship.vx, 2)
        self.assertAlmostEqual(ship.vy, -21)
        self.assertGreater(math.hypot(ship.x - planet.x, ship.y - planet.y), ship.radius + planet.radius)
        self.assertEqual((ship.mass, ship.fuel), (2, 100))

    def test_thrust_rotation_fuel_and_pause(self):
        system = OrbitSystem()
        ship = system.launch_ship(1, 0, 0, fuel=1)
        ship.vx = ship.vy = 0
        system.bodies = [ship]
        system.set_throttle(1)
        system.paused = True
        system.advance_real_time(.1)
        self.assertEqual(ship.fuel, 1)
        system.paused = False
        system.advance(.5)
        self.assertAlmostEqual(ship.fuel, .5)
        self.assertGreater(ship.vx, 20)
        self.assertAlmostEqual(ship.vy, 0)
        system.rotate_ship(90)
        system.advance(.6)
        self.assertEqual(ship.fuel, 0)
        self.assertEqual(ship.throttle, 0)
        self.assertEqual(ship.mass, ship.dry_mass)
        self.assertLess(ship.vy, -20)
        before = (ship.vx, ship.vy)
        system.advance(1)
        self.assertEqual((ship.vx, ship.vy), before)

    def test_invalid_launch_and_throttle_do_not_mutate_scene(self):
        system = OrbitSystem()
        for speed in (-1, float("nan")):
            with self.assertRaises(ValueError):
                system.launch_ship(1, speed, 90)
        self.assertEqual(len(system.bodies), 2)
        with self.assertRaises(ValueError):
            system.set_throttle(.5)
        ship = system.launch_ship(1, 10, 0)
        with self.assertRaises(ValueError):
            system.set_throttle(2)
        with self.assertRaises(ValueError):
            system.set_mass(ship.id, 100)
        self.assertEqual(ship.throttle, 0)


if __name__ == "__main__":
    unittest.main()
