import tkinter as tk
import unittest
from types import SimpleNamespace

from app.config import AppConfig
from app.main_window import Seoul2LineToolbox
from app.palette import ThemeMode, palette
from app.tool_registry import ToolRegistry, ToolSpec
from app.tools.home import HomeOverview, build


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class LayoutWindow(Seoul2LineToolbox):
    """Real shell without background services or changes to user settings."""
    def __init__(self, mode=ThemeMode.DARK):
        tk.Tk.__init__(self)
        self.callback_errors = []
        self.report_callback_exception = lambda _kind, error, _trace: self.callback_errors.append(error)
        self.title('seoul2line Toolbox — UI preview')
        self.geometry('1280x760')
        self.dark_mode = mode
        self.config_store = AppConfig()
        self.stock_price_engine = SimpleNamespace(running=False)
        self.screenshot_manager = SimpleNamespace(capture_now=lambda: None)
        self.registry = ToolRegistry()
        self.registry.register(ToolSpec('home.overview', '개요', '홈', build, 0))
        for tool_id, title, section in (
            ('home.system_monitor', '시스템 모니터', '홈'),
            ('automation.editor', '워크플로', '자동화'),
            ('settings.preferences', '테마 및 화면', '설정'),
            ('file.test', '파일 관리', '파일'),
        ):
            self.registry.register(ToolSpec(tool_id, title, section,
                                           lambda parent, _app: tk.Frame(parent)))
        self.current_section = '홈'
        self.current_tool_id = None
        self.section_buttons = {}
        self.tool_buttons = {}
        self.menu_buttons = {}
        self.gpt_panel_visible = False
        self.tool_nav_collapsed = False
        self.tool_nav_width = 224
        self.command_palette = None
        self.palette_results = None
        self.palette_selection = 0
        self.palette_matches = []
        self.gpt_help_label = None
        self._build_layout()
        self.show_section('홈')
        self.update()

    @property
    def home(self):
        return next(widget for widget in descendants(self.workspace) if isinstance(widget, HomeOverview))

    def dispose(self):
        for job in self.tk.call('after', 'info'):
            self.after_cancel(job)
        self.destroy()


class HomeLayoutTests(unittest.TestCase):
    def setUp(self):
        self.app = LayoutWindow()

    def tearDown(self):
        errors = self.app.callback_errors[:]
        self.app.dispose()
        self.assertEqual(errors, [])

    def test_reference_cards_execute_search_monitor_automation_and_settings(self):
        self.assertEqual(len(self.app.home.cards), 4)
        self.app.home.cards[0].invoke()
        self.assertIsNotNone(self.app.command_palette)
        self.app._close_command_palette()
        for index, tool_id, section in ((1, 'home.system_monitor', '홈'),
                                        (2, 'automation.editor', '자동화'),
                                        (3, 'settings.preferences', '설정')):
            self.app.show_section('홈')
            self.app.update()
            self.app.home.cards[index].invoke()
            self.app.update()
            self.assertEqual(self.app.current_tool_id, tool_id)
            self.assertEqual(self.app.current_section, section)
        self.app.show_section('홈')
        self.app.update()
        link = next(link for link in self.app.home.tool_links if link.cget('text') == '파일 관리')
        link.invoke()
        self.assertEqual(self.app.current_tool_id, 'file.test')
        self.assertEqual(self.app.current_section, '파일')

    def test_collapsing_restores_width_and_keyboard_can_toggle(self):
        self.assertTrue(self.app._pane_contains(self.app.main_pane, self.app.tool_nav))
        self.app.main_pane.sash_place(0, 270, 1)
        self.app.update()
        width = self.app.tool_nav.winfo_width()
        narrow = self.app.workspace.winfo_width()
        self.app.nav_toggle.focus_force()
        self.app.update()
        self.app.nav_toggle.event_generate('<Return>')
        self.app.update()
        self.assertTrue(self.app.tool_nav_collapsed)
        self.assertGreater(self.app.workspace.winfo_width(), narrow + 190)
        self.app.toggle_tool_nav()
        self.app.update()
        self.assertAlmostEqual(self.app.tool_nav.winfo_width(), width, delta=2)

    def test_cards_reflow_scroll_and_show_focus_at_minimum_size(self):
        self.app.geometry('1672x941')
        self.app.update()
        home = self.app.home
        self.assertEqual(home.canvas.coords(home.card_windows[0])[1],
                         home.canvas.coords(home.card_windows[1])[1])
        self.app.geometry('980x620')
        self.app.update()
        self.assertGreater(home.canvas.coords(home.card_windows[1])[1],
                           home.canvas.coords(home.card_windows[0])[1])
        for item in home.card_windows:
            x, _y = home.canvas.coords(item)
            self.assertLessEqual(x + float(home.canvas.itemcget(item, 'width')), home.canvas.winfo_width())
        home.cards[0].event_generate('<MouseWheel>', delta=-120)
        self.app.update()
        self.assertGreater(home.canvas.yview()[0], 0)
        home.canvas.yview_moveto(0)
        self.app.update()
        home.cards[0].focus_force()
        self.app.update()
        for card in home.cards[:-1]:
            card.event_generate('<Tab>')
            self.app.update()
        self.app.update()
        item = home.card_windows[-1]
        bottom = home.canvas.coords(item)[1] + float(home.canvas.itemcget(item, 'height'))
        self.assertGreaterEqual(home.canvas.canvasy(home.canvas.winfo_height()), bottom - 2)
        self.assertTrue(home.cards[-1].hover)
        home.cards[-1].event_generate('<Tab>')
        self.app.update()
        for link in home.tool_links[:-1]:
            link.event_generate('<Tab>')
            self.app.update()
        self.assertEqual(self.app.focus_get(), home.tool_links[-1])
        last_link = home.tool_links[-1]
        link_bottom = home.canvas.coords(home.catalog_window)[1] + last_link.master.winfo_y() + last_link.winfo_y() + last_link.winfo_height()
        self.assertGreaterEqual(home.canvas.canvasy(home.canvas.winfo_height()), link_bottom - 2)
        last_link.event_generate('<Return>')
        self.assertEqual(self.app.current_tool_id, 'settings.preferences')

    def test_each_theme_rebuilds_and_preserves_collapsed_navigation(self):
        self.app.toggle_tool_nav()
        for mode in ThemeMode:
            self.app.config_store.data['theme'] = mode.value
            self.app.reload_theme()
            self.app.update()
            self.assertEqual(self.app.dark_mode, mode)
            self.assertFalse(self.app._pane_contains(self.app.main_pane, self.app.tool_nav))
            self.assertEqual(len(self.app.home.cards), 4)
            self.assertEqual(self.app.home.colors, palette(mode))
            self.assertTrue(self.app.home.canvas.find_withtag('decoration'))


if __name__ == '__main__':
    unittest.main()
