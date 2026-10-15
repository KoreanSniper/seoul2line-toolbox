from __future__ import annotations

import math
import os
import json
import random
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox

from app.tool_registry import ToolSpec
from app.games.starsystem.renderer import ShaderProgram, ShaderSourceError
from app.ui import RoundedButton, RoundedFrame
from app.palette import palette
from app.config import CONFIG_PATH
from app.paths import application_root

try:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        config = {}
except (OSError, UnicodeError, json.JSONDecodeError):
    config = {}

theme = config.get("theme","dark")
dark_mode:bool = (theme == "dark")

G = 0.035
MAX_BODIES = 400
MAX_TRAIL = 36
MAX_WAVES = 8
PLANET_RADIUS_SCALE = 0.68
STAR_MASS = 680000
SPAWN_STAR_MASS = 320000
BLACK_HOLE_EFFECTIVE_MASS = 1800000
MIN_ZOOM = 0.18
MAX_ZOOM = 5.0
RENDER_PROFILES = {
    "저사양": {
        "grid_line_step": 60,
        "grid_sample_step": 32,
        "grid_alpha": 0.7,
        "glow_layers": 0,
        "radial_steps": 28,
        "lens_steps": 24,
        "ellipse_steps": 40,
        "crescent_steps": 16,
        "photon_rays": 4,
        "ray_steps": 18,
        "target_fps": 45,
    },
    "균형": {
        "grid_line_step": 24,
        "grid_sample_step": 18,
        "grid_alpha": 0.9,
        "glow_layers": 4,
        "radial_steps": 40,
        "lens_steps": 36,
        "ellipse_steps": 56,
        "crescent_steps": 22,
        "photon_rays": 7,
        "ray_steps": 28,
        "target_fps": 60,
    },
    "화질": {
        "grid_line_step": 16,
        "grid_sample_step": 12,
        "grid_alpha": 0.92,
        "glow_layers": 5,
        "radial_steps": 56,
        "lens_steps": 48,
        "ellipse_steps": 80,
        "crescent_steps": 26,
        "photon_rays": 10,
        "ray_steps": 40,
        "target_fps": 60,
    },
}

@dataclass
class Body:
    x: float
    y: float
    vx: float
    vy: float
    mass: float
    radius: float
    color: tuple[float, float, float]
    name: str
    kind: str = "행성"
    temperature: float = 0.0
    luminosity: float = 0.0
    atmosphere: bool = False
    trail: list[tuple[float, float]] = field(default_factory=list)
    play: bool = True
    def __getitem__(self, key):
        return getattr(self, key)


@dataclass
class ShockWave:
    x: float
    y: float
    radius: float
    strength: float
    age: int = 0


@dataclass
class ExplosionFlash:
    x: float
    y: float
    strength: float
    angle: float = 0.0
    color: tuple[float, float, float] = (1.0, 0.55, 0.18)
    age: int = 0
    life: int = 34


