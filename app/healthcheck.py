"""Non-interactive smoke check for the frozen release artifact."""
import json
from pathlib import Path
import sys
import traceback


def run(report_path: str) -> int:
    report = {"ok": False}
    app = None
    try:
        from app.main_window import Seoul2LineToolbox
        from app.config import APP_DIR
        from app.version import VERSION
        from app.tools.system_monitor import SystemMonitor
        from app.games.trsim.view import RailPanic
        from app.games.aim_trainer.view import AimTrainer
        from app.tools.gaming_soundboard import SoundboardTool
        from app.games.sandbox.view import SandboxView
        app = Seoul2LineToolbox()
        app.withdraw()
        app.updater.close()
        app.show_section("설정")
        app.update_idletasks()
        monitor = next(tool for tool in app.registry.tools_for("홈") if tool.id == "home.system_monitor")
        app.show_tool(monitor)
        app.update_idletasks()
        assert app.current_tool_id == "home.system_monitor"
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        monitor_view = next(widget for widget in descendants(app.workspace) if isinstance(widget, SystemMonitor))
        assert monitor_view._refresh_job is not None
        assert all(label.cget("text") != "-" for label in monitor_view.labels.values() if label is not monitor_view.labels["VRAM"])
        monitor_view.refresh()
        app.show_section("설정")
        app.update_idletasks()
        assert not monitor_view.winfo_exists()
        trsim = next(tool for tool in app.registry.tools_for('미니게임') if tool.id == 'minigame.trsim')
        app.show_tool(trsim)
        app.update_idletasks()
        trsim_view = next(widget for widget in descendants(app.workspace) if isinstance(widget, RailPanic))
        assert len(trsim_view.nodes) == 14 and trsim_view._tick_job is not None
        app.show_section('설정')
        app.update_idletasks()
        assert not trsim_view.winfo_exists() and trsim_view._tick_job is None
        aim = next(tool for tool in app.registry.tools_for('게임') if tool.id == 'gaming.aim_trainer')
        app.show_tool(aim)
        app.update_idletasks()
        aim_view = next(widget for widget in descendants(app.workspace) if isinstance(widget, AimTrainer))
        assert aim_view.fields['dpi'].get() == '800' and not aim_view.active
        app.show_section('설정')
        app.update_idletasks()
        assert not aim_view.winfo_exists() and aim_view.raw is None and aim_view.job is None
        soundboard = next(tool for tool in app.registry.tools_for('게임') if tool.id == 'gaming.soundboard')
        app.show_tool(soundboard)
        app.update_idletasks()
        soundboard_view = next(widget for widget in descendants(app.workspace) if isinstance(widget, SoundboardTool))
        assert soundboard_view.store is not None and not soundboard_view.editing
        import soundfile
        assert {'MP3', 'WAV', 'OGG'} <= set(soundfile.available_formats())
        import soundcard
        if getattr(sys, 'frozen', False):
            assert (Path(soundcard.__file__).parent / 'mediafoundation.py.h').is_file()
        app.show_section('설정')
        app.update_idletasks()
        assert not soundboard_view.winfo_exists() and soundboard_view.audio.closed
        sandbox = next(tool for tool in app.registry.tools_for('미니게임') if tool.id == 'minigame.sandbox')
        app.show_tool(sandbox)
        app.update_idletasks()
        sandbox_view = next(widget for widget in descendants(app.workspace) if isinstance(widget, SandboxView))
        assert sandbox_view.tick_id is not None and 'sand' in sandbox_view.world.cells
        app.show_section('설정')
        app.update_idletasks()
        assert not sandbox_view.winfo_exists() and sandbox_view.tick_id is None
        tools = [tool.id for section in app.registry.sections() for tool in app.registry.tools_for(section)]
        assert "minigame.micro_warfare" in tools and "minigame.orbit_lab" in tools
        assert not [plugin.error for plugin in app.plugin_manager.plugins if plugin.error]
        if getattr(sys, "frozen", False):
            assert (Path(sys._MEIPASS) / "updater/install_update.ps1").is_file()
            assert {plugin.id for plugin in app.plugin_manager.plugins} >= {"developer_tools", "automation_tools", "example_plugin"}
            automation_tools = app.registry.tools_for('자동화')
            assert {tool.id for tool in automation_tools} == {
                'automation.editor', 'automation.history', 'automation.manager'}
            assert all(tool.plugin_id == 'automation_tools' for tool in automation_tools)
        report.update(ok=True, version=VERSION, tool_count=len(tools), data_directory=str(APP_DIR),
                      plugins=[plugin.id for plugin in app.plugin_manager.plugins], checked_tools=["settings.preferences", "home.system_monitor", "minigame.trsim", "gaming.aim_trainer", "gaming.soundboard", "minigame.sandbox"])
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app is not None:
            app._close_app()
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
