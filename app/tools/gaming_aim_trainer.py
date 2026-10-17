from app.games.aim_trainer.view import AimTrainer
from app.tool_registry import ToolSpec


def register(registry):
    registry.register(ToolSpec("gaming.aim_trainer", "에임 연습", "게임", AimTrainer, 30))