class GpuStarSystemLauncher(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.process: subprocess.Popen | None = None
        self.status = tk.StringVar(value="GPU 렌더러 대기 중")
        self._build()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="GPU 항성계 샌드박스", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="중력/충돌은 CPU가 계산하고, 격자/천체/궤적은 OpenGL GPU 창에서 그립니다.",
            font=("Segoe UI", 10),
            fg=colors["muted"],
            bg=colors["panel"],
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        RoundedButton(header, "GPU 창 열기", self.launch, colors, accent=True, compact=True, radius=10).grid(row=0, column=1, rowspan=2, sticky="e")

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        info = RoundedFrame(body, colors, colors["panel_soft"], colors["border"], radius=18, padding=16)
        info.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(info.body, text="조작", font=("Segoe UI", 14, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(anchor="w")
        for line in (
            "마우스 드래그: 방향/힘으로 천체 생성",
            "우클릭 드래그: 무한 월드 화면 이동",
            "짧은 우클릭: 천체 정보창 열기",
            "휠: 카메라 확대/축소",
            "1 행성, 2 항성, 3 먼지, 4 블랙홀",
            "Space 일시정지, R 초기화, O 랜덤 궤도",
            "+/- 힘 배율, [/] 질량 조절",
            "옆 조작창에서 질량/힘/중력/빛/노출 조절",
            "Esc 또는 GPU 창 닫기: 종료",
        ):
            tk.Label(info.body, text=line, fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 10), anchor="w").pack(anchor="w", pady=(10, 0))

        tech = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=18, padding=16)
        tech.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(tech.body, text="렌더링 구조", font=("Segoe UI", 14, "bold"), fg=colors["text"], bg=colors["surface"]).pack(anchor="w")
        tk.Label(
            tech.body,
            text=(
                "Tkinter Canvas가 아니라 pygame OPENGL 디스플레이를 사용합니다.\n\n"
                "Python은 천체 위치, 중력, 충돌, 블랙홀 흡수와 카메라 상태만 계산하고 OpenGL이 월드 격자와 천체를 그립니다.\n\n"
                "항성 온도 기반 색, 역제곱 광량, 노출, ACES 톤매핑 기반으로 셰이더 파이프라인으로 옮길 준비가 된 구조입니다."
            ),
            fg=colors["muted"],
            bg=colors["surface"],
            font=("Segoe UI", 10),
            justify="left",
            wraplength=360,
        ).pack(anchor="w", pady=(10, 18))
        tk.Label(tech.body, textvariable=self.status, fg=colors["accent"], bg=colors["surface"], font=("Segoe UI", 10, "bold")).pack(anchor="w")

    def launch(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.launch()
            return
        try:
            project_root = application_root()
            # 버튼 콜백에서 별도 Python 프로세스를 실행해 메인 Tkinter 창을 멈추지 않는다.
            command = [sys.executable, "--run-gpu-stars"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "app.tools.chill_starsystem_gpu", "--run"]
            self.process = subprocess.Popen(command, cwd=project_root)
        except OSError as exc:
            messagebox.showerror("GPU 항성계", f"GPU 창을 열 수 없습니다.\n{exc}")
            return
        self.status.set("GPU 창 실행 중")


class GpuStarSystem:
    def __init__(self) -> None:
        self.width = 1100
        self.height = 720
        self.running = True
        self.kind = "행성"
        self.mass = 35.0
        self.force = 1.0
        self.gravity = G
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.zoom = 1.0
        self.show_grid = False
        self.show_light = True
        self.quality = "균형"
        self.light_power = 0.72
        self.lens_power = 0.62
        self.exposure = 0.92
        self.star_temperature = 5800.0
        self.last_event = "대기 중"
        self.drag_start: tuple[float, float] | None = None
        self.drag_now: tuple[float, float] | None = None
        self.pan_start: tuple[float, float] | None = None
        self.pan_camera: tuple[float, float] | None = None
        self.pan_moved = False
        self.bodies: list[Body] = []
        self.waves: list[ShockWave] = []
        self.explosions: list[ExplosionFlash] = []
        self.spawn_tick = 0
        self.auto_spawn_enabled = True
        self.first()

    def spawn_planet(self):
        mass = random.randint(30,80) * random.uniform(0.8,1.2) * random.uniform(0.8,1.2) * random.uniform(0.8,1.2)
        angle = random.random() * math.tau
        distance = 225 + random.randint(0,28)
        x = math.cos(angle) * distance + self.bodies[0]["x"]
        y = math.sin(angle) * distance + self.bodies[0]["y"]
        speed = orbit_speed(STAR_MASS, distance) * random.uniform(0.92, 1.06) * random.uniform(0.92, 1.06) * random.uniform(0.92, 1.06) * random.uniform(0.92, 1.06) * random.uniform(0.92, 1.06) * random.choice([-1,1])
        self.bodies.append(Body(x, y, -math.sin(angle) * speed, math.cos(angle) * speed, mass, random.uniform(3.0, 5.2), random.choice(PALETTE), f"천체", "행성", atmosphere=random.randint(1,3) % 3 == 0))

    def first(self) -> None:
        
        self.waves = []
        self.explosions = []
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.zoom = 1.0
        main_mass = STAR_MASS
        self.bodies = [
            make_star(0, 0, 0, 0, main_mass, 24, "주성", 5800)
        ]
        self.spawn_tick = 0
        self.last_event = "항성계를 생성함"

    def reset(self) -> None:
        self.stop_auto_spawn()
        self.waves = []
        self.explosions = []
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.zoom = 1.0
        main_mass = STAR_MASS
        self.bodies = [
            make_star(0, 0, 0, 0, main_mass, 24, "주성", 5800)
        ]
        self.spawn_tick = 0
        self.last_event = "항성계를 초기화함"
        

    def seed_orbits(self) -> None:
        self.stop_auto_spawn()
        self.waves = []
        self.explosions = []
        main_mass = STAR_MASS
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.zoom = 1.0
        self.bodies = [make_star(0, 0, 0, 0, main_mass, 24, "주성", 5800)]
        self.spawn_tick = 0
        for index in range(96):
            angle = random.random() * math.tau
            distance = 85 + index * random.randint(0,28)
            x = math.cos(angle) * distance
            y = math.sin(angle) * distance
            speed = orbit_speed(main_mass, distance) * random.uniform(0.92, 1.06)
            self.bodies.append(Body(x, y, -math.sin(angle) * speed, math.cos(angle) * speed, random.randint(10, 500), random.uniform(3.0, 5.4), random.choice(PALETTE), f"천체 {index + 1}", "행성", atmosphere=index % 3 == 0))
        self.last_event = "안정 궤도 프리셋 생성"

    def stop_auto_spawn(self) -> None:
        self.auto_spawn_enabled = False
        self.spawn_tick = 0

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.mass = {"행성": 35.0, "항성": SPAWN_STAR_MASS, "먼지": 8.0, "블랙홀": -1.0}[kind]

    def set_quality(self, quality: str) -> None:
        if quality in RENDER_PROFILES:
            self.quality = quality
            self.last_event = f"렌더 품질: {quality}"

    def render_profile(self) -> dict[str, float | int]:
        return RENDER_PROFILES.get(self.quality, RENDER_PROFILES["균형"])

    def spawn(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        sx, sy = start
        dx = sx - end[0]
        dy = sy - end[1]
        mass = -1 if self.kind == "블랙홀" else max(1, self.mass)
        if self.kind == "블랙홀":
            radius = 13
        elif self.kind == "항성":
            radius = 18
        elif self.kind == "먼지":
            radius = 3.4
        else:
            radius = max(3.6, min(12.0, math.sqrt(mass) * PLANET_RADIUS_SCALE))
        if len(self.bodies) >= MAX_BODIES:
            self.bodies.pop(1 if len(self.bodies) > 1 else 0)
        if self.kind == "항성":
            temperature = self.star_temperature
            body = make_star(sx, sy, dx * 0.018 * self.force, dy * 0.018 * self.force, max(SPAWN_STAR_MASS, mass), radius, self.kind, temperature)
        else:
            color = {"행성": hex_color("#38bdf8"), "먼지": hex_color("#a7f3d0"), "블랙홀": hex_color("#020617")}[self.kind]
            body = Body(sx, sy, dx * 0.018 * self.force, dy * 0.018 * self.force, mass, radius, color, self.kind, self.kind, atmosphere=self.kind == "행성")
        self.bodies.append(body)
        self.last_event = f"{self.kind} 생성"

    def step(self) -> None:
        if self.auto_spawn_enabled:
            self.spawn_tick += 1
            if self.spawn_tick >= int(self.render_profile()["target_fps"]) and len(self.bodies) < MAX_BODIES:
                self.spawn_tick = 0
                self.spawn_planet()

        for wave in self.waves:
            wave.age += 1
            wave.radius += 7 + wave.strength * 0.03
            wave.strength *= 0.94
        self.waves = [wave for wave in self.waves if wave.age < 80 and wave.strength > 1]

        for flash in self.explosions:
            flash.age += 1
        self.explosions = [flash for flash in self.explosions if flash.age < flash.life]

        accelerations = []
        for i, body in enumerate(self.bodies):
            ax = ay = 0.0
            for j, other in enumerate(self.bodies):
                if i == j:
                    continue
                dx = other.x - body.x
                dy = other.y - body.y
                dist_sq = dx * dx + dy * dy + 140
                dist = math.sqrt(dist_sq)
                pull = self.gravity * effective_mass(other) / dist_sq
                ax += pull * dx / dist
                ay += pull * dy / dist
            accelerations.append((ax, ay))
        for body, (ax, ay) in zip(self.bodies, accelerations):
            if body.play:
                body.vx = (body.vx + ax) * 0.99999
                body.vy = (body.vy + ay) * 0.99999
                body.x += body.vx
                body.y += body.vy
                body.trail.append((body.x, body.y))
                body.trail = body.trail[-MAX_TRAIL:]
        self.apply_wave_forces()
        self.resolve_collisions()

    def refresh_star_physics(self) -> None:
        for body in self.bodies:
            if body.kind != "항성":
                continue
            if body.temperature <= 0:
                body.temperature = self.star_temperature
            body.color = blackbody_color(body.temperature)
            body.luminosity = stellar_luminosity(body.mass, body.temperature, body.radius)

    def screen_to_world(self, x: float, y: float) -> tuple[float, float]:
        return self.camera_x + (x - self.width / 2) / self.zoom, self.camera_y + (y - self.height / 2) / self.zoom

    def zoom_at(self, screen_x: float, screen_y: float, factor: float) -> None:
        before_x, before_y = self.screen_to_world(screen_x, screen_y)
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        after_x, after_y = self.screen_to_world(screen_x, screen_y)
        self.camera_x += before_x - after_x
        self.camera_y += before_y - after_y
        self.last_event = f"줌 {self.zoom:.2f}x"

    def begin_pan(self, screen_pos: tuple[float, float]) -> None:
        self.pan_start = screen_pos
        self.pan_camera = (self.camera_x, self.camera_y)
        self.pan_moved = False

    def update_pan(self, screen_pos: tuple[float, float]) -> None:
        if self.pan_start is None or self.pan_camera is None:
            return
        dx = screen_pos[0] - self.pan_start[0]
        dy = screen_pos[1] - self.pan_start[1]
        self.camera_x = self.pan_camera[0] - dx / self.zoom
        self.camera_y = self.pan_camera[1] - dy / self.zoom
        if abs(dx) + abs(dy) > 6:
            self.pan_moved = True

    def end_pan(self) -> bool:
        moved = self.pan_moved
        self.pan_start = None
        self.pan_camera = None
        self.pan_moved = False
        return moved

    def apply_wave_forces(self) -> None:
        for body in self.bodies:
            for wave in self.waves:
                dx = body.x - wave.x
                dy = body.y - wave.y
                distance = math.hypot(dx, dy) + 1
                band = abs(distance - wave.radius)
                if band > 72:
                    continue
                pressure = (1 - band / 72) * wave.strength / max(effective_mass(body), 8)
                body.vx += dx / distance * pressure * 0.45
                body.vy += dy / distance * pressure * 0.45

    def resolve_collisions(self) -> None:
        remove: set[int] = set()
        additions: list[Body] = []
        for i, first in enumerate(self.bodies):
            if i in remove:
                continue
            for j in range(i + 1, len(self.bodies)):
                if j in remove:
                    continue
                second = self.bodies[j]
                if math.hypot(second.x - first.x, second.y - first.y) > first.radius + second.radius:
                    continue
                if first.kind == "블랙홀" or second.kind == "블랙홀":
                    keeper_index, eaten_index = (i, j) if first.kind == "블랙홀" else (j, i)
                    keeper = self.bodies[keeper_index]
                    eaten = self.bodies[eaten_index]
                    remove.add(eaten_index)
                    keeper.radius = min(34, keeper.radius + max(0.2, eaten.radius * 0.04))
                    if eaten.kind in {"항성", "블랙홀"}:
                        self.push_wave(eaten.x, eaten.y, 70 if eaten.kind == "블랙홀" else 34 + effective_mass(eaten) * 0.018)
                    if eaten.kind not in {"블랙홀", "먼지", "파편"} and eaten.radius >= 5:
                        additions.extend(self.shatter(keeper, eaten))
                        self.last_event = f"블랙홀이 {eaten.kind}을 부수며 흡수"
                    else:
                        self.last_event = f"블랙홀이 {eaten.kind} 흡수"
                    continue
                if first.kind == "항성" and second.kind == "항성":
                    larger_index, smaller_index = (i, j) if first.mass > second.mass else (j, i)
                    larger = self.bodies[larger_index]
                    smaller = self.bodies[smaller_index]
                    remove.add(smaller_index)
                    larger.mass += smaller.mass * 0.18
                    larger.radius = min(28, larger.radius + max(0.5, smaller.radius * 0.08))
                    larger.temperature = min(12000, max(2500, larger.temperature + smaller.mass * 0.015))
                    larger.luminosity = stellar_luminosity(larger.mass, larger.temperature, larger.radius)
                    larger.color = blackbody_color(larger.temperature)
                    if larger.mass>8000:
                        additions.extend(self.explode(larger, smaller))
                        remove.add(larger_index)
                        self.last_event = "항성 충돌 폭발"
                        continue
                    self.last_event = "항성 충돌 흡수"
                    continue
                if first.kind == "항성" or second.kind == "항성":
                    larger_index, smaller_index = (i, j) if first.kind == "항성" else (j, i)
                    larger = self.bodies[larger_index]
                    smaller = self.bodies[smaller_index]
                    impact_speed = math.hypot(first.vx - second.vx, first.vy - second.vy)
                    strength = min(140.0, first.mass + second.mass + impact_speed * 18.0)
                    self.push_explosion(smaller.x, smaller.y, strength, math.atan2(smaller.vy - larger.vy, smaller.vx - larger.vx), smaller.color)
                    remove.add(smaller_index)
                    larger.mass += smaller.mass * 0.18
                    larger.radius = min(28, larger.radius + max(0.5, smaller.radius * 0.08))
                    larger.temperature = min(12000, max(2500, larger.temperature + smaller.mass * 0.015))
                    larger.luminosity = stellar_luminosity(larger.mass, larger.temperature, larger.radius)
                    larger.color = blackbody_color(larger.temperature)
                    self.last_event = f"항성이 {smaller.kind} 흡수"
                    continue
                if not(first.kind in {"파편"} and second.kind in {"파편"}):
                    larger_index, smaller_index = (i, j) if first.mass > second.mass else (j, i)
                    larger = self.bodies[larger_index]
                    smaller = self.bodies[smaller_index]
                    if smaller.mass/larger.mass < 0.05:
                        remove.add(smaller_index)
                        larger.mass += smaller.mass * 0.18
                        larger.radius = min(28, larger.radius + max(0.5, smaller.radius * 0.08))
                        self.last_event = "행성 충돌 흡수"
                    else:
                        remove.update((i, j))
                        additions.extend(self.break_collision(first, second))
                        self.last_event = "행성 충돌 파쇄"
                if first.kind in {"파편"} and second.kind in {"파편"}:
                    larger_index, smaller_index = (i, j) if first.mass >= second.mass else (j, i)
                    larger = self.bodies[larger_index]
                    smaller = self.bodies[smaller_index]
                    remove.add(smaller_index)
                    larger.mass += smaller.mass * 0.18
                    larger.radius = min(28, larger.radius + max(0.5, smaller.radius * 0.08))
                    self.last_event = f"파편 병합"
        if remove:
            self.bodies = [body for index, body in enumerate(self.bodies) if index not in remove]
            self.bodies.extend(additions[: max(0, MAX_BODIES - len(self.bodies))])

    def break_collision(self, first: Body, second: Body) -> list[Body]:
        x = (first.x + second.x) / 2
        y = (first.y + second.y) / 2
        impact_speed = math.hypot(first.vx - second.vx, first.vy - second.vy)
        strength = min(140.0, first.mass + second.mass + impact_speed * 18.0)
        self.push_explosion(x, y, strength, math.atan2(second.vy - first.vy, second.vx - first.vx), mix_color(first.color, second.color, 0.5))
        fragments = []
        total = min(8, max(4, int(first.radius + second.radius)))
        for index in range(total):
            angle = math.tau * index / total + random.uniform(-0.25, 0.25)
            speed = random.uniform(0.6, 1.8)*3
            source = first if index % 2 == 0 else second
            fragments.append(Body(x + math.cos(angle) * 8, y + math.sin(angle) * 8, math.cos(angle) * speed + source.vx * 0.35, math.sin(angle) * speed + source.vy * 0.35, max(2, (first.mass + second.mass) / total * 0.25), random.uniform(2.0, 3.4), source.color, "충돌 파편", "파편"))
        return fragments

    def nearest_body(self, position: tuple[float, float]) -> Body | None:
        px, py = position
        best: tuple[float, Body] | None = None
        for body in self.bodies:
            distance = math.hypot(body.x - px, body.y - py)
            if distance <= max(18, body.radius + 8) and (best is None or distance < best[0]):
                best = (distance, body)
        return best[1] if best else None

    def shatter(self, black_hole: Body, eaten: Body) -> list[Body]:
        fragments = []
        count = max(3, min(5, int(eaten.radius * 0.65)))
        base_angle = math.atan2(eaten.y - black_hole.y, eaten.x - black_hole.x)
        for index in range(count):
            angle = base_angle + random.uniform(-1.2, 1.2) + index * 0.18
            distance = black_hole.radius + eaten.radius + random.uniform(4, 18)
            x = black_hole.x + math.cos(angle) * distance
            y = black_hole.y + math.sin(angle) * distance
            pull_angle = math.atan2(black_hole.y - y, black_hole.x - x)
            speed = random.uniform(1.7, 2.8)
            tangent = random.choice((-1, 1)) * random.uniform(0.15, 0.55)
            fragments.append(Body(x, y, math.cos(pull_angle) * speed - math.sin(pull_angle) * tangent, math.sin(pull_angle) * speed + math.cos(pull_angle) * tangent, max(2, eaten.mass / count * 0.32), 2.4, eaten.color, "흡수 파편", "파편"))
        return fragments

    def explode(self, first: Body, second: Body) -> list[Body]:
        x = (first.x * first.mass + second.x * second.mass) / (first.mass + second.mass)
        y = (first.y * first.mass + second.y * second.mass) / (first.mass + second.mass)
        strength = min(260, 55 + (first.mass + second.mass) * 0.08)
        self.push_wave(x, y, strength)
        self.push_explosion(x, y, strength * 1.3, math.atan2(second.vy - first.vy, second.vx - first.vx), mix_color(first.color, second.color, 0.5))
        fragments = []
        for index in range(10):
            angle = math.tau * index / 10 + random.uniform(-0.18, 0.18)
            speed = random.uniform(1.6, 3.4)
            fragments.append(Body(x + math.cos(angle) * 12, y + math.sin(angle) * 12, math.cos(angle) * speed, math.sin(angle) * speed, random.uniform(5, 14), random.uniform(2.2, 3.6), random.choice(PALETTE), "항성 잔해", "먼지"))
        return fragments

    def push_wave(self, x: float, y: float, strength: float) -> None:
        self.waves.append(ShockWave(x, y, 6, strength))
        self.waves = self.waves[-MAX_WAVES:]

    def push_explosion(self, x: float, y: float, strength: float, angle: float = 0.0, color: tuple[float, float, float] = (1.0, 0.55, 0.18)) -> None:
        self.explosions.append(ExplosionFlash(x, y, max(6.0, strength * 0.48), angle, color))
        self.explosions = self.explosions[-24:]

    def warp_point(self, x: float, y: float) -> tuple[float, float]:
        wx, wy = x, y
        for body in self.bodies:
            dx = body.x - x
            dy = body.y - y
            dist_sq = dx * dx + dy * dy + 800
            dist = math.sqrt(dist_sq)
            pressure = max(effective_mass(body), body.radius * body.radius * 12)
            warp = min(24, pressure / dist_sq * 24)
            wx += dx / dist * warp
            wy += dy / dist * warp
        for wave in self.waves:
            dx = x - wave.x
            dy = y - wave.y
            distance = math.hypot(dx, dy) + 1
            band = abs(distance - wave.radius)
            if band > 80:
                continue
            ripple = (1 - band / 80) * wave.strength / max(distance, 60)
            direction = 1 if distance >= wave.radius else -1
            wx += dx / distance * ripple * 13 * direction
            wy += dy / distance * ripple * 13 * direction
        return wx, wy


class GL:
    GL_COLOR_BUFFER_BIT = 0x00004000
    GL_PROJECTION = 0x1701
    GL_MODELVIEW = 0x1700
    GL_POINTS = 0x0000
    GL_LINES = 0x0001
    GL_LINE_STRIP = 0x0003
    GL_TRIANGLE_FAN = 0x0006
    GL_QUADS = 0x0007
    GL_BLEND = 0x0BE2
    GL_SRC_ALPHA = 0x0302
    GL_ONE = 0x0001
    GL_ONE_MINUS_SRC_ALPHA = 0x0303

    def __init__(self) -> None:
        from OpenGL import GL as pygl

        self.lib = pygl

    def _bind(self) -> None:
        return None

    def color(self, color: tuple[float, float, float], alpha: float = 1.0) -> None:
        self.lib.glColor4f(color[0], color[1], color[2], alpha)

    def vertex(self, x: float, y: float) -> None:
        self.lib.glVertex2f(x, y)


class FullscreenGpuEffects:
    def __init__(self) -> None:
        self.program = ShaderProgram("fullscreen.vert", "blackhole_ray.frag")
        self.ready = False
        self.failed = False
        self.error = ""

    def ensure_ready(self) -> bool:
        if self.ready:
            return True
        if self.failed:
            return False
        try:
            self.program.compile()
        except (ShaderSourceError, RuntimeError) as exc:
            # 셰이더 컴파일 실패를 객체에 기록하고 호출부가 기본 렌더링 경로를 선택하게 한다.
            self.failed = True
            self.error = str(exc)
            return False
        self.ready = True
        return True

    def draw(self, gl: GL, world: GpuStarSystem, elapsed: float) -> bool:
        if not self.ensure_ready():
            return False
        pygl = gl.lib
        black_holes = [body for body in world.bodies if body.kind == "블랙홀"]
        black_hole = black_holes[0] if black_holes else None
        bh_x = black_hole.x if black_hole else world.camera_x + 1000000.0
        bh_y = black_hole.y if black_hole else world.camera_y + 1000000.0
        bh_mass = effective_mass(black_hole) if black_hole else 0.0
        event_radius = event_horizon_radius(black_hole) if black_hole else 1.0

        pygl.glMatrixMode(pygl.GL_PROJECTION)
        pygl.glPushMatrix()
        pygl.glLoadIdentity()
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        pygl.glPushMatrix()
        pygl.glLoadIdentity()
        pygl.glDisable(pygl.GL_BLEND)

        self.program.use()
        self._uniform2f(pygl, "u_resolution", world.width, world.height)
        self._uniform2f(pygl, "u_camera", world.camera_x, world.camera_y)
        self._uniform1f(pygl, "u_zoom", world.zoom)
        self._uniform2f(pygl, "u_blackHole", bh_x, bh_y)
        self._uniform1f(pygl, "u_blackHoleMass", bh_mass)
        self._uniform1f(pygl, "u_eventRadius", event_radius)
        self._uniform1f(pygl, "u_lensPower", world.lens_power if world.show_light else 0.0)
        self._uniform1f(pygl, "u_showGrid", 1.0 if world.show_grid else 0.0)
        self._uniform1f(pygl, "u_gridStep", float(world.render_profile()["grid_line_step"]))
        self._uniform1f(pygl, "u_gridAlpha", float(world.render_profile()["grid_alpha"]))
        self._uniform_warp_bodies(pygl, world)
        self._uniform1f(pygl, "u_time", elapsed)

        pygl.glBegin(pygl.GL_QUADS)
        pygl.glTexCoord2f(0.0, 0.0)
        pygl.glVertex2f(-1.0, -1.0)
        pygl.glTexCoord2f(1.0, 0.0)
        pygl.glVertex2f(1.0, -1.0)
        pygl.glTexCoord2f(1.0, 1.0)
        pygl.glVertex2f(1.0, 1.0)
        pygl.glTexCoord2f(0.0, 1.0)
        pygl.glVertex2f(-1.0, 1.0)
        pygl.glEnd()

        pygl.glUseProgram(0)
        pygl.glEnable(pygl.GL_BLEND)
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        pygl.glPopMatrix()
        pygl.glMatrixMode(pygl.GL_PROJECTION)
        pygl.glPopMatrix()
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        return True

    def _uniform1f(self, pygl, name: str, value: float) -> None:
        if self.program.program is None:
            return
        location = pygl.glGetUniformLocation(self.program.program, name)
        if location != -1:
            pygl.glUniform1f(location, float(value))

    def _uniform2f(self, pygl, name: str, x: float, y: float) -> None:
        if self.program.program is None:
            return
        location = pygl.glGetUniformLocation(self.program.program, name)
        if location != -1:
            pygl.glUniform2f(location, float(x), float(y))

    def _uniform_warp_bodies(self, pygl, world: GpuStarSystem) -> None:
        if self.program.program is None:
            return
        half_width = world.width / (2 * world.zoom)
        half_height = world.height / (2 * world.zoom)
        influence = max(600.0, max(half_width, half_height) * 1.35)
        candidates = []
        for body in world.bodies:
            dx = body.x - world.camera_x
            dy = body.y - world.camera_y
            if abs(dx) > half_width + influence or abs(dy) > half_height + influence:
                continue
            pressure = max(effective_mass(body), body.radius * body.radius * 12)
            candidates.append((pressure, body))
        candidates.sort(key=lambda item: item[0], reverse=True)
        bodies = [body for _pressure, body in candidates[:32]]

        count_location = pygl.glGetUniformLocation(self.program.program, "u_warpCount")
        if count_location != -1:
            pygl.glUniform1i(count_location, len(bodies))

        for index, body in enumerate(bodies):
            position_location = pygl.glGetUniformLocation(self.program.program, f"u_warpPositions[{index}]")
            mass_location = pygl.glGetUniformLocation(self.program.program, f"u_warpMasses[{index}]")
            radius_location = pygl.glGetUniformLocation(self.program.program, f"u_warpRadii[{index}]")
            if position_location != -1:
                pygl.glUniform2f(position_location, float(body.x), float(body.y))
            if mass_location != -1:
                pygl.glUniform1f(mass_location, float(effective_mass(body)))
            if radius_location != -1:
                pygl.glUniform1f(radius_location, float(body.radius))


class ExplosionGpuEffects:
    def __init__(self) -> None:
        self.program = ShaderProgram("fullscreen.vert", "explosion_fragment.frag")
        self.ready = False
        self.failed = False
        self.error = ""

    def ensure_ready(self) -> bool:
        if self.ready:
            return True
        if self.failed:
            return False
        try:
            self.program.compile()
        except (ShaderSourceError, RuntimeError) as exc:
            self.failed = True
            self.error = str(exc)
            return False
        self.ready = True
        return True

    def draw(self, gl: GL, world: GpuStarSystem) -> bool:
        if not world.explosions or not self.ensure_ready():
            return False
        pygl = gl.lib
        pygl.glMatrixMode(pygl.GL_PROJECTION)
        pygl.glPushMatrix()
        pygl.glLoadIdentity()
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        pygl.glPushMatrix()
        pygl.glLoadIdentity()
        pygl.glEnable(pygl.GL_BLEND)
        pygl.glBlendFunc(pygl.GL_SRC_ALPHA, pygl.GL_ONE)
        self.program.use()
        self._uniform2f(pygl, "u_resolution", world.width, world.height)
        self._uniform1f(pygl, "u_active", 1.0)
        self._uniform1f(pygl, "u_worldScale", world.zoom / max(world.height, 1))

        for flash in world.explosions:
            center = self._world_to_uv(world, flash.x, flash.y)
            if center is None:
                continue
            self._uniform2f(pygl, "u_center", center[0], center[1])
            self._uniform1f(pygl, "u_time", flash.age / max(flash.life, 1))
            self._uniform1f(pygl, "u_strength", min(2.2, flash.strength / 140.0))
            self._uniform1f(pygl, "u_angle", -flash.angle)
            self._uniform3f(pygl, "u_color", flash.color[0], flash.color[1], flash.color[2])
            self._quad(pygl)

        pygl.glUseProgram(0)
        pygl.glBlendFunc(pygl.GL_SRC_ALPHA, pygl.GL_ONE_MINUS_SRC_ALPHA)
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        pygl.glPopMatrix()
        pygl.glMatrixMode(pygl.GL_PROJECTION)
        pygl.glPopMatrix()
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        return True

    def _world_to_uv(self, world: GpuStarSystem, x: float, y: float) -> tuple[float, float] | None:
        sx = (x - world.camera_x) * world.zoom + world.width / 2
        sy = world.height / 2 - (y - world.camera_y) * world.zoom
        margin = 220
        if sx < -margin or sx > world.width + margin or sy < -margin or sy > world.height + margin:
            return None
        return sx / max(world.width, 1), sy / max(world.height, 1)

    def _quad(self, pygl) -> None:
        pygl.glBegin(pygl.GL_QUADS)
        pygl.glTexCoord2f(0.0, 0.0)
        pygl.glVertex2f(-1.0, -1.0)
        pygl.glTexCoord2f(1.0, 0.0)
        pygl.glVertex2f(1.0, -1.0)
        pygl.glTexCoord2f(1.0, 1.0)
        pygl.glVertex2f(1.0, 1.0)
        pygl.glTexCoord2f(0.0, 1.0)
        pygl.glVertex2f(-1.0, 1.0)
        pygl.glEnd()

    def _uniform1f(self, pygl, name: str, value: float) -> None:
        if self.program.program is None:
            return
        location = pygl.glGetUniformLocation(self.program.program, name)
        if location != -1:
            pygl.glUniform1f(location, float(value))

    def _uniform2f(self, pygl, name: str, x: float, y: float) -> None:
        if self.program.program is None:
            return
        location = pygl.glGetUniformLocation(self.program.program, name)
        if location != -1:
            pygl.glUniform2f(location, float(x), float(y))

    def _uniform3f(self, pygl, name: str, x: float, y: float, z: float) -> None:
        if self.program.program is None:
            return
        location = pygl.glGetUniformLocation(self.program.program, name)
        if location != -1:
            pygl.glUniform3f(location, float(x), float(y), float(z))


class GlTextCache:
    def __init__(self, pygame_module) -> None:
        self.pygame = pygame_module
        self.fonts: dict[int, object] = {}
        self.textures: dict[tuple[str, int, tuple[int, int, int]], tuple[int, int, int]] = {}
        self.font_path = self._find_korean_font()

    def _find_korean_font(self) -> str | None:
        for name in ("malgungothic", "malgun gothic", "맑은 고딕", "gulim", "dotum"):
            path = self.pygame.font.match_font(name)
            if path:
                return path
        windows_root = os.environ.get("WINDIR") or Path.cwd().anchor or "."
        windows_font = Path(windows_root) / "Fonts" / "malgun.ttf"
        if windows_font.exists():
            return str(windows_font)
        return None

    def font(self, size: int):
        if size not in self.fonts:
            if self.font_path:
                self.fonts[size] = self.pygame.font.Font(self.font_path, size)
            else:
                self.fonts[size] = self.pygame.font.SysFont("arialunicodems", size)
        return self.fonts[size]

    def texture(self, pygl, text: str, size: int, color: tuple[int, int, int]) -> tuple[int, int, int]:
        key = (text, size, color)
        if key in self.textures:
            return self.textures[key]
        surface = self.font(size).render(text, True, color)
        width, height = surface.get_size()
        pixels = self.pygame.image.tostring(surface, "RGBA", True)
        texture_id = pygl.glGenTextures(1)
        pygl.glBindTexture(pygl.GL_TEXTURE_2D, texture_id)
        pygl.glTexParameteri(pygl.GL_TEXTURE_2D, pygl.GL_TEXTURE_MIN_FILTER, pygl.GL_LINEAR)
        pygl.glTexParameteri(pygl.GL_TEXTURE_2D, pygl.GL_TEXTURE_MAG_FILTER, pygl.GL_LINEAR)
        pygl.glTexImage2D(pygl.GL_TEXTURE_2D, 0, pygl.GL_RGBA, width, height, 0, pygl.GL_RGBA, pygl.GL_UNSIGNED_BYTE, pixels)
        self.textures[key] = (texture_id, width, height)
        return self.textures[key]

    def draw(self, pygl, text: str, x: float, y: float, size: int = 14, color: tuple[int, int, int] = (237, 242, 247)) -> None:
        texture_id, width, height = self.texture(pygl, text, size, color)
        pygl.glEnable(pygl.GL_TEXTURE_2D)
        pygl.glBindTexture(pygl.GL_TEXTURE_2D, texture_id)
        pygl.glColor4f(1.0, 1.0, 1.0, 1.0)
        pygl.glBegin(pygl.GL_QUADS)
        pygl.glTexCoord2f(0.0, 1.0)
        pygl.glVertex2f(x, y)
        pygl.glTexCoord2f(1.0, 1.0)
        pygl.glVertex2f(x + width, y)
        pygl.glTexCoord2f(1.0, 0.0)
        pygl.glVertex2f(x + width, y + height)
        pygl.glTexCoord2f(0.0, 0.0)
        pygl.glVertex2f(x, y + height)
        pygl.glEnd()
        pygl.glDisable(pygl.GL_TEXTURE_2D)


class PygameControlPanel:
    def __init__(self, pygame_module) -> None:
        self.pygame = pygame_module
        self.width = 268
        self.margin = 14
        self.drag_slider: str | None = None
        self.text = GlTextCache(pygame_module)
        self.buttons: list[tuple[float, float, float, float, str, object]] = []
        self.sliders: dict[str, tuple[float, float, float, float, float, float, object, object]] = {}

    def contains(self, world: GpuStarSystem, pos: tuple[int, int]) -> bool:
        x, y = pos
        panel_x = max(0, world.width - self.width - self.margin)
        return panel_x <= x <= world.width - self.margin and self.margin <= y <= world.height - self.margin

    def handle_event(self, event, world: GpuStarSystem) -> bool:
        if event.type == self.pygame.MOUSEBUTTONDOWN and event.button == 1 and self.contains(world, event.pos):
            x, y = event.pos
            for bx, by, bw, bh, _label, command in self.buttons:
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    command()
                    return True
            for key, (sx, sy, sw, _sh, start, end, _getter, setter) in self.sliders.items():
                if sx <= x <= sx + sw and sy - 8 <= y <= sy + 18:
                    self.drag_slider = key
                    self._set_slider_value(x, sx, sw, start, end, setter)
                    return True
            return True
        if event.type == self.pygame.MOUSEMOTION and self.drag_slider:
            slider = self.sliders.get(self.drag_slider)
            if slider:
                sx, _sy, sw, _sh, start, end, _getter, setter = slider
                self._set_slider_value(event.pos[0], sx, sw, start, end, setter)
            return True
        if event.type == self.pygame.MOUSEBUTTONUP and event.button == 1 and self.drag_slider:
            self.drag_slider = None
            return True
        if event.type in (self.pygame.MOUSEBUTTONDOWN, self.pygame.MOUSEBUTTONUP) and hasattr(event, "pos"):
            return self.contains(world, event.pos)
        if event.type == self.pygame.MOUSEWHEEL:
            return self.contains(world, self.pygame.mouse.get_pos())
        return False

    def draw(self, gl: GL, world: GpuStarSystem) -> None:
        pygl = gl.lib
        self.buttons = []
        self.sliders = {}
        pygl.glMatrixMode(pygl.GL_PROJECTION)
        pygl.glPushMatrix()
        pygl.glLoadIdentity()
        pygl.glOrtho(0, world.width, world.height, 0, -1, 1)
        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        pygl.glPushMatrix()
        pygl.glLoadIdentity()
        pygl.glEnable(pygl.GL_BLEND)
        pygl.glBlendFunc(pygl.GL_SRC_ALPHA, pygl.GL_ONE_MINUS_SRC_ALPHA)

        x = max(0, world.width - self.width - self.margin)
        y = self.margin
        height = min(world.height - self.margin * 2, 692)
        self._rect(pygl, x, y, self.width, height, (0.05, 0.07, 0.10), 0.90)
        self._rect(pygl, x, y, self.width, height, (0.15, 0.20, 0.26), 1.0, outline=True)
        y += 14
        self.text.draw(pygl, "항성계 조작", x + 14, y, 18)
        y += 30
        self.text.draw(pygl, f"{world.kind} | {len(world.bodies)}개 | {world.zoom:.2f}x", x + 14, y, 12, (145, 160, 180))
        y += 30

        y = self._button_row(pygl, world, x + 14, y, (("행성", lambda: world.set_kind("행성")), ("항성", lambda: world.set_kind("항성"))))
        y = self._button_row(pygl, world, x + 14, y, (("먼지", lambda: world.set_kind("먼지")), ("블랙홀", lambda: world.set_kind("블랙홀"))))
        y += 5
        y = self._button_row(pygl, world, x + 14, y, (("재생" if not world.running else "일시정지", lambda: setattr(world, "running", not world.running)), ("초기화", world.reset)))
        y = self._button_row(pygl, world, x + 14, y, (("랜덤 궤도", world.seed_orbits), ("행성 추가", world.spawn_planet)))
        y = self._button_row(pygl, world, x + 14, y, (("격자 끄기" if world.show_grid else "격자 켜기", lambda: setattr(world, "show_grid", not world.show_grid)), ("빛 끄기" if world.show_light else "빛 켜기", lambda: setattr(world, "show_light", not world.show_light))))
        y += 7

        y = self._slider(pygl, world, x + 14, y, "질량", 1, 8000, lambda: world.mass if world.mass > 0 else 1, lambda value: self._set_mass(world, value))
        y = self._slider(pygl, world, x + 14, y, "힘", 0.2, 5.0, lambda: world.force, lambda value: setattr(world, "force", value))
        y = self._slider(pygl, world, x + 14, y, "중력", 0.0, 0.1, lambda: world.gravity, lambda value: setattr(world, "gravity", value))
        y = self._slider(pygl, world, x + 14, y, "빛", 0.0, 1.4, lambda: world.light_power, lambda value: setattr(world, "light_power", value))
        y = self._slider(pygl, world, x + 14, y, "렌즈", 0.0, 1.2, lambda: world.lens_power, lambda value: setattr(world, "lens_power", value))
        y = self._slider(pygl, world, x + 14, y, "노출", 0.35, 2.2, lambda: world.exposure, lambda value: setattr(world, "exposure", value))
        y = self._slider(pygl, world, x + 14, y, "새 항성 K", 2500, 12000, lambda: world.star_temperature, lambda value: self._set_star_temperature(world, value))
        y += 4
        self.text.draw(pygl, f"이벤트: {world.last_event[:22]}", x + 14, y, 12, (45, 212, 191))

        pygl.glMatrixMode(pygl.GL_MODELVIEW)
        pygl.glPopMatrix()
        pygl.glMatrixMode(pygl.GL_PROJECTION)
        pygl.glPopMatrix()
        pygl.glMatrixMode(pygl.GL_MODELVIEW)

    def _button_row(self, pygl, world: GpuStarSystem, x: float, y: float, items) -> float:
        gap = 8
        width = (self.width - 28 - gap) / 2
        for index, (label, command) in enumerate(items):
            bx = x + index * (width + gap)
            active = label.startswith(world.kind) or (label.startswith("격자") and world.show_grid) or (label.startswith("빛") and world.show_light)
            self._button(pygl, bx, y, width, 30, label, command, active)
        return y + 38

    def _button(self, pygl, x: float, y: float, w: float, h: float, label: str, command, active: bool = False) -> None:
        fill = (0.07, 0.22, 0.20) if active else (0.08, 0.12, 0.17)
        border = (0.17, 0.83, 0.75) if active else (0.15, 0.20, 0.26)
        self._rect(pygl, x, y, w, h, fill, 0.95)
        self._rect(pygl, x, y, w, h, border, 1.0, outline=True)
        self.text.draw(pygl, label, x + 10, y + 8, 12, (237, 242, 247))
        self.buttons.append((x, y, w, h, label, command))

    def _slider(self, pygl, world: GpuStarSystem, x: float, y: float, label: str, start: float, end: float, getter, setter) -> float:
        value = max(start, min(end, float(getter())))
        track_y = y + 28
        track_w = self.width - 28
        amount = (value - start) / max(end - start, 0.0001)
        self.text.draw(pygl, f"{label} {value:.2f}" if end <= 10 else f"{label} {value:.0f}", x, y, 12, (145, 160, 180))
        self._rect(pygl, x, track_y, track_w, 4, (0.10, 0.14, 0.20), 1.0)
        self._rect(pygl, x, track_y, track_w * amount, 4, (0.17, 0.83, 0.75), 1.0)
        knob_x = x + track_w * amount
        self._rect(pygl, knob_x - 4, track_y - 5, 8, 14, (0.88, 0.98, 0.96), 1.0)
        self.sliders[label] = (x, track_y, track_w, 14, start, end, getter, setter)
        return y + 48

    def _set_slider_value(self, mouse_x: float, x: float, width: float, start: float, end: float, setter) -> None:
        amount = max(0.0, min(1.0, (mouse_x - x) / max(width, 1)))
        setter(start + (end - start) * amount)

    def _set_mass(self, world: GpuStarSystem, value: float) -> None:
        if world.kind != "블랙홀":
            world.mass = value

    def _set_star_temperature(self, world: GpuStarSystem, value: float) -> None:
        world.star_temperature = value
        world.last_event = f"새 항성 온도 {value:.0f} K"

    def _rect(self, pygl, x: float, y: float, w: float, h: float, color: tuple[float, float, float], alpha: float, outline: bool = False) -> None:
        pygl.glColor4f(color[0], color[1], color[2], alpha)
        pygl.glLineWidth(1.0)
        pygl.glBegin(pygl.GL_LINE_LOOP if outline else pygl.GL_QUADS)
        pygl.glVertex2f(x, y)
        pygl.glVertex2f(x + w, y)
        pygl.glVertex2f(x + w, y + h)
        pygl.glVertex2f(x, y + h)
        pygl.glEnd()


def run_gpu_window() -> None:
    import pygame

    os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "40,80")
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    screen = pygame.display.set_mode((1100, 720), pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE)
    pygame.display.set_caption("seoul2line GPU Star System")
    gl = GL()
    gl.lib.glEnable(GL.GL_BLEND)
    gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    world = GpuStarSystem()
    gpu_effects = FullscreenGpuEffects()
    explosion_effects = ExplosionGpuEffects()
    control_panel = PygameControlPanel(pygame)
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                world.width, world.height = event.w, event.h
            elif control_panel.handle_event(event, world):
                continue
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    world.running = not world.running
                elif event.key == pygame.K_r:
                    world.reset()
                elif event.key == pygame.K_o:
                    world.seed_orbits()
                elif event.key == pygame.K_i:
                    world.spawn_planet()
                elif event.key == pygame.K_1:
                    world.set_kind("행성")
                elif event.key == pygame.K_2:
                    world.set_kind("항성")
                elif event.key == pygame.K_3:
                    world.set_kind("먼지")
                elif event.key == pygame.K_4:
                    world.set_kind("블랙홀")
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    world.force = min(5.0, world.force + 0.2)
                elif event.key == pygame.K_MINUS:
                    world.force = max(0.2, world.force - 0.2)
                elif event.key == pygame.K_RIGHTBRACKET and world.kind != "블랙홀":
                    world.mass = min(800, world.mass + 10)
                elif event.key == pygame.K_LEFTBRACKET and world.kind != "블랙홀":
                    world.mass = max(1, world.mass - 10)
                elif event.key == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
                    pygame.display.flip()
            elif event.type == pygame.MOUSEWHEEL:
                if pygame.key.get_focused():
                    x, y = pygame.mouse.get_pos()
                    world.zoom_at(x, y, 1.14 if event.y > 0 else 1 / 1.14)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 4:
                world.zoom_at(*event.pos, 1.14)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 5:
                world.zoom_at(*event.pos, 1 / 1.14)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                world.drag_start = world.screen_to_world(*event.pos)
                world.drag_now = world.drag_start
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                world.begin_pan(event.pos)
            elif event.type == pygame.MOUSEMOTION and world.drag_start:
                world.drag_now = world.screen_to_world(*event.pos)
            elif event.type == pygame.MOUSEMOTION and world.pan_start:
                world.update_pan(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and world.drag_start:
                world.spawn(world.drag_start, world.screen_to_world(*event.pos))
                world.drag_start = None
                world.drag_now = None
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                moved = world.end_pan()
                if not moved:
                    body = world.nearest_body(world.screen_to_world(*event.pos))
                    if body:
                        show_body_info(body)

        if world.running:
            world.step()
        elapsed = pygame.time.get_ticks() / 1000
        render(gl, world, gpu_effects, explosion_effects, elapsed)
        control_panel.draw(gl, world)
        pygame.display.flip()
        pygame.display.set_caption(f"seoul2line GPU Star System | {world.kind} zoom={world.zoom:.2f}x mass={world.mass:g} force={world.force:.1f} bodies={len(world.bodies)}")
        clock.tick(int(world.render_profile()["target_fps"]))
    pygame.quit()


def show_body_info(body: Body) -> None:
    def run() -> None:
        root = tk.Tk()
        root.title(f"천체 정보 - {body.name}")
        root.geometry("300x230")
        root.configure(bg="#0d1117")
        lines = (
            f"이름: {body.name}",
            f"종류: {body.kind}",
            f"질량: {body.mass:g}",
            f"유효 질량: {effective_mass(body):g}",
            f"반지름: {body.radius:.1f}",
            f"표면온도: {body.temperature:.0f} K" if body.kind == "항성" else "표면온도: -",
            f"광도: {body.luminosity:.0f}" if body.kind == "항성" else "광도: -",
            f"속도: {math.hypot(body.vx, body.vy):.2f}",
            f"위치: {body.x:.0f}, {body.y:.0f}",
        )
        tk.Label(root, text="\n".join(lines), justify="left", fg="#edf2f7", bg="#0d1117", font=("Consolas", 10)).pack(anchor="w", padx=16, pady=0)
        RoundedButton(root, text="정지", command=lambda:body.__setattr__("play",not body.play),colors=palette(dark_mode)).pack(anchor="w", padx=16, pady=16)
        tk.Button(root, text="닫기", command=root.destroy, relief="flat", bd=0, bg="#172331", fg="#edf2f7", padx=12, pady=8).pack(anchor="e", padx=16)
        root.mainloop()

    threading.Thread(target=run, daemon=True).start()


def render(
    gl: GL,
    world: GpuStarSystem,
    gpu_effects: FullscreenGpuEffects | None = None,
    explosion_effects: ExplosionGpuEffects | None = None,
    elapsed: float = 0.0,
) -> None:
    world.refresh_star_physics()
    half_width = world.width / (2 * world.zoom)
    half_height = world.height / (2 * world.zoom)
    gl.lib.glViewport(0, 0, world.width, world.height)
    gl.lib.glMatrixMode(GL.GL_PROJECTION)
    gl.lib.glLoadIdentity()
    gl.lib.glOrtho(world.camera_x - half_width, world.camera_x + half_width, world.camera_y + half_height, world.camera_y - half_height, -1, 1)
    gl.lib.glMatrixMode(GL.GL_MODELVIEW)
    gl.lib.glLoadIdentity()
    gl.lib.glClearColor(0.027, 0.043, 0.075, 1.0)
    gl.lib.glClear(GL.GL_COLOR_BUFFER_BIT)
    used_gpu_background = gpu_effects.draw(gl, world, elapsed) if gpu_effects else False
    gl.lib.glMatrixMode(GL.GL_PROJECTION)
    gl.lib.glLoadIdentity()
    gl.lib.glOrtho(world.camera_x - half_width, world.camera_x + half_width, world.camera_y + half_height, world.camera_y - half_height, -1, 1)
    gl.lib.glMatrixMode(GL.GL_MODELVIEW)
    gl.lib.glLoadIdentity()
    if not used_gpu_background:
        draw_starfield(gl, world)
    if world.show_grid and not used_gpu_background:
        draw_grid(gl, world)
    if world.show_light:
        gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)
        if not used_gpu_background:
            draw_black_hole_photon_effects(gl, world)
        for star in stars(world):
            draw_star_glow(gl, star, world)
        gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    for body in world.bodies:
        if len(body.trail) > 1:
            draw_polyline(gl, body.trail, body.color, 0.42)
        if body.kind == "블랙홀":
            if world.show_light:
                draw_accretion_disk(gl, body, world)
            draw_circle(gl, body.x, body.y, body.radius, body.color, 1)
        elif body.kind == "항성":
            star_color = tone_map_color(multiply_color(body.color, 2.8 * world.light_power), world.exposure)
            draw_circle(gl, body.x, body.y, body.radius * 1.18, tone_map_color(multiply_color(body.color, 1.5), world.exposure), 0.32)
            draw_circle(gl, body.x, body.y, body.radius, star_color, 1)
        else:
            draw_lit_body(gl, body, world)
    used_gpu_explosions = explosion_effects.draw(gl, world) if explosion_effects else False
    if world.explosions and not used_gpu_explosions:
        gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)
        for flash in world.explosions:
            draw_explosion_flash(gl, flash, world)
        gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    if world.drag_start and world.drag_now:
        draw_polyline(gl, [world.drag_now, world.drag_start], hex_color("#2dd4bf"), 1.0, 2.0)


def draw_starfield(gl: GL, world: GpuStarSystem) -> None:
    half_width = world.width / (2 * world.zoom)
    half_height = world.height / (2 * world.zoom)
    left = world.camera_x - half_width
    right = world.camera_x + half_width
    top = world.camera_y - half_height
    bottom = world.camera_y + half_height
    cell = 180
    start_x = math.floor(left / cell) - 1
    end_x = math.floor(right / cell) + 1
    start_y = math.floor(top / cell) - 1
    end_y = math.floor(bottom / cell) + 1
    gl.lib.glBegin(GL.GL_POINTS)
    for gx in range(start_x, end_x + 1):
        for gy in range(start_y, end_y + 1):
            seed = hash_pair(gx, gy)
            if seed % 100 < 46:
                x = gx * cell + ((seed >> 8) % cell)
                y = gy * cell + ((seed >> 16) % cell)
                brightness = 0.22 + ((seed >> 24) % 100) / 220
                gl.color(tone_map_color((brightness, brightness * 1.04, brightness * 1.18), world.exposure), 0.82)
                gl.vertex(x, y)
    gl.lib.glEnd()


def draw_grid(gl: GL, world: GpuStarSystem) -> None:
    profile = world.render_profile()
    line_step = int(profile["grid_line_step"])
    sample_step = int(profile["grid_sample_step"])
    alpha = float(profile["grid_alpha"])
    half_width = world.width / (2 * world.zoom)
    half_height = world.height / (2 * world.zoom)
    left = world.camera_x - half_width - line_step * 2
    right = world.camera_x + half_width + line_step * 2
    top = world.camera_y - half_height - line_step * 2
    bottom = world.camera_y + half_height + line_step * 2
    first_x = math.floor(left / line_step) * line_step
    first_y = math.floor(top / line_step) * line_step
    gl.lib.glLineWidth(1)
    x = first_x
    while x <= right:
        gl.color(hex_color("#122033"), alpha)
        gl.lib.glBegin(GL.GL_LINE_STRIP)
        y = math.floor(top / sample_step) * sample_step
        while y <= bottom:
            gl.vertex(*world.warp_point(x, y))
            y += sample_step
        gl.lib.glEnd()
        x += line_step
    y = first_y
    while y <= bottom:
        gl.color(hex_color("#122033"), alpha)
        gl.lib.glBegin(GL.GL_LINE_STRIP)
        x = math.floor(left / sample_step) * sample_step
        while x <= right:
            gl.vertex(*world.warp_point(x, y))
            x += sample_step
        gl.lib.glEnd()
        y += line_step


def draw_star_glow(gl: GL, body: Body, world: GpuStarSystem) -> None:
    if world.light_power <= 0:
        return
    glow_scale = min(2.4, max(0.7, math.sqrt(max(body.luminosity, 1) / STAR_MASS)))
    glow = (
        (body.radius * 11.0 * glow_scale, 0.018),
        (body.radius * 7.2 * glow_scale, 0.032),
        (body.radius * 4.6 * glow_scale, 0.055),
        (body.radius * 2.6 * glow_scale, 0.095),
        (body.radius * 1.5 * glow_scale, 0.16),
    )
    for radius, alpha in glow[-int(world.render_profile()["glow_layers"]):]:
        hdr_color = tone_map_color(multiply_color(body.color, 1.0 + body.luminosity / 4200), world.exposure)
        draw_radial_disc(gl, body.x, body.y, radius, hdr_color, alpha * world.light_power, int(world.render_profile()["radial_steps"]))


def draw_black_hole_photon_effects(gl: GL, world: GpuStarSystem) -> None:
    if world.lens_power <= 0:
        return
    profile = world.render_profile()
    ray_count = int(profile["photon_rays"])
    ray_steps = int(profile["ray_steps"])
    black_holes = [body for body in world.bodies if body.kind == "블랙홀"]
    for black_hole in black_holes:
        for star in stars(world):
            distance = math.hypot(star.x - black_hole.x, star.y - black_hole.y)
            if distance < 60:
                continue
            alpha = min(0.22, 280 / distance) * world.lens_power
            for index in range(ray_count):
                offset = (index - (ray_count - 1) / 2) * black_hole.radius * 0.82
                points = bent_photon_path(star, black_hole, offset, ray_steps)
                if len(points) > 1:
                    draw_polyline(gl, points, tone_map_color(multiply_color(star.color, 1.7), world.exposure), alpha / max(1, abs(index - ray_count / 2) + 1), 0.9)


def bent_photon_path(star: Body, black_hole: Body, offset: float, steps: int) -> list[tuple[float, float]]:
    dx = black_hole.x - star.x
    dy = black_hole.y - star.y
    distance = math.hypot(dx, dy)
    if distance <= 1:
        return []
    ux = dx / distance
    uy = dy / distance
    px = -uy
    py = ux
    start = 0.12
    end = 1.16
    points = []
    influence = min(90, schwarzschild_radius(black_hole) * 1.4)
    for step in range(steps):
        t = start + (end - start) * step / max(steps - 1, 1)
        bend = math.sin(t * math.pi) * influence * (1 if offset >= 0 else -1) / max(abs(offset) + black_hole.radius * 0.55, 1)
        x = star.x + dx * t + px * (offset + bend)
        y = star.y + dy * t + py * (offset + bend)
        if math.hypot(x - black_hole.x, y - black_hole.y) <= event_horizon_radius(black_hole):
            break
        points.append((x, y))
    return points


def draw_accretion_disk(gl: GL, black_hole: Body, world: GpuStarSystem) -> None:
    if world.lens_power <= 0:
        return
    inner = event_horizon_radius(black_hole) * 1.7
    outer = black_hole.radius * 4.8
    steps = int(world.render_profile()["ellipse_steps"])
    for layer, radius in enumerate((outer, (outer + inner) * 0.55, inner)):
        temperature = 8500 - layer * 2200
        color = tone_map_color(multiply_color(blackbody_color(temperature), 1.6 - layer * 0.32), world.exposure)
        alpha = (0.18 - layer * 0.035) * world.lens_power
        draw_ellipse_arc(gl, black_hole.x, black_hole.y, radius, radius * 0.28, 0.28, color, alpha, 1.15, steps)


def draw_lit_body(gl: GL, body: Body, world: GpuStarSystem) -> None:
    star = strongest_star(body, world)
    if not world.show_light or star is None:
        draw_circle(gl, body.x, body.y, body.radius, scale_color(body.color, 0.14), 1)
        return
    dx = star.x - body.x
    dy = star.y - body.y
    distance = max(1, math.hypot(dx, dy))
    intensity = light_intensity(star, distance) * world.light_power
    nx = dx / distance
    ny = dy / distance
    base = tone_map_color(multiply_color(body.color, 0.18 + intensity * 0.32), world.exposure)
    lit = tone_map_color(multiply_color(lighten(body.color, 0.34), 0.28 + intensity * 0.85), world.exposure)
    rim = mix_color(star.color, body.color, 0.35)
    draw_circle(gl, body.x, body.y, body.radius, base, 1)
    gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)
    profile = world.render_profile()
    draw_radial_disc(gl, body.x + nx * body.radius * 0.42, body.y + ny * body.radius * 0.42, body.radius * 0.96, lit, min(0.55, 0.18 + intensity * 0.38), int(profile["radial_steps"]))
    draw_polyline(gl, crescent_points(body.x, body.y, body.radius * 1.02, math.atan2(ny, nx), int(profile["crescent_steps"])), rim, min(0.45, 0.1 + intensity * 0.22), 1.2)
    if body.atmosphere:
        draw_atmosphere(gl, body, star, world, intensity, math.atan2(ny, nx))
    gl.lib.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)


