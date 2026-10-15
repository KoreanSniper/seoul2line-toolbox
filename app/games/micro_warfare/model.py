from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
import random


TILE_SIZE = 32
TERRAIN_COLORS = {"grass": "#263e35", "forest": "#1b3029", "water": "#24485e", "rock": "#50565b"}
GAME_MODES = {"skirmish": "본부 파괴전", "annihilation": "전멸전", "sandbox": "샌드박스"}
BUILDING_SPECS = {
    "hq": {"name": "본부", "ore": 200, "wood": 150, "time": 10, "color": "#425a81"},
    "barracks": {"name": "병영", "ore": 120, "wood": 80, "time": 6, "color": "#816549"},
    "warehouse": {"name": "창고", "ore": 60, "wood": 80, "time": 5, "color": "#446d66"},
}
UNIT_SPECS = {
    "worker": {"name": "일꾼", "building": "hq", "ore": 50, "wood": 20, "time": 4, "speed": 80,
               "hp": 60, "range": 36, "damage": 4, "cooldown": 1.2, "vision": 60},
    "soldier": {"name": "보병", "building": "barracks", "ore": 80, "wood": 40, "time": 6, "speed": 96,
                "hp": 100, "range": 160, "damage": 12, "cooldown": 0.8, "vision": 240},
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
    path: list[tuple[float, float]] = field(default_factory=list)
    hp: float = -1
    cooldown: float = 0
    attack_target: tuple[str, int] | None = None
    repath_remaining: float = 0

    def __post_init__(self) -> None:
        if self.hp < 0:
            self.hp = UNIT_SPECS[self.role]["hp"]


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
    hp: float = 500

    @property
    def complete(self) -> bool:
        return self.progress >= BUILDING_SPECS[self.kind]["time"]

    @property
    def center(self) -> tuple[float, float]:
        return (self.col + 1) * TILE_SIZE, (self.row + 1) * TILE_SIZE

    def contains(self, x: float, y: float) -> bool:
        return self.col * TILE_SIZE <= x < (self.col + 2) * TILE_SIZE and self.row * TILE_SIZE <= y < (self.row + 2) * TILE_SIZE


class WarfareGame:
    def __init__(self, seed: int = 1, *, ai_enabled: bool = True, mode: str = "skirmish") -> None:
        if mode not in GAME_MODES:
            raise ValueError("알 수 없는 게임 모드입니다.")
        self.mode = mode
        self.result = "running"
        self.paused = False
        ai_enabled = ai_enabled and mode != "sandbox"
        self.world = Battlefield.generate(seed)
        self.units = [Unit(i + 1, 0, (6 + i % 2) * TILE_SIZE + 16,
                           (8 + i // 2) * TILE_SIZE + 16) for i in range(4)]
        self.units.append(Unit(5, 1, (self.world.width - 8) * TILE_SIZE + 16,
                               (self.world.height - 10) * TILE_SIZE + 16, "soldier"))
        self.selected_ids: set[int] = set()
        self.next_unit_id = 6
        self.next_building_id = 3
        self.notice = "일꾼을 선택하고 우클릭으로 이동하세요."
        self.stock = {"ore": 200.0, "wood": 150.0}
        self.enemy_stock = {"ore": 200.0, "wood": 150.0}
        self.ai_enabled = ai_enabled
        self.ai_timer = 0.0
        self.elapsed = 0.0
        self.statistics = {owner: {key: 0.0 for key in ("gathered_ore", "gathered_wood", "units_produced", "units_lost", "kills",
                                                     "buildings_built", "buildings_lost", "buildings_destroyed", "damage_dealt")}
                           for owner in (0, 1)}
        self.enemy_depot = ((self.world.width - 9) * TILE_SIZE + 16, (self.world.height - 10) * TILE_SIZE + 16)
        self.storage_capacity = 2000.0
        self.depot = (6 * TILE_SIZE + 16, 7 * TILE_SIZE + 16)
        self.buildings = [Building(1, "hq", 0, 5, 5, progress=10, hp=1000),
                          Building(2, "hq", 1, self.world.width - 10, self.world.height - 12, progress=10, hp=1000)]
        self.selected_building: int | None = None
        self.resources = [ResourceNode(1, "ore", 11 * TILE_SIZE + 16, 8 * TILE_SIZE + 16),
                          ResourceNode(2, "wood", 11 * TILE_SIZE + 16, 11 * TILE_SIZE + 16)]
        for node in self.resources:
            for cy in range(5, int(node.y // TILE_SIZE) + 2):
                for cx in range(5, int(node.x // TILE_SIZE) + 2):
                    self.world.tiles[cy][cx] = "grass"
        if ai_enabled:
            self.units.extend(Unit(6 + i, 1, (self.world.width - 9 + i) * TILE_SIZE + 16,
                                   (self.world.height - 9) * TILE_SIZE + 16) for i in range(2))
            self.next_unit_id = 8
            self.resources.extend((ResourceNode(3, "ore", (self.world.width - 14) * TILE_SIZE + 16, (self.world.height - 10) * TILE_SIZE + 16),
                                   ResourceNode(4, "wood", (self.world.width - 14) * TILE_SIZE + 16, (self.world.height - 7) * TILE_SIZE + 16)))
            for row in range(self.world.height - 15, self.world.height - 4):
                for col in range(self.world.width - 16, self.world.width - 4):
                    self.world.tiles[row][col] = "grass"
        if mode == "sandbox":
            self.stock = {"ore": 5000.0, "wood": 5000.0}
            self.storage_capacity = 20000

    def can_issue_order(self) -> bool:
        if self.result != "running":
            self.notice = "전투가 종료되었습니다. 새 전장을 시작하세요."
            return False
        return True

    def evaluate_result(self) -> None:
        if self.mode == "sandbox" or self.result != "running":
            return
        if self.mode == "skirmish":
            alive = {item.owner for item in self.buildings if item.kind == "hq" and item.hp > 0}
        else:
            alive = {item.owner for item in [*self.units, *self.buildings] if item.hp > 0}
        if 0 not in alive and 1 not in alive:
            self.result = "draw"
        elif 0 not in alive:
            self.result = "defeat"
        elif 1 not in alive:
            self.result = "victory"
        if self.result != "running":
            self.notice = {"victory": "승리!", "defeat": "패배", "draw": "무승부"}[self.result]

    def stock_for(self, owner: int) -> dict[str, float]:
        return self.stock if owner == 0 else self.enemy_stock

    def depot_for(self, owner: int) -> tuple[float, float]:
        return self.depot if owner == 0 else self.enemy_depot

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
        if not self.can_issue_order():
            return False
        selected = self.selected_units
        if not selected:
            self.notice = "먼저 아군 유닛을 선택하세요."
            return False
        if not self.walkable(x, y):
            self.notice = "물·바위 또는 전장 밖으로 이동할 수 없습니다."
            return False
        columns = math.ceil(math.sqrt(len(selected)))
        moved = 0
        for index, unit in enumerate(selected):
            tx = x + (index % columns - (columns - 1) / 2) * 20
            ty = y + (index // columns) * 20
            destination = (tx, ty) if self.walkable(tx, ty) else (x, y)
            if not self.set_destination(unit, destination):
                continue
            moved += 1
            unit.resource_id = None
            unit.returning = False
            unit.building_id = None
            unit.attack_target = None
        self.notice = f"{moved}기 이동 명령" if moved else "목적지로 갈 수 있는 경로가 없습니다."
        return moved > 0

    def resource_at(self, x: float, y: float) -> ResourceNode | None:
        return next((node for node in self.resources if math.hypot(node.x - x, node.y - y) <= 22), None)

    def issue_harvest(self, node: ResourceNode, *, worker_id: int | None = None, owner: int = 0) -> bool:
        if not self.can_issue_order():
            return False
        workers = [unit for unit in (self.selected_units if worker_id is None else self.units)
                   if unit.role == "worker" and unit.owner == owner and (worker_id is None or unit.id == worker_id)]
        if not workers or node.amount <= 0:
            self.notice = "채굴할 자원과 아군 일꾼을 선택하세요."
            return False
        assigned = 0
        for worker in workers:
            destination = self.depot_for(worker.owner) if worker.cargo > 0 else (node.x, node.y)
            if not self.set_destination(worker, destination):
                continue
            assigned += 1
            worker.building_id = None
            worker.attack_target = None
            worker.resource_id = node.id
            worker.returning = worker.cargo > 0
        self.notice = f"일꾼 {assigned}기 자동 채굴 시작" if assigned else "자원에 접근할 경로가 없습니다."
        return assigned > 0

    def issue_deposit(self) -> None:
        if not self.can_issue_order():
            return
        for worker in self.selected_units:
            if worker.role == "worker" and worker.cargo > 0 and self.set_destination(worker, self.depot):
                worker.returning = True
                worker.building_id = None
                worker.attack_target = None
        self.notice = "운반 중인 자원을 본부에 반납합니다."

    def building_at(self, x: float, y: float) -> Building | None:
        return next((building for building in self.buildings if building.contains(x, y)), None)

    def walkable(self, x: float, y: float) -> bool:
        return self.world.walkable(x, y) and self.building_at(x, y) is None

    def find_path(self, start: tuple[float, float], goal: tuple[float, float]) -> list[tuple[float, float]]:
        if not self.walkable(*start) or not self.walkable(*goal):
            return []
        origin = (int(start[0] // TILE_SIZE), int(start[1] // TILE_SIZE))
        finish = (int(goal[0] // TILE_SIZE), int(goal[1] // TILE_SIZE))
        frontier = [(0.0, origin)]
        costs = {origin: 0.0}
        parents: dict[tuple[int, int], tuple[int, int]] = {}
        while frontier:
            _, current = heapq.heappop(frontier)
            if current == finish:
                cells = [current]
                while current != origin:
                    current = parents[current]
                    cells.append(current)
                cells.reverse()
                points = [((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE) for x, y in cells]
                if origin == finish:
                    return [goal]
                return points + [goal]
            x, y = current
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                nx, ny = neighbor
                if not self.walkable((nx + 0.5) * TILE_SIZE, (ny + 0.5) * TILE_SIZE):
                    continue
                cost = costs[current] + (1.4 if self.world.tiles[ny][nx] == "forest" else 1)
                if cost >= costs.get(neighbor, float("inf")):
                    continue
                costs[neighbor], parents[neighbor] = cost, current
                heuristic = abs(nx - finish[0]) + abs(ny - finish[1])
                heapq.heappush(frontier, (cost + heuristic, neighbor))
        return []

    def set_destination(self, unit: Unit, destination: tuple[float, float]) -> bool:
        path = self.find_path((unit.x, unit.y), destination)
        if not path:
            return False
        unit.path, unit.target = path, destination
        return True

    def move_unit(self, unit: Unit, dt: float) -> None:
        if unit.target is None:
            return
        if not unit.path and not self.set_destination(unit, unit.target):
            unit.target = None
            return
        budget = unit.speed * dt
        while unit.path and budget > 0:
            destination = unit.path[0]
            distance = math.dist((unit.x, unit.y), destination)
            if distance < 0.01:
                unit.path.pop(0)
                continue
            travel = min(distance, budget, 4)
            nx = unit.x + (destination[0] - unit.x) / distance * travel
            ny = unit.y + (destination[1] - unit.y) / distance * travel
            if not self.walkable(nx, ny):
                if not self.set_destination(unit, unit.target):
                    unit.target, unit.path = None, []
                    self.notice = "이동 경로가 막혔습니다."
                return
            unit.x, unit.y = nx, ny
            budget -= travel
        if not unit.path:
            unit.target = None

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

    def spend(self, ore: float, wood: float, owner: int = 0) -> bool:
        stock = self.stock_for(owner)
        if stock["ore"] < ore or stock["wood"] < wood:
            self.notice = f"자원이 부족합니다. 필요: 광석 {ore:.0f}, 목재 {wood:.0f}"
            return False
        stock["ore"] -= ore
        stock["wood"] -= wood
        return True

    def work_point(self, building: Building, worker: Unit) -> tuple[float, float] | None:
        col, row = building.col, building.row
        cells = [(col + x, row - 1) for x in range(2)] + [(col + x, row + 2) for x in range(2)]
        cells += [(col - 1, row + y) for y in range(2)] + [(col + 2, row + y) for y in range(2)]
        points = [((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE) for x, y in cells]
        for point in sorted((point for point in points if self.walkable(*point)),
                            key=lambda point: math.dist(point, (worker.x, worker.y))):
            if self.find_path((worker.x, worker.y), point):
                return point
        return None

    def issue_build(self, kind: str, col: int, row: int, *, worker_id: int | None = None, owner: int = 0) -> bool:
        if not self.can_issue_order():
            return False
        workers = [unit for unit in (self.selected_units if worker_id is None else self.units)
                   if unit.role == "worker" and unit.owner == owner and (worker_id is None or unit.id == worker_id)]
        if not workers:
            self.notice = "건설할 일꾼을 선택하세요."
            return False
        error = self.placement_error(kind, col, row)
        if error:
            self.notice = error
            return False
        building = Building(self.next_building_id, kind, owner, col, row)
        worker = min(workers, key=lambda unit: math.dist((unit.x, unit.y), building.center))
        point = self.work_point(building, worker)
        if point is None:
            self.notice = "건설 현장에 접근할 공간이 없습니다."
            return False
        spec = BUILDING_SPECS[kind]
        if not self.spend(spec["ore"], spec["wood"], owner):
            return False
        self.buildings.append(building)
        self.next_building_id += 1
        worker.resource_id, worker.returning = None, False
        worker.building_id = building.id
        worker.attack_target = None
        self.set_destination(worker, point)
        self.notice = f"{spec['name']} 건설 시작"
        return True

    def resume_build(self) -> bool:
        if not self.can_issue_order():
            return False
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
        worker.building_id = building.id
        worker.attack_target = None
        self.set_destination(worker, point)
        self.notice = "건설을 재개합니다."
        return True

    def upgrade(self, *, building_id: int | None = None, owner: int = 0) -> bool:
        if not self.can_issue_order():
            return False
        building = next((item for item in self.buildings if item.id == (self.selected_building if building_id is None else building_id)), None)
        if not building or building.owner != owner or not building.complete or building.level >= 3 or building.upgrade_remaining:
            self.notice = "완성된 아군 건물을 선택하세요. 최대 레벨은 3입니다."
            return False
        if not self.spend(80 * building.level, 60 * building.level, owner):
            return False
        building.upgrade_remaining = 5 * building.level
        self.notice = "건물 업그레이드 시작"
        return True

    def refresh_capacity(self) -> None:
        self.storage_capacity = sum((2000 if item.kind == "hq" else 1000) * item.level
                                    for item in self.buildings if item.owner == 0 and item.complete
                                    and item.kind in ("hq", "warehouse"))
        if self.mode == "sandbox":
            self.storage_capacity = max(20000, self.storage_capacity)

    @property
    def population_limit(self) -> int:
        return self.population_limit_for(0)

    def population_limit_for(self, owner: int) -> int:
        return sum((10 if building.kind == "hq" else 5) * building.level
                   for building in self.buildings if building.owner == owner and building.complete
                   and building.kind in ("hq", "barracks"))

    @property
    def population_reserved(self) -> int:
        return self.population_reserved_for(0)

    def population_reserved_for(self, owner: int) -> int:
        return sum(unit.owner == owner for unit in self.units) + sum(len(building.queue) for building in self.buildings if building.owner == owner)

    def enqueue(self, kind: str, *, building_id: int | None = None, owner: int = 0) -> bool:
        if not self.can_issue_order():
            return False
        building = next((item for item in self.buildings if item.id == (self.selected_building if building_id is None else building_id)), None)
        spec = UNIT_SPECS.get(kind)
        if not spec or not building or building.owner != owner or not building.complete or building.kind != spec["building"]:
            self.notice = "일꾼은 완성된 본부에서, 보병은 완성된 병영에서 생산합니다."
            return False
        if len(building.queue) >= 5:
            self.notice = "건물당 생산 대기열은 5개까지입니다."
            return False
        if self.population_reserved_for(owner) >= self.population_limit_for(owner):
            self.notice = "인구 한도에 도달했습니다. 본부를 강화하거나 병영을 건설하세요."
            return False
        if not self.spend(spec["ore"], spec["wood"], owner):
            return False
        building.queue.append(ProductionOrder(kind))
        self.notice = f"{spec['name']} 생산 예약"
        return True

    def cancel_production(self, index: int) -> bool:
        if not self.can_issue_order():
            return False
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
                if building.owner == 0:
                    self.notice = "생산 완료 · 출구가 막혀 빈 공간을 기다립니다."
                continue
            self.units.append(Unit(self.next_unit_id, building.owner, *point, role=order.kind, speed=spec["speed"]))
            self.next_unit_id += 1
            self.statistics[building.owner]["units_produced"] += 1
            building.queue.pop(0)
            if building.owner == 0:
                self.notice = f"{spec['name']} 생산 완료"

    def update_buildings(self, dt: float) -> None:
        for building in self.buildings:
            if building.upgrade_remaining:
                building.upgrade_remaining = max(0, building.upgrade_remaining - dt)
                if building.upgrade_remaining == 0:
                    building.level += 1
                    self.refresh_capacity()
                    if building.owner == 0:
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
                    self.statistics[building.owner]["buildings_built"] += 1
                    worker.building_id = None
                    self.refresh_capacity()
                    if building.owner == 0:
                        self.notice = f"{BUILDING_SPECS[building.kind]['name']} 건설 완료"

    def update_harvest(self, worker: Unit, dt: float) -> None:
        if worker.role != "worker" or worker.target is not None:
            return
        node = next((node for node in self.resources if node.id == worker.resource_id), None)
        depot, stock = self.depot_for(worker.owner), self.stock_for(worker.owner)
        capacity = self.storage_capacity if worker.owner == 0 else 2000
        if worker.returning:
            if not any(item.kind == "hq" and item.owner == worker.owner and item.complete for item in self.buildings):
                self.notice = "본부가 없어 자원을 반납할 수 없습니다."
                return
            if math.dist((worker.x, worker.y), depot) > 8:
                return
            deposited = min(worker.cargo, max(0, capacity - sum(stock.values())))
            stock[worker.cargo_kind] += deposited
            self.statistics[worker.owner][f"gathered_{worker.cargo_kind}"] += deposited
            worker.cargo -= deposited
            if worker.cargo > 0.001:
                self.notice = "창고가 가득 찼습니다. 자원을 사용하면 다시 보관합니다."
                return
            worker.cargo = 0
            worker.returning = False
            if node and node.amount > 0:
                self.set_destination(worker, (node.x, node.y))
            else:
                worker.resource_id = None
        elif node and math.dist((worker.x, worker.y), (node.x, node.y)) <= 8:
            mined = min(10 * dt, node.amount, 20 - worker.cargo)
            worker.cargo_kind = node.kind
            worker.cargo += mined
            node.amount -= mined
            if worker.cargo >= 20 or node.amount <= 0:
                worker.returning = True
                self.set_destination(worker, depot)

    def update_enemy_ai(self, dt: float) -> None:
        if not self.ai_enabled:
            return
        self.ai_timer -= dt
        if self.ai_timer > 0 or self.elapsed < 3:
            return
        self.ai_timer = 1.5
        notice = self.notice
        try:
            self.plan_enemy_turn()
        finally:
            self.notice = notice

    def plan_enemy_turn(self) -> None:
        hq = next((building for building in self.buildings if building.kind == "hq" and building.owner == 1 and building.complete), None)
        if hq is None:
            return
        workers = [unit for unit in self.units if unit.owner == 1 and unit.role == "worker"]
        barracks = [building for building in self.buildings if building.owner == 1 and building.kind == "barracks"]
        soldiers = [unit for unit in self.units if unit.owner == 1 and unit.role == "soldier"]
        # Build with actual saved resources before spending the reserve on troops.
        if not barracks and workers and self.enemy_stock["ore"] >= 120 and self.enemy_stock["wood"] >= 80:
            worker = next((unit for unit in workers if unit.building_id is None), None)
            if worker:
                placed = False
                for row in range(hq.row - 3, hq.row + 5):
                    for col in range(hq.col - 4, hq.col + 5):
                        if self.placement_error("barracks", col, row):
                            continue
                        if self.issue_build("barracks", col, row, worker_id=worker.id, owner=1):
                            placed = True
                            break
                    if placed:
                        break
        for worker in workers:
            if worker.building_id is not None or worker.resource_id is not None or worker.attack_target is not None:
                continue
            nodes = [node for node in self.resources if node.amount > 0]
            preferred = "ore" if self.enemy_stock["ore"] < self.enemy_stock["wood"] * 1.5 else "wood"
            node = min(nodes, key=lambda item: math.dist((worker.x, worker.y), (item.x, item.y)) + (0 if item.kind == preferred else 150), default=None)
            if node:
                self.issue_harvest(node, worker_id=worker.id, owner=1)
        queued_workers = sum(order.kind == "worker" for order in hq.queue)
        if len(workers) + queued_workers < 4:
            self.enqueue("worker", building_id=hq.id, owner=1)
        for building in barracks:
            queued = sum(len(item.queue) for item in barracks)
            if building.complete and len(soldiers) + queued < 8:
                self.enqueue("soldier", building_id=building.id, owner=1)
        if len(soldiers) >= 3:
            target = next((building for building in self.buildings if building.owner == 0 and building.kind == "hq"), None)
            if target:
                for soldier in soldiers:
                    if soldier.hp < 25:
                        soldier.attack_target = None
                        self.set_destination(soldier, self.enemy_depot)
                    elif soldier.attack_target is None:
                        soldier.attack_target, soldier.repath_remaining = ("building", target.id), 0
        if len(soldiers) >= 3 and self.enemy_stock["ore"] >= 300 and self.enemy_stock["wood"] >= 200:
            self.upgrade(building_id=hq.id, owner=1)

    def enemy_at(self, x: float, y: float) -> Unit | Building | None:
        unit = next((unit for unit in self.units if unit.owner != 0 and math.dist((unit.x, unit.y), (x, y)) <= 18), None)
        if unit:
            return unit
        building = self.building_at(x, y)
        return building if building and building.owner != 0 else None

    @staticmethod
    def target_position(target: Unit | Building) -> tuple[float, float]:
        return target.center if isinstance(target, Building) else (target.x, target.y)

    def resolve_target(self, key: tuple[str, int] | None) -> Unit | Building | None:
        if key is None:
            return None
        return next((item for item in (self.units if key[0] == "unit" else self.buildings) if item.id == key[1] and item.hp > 0), None)

    def issue_attack(self, target: Unit | Building) -> bool:
        if not self.can_issue_order():
            return False
        if target.owner == 0 or target.hp <= 0 or not self.selected_units:
            self.notice = "공격할 적과 아군 유닛을 선택하세요."
            return False
        for unit in self.selected_units:
            unit.attack_target = ("building" if isinstance(target, Building) else "unit", target.id)
            unit.resource_id, unit.building_id, unit.returning = None, None, False
            unit.target, unit.path, unit.repath_remaining = None, [], 0
        self.notice = "적 공격 명령"
        return True

    def line_of_sight(self, start: tuple[float, float], end: tuple[float, float], target: Unit | Building) -> bool:
        steps = max(1, math.ceil(math.dist(start, end) / 8))
        for index in range(1, steps):
            t = index / steps
            x, y = start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t
            blocker = self.building_at(x, y)
            if self.world.tile_at(x, y) == "rock" or (blocker is not None and blocker is not target):
                return False
        return True

    def attack_position(self, unit: Unit, target: Unit | Building) -> tuple[float, float] | None:
        x, y = self.target_position(target)
        radius = UNIT_SPECS[unit.role]["range"] + (24 if isinstance(target, Building) else -8)
        points = [(x + math.cos(angle * math.pi / 8) * radius, y + math.sin(angle * math.pi / 8) * radius) for angle in range(16)]
        for point in sorted(points, key=lambda point: math.dist(point, (unit.x, unit.y))):
            if self.walkable(*point) and self.line_of_sight(point, (x, y), target) and self.find_path((unit.x, unit.y), point):
                return point
        return None

    def update_combat(self, dt: float) -> None:
        for unit in self.units:
            if unit.hp <= 0:
                continue
            spec = UNIT_SPECS[unit.role]
            unit.cooldown = max(0, unit.cooldown - dt)
            unit.repath_remaining = max(0, unit.repath_remaining - dt)
            target = self.resolve_target(unit.attack_target)
            if target is None:
                unit.attack_target = None
                if unit.target is not None or unit.resource_id is not None or unit.building_id is not None:
                    continue
                enemies = [other for other in [*self.units, *self.buildings] if other.owner != unit.owner and other.hp > 0
                           and math.dist((unit.x, unit.y), self.target_position(other)) <= spec["vision"]]
                target = min(enemies, key=lambda other: math.dist((unit.x, unit.y), self.target_position(other)), default=None)
                if target is None:
                    continue
                unit.attack_target = ("building" if isinstance(target, Building) else "unit", target.id)
            position = self.target_position(target)
            radius = spec["range"] + (32 if isinstance(target, Building) else 0)
            if math.dist((unit.x, unit.y), position) <= radius and self.line_of_sight((unit.x, unit.y), position, target):
                unit.target, unit.path = None, []
                if unit.cooldown <= 0:
                    self.statistics[unit.owner]["damage_dealt"] += min(target.hp, spec["damage"])
                    target.hp = max(0, target.hp - spec["damage"])
                    if target.hp == 0:
                        self.statistics[unit.owner]["buildings_destroyed" if isinstance(target, Building) else "kills"] += 1
                    unit.cooldown = spec["cooldown"]
            elif unit.repath_remaining <= 0:
                point = self.attack_position(unit, target)
                if point:
                    self.set_destination(unit, point)
                unit.repath_remaining = 0.8
        for unit in self.units:
            if unit.hp <= 0:
                self.statistics[unit.owner]["units_lost"] += 1
        self.units[:] = [unit for unit in self.units if unit.hp > 0]
        destroyed = [item for item in self.buildings if item.hp <= 0]
        if destroyed:
            for building in destroyed:
                self.statistics[building.owner]["buildings_lost"] += 1
            self.buildings[:] = [item for item in self.buildings if item.hp > 0]
            self.refresh_capacity()
        self.selected_ids.intersection_update(unit.id for unit in self.units)
        if not any(item.id == self.selected_building for item in self.buildings):
            self.selected_building = None

    def update(self, dt: float) -> None:
        if dt < 0 or not math.isfinite(dt):
            raise ValueError("시간 간격은 유한한 양수여야 합니다.")
        if self.paused or self.result != "running":
            return
        self.elapsed += dt
        self.update_enemy_ai(dt)
        for unit in self.units:
            self.move_unit(unit, dt)
        for worker in self.units:
            self.update_harvest(worker, dt)
        self.update_buildings(dt)
        self.update_production(dt)
        self.update_combat(dt)
        self.evaluate_result()
