from __future__ import annotations

import json
from pathlib import Path
import random

import numpy as np


# id: (표시 이름, 색, 종류, 밀도, 초기 온도)
MATERIALS = {
    "empty": ("지우개", "#101722", "empty", 0, 20),
    "sand": ("모래", "#e6c47b", "powder", 5, 20),
    "water": ("물", "#438ee8", "liquid", 3, 20),
    "stone": ("돌", "#8b95a4", "solid", 9, 20),
    "wood": ("나무", "#a67748", "solid", 8, 20),
    "oil": ("기름", "#b9a24c", "liquid", 2, 20),
    "fire": ("불", "#ff793c", "gas", 0, 650),
    "steam": ("증기", "#b6d8e9", "gas", 1, 120),
    "ice": ("얼음", "#88e4f2", "solid", 8, -20),
    "lava": ("용암", "#f44b32", "liquid", 6, 1100),
    "gunpowder": ("화약", "#a2a17e", "powder", 5, 20),
    "smoke": ("연기", "#656c7b", "gas", 0, 100),
    "acid": ("산", "#98d84c", "liquid", 3, 20),
    "metal": ("금속", "#b6becb", "solid", 9, 20),
    "spark": ("전기", "#fff191", "solid", 9, 180),
    "plant": ("식물", "#49ae67", "solid", 8, 20),
    "salt": ("소금", "#e1e6ef", "powder", 5, 20),
    "saltwater": ("소금물", "#67a9bd", "liquid", 4, 20),
    "glass": ("유리", "#659b9b", "solid", 9, 20),
}


