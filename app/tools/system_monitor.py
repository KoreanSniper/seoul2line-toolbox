from __future__ import annotations

import ctypes
import shutil
import subprocess
import time
import tkinter as tk

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedFrame


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SystemMonitor(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.labels: dict[str, tk.Label] = {}
        self.running = True
        self.last_net: tuple[int, int, float] | None = None
        self._build()
        self.refresh()

    def destroy(self) -> None:
        self.running = False
        super().destroy()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="시스템 모니터", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="CPU/RAM/GPU/디스크/네트워크를 낮은 주기로 확인합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        grid = tk.Frame(self, bg=colors["panel"])
        grid.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 18))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        for index, key in enumerate(("CPU", "RAM", "GPU", "VRAM", "디스크", "네트워크")):
            card = RoundedFrame(grid, colors, colors["surface"], colors["border"], radius=16, padding=14)
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=6, pady=6)
            tk.Label(card.body, text=key, fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            label = tk.Label(card.body, text="-", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 16, "bold"))
            label.pack(anchor="w", pady=(6, 0))
            self.labels[key] = label

    def refresh(self) -> None:
        if not self.running:
            return
        data = self.snapshot()
        for key, value in data.items():
            self.labels[key].configure(text=value)
        self.after(2500, self.refresh)

    def snapshot(self) -> dict[str, str]:
        memory = MEMORYSTATUSEX()
        memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
        used = (memory.ullTotalPhys - memory.ullAvailPhys) / 1024 / 1024 / 1024
        total = memory.ullTotalPhys / 1024 / 1024 / 1024
        disk = shutil.disk_usage(Path.cwd().anchor or ".")
        gpu, vram = self.gpu_snapshot()
        return {
            "CPU": self.cpu_snapshot(),
            "RAM": f"{memory.dwMemoryLoad}%  {used:.1f}/{total:.1f} GB",
            "GPU": gpu,
            "VRAM": vram,
            "디스크": f"{disk.used / disk.total * 100:.0f}%  {disk.free / 1024 / 1024 / 1024:.0f} GB 여유",
            "네트워크": self.net_snapshot(),
        }

    def cpu_snapshot(self) -> str:
        try:
            result = subprocess.run(
                ["wmic", "cpu", "get", "loadpercentage", "/value"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1.8,
            )
            for line in result.stdout.splitlines():
                if line.startswith("LoadPercentage="):
                    return f"{line.split('=', 1)[1]}%"
        except Exception:
            pass
        return "확인 불가"

    def gpu_snapshot(self) -> tuple[str, str]:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1.8,
            )
            first = result.stdout.splitlines()[0]
            util, used, total = [part.strip() for part in first.split(",")]
            return f"{util}%", f"{used}/{total} MB"
        except Exception:
            return "NVIDIA 아님/불가", "-"

    def net_snapshot(self) -> str:
        try:
            result = subprocess.run(
                ["netstat", "-e"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1.8,
            )
            numbers = [int(token) for token in result.stdout.replace(",", "").split() if token.isdigit()]
            if len(numbers) >= 2:
                now = time.time()
                current = (numbers[0], numbers[1], now)
                if self.last_net:
                    dt = max(now - self.last_net[2], 0.1)
                    down = (current[0] - self.last_net[0]) / dt / 1024
                    up = (current[1] - self.last_net[1]) / dt / 1024
                    self.last_net = current
                    return f"↓ {down:.1f} KB/s  ↑ {up:.1f} KB/s"
                self.last_net = current
        except Exception:
            pass
        return "측정 중"


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return SystemMonitor(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("home.system_monitor", "시스템 모니터", "홈", build, 10))
