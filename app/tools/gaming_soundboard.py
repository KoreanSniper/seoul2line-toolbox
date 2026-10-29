from concurrent.futures import ThreadPoolExecutor
from functools import partial
import queue
import math
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

from app.palette import palette
from app.services.soundboard_audio import SoundboardAudio
from app.services.soundboard_store import SoundboardStore
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar


class SoundboardTool(tk.Frame):
    def __init__(self, parent, app, store=None, audio=None):
        self.colors = palette(app.dark_mode)
        super().__init__(parent, bg=self.colors["panel"])
        self.audio = audio or SoundboardAudio()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="soundboard-files")
        self.results = queue.Queue()
        self.files_cancel = threading.Event()
        self.editing = False
        self.closed = False
        self.busy = False
        self.devices = []
        self.device_refresh_ticks = 0
        self.items = []
        self.buttons = {}
        self.entries = {}
        self.tiles = []
        self.columns = 0
        self.delay = tk.StringVar(value="0")
        self.pending = None
        self.play_timer = None
        self.play_deadline = 0
        self.status = tk.StringVar(value="개인설정에서 사운드와 출력 장치를 추가하세요.")
        try:
            self.store = store or SoundboardStore()
            self.master_volume, self.outputs = self.store.settings()
            self.items = self.store.items()
        except Exception as exc:
            self.store = None
            self.master_volume, self.outputs = 100, []
            self.status.set(f"사운드보드 DB를 열 수 없습니다: {exc}")
        self.audio.volumes(self.master_volume, self.outputs)
        self._build()
        self.render()
        self.refresh_devices()
        self.timer = self.after(50, self.poll)

    def label(self, parent, text=None, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.colors["text"], font=("Malgun Gothic", 10), **kwargs)

    def button(self, parent, text, command, **kwargs):
        return RoundedButton(parent, text, command, self.colors, compact=True, anchor="center", **kwargs)

    def scale(self, parent, value, command):
        scale = tk.Scale(parent, from_=0, to=100, orient="horizontal",
                         bg=parent.cget("bg"), fg=self.colors["text"], troughcolor=self.colors["field"],
                         activebackground=self.colors["accent"], highlightthickness=0, bd=0)
        scale.set(value)
        scale.configure(command=command)
        return scale

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        header = tk.Frame(self, bg=self.cget("bg"))
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        header.columnconfigure(0, weight=1)
        self.label(header, "사운드보드").grid(row=0, column=0, sticky="w")
        self.edit_button = self.button(header, "개인설정", self.toggle_edit)
        self.edit_button.configure(width=110)
        self.edit_button.grid(row=0, column=1)
        self.button(header, "전체 정지", self.stop).grid(row=0, column=2, padx=(8, 0))
        self.label(header, "전체 볼륨 (%)").grid(row=1, column=0, sticky="w")
        self.volume_scale = self.scale(header, self.master_volume, self.change_master)
        self.volume_scale.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.output_summary = self.label(header, "")
        self.output_summary.grid(row=3, column=0, columnspan=3, sticky="ew")
        delay_row = tk.Frame(header, bg=self.cget("bg"))
        delay_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.label(delay_row, "재생 대기 (초)").pack(side="left")
        tk.Spinbox(delay_row, from_=0, to=3600, increment=.5, textvariable=self.delay, width=8,
                   bg=self.colors["field"], fg=self.colors["text"], insertbackground=self.colors["text"]).pack(side="left", padx=8)
        self.label(delay_row, "0 = 즉시 · 최대 3,600초").pack(side="left")

        self.settings_panel = tk.Frame(self, bg=self.cget("bg"))
        self.settings_panel.grid(row=1, column=0, sticky="ew", padx=18)
        self.settings_panel.columnconfigure(1, weight=1)
        self.selectors, self.device_scales = [], []
        for i in range(2):
            self.label(self.settings_panel, f"출력 {i+1}").grid(row=i, column=0, padx=(0, 8))
            selector = ttk.Combobox(self.settings_panel, state="disabled", width=24)
            selector.grid(row=i, column=1, sticky="ew")
            selector.bind("<<ComboboxSelected>>", lambda e: self.select_outputs())
            self.selectors.append(selector)
            initial_volume = self.outputs[i]["volume"] if i < len(self.outputs) else 100
            slider = self.scale(self.settings_panel, initial_volume, lambda value, slot=i: self.change_device(slot, value))
            slider.configure(length=115)
            slider.grid(row=i, column=2, padx=(8, 0))
            self.device_scales.append(slider)
        actions = self.edit_actions = tk.Frame(self.settings_panel, bg=self.cget("bg"))
        for title, command, width in (("장치 새로고침", self.refresh_devices, 130),
                                      ("사운드 추가", self.add, 110),
                                      ("목소리 변조 복사", self.open_voice_fx, 150)):
            button = self.button(actions, title, command)
            button.configure(width=width)
            button.pack(side="left", padx=(0, 6))
        self.label(self, textvariable=self.status, wraplength=600, justify="left").grid(row=2, column=0, sticky="ew", padx=18, pady=8)

        wrap = tk.Frame(self, bg=self.cget("bg"))
        wrap.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, bg=self.cget("bg"), highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = styled_scrollbar(wrap, "vertical", self.canvas.yview, self.colors)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.grid_body = tk.Frame(self.canvas, bg=self.cget("bg"))
        self.window = self.canvas.create_window(0, 0, window=self.grid_body, anchor="nw")
        self.grid_body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.layout)
        self.canvas.bind("<MouseWheel>", self.wheel)

    def wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def layout(self, event=None):
        width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self.window, width=max(1, width))
        count = max(1, width // 180)
        if count == self.columns:
            return
        self.columns = count
        for i, tile in enumerate(self.tiles):
            tile.grid(row=i // count, column=i % count, padx=6, pady=6, sticky="nw")

    def render(self):
        for child in self.grid_body.winfo_children():
            child.destroy()
        self.tiles, self.buttons, self.entries = [], {}, {}
        for index, item in enumerate(self.items):
            identity = item["id"]
            tile = tk.Frame(self.grid_body, bg=self.cget("bg"), width=168, height=220 if self.editing else 160)
            tile.grid_propagate(False)
            tile.columnconfigure(0, weight=1)
            panel = RoundedFrame(tile, self.colors, self.colors["surface"], self.colors["border"], radius=14, padding=8)
            panel.grid(row=0, column=0, sticky="ew")
            button = self.button(panel.body, "파일 선택" if self.editing else "▶ 재생", lambda key=identity: self.click(key), height=82)
            button.pack(fill="x")
            self.buttons[identity] = button
            if self.editing:
                entry = tk.Entry(tile, bg=self.colors["field"], fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat", width=18)
                entry.insert(0, item["title"])
                entry.grid(row=1, column=0, sticky="ew", pady=6)
                entry.bind("<FocusOut>", lambda e, key=identity: self.save_title(key))
                entry.bind("<Return>", lambda e, key=identity: self.save_title(key))
                self.entries[identity] = entry
                row = tk.Frame(tile, bg=self.cget("bg"))
                row.grid(row=2, column=0, sticky="ew")
                for title, command in (("←", lambda n=index: self.move(n, -1)), ("→", lambda n=index: self.move(n, 1)), ("삭제", lambda key=identity: self.delete(key))):
                    b = self.button(row, title, command)
                    b.configure(width=48)
                    b.pack(side="left", padx=2)
                handle = self.label(tile, "⠿ 드래그로 순서 변경", cursor="fleur")
                handle.grid(row=3, column=0, pady=5)
                handle.bind("<ButtonPress-1>", lambda e, key=identity: setattr(self, "drag_id", key))
                handle.bind("<ButtonRelease-1>", self.drop)
            else:
                self.label(tile, item["title"], wraplength=155).grid(row=1, column=0, sticky="ew", pady=6)
            tile.sound_id = identity
            for widget in (tile, panel, panel.body, button):
                widget.bind("<MouseWheel>", self.wheel)
            self.tiles.append(tile)
        self.columns = 0
        self.layout()
        self.sync_state()

    def sync_state(self):
        for identity, button in self.buttons.items():
            button.set_active(identity in (self.audio.current, self.pending) and not self.editing)
        current_names = {d["id"]: d["name"] for d in self.devices}
        names = [f"{current_names.get(o['id'], o['name'])} ({o['volume']:g}%)" for o in self.outputs]
        self.output_summary.configure(text="출력: " + (" · ".join(names) or "개인설정에서 장치를 선택하세요"), wraplength=max(180, self.winfo_width()-40))

    def action(self, command):
        if self.store is None or self.busy:
            return False
        try:
            command()
            return True
        except Exception as exc:
            self.status.set(f"저장 실패: {exc}")
            return False

    def save_title(self, identity):
        entry = self.entries.get(identity)
        if not entry or not self.store:
            return True
        value = entry.get()
        old = next(i for i in self.items if i["id"] == identity)
        if value == old["title"]:
            return True
        if self.action(lambda: self.store.rename(identity, value)):
            old["title"] = value.strip()
            return True
        return False

    def save_titles(self):
        return all(self.save_title(key) for key in list(self.entries))

    def toggle_edit(self):
        if self.busy or not self.save_titles():
            return
        self.stop()
        self.editing = not self.editing
        self.edit_button.set_active(self.editing)
        for selector in self.selectors:
            selector.configure(state="readonly" if self.editing else "disabled")
        if self.editing:
            self.edit_actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        else:
            self.edit_actions.grid_remove()
        self.status.set("버튼으로 파일 선택 · 제목은 Enter/포커스 이동 시 저장 · 화살표/드래그로 순서 변경" if self.editing else "버튼을 다시 누르면 정지합니다.")
        self.render()

    def add(self):
        if self.editing and self.save_titles() and self.action(self.store.add if self.store else lambda: None):
            self.reload()

    def delete(self, identity):
        if self.editing and self.save_titles() and self.action(lambda: self.store.delete(identity)):
            self.reload()

    def reload(self):
        try:
            self.items = self.store.items()
            self.render()
        except Exception as exc:
            self.status.set(str(exc))

    def move(self, index, offset):
        target = index + offset
        if self.editing and not self.busy and 0 <= target < len(self.items) and self.save_titles():
            ids = [i["id"] for i in self.items]
            ids.insert(target, ids.pop(index))
            if self.action(lambda: self.store.reorder(ids)):
                self.reload()

    def drop(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget and not hasattr(widget, "sound_id"):
            widget = getattr(widget, "master", None)
        if widget and getattr(self, "drag_id", None):
            ids = [i["id"] for i in self.items]
            self.move(ids.index(self.drag_id), ids.index(widget.sound_id)-ids.index(self.drag_id))
        self.drag_id = None

    def click(self, identity):
        if not self.store or self.busy:
            return
        item = next(i for i in self.items if i["id"] == identity)
        if self.editing:
            if not self.save_titles():
                return
            source = filedialog.askopenfilename(parent=self, title="사운드 파일 선택", filetypes=[("오디오", "*.mp3 *.wav *.ogg")])
            if source:
                self.busy = True
                self.status.set("파일 복사 및 오디오 검증 중…")
                validate = partial(self.audio.driver.validate, cancel=self.files_cancel)
                self.submit("registered", partial(self.store.register_file, identity, source, validate, self.files_cancel))
            return
        try:
            if self.pending == identity or self.audio.current == identity:
                self.stop()
                return
            try:
                seconds = float(self.delay.get())
            except ValueError:
                raise ValueError("재생 대기는 0~3,600초로 입력하세요.") from None
            if not math.isfinite(seconds) or not 0 <= seconds <= 3600:
                raise ValueError("재생 대기는 0~3,600초로 입력하세요.")
            if not item["path"]:
                raise ValueError("개인설정에서 이 버튼의 오디오 파일을 선택하세요.")
            if not self.outputs:
                raise ValueError("개인설정에서 출력 장치를 1~2개 선택하세요.")
            path = self.store.resolve(item["path"])
            if not path.is_file():
                raise ValueError("오디오 파일이 없습니다. 개인설정에서 다시 선택하세요.")
            self.stop()
            if seconds:
                self.pending = identity
                self.play_deadline = time.monotonic() + seconds
                self.play_timer = self.after(max(1, math.ceil(seconds * 1000)), lambda: self.play_pending(identity))
                self.status.set(f"{seconds:g}초 후 재생: {item['title']} (다시 누르면 취소)")
            else:
                self.play_item(identity)
        except Exception as exc:
            self.status.set(str(exc))
        self.sync_state()

    def stop(self):
        if self.play_timer is not None:
            self.after_cancel(self.play_timer)
            self.play_timer = None
        self.pending = None
        self.audio.stop()
        self.status.set("정지")
        self.sync_state()

    def play_pending(self, identity):
        self.play_timer = None
        if self.closed or self.pending != identity:
            return
        self.pending = None
        self.play_item(identity)

    def play_item(self, identity):
        try:
            item = next(i for i in self.items if i["id"] == identity)
            path = self.store.resolve(item["path"])
            if not path.is_file():
                raise ValueError("오디오 파일이 없습니다. 개인설정에서 다시 선택하세요.")
            self.audio.toggle(identity, path, [dict(o) for o in self.outputs])
            self.status.set("재생 요청: " + item["title"])
        except Exception as exc:
            self.status.set("재생 실패: " + str(exc))
        self.sync_state()

    def submit(self, kind, command):
        results = self.results
        def run():
            try:
                results.put((kind, command(), None))
            except Exception as exc:
                from app.services.voice_fx_log import log_failure
                log_failure()
                results.put((kind, None, str(exc)))
        self.executor.submit(run)

    def open_voice_fx(self):
        if self.closed or self.busy or not self.store:
            return
        from app.tools.voice_fx_soundboard import SoundboardFXDialog
        current = getattr(self, "fx_dialog", None)
        if current and current.winfo_exists():
            current.lift()
            return
        self.stop()
        self.fx_cancel = threading.Event()
        self.fx_dialog = SoundboardFXDialog(self, self.colors, self.items, self.apply_voice_fx, self.fx_cancel.set)

    def apply_voice_fx(self, identities, settings):
        if self.closed or self.busy:
            return
        if not identities:
            self.fx_dialog.status.set("변조할 사운드를 하나 이상 선택하세요.")
            return
        from app.services.voice_fx_soundboard import copy_with_fx
        self.fx_cancel.clear()
        self.busy = True
        self.status.set("사운드보드 변조 복사 중… 원본은 유지됩니다.")
        self.fx_dialog.status.set("변조 복사 중… 닫으면 작업을 취소합니다.")
        store, cancel, results = self.store, self.fx_cancel, self.results
        self.submit("fx_copied", lambda: copy_with_fx(store, identities, settings, cancel,
                                                    lambda message: results.put(("fx_progress", message, None))))

    def refresh_devices(self):
        if not getattr(self, "discovering", False):
            self.discovering = True
            self.submit("devices", self.audio.driver.devices)

    def update_selectors(self):
        choices = ["선택 안 함"] + [f"{i+1}. {d['name']}" for i, d in enumerate(self.devices)]
        for slot, selector in enumerate(self.selectors):
            selector.configure(values=choices)
            output = self.outputs[slot] if slot < len(self.outputs) else None
            index = next((i+1 for i, d in enumerate(self.devices) if output and d["id"] == output["id"]), 0)
            selector.current(index)
            if output and not index:
                selector.set("연결 끊김: " + output["name"])
            self.device_scales[slot].set(output["volume"] if output else 100)
        missing = [o["name"] for o in self.outputs if not any(d["id"] == o["id"] for d in self.devices)]
        if missing:
            self.status.set("연결되지 않은 장치: " + ", ".join(missing) + ". 개인설정에서 다시 선택하세요.")

    def select_outputs(self):
        if not self.editing:
            return
        outputs = []
        for slot, selector in enumerate(self.selectors):
            index = selector.current()
            if index > 0:
                device = self.devices[index-1]
                outputs.append({"id": device["id"], "name": device["name"], "volume": self.device_scales[slot].get()})
            elif index < 0 and slot < len(self.outputs):
                outputs.append(dict(self.outputs[slot]))
        if self.action(lambda: self.store.save_settings(self.master_volume, outputs)):
            self.stop()
            self.outputs = outputs
            self.audio.volumes(self.master_volume, self.outputs)
        self.update_selectors()
        self.sync_state()

    def change_master(self, value):
        volume = float(value)
        if volume == self.master_volume:
            return
        if self.action(lambda: self.store.save_volume(volume)):
            self.master_volume = volume
            self.audio.volumes(volume, self.outputs)

    def change_device(self, slot, value):
        if slot >= len(self.outputs) or float(value) == self.outputs[slot]["volume"]:
            return
        outputs = [dict(o) for o in self.outputs]
        outputs[slot]["volume"] = float(value)
        if self.action(lambda: self.store.save_settings(self.master_volume, outputs)):
            self.outputs = outputs
            self.audio.volumes(self.master_volume, outputs)
            self.sync_state()

    def poll(self):
        if self.pending is not None:
            item = next((i for i in self.items if i["id"] == self.pending), None)
            if item:
                self.status.set(f"{max(0, self.play_deadline-time.monotonic()):.1f}초 후 재생: {item['title']} (다시 누르면 취소)")
        self.device_refresh_ticks += 1
        if self.device_refresh_ticks >= 100:
            self.device_refresh_ticks = 0
            self.refresh_devices()
        while not self.results.empty():
            kind, result, error = self.results.get_nowait()
            if kind == "registered":
                self.busy = False
                self.status.set("등록 실패: " + error if error else "오디오 등록 완료")
                self.reload()
            elif kind == "devices":
                self.discovering = False
                if error:
                    self.status.set("출력 장치 감지 실패: " + error)
                else:
                    self.devices = result
                    self.update_selectors()
            elif kind == "fx_progress":
                self.status.set(result)
                if getattr(self, "fx_dialog", None) and self.fx_dialog.winfo_exists():
                    self.fx_dialog.status.set(result)
            elif kind == "fx_copied":
                self.busy = False
                self.status.set("변조 복사 실패: " + error if error else f"변조 복사 완료: {len(result)}개 · 기존 원본 유지")
                self.reload()
                if getattr(self, "fx_dialog", None) and self.fx_dialog.winfo_exists():
                    self.fx_dialog.status.set(self.status.get())
        while not self.audio.events.empty():
            generation, kind, message = self.audio.events.get_nowait()
            if generation == self.audio.generation and kind == "error":
                self.status.set("오디오 오류: " + message)
        self.sync_state()
        self.timer = self.after(50, self.poll)

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        self.stop()
        self.files_cancel.set()
        if hasattr(self, "fx_cancel"):
            self.fx_cancel.set()
        if getattr(self, "fx_dialog", None) and self.fx_dialog.winfo_exists():
            self.fx_dialog.destroy()
        self.save_titles()
        self.audio.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.after_cancel(self.timer)
        super().destroy()
        self.status = self.delay = None


def build(parent, app):
    return SoundboardTool(parent, app)


def register(registry):
    registry.register(ToolSpec("gaming.soundboard", "사운드보드", "게임", build, 15))
