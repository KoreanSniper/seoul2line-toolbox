from app.automation.ui import Manager
from app.tool_registry import ToolSpec


def register(registry):
    registry.register(ToolSpec("automation.history", "자동화 실행 기록", "자동화", lambda parent, app: Manager(parent, app, history=True), 10))