def draw_atmosphere(gl: GL, body: Body, star: Body, world: GpuStarSystem, intensity: float, light_angle: float) -> None:
    rayleigh = mix_color(star.color, hex_color("#38bdf8"), 0.76)
    mie = mix_color(star.color, hex_color("#fde68a"), 0.38)
    atmosphere = tone_map_color(multiply_color(rayleigh, 0.5 + intensity), world.exposure)
    sunset = tone_map_color(multiply_color(mie, 0.28 + intensity * 0.7), world.exposure)
    draw_circle(gl, body.x, body.y, body.radius * 1.22, atmosphere, min(0.18, 0.04 + intensity * 0.1), outline=True)
    draw_polyline(gl, crescent_points(body.x, body.y, body.radius * 1.27, light_angle + math.pi, int(world.render_profile()["crescent_steps"])), sunset, min(0.2, 0.05 + intensity * 0.08), 1.0)


def strongest_star(body: Body, world: GpuStarSystem) -> Body | None:
    candidates = [star for star in stars(world) if star is not body]
    if not candidates:
        return None
    return max(candidates, key=lambda star: raw_light_intensity(star, max(1, math.hypot(star.x - body.x, star.y - body.y))))


def light_intensity(star: Body, distance: float) -> float:
    return min(1.0, raw_light_intensity(star, distance))


