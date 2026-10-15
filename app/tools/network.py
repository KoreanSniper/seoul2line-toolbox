from __future__ import annotations

import re
import os
import socket
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette

@dataclass(frozen=True)
class NetworkSnapshot:
    host: str
    ip: str
    latency: str
    latency_ms: int | None
    packet_loss: str
    bytes_in: str
    bytes_out: str
    adapters: tuple[tuple[str, str], ...]
    raw: str
    captured_at: str


class NetworkView(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.auto_enabled = False
        self.refreshing = False
        self._destroyed = False
        self._job: str | None = None
        self.history: list[int | None] = []
        self.cards: dict[str, tk.Label] = {}
        self.card_notes: dict[str, tk.Label] = {}
        self.adapter_list: tk.Frame | None = None
        self.history_canvas: tk.Canvas | None = None
        self.output: tk.Text | None = None
        self.refresh_button: RoundedButton | None = None
        self.auto_button: RoundedButton | None = None
        self.status_dot: tk.Canvas | None = None
        self.status_text: tk.Label | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.columnconfigure(0, weight=1)

        title_box = tk.Frame(header, bg=colors["panel"])
        title_box.grid(row=0, column=0, sticky="w")
        tk.Label(title_box, text="네트워크", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(
            title_box,
            text="연결 상태, 지연시간, 어댑터 정보를 가볍게 확인합니다.",
            font=("Segoe UI", 10),
            fg=colors["muted"],
            bg=colors["panel"],
        ).pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(header, bg=colors["panel"])
        actions.grid(row=0, column=1, sticky="e")
        self.refresh_button = RoundedButton(actions, "새로고침", self.refresh, colors, accent=True, compact=True, radius=10)
        self.refresh_button.pack(side="left", padx=(0, 8), fill="x")
        self.auto_button = RoundedButton(actions, "자동 꺼짐", self.toggle_auto, colors, compact=True, radius=10)
        self.auto_button.pack(side="left", fill="x")

        content = tk.Frame(self, bg=colors["panel"])
        content.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=4)
        content.rowconfigure(2, weight=1)

        cards = tk.Frame(content, bg=colors["panel"])
        cards.grid(row=0, column=0, columnspan=2, sticky="ew")
        for index in range(4):
            cards.columnconfigure(index, weight=1, uniform="metric")
        self._metric_card(cards, 0, "연결", "확인 중", "1.1.1.1 ping")
        self._metric_card(cards, 1, "로컬 IP", "-", "호스트 주소")
        self._metric_card(cards, 2, "지연시간", "-", "최근 응답")
        self._metric_card(cards, 3, "트래픽", "-", "수신 / 송신")

        history_panel = RoundedFrame(content, colors, colors["surface"], colors["border"], radius=16, padding=14)
        history_panel.grid(row=1, column=0, sticky="nsew", pady=(14, 0), padx=(0, 7))
        tk.Label(history_panel.body, text="최근 Ping 흐름", font=("Segoe UI", 12, "bold"), fg=colors["text"], bg=colors["surface"]).pack(anchor="w")
        self.history_canvas = tk.Canvas(history_panel.body, height=116, bg=colors["surface"], highlightthickness=0, bd=0)
        self.history_canvas.pack(fill="x", pady=(12, 0))

        adapters_panel = RoundedFrame(content, colors, colors["surface"], colors["border"], radius=16, padding=14)
        adapters_panel.grid(row=1, column=1, sticky="nsew", pady=(14, 0), padx=(7, 0))
        tk.Label(adapters_panel.body, text="활성 어댑터", font=("Segoe UI", 12, "bold"), fg=colors["text"], bg=colors["surface"]).pack(anchor="w")
        self.adapter_list = tk.Frame(adapters_panel.body, bg=colors["surface"])
        self.adapter_list.pack(fill="both", expand=True, pady=(10, 0))

        log_panel = RoundedFrame(content, colors, colors["surface"], colors["border"], radius=16, padding=14)
        log_panel.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        top = tk.Frame(log_panel.body, bg=colors["surface"])
        top.pack(fill="x")
        tk.Label(top, text="진단 로그", font=("Segoe UI", 12, "bold"), fg=colors["text"], bg=colors["surface"]).pack(side="left")
        for text, command in (
            ("DNS", lambda: self.run_diagnostic("DNS 확인", ["nslookup", "github.com"], 8)),
            ("경로", lambda: self.run_diagnostic("짧은 경로 추적", ["tracert", "-d", "-h", "6", "1.1.1.1"], 16)),
            ("로그 복사", self.copy_log),
        ):
            RoundedButton(top, text, command, colors, compact=True, radius=9, anchor="center", height=30).pack(side="left", padx=(8, 0))
        self.status_dot = tk.Canvas(top, width=12, height=12, bg=colors["surface"], highlightthickness=0, bd=0)
        self.status_dot.pack(side="right", padx=(8, 0))
        self.status_text = tk.Label(top, text="대기", font=("Segoe UI", 9), fg=colors["muted"], bg=colors["surface"])
        self.status_text.pack(side="right")

        text_wrap = tk.Frame(log_panel.body, bg=colors["surface"])
        text_wrap.pack(fill="both", expand=True, pady=(10, 0))
        self.output = tk.Text(
            text_wrap,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["text"],
            wrap="none",
            height=10,
            bd=0,
            padx=12,
            pady=12,
            font=("Consolas", 9),
        )
        self.output.pack(side="left", fill="both", expand=True)
        scroll = styled_scrollbar(text_wrap, "vertical", self.output.yview, colors)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)

    def _metric_card(self, parent: tk.Widget, column: int, title: str, value: str, note: str) -> None:
        colors = palette(self.app.dark_mode)
        panel = RoundedFrame(parent, colors, colors["surface"], colors["border"], radius=16, padding=14)
        panel.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 7, 0 if column == 3 else 7))
        tk.Label(panel.body, text=title, font=("Segoe UI", 9, "bold"), fg=colors["muted"], bg=colors["surface"]).pack(anchor="w")
        value_label = tk.Label(panel.body, text=value, font=("Segoe UI", 17, "bold"), fg=colors["text"], bg=colors["surface"], anchor="w")
        value_label.pack(anchor="w", fill="x", pady=(6, 2))
        note_label = tk.Label(panel.body, text=note, font=("Segoe UI", 9), fg=colors["subtle"], bg=colors["surface"], anchor="w")
        note_label.pack(anchor="w", fill="x")
        self.cards[title] = value_label
        self.card_notes[title] = note_label

    def refresh(self) -> None:
        if self._destroyed:
            return
        if self.refreshing:
            return
        self.refreshing = True
        self._set_status("확인 중", palette(self.app.dark_mode)["accent"])
        if self.refresh_button:
            self.refresh_button.text = "확인 중..."
            self.refresh_button._draw()
        threading.Thread(target=self._collect_snapshot, daemon=True).start()

    def _collect_snapshot(self) -> None:
        host = socket.gethostname()
        ip = local_ip(host)
        ping = _run(["ping", "-n", "1", "1.1.1.1"], timeout=5)
        ipconfig = _run(["ipconfig"], timeout=8)
        netstat = _run(["netstat", "-e"], timeout=8)
        latency, latency_ms = parse_latency(ping)
        packet_loss = parse_packet_loss(ping)
        bytes_in, bytes_out = parse_netstat_bytes(netstat)
        snapshot = NetworkSnapshot(
            host=host,
            ip=ip,
            latency=latency,
            latency_ms=latency_ms,
            packet_loss=packet_loss,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
            adapters=parse_adapters(ipconfig),
            raw=f"PING 1.1.1.1\n{ping}\n\n네트워크 바이트\n{netstat}\n\nIP 설정\n{ipconfig}",
            captured_at=time.strftime("%H:%M:%S"),
        )
        if self._destroyed:
            return
        try:
            self.after(0, lambda: self._apply_snapshot(snapshot))
        except tk.TclError:
            return

    def _apply_snapshot(self, snapshot: NetworkSnapshot) -> None:
        if self._destroyed or not self.winfo_exists():
            return
        colors = palette(self.app.dark_mode)
        online = snapshot.latency_ms is not None
        self.history.append(snapshot.latency_ms)
        self.history = self.history[-18:]

        self.cards["연결"].configure(text="온라인" if online else "오프라인", fg=colors["accent"] if online else colors["danger"])
        self.card_notes["연결"].configure(text=f"{snapshot.captured_at} 갱신")
        self.cards["로컬 IP"].configure(text=snapshot.ip)
        self.card_notes["로컬 IP"].configure(text=snapshot.host)
        self.cards["지연시간"].configure(text=snapshot.latency, fg=latency_color(snapshot.latency_ms, colors))
        self.card_notes["지연시간"].configure(text=f"{latency_note(snapshot.latency_ms)} | 손실 {snapshot.packet_loss}")
        self.cards["트래픽"].configure(text=f"{snapshot.bytes_in} / {snapshot.bytes_out}")
        self.card_notes["트래픽"].configure(text="수신 / 송신 bytes")

        self._draw_history()
        self._draw_adapters(snapshot.adapters)
        if self.output:
            self.output.delete("1.0", "end")
            self.output.insert("1.0", snapshot.raw)
        self._set_status("정상" if online else "응답 없음", colors["accent"] if online else colors["danger"])
        if self.refresh_button:
            self.refresh_button.text = "새로고침"
            self.refresh_button._draw()
        self.refreshing = False
        if self.auto_enabled:
            self._job = self.after(10000, self.refresh)

    def _draw_history(self) -> None:
        if self.history_canvas is None:
            return
        colors = palette(self.app.dark_mode)
        canvas = self.history_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 100)
        canvas.create_line(0, height - 24, width, height - 24, fill=colors["border"])
        if not self.history:
            canvas.create_text(12, height // 2, text="아직 기록 없음", anchor="w", fill=colors["muted"], font=("Segoe UI", 10))
            return
        gap = 8
        count = len(self.history)
        bar_width = max(10, (width - gap * (count + 1)) // count)
        max_ms = max([value or 0 for value in self.history] + [100])
        for index, value in enumerate(self.history):
            x1 = gap + index * (bar_width + gap)
            x2 = x1 + bar_width
            if value is None:
                y1 = height - 42
                fill = colors["danger"]
                label = "off"
            else:
                bar_height = int((height - 42) * min(value / max_ms, 1))
                y1 = height - 24 - max(bar_height, 8)
                fill = latency_color(value, colors)
                label = f"{value}"
            canvas.create_rectangle(x1, y1, x2, height - 24, fill=fill, outline="")
            canvas.create_text((x1 + x2) // 2, height - 10, text=label, fill=colors["subtle"], font=("Segoe UI", 8))

    def _draw_adapters(self, adapters: tuple[tuple[str, str], ...]) -> None:
        if self.adapter_list is None:
            return
        colors = palette(self.app.dark_mode)
        for child in self.adapter_list.winfo_children():
            child.destroy()
        if not adapters:
            tk.Label(self.adapter_list, text="활성 IPv4 어댑터를 찾지 못했습니다.", fg=colors["muted"], bg=colors["surface"]).pack(anchor="w")
            return
        for name, ip in adapters[:6]:
            row = tk.Frame(self.adapter_list, bg=colors["surface"])
            row.pack(fill="x", pady=4)
            tk.Label(row, text=name, fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text=ip, fg=colors["accent"], bg=colors["surface"], font=("Consolas", 9), anchor="e").pack(side="right")

    def _set_status(self, text: str, color: str) -> None:
        if self.status_text:
            self.status_text.configure(text=text)
        if self.status_dot:
            self.status_dot.delete("all")
            self.status_dot.create_oval(2, 2, 10, 10, fill=color, outline="")

    def toggle_auto(self) -> None:
        if self._destroyed:
            return
        self.auto_enabled = not self.auto_enabled
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        if self.auto_button:
            self.auto_button.text = "자동 켜짐" if self.auto_enabled else "자동 꺼짐"
            self.auto_button.set_active(self.auto_enabled)
        if self.auto_enabled:
            self._job = self.after(10000, self.refresh)

    def run_diagnostic(self, title: str, command: list[str], timeout: int) -> None:
        self._set_status(f"{title} 중", palette(self.app.dark_mode)["accent"])

        def worker() -> None:
            result = _run(command, timeout=timeout)
            if self._destroyed:
                return
            try:
                self.after(0, lambda: self.write_log(f"{title}\n$ {' '.join(command)}\n\n{result}"))
            except tk.TclError:
                return

        threading.Thread(target=worker, daemon=True).start()

    def write_log(self, text: str) -> None:
        if self._destroyed:
            return
        if self.output:
            self.output.delete("1.0", "end")
            self.output.insert("1.0", text or "완료했습니다.")
        self._set_status("진단 완료", palette(self.app.dark_mode)["accent"])

    def copy_log(self) -> None:
        if not self.output:
            return
        text = self.output.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("로그 복사 완료", palette(self.app.dark_mode)["accent"])

    def destroy(self) -> None:
        self._destroyed = True
        self.auto_enabled = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        super().destroy()


def _run(command: list[str], timeout: int = 8) -> str:
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        run_command = command
        if os.name == "nt":
            # Windows 기본 코드 페이지가 CP949여도 명령 출력은 UTF-8로 고정한다.
            run_command = ["cmd.exe", "/d", "/c", f"chcp 65001>nul & {subprocess.list2cmdline(command)}"]
        result = subprocess.run(
            run_command,
            capture_output=True,
            timeout=timeout,
            creationflags=flags,
        )
        return _decode_command_output(result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)


def _decode_command_output(raw: bytes) -> str:
    """Windows 명령의 UTF-8/CP949 출력을 환경에 맞게 복원한다."""
    if not raw:
        return ""
    for encoding in ("utf-8-sig", "cp949", "mbcs"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def local_ip(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return "확인 불가"


def parse_latency(output: str) -> tuple[str, int | None]:
    patterns = (
        r"(?:Average|평균)\s*=\s*(\d+)\s*ms",
        r"time[=<]\s*(\d+)\s*ms",
        r"시간[=<]\s*(\d+)\s*ms",
    )
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            ms = int(match.group(1))
            return f"{ms} ms", ms
    return "오프라인", None


def parse_packet_loss(output: str) -> str:
    patterns = (
        r"\((\d+)%\s*loss\)",
        r"(\d+)%\s*(?:loss|손실)",
        r"손실\s*=\s*\d+\s*\((\d+)%\s*손실\)",
    )
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return f"{match.group(1)}%"
    return "-"


def parse_netstat_bytes(output: str) -> tuple[str, str]:
    match = re.search(r"(?:Bytes|바이트)\s+([\d,]+)\s+([\d,]+)", output, re.IGNORECASE)
    if not match:
        return "-", "-"
    return compact_number(match.group(1)), compact_number(match.group(2))


def parse_adapters(output: str) -> tuple[tuple[str, str], ...]:
    adapters: list[tuple[str, str]] = []
    current = "네트워크 어댑터"
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":") and not line.startswith(("IPv4", "Subnet", "Default", "기본", "서브넷")):
            current = line[:-1].replace("adapter ", "").replace("어댑터", "").strip() or current
            continue
        if "IPv4" in line:
            ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if ip_match and not ip_match.group(1).startswith("169.254"):
                adapters.append((current, ip_match.group(1)))
    return tuple(adapters)


def compact_number(value: str) -> str:
    try:
        number = int(value.replace(",", ""))
    except ValueError:
        return value
    units = ("", "K", "M", "G", "T")
    unit = 0
    amount = float(number)
    while amount >= 1000 and unit < len(units) - 1:
        amount /= 1000
        unit += 1
    return f"{amount:.1f}{units[unit]}" if unit else str(number)


def latency_color(value: int | None, colors: dict[str, str]) -> str:
    if value is None:
        return colors["danger"]
    if value <= 60:
        return colors["accent"]
    if value <= 140:
        return "#f59e0b"
    return colors["danger"]


def latency_note(value: int | None) -> str:
    if value is None:
        return "ping 응답 실패"
    if value <= 60:
        return "쾌적"
    if value <= 140:
        return "보통"
    return "불안정"


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return NetworkView(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("network.status", "네트워크 상태", "네트워크", build, 0))
