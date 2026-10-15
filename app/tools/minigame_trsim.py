from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


def _coding_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _trsim_dir() -> Path:
    return _coding_root() / "GAME_MOD" / "TRSim"


class TRSimLauncher(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.status = tk.StringVar(value="TRSim 대기 중")
        self._build()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="TRSim", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="철도 건설, 물류, 도시 성장을 다루는 Tkinter 미니 경영 게임입니다.",
            font=("Segoe UI", 10),
            fg=colors["muted"],
            bg=colors["panel"],
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        actions = tk.Frame(header, bg=colors["panel"])
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        RoundedButton(actions, "폴더 열기", self.open_folder, colors, compact=True, radius=10).pack(side="left", padx=(0, 8))
        RoundedButton(actions, "실행", self.launch, colors, accent=True, compact=True, radius=10).pack(side="left")

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)

        info = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=18, padding=16)
        info.grid(row=0, column=0, sticky="ew")
        tk.Label(info.body, text="게임 메모", font=("Segoe UI", 14, "bold"), fg=colors["text"], bg=colors["surface"]).pack(anchor="w")
        for line in (
            "넓은 타일 격자 맵에 철길, 역, 화물 시설을 배치합니다.",
            "열차가 승객과 화물을 운송하며 수익과 유지비를 만듭니다.",
            "도시 성장, 화물 생산, 미니맵, 여러 선로/역 도구가 들어 있습니다.",
            "외부 패키지 없이 현재 Python으로 실행합니다.",
        ):
            tk.Label(info.body, text=line, fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 10), anchor="w").pack(anchor="w", pady=(10, 0))

        path_panel = RoundedFrame(body, colors, colors["panel_soft"], colors["border"], radius=16, padding=14)
        path_panel.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        tk.Label(path_panel.body, text=str(_trsim_dir()), fg=colors["muted"], bg=colors["panel_soft"], font=("Consolas", 9), wraplength=860, justify="left").pack(anchor="w")

        tk.Label(self, textvariable=self.status, fg=colors["muted"], bg=colors["panel"], anchor="w", font=("Segoe UI", 9)).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))

    def launch(self) -> None:
        project = _trsim_dir()
        script = project / "main.py"
        if not script.exists():
            self.status.set("TRSim main.py를 찾지 못했습니다.")
            messagebox.showerror("seoul2line Toolbox", f"TRSim을 찾지 못했습니다:\n{script}")
            return
        try:
            subprocess.Popen([sys.executable, str(script)], cwd=project)
        except OSError as exc:
            self.status.set(str(exc))
            messagebox.showerror("seoul2line Toolbox", str(exc))
            return
        self.status.set("TRSim 실행 명령을 보냈습니다.")

    def open_folder(self) -> None:
        project = _trsim_dir()
        if not project.exists():
            self.status.set("TRSim 폴더를 찾지 못했습니다.")
            return
        os.startfile(project)  # type: ignore[attr-defined]
        self.status.set("TRSim 폴더를 열었습니다.")


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return TRSimLauncher(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("minigame.trsim", "TRSim", "미니게임", build, 20))
