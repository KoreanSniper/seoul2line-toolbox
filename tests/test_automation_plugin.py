from pathlib import Path
import shutil
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest

from app.automation.runtime import AutomationRuntime
from app.automation.ui import Editor, Manager, image_example
from app.config import AppConfig
from app.main_window import Seoul2LineToolbox
from app.plugin_system import PluginManager
from app.tool_registry import load_builtin_tools
from app.tools.home import HomeOverview


class AutomationPluginTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        (root / 'user_data').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root / 'user_data', prefix='automation-plugin-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(root / 'plugins/automation_tools', self.root / 'plugins/automation_tools')
        self.config = AppConfig()
        self.manager = PluginManager(self.config, self.root)

    def registry(self, enabled=True):
        self.config.data.setdefault('plugins', {})['enabled'] = {'automation_tools': enabled}
        registry = load_builtin_tools()
        self.manager.load_into(registry)
        return registry

    def test_menu_is_registered_only_by_enabled_plugin_with_stable_ids(self):
        self.assertNotIn('자동화', load_builtin_tools().sections())
        registry = self.registry()
        self.assertEqual(self.manager.plugins[0].status, '활성')
        self.assertEqual(registry.section_spec('자동화').plugin_id, 'automation_tools')
        tools = registry.tools_for('자동화')
        self.assertEqual([tool.id for tool in tools],
                         ['automation.editor', 'automation.history', 'automation.manager'])
        self.assertTrue(all(tool.plugin_id == 'automation_tools' for tool in tools))
        for _ in range(2):
            disabled = self.registry(False)
            self.assertNotIn('자동화', disabled.sections())
            self.assertEqual(self.manager.plugins[0].status, '비활성화')
            search_app = SimpleNamespace(registry=disabled, toggle_gpt_panel=lambda: None,
                                         screenshot_manager=SimpleNamespace(capture_now=lambda: None))
            commands = Seoul2LineToolbox._build_palette_commands(search_app)
            self.assertFalse(any('automation.' in command.keywords or '자동화 열기' == command.title
                                 for command in commands))
            enabled = self.registry(True)
            self.assertEqual(len(enabled.tools_for('자동화')), 3)

    def test_plugin_factories_use_host_runtime_and_existing_storage_after_toggle(self):
        runtime = AutomationRuntime(self.root / 'user_data/automation')
        self.addCleanup(runtime.close)
        workflow = image_example()
        runtime.store.save(workflow)
        path = runtime.store.path(workflow['id'])
        before = path.read_bytes()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.dark_mode = True
        root.automation = runtime
        root.drain_automation_events = lambda: []
        app = root
        for enabled in (True, False, True):
            registry = self.registry(enabled)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(runtime.shutdown.is_set())
            for spec in registry.tools_for('자동화'):
                widget = spec.factory(root, app)
                self.assertIs(widget.runtime, runtime)
                self.assertIsInstance(widget, Editor if spec.id == 'automation.editor' else Manager)
                if spec.id != 'automation.editor':
                    self.assertEqual(widget.history, spec.id == 'automation.history')
                widget.destroy()
        self.assertEqual(runtime.store.list()[0]['id'], workflow['id'])

    def test_home_shortcut_opens_plugin_settings_when_automation_menu_is_disabled(self):
        registry = self.registry(False)
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        opened = []
        app = SimpleNamespace(dark_mode=True, registry=registry,
                              _open_command_palette=lambda: None,
                              show_tool_from_palette=lambda tool: opened.append(tool.id),
                              show_section=lambda section: opened.append(section))
        home = HomeOverview(root, app)
        home.cards[2].invoke()
        self.assertEqual(opened, ['settings.plugins'])
        home.destroy()


if __name__ == '__main__':
    unittest.main()
