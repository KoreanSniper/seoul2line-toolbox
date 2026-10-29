import queue
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, ttk

from app.palette import palette
from app.services.soundboard_audio import AudioDriver
from app.services.tts import WindowsTTS
from app.services.voice_fx import default_settings
from app.tools.voice_fx_editor import VoiceFXEditor
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, styled_scrollbar


class TTSTool(tk.Frame):
    def __init__(self, parent, app, engine=None):
        colors = palette(app.dark_mode)
        super().__init__(parent, bg=colors["panel"])
        self.engine = engine or WindowsTTS()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
        self.results = queue.Queue()
        self.closed = False
        self.busy = True
        self.voices = []
        self.devices = []
        self.discovering = False
        self.timer = None
        self.status = tk.StringVar(value="설치된 음성을 확인하는 중…")
        self.rate = tk.IntVar(value=0)
        self.volume = tk.IntVar(value=100)
        self.title = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        tk.Label(self, text="TTS · Voice FX", font=("Malgun Gothic", 20, "bold"), bg=colors["panel"], fg=colors["text"]).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 4))
        tk.Label(self, text="오프라인 음성 생성 · 원본 보존 · 효과 체인과 프리셋",
                 bg=colors["panel"], fg=colors["muted"]).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 6))
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=18)
        source_tab = tk.Frame(self.tabs, bg=colors["panel"])
        self.tabs.add(source_tab, text="텍스트 · 음성 · 출력")
        source_tab.columnconfigure(0, weight=1)
        source_tab.rowconfigure(0, weight=1)
        text_wrap = tk.Frame(source_tab, bg=colors["panel"])
        text_wrap.grid(row=0, column=0, sticky="nsew", pady=6)
        text_wrap.columnconfigure(0, weight=1)
        text_wrap.rowconfigure(0, weight=1)
        self.text = tk.Text(text_wrap, wrap="word", height=5, width=30, undo=True, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"], relief="flat")
        self.text.grid(row=0, column=0, sticky="nsew")
        text_bar = styled_scrollbar(text_wrap, "vertical", self.text.yview, colors)
        text_bar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=text_bar.set)
        self.count = tk.StringVar(value="0 / 10,000자")
        tk.Label(source_tab, textvariable=self.count, bg=colors["panel"], fg=colors["muted"]).grid(row=1, column=0, sticky="e")
        self.text.bind("<<Modified>>", self.update_count)
        controls = tk.Frame(source_tab, bg=colors["panel"])
        controls.grid(row=2, column=0, sticky="ew", pady=5)
        controls.columnconfigure(1, weight=1)
        for row, title in enumerate(("Windows 음성", "TTS 읽기 속도", "볼륨 (%)")):
            tk.Label(controls, text=title, bg=colors["panel"], fg=colors["text"]).grid(row=row, column=0, sticky="w", padx=(0, 10))
        self.voice = ttk.Combobox(controls, state="disabled", width=18)
        self.voice.grid(row=0, column=1, sticky="ew")
        refresh_voice = RoundedButton(controls, "음성 새로고침", self.refresh_voices, colors, compact=True)
        refresh_voice.configure(width=115)
        refresh_voice.grid(row=0, column=2, padx=(8, 0))
        for row, variable, low, high in ((1, self.rate, -10, 10), (2, self.volume, 0, 100)):
            tk.Scale(controls, variable=variable, from_=low, to=high, orient="horizontal", bg=colors["panel"], fg=colors["text"], highlightthickness=0).grid(row=row, column=1, columnspan=2, sticky="ew")
        tk.Label(controls, text="사운드 제목", bg=colors["panel"], fg=colors["text"]).grid(row=3, column=0, sticky="w")
        tk.Entry(controls, textvariable=self.title, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"]).grid(row=3, column=1, columnspan=2, sticky="ew", pady=5)
        tk.Label(controls, text="출력 / 미리듣기 장치", bg=colors["panel"], fg=colors["text"]).grid(row=4, column=0, sticky="w")
        self.output_device = ttk.Combobox(controls, state="disabled", width=18)
        self.output_device.grid(row=4, column=1, sticky="ew")
        refresh_button = RoundedButton(controls, "장치 새로고침", self.refresh_devices, colors, compact=True)
        refresh_button.configure(width=115)
        refresh_button.grid(row=4, column=2, padx=(8, 0))
        self.fx = VoiceFXEditor(self.tabs, colors, self.status)
        self.tabs.add(self.fx, text="목소리 변조 · 프리셋")
        actions = tk.Frame(self, bg=colors["panel"])
        actions.grid(row=3, column=0, sticky="ew", padx=18, pady=7)
        commands = [("WAV 저장", self.generate), ("사운드보드 추가", lambda: self.generate(True)),
                    ("일회용 출력", lambda: self.generate(play_once=True)),
                    ("원본 미리듣기", lambda: self.generate(preview="original")),
                    ("변조 미리듣기", lambda: self.generate(preview="modified")),
                    ("변조만 다시 생성", self.remix)]
        for index, (label, command) in enumerate(commands):
            actions.columnconfigure(index % 3, weight=1)
            button = RoundedButton(actions, label, command, colors, compact=True)
            button.configure(width=125)
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
            if index == 0:
                self.generate_button = button
        self.short_preview = tk.BooleanVar(value=True)
        tk.Checkbutton(actions, text="미리듣기: 앞 12초만 (끄면 전체)", variable=self.short_preview,
                       bg=colors["panel"], fg=colors["text"], selectcolor=colors["field"], activebackground=colors["panel"], activeforeground=colors["text"]).grid(row=2, column=0, columnspan=2, sticky="w")
        stop = RoundedButton(actions, "처리 취소 / 정지", self.cancel_work, colors, compact=True)
        stop.configure(width=125)
        stop.grid(row=2, column=2, sticky="ew", padx=2, pady=2)
        self.progress_bar = ttk.Progressbar(self, mode="indeterminate")
        self.progress_bar.grid(row=4, column=0, sticky="ew", padx=18)
        tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["muted"], wraplength=480, justify="left").grid(row=5, column=0, sticky="ew", padx=18, pady=(5, 10))
        results = self.results
        self.engine.progress = lambda message: results.put(("progress", message, None))
        self.submit("voices", self.engine.voices)
        self.refresh_devices()
        self.timer = self.after(50, self.poll)

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

    def refresh_devices(self):
        if self.closed or self.discovering:
            return
        self.discovering = True
        self.submit("devices", AudioDriver().devices)

    def update_count(self, _event=None):
        if self.text.edit_modified():
            self.count.set(f"{len(self.text.get('1.0', 'end-1c')):,} / 10,000자")
            self.text.edit_modified(False)

    def refresh_voices(self):
        if not self.closed and not self.busy:
            self.busy = True
            self.submit("voices", self.engine.voices)

    def cancel_work(self):
        if self.busy and hasattr(self.engine, "cancel"):
            self.engine.cancel.set()
            self.status.set("취소 요청 중… 현재 처리 단계가 끝나면 정리합니다.")

    def begin_work(self):
        if hasattr(self.engine, "reset_cancel"):
            self.engine.reset_cancel()
        self.busy = True
        self.progress_bar.start(15)
        self.fx.persist()

    def remix(self):
        if self.closed or self.busy:
            return
        settings = self.fx.snapshot()
        self.begin_work()
        engine = self.engine
        self.status.set("보존한 원본에 효과만 다시 적용 중…")
        self.submit("remixed", lambda: engine.render_cached(settings))

    def generate(self, add_to_soundboard=False, play_once=False, preview=None):
        if self.closed or self.busy:
            return
        text = self.text.get("1.0", "end-1c")
        if not text.strip() or len(text) > 10000:
            self.status.set("텍스트를 1~10,000자 입력하세요.")
            return
        if not self.voices:
            self.status.set("사용 가능한 Windows 음성이 없습니다. Windows 설정에서 음성을 설치한 뒤 도구를 다시 여세요.")
            return
        if play_once or preview:
            selected = self.output_device.current()
            if selected < 0 or selected >= len(self.devices):
                self.status.set("일회용 출력 장치에서 CABLE Input 등 사용할 장치를 선택하세요.")
                return
            output = dict(self.devices[selected])
        elif add_to_soundboard:
            title = self.title.get().strip() or text.strip().splitlines()[0][:100]
            if len(title) > 100:
                self.status.set("사운드 제목은 1~100자로 입력하세요.")
                return
        else:
            target = filedialog.asksaveasfilename(parent=self, title="TTS 음성 저장", defaultextension=".wav", filetypes=[("WAV 음성", "*.wav")])
            if not target:
                return
        if not 0 <= self.voice.current() < len(self.voices):
            self.status.set("Windows 음성을 선택하세요.")
            return
        voice = self.voices[self.voice.current()]["name"]
        rate, volume = self.rate.get(), self.volume.get()
        effect = default_settings() if preview == "original" else self.fx.snapshot()
        seconds = 12 if preview and self.short_preview.get() else None
        self.begin_work()
        engine = self.engine
        if preview:
            self.status.set(("원본" if preview == "original" else "변조") + " 미리듣기 중: " + output["name"])
            self.submit("previewed", lambda: engine.play_once(text, output, voice, rate, volume, effect, seconds))
        elif play_once:
            self.status.set("일회용 음성 생성·출력 중: " + output["name"] + " · 재생 후 자동 폐기")
            self.submit("played", lambda: engine.play_once(text, output, voice, rate, volume, effect))
        elif add_to_soundboard:
            self.status.set("음성 생성 및 사운드보드 등록 중…")
            self.submit("added", lambda: engine.add_to_soundboard(text, title, voice, rate, volume, effect))
        else:
            self.status.set("음성 생성 중… (화면을 떠나면 취소됩니다)")
            self.submit("generated", lambda: engine.generate(text, target, voice, rate, volume, effect))

    def poll(self):
        while not self.results.empty():
            kind, result, error = self.results.get_nowait()
            if kind == "progress":
                self.status.set(result)
                continue
            if kind == "devices":
                self.discovering = False
                if error:
                    self.status.set("출력 장치 조회 실패: " + error)
                else:
                    selected = self.output_device.current()
                    old_id = self.devices[selected]["id"] if 0 <= selected < len(self.devices) else None
                    self.devices = result
                    self.output_device.configure(values=[f"{i+1}. {d['name']}" for i, d in enumerate(result)], state="readonly" if result else "disabled")
                    self.output_device.set("")
                    found = next((i for i, d in enumerate(result) if d["id"] == old_id), None)
                    if found is not None:
                        self.output_device.current(found)
                    elif old_id:
                        self.status.set("선택한 출력 장치가 없습니다. 장치를 다시 선택하세요.")
                    if not result:
                        self.status.set("사용 가능한 출력 장치가 없습니다. 케이블 장치를 연결한 뒤 새로고침하세요.")
                continue
            self.busy = False
            self.progress_bar.stop()
            if error:
                self.status.set("음성 처리 실패: " + error)
            elif hasattr(self.engine, "cancel") and self.engine.cancel.is_set():
                self.status.set("음성 처리를 취소했습니다.")
            elif kind == "voices":
                old_voice = self.voices[self.voice.current()]["name"] if 0 <= self.voice.current() < len(self.voices) else None
                self.voices = result
                self.voice.configure(values=[f"{v['name']} ({v['culture']})" for v in result], state="readonly" if result else "disabled")
                if result:
                    self.voice.current(next((i for i, v in enumerate(result) if v["name"] == old_voice),
                                            next((i for i, v in enumerate(result) if v["culture"].startswith("ko")), 0)))
                self.status.set("텍스트를 입력한 뒤 WAV 저장 또는 사운드보드에 추가를 누르세요." if result else "사용 가능한 Windows 음성이 없습니다. Windows 설정에서 음성을 설치하세요.")
            elif kind == "added":
                self.status.set("사운드보드에 추가 완료: " + result + " · 게임 → 사운드보드에서 재생하세요.")
            elif kind == "played":
                self.status.set("일회용 출력 완료: " + result + " · 임시 음성 파일 폐기 완료")
            elif kind == "previewed":
                self.status.set("미리듣기 종료 · 원본 TTS는 다음 변조에 재사용합니다.")
            elif kind == "remixed":
                self.status.set("변조만 재생성 완료 · 저장·출력 시 동일한 결과를 재사용합니다.")
            else:
                self.status.set("저장 완료: " + result)
        self.timer = self.after(50, self.poll)

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        self.engine.close()
        if hasattr(self, "progress_bar"):
            self.progress_bar.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        super().destroy()
        self.status = self.rate = self.volume = self.title = self.count = self.short_preview = None


def register(registry):
    registry.register(ToolSpec("files.tts", "TTS 음성 생성", "파일", lambda parent, app: TTSTool(parent, app), 25))
