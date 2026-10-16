from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


PRESETS = {
    "마크 개발": [
        ("VS Code", "code ..\\.."),
        ("Minecraft 폴더", "explorer %APPDATA%\\.minecraft"),
    ],
    "Python": [
        ("VS Code", "code ..\\.."),
        ("PowerShell", "powershell -NoExit -Command Set-Location ..\\.."),
    ],
    "발로란트": [
        ("Riot Client", ""),
    ],
    "미니게임": [
        ("항성계", "py -m app.tools.chill_starsystem_gpu --run"),
        ("TRSim", "toolbox:minigame.trsim"),
    ],
}


class WorkspacePresets(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self._build()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="작업공간 프리셋", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="필요한 프로그램 묶음을 한 번에 실행합니다. 빈 경로는 설정 후 사용하면 됩니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        grid = tk.Frame(self, bg=colors["panel"])
        grid.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 18))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        for index, (name, commands) in enumerate(PRESETS.items()):
            card = RoundedFrame(grid, colors, colors["surface"], colors["border"], radius=16, padding=14)
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=6, pady=6)
            tk.Label(card.body, text=name, fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
            tk.Label(card.body, text=", ".join(label for label, _cmd in commands), fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9), wraplength=320, justify="left").pack(anchor="w", pady=(6, 12))
            RoundedButton(card.body, "실행", lambda commands=commands: self.launch(commands), colors, accent=True, compact=True, radius=10).pack(anchor="w")

    def launch(self, commands: list[tuple[str, str]]) -> None:
        root = Path(__file__).resolve().parents[2]
        for _label, command in commands:
            if not command:
                continue
            if command.startswith('toolbox:'):
                tool_id = command.removeprefix('toolbox:')
                tool = next((tool for section in self.app.registry.sections()
                             for tool in self.app.registry.tools_for(section) if tool.id == tool_id), None)
                if tool is not None:
                    # Defer navigation until all commands in this preset have been dispatched.
                    self.app.after_idle(lambda tool=tool: self.app.show_tool_from_palette(tool))
                continue
            try:
                subprocess.Popen(command, cwd=root, shell=True)
            except OSError:
                pass


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return WorkspacePresets(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("gaming.workspace_presets", "작업공간 프리셋", "게임", build, 20))
