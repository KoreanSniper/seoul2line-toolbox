from __future__ import annotations

import tkinter as tk

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


class ClipboardHistory(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.items: list[str] = []
        self.running = True
        self._build()
        self.after(900, self.poll_clipboard)

    def destroy(self) -> None:
        self.running = False
        super().destroy()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="클립보드 기록", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="이 도구가 열려 있을 때만 최근 텍스트 클립보드를 가볍게 기록합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        panel = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        panel.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        panel.body.rowconfigure(0, weight=1)
        panel.body.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(panel.body, bg=colors["field"], fg=colors["text"], selectbackground=colors["accent_soft"], selectforeground=colors["text"], relief="flat", bd=0, font=("Consolas", 10), activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        actions = tk.Frame(panel.body, bg=colors["surface"])
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        RoundedButton(actions, "다시 복사", self.copy_selected, colors, accent=True, compact=True, radius=10).pack(side="left", padx=(0, 8))
        RoundedButton(actions, "비우기", self.clear, colors, compact=True, radius=10).pack(side="left")

    def poll_clipboard(self) -> None:
        if not self.running:
            return
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        text = text.strip()
        if text and (not self.items or self.items[0] != text):
            self.items.insert(0, text)
            self.items = self.items[:40]
            self.refresh()
        self.after(900, self.poll_clipboard)

    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        for item in self.items:
            preview = item.replace("\n", " ")[:180]
            self.listbox.insert("end", preview)

    def copy_selected(self) -> None:
        if not self.listbox.curselection():
            return
        self.clipboard_clear()
        self.clipboard_append(self.items[self.listbox.curselection()[0]])

    def clear(self) -> None:
        self.items.clear()
        self.refresh()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return ClipboardHistory(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.clipboard_history", "클립보드 기록", "파일", build, 20))
