from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.games.sandbox.view import SandboxView
from app.tool_registry import ToolRegistry
from app.tools.minigame_sandbox import register
from app.theme_art import tool_icon


class SandboxUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("880x700")
        self.addCleanup(self.root.destroy)
        self.view = SandboxView(self.root, SimpleNamespace(dark_mode=True))
        self.view.pack(fill="both", expand=True)
        self.view.paused = True
        self.root.update()
        self.root.update_idletasks()

    def point(self, x, y):
        v = self.view
        return SimpleNamespace(x=v.offset[0] + (x + .5) * v.scale,
                               y=v.offset[1] + (y + .5) * v.scale)

    def test_draw_interpolated_brush_erase_and_probe(self):
        v = self.view
        v.clear()
        v.select("sand")
        v.brush_size.set(1)
        v.paint(self.point(10, 10))
        v.paint(self.point(30, 10))
        self.assertTrue(all(v.world.cells[10 * 160 + x] == "sand" for x in range(10, 31)))
        v.hover(self.point(20, 10))
        self.assertIn("모래", v.status.get())
        self.assertIn("20°C", v.status.get())
        v.paint(self.point(20, 10), erase=True)
        self.assertEqual(v.world.cells[10 * 160 + 20], "empty")
        v.wheel(SimpleNamespace(delta=120))
        self.assertEqual(v.brush_size.get(), 2)

    def test_pause_step_and_local_keyboard_binding(self):
        v = self.view
        v.toggle_pause()
        self.assertFalse(v.paused)
        v.single_step()
        self.assertTrue(v.paused)
        self.assertEqual(v.world.ticks, 1)
        self.assertTrue(v.canvas.bind("<KeyPress-space>"))
        self.assertFalse(self.root.bind("<KeyPress-space>"))

    def test_save_load_and_corruption_preserves_current_scene(self):
        v = self.view
        with TemporaryDirectory() as directory:
            v.save_path = Path(directory) / "scene.json"
            v.save()
            cells = v.world.cells.copy()
            v.clear()
            v.load()
            self.assertEqual(v.world.cells, cells)
            self.assertTrue(v.paused)
            v.save_path.write_text('{"version": 99}')
            v.load()
            self.assertIn("실패", v.message)
            self.assertEqual(v.world.cells, cells)

    def test_three_themes_resize_bounded_canvas_and_timer_cleanup(self):
        for theme in ("dark", "light", "green"):
            v = SandboxView(self.root, SimpleNamespace(dark_mode=theme))
            v.pack(fill="both", expand=True)
            self.root.update_idletasks()
            v.draw()
            self.assertEqual(len(v.canvas.find_all()), 2)
            v.destroy()
            self.assertIsNone(v.tick_id)
        self.root.geometry("640x620")
        self.root.update_idletasks()
        self.view.draw()
        self.assertGreater(self.view.canvas.winfo_width(), 200)
        self.assertIsNone(self.view.position(SimpleNamespace(x=-2, y=-2)))
        self.view.destroy()
        self.assertIsNone(self.view.tick_id)
        self.assertIsNone(self.view.photo)
        self.assertIsNone(self.view.status)

    def test_registry(self):
        registry = ToolRegistry()
        register(registry)
        tool = registry.tools_for("미니게임")[0]
        self.assertEqual((tool.id, tool.label), ("minigame.sandbox", "Sandbox"))
        self.assertEqual(tool_icon(tool.id), "cube")

    def test_material_wheel_and_arrow_navigation(self):
        v = self.view
        v.side_canvas.yview_moveto(0)
        for _ in range(20):
            v.scroll_materials(SimpleNamespace(delta=-120))
        self.assertGreater(v.side_canvas.yview()[0], 0)
        self.assertTrue(v.buttons["sand"].bind("<MouseWheel>"))
        v.cycle_material("sand", 1)
        self.assertEqual(v.selected, "water")
        v.cycle_material("empty", -1)
        self.assertEqual(v.selected, "cool")
        self.assertGreater(v.side_canvas.yview()[0], 0)

    def test_high_speed_budget_and_hidden_world_do_not_advance(self):
        v = self.view
        v.after_cancel(v.tick_id)
        v.tick_id = None
        v.paused = False
        v.speed.set("4")
        with patch.object(v, "winfo_ismapped", return_value=True), \
                patch.object(v.world, "step") as step, \
                patch("app.games.sandbox.view.time.perf_counter", side_effect=[0, .04]):
            v.tick()
            self.assertEqual(step.call_count, 1)
        v.after_cancel(v.tick_id)
        with patch.object(v, "winfo_ismapped", return_value=False), patch.object(v.world, "step") as step:
            v.tick()
            step.assert_not_called()

    def test_save_failure_and_missing_load_keep_scene(self):
        v = self.view
        original = v.world
        with patch.object(v.world, "save", side_effect=OSError("쓰기 거부")):
            v.save()
        self.assertIn("저장 실패", v.message)
        self.assertIs(v.world, original)
        with TemporaryDirectory() as directory:
            v.save_path = Path(directory) / "missing.json"
            v.load()
        self.assertIn("불러오기 실패", v.message)
        self.assertIs(v.world, original)

    def test_loading_new_grid_resets_pointer_and_drag_anchor(self):
        from app.games.sandbox.model import Sandbox
        v = self.view
        with TemporaryDirectory() as directory:
            v.save_path = Path(directory) / "small.json"
            Sandbox(8, 8).save(v.save_path)
            v.pointer = v.last_point = (159, 99)
            v.load()
        self.assertEqual((v.world.width, v.world.height), (8, 8))
        self.assertIsNone(v.pointer)
        self.assertIsNone(v.last_point)


if __name__ == "__main__":
    unittest.main()
