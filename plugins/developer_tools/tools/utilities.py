from __future__ import annotations

import base64
import json
import time
import tkinter as tk
import urllib.parse
import uuid

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


class DeveloperUtilities(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.mode = tk.StringVar(value="JSON 정리")
        self._build()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="개발자 변환기", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="JSON, Base64, URL, timestamp, 진수, UUID를 한 화면에서 처리합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(3, 0))

        modes = tk.Frame(self, bg=colors["panel"])
        modes.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        for column in range(5):
            modes.columnconfigure(column, weight=1)
        for index, label in enumerate(("JSON 정리", "JSON 압축", "Base64 인코드", "Base64 디코드", "URL 인코드", "URL 디코드", "Timestamp", "진수 변환", "UUID")):
            RoundedButton(modes, label, lambda label=label: self._set_mode(label), colors, compact=True, radius=10).grid(row=index // 5, column=index % 5, sticky="ew", padx=3, pady=3)

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=16, padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=16, padding=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        tk.Label(left.body, text="입력", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        self.input = tk.Text(left.body, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="word", height=14, font=("Consolas", 10))
        self.input.pack(fill="both", expand=True)
        self.input.bind("<KeyRelease>", lambda _event: self.convert())

        right_head = tk.Frame(right.body, bg=colors["surface"])
        right_head.pack(fill="x", pady=(0, 8))
        tk.Label(right_head, text="결과", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 11, "bold")).pack(side="left")
        RoundedButton(right_head, "복사", self.copy_output, colors, compact=True, radius=9).pack(side="right")
        self.output = tk.Text(right.body, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="word", height=14, font=("Consolas", 10))
        self.output.pack(fill="both", expand=True)
        self.convert()

    def _set_mode(self, mode: str) -> None:
        self.mode.set(mode)
        self.convert()

    def convert(self) -> None:
        text = self.input.get("1.0", "end-1c")
        mode = self.mode.get()
        try:
            if mode == "JSON 정리":
                result = json.dumps(json.loads(text or "{}"), ensure_ascii=False, indent=2)
            elif mode == "JSON 압축":
                result = json.dumps(json.loads(text or "{}"), ensure_ascii=False, separators=(",", ":"))
            elif mode == "Base64 인코드":
                result = base64.b64encode(text.encode("utf-8")).decode("ascii")
            elif mode == "Base64 디코드":
                result = base64.b64decode(text.encode("ascii")).decode("utf-8")
            elif mode == "URL 인코드":
                result = urllib.parse.quote(text)
            elif mode == "URL 디코드":
                result = urllib.parse.unquote(text)
            elif mode == "Timestamp":
                value = int(text.strip() or time.time())
                result = f"Unix: {value}\nLocal: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(value))}"
            elif mode == "진수 변환":
                value = int(text.strip() or "0", 0)
                result = f"DEC {value}\nHEX {hex(value)}\nBIN {bin(value)}\nOCT {oct(value)}"
            else:
                result = str(uuid.uuid4())
        except Exception as exc:
            result = f"변환 실패: {exc}"
        self.output.delete("1.0", "end")
        self.output.insert("1.0", result)

    def copy_output(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.output.get("1.0", "end-1c"))


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return DeveloperUtilities(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("developer.utilities", "개발자 변환기", "개발자", build, 50))