def raw_light_intensity(star: Body, distance: float) -> float:
    luminosity = star.luminosity or effective_mass(star)
    return luminosity / max(distance * distance, 1) * 0.07


def stars(world: GpuStarSystem) -> list[Body]:
    return [body for body in world.bodies if body.kind == "항성"]


def lit_color(body: Body, world: GpuStarSystem) -> tuple[float, float, float]:
    if not world.show_light:
        return body.color
    star_bodies = stars(world)
    if not star_bodies:
        factor = 0.12
    else:
        factor = 0.18
        for star in star_bodies:
            distance = max(60, math.hypot(body.x - star.x, body.y - star.y))
            factor += min(0.95, effective_mass(star) / (distance * distance) * 0.035)
        factor = min(1.18, factor)
    return tuple(min(1, component * factor) for component in body.color)


def draw_polyline(gl: GL, points: list[tuple[float, float]], color: tuple[float, float, float], alpha: float, width: float = 1.0) -> None:
    gl.lib.glLineWidth(width)
    gl.color(color, alpha)
    gl.lib.glBegin(GL.GL_LINE_STRIP)
    for x, y in points:
        gl.vertex(x, y)
    gl.lib.glEnd()


def draw_circle(gl: GL, x: float, y: float, radius: float, color: tuple[float, float, float], alpha: float, outline: bool = False) -> None:
    gl.color(color, alpha)
    gl.lib.glLineWidth(2)
    gl.lib.glBegin(GL.GL_LINE_STRIP if outline else GL.GL_TRIANGLE_FAN)
    if not outline:
        gl.vertex(x, y)
    steps = 32
    for index in range(steps + 1):
        angle = math.tau * index / steps
        gl.vertex(x + math.cos(angle) * radius, y + math.sin(angle) * radius)
    gl.lib.glEnd()


