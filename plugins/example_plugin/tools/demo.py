import tkinter as tk

from app.palette import palette
from app.tool_registry import ToolSpec


def build(parent: tk.Widget, app: object) -> tk.Widget:
    colors = palette(app.dark_mode)
    frame = tk.Frame(parent, bg=colors["panel"])
    tk.Label(
        frame,
        text="이 화면은 plugins/example_plugin에서 로드되었습니다.",
        fg=colors["text"],
        bg=colors["panel"],
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w", padx=22, pady=(22, 8))
    tk.Label(
        frame,
        text="이 구조를 복사해 파일 변환기, API 연동, 게임 도구 등 원하는 기능을 독립적으로 추가할 수 있습니다.",
        fg=colors["muted"],
        bg=colors["panel"],
        justify="left",
        wraplength=720,
    ).pack(anchor="w", padx=22)
    return frame


def register(registry) -> None:
    registry.register(ToolSpec("example_plugin.demo", "플러그인 예제", "플러그인", build, 0))
