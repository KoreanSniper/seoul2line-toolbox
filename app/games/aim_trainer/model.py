from __future__ import annotations

import math
import random
from dataclasses import dataclass

TARGET_EDPI = 800


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


def project(target, camera, width, height, fov):
    yaw = (target[0] - camera[0] + 180) % 360 - 180
    pitch = target[1] - camera[1]
    if abs(yaw) >= 89 or abs(pitch) >= 89:
        return None
    focal = focal_length(width, fov)
    return width / 2 + math.tan(math.radians(yaw)) * focal, height / 2 + math.tan(math.radians(pitch)) * focal


class AimSession:
    def __init__(self, duration=60, radius=20, rng=None):
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

    def start(self, now, width, height):
        self.started = now
        self.shots = self.hits = 0
        self.reactions = []
        self.spawn(now, width, height)

    def spawn(self, now, width, height):
        margin = self.radius + 8
        if width < 2 * margin or height < 2 * margin:
            self.target = None
            return
        self.target = (self.rng.uniform(margin, width - margin),
                       self.rng.uniform(margin, height - margin))
        self.target_since = now

    def shoot(self, x, y, now, width, height):
        if self.started is None or not self.remaining(now) or self.target is None:
            return None
        self.shots += 1
        if math.hypot(x - self.target[0], y - self.target[1]) <= self.radius:
            self.hits += 1
            self.reactions.append(max(0, now - self.target_since))
            self.spawn(now, width, height)
            return True
        return False

    @property
    def accuracy(self):
        return 100 * self.hits / self.shots if self.shots else 0

    @property
    def reaction_ms(self):
        return 1000 * sum(self.reactions) / len(self.reactions) if self.reactions else 0