def draw_ellipse_arc(
    gl: GL,
    x: float,
    y: float,
    rx: float,
    ry: float,
    rotation: float,
    color: tuple[float, float, float],
    alpha: float,
    width: float,
    steps: int = 80,
) -> None:
    gl.lib.glLineWidth(width)
    gl.color(color, alpha)
    gl.lib.glBegin(GL.GL_LINE_STRIP)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    for index in range(steps):
        angle = math.tau * index / max(steps - 1, 1)
        px = math.cos(angle) * rx
        py = math.sin(angle) * ry
        gl.vertex(x + px * cos_r - py * sin_r, y + px * sin_r + py * cos_r)
    gl.lib.glEnd()


def crescent_points(x: float, y: float, radius: float, light_angle: float, steps: int = 26) -> list[tuple[float, float]]:
    points = []
    side_angle = light_angle + math.pi / 2
    for index in range(steps):
        t = -1.05 + 2.1 * index / max(steps - 1, 1)
        angle = side_angle + t
        points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius))
    return points


def draw_radial_disc(gl: GL, x: float, y: float, radius: float, color: tuple[float, float, float], alpha: float, steps: int = 56) -> None:
    inner = lighten(color, 0.35)
    gl.lib.glBegin(GL.GL_TRIANGLE_FAN)
    gl.color(inner, alpha)
    gl.vertex(x, y)
    for index in range(steps + 1):
        angle = math.tau * index / steps
        edge_alpha = alpha * 0.06
        gl.color(color, edge_alpha)
        gl.vertex(x + math.cos(angle) * radius, y + math.sin(angle) * radius)
    gl.lib.glEnd()


