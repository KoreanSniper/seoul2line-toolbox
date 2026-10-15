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
        app = Seoul2LineToolbox()
        app.withdraw()
        app.updater.close()
        app.show_section("설정")
        app.update_idletasks()
        tools = [tool.id for section in app.registry.sections() for tool in app.registry.tools_for(section)]
        assert "minigame.micro_warfare" in tools and "minigame.orbit_lab" in tools
        assert not [plugin.error for plugin in app.plugin_manager.plugins if plugin.error]
        if getattr(sys, "frozen", False):
            assert (Path(sys._MEIPASS) / "updater/install_update.ps1").is_file()
            assert {plugin.id for plugin in app.plugin_manager.plugins} >= {"developer_tools", "example_plugin"}
        report.update(ok=True, version=VERSION, tool_count=len(tools), data_directory=str(APP_DIR),
                      plugins=[plugin.id for plugin in app.plugin_manager.plugins])
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app is not None:
            app._close_app()
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
