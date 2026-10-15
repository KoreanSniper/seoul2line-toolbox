from __future__ import annotations

import subprocess
import threading
import tkinter as tk

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


class ProcessManager(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.filter_var = tk.StringVar()
        self.rows: list[tuple[str, str, str, str]] = []
        self._destroyed = False
        self._build()
        self.refresh()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.columnconfigure(1, weight=1)
        tk.Label(header, text="프로세스 관리자", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Entry(header, textvariable=self.filter_var, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0).grid(row=0, column=1, sticky="ew", padx=12, ipady=8)
        self.filter_var.trace_add("write", lambda *_args: self.render_rows())
        RoundedButton(header, "새로고침", self.refresh, colors, accent=True, compact=True, radius=10).grid(row=0, column=2, padx=(0, 8))
        RoundedButton(header, "종료", self.kill_selected, colors, compact=True, radius=10).grid(row=0, column=3)

        panel = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        panel.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        panel.body.rowconfigure(0, weight=1)
        panel.body.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(panel.body, bg=colors["field"], fg=colors["text"], selectbackground=colors["accent_soft"], selectforeground=colors["text"], relief="flat", bd=0, activestyle="none", font=("Consolas", 10))
        self.listbox.grid(row=0, column=0, sticky="nsew")

    def refresh(self) -> None:
        if self._destroyed:
            return
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        command = "Get-Process | Sort-Object CPU -Descending | Select-Object -First 160 Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Csv -NoTypeInformation"
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, encoding="utf-8", errors="replace")
            rows = []
            for line in result.stdout.splitlines()[1:]:
                parts = [part.strip('"') for part in line.split('","')]
                if len(parts) >= 4:
                    mem_mb = int(float(parts[3].strip('"') or 0)) / 1024 / 1024
                    cpu = parts[2] or "0"
                    rows.append((parts[0], parts[1], cpu, f"{mem_mb:.1f} MB"))
        except Exception:
            rows = []
        if self._destroyed:
            return
        try:
            self.after(0, lambda: self._finish(rows))
        except tk.TclError:
            return

    def _finish(self, rows: list[tuple[str, str, str, str]]) -> None:
        if self._destroyed:
            return
        self.rows = rows
        self.render_rows()

    def render_rows(self) -> None:
        if self._destroyed or not self.listbox.winfo_exists():
            return
        query = self.filter_var.get().strip().lower()
        self.listbox.delete(0, "end")
        for pid, name, cpu, mem in self.rows:
            if query and query not in name.lower() and query not in pid:
                continue
            self.listbox.insert("end", f"{pid:>7}  {name:<32.32}  CPU {cpu:<9.9}  RAM {mem}")

    def kill_selected(self) -> None:
        if self._destroyed:
            return
        if not self.listbox.curselection():
            return
        line = self.listbox.get(self.listbox.curselection()[0])
        pid = line.strip().split()[0]
        subprocess.Popen(["taskkill", "/PID", pid, "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.after(500, self.refresh)

    def destroy(self) -> None:
        self._destroyed = True
        super().destroy()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return ProcessManager(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.process_manager", "프로세스 관리자", "파일", build, 40))
