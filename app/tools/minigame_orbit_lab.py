from app.games.orbit_lab.view import OrbitLabView
from app.tool_registry import ToolSpec


def build(parent, app):
    return OrbitLabView(parent, app)


def register(registry):
    registry.register(ToolSpec("minigame.orbit_lab", "Orbit Lab", "미니게임", build, 31))
