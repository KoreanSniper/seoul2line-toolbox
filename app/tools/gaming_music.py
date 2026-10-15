from __future__ import annotations

import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette


MODES = ("목록 한 번", "목록 반복", "한 곡 반복")
SUPPORTED_AUDIO = (".mp3",)


class MusicBackend:
    def __init__(self) -> None:
        self.pygame = None
        self.ready = False
        self.playlist: list[str] = []
        self.index = -1
        self.volume = 0.55
        self.mode = "목록 반복"
        self.playing = False
        self.paused = False
        self.last_error = ""

    def configure(self, playlist: list[str], volume: float, mode: str) -> None:
        self.playlist = [path for path in playlist if Path(path).exists() and Path(path).suffix.lower() in SUPPORTED_AUDIO]
        self.volume = max(0.0, min(1.0, volume))
        self.mode = mode if mode in MODES else "목록 반복"
        if self.index >= len(self.playlist):
            self.index = 0 if self.playlist else -1

    def ensure_ready(self) -> bool:
        if self.ready:
            return True
        try:
            import pygame

            pygame.mixer.init()
            pygame.mixer.music.set_volume(self.volume)
        except Exception as exc:
            self.last_error = f"오디오 엔진을 시작할 수 없습니다: {exc}"
            return False
        self.pygame = pygame
        self.ready = True
        return True

    def play(self, index: int | None = None) -> bool:
        if not self.playlist:
            self.last_error = "재생할 MP3 파일을 먼저 추가하세요."
            return False
        if not self.ensure_ready():
            return False
        if index is not None:
            self.index = max(0, min(len(self.playlist) - 1, index))
        elif self.index < 0:
            self.index = 0
        try:
            assert self.pygame is not None
            self.pygame.mixer.music.load(self.playlist[self.index])
            self.pygame.mixer.music.set_volume(self.volume)
            self.pygame.mixer.music.play(loops=-1 if self.mode == "한 곡 반복" else 0)
        except Exception as exc:
            self.last_error = f"재생 실패: {exc}"
            self.playing = False
            self.paused = False
            return False
        self.playing = True
        self.paused = False
        self.last_error = ""
        return True

    def pause_or_resume(self) -> None:
        if not self.ready or not self.playing or self.pygame is None:
            return
        if self.paused:
            self.pygame.mixer.music.unpause()
            self.paused = False
        else:
            self.pygame.mixer.music.pause()
            self.paused = True

    def stop(self) -> None:
        if self.ready and self.pygame is not None:
            self.pygame.mixer.music.stop()
        self.playing = False
        self.paused = False

    def next(self) -> bool:
        if not self.playlist:
            return False
        next_index = self.index + 1
        if next_index >= len(self.playlist):
            next_index = 0
        return self.play(next_index)

    def previous(self) -> bool:
        if not self.playlist:
            return False
        prev_index = self.index - 1
        if prev_index < 0:
            prev_index = len(self.playlist) - 1
        return self.play(prev_index)

    def set_volume(self, value: float) -> None:
        self.volume = max(0.0, min(1.0, value))
        if self.ready and self.pygame is not None:
            self.pygame.mixer.music.set_volume(self.volume)

    def set_mode(self, mode: str) -> None:
        self.mode = mode if mode in MODES else "목록 반복"
        if self.playing and not self.paused:
            self.play(self.index)

    def current_name(self) -> str:
        if 0 <= self.index < len(self.playlist):
            return Path(self.playlist[self.index]).name
        return "선택된 곡 없음"

    def tick(self) -> bool:
        if not self.ready or not self.playing or self.paused or self.pygame is None:
            return False
        if self.pygame.mixer.music.get_busy():
            return True
        if self.mode == "목록 반복":
            return self.next()
        if self.mode == "목록 한 번" and self.index + 1 < len(self.playlist):
            return self.next()
        self.playing = False
        return False


_BACKEND = MusicBackend()


class BackgroundMusicTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        cfg = app.config_store.get("music", default={}) or {}
        _BACKEND.configure(cfg.get("playlist", []), float(cfg.get("volume", 0.55)), cfg.get("mode", "목록 반복"))
        self.status = tk.StringVar(value=self._status_text())
        self.mode = tk.StringVar(value=_BACKEND.mode)
        self.volume = tk.DoubleVar(value=_BACKEND.volume * 100)
        self._after_id: str | None = None
        self._volume_save_after: str | None = None
        self._build()
        self.refresh_list()
        self.schedule_tick()

    def _build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="배경음악", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="MP3 파일을 스트리밍 재생합니다. 재생 중이 아닐 때는 오디오 엔진을 건드리지 않습니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(3, 0))
        RoundedButton(header, "MP3 추가", self.add_files, colors, accent=True, compact=True, radius=10, anchor="center").grid(row=0, column=1, rowspan=2, sticky="e")

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        list_panel = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=18, padding=14)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        list_panel.body.columnconfigure(0, weight=1)
        list_panel.body.rowconfigure(1, weight=1)
        tk.Label(list_panel.body, text="재생 목록", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")

        list_wrap = tk.Frame(list_panel.body, bg=colors["surface"])
        list_wrap.grid(row=1, column=0, sticky="nsew", pady=(10, 10))
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_wrap,
            bg=colors["field"],
            fg=colors["text"],
            selectbackground=colors["accent_soft"],
            selectforeground=colors["accent"],
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
            activestyle="none",
            exportselection=False,
            font=("Segoe UI", 10),
        )
        scroll = styled_scrollbar(list_wrap, "vertical", self.listbox.yview, colors)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.bind("<Double-Button-1>", lambda _event: self.play_selected())

        list_actions = tk.Frame(list_panel.body, bg=colors["surface"])
        list_actions.grid(row=2, column=0, sticky="ew")
        for label, command, accent in (
            ("선택 재생", self.play_selected, True),
            ("선택 제거", self.remove_selected, False),
            ("목록 비우기", self.clear_playlist, False),
        ):
            RoundedButton(list_actions, label, command, colors, accent=accent, compact=True, radius=10, anchor="center", height=36).pack(side="left", fill="x", expand=True, padx=(0, 7))

        control_panel = RoundedFrame(body, colors, colors["panel_soft"], colors["border"], radius=18, padding=14)
        control_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        control_panel.body.columnconfigure(0, weight=1)
        tk.Label(control_panel.body, text="컨트롤", fg=colors["text"], bg=colors["panel_soft"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(control_panel.body, textvariable=self.status, fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9), wraplength=330, justify="left").grid(row=1, column=0, sticky="ew", pady=(6, 14))

        buttons = tk.Frame(control_panel.body, bg=colors["panel_soft"])
        buttons.grid(row=2, column=0, sticky="ew")
        for label, command in (("이전", self.previous), ("재생/일시정지", self.play_or_pause), ("다음", self.next)):
            RoundedButton(buttons, label, command, colors, compact=True, radius=10, anchor="center", height=38).pack(side="left", fill="x", expand=True, padx=(0, 6))
        RoundedButton(control_panel.body, "정지", self.stop, colors, compact=True, radius=10, anchor="center", height=38).grid(row=3, column=0, sticky="ew", pady=(8, 16))

        tk.Label(control_panel.body, text="재생 방식", fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9, "bold")).grid(row=4, column=0, sticky="w")
        mode_row = tk.Frame(control_panel.body, bg=colors["panel_soft"])
        mode_row.grid(row=5, column=0, sticky="ew", pady=(7, 16))
        self.mode_buttons: dict[str, RoundedButton] = {}
        for mode in MODES:
            button = RoundedButton(mode_row, mode, lambda value=mode: self.set_mode(value), colors, compact=True, radius=10, anchor="center", height=34)
            button.pack(fill="x", pady=(0, 7))
            self.mode_buttons[mode] = button
        self.sync_mode_buttons()

        tk.Label(control_panel.body, text="사운드", fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9, "bold")).grid(row=6, column=0, sticky="w")
        self.volume_scale = tk.Scale(
            control_panel.body,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.volume,
            command=self.change_volume,
            bg=colors["panel_soft"],
            fg=colors["text"],
            troughcolor=colors["field"],
            activebackground=colors["accent"],
            highlightthickness=0,
            bd=0,
            relief="flat",
            showvalue=True,
            font=("Segoe UI", 9),
        )
        self.volume_scale.grid(row=7, column=0, sticky="ew", pady=(6, 0))

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="MP3 파일 선택", filetypes=[("MP3 파일", "*.mp3")])
        if not paths:
            return
        existing = set(_BACKEND.playlist)
        for path in paths:
            if path not in existing:
                _BACKEND.playlist.append(path)
        if _BACKEND.index < 0 and _BACKEND.playlist:
            _BACKEND.index = 0
        self.persist()
        self.refresh_list()
        self.set_status(f"MP3 {len(paths)}개 추가")

    def selected_index(self) -> int | None:
        selection = self.listbox.curselection()
        if not selection or not _BACKEND.playlist:
            return None
        index = int(selection[0])
        return index if 0 <= index < len(_BACKEND.playlist) else None

    def play_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            index = _BACKEND.index if _BACKEND.index >= 0 else 0
        if not _BACKEND.play(index):
            messagebox.showerror("배경음악", _BACKEND.last_error)
        self.refresh_list()
        self.schedule_tick()

    def play_or_pause(self) -> None:
        if _BACKEND.playing:
            _BACKEND.pause_or_resume()
        else:
            self.play_selected()
            return
        self.refresh_list()
        self.schedule_tick()

    def next(self) -> None:
        if not _BACKEND.next():
            messagebox.showwarning("배경음악", "재생할 MP3 파일을 먼저 추가하세요.")
        self.refresh_list()
        self.schedule_tick()

    def previous(self) -> None:
        if not _BACKEND.previous():
            messagebox.showwarning("배경음악", "재생할 MP3 파일을 먼저 추가하세요.")
        self.refresh_list()
        self.schedule_tick()

    def stop(self) -> None:
        _BACKEND.stop()
        self.refresh_list()

    def remove_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        was_current = index == _BACKEND.index
        del _BACKEND.playlist[index]
        if not _BACKEND.playlist:
            _BACKEND.index = -1
            _BACKEND.stop()
        elif _BACKEND.index >= len(_BACKEND.playlist):
            _BACKEND.index = len(_BACKEND.playlist) - 1
        if was_current and _BACKEND.playing:
            _BACKEND.play(_BACKEND.index)
        self.persist()
        self.refresh_list()

    def clear_playlist(self) -> None:
        _BACKEND.stop()
        _BACKEND.playlist = []
        _BACKEND.index = -1
        self.persist()
        self.refresh_list()

    def set_mode(self, mode: str) -> None:
        self.mode.set(mode)
        _BACKEND.set_mode(mode)
        self.persist()
        self.sync_mode_buttons()
        self.refresh_list()
        self.schedule_tick()

    def sync_mode_buttons(self) -> None:
        for mode, button in self.mode_buttons.items():
            button.set_active(mode == self.mode.get())

    def change_volume(self, value: str) -> None:
        try:
            volume = float(value) / 100
        except ValueError:
            return
        _BACKEND.set_volume(volume)
        self.schedule_volume_save()
        self.status.set(self._status_text())

    def schedule_volume_save(self) -> None:
        if self._volume_save_after is not None:
            self.after_cancel(self._volume_save_after)
        self._volume_save_after = self.after(450, self.persist_volume)

    def persist_volume(self) -> None:
        self._volume_save_after = None
        self.persist()

    def refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        if not _BACKEND.playlist:
            self.listbox.insert("end", "MP3 파일을 추가하세요")
            self.listbox.itemconfigure(0, fg=self.colors["subtle"])
        else:
            for index, path in enumerate(_BACKEND.playlist):
                prefix = "재생 중  " if index == _BACKEND.index and _BACKEND.playing else "        "
                self.listbox.insert("end", prefix + os.path.basename(path))
            if 0 <= _BACKEND.index < len(_BACKEND.playlist):
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(_BACKEND.index)
                self.listbox.see(_BACKEND.index)
        self.status.set(self._status_text())

    def schedule_tick(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if _BACKEND.playing and not _BACKEND.paused:
            self._after_id = self.after(700, self.on_tick)

    def on_tick(self) -> None:
        self._after_id = None
        _BACKEND.tick()
        self.refresh_list()
        self.schedule_tick()

    def set_status(self, text: str) -> None:
        self.status.set(f"{text}\n{self._status_text()}")

    def _status_text(self) -> str:
        state = "일시정지" if _BACKEND.paused else ("재생 중" if _BACKEND.playing else "대기 중")
        return f"{state} | {_BACKEND.current_name()}\n방식: {_BACKEND.mode} | 볼륨: {int(_BACKEND.volume * 100)}% | 곡 수: {len(_BACKEND.playlist)}"

    def persist(self) -> None:
        self.app.config_store.set("music", value={"playlist": _BACKEND.playlist, "volume": _BACKEND.volume, "mode": _BACKEND.mode})

    def destroy(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._volume_save_after is not None:
            self.after_cancel(self._volume_save_after)
            self._volume_save_after = None
        super().destroy()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return BackgroundMusicTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("gaming.music", "배경음악", "게임", build, 10))