def draw_explosion_flash(gl: GL, flash: ExplosionFlash, world: GpuStarSystem) -> None:
    t = flash.age / max(flash.life, 1)
    if t >= 1.0:
        return
    expansion = t ** 0.55
    fade = max(0.0, 1.0 - t)
    flicker = 0.92 + math.sin(t * 55.0) * 0.06 + math.sin(t * 91.0) * 0.03

    base_radius = 6.0 + flash.strength * 0.045
    outer_radius = base_radius * (0.85 + expansion * 2.35)
    mid_radius = base_radius * (0.55 + expansion * 1.45)
    core_radius = base_radius * (0.20 + (1.0 - t) * 0.65)
    ring_radius = base_radius * (0.95 + expansion * 3.3)

    red = tone_map_color((4.8, 0.18, 0.05), world.exposure)
    orange = tone_map_color((5.2, 1.1, 0.08), world.exposure)
    yellow = tone_map_color((6.0, 3.2, 0.28), world.exposure)
    white = tone_map_color((8.4, 7.8, 6.6), world.exposure)

    draw_radial_disc(gl, flash.x, flash.y, outer_radius, red, min(0.42, (0.15 + fade * 0.24) * flicker), 40)
    draw_radial_disc(gl, flash.x, flash.y, mid_radius, orange, min(0.52, (0.22 + fade * 0.24) * flicker), 40)
    draw_radial_disc(gl, flash.x, flash.y, mid_radius * 0.72, yellow, min(0.75, (0.25 + fade * 0.32) * flicker), 40)
    draw_radial_disc(gl, flash.x, flash.y, core_radius, white, min(0.98, (0.38 + (1.0 - t) * 0.62) * flicker), 40)

    ring_alpha = max(0.0, 0.55 - t * 0.45) * flicker
    if ring_alpha > 0:
        draw_circle(gl, flash.x, flash.y, ring_radius, yellow, ring_alpha, outline=True)
        draw_circle(gl, flash.x, flash.y, ring_radius * 1.08, red, ring_alpha * 0.45, outline=True)


