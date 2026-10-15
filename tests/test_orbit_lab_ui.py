import tkinter as tk
from types import SimpleNamespace
import unittest

from app.games.orbit_lab.view import OrbitLabView
from app.tools.minigame_orbit_lab import register
from app.tool_registry import ToolRegistry


class OrbitLabUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.view = OrbitLabView(self.root, SimpleNamespace(dark_mode=True))
        self.view.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.view.resize(SimpleNamespace(width=800, height=500))

    def test_planet_moon_placement_mass_and_invalid_input(self):
        self.view.system.selected_id = 1
        self.view.start_placement("moon")
        sx, sy = self.view.camera.to_screen(300, 200)
        self.view.click(SimpleNamespace(x=sx, y=sy))
        self.assertEqual(len(self.view.system.bodies), 3)
        self.assertEqual(self.view.system.selected.parent_id, 1)
        self.view.mass.set("25")
        self.view.apply_mass()
        self.assertEqual(self.view.system.selected.mass, 25)
        self.view.mass.set("nan")
        self.view.apply_mass()
        self.assertEqual(self.view.system.selected.mass, 25)
        self.view.start_placement("planet")
        self.view.cancel_placement()
        self.assertIsNone(self.view.placement)

    def test_clock_camera_launch_rotation_and_throttle(self):
        self.view.toggle_pause()
        self.view.single_step()
        self.assertAlmostEqual(self.view.system.elapsed, .05)
        self.view.speed_choice.set("20")
        self.view.change_speed()
        self.assertEqual(self.view.system.time_scale, 20)
        self.view.system.selected_id = 1
        self.view.launch()
        ship = self.view.system.selected
        self.assertEqual(ship.kind, "ship")
        self.view.rotate(5)
        self.assertEqual(ship.heading, 95)
        self.view.throttle.set(50)
        self.view.throttle_changed()
        self.assertEqual(ship.throttle, .5)
        self.view.key(SimpleNamespace(keysym="d"))
        self.assertGreater(self.view.camera.x, 0)
        self.view.wheel(SimpleNamespace(delta=120, x=200, y=100))
        self.assertGreater(self.view.camera.zoom, 1)
        self.view.reset_camera()
        self.assertEqual(self.view.camera.zoom, 1)
        self.view.destroy()
        self.assertIsNone(self.view.tick_id)

    def test_light_theme_and_registry(self):
        light = OrbitLabView(self.root, SimpleNamespace(dark_mode=False))
        light.draw()
        light.destroy()
        registry = ToolRegistry()
        register(registry)
        self.assertIn("미니게임", registry.sections())


if __name__ == "__main__":
    unittest.main()
