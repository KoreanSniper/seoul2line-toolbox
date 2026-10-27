import queue
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, ttk

from app.palette import palette
from app.services.tts import WindowsTTS
from app.tool_registry import ToolSpec
from app.ui import RoundedButton


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
        self.status = tk.StringVar(value="설치된 음성을 확인하는 중…")
        self.rate = tk.IntVar(value=0)
        self.volume = tk.IntVar(value=100)
        self.title = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        tk.Label(self, text="TTS 음성 생성", font=("Malgun Gothic", 20, "bold"), bg=colors["panel"], fg=colors["text"]).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        tk.Label(self, text="Windows에 설치된 음성으로 WAV 저장 · 인터넷 연결 불필요 · 최대 10,000자",
                 bg=colors["panel"], fg=colors["muted"], wraplength=480, justify="left").grid(row=1, column=0, sticky="w", padx=18, pady=(0, 8))
        self.text = tk.Text(self, wrap="word", height=8, undo=True, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"], relief="flat")
        self.text.grid(row=2, column=0, sticky="nsew", padx=18)
        controls = tk.Frame(self, bg=colors["panel"])
        controls.grid(row=3, column=0, sticky="ew", padx=18, pady=10)
        controls.columnconfigure(1, weight=1)
        for row, title in enumerate(("음성", "속도", "볼륨 (%)")):
            tk.Label(controls, text=title, bg=colors["panel"], fg=colors["text"]).grid(row=row, column=0, sticky="w", padx=(0, 12))
        self.voice = ttk.Combobox(controls, state="disabled")
        self.voice.grid(row=0, column=1, sticky="ew")
        for row, variable, low, high in ((1, self.rate, -10, 10), (2, self.volume, 0, 100)):
            tk.Scale(controls, variable=variable, from_=low, to=high, orient="horizontal", bg=colors["panel"], fg=colors["text"], highlightthickness=0).grid(row=row, column=1, sticky="ew")
        tk.Label(controls, text="사운드 제목", bg=colors["panel"], fg=colors["text"]).grid(row=3, column=0, sticky="w", padx=(0, 12))
        tk.Entry(controls, textvariable=self.title, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"]).grid(row=3, column=1, sticky="ew", pady=8)
        actions = tk.Frame(controls, bg=colors["panel"])
        actions.grid(row=4, column=0, columnspan=2, sticky="e")
        self.generate_button = RoundedButton(actions, "WAV 저장", self.generate, colors, compact=True)
        self.generate_button.pack(side="left", padx=(0, 8))
        RoundedButton(actions, "사운드보드에 추가", lambda: self.generate(True), colors, compact=True, accent=True).pack(side="left")
        tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["muted"], wraplength=480, justify="left").grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 16))
        self.submit("voices", self.engine.voices)
        self.timer = self.after(50, self.poll)

    def submit(self, kind, command):
        results = self.results
        def run():
            try:
                results.put((kind, command(), None))
            except Exception as exc:
                results.put((kind, None, str(exc)))
        self.executor.submit(run)

    def generate(self, add_to_soundboard=False):
        if self.closed or self.busy:
            return
        text = self.text.get("1.0", "end-1c")
        if not text.strip() or len(text) > 10000:
            self.status.set("텍스트를 1~10,000자 입력하세요.")
            return
        if not self.voices:
            self.status.set("사용 가능한 Windows 음성이 없습니다. Windows 설정에서 음성을 설치한 뒤 도구를 다시 여세요.")
            return
        if add_to_soundboard:
            title = self.title.get().strip() or text.strip().splitlines()[0][:100]
            if len(title) > 100:
                self.status.set("사운드 제목은 1~100자로 입력하세요.")
                return
        else:
            target = filedialog.asksaveasfilename(parent=self, title="TTS 음성 저장", defaultextension=".wav", filetypes=[("WAV 음성", "*.wav")])
            if not target:
                return
        voice = self.voices[self.voice.current()]["name"]
        rate, volume = self.rate.get(), self.volume.get()
        self.busy = True
        self.status.set("음성 생성 및 사운드보드 등록 중…" if add_to_soundboard else "음성 생성 중… (화면을 떠나면 취소됩니다)")
        engine = self.engine
        if add_to_soundboard:
            self.submit("added", lambda: engine.add_to_soundboard(text, title, voice, rate, volume))
        else:
            self.submit("generated", lambda: engine.generate(text, target, voice, rate, volume))

    def poll(self):
        while not self.results.empty():
            kind, result, error = self.results.get_nowait()
            self.busy = False
            if error:
                self.status.set("음성 처리 실패: " + error)
            elif kind == "voices":
                self.voices = result
                self.voice.configure(values=[f"{v['name']} ({v['culture']})" for v in result], state="readonly" if result else "disabled")
                if result:
                    self.voice.current(next((i for i, v in enumerate(result) if v["culture"].startswith("ko")), 0))
                self.status.set("텍스트를 입력한 뒤 WAV 저장 또는 사운드보드에 추가를 누르세요." if result else "사용 가능한 Windows 음성이 없습니다. Windows 설정에서 음성을 설치하세요.")
            elif kind == "added":
                self.status.set("사운드보드에 추가 완료: " + result + " · 게임 → 사운드보드에서 재생하세요.")
            else:
                self.status.set("저장 완료: " + result)
        self.timer = self.after(50, self.poll)

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        self.engine.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.after_cancel(self.timer)
        super().destroy()
        self.status = self.rate = self.volume = self.title = None


def register(registry):
    registry.register(ToolSpec("files.tts", "TTS 음성 생성", "파일", lambda parent, app: TTSTool(parent, app), 25))