def make_star(x: float, y: float, vx: float, vy: float, mass: float, radius: float, name: str, temperature: float) -> Body:
    color = blackbody_color(temperature)
    luminosity = stellar_luminosity(mass, temperature, radius)
    return Body(x, y, vx, vy, mass, radius, color, name, "항성", temperature=temperature, luminosity=luminosity)


def stellar_luminosity(mass: float, temperature: float, radius: float) -> float:
    radius_scale = max(radius, 1) / 24
    temperature_scale = max(2500, min(12000, temperature)) / 5800
    return max(800, mass * radius_scale * radius_scale * temperature_scale ** 4)


def blackbody_color(temperature: float) -> tuple[float, float, float]:
    key = int(round(max(2500, min(12000, temperature)) / 100) * 100)
    if key not in BLACKBODY_LUT:
        BLACKBODY_LUT[key] = _blackbody_color_uncached(key)
    return BLACKBODY_LUT[key]


def _blackbody_color_uncached(temperature: float) -> tuple[float, float, float]:
    temp = temperature / 100
    if temp <= 66:
        red = 255
        green = 99.4708025861 * math.log(temp) - 161.1195681661
        blue = 0 if temp <= 19 else 138.5177312231 * math.log(temp - 10) - 305.0447927307
    else:
        red = 329.698727446 * ((temp - 60) ** -0.1332047592)
        green = 288.1221695283 * ((temp - 60) ** -0.0755148492)
        blue = 255
    return tuple(max(0, min(255, value)) / 255 for value in (red, green, blue))


