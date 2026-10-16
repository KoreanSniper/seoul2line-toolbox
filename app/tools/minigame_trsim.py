from app.games.trsim.view import RailPanic
from app.tool_registry import ToolSpec


def build(parent, app):
    return RailPanic(parent, app)


def register(registry):
    registry.register(ToolSpec('minigame.trsim', 'TRSim', '미니게임', build, 20))
