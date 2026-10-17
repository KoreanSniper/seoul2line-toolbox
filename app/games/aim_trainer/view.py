import math
import time
import tkinter as tk

from app.games.aim_trainer.model import AimSession, Sensitivity, focal_length, project
from app.games.aim_trainer.raw_mouse import RawMouse
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
        self.camera = [0.0, 0.0]
        self.world_target = None
        self.settings = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        tk.Label(self, text="에임 연습", font=("Segoe UI", 20, "bold"), bg=colors["panel"], fg=colors["text"]).grid(sticky="w")
        form = tk.Frame(self, bg=colors["panel"])
        form.grid(row=1, column=0, sticky="ew", pady=8)
        self.fields = {}
        for index, (key, label, default) in enumerate((
            ("game", "기준 게임 (메모)", "사용자 정의"), ("dpi", "마우스 DPI", "800"),
            ("coefficient", "회전 계수 (°/count)", "1"), ("fov", "수평 FOV (°)", "90"),
            ("duration", "연습 시간 (초)", "60"), ("radius", "표적 반지름 (px)", "20"),
        )):
            column, row = index % 3, (index // 3) * 2
            form.columnconfigure(column, weight=1)
            tk.Label(form, text=label, bg=colors["panel"], fg=colors["muted"], anchor="w").grid(row=row, column=column, sticky="ew", padx=(0, 10))
            variable = tk.StringVar(self, default)
            self.fields[key] = variable
            tk.Entry(form, textvariable=variable, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"], width=14).grid(row=row + 1, column=column, sticky="ew", padx=(0, 10), pady=(3, 8))
        tk.Label(self, text="eDPI 1 고정 · 감도 = 1 ÷ DPI. 회전 계수는 해당 게임의 감도 1에서 입력 1카운트당 회전각입니다.\n게임 이름은 메모용이며 계수를 자동으로 바꾸지 않습니다. 기본 계수 1은 사용자 정의값입니다.\neDPI 1은 매우 낮은 감도입니다. 연습 중에는 커서가 고정되며 Esc로 해제합니다.",
                 bg=colors["panel"], fg=colors["muted"], justify="left", anchor="w", wraplength=760).grid(row=2, column=0, sticky="ew")
        self.status = tk.StringVar(self, "설정 후 시작 · 좌클릭 발사 · Esc 또는 화면 이탈 시 종료")
        tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["text"], anchor="w", justify="left", wraplength=760).grid(row=3, column=0, sticky="ew", pady=8)
        self.canvas = tk.Canvas(self, bg=colors["field"], highlightthickness=1, highlightbackground=colors["border"], takefocus=True)
        self.canvas.grid(row=4, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self.shoot)
        self.canvas.bind("<Escape>", lambda event: self.stop("연습 종료"))
        self.canvas.bind("<FocusOut>", lambda event: self.stop("화면 이탈 · 연습 종료") if self.active else None)
        self.canvas.bind("<Configure>", self.resize)
        RoundedButton(self, "연습 시작", self.start, colors, compact=True).grid(row=5, column=0, sticky="ew", pady=(10, 0))

    def size(self):
        return self.canvas.winfo_width(), self.canvas.winfo_height()

    def start(self):
        if self.active:
            return
        try:
            self.settings = Sensitivity(*(float(self.fields[key].get()) for key in ("dpi", "coefficient", "fov")))
            duration, radius = float(self.fields["duration"].get()), float(self.fields["radius"].get())
            if not math.isfinite(duration) or not 5 <= duration <= 600 or not math.isfinite(radius) or not 4 <= radius <= 80:
                raise ValueError("연습 시간은 5~600초, 표적 반지름은 4~80px로 입력하세요.")
            width, height = self.size()
            if min(width, height) < 2 * (radius + 8):
                raise ValueError("연습 영역이 작습니다. 창을 넓히거나 표적 크기를 줄이세요.")
            self.canvas.focus_set()
            self.raw = RawMouse(self.canvas.winfo_id())
            self.raw.confine(self.canvas.winfo_rootx() + width // 2, self.canvas.winfo_rooty() + height // 2)
        except (ValueError, OSError, AttributeError) as exc:
            self.release_input()
            self.status.set(str(exc))
            return
        self.canvas.configure(cursor="none")
        self.camera = [0.0, 0.0]
        self.session = AimSession(duration, radius)
        self.session.start(time.perf_counter(), width, height)
        self.anchor_target()
        self.active = True
        self.tick()

    def anchor_target(self):
        width, height = self.size()
        x, y = self.session.target
        focal = focal_length(width, self.settings.fov)
        pitch = self.camera[1] + math.degrees(math.atan((y - height / 2) / focal))
        self.world_target = (self.camera[0] + math.degrees(math.atan((x - width / 2) / focal)),
                             max(-88, min(88, pitch)))

    def update_input(self):
        dx, dy = self.raw.take()
        self.camera[0] = (self.camera[0] + self.settings.angle(dx)) % 360
        self.camera[1] = max(-89, min(89, self.camera[1] + self.settings.angle(dy)))
        self.session.target = project(self.world_target, self.camera, *self.size(), self.settings.fov)

    def shoot(self, event=None):
        if not self.active:
            return
        self.update_input()
        width, height = self.size()
        if self.session.remaining(time.perf_counter()) <= 0:
            self.stop("연습 완료")
            return
        if self.session.target is None:
            self.session.shots += 1
        elif self.session.shoot(width / 2, height / 2, time.perf_counter(), width, height):
            self.anchor_target()
        self.draw()

    def tick(self):
        self.job = None
        if not self.active:
            return
        if self.raw.error:
            self.stop("입력 오류: " + self.raw.error)
            return
        if self.session.remaining(time.perf_counter()) <= 0:
            self.stop("연습 완료")
            return
        self.update_input()
        self.draw()
        self.job = self.after(16, self.tick)

    def summary(self):
        session = self.session
        return f"적중 {session.hits}/{session.shots} · 정확도 {session.accuracy:.1f}% · 평균 표적 처리 {session.reaction_ms:.0f}ms"

    def draw(self):
        self.canvas.delete("all")
        width, height = self.size()
        if self.session.target:
            x, y = self.session.target
            radius = self.session.radius
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=self.colors["accent"], outline=self.colors["text"], width=2)
        x, y = width / 2, height / 2
        self.canvas.create_line(x - 9, y, x + 9, y, fill=self.colors["text"], width=2)
        self.canvas.create_line(x, y - 9, x, y + 9, fill=self.colors["text"], width=2)
        if self.active:
            self.status.set(f"남은 시간 {self.session.remaining(time.perf_counter()):.1f}초 · {self.summary()}\neDPI 1 · 감도 {self.settings.sensitivity:.8g} · 360° 약 {self.settings.cm360:.1f}cm · Esc 종료")

    def resize(self, event=None):
        if self.active:
            self.stop("영역 크기 변경 · 다시 시작하세요")

    def release_input(self):
        if self.raw:
            self.raw.close()
            self.raw = None
        self.canvas.configure(cursor="")

    def stop(self, message="연습 종료"):
        self.active = False
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.release_input()
        self.status.set(f"{message} · {self.summary()}")

    def destroy(self):
        self.stop()
        super().destroy()
