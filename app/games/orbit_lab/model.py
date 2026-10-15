from __future__ import annotations

from dataclasses import dataclass
import math


G = 1.0
BODY_COLORS = {"planet": "#70b7ef", "moon": "#c0c7d5", "ship": "#f8dc88"}
TIME_SCALES = (.25, 1.0, 5.0, 20.0, 100.0)
FUEL_MASS = .01
THRUST_FORCE = 60.0
FUEL_RATE = 1.0


def finite(value: float, lower: float, upper: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{label}: {lower:g}~{upper:g} 범위의 유한한 숫자를 입력하세요.")
    return float(value)


@dataclass
class Body:
    id: int
    name: str
    kind: str
    mass: float
    radius: float
    x: float
    y: float
    vx: float = 0
    vy: float = 0
    parent_id: int | None = None
    fuel: float = 0
    dry_mass: float = 1
    heading: float = 90
    throttle: float = 0


class OrbitSystem:
    def __init__(self) -> None:
        self.bodies: list[Body] = []
        self.next_id = 1
        self.selected_id: int | None = None
        self.notice = "천체를 선택하거나 행성·위성을 추가하세요."
        self.elapsed = 0.0
        self.physics_limited = False
        self.paused = False
        self.time_scale = 1.0
        self.effective_speed = 0.0
        planet = self.add_body("planet", "행성", 12000, 30, 0, 0)
        moon = self.add_moon(planet.id, "위성", 12, 8, 180, 0)
        # Balance the initial demonstration system's total momentum.
        planet.vy = -moon.mass * moon.vy / (planet.mass + moon.mass)
        moon.vy += planet.vy
        self.selected_id = planet.id

    @property
    def selected(self) -> Body | None:
        return next((body for body in self.bodies if body.id == self.selected_id), None)

    def body_at(self, x: float, y: float, tolerance: float = 0) -> Body | None:
        choices = [body for body in self.bodies if math.hypot(body.x - x, body.y - y) <= body.radius + tolerance]
        return min(choices, key=lambda body: math.hypot(body.x - x, body.y - y), default=None)

    def add_body(self, kind: str, name: str, mass: float, radius: float, x: float, y: float,
                 vx: float = 0, vy: float = 0, parent_id: int | None = None) -> Body:
        if kind not in BODY_COLORS or not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
            raise ValueError("천체 종류와 1~40자의 이름이 필요합니다.")
        if len(self.bodies) >= 64:
            raise ValueError("천체는 최대 64개까지 생성할 수 있습니다.")
        mass = finite(mass, .01, 1e8, "질량")
        radius = finite(radius, .5, 1000, "반지름")
        x, y = finite(x, -1e6, 1e6, "X 좌표"), finite(y, -1e6, 1e6, "Y 좌표")
        vx, vy = finite(vx, -1e5, 1e5, "X 속도"), finite(vy, -1e5, 1e5, "Y 속도")
        if any(math.hypot(body.x - x, body.y - y) <= body.radius + radius for body in self.bodies):
            raise ValueError("다른 천체와 겹치지 않는 위치에 배치하세요.")
        body = Body(self.next_id, name.strip(), kind, mass, radius, x, y, vx, vy, parent_id)
        self.next_id += 1
        self.bodies.append(body)
        self.selected_id = body.id
        return body

    def add_moon(self, parent_id: int, name: str, mass: float, radius: float, x: float, y: float) -> Body:
        parent = next((body for body in self.bodies if body.id == parent_id), None)
        if parent is None:
            raise ValueError("위성의 중심 천체를 먼저 선택하세요.")
        mass = finite(mass, .01, 1e8, "질량")
        radius = finite(radius, .5, 1000, "반지름")
        x, y = finite(x, -1e6, 1e6, "X 좌표"), finite(y, -1e6, 1e6, "Y 좌표")
        dx, dy = x - parent.x, y - parent.y
        distance = math.hypot(dx, dy)
        if distance <= parent.radius + radius:
            raise ValueError("위성은 중심 천체의 표면 밖에 배치하세요.")
        speed = math.sqrt(G * (parent.mass + mass) / distance)
        return self.add_body("moon", name, mass, radius, x, y,
                             parent.vx - dy / distance * speed, parent.vy + dx / distance * speed, parent.id)

    def set_mass(self, body_id: int, mass: float) -> None:
        value = finite(mass, .01, 1e8, "질량")
        body = next((body for body in self.bodies if body.id == body_id), None)
        if body is None:
            raise ValueError("질량을 바꿀 천체를 선택하세요.")
        if body.kind == "ship":
            raise ValueError("우주선 질량은 건조 질량과 남은 연료로 계산됩니다.")
        body.mass = value

    def launch_ship(self, parent_id: int, speed: float, heading: float, fuel: float = 100) -> Body:
        parent = next((body for body in self.bodies if body.id == parent_id and body.kind != "ship"), None)
        if parent is None:
            raise ValueError("발사할 행성 또는 위성을 먼저 선택하세요.")
        speed = finite(speed, 0, 500, "발사 속도")
        heading = finite(heading, -3600, 3600, "발사 방향") % 360
        fuel = finite(fuel, 0, 1000, "연료")
        angle = math.radians(heading)
        dx, dy = math.cos(angle), -math.sin(angle)
        distance = parent.radius + 4
        ship = self.add_body("ship", f"우주선 {self.next_id}", 1 + fuel * FUEL_MASS, 2,
                             parent.x + dx * distance, parent.y + dy * distance,
                             parent.vx + dx * speed, parent.vy + dy * speed, parent.id)
        ship.fuel, ship.heading = fuel, heading
        self.notice = "우주선 발사 · 추력과 방향을 조절하세요."
        return ship

    def set_throttle(self, value: float) -> None:
        value = finite(value, 0, 1, "추력 비율")
        if self.selected is None or self.selected.kind != "ship":
            raise ValueError("추력을 조절할 우주선을 선택하세요.")
        self.selected.throttle = value if self.selected.fuel > 0 else 0

    def rotate_ship(self, delta: float) -> None:
        delta = finite(delta, -3600, 3600, "회전 각도")
        if self.selected is None or self.selected.kind != "ship":
            raise ValueError("회전할 우주선을 선택하세요.")
        self.selected.heading = (self.selected.heading + delta) % 360

    def thrust_for_step(self, step: float) -> dict[int, tuple[float, float]]:
        forces = {}
        for ship in self.bodies:
            if ship.kind != "ship" or ship.throttle <= 0 or ship.fuel <= 0:
                continue
            burned = min(ship.fuel, FUEL_RATE * ship.throttle * step)
            mass_midpoint = ship.dry_mass + (ship.fuel - burned / 2) * FUEL_MASS
            acceleration = THRUST_FORCE * burned / (FUEL_RATE * step) / mass_midpoint
            angle = math.radians(ship.heading)
            forces[ship.id] = (acceleration * math.cos(angle), -acceleration * math.sin(angle))
            ship.fuel = max(0, ship.fuel - burned)
            ship.mass = ship.dry_mass + ship.fuel * FUEL_MASS
            if ship.fuel == 0:
                ship.throttle = 0
                self.notice = f"{ship.name}: 연료 소진"
        return forces

    def remove_selected(self) -> None:
        if self.selected is None:
            raise ValueError("삭제할 천체를 선택하세요.")
        self.bodies = [body for body in self.bodies if body.id != self.selected_id]
        for body in self.bodies:
            if body.parent_id == self.selected_id:
                body.parent_id = None
        self.selected_id = None

    def accelerations(self) -> dict[int, tuple[float, float]]:
        result = {body.id: [0.0, 0.0] for body in self.bodies}
        for index, first in enumerate(self.bodies):
            for second in self.bodies[index + 1:]:
                dx, dy = second.x - first.x, second.y - first.y
                distance_squared = max(dx * dx + dy * dy, 1e-12)
                inverse_cube = G / (distance_squared * math.sqrt(distance_squared))
                result[first.id][0] += second.mass * dx * inverse_cube
                result[first.id][1] += second.mass * dy * inverse_cube
                result[second.id][0] -= first.mass * dx * inverse_cube
                result[second.id][1] -= first.mass * dy * inverse_cube
        return {body_id: (values[0], values[1]) for body_id, values in result.items()}

    def stable_step(self) -> float:
        step = .05
        for index, first in enumerate(self.bodies):
            for second in self.bodies[index + 1:]:
                distance = max(1e-6, math.hypot(first.x - second.x, first.y - second.y))
                relative_speed = math.hypot(first.vx - second.vx, first.vy - second.vy)
                step = min(step, .02 * math.sqrt(distance ** 3 / (G * (first.mass + second.mass))))
                if relative_speed:
                    step = min(step, .1 * distance / relative_speed)
        return max(1e-6, step)

    def advance(self, duration: float, max_steps: int = 512) -> float:
        duration = finite(duration, 0, 10000, "경과 시간")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 20000:
            raise ValueError("물리 계산 횟수는 1~20000의 정수여야 합니다.")
        advanced = 0.0
        for _ in range(max_steps):
            remaining = duration - advanced
            if remaining < 1e-12:
                break
            step = min(remaining, self.stable_step())
            thrust = self.thrust_for_step(step)
            before = self.accelerations()
            for body in self.bodies:
                ax, ay = before[body.id]
                tx, ty = thrust.get(body.id, (0, 0))
                ax, ay = ax + tx, ay + ty
                body.x += body.vx * step + .5 * ax * step * step
                body.y += body.vy * step + .5 * ay * step * step
            after = self.accelerations()
            for body in self.bodies:
                tx, ty = thrust.get(body.id, (0, 0))
                body.vx += (.5 * (before[body.id][0] + after[body.id][0]) + tx) * step
                body.vy += (.5 * (before[body.id][1] + after[body.id][1]) + ty) * step
            advanced += step
        self.elapsed += advanced
        self.physics_limited = duration - advanced > 1e-9
        return advanced

    def momentum(self) -> tuple[float, float]:
        return sum(body.mass * body.vx for body in self.bodies), sum(body.mass * body.vy for body in self.bodies)

    def set_time_scale(self, value: float) -> None:
        if isinstance(value, bool) or value not in TIME_SCALES:
            raise ValueError("배속은 0.25, 1, 5, 20, 100 중에서 선택하세요.")
        self.time_scale = float(value)

    def advance_real_time(self, real_seconds: float) -> float:
        real_seconds = finite(real_seconds, 0, 86400, "실제 경과 시간")
        if self.paused or real_seconds == 0:
            self.effective_speed = 0
            return 0
        requested = min(.25, real_seconds) * self.time_scale
        advanced = self.advance(requested, max_steps=128)
        self.effective_speed = advanced / real_seconds
        self.physics_limited = self.physics_limited or real_seconds > .25
        return advanced

    def single_step(self) -> float:
        if not self.paused:
            self.notice = "한 단계 진행은 일시정지 중에 사용할 수 있습니다."
            return 0
        return self.advance(.05, max_steps=128)

    def energy(self) -> float:
        kinetic = sum(.5 * body.mass * (body.vx ** 2 + body.vy ** 2) for body in self.bodies)
        potential = sum(-G * first.mass * second.mass / max(1e-6, math.hypot(first.x - second.x, first.y - second.y))
                        for index, first in enumerate(self.bodies) for second in self.bodies[index + 1:])
        return kinetic + potential


@dataclass
class SpaceCamera:
    x: float = 0
    y: float = 0
    zoom: float = 1
    width: float = 800
    height: float = 600

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x) * self.zoom + self.width / 2, (y - self.y) * self.zoom + self.height / 2

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.width / 2) / self.zoom + self.x, (sy - self.height / 2) / self.zoom + self.y

    def pan(self, dx: float, dy: float) -> None:
        self.x += dx / self.zoom
        self.y += dy / self.zoom

    def zoom_at(self, factor: float, sx: float, sy: float) -> None:
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("확대 배율은 유한한 양수여야 합니다.")
        wx, wy = self.to_world(sx, sy)
        self.zoom = max(0.05, min(8, self.zoom * factor))
        self.x = wx - (sx - self.width / 2) / self.zoom
        self.y = wy - (sy - self.height / 2) / self.zoom

    def resize(self, width: float, height: float) -> None:
        self.width, self.height = max(1, width), max(1, height)
