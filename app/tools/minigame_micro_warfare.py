from app.games.micro_warfare.view import MicroWarfareView
from app.tool_registry import ToolSpec


def build(parent, app):
    return MicroWarfareView(parent, app)


def register(registry):
    registry.register(ToolSpec("minigame.micro_warfare", "Micro Warfare", "미니게임", build, 30))
