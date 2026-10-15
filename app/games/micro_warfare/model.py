from __future__ import annotations

from dataclasses import dataclass, field
import math
import random


TILE_SIZE = 32
TERRAIN_COLORS = {"grass": "#263e35", "forest": "#1b3029", "water": "#24485e", "rock": "#50565b"}
BUILDING_SPECS = {
    "hq": {"name": "본부", "ore": 200, "wood": 150, "time": 10, "color": "#425a81"},
    "barracks": {"name": "병영", "ore": 120, "wood": 80, "time": 6, "color": "#816549"},
    "warehouse": {"name": "창고", "ore": 60, "wood": 80, "time": 5, "color": "#446d66"},
}
UNIT_SPECS = {
    "worker": {"name": "일꾼", "building": "hq", "ore": 50, "wood": 20, "time": 4, "speed": 80},
    "soldier": {"name": "보병", "building": "barracks", "ore": 80, "wood": 40, "time": 6, "speed": 96},
}


@dataclass
class Battlefield:
    width: int
    height: int
    seed: int
    tiles: list[list[str]]

    @classmethod
    def generate(cls, seed: int = 1, width: int = 80, height: int = 60) -> Battlefield:
        if width < 24 or height < 24:
            raise ValueError("전장 크기는 24 × 24 이상이어야 합니다.")
        rng = random.Random(seed)
        tiles = [["grass" for _ in range(width)] for _ in range(height)]
        for _ in range(width * height // 110):
            cx, cy = rng.randrange(width), rng.randrange(height)
            rx, ry = rng.randint(2, 5), rng.randint(2, 4)
            kind = rng.choice(("forest", "forest", "water", "rock"))
            for y in range(max(0, cy - ry), min(height, cy + ry + 1)):
                for x in range(max(0, cx - rx), min(width, cx + rx + 1)):
                    if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                        tiles[y][x] = kind
        # Clear starting zones and a connecting corridor for a playable map.
        for bx, by in ((6, 8), (width - 8, height - 10)):
            for y in range(by - 4, by + 5):
                for x in range(bx - 4, bx + 5):
                    tiles[y][x] = "grass"
        for x in range(6, width - 7):
            tiles[8][x] = "grass"
        for y in range(8, height - 9):
            tiles[y][width - 8] = "grass"
        return cls(width, height, seed, tiles)

    @property
    def pixel_width(self) -> int:
        return self.width * TILE_SIZE

    @property
    def pixel_height(self) -> int:
        return self.height * TILE_SIZE

    def contains(self, x: float, y: float) -> bool:
        return 0 <= x < self.pixel_width and 0 <= y < self.pixel_height

    def tile_at(self, x: float, y: float) -> str | None:
        if not self.contains(x, y):
            return None
        return self.tiles[int(y // TILE_SIZE)][int(x // TILE_SIZE)]

    def walkable(self, x: float, y: float) -> bool:
        return self.tile_at(x, y) in ("grass", "forest")


@dataclass
class Camera:
    world_width: float
    world_height: float
    x: float = 0
    y: float = 0
    zoom: float = 1
    width: float = 800
    height: float = 600

    def clamp(self) -> None:
        self.x = max(0, min(self.x, max(0, self.world_width - self.width / self.zoom)))
        self.y = max(0, min(self.y, max(0, self.world_height - self.height / self.zoom)))

    def resize(self, width: float, height: float) -> None:
        self.width, self.height = max(1, width), max(1, height)
        self.clamp()

    def pan(self, dx: float, dy: float) -> None:
        self.x += dx / self.zoom
        self.y += dy / self.zoom
        self.clamp()

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return self.x + sx / self.zoom, self.y + sy / self.zoom

    def to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.x) * self.zoom, (wy - self.y) * self.zoom

    def zoom_at(self, factor: float, sx: float, sy: float) -> None:
        wx, wy = self.to_world(sx, sy)
        self.zoom = max(0.5, min(2.5, self.zoom * factor))
        self.x, self.y = wx - sx / self.zoom, wy - sy / self.zoom
        self.clamp()

    def visible_tiles(self, world: Battlefield) -> tuple[range, range]:
        left, top = int(self.x // TILE_SIZE), int(self.y // TILE_SIZE)
        right = min(world.width, math.ceil((self.x + self.width / self.zoom) / TILE_SIZE))
        bottom = min(world.height, math.ceil((self.y + self.height / self.zoom) / TILE_SIZE))
        return range(left, right), range(top, bottom)


@dataclass
class Unit:
    id: int
    owner: int
    x: float
    y: float
    role: str = "worker"
    target: tuple[float, float] | None = None
    speed: float = 80
    resource_id: int | None = None
    cargo: float = 0
    cargo_kind: str = "ore"
    returning: bool = False
    building_id: int | None = None


@dataclass
class ResourceNode:
    id: int
    kind: str
    x: float
    y: float
    amount: float = 500


@dataclass
class ProductionOrder:
    kind: str
    progress: float = 0


@dataclass
class Building:
    id: int
    kind: str
    owner: int
    col: int
    row: int
    progress: float = 0
    level: int = 1
    upgrade_remaining: float = 0
    queue: list[ProductionOrder] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.progress >= BUILDING_SPECS[self.kind]["time"]

    @property
    def center(self) -> tuple[float, float]:
        return (self.col + 1) * TILE_SIZE, (self.row + 1) * TILE_SIZE

    def contains(self, x: float, y: float) -> bool:
        return self.col * TILE_SIZE <= x < (self.col + 2) * TILE_SIZE and self.row * TILE_SIZE <= y < (self.row + 2) * TILE_SIZE


class WarfareGame:
    def __init__(self, seed: int = 1) -> None:
        self.world = Battlefield.generate(seed)
        self.units = [Unit(i + 1, 0, (6 + i % 2) * TILE_SIZE + 16,
                           (8 + i // 2) * TILE_SIZE + 16) for i in range(4)]
        self.units.append(Unit(5, 1, (self.world.width - 8) * TILE_SIZE + 16,
                               (self.world.height - 10) * TILE_SIZE + 16, "soldier"))
        self.selected_ids: set[int] = set()
        self.next_unit_id = 6
        self.notice = "일꾼을 선택하고 우클릭으로 이동하세요."
        self.stock = {"ore": 200.0, "wood": 150.0}
        self.storage_capacity = 2000.0
        self.depot = (6 * TILE_SIZE + 16, 7 * TILE_SIZE + 16)
        self.buildings = [Building(1, "hq", 0, 5, 5, progress=10),
                          Building(2, "hq", 1, self.world.width - 10, self.world.height - 12, progress=10)]
        self.selected_building: int | None = None
        self.resources = [ResourceNode(1, "ore", 11 * TILE_SIZE + 16, 8 * TILE_SIZE + 16),
                          ResourceNode(2, "wood", 11 * TILE_SIZE + 16, 11 * TILE_SIZE + 16)]
        for node in self.resources:
            for cy in range(5, int(node.y // TILE_SIZE) + 2):
                for cx in range(5, int(node.x // TILE_SIZE) + 2):
                    self.world.tiles[cy][cx] = "grass"

    @property
    def selected_units(self) -> list[Unit]:
        return [unit for unit in self.units if unit.owner == 0 and unit.id in self.selected_ids]

    def select(self, x1: float, y1: float, x2: float, y2: float, additive: bool = False) -> None:
        self.selected_building = None
        if not additive:
            self.selected_ids.clear()
        if math.hypot(x2 - x1, y2 - y1) < 8:
            building = self.building_at(x2, y2)
            if building and building.owner == 0:
                self.selected_building = building.id
                self.notice = f"{BUILDING_SPECS[building.kind]['name']} 선택 · Lv.{building.level}"
                return
            candidates = [unit for unit in self.units if unit.owner == 0
                          and math.hypot(unit.x - x2, unit.y - y2) <= 18]
            chosen = [min(candidates, key=lambda unit: math.hypot(unit.x - x2, unit.y - y2))] if candidates else []
        else:
            chosen = [unit for unit in self.units if unit.owner == 0
                      and min(x1, x2) <= unit.x <= max(x1, x2) and min(y1, y2) <= unit.y <= max(y1, y2)]
        self.selected_ids.update(unit.id for unit in chosen)
        self.notice = f"유닛 {len(self.selected_units)}기 선택"

    def issue_move(self, x: float, y: float) -> bool:
        selected = self.selected_units
        if not selected:
            self.notice = "먼저 아군 유닛을 선택하세요."
            return False
        if not self.walkable(x, y):
            self.notice = "물·바위 또는 전장 밖으로 이동할 수 없습니다."
            return False
        columns = math.ceil(math.sqrt(len(selected)))
        for index, unit in enumerate(selected):
            tx = x + (index % columns - (columns - 1) / 2) * 20
            ty = y + (index // columns) * 20
            unit.target = (tx, ty) if self.walkable(tx, ty) else (x, y)
            unit.resource_id = None
            unit.returning = False
            unit.building_id = None
        self.notice = f"{len(selected)}기 이동 명령"
        return True

    def resource_at(self, x: float, y: float) -> ResourceNode | None:
        return next((node for node in self.resources if math.hypot(node.x - x, node.y - y) <= 22), None)

    def issue_harvest(self, node: ResourceNode) -> bool:
        workers = [unit for unit in self.selected_units if unit.role == "worker"]
        if not workers or node.amount <= 0:
            self.notice = "채굴할 자원과 아군 일꾼을 선택하세요."
            return False
        for worker in workers:
            worker.building_id = None
            worker.resource_id = node.id
            worker.returning = worker.cargo > 0
            worker.target = self.depot if worker.returning else (node.x, node.y)
        self.notice = f"일꾼 {len(workers)}기 자동 채굴 시작"
        return True

    def issue_deposit(self) -> None:
        for worker in self.selected_units:
            if worker.role == "worker" and worker.cargo > 0:
                worker.returning = True
                worker.building_id = None
                worker.target = self.depot
        self.notice = "운반 중인 자원을 본부에 반납합니다."

    def building_at(self, x: float, y: float) -> Building | None:
        return next((building for building in self.buildings if building.contains(x, y)), None)

    def walkable(self, x: float, y: float) -> bool:
        return self.world.walkable(x, y) and self.building_at(x, y) is None

    def placement_error(self, kind: str, col: int, row: int) -> str:
        if kind not in BUILDING_SPECS:
            return "알 수 없는 건물입니다."
        for cy in range(row, row + 2):
            for cx in range(col, col + 2):
                if not self.walkable((cx + 0.5) * TILE_SIZE, (cy + 0.5) * TILE_SIZE):
                    return "건물은 전장 안의 빈 육지에만 배치할 수 있습니다."
        if any(col * TILE_SIZE - 10 <= unit.x <= (col + 2) * TILE_SIZE + 10
               and row * TILE_SIZE - 10 <= unit.y <= (row + 2) * TILE_SIZE + 10 for unit in self.units):
            return "유닛이 있는 곳에는 건설할 수 없습니다."
        if any(col * TILE_SIZE - 22 <= node.x <= (col + 2) * TILE_SIZE + 22
               and row * TILE_SIZE - 22 <= node.y <= (row + 2) * TILE_SIZE + 22 for node in self.resources):
            return "자원 매장지와 겹칩니다."
        return ""

    def spend(self, ore: float, wood: float) -> bool:
        if self.stock["ore"] < ore or self.stock["wood"] < wood:
            self.notice = f"자원이 부족합니다. 필요: 광석 {ore:.0f}, 목재 {wood:.0f}"
            return False
        self.stock["ore"] -= ore
        self.stock["wood"] -= wood
        return True

    def work_point(self, building: Building, worker: Unit) -> tuple[float, float] | None:
        col, row = building.col, building.row
        cells = [(col + x, row - 1) for x in range(2)] + [(col + x, row + 2) for x in range(2)]
        cells += [(col - 1, row + y) for y in range(2)] + [(col + 2, row + y) for y in range(2)]
        points = [((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE) for x, y in cells]
        return min((point for point in points if self.walkable(*point)),
                   key=lambda point: math.dist(point, (worker.x, worker.y)), default=None)

    def issue_build(self, kind: str, col: int, row: int) -> bool:
        workers = [unit for unit in self.selected_units if unit.role == "worker"]
        if not workers:
            self.notice = "건설할 일꾼을 선택하세요."
            return False
        error = self.placement_error(kind, col, row)
        if error:
            self.notice = error
            return False
        building = Building(max(item.id for item in self.buildings) + 1, kind, 0, col, row)
        worker = min(workers, key=lambda unit: math.dist((unit.x, unit.y), building.center))
        point = self.work_point(building, worker)
        if point is None:
            self.notice = "건설 현장에 접근할 공간이 없습니다."
            return False
        spec = BUILDING_SPECS[kind]
        if not self.spend(spec["ore"], spec["wood"]):
            return False
        self.buildings.append(building)
        worker.resource_id, worker.returning = None, False
        worker.building_id, worker.target = building.id, point
        self.notice = f"{spec['name']} 건설 시작"
        return True

    def resume_build(self) -> bool:
        building = next((item for item in self.buildings if item.id == self.selected_building), None)
        if not building or building.owner != 0 or building.complete:
            self.notice = "미완성 아군 건물을 선택하세요."
            return False
        workers = [unit for unit in self.units if unit.owner == 0 and unit.role == "worker" and unit.building_id is None]
        if not workers:
            self.notice = "작업 가능한 일꾼이 없습니다."
            return False
        worker = min(workers, key=lambda unit: math.dist((unit.x, unit.y), building.center))
        point = self.work_point(building, worker)
        if point is None:
            return False
        worker.resource_id, worker.returning = None, False
        worker.building_id, worker.target = building.id, point
        self.notice = "건설을 재개합니다."
        return True

    def upgrade(self) -> bool:
        building = next((item for item in self.buildings if item.id == self.selected_building), None)
        if not building or building.owner != 0 or not building.complete or building.level >= 3 or building.upgrade_remaining:
            self.notice = "완성된 아군 건물을 선택하세요. 최대 레벨은 3입니다."
            return False
        if not self.spend(80 * building.level, 60 * building.level):
            return False
        building.upgrade_remaining = 5 * building.level
        self.notice = "건물 업그레이드 시작"
        return True

    def refresh_capacity(self) -> None:
        self.storage_capacity = sum((2000 if item.kind == "hq" else 1000) * item.level
                                    for item in self.buildings if item.owner == 0 and item.complete
                                    and item.kind in ("hq", "warehouse"))

    @property
    def population_limit(self) -> int:
        return sum((10 if building.kind == "hq" else 5) * building.level
                   for building in self.buildings if building.owner == 0 and building.complete
                   and building.kind in ("hq", "barracks"))

    @property
    def population_reserved(self) -> int:
        return sum(unit.owner == 0 for unit in self.units) + sum(len(building.queue) for building in self.buildings if building.owner == 0)

    def enqueue(self, kind: str) -> bool:
        building = next((item for item in self.buildings if item.id == self.selected_building), None)
        spec = UNIT_SPECS.get(kind)
        if not spec or not building or building.owner != 0 or not building.complete or building.kind != spec["building"]:
            self.notice = "일꾼은 완성된 본부에서, 보병은 완성된 병영에서 생산합니다."
            return False
        if len(building.queue) >= 5:
            self.notice = "건물당 생산 대기열은 5개까지입니다."
            return False
        if self.population_reserved >= self.population_limit:
            self.notice = "인구 한도에 도달했습니다. 본부를 강화하거나 병영을 건설하세요."
            return False
        if not self.spend(spec["ore"], spec["wood"]):
            return False
        building.queue.append(ProductionOrder(kind))
        self.notice = f"{spec['name']} 생산 예약"
        return True

    def cancel_production(self, index: int) -> bool:
        building = next((item for item in self.buildings if item.id == self.selected_building), None)
        if not building or building.owner != 0 or not 0 <= index < len(building.queue):
            self.notice = "취소할 생산 항목을 선택하세요."
            return False
        order = building.queue.pop(index)
        spec = UNIT_SPECS[order.kind]
        self.stock["ore"] += spec["ore"]
        self.stock["wood"] += spec["wood"]
        self.notice = "생산 취소 · 예약 자원 전액 반환"
        return True

    def spawn_point(self, building: Building) -> tuple[float, float] | None:
        for radius in range(1, 5):
            for row in range(building.row - radius, building.row + 2 + radius):
                for col in range(building.col - radius, building.col + 2 + radius):
                    point = ((col + 0.5) * TILE_SIZE, (row + 0.5) * TILE_SIZE)
                    if self.walkable(*point) and all(math.dist(point, (unit.x, unit.y)) >= 20 for unit in self.units):
                        return point
        return None

    def update_production(self, dt: float) -> None:
        for building in self.buildings:
            if not building.complete or not building.queue:
                continue
            order = building.queue[0]
            spec = UNIT_SPECS[order.kind]
            order.progress = min(spec["time"], order.progress + dt * building.level)
            if order.progress < spec["time"]:
                continue
            point = self.spawn_point(building)
            if point is None:
                self.notice = "생산 완료 · 출구가 막혀 빈 공간을 기다립니다."
                continue
            self.units.append(Unit(self.next_unit_id, building.owner, *point, role=order.kind, speed=spec["speed"]))
            self.next_unit_id += 1
            building.queue.pop(0)
            self.notice = f"{spec['name']} 생산 완료"

    def update_buildings(self, dt: float) -> None:
        for building in self.buildings:
            if building.upgrade_remaining:
                building.upgrade_remaining = max(0, building.upgrade_remaining - dt)
                if building.upgrade_remaining == 0:
                    building.level += 1
                    self.refresh_capacity()
                    self.notice = "업그레이드 완료"
        for worker in self.units:
            if worker.building_id is None or worker.target is not None:
                continue
            building = next((item for item in self.buildings if item.id == worker.building_id), None)
            if building is None or building.complete:
                worker.building_id = None
                continue
            point = self.work_point(building, worker)
            if point is not None and math.dist((worker.x, worker.y), point) <= 12:
                building.progress += dt
                if building.complete:
                    worker.building_id = None
                    self.refresh_capacity()
                    self.notice = f"{BUILDING_SPECS[building.kind]['name']} 건설 완료"

    def update_harvest(self, worker: Unit, dt: float) -> None:
        if worker.role != "worker" or worker.target is not None:
            return
        node = next((node for node in self.resources if node.id == worker.resource_id), None)
        if worker.returning:
            if math.dist((worker.x, worker.y), self.depot) > 8:
                return
            deposited = min(worker.cargo, max(0, self.storage_capacity - sum(self.stock.values())))
            self.stock[worker.cargo_kind] += deposited
            worker.cargo -= deposited
            if worker.cargo > 0.001:
                self.notice = "창고가 가득 찼습니다. 자원을 사용하면 다시 보관합니다."
                return
            worker.cargo = 0
            worker.returning = False
            if node and node.amount > 0:
                worker.target = (node.x, node.y)
            else:
                worker.resource_id = None
        elif node and math.dist((worker.x, worker.y), (node.x, node.y)) <= 8:
            mined = min(10 * dt, node.amount, 20 - worker.cargo)
            worker.cargo_kind = node.kind
            worker.cargo += mined
            node.amount -= mined
            if worker.cargo >= 20 or node.amount <= 0:
                worker.returning = True
                worker.target = self.depot

    def update(self, dt: float) -> None:
        if dt < 0 or not math.isfinite(dt):
            raise ValueError("시간 간격은 유한한 양수여야 합니다.")
        for unit in self.units:
            if unit.target is None:
                continue
            tx, ty = unit.target
            distance = math.hypot(tx - unit.x, ty - unit.y)
            if distance < 0.1:
                unit.target = None
                continue
            travel = min(distance, unit.speed * dt)
            steps = max(1, math.ceil(travel / 4))
            for _ in range(steps):
                nx = unit.x + (tx - unit.x) / distance * travel / steps
                ny = unit.y + (ty - unit.y) / distance * travel / steps
                if not self.walkable(nx, ny):
                    unit.target = None
                    self.notice = "이동 경로에 장애물이 있습니다. 다른 지점으로 이동하세요."
                    break
                unit.x, unit.y = nx, ny
                distance = math.hypot(tx - unit.x, ty - unit.y)
                if distance <= 0.1:
                    unit.target = None
                    break
        for worker in self.units:
            self.update_harvest(worker, dt)
        self.update_buildings(dt)
        self.update_production(dt)
