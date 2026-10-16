import tkinter as tk
import unittest
from types import SimpleNamespace

from app.main_window import PaletteCommand, Seoul2LineToolbox


class SearchWindow(Seoul2LineToolbox):
    """Exercise the real search widgets without starting background services."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.geometry("1280x760")
        self.dark_mode = True
        self.command_palette = None
        self.palette_results = None
        self.palette_selection = 0
        self.palette_matches = []
        self.executed = []
        self.shell = tk.Frame(self, bg="#191c28")
        self.shell.pack(fill="both", expand=True)
        self._build_search_header()
        self.workspace = tk.Frame(self.shell, takefocus=True)
        self.workspace.pack(fill="both", expand=True)
        self.bind_all("<Control-k>", self._open_command_palette)
        self.bind_all("<Button-1>", self._dismiss_search_outside, add="+")
        self.update()

    def _build_palette_commands(self):
        return [PaletteCommand(title, subtitle, keywords,
                               lambda title=title: self.executed.append(title))
                for title, subtitle, keywords in (
                    ("시스템 모니터", "하드웨어 도구", "system monitor"),
                    ("플러그인 관리", "설정 도구", "plugin"),
                    ("설정 열기", "테마 변경", "settings"),
                )]


class GlobalSearchTests(unittest.TestCase):
    def setUp(self):
        self.app = SearchWindow()

    def tearDown(self):
        self.app.destroy()

    def test_search_and_keyboard_selection_execute_actual_command(self):
        self.app._open_command_palette(SimpleNamespace(keysym="k"))
        self.app.palette_query.set("도구")
        self.assertEqual(len(self.app.palette_matches), 2)
        self.app._move_search_selection(1)
        self.app.search_entry.focus_force()
        self.app.update()
        self.app.search_entry.event_generate("<Return>")
        self.app.update()
        self.assertEqual(self.app.executed, ["플러그인 관리"])
        self.assertIsNone(self.app.command_palette)

    def test_no_results_does_not_execute_and_escape_dismisses(self):
        self.app._open_command_palette()
        self.app.palette_query.set("없는 도구 xyz")
        self.app._run_first_palette_command()
        self.assertEqual(self.app.executed, [])
        self.assertEqual(self.app.palette_matches, [])
        self.app._escape_search()
        self.assertIsNone(self.app.command_palette)
        self.assertEqual(self.app.palette_query.get(), "")

    def test_shortcut_reuses_popup_and_preserves_query(self):
        self.app._open_command_palette()
        self.app.palette_query.set("system")
        popup = self.app.command_palette
        self.app._open_command_palette(SimpleNamespace(keysym="k"))
        self.assertIs(self.app.command_palette, popup)
        self.assertEqual(self.app.palette_query.get(), "system")
        self.assertEqual(self.app.search_entry.selection_get(), "system")
        self.app._run_first_palette_command()
        self.assertEqual(self.app.executed, ["시스템 모니터"])

    def test_search_is_centered_and_fits_minimum_window(self):
        for width in (980, 1280, 1600):
            self.app.geometry(f"{width}x620")
            self.app.update()
            self.app._open_command_palette()
            self.app.update()
            box = self.app.search_box
            self.assertAlmostEqual(box.winfo_x() + box.winfo_width() / 2,
                                   self.app.header.winfo_width() / 2, delta=2)
            self.assertGreaterEqual(box.winfo_width(), 580)
            self.assertLessEqual(box.winfo_width(), 720)
            popup = self.app.command_palette
            self.assertLess(popup.winfo_y() + popup.winfo_height(), 620)
            self.app._dismiss_search_outside(SimpleNamespace(widget=self.app.workspace))
            self.assertIsNone(self.app.command_palette)


if __name__ == "__main__":
    unittest.main()
