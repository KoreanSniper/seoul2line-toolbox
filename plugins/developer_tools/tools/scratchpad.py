from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame
from app.config import APP_DIR


DATA_PATH = APP_DIR / "scratchpad.json"


class Scratchpad(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.items = self._load()
        self.title_var = tk.StringVar()
        self._build()
        self.refresh()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=2)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="스크래치패드 + 코드 스니펫", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="자주 쓰는 코드, Minecraft 커맨드, 메모를 로컬 JSON에 저장하고 한 번에 복사합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        left = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=(0, 18))
        self.listbox = tk.Listbox(left.body, bg=colors["field"], fg=colors["text"], selectbackground=colors["accent_soft"], selectforeground=colors["text"], relief="flat", bd=0, font=("Segoe UI", 10), activestyle="none")
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self.load_selected())

        right = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=(0, 18))
        right.body.columnconfigure(0, weight=1)
        right.body.rowconfigure(1, weight=1)
        tk.Entry(right.body, textvariable=self.title_var, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, font=("Segoe UI", 11)).grid(row=0, column=0, sticky="ew", ipady=8)
        self.text = tk.Text(right.body, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="word", font=("Consolas", 10))
        self.text.grid(row=1, column=0, sticky="nsew", pady=10)
        actions = tk.Frame(right.body, bg=colors["surface"])
        actions.grid(row=2, column=0, sticky="ew")
        for label, command, accent in (("저장", self.save_item, True), ("복사", self.copy_item, False), ("새 메모", self.new_item, False), ("삭제", self.delete_item, False)):
            RoundedButton(actions, label, command, colors, accent=accent, compact=True, radius=10).pack(side="left", padx=(0, 8))

    def _load(self) -> list[dict[str, str]]:
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return [{"title": "Minecraft execute 예시", "body": "execute as @e[type=minecraft:zombie,distance=..10] at @s run say 감지됨"}]

    def _save(self) -> None:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        for item in self.items:
            self.listbox.insert("end", item.get("title", "제목 없음"))

    def load_selected(self) -> None:
        if not self.listbox.curselection():
            return
        item = self.items[self.listbox.curselection()[0]]
        self.title_var.set(item.get("title", ""))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", item.get("body", ""))

    def save_item(self) -> None:
        title = self.title_var.get().strip() or "제목 없음"
        body = self.text.get("1.0", "end-1c")
        index = self.listbox.curselection()[0] if self.listbox.curselection() else None
        if index is None:
            self.items.append({"title": title, "body": body})
        else:
            self.items[index] = {"title": title, "body": body}
        self._save()
        self.refresh()

    def copy_item(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end-1c"))

    def new_item(self) -> None:
        self.listbox.selection_clear(0, "end")
        self.title_var.set("")
        self.text.delete("1.0", "end")

    def delete_item(self) -> None:
        if not self.listbox.curselection():
            return
        del self.items[self.listbox.curselection()[0]]
        self._save()
        self.refresh()
        self.new_item()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return Scratchpad(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("developer.scratchpad", "스크래치패드", "개발자", build, 55))

