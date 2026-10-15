from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.games.micro_warfare.storage import snapshot
from app.games.micro_warfare.view import MicroWarfareView


class WarfareUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.view = MicroWarfareView(self.root, SimpleNamespace(dark_mode=True))
        self.view.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.view.camera.resize(1000, 620)

    def click(self, x, y):
        sx, sy = self.view.camera.to_screen(x, y)
        event = SimpleNamespace(x=sx, y=sy, state=0)
        self.view.select_start(event)
        self.view.select_end(event)

    def test_select_build_produce_cancel_and_mode_reset(self):
        self.click(self.view.game.units[0].x, self.view.game.units[0].y)
        self.view.start_build("barracks")
        self.click(8 * 32 + 1, 5 * 32 + 1)
        self.assertEqual(len(self.view.game.buildings), 3)
        for _ in range(150):
            self.view.game.update(.1)
        building = self.view.game.buildings[2]
        self.assertTrue(building.complete)
        self.click(*building.center)
        self.view.produce("soldier")
        self.assertEqual(self.view.queue_list.size(), 1)
        self.view.queue_list.selection_set(0)
        self.view.cancel_production()
        self.assertEqual(self.view.queue_list.size(), 0)
        self.view.mode_choice.set("샌드박스")
        self.view.new_world()
        self.assertFalse(self.view.game.ai_enabled)
        self.view.toggle_pause()
        self.assertTrue(self.view.game.paused)
        self.view.destroy()
        self.assertIsNone(self.view.tick_id)

    def test_save_load_and_corrupt_load_keeps_current_game(self):
        directory = Path(__file__).resolve().parents[1] / "user_data"
        with tempfile.TemporaryDirectory(prefix="warfare-ui-", dir=directory) as temporary:
            path = Path(temporary) / "battle.json"
            saved = snapshot(self.view.game)
            with patch("app.games.micro_warfare.view.filedialog.asksaveasfilename", return_value=str(path)):
                self.view.save_current()
            self.view.new_world()
            with patch("app.games.micro_warfare.view.filedialog.askopenfilename", return_value=str(path)):
                self.view.load_current()
            self.assertEqual(snapshot(self.view.game), saved)
            current = self.view.game
            path.write_text("invalid")
            with patch("app.games.micro_warfare.view.filedialog.askopenfilename", return_value=str(path)), patch("app.games.micro_warfare.view.messagebox.showerror") as error:
                self.view.load_current()
            error.assert_called_once()
            self.assertIs(self.view.game, current)


if __name__ == "__main__":
    unittest.main()
