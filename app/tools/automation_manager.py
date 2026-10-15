from app.automation.ui import Manager
from app.tool_registry import ToolSpec


def register(registry):
    registry.register(ToolSpec("automation.manager", "자동화 관리", "자동화", Manager, 20))
