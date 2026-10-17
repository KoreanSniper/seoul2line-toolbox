from __future__ import annotations

import math
import random
from dataclasses import dataclass

TARGET_EDPI = 800


class StepClock:
    """120 Hz movement steps with a bounded catch-up after a GUI stall."""
    step = 1 / 120

    def __init__(self, now):
        self.previous = now
        self.pending = 0.0

    def consume(self, now):
        self.pending += min(.25, max(0, now - self.previous))
        self.previous = now
        count = int((self.pending + 1e-10) / self.step)
        self.pending = max(0.0, self.pending - count * self.step)
        return count


@dataclass(frozen=True)
class Sensitivity:
    dpi: float
    coefficient: float
    fov: float

    def __post_init__(self):
        if not all(math.isfinite(value) for value in (self.dpi, self.coefficient, self.fov)):
            raise ValueError("유한한 숫자를 입력하세요.")
        if not 1 <= self.dpi <= 100000 or not 0 < self.coefficient <= 10 or not 1 <= self.fov < 170:
            raise ValueError("DPI 1~100000, 회전 계수 0 초과~10, 수평 FOV 1~170 미만을 입력하세요.")

    @property
    def sensitivity(self):
        return TARGET_EDPI / self.dpi

    @property
    def cm360(self):
        return 360 * 2.54 / (self.coefficient * TARGET_EDPI)

    def angle(self, counts):
        return counts * self.sensitivity * self.coefficient


def focal_length(width, fov):
    return width / (2 * math.tan(math.radians(fov / 2)))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


@dataclass
class Camera:
    position: tuple = (0.0, 1.6, -6.0)
    yaw: float = 0.0
    pitch: float = 0.0

    def basis(self):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        sy, cy, sp, cp = math.sin(yaw), math.cos(yaw), math.sin(pitch), math.cos(pitch)
        return (cy, 0, -sy), (sy * sp, cp, cy * sp), (sy * cp, -sp, cy * cp)

    def local(self, point):
        delta = tuple(a - b for a, b in zip(point, self.position))
        return tuple(dot(delta, axis) for axis in self.basis())

    def move(self, forward, right, seconds):
        yaw = math.radians(self.yaw)
        distance = 4 * seconds / max(1, math.hypot(forward, right))
        x, y, z = self.position
        self.position = (max(-5.5, min(5.5, x + distance * (forward * math.sin(yaw) + right * math.cos(yaw)))),
                         y, max(-7.5, min(13.5, z + distance * (forward * math.cos(yaw) - right * math.sin(yaw)))))


def project(point, camera, width, height, fov):
    x, y, z = camera.local(point)
    if z < .05:
        return None
    focal = focal_length(width, fov)
    return width / 2 + focal * x / z, height / 2 - focal * y / z


def ray_sphere(origin, direction, center, radius):
    delta = tuple(a - b for a, b in zip(origin, center))
    b = dot(delta, direction)
    discriminant = b * b - dot(delta, delta) + radius * radius
    if discriminant < 0:
        return None
    near, far = -b - math.sqrt(discriminant), -b + math.sqrt(discriminant)
    return near if near >= 0 else far if far >= 0 else None


class AimSession:
    def __init__(self, duration=60, radius=.25, rng=None):
        self.duration = duration
        self.radius = radius
        self.rng = rng or random.Random()
        self.started = None
        self.target_since = None
        self.target = None
        self.shots = 0
        self.hits = 0
        self.reactions = []

    def remaining(self, now):
        return self.duration if self.started is None else max(0, self.duration - (now - self.started))

    def start(self, now):
        self.started = now
        self.shots = self.hits = 0
        self.reactions = []
        self.spawn(now)

    def spawn(self, now):
        self.target = (self.rng.uniform(-4.5, 4.5), self.rng.uniform(.7, 3.5), self.rng.uniform(1, 11))
        self.target_since = now

    def shoot(self, camera, now):
        if self.started is None or not self.remaining(now) or self.target is None:
            return None
        self.shots += 1
        if ray_sphere(camera.position, camera.basis()[2], self.target, self.radius) is not None:
            self.hits += 1
            self.reactions.append(max(0, now - self.target_since))
            self.spawn(now)
            return True
        return False

    @property
    def accuracy(self):
        return 100 * self.hits / self.shots if self.shots else 0

    @property
    def reaction_ms(self):
        return 1000 * sum(self.reactions) / len(self.reactions) if self.reactions else 0
