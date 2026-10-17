import math
import time
import tkinter as tk

from app.games.aim_trainer.model import AimSession, Camera, Sensitivity
from app.games.aim_trainer.raw_mouse import RawMouse
from app.games.aim_trainer.scene import render_faces
from app.palette import palette
from app.ui import RoundedButton


class AimTrainer(tk.Frame):
    def __init__(self, parent, app):
        self.colors = colors = palette(app.dark_mode)
        super().__init__(parent, bg=colors["panel"], padx=16, pady=14)
        self.session = AimSession()
        self.raw = None
        self.job = None
        self.active = False
        self.camera = Camera()
        self.keys = set()
        self.last_tick = time.perf_counter()
        self.settings = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        tk.Label(self, text="에임 연습", font=("Segoe UI", 20, "bold"), bg=colors["panel"], fg=colors["text"]).grid(sticky="w")
        form = tk.Frame(self, bg=colors["panel"])
        form.grid(row=1, column=0, sticky="ew", pady=8)
        self.fields = {}
        for index, (key, label, default) in enumerate((
            ("game", "기준 게임 (메모)", "사용자 정의"), ("dpi", "마우스 DPI", "800"),
            ("coefficient", "회전 계수 (°/count)", "0.07"), ("fov", "수평 FOV (°)", "90"),
            ("duration", "연습 시간 (초)", "60"), ("radius", "표적 반지름 (m)", "0.25"),
        )):
            column, row = index % 3, (index // 3) * 2
            form.columnconfigure(column, weight=1)
            tk.Label(form, text=label, bg=colors["panel"], fg=colors["muted"], anchor="w").grid(row=row, column=column, sticky="ew", padx=(0, 10))
            variable = tk.StringVar(self, default)
            self.fields[key] = variable
            tk.Entry(form, textvariable=variable, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"], width=14).grid(row=row + 1, column=column, sticky="ew", padx=(0, 10), pady=(3, 8))
        tk.Label(self, text="eDPI 800 고정 · 감도 = 800 ÷ DPI. 회전 계수는 해당 게임의 감도 1에서 입력 1카운트당 회전각입니다.\n게임 이름은 메모용이며 계수를 자동으로 바꾸지 않습니다. 기본 계수 0.07은 사용자 정의값입니다.\n3D 사격장 · 마우스 시점 회전 · WASD 이동 · 좌클릭 발사 · Esc 종료",
                 bg=colors["panel"], fg=colors["muted"], justify="left", anchor="w", wraplength=760).grid(row=2, column=0, sticky="ew")
        self.status = tk.StringVar(self, "설정 후 시작 · 좌클릭 발사 · Esc 또는 화면 이탈 시 종료")
        tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["text"], anchor="w", justify="left", wraplength=760, height=3).grid(row=3, column=0, sticky="ew", pady=8)
        self.canvas = tk.Canvas(self, bg=colors["field"], highlightthickness=1, highlightbackground=colors["border"], takefocus=True)
        self.canvas.grid(row=4, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self.shoot)
        self.canvas.bind("<Escape>", lambda event: self.stop("연습 종료"))
        self.canvas.bind("<FocusOut>", lambda event: self.stop("화면 이탈 · 연습 종료") if self.active else None)
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<KeyPress>", lambda event: self.keys.add(event.keysym.lower()))
        self.canvas.bind("<KeyRelease>", lambda event: self.keys.discard(event.keysym.lower()))
        RoundedButton(self, "연습 시작", self.start, colors, compact=True).grid(row=5, column=0, sticky="ew", pady=(10, 0))

    def size(self):
        return self.canvas.winfo_width(), self.canvas.winfo_height()

    def start(self):
        if self.active:
            return
        try:
            self.settings = Sensitivity(*(float(self.fields[key].get()) for key in ("dpi", "coefficient", "fov")))
            duration, radius = float(self.fields["duration"].get()), float(self.fields["radius"].get())
            if not math.isfinite(duration) or not 5 <= duration <= 600 or not math.isfinite(radius) or not .05 <= radius <= .6:
                raise ValueError("연습 시간은 5~600초, 표적 반지름은 0.05~0.6m로 입력하세요.")
            self.update_idletasks()
            width, height = self.size()
            if min(width, height) < 100:
                raise ValueError("연습 영역이 작습니다. 창을 넓히세요.")
            self.canvas.focus_set()
            self.raw = RawMouse(self.canvas.winfo_id())
            if not self.raw.confine_center():
                raise ValueError("툴박스 창을 활성화한 뒤 다시 시작하세요.")
        except (ValueError, OSError, AttributeError) as exc:
            self.release_input()
            self.status.set(str(exc))
            return
        self.canvas.configure(cursor="none")
        self.camera = Camera()
        self.keys.clear()
        self.session = AimSession(duration, radius)
        self.last_tick = time.perf_counter()
        self.session.start(self.last_tick)
        self.active = True
        self.tick()

    def update_input(self):
        dx, dy = self.raw.take()
        self.camera.yaw = (self.camera.yaw + self.settings.angle(dx)) % 360
        self.camera.pitch = max(-89, min(89, self.camera.pitch + self.settings.angle(dy)))

    def shoot(self, event=None):
        if not self.active:
            return
        self.update_input()
        if self.session.remaining(time.perf_counter()) <= 0:
            self.stop("연습 완료")
            return
        self.session.shoot(self.camera, time.perf_counter())
        self.draw()

    def tick(self):
        frame_started = time.perf_counter()
        self.job = None
        if not self.active:
            return
        if self.raw.error:
            self.stop("입력 오류: " + self.raw.error)
            return
        if self.session.remaining(time.perf_counter()) <= 0:
            self.stop("연습 완료")
            return
        try:
            if not self.raw.confine_center():
                self.stop("화면 이탈 · 연습 종료")
                return
        except OSError as exc:
            self.stop("커서 고정 실패: " + str(exc))
            return
        self.update_input()
        now = time.perf_counter()
        self.camera.move(int('w' in self.keys) - int('s' in self.keys),
                         int('d' in self.keys) - int('a' in self.keys), min(.05, now - self.last_tick))
        self.last_tick = now
        self.draw()
        self.job = self.after(max(1, 16 - int((time.perf_counter() - frame_started) * 1000)), self.tick)

    def summary(self):
        session = self.session
        return f"적중 {session.hits}/{session.shots} · 정확도 {session.accuracy:.1f}% · 평균 표적 처리 {session.reaction_ms:.0f}ms"

    def draw(self):
        self.canvas.delete("all")
        width, height = self.size()
        if min(width, height) < 2:
            return
        fov = self.settings.fov if self.settings else 90
        for depth, points, color in render_faces(self.camera, self.session.target, self.session.radius, width, height, fov):
            self.canvas.create_polygon(*[coordinate for point in points for coordinate in point], fill=color, outline=color, tags='world3d')
        x, y = width / 2, height / 2
        self.canvas.create_line(x - 9, y, x + 9, y, fill=self.colors["text"], width=2)
        self.canvas.create_line(x, y - 9, x, y + 9, fill=self.colors["text"], width=2)
        if self.active:
            self.status.set(f"남은 시간 {self.session.remaining(time.perf_counter()):.1f}초 · {self.summary()}\neDPI 800 · 감도 {self.settings.sensitivity:.8g} · 360° 약 {self.settings.cm360:.1f}cm · Esc 종료")

    def resize(self, event=None):
        if self.active:
            self.stop("영역 크기 변경 · 다시 시작하세요")
        self.draw()

    def release_input(self):
        if self.raw:
            self.raw.close()
            self.raw = None
        self.canvas.configure(cursor="")

    def stop(self, message="연습 종료"):
        self.active = False
        self.keys.clear()
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.release_input()
        self.status.set(f"{message} · {self.summary()}")

    def destroy(self):
        self.stop()
        super().destroy()
