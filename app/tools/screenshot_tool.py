from __future__ import annotations

import tkinter as tk

from app.screenshot import screenshot_dir
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame
from app.palette import palette


class ScreenshotTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        self.build()

    def build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="영역 캡쳐", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="앱이 켜져 있으면 다른 앱 위에서도 PrintScreen 하나로 바로 영역 선택을 시작합니다.",
            font=("Segoe UI", 10),
            fg=colors["muted"],
            bg=colors["panel"],
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        card = RoundedFrame(self, colors, colors["panel_soft"], colors["border"], radius=18, padding=16)
        card.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        card.body.columnconfigure(1, weight=1)
        self._info_row(card.body, "단축키", "PrintScreen")
        self._info_row(card.body, "동작", "화면 고정 → 드래그 선택 → PNG 저장 → 이미지 클립보드 복사")
        self._info_row(card.body, "저장 위치", str(screenshot_dir()))

        actions = tk.Frame(card.body, bg=colors["panel_soft"])
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        RoundedButton(actions, "지금 캡쳐", self.app.screenshot_manager.capture_now, colors, accent=True, radius=10, anchor="center").grid(row=0, column=0, sticky="ew", padx=(0, 8))
        RoundedButton(actions, "저장 폴더 경로 복사", self.copy_folder, colors, radius=10, anchor="center").grid(row=0, column=1, sticky="ew")

        tip = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=14)
        tip.grid(row=2, column=0, sticky="ew", padx=18)
        tk.Label(
            tip.body,
            text="Esc를 누르면 선택을 취소합니다. 너무 작은 영역은 저장하지 않습니다.",
            font=("Segoe UI", 10),
            fg=colors["muted"],
            bg=colors["surface"],
            justify="left",
        ).pack(anchor="w")

    def _info_row(self, parent: tk.Widget, label: str, value: str) -> None:
        colors = self.colors
        row = len(parent.grid_slaves()) // 2
        tk.Label(parent, text=label, font=("Segoe UI", 9, "bold"), fg=colors["accent"], bg=colors["panel_soft"], width=11, anchor="w").grid(
            row=row,
            column=0,
            sticky="nw",
            pady=5,
            padx=(0, 12),
        )
        tk.Label(parent, text=value, font=("Segoe UI", 9), fg=colors["text"], bg=colors["panel_soft"], anchor="w", justify="left", wraplength=760).grid(
            row=row,
            column=1,
            sticky="ew",
            pady=5,
        )

    def copy_folder(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(str(screenshot_dir()))


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return ScreenshotTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.screenshot", "영역 캡쳐", "파일", build, 64))
