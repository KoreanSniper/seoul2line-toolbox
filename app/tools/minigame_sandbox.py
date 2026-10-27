from app.games.sandbox.view import SandboxView
from app.tool_registry import ToolSpec


def build(parent, app):
    return SandboxView(parent, app)


def register(registry):
    registry.register(ToolSpec("minigame.sandbox", "Sandbox", "미니게임", build, 32))
