import json
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.games.trsim.view import RailPanic, Train
from app.tool_registry import ToolRegistry
from app.tools.minigame_trsim import register
from app.tools.workspace_presets import PRESETS, WorkspacePresets


class TRSimTests(unittest.TestCase):
    def setUp(self):
        directory = Path(__file__).resolve().parents[1] / 'user_data'
        directory.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='trsim-test-', dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.geometry('700x600')
        self.errors = []
        self.root.report_callback_exception = lambda _kind, error, _trace: self.errors.append(error)
        self.addCleanup(self.root.destroy)
        self.game = RailPanic(self.root, save_path=Path(self.temp.name) / 'save.json')
        self.game.paused = True
        self.game.pack(fill='both', expand=True)
        self.root.update()

    def tearDown(self):
        self.game.destroy()
        self.assertEqual(self.errors, [])

    def test_embedded_map_switches_train_pause_and_local_shortcuts(self):
        self.assertEqual(len(self.game.nodes), 14)
        node = self.game.nodes[0]
        self.game.trains.clear()
        before = node.switch
        self.game.draw()
        x = node.x * self.game._scale + self.game._offset[0]
        y = node.y * self.game._scale + self.game._offset[1]
        self.game.on_click(SimpleNamespace(x=x, y=y))
        self.assertNotEqual(node.switch, before)
        self.game.spawn_train()
        train = self.game.trains[0]
        x, y = self.game.train_position(train)
        self.game.on_click(SimpleNamespace(x=x * self.game._scale + self.game._offset[0],
                                            y=y * self.game._scale + self.game._offset[1]))
        self.assertTrue(train.paused)
        self.root.focus_force()
        self.game.canvas.focus_force()
        self.root.update()
        self.game.canvas.event_generate('<space>')
        self.assertFalse(self.game.paused)
        self.assertEqual(self.root.bind('<space>'), '')

    def test_save_reload_and_invalid_snapshot_preserve_running_state(self):
        self.game.score = 123
        self.game.save_game()
        self.game.score = 0
        self.game.load_game()
        self.assertEqual(self.game.score, 123)
        self.assertTrue(self.game.paused)
        data = json.loads(self.game.save_path.read_text(encoding='utf-8'))
        data['trains'] = [dict(node=999, target=0, next_node=1, progress=.3, speed=.01,
                              cargo='승객', color='#ffffff', reward=1, deadline=100)]
        self.game.save_path.write_text(json.dumps(data), encoding='utf-8')
        trains = self.game.trains[:]
        self.game.load_game()
        self.assertEqual(self.game.score, 123)
        self.assertEqual(self.game.trains, trains)
        self.assertIn('실패', self.game.event_log[0])

    def test_delivery_and_opposite_direction_collision_use_physical_position(self):
        train = Train(1, 0, 0, .99, .02, '승객', '#54a0ff', 100, self.game.day + 100)
        self.game.trains = [train]
        self.game.move_trains()
        self.assertEqual(self.game.trains, [])
        self.assertGreaterEqual(self.game.score, 100)
        def pair(first, second):
            self.game.trains = [Train(0, 2, 1, first, .01, '승객', '#54a0ff', 100, 999),
                                Train(1, 2, 0, second, .01, '우편', '#feca57', 100, 999)]
            self.game.check_collisions()
        pair(.25, .25)
        self.assertEqual(len(self.game.trains), 2)
        pair(.25, .75)
        self.assertEqual(self.game.trains, [])

    def test_small_map_fits_and_destroy_cancels_tick_without_root_bindings(self):
        self.root.geometry('500x430')
        self.root.update()
        width, height = self.game.canvas.winfo_width(), self.game.canvas.winfo_height()
        for node in self.game.nodes:
            x = node.x * self.game._scale + self.game._offset[0]
            y = node.y * self.game._scale + self.game._offset[1]
            self.assertTrue(0 < x < width and 0 < y < height)
        job = self.game._tick_job
        self.game.destroy()
        self.assertIsNone(self.game._tick_job)
        self.assertNotIn(job, self.root.tk.call('after', 'info'))
        self.root.update()

    def test_registry_and_workspace_preset_open_embedded_tool(self):
        registry = ToolRegistry()
        register(registry)
        tool = registry.tools_for('미니게임')[0]
        self.assertEqual(tool.id, 'minigame.trsim')
        opened = []
        app = SimpleNamespace(registry=registry, after_idle=lambda action: action(),
                              show_tool_from_palette=lambda spec: opened.append(spec.id))
        commands = [command for command in PRESETS['미니게임'] if command[0] == 'TRSim']
        with patch('app.tools.workspace_presets.subprocess.Popen') as process:
            WorkspacePresets.launch(SimpleNamespace(app=app), commands)
            process.assert_not_called()
        self.assertEqual(opened, ['minigame.trsim'])


if __name__ == '__main__':
    unittest.main()