def multiply_color(color: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return tuple(component * factor for component in color)


def tone_map_color(color: tuple[float, float, float], exposure: float = 1.0) -> tuple[float, float, float]:
    return tuple(aces_channel(component * exposure) for component in color)


def aces_channel(value: float) -> float:
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14
    mapped = (value * (a * value + b)) / (value * (c * value + d) + e)
    return max(0.0, min(1.0, mapped))


def schwarzschild_radius(black_hole: Body) -> float:
    return max(black_hole.radius * 0.9, math.sqrt(effective_mass(black_hole)) * 0.08)


def event_horizon_radius(black_hole: Body) -> float:
    return max(black_hole.radius * 0.92, schwarzschild_radius(black_hole))


def photon_sphere_radius(black_hole: Body) -> float:
    return event_horizon_radius(black_hole) * 1.5


def hash_pair(x: int, y: int) -> int:
    value = (x * 73856093) ^ (y * 19349663)
    value ^= value >> 13
    value *= 1274126177
    return value & 0xFFFFFFFF


def effective_mass(body: Body) -> float:
    if body.kind == "블랙홀" or body.mass == -1:
        return BLACK_HOLE_EFFECTIVE_MASS
    return max(body.mass, 1)


def orbit_speed(center_mass: float, distance: float) -> float:
    return math.sqrt(G * center_mass / max(distance, 1))


def hex_color(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return int(value[0:2], 16) / 255, int(value[2:4], 16) / 255, int(value[4:6], 16) / 255


def lighten(color: tuple[float, float, float], amount: float) -> tuple[float, float, float]:
    return tuple(min(1, component + (1 - component) * amount) for component in color)


def scale_color(color: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return tuple(min(1, component * factor) for component in color)


def mix_color(a: tuple[float, float, float], b: tuple[float, float, float], amount: float) -> tuple[float, float, float]:
    return tuple(a[i] * (1 - amount) + b[i] * amount for i in range(3))


PALETTE = tuple(hex_color(value) for value in ("#38bdf8", "#fb7185", "#a7f3d0", "#c084fc", "#fde68a"))
BLACKBODY_LUT = {temperature: _blackbody_color_uncached(temperature) for temperature in range(2500, 12100, 100)}


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return GpuStarSystemLauncher(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("minigame.starsystem_gpu", "항성계 시뮬레이터 (GPU)", "미니게임", build, 10))


if __name__ == "__main__":
    if "--run" in sys.argv:
        run_gpu_window()
    else:
        root = Path(__file__).resolve().parents[2]
        subprocess.Popen([sys.executable, "-m", "app.tools.chill_starsystem_gpu", "--run"], cwd=root)
