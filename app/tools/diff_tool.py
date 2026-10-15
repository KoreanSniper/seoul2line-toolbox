from __future__ import annotations

import difflib
import tkinter as tk

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


class DiffTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self._build()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="파일 비교 / Diff", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="두 텍스트나 JSON을 붙여넣고 바뀐 줄을 빠르게 확인합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        editors = tk.Frame(self, bg=colors["panel"])
        editors.grid(row=1, column=0, sticky="nsew", padx=18)
        editors.columnconfigure(0, weight=1)
        editors.columnconfigure(1, weight=1)
        self.left = self._text_panel(editors, "왼쪽", 0)
        self.right = self._text_panel(editors, "오른쪽", 1)

        result_panel = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        result_panel.grid(row=2, column=0, sticky="nsew", padx=18, pady=18)
        result_panel.body.rowconfigure(1, weight=1)
        result_panel.body.columnconfigure(0, weight=1)
        bar = tk.Frame(result_panel.body, bg=colors["surface"])
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(bar, text="결과", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 11, "bold")).pack(side="left")
        RoundedButton(bar, "비교", self.compare, colors, accent=True, compact=True, radius=10).pack(side="right")
        self.output = tk.Text(result_panel.body, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="none", font=("Consolas", 10))
        self.output.grid(row=1, column=0, sticky="nsew")

    def _text_panel(self, parent: tk.Widget, title: str, column: int) -> tk.Text:
        colors = palette(self.app.dark_mode)
        panel = RoundedFrame(parent, colors, colors["surface"], colors["border"], radius=16, padding=12)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        tk.Label(panel.body, text=title, fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        text = tk.Text(panel.body, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="none", height=8, font=("Consolas", 10))
        text.pack(fill="both", expand=True)
        return text

    def compare(self) -> None:
        left = self.left.get("1.0", "end-1c").splitlines()
        right = self.right.get("1.0", "end-1c").splitlines()
        diff = difflib.unified_diff(left, right, fromfile="left", tofile="right", lineterm="")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", "\n".join(diff) or "차이가 없습니다.")


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return DiffTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.diff", "파일 비교 / Diff", "파일", build, 30))
