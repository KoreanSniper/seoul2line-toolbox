from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from pathlib import Path

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


class DeveloperTerminal(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.cwd = tk.StringVar(value=str(Path.cwd()))
        self.command = tk.StringVar()
        self.running = False
        self._build()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="통합 터미널", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="PowerShell 명령을 Toolbox 안에서 실행합니다. 출력은 비동기로 받아 UI를 멈추지 않습니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        bar = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=10)
        bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        bar.body.columnconfigure(1, weight=1)
        tk.Label(bar.body, text="경로", fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Entry(bar.body, textvariable=self.cwd, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0).grid(row=0, column=1, sticky="ew", ipady=7)

        panel = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        panel.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        panel.body.columnconfigure(0, weight=1)
        panel.body.rowconfigure(0, weight=1)
        self.output = tk.Text(panel.body, bg="#05080d" if self.app.dark_mode else "#ffffff", fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="word", font=("Consolas", 10))
        self.output.grid(row=0, column=0, columnspan=2, sticky="nsew")
        entry = tk.Entry(panel.body, textvariable=self.command, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, font=("Consolas", 10))
        entry.grid(row=1, column=0, sticky="ew", pady=(10, 0), ipady=9)
        entry.bind("<Return>", lambda _event: self.run_command())
        RoundedButton(panel.body, "실행", self.run_command, colors, accent=True, compact=True, radius=10).grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(10, 0))

    def run_command(self) -> None:
        if self.running:
            return
        command = self.command.get().strip()
        if not command:
            return
        self.command.set("")
        self._append(f"> {command}\n")
        self.running = True
        threading.Thread(target=self._run_worker, args=(command,), daemon=True).start()

    def _run_worker(self, command: str) -> None:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                cwd=self.cwd.get() or None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output = result.stdout
            if result.stderr:
                output += result.stderr
            output += f"\n종료 코드: {result.returncode}\n"
        except Exception as exc:
            output = f"실행 실패: {exc}\n"
        self.after(0, lambda: self._finish(output))

    def _finish(self, output: str) -> None:
        self._append(output)
        self.running = False

    def _append(self, text: str) -> None:
        self.output.insert("end", text)
        self.output.see("end")


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return DeveloperTerminal(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("developer.terminal", "통합 터미널", "개발자", build, 45))