class Sandbox:
    """고정 격자의 경량 셀룰러 시뮬레이션. 온도 단위는 °C."""

    def __init__(self, width=160, height=100, seed=None):
        if not 8 <= width <= 320 or not 8 <= height <= 200:
            raise ValueError("격자 크기가 지원 범위를 벗어났습니다.")
        self.width, self.height = width, height
        self.rng = random.Random(seed)
        self._neighbors = []
        for y in range(height):
            for x in range(width):
                self._neighbors.append(tuple((y + dy) * width + x + dx
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    if 0 <= x + dx < width and 0 <= y + dy < height))
        self.clear()

    def clear(self):
        size = self.width * self.height
        self.cells = ["empty"] * size
        self.heat = [20.0] * size
        self.life = [0] * size
        self.ticks = 0

    def put(self, x, y, material, *, overwrite=True):
        if material not in MATERIALS:
            raise ValueError("알 수 없는 재료입니다.")
        if 0 <= x < self.width and 0 <= y < self.height:
            i = y * self.width + x
            if overwrite or self.cells[i] == "empty":
                self._set(i, material)

    def _set(self, i, material):
        self.cells[i] = material
        self.heat[i] = float(MATERIALS[material][4])
        self.life[i] = self.rng.randint(25, 65) if material in ("fire", "smoke") else 4 if material == "spark" else 0

    def brush(self, x, y, radius, material):
        radius = max(1, min(12, int(radius)))
        for yy in range(max(0, y - radius), min(self.height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(self.width, x + radius + 1)):
                if (xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2:
                    i = yy * self.width + xx
                    if material in ("heat", "cool"):
                        if self.cells[i] != "empty":
                            self.heat[i] = max(-273.0, min(2000.0, self.heat[i] + (100 if material == "heat" else -100)))
                    elif material == "empty" or self.cells[i] == "empty":
                        self.put(xx, yy, material)
                    elif material == "spark" and self.cells[i] == "metal":
                        self._set(i, "spark")

    def neighbors(self, i):
        return self._neighbors[i]

    def _blast(self, i, touched):
        x, y = i % self.width, i // self.width
        for yy in range(max(0, y - 5), min(self.height, y + 6)):
            for xx in range(max(0, x - 5), min(self.width, x + 6)):
                if (xx - x) ** 2 + (yy - y) ** 2 > 25:
                    continue
                j = yy * self.width + xx
                if self.cells[j] in ("metal", "glass", "spark"):
                    self.heat[j] = min(2000, self.heat[j] + 150)
                elif self.cells[j] == "gunpowder" and j != i:
                    self.heat[j] = 650  # 다음 단계에서 연쇄 반응
                else:
                    self._set(j, "fire")
                touched.add(j)

    def step(self):
        touched = set()
        # 열전도는 동일한 이전 상태를 기준으로 계산한다.
        source = np.asarray(self.heat, dtype=float).reshape(self.height, self.width)
        heat = source.copy()
        occupied = np.asarray(self.cells).reshape(self.height, self.width) != "empty"
        for first, second in ((np.s_[:, :-1], np.s_[:, 1:]), (np.s_[:-1, :], np.s_[1:, :])):
            amount = (source[second] - source[first]) * .08 * (occupied[first] & occupied[second])
            heat[first] += amount
            heat[second] -= amount
        self.heat = heat.ravel().tolist()
        # 반응 결과가 같은 단계 안에서 무한 전파되지 않게 원본을 참조한다.
        old = self.cells.copy()
        for i, material in enumerate(old):
            if material == "empty" or i in touched:
                continue
            near = self._neighbors[i]
            hot = (material in ("wood", "oil", "plant", "gunpowder") and
                   any(old[j] in ("fire", "lava", "spark") for j in near))
            temperature = self.heat[i]
            change = None
            if material == "water":
                change = "steam" if temperature >= 100 else "ice" if temperature <= 0 else None
            elif material == "saltwater" and temperature >= 100:
                for j in near:
                    if self.cells[j] == "empty":
                        change = "steam"
                        self._set(j, "salt")
                        touched.add(j)
                        break
            elif material == "ice" and temperature > 0:
                change = "water"
            elif material == "steam" and temperature < 95:
                change = "water"
            elif material == "lava":
                if any(old[j] in ("water", "saltwater", "ice") for j in near):
                    change = "stone"
                    for j in near:
                        if old[j] in ("water", "saltwater", "ice"):
                            self._set(j, "steam")
                            touched.add(j)
                elif temperature < 650:
                    change = "stone"
            elif material == "sand" and temperature >= 1400:
                change = "glass"
            elif material in ("wood", "oil", "plant") and (hot or temperature >= 300):
                change = "fire"
            elif material == "gunpowder" and (hot or temperature >= 250):
                self._blast(i, touched)
                continue
            elif material in ("fire", "smoke"):
                self.life[i] -= 1
                if material == "fire" and any(old[j] in ("water", "saltwater", "ice") for j in near):
                    change = "smoke"
                elif self.life[i] <= 0:
                    change = "smoke" if material == "fire" else "empty"
            elif material == "spark":
                self.life[i] -= 1
                # 마지막 단계는 재점화를 막는 냉각 구간이다.
                if self.life[i] == 2:
                    for j in near:
                        if old[j] == "metal" and j not in touched:
                            self._set(j, "spark")
                            touched.add(j)
                if self.life[i] <= 0:
                    change = "metal"
            elif material == "acid":
                targets = [j for j in near if old[j] not in ("empty", "acid", "glass", "fire", "smoke", "steam")]
                if targets:
                    self._set(self.rng.choice(targets), "empty")
                    touched.add(i)
                    change = "empty"
            elif material == "salt":
                for j in near:
                    if old[j] == "water" and j not in touched:
                        self._set(j, "saltwater")
                        touched.add(j)
                        change = "empty"
                        break
            elif material == "plant" and not hot and self.rng.random() < .02:
                for j in near:
                    if old[j] == "water" and j not in touched:
                        self._set(j, "plant")
                        touched.add(j)
                        break
            if change is not None:
                self._set(i, change)
                touched.add(i)

        # 아래에서 위로 순회하고 이동한 입자는 재이동하지 않는다.
        for y in range(self.height - 1, -1, -1):
            xs = range(self.width) if self.ticks % 2 else range(self.width - 1, -1, -1)
            for x in xs:
                i = y * self.width + x
                material = self.cells[i]
                kind = MATERIALS[material][2]
                if i in touched or kind not in ("powder", "liquid", "gas"):
                    continue
                direction = self.rng.choice((-1, 1))
                dy = -1 if kind == "gas" else 1
                moves = [(0, dy), (direction, dy), (-direction, dy)]
                if kind in ("liquid", "gas"):
                    moves += [(direction, 0), (-direction, 0)]
                for dx, yy in moves:
                    nx, ny = x + dx, y + yy
                    if not (0 <= nx < self.width and 0 <= ny < self.height):
                        continue
                    j = ny * self.width + nx
                    target = self.cells[j]
                    allowed = target == "empty"
                    if dy > 0 and yy > 0 and MATERIALS[target][2] in ("liquid", "gas"):
                        allowed = MATERIALS[material][3] > MATERIALS[target][3]
                    if j not in touched and allowed:
                        for array in (self.cells, self.heat, self.life):
                            array[i], array[j] = array[j], array[i]
                        touched.update((i, j))
                        break
        self.ticks += 1

    def save(self, path: Path):
        data = dict(version=1, width=self.width, height=self.height,
                    cells=self.cells, heat=self.heat, life=self.life)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path):
        if path.stat().st_size > 5_000_000:
            raise ValueError("저장 파일이 너무 큽니다.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("지원하지 않는 저장 형식입니다.")
        w, h = data.get("width"), data.get("height")
        if type(w) is not int or type(h) is not int:
            raise ValueError("격자 크기가 올바르지 않습니다.")
        world = cls(w, h)
        for key in ("cells", "heat", "life"):
            if not isinstance(data.get(key), list) or len(data[key]) != w * h:
                raise ValueError("입자 데이터 길이가 올바르지 않습니다.")
        if any(not isinstance(m, str) or m not in MATERIALS for m in data["cells"]):
            raise ValueError("알 수 없는 재료가 포함되어 있습니다.")
        if any(type(t) not in (float, int) or not -273 <= t <= 2000 for t in data["heat"]):
            raise ValueError("온도 데이터가 올바르지 않습니다.")
        if any(type(t) is not int or not 0 <= t <= 65 for t in data["life"]):
            raise ValueError("입자 수명이 올바르지 않습니다.")
        world.cells, world.heat, world.life = data["cells"], data["heat"], data["life"]
        return world

    def demo(self):
        self.clear()
        w, h = self.width, self.height
        for x in range(w):
            self.put(x, h - 1, "stone")
        for x in range(w // 8, w * 7 // 8):
            self.put(x, h * 3 // 4, "glass")
        for y in range(h // 2, h * 3 // 4):
            self.put(w // 8, y, "glass")
            self.put(w * 7 // 8 - 1, y, "glass")
        for y in range(h // 2 + 4, h * 3 // 4):
            for x in range(w // 8 + 1, w // 2):
                self.put(x, y, "water")
        for x in range(w // 2, w * 3 // 4):
            for y in range(h // 5, h // 3):
                self.put(x, y, "sand")
