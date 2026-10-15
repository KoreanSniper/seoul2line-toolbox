from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field


DEFAULT_GRID_SIZE = 112
DEFAULT_UNIT_SPEED = 34.0
UNIT_RADIUS = 3.2
SELECTION_RADIUS = 11.0
MAX_WALKABLE_SLOPE = 0.66
SLOW_SLOPE = 0.30
WATER_BLOCK_THRESHOLD = 0.45
BUILD_RANGE = 10.0
BUILDING_PLACEMENT_MAX_SLOPE = 0.28
SOLDIER_HEALTH = 100.0
SOLDIER_ATTACK_DAMAGE = 12.0
SOLDIER_ATTACK_RANGE = 58.0
SOLDIER_ATTACK_COOLDOWN = 0.85
SOLDIER_SPEED = 38.0
ATTACK_TARGET_RADIUS = 13.0
LINE_OF_SIGHT_EYE_HEIGHT = 6.0
LINE_OF_SIGHT_TERRAIN_MARGIN = 2.0
RELATION_NEUTRAL = "NEUTRAL"
RELATION_FRIENDLY = "FRIENDLY"
RELATION_ALLIED = "ALLIED"
RELATION_HOSTILE = "HOSTILE"
RELATION_AT_WAR = "AT_WAR"
CAPITAL_COUNT = 8
CAPITAL_CANDIDATE_GRID = 48
CAPITAL_MAX_SLOPE = BUILDING_PLACEMENT_MAX_SLOPE
REPATH_COOLDOWN = 0.45
MAX_REPATH_ATTEMPTS = 5
SEGMENT_SAMPLE_SPACING_FACTOR = 0.25
MAX_PATH_VALIDATION_PASSES = 12
NATION_COLORS = (
    (0.20, 0.68, 0.96),
    (0.92, 0.18, 0.18),
    (0.18, 0.78, 0.48),
    (0.92, 0.72, 0.20),
    (0.64, 0.38, 0.92),
    (0.92, 0.42, 0.70),
    (0.22, 0.82, 0.82),
    (0.88, 0.50, 0.20),
)
NATION_NAMES = ("Seoul", "Hanbit", "Mirae", "Baekdu", "Nara", "Haneul", "Geumgang", "Sudo")


@dataclass(frozen=True)
class BuildingType:
    id: str
    name: str
    footprint_radius: float
    height: float
    build_time: float


HOUSE = BuildingType("house", "House", footprint_radius=13.0, height=18.0, build_time=6.0)
BUILDING_TYPES = {HOUSE.id: HOUSE}


@dataclass
class Nation:
    id: int
    name: str
    color: tuple[float, float, float]
    capital_x: float
    capital_z: float
    unit_ids: list[int] = field(default_factory=list)
    building_ids: list[int] = field(default_factory=list)
    territory: list[tuple[float, float, float]] = field(default_factory=list)
    diplomatic_relations: dict[int, str] = field(default_factory=dict)
    current_wars: set[int] = field(default_factory=set)
    alliances: set[int] = field(default_factory=set)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge0 == edge1:
        return 0.0
    t = clamp((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp(t, 0.0, 1.0)


@dataclass(frozen=True)
class TerrainSample:
    x: float
    z: float
    height: float
    slope: float
    water: float
    walkable: bool


@dataclass
class RendererTerrainSource:
    size: int
    scale: float
    height_scale: float
    seed: float
    erosion: float
    max_walkable_slope: float = MAX_WALKABLE_SLOPE
    _base_cache: dict[tuple[int, int], float] = field(default_factory=dict, init=False)
    _height_cache: dict[tuple[int, int], float] = field(default_factory=dict, init=False)
    _water_cache: dict[tuple[int, int], float] = field(default_factory=dict, init=False)

    @property
    def half_extent(self) -> float:
        return (self.size - 1) * self.scale * 0.5

    def update_seed(self, seed: float, erosion: float) -> None:
        self.seed = seed
        self.erosion = erosion
        self._base_cache.clear()
        self._height_cache.clear()
        self._water_cache.clear()

    def world_to_uv(self, x: float, z: float) -> tuple[float, float]:
        half = self.half_extent
        u = (x + half) / (half * 2.0)
        v = (z + half) / (half * 2.0)
        return clamp(u, 0.0, 1.0), clamp(v, 0.0, 1.0)

    def uv_to_world(self, u: float, v: float) -> tuple[float, float]:
        half = self.half_extent
        return (clamp(u, 0.0, 1.0) * 2.0 - 1.0) * half, (clamp(v, 0.0, 1.0) * 2.0 - 1.0) * half

    def terrain_height(self, x: float, z: float) -> float:
        u, v = self.world_to_uv(x, z)
        key = (int(round(u * 2048)), int(round(v * 2048)))
        cached = self._height_cache.get(key)
        if cached is not None:
            return cached
        value = self.world_height_uv(u, v) * self.height_scale
        self._height_cache[key] = value
        return value

    def slope(self, x: float, z: float) -> float:
        step = self.scale
        left = self.terrain_height(x - step, z)
        right = self.terrain_height(x + step, z)
        down = self.terrain_height(x, z - step)
        up = self.terrain_height(x, z + step)
        return math.hypot(right - left, up - down) / (step * 2.0)

    def normal(self, x: float, z: float) -> tuple[float, float, float]:
        step = self.scale
        left = self.terrain_height(x - step, z)
        right = self.terrain_height(x + step, z)
        down = self.terrain_height(x, z - step)
        up = self.terrain_height(x, z + step)
        nx = left - right
        ny = step * 2.0
        nz = down - up
        length = max(0.0001, math.sqrt(nx * nx + ny * ny + nz * nz))
        return nx / length, ny / length, nz / length

    def water_amount(self, x: float, z: float) -> float:
        u, v = self.world_to_uv(x, z)
        key = (int(round(u * 2048)), int(round(v * 2048)))
        cached = self._water_cache.get(key)
        if cached is not None:
            return cached
        h = self.terrain_base_height_uv(u, v)
        ocean = self.ocean_mask_uv(u, v)
        river = self.river_mask_uv(u, v) * smoothstep(0.115, 0.42, h) * (1.0 - smoothstep(0.64, 0.86, h)) * (1.0 - ocean)
        lake_allowed = (1.0 - smoothstep(0.19, 0.30, h)) * smoothstep(0.075, 0.135, h)
        lake = self.lake_mask_uv(u, v) * lake_allowed * (1.0 - river * 0.55) * (1.0 - ocean)
        value = clamp(max(ocean, river, lake), 0.0, 1.0)
        self._water_cache[key] = value
        return value

    def is_water(self, x: float, z: float) -> bool:
        return self.water_amount(x, z) > WATER_BLOCK_THRESHOLD

    def is_inside(self, x: float, z: float) -> bool:
        half = self.half_extent
        return -half <= x <= half and -half <= z <= half

    def sample(self, x: float, z: float) -> TerrainSample:
        u, v = self.world_to_uv(x, z)
        slope = self.slope(x, z)
        water = self.water_amount(x, z)
        edge_cliff = self.edge_cliff_mask_uv(u, v)
        walkable = self.is_inside(x, z) and edge_cliff < 0.18 and water <= WATER_BLOCK_THRESHOLD and slope <= self.max_walkable_slope
        return TerrainSample(x=x, z=z, height=self.terrain_height(x, z), slope=slope, water=water, walkable=walkable)

    def is_walkable(self, x: float, z: float) -> bool:
        return self.sample(x, z).walkable

    def movement_cost_multiplier(self, x: float, z: float) -> float:
        slope = self.slope(x, z)
        if slope <= SLOW_SLOPE:
            return 1.0
        return 1.0 + (slope - SLOW_SLOPE) * 2.2

    def hash2(self, x: float, y: float) -> float:
        value = math.sin((x + self.seed * 0.013) * 127.1 + (y + self.seed * 0.021) * 311.7) * 43758.5453123
        return value - math.floor(value)

    def value_noise(self, x: float, y: float) -> float:
        x0 = math.floor(x)
        y0 = math.floor(y)
        sx = smoothstep(0.0, 1.0, x - x0)
        sy = smoothstep(0.0, 1.0, y - y0)
        top = mix(self.hash2(x0, y0), self.hash2(x0 + 1, y0), sx)
        bottom = mix(self.hash2(x0, y0 + 1), self.hash2(x0 + 1, y0 + 1), sx)
        return mix(top, bottom, sy)

    def fbm(self, x: float, y: float) -> float:
        total = 0.0
        amp = 0.5
        for _ in range(4):
            total += self.value_noise(x, y) * amp
            x = x * 2.01 + 12.7
            y = y * 2.01 + 6.3
            amp *= 0.52
        return total

    def ridged(self, x: float, y: float) -> float:
        n = self.value_noise(x, y)
        r = 1.0 - abs(n * 2.0 - 1.0)
        n2 = self.value_noise(x * 2.07 + 5.0, y * 2.07 + 13.0)
        r2 = 1.0 - abs(n2 * 2.0 - 1.0)
        return r * r * 0.68 + r2 * r2 * 0.32

    def _macro_rotate(self, u: float, v: float) -> tuple[float, float]:
        """seed 에 따라 (u, v) 를 정규 매크로 좌표 (mu, mv) 로 변환.
        정규 좌표 기준:
        - 산악 코너 = (0, 0)
        - 해양 코너 = (1, 1)
        - 강 대각선 = mu + mv = 1
        """
        rotation = int(abs(self.seed)) % 4

        if rotation == 0:
            return u, v
        elif rotation == 1:
            return 1.0 - u, v
        elif rotation == 2:
            return 1.0 - u, 1.0 - v
        else:
            return u, 1.0 - v

    def _macro_diagonal_mask(self, u: float, v: float) -> float:
        """강/협곡 대각선 통로 마스크 (0~1).
        높을수록 대각선 중심에 가깝다.
        """
        mu, mv = self._macro_rotate(u, v)
        river_dist = abs(mu + mv - 1.0)

        return max(0.0, 1.0 - river_dist / 0.26) ** 1.6

    def edge_cliff_mask_uv(self, u: float, v: float) -> float:
        edge_distance = min(min(u, 1.0 - u), min(v, 1.0 - v))
        rough_edge = edge_distance + (self.fbm(u * 9.0 + 211.0, v * 9.0 + 211.0) - 0.5) * 0.028
        cliff = 1.0 - smoothstep(0.010, 0.055, rough_edge)
        inner_ridge = 1.0 - smoothstep(0.030, 0.090, edge_distance)
        return clamp(max(cliff, inner_ridge * 0.12), 0.0, 1.0)

    def terrain_base_height_uv(self, u: float, v: float) -> float:
        key = (int(round(u * 2048)), int(round(v * 2048)))
        cached = self._base_cache.get(key)
        if cached is not None:
            return cached

        # ── 매크로 영향권 계산 ──────────────────────────────────────
        mu, mv = self._macro_rotate(u, v)

        macro_mountain = max(
            0.0,
            1.0 - math.sqrt(mu * mu + mv * mv) / 0.72
        ) ** 1.6

        macro_ocean = max(
            0.0,
            1.0 - math.sqrt(
                (mu - 1.0) ** 2 + (mv - 1.0) ** 2
            ) / 0.72
        ) ** 1.4

        macro_river = self._macro_diagonal_mask(u, v)

        # ── 도메인 워핑 세부 지형 ────────────────────────────────────
        warp_x = self.fbm(
            u * 2.6 + 13.0,
            v * 2.6 + 17.0
        ) - 0.5

        warp_y = self.fbm(
            u * 2.6 + 53.0,
            v * 2.6 + 71.0
        ) - 0.5

        wu = u + warp_x * 0.18
        wv = v + warp_y * 0.18

        base_plains = (
            0.16
            + (
                self.fbm(
                    wu * 2.8 + 5.0,
                    wv * 2.8 + 9.0
                ) - 0.5
            ) * 0.07
        )

        ridge_raw = self.ridged(
            wu * 3.6 + 31.0,
            wv * 3.6 + 47.0
        )

        mountain_ridges = (ridge_raw ** 1.8) * 0.60

        peak_noise = self.ridged(
            wu * 6.5 + 101.0,
            wv * 6.5 + 113.0
        )

        peaks = (
            (peak_noise ** 2.2)
            * 0.22
            * smoothstep(
                0.30,
                0.60,
                mountain_ridges
            )
        )

        valley_mask = smoothstep(
            0.20,
            0.55,
            self.fbm(
                wu * 3.0 + 83.0,
                wv * 3.0 + 97.0
            )
        )

        pass_carve = (
            smoothstep(
                0.48,
                0.65,
                valley_mask
            )
            * (
                1.0
                - smoothstep(
                    0.70,
                    0.85,
                    valley_mask
                )
            )
        )

        h = base_plains + mountain_ridges + peaks

        h -= (
            pass_carve
            * 0.32
            * smoothstep(
                0.25,
                0.70,
                mountain_ridges
            )
        )

        # ── 매크로 구조 적용 ────────────────────────────────────────
        h += macro_mountain * 0.48

        h = mix(
            h,
            0.06,
            macro_ocean * 0.85
        )

        h = mix(
            h,
            min(h, 0.20),
            macro_river * 0.70
        )
        value = clamp(h, 0.04, 0.95)
        self._base_cache[key] = value
        return value

    def ocean_mask_uv(self, u: float, v: float) -> float:
        edge_distance = min(min(u, 1.0 - u), min(v, 1.0 - v))
        border_water = 1.0 - smoothstep(0.010, 0.060, edge_distance)
        edge_cliff = self.edge_cliff_mask_uv(u, v)
        return clamp(border_water * 0.35 * (1.0 - edge_cliff * 0.92), 0.0, 1.0)

    def river_mask_uv(self, u: float, v: float) -> float:
        px = u * 8.0
        py = v * 8.0

        channel = (
            self.ridged(
                px * 0.92 + 31.0,
                py * 0.92 + 9.0
            ) ** 2.8
        )

        noise_river = smoothstep(
            0.58,
            0.86,
            channel
        )

        macro_river = (
            self._macro_diagonal_mask(u, v)
            * 0.80
        )

        return clamp(
            max(noise_river, macro_river),
            0.0,
            1.0
        )

    def lake_mask_uv(self, u: float, v: float) -> float:
        px = u * 8.0
        py = v * 8.0
        basin = 1.0 - smoothstep(0.39, 0.58, self.fbm(px * 0.42 + 81.0, py * 0.42 + 81.0) * 0.70 + self.fbm(px * 0.95 + 12.0, py * 0.95 + 12.0) * 0.30)
        pools = smoothstep(0.60, 0.86, basin + self.value_noise(px * 1.1 + 9.0, py * 1.1 + 2.0) * 0.24)
        return clamp(pools, 0.0, 1.0)

    def world_height_uv(self, u: float, v: float) -> float:
        h = self.terrain_base_height_uv(u, v)
        ocean = self.ocean_mask_uv(u, v)
        river_allowed = smoothstep(0.24, 0.42, h) * (1.0 - smoothstep(0.58, 0.76, h))
        river = self.river_mask_uv(u, v) * river_allowed * (1.0 - ocean) * 0.62
        lake_allowed = (1.0 - smoothstep(0.24, 0.34, h)) * smoothstep(0.12, 0.18, h)
        lake = self.lake_mask_uv(u, v) * lake_allowed * (1.0 - river * 0.45) * (1.0 - ocean) * 0.55
        h = mix(h, max(0.150, h - 0.035), river)
        h = mix(h, min(h, 0.078), ocean)
        h = mix(h, 0.170, lake * (1.0 - smoothstep(0.170, 0.245, h)))
        return clamp(h, 0.025, 1.0)


@dataclass
class WorldInterface:
    terrain: RendererTerrainSource

    @property
    def size(self) -> int:
        return self.terrain.size

    @property
    def scale(self) -> float:
        return self.terrain.scale

    @property
    def height_scale(self) -> float:
        return self.terrain.height_scale

    @property
    def half_extent(self) -> float:
        return self.terrain.half_extent

    @property
    def max_walkable_slope(self) -> float:
        return self.terrain.max_walkable_slope

    def update_seed(self, seed: float, erosion: float) -> None:
        self.terrain.update_seed(seed, erosion)

    def world_to_uv(self, x: float, z: float) -> tuple[float, float]:
        return self.terrain.world_to_uv(x, z)

    def uv_to_world(self, u: float, v: float) -> tuple[float, float]:
        return self.terrain.uv_to_world(u, v)

    def terrain_height(self, x: float, z: float) -> float:
        return self.terrain.terrain_height(x, z)

    def slope(self, x: float, z: float) -> float:
        return self.terrain.slope(x, z)

    def normal(self, x: float, z: float) -> tuple[float, float, float]:
        return self.terrain.normal(x, z)

    def water_amount(self, x: float, z: float) -> float:
        return self.terrain.water_amount(x, z)

    def is_water(self, x: float, z: float) -> bool:
        return self.terrain.is_water(x, z)

    def is_inside(self, x: float, z: float) -> bool:
        return self.terrain.is_inside(x, z)

    def sample(self, x: float, z: float) -> TerrainSample:
        return self.terrain.sample(x, z)

    def is_walkable(self, x: float, z: float) -> bool:
        return self.terrain.is_walkable(x, z)

    def movement_cost_multiplier(self, x: float, z: float) -> float:
        return self.terrain.movement_cost_multiplier(x, z)


@dataclass
class NavigationGrid:
    world: WorldInterface
    resolution: int = DEFAULT_GRID_SIZE
    walkable: list[list[bool]] = field(default_factory=list)
    slope_cost: list[list[float]] = field(default_factory=list)
    blocked_circles: list[tuple[float, float, float]] = field(default_factory=list)
    static_edge_cache: dict[tuple[int, int, int, int], bool] = field(default_factory=dict)
    static_edge_cache_complete: bool = False
    static_edge_cache_source: str = "lazy_cpu"
    timing_diagnostics: dict[str, float | int | str] = field(default_factory=dict)
    debug_timing: bool = False

    def rebuild(self, progress_callback: object | None = None) -> None:
        rebuild_start = time.perf_counter()
        self.walkable = []
        self.slope_cost = []
        self.static_edge_cache.clear()
        self.static_edge_cache_complete = False
        self.static_edge_cache_source = "lazy_cpu"
        self.timing_diagnostics = {}
        grid_start = time.perf_counter()
        for gy in range(self.resolution):
            walk_row: list[bool] = []
            cost_row: list[float] = []
            for gx in range(self.resolution):
                x, z = self.grid_to_world(gx, gy)
                sample = self.world.sample(x, z)
                walk_row.append(sample.walkable)
                cost_row.append(self.world.movement_cost_multiplier(x, z))
            self.walkable.append(walk_row)
            self.slope_cost.append(cost_row)
            if progress_callback is not None and (gy % 3 == 0 or gy == self.resolution - 1):
                progress_callback(gy / max(1, self.resolution - 1), f"Building navigation {gy + 1}/{self.resolution}")
        self.timing_diagnostics["navigation_grid_build_ms"] = (time.perf_counter() - grid_start) * 1000.0
        self.timing_diagnostics["gpu_edge_status"] = "lazy_candidate_validation"
        self.timing_diagnostics["navigation_rebuild_total_ms"] = (time.perf_counter() - rebuild_start) * 1000.0
        if self.debug_timing:
            self.run_path_timing_probe()

    def grid_to_world(self, gx: int, gy: int) -> tuple[float, float]:
        half = self.world.half_extent
        u = gx / max(1, self.resolution - 1)
        v = gy / max(1, self.resolution - 1)
        return mix(-half, half, u), mix(-half, half, v)

    def world_to_grid(self, x: float, z: float) -> tuple[int, int]:
        half = self.world.half_extent
        gx = round((clamp(x, -half, half) + half) / (half * 2.0) * (self.resolution - 1))
        gy = round((clamp(z, -half, half) + half) / (half * 2.0) * (self.resolution - 1))
        return int(gx), int(gy)

    def is_grid_walkable(self, gx: int, gy: int) -> bool:
        if not (0 <= gx < self.resolution and 0 <= gy < self.resolution and self.walkable[gy][gx]):
            return False
        x, z = self.grid_to_world(gx, gy)
        return not self.is_blocked_by_circle(x, z)

    def is_blocked_by_circle(self, x: float, z: float) -> bool:
        for bx, bz, radius in self.blocked_circles:
            if math.hypot(x - bx, z - bz) <= radius:
                return True
        return False

    def is_segment_blocked_by_circle(self, start: tuple[float, float], end: tuple[float, float]) -> bool:
        sx, sz = start
        ex, ez = end
        dx = ex - sx
        dz = ez - sz
        length_sq = dx * dx + dz * dz
        for bx, bz, radius in self.blocked_circles:
            if length_sq <= 0.000001:
                if math.hypot(sx - bx, sz - bz) <= radius:
                    return True
                continue
            t = clamp(((bx - sx) * dx + (bz - sz) * dz) / length_sq, 0.0, 1.0)
            closest_x = sx + dx * t
            closest_z = sz + dz * t
            if math.hypot(closest_x - bx, closest_z - bz) <= radius:
                return True
        return False

    def set_building_blockers(self, buildings: list[Building]) -> None:
        self.blocked_circles = [
            (building.x, building.z, building.building_type.footprint_radius + UNIT_RADIUS)
            for building in buildings
        ]

    def iter_static_neighbor_edges(self) -> list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]]:
        edges: list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]] = []
        directions = ((1, 0), (0, 1), (1, 1), (1, -1))
        for gy in range(self.resolution):
            for gx in range(self.resolution):
                for dx, dy in directions:
                    nx = gx + dx
                    ny = gy + dy
                    if not (0 <= nx < self.resolution and 0 <= ny < self.resolution):
                        continue
                    key = self.static_edge_key(gx, gy, nx, ny)
                    edges.append((key, self.grid_to_world(gx, gy), self.grid_to_world(nx, ny)))
        return edges

    def build_edge_sample_buffers(
        self,
        edges: list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]],
        progress_callback: object | None = None,
    ) -> tuple[object, object, object, object]:
        import numpy as np

        edge_meta: list[int] = []
        edge_sample_indices: list[int] = []
        edge_sample_distances: list[float] = []
        sample_positions: list[tuple[float, float]] = []
        sample_position_to_index: dict[tuple[int, int], int] = {}
        spacing = max(1.0, self.world.scale * SEGMENT_SAMPLE_SPACING_FACTOR)

        def sample_index_for(x: float, z: float) -> int:
            key = (int(round(x * 100000.0)), int(round(z * 100000.0)))
            existing = sample_position_to_index.get(key)
            if existing is not None:
                return existing
            index = len(sample_positions)
            sample_position_to_index[key] = index
            sample_positions.append((x, z))
            return index

        topology_start = time.perf_counter()
        for edge_index, (_key, start, end) in enumerate(edges):
            sx, sz = start
            ex, ez = end
            distance = math.hypot(ex - sx, ez - sz)
            steps = max(0, max(2, int(math.ceil(distance / spacing))) if distance > 0.001 else 0)
            offset = len(edge_sample_indices)
            count = steps + 1
            last_x = sx
            last_z = sz
            for sample_index in range(count):
                t = sample_index / max(1, steps)
                x = mix(sx, ex, t)
                z = mix(sz, ez, t)
                edge_sample_indices.append(sample_index_for(x, z))
                edge_sample_distances.append(0.0 if sample_index == 0 else math.hypot(x - last_x, z - last_z))
                last_x = x
                last_z = z
            edge_meta.extend((offset, count, 0, 0))
            if progress_callback is not None and edge_index % 1536 == 0:
                progress_callback(1.0, f"Indexing shared nav samples {edge_index + 1}/{len(edges)}")
        self.timing_diagnostics["candidate_nav_sample_field_index_ms"] = (
            float(self.timing_diagnostics.get("candidate_nav_sample_field_index_ms", 0.0))
            + (time.perf_counter() - topology_start) * 1000.0
        )

        sample_start = time.perf_counter()
        sample_data: list[float] = []
        for index, (x, z) in enumerate(sample_positions):
            sample = self.world.sample(x, z)
            sample_data.extend((sample.height, sample.water, 1.0 if sample.walkable else 0.0, 0.0))
            if progress_callback is not None and index % 4096 == 0:
                progress_callback(1.0, f"Sampling shared nav field {index + 1}/{len(sample_positions)}")
        self.timing_diagnostics["candidate_nav_sample_field_sample_ms"] = (
            float(self.timing_diagnostics.get("candidate_nav_sample_field_sample_ms", 0.0))
            + (time.perf_counter() - sample_start) * 1000.0
        )
        self.timing_diagnostics["candidate_nav_sample_field_unique_samples"] = (
            int(self.timing_diagnostics.get("candidate_nav_sample_field_unique_samples", 0)) + len(sample_positions)
        )
        self.timing_diagnostics["candidate_nav_edge_sample_references"] = (
            int(self.timing_diagnostics.get("candidate_nav_edge_sample_references", 0)) + len(edge_sample_indices)
        )
        return (
            np.array(edge_meta, dtype=np.int32),
            np.array(edge_sample_indices, dtype=np.int32),
            np.array(edge_sample_distances, dtype=np.float32),
            np.array(sample_data, dtype=np.float32),
        )

    def precompute_static_edges_gpu(self, progress_callback: object | None = None) -> None:
        edges = self.iter_static_neighbor_edges()
        self.timing_diagnostics["static_edge_count"] = len(edges)
        try:
            self.detect_compute_shader_context()
        except Exception as exc:
            self.timing_diagnostics["gpu_edge_status"] = f"fallback_cpu: {exc.__class__.__name__}"
            return
        if progress_callback is not None:
            progress_callback(1.0, "Preparing GPU navigation edge cache")
        prep_start = time.perf_counter()
        try:
            edge_meta, edge_sample_indices, edge_sample_distances, sample_data = self.build_edge_sample_buffers(edges, progress_callback)
        except Exception as exc:
            self.timing_diagnostics["gpu_edge_status"] = f"sample_prep_failed: {exc.__class__.__name__}"
            return
        self.timing_diagnostics["nav_sample_field_prepare_ms"] = (time.perf_counter() - prep_start) * 1000.0
        try:
            results, upload_ms, gpu_ms, readback_ms, version = self.dispatch_edge_compute(
                edge_meta,
                edge_sample_indices,
                edge_sample_distances,
                sample_data,
                len(edges),
            )
        except Exception as exc:
            self.timing_diagnostics["gpu_edge_status"] = f"fallback_cpu: {exc.__class__.__name__}"
            return
        self.timing_diagnostics["opengl_version"] = version
        self.timing_diagnostics["gpu_edge_upload_ms"] = upload_ms
        self.timing_diagnostics["gpu_edge_precompute_ms"] = gpu_ms
        self.timing_diagnostics["gpu_edge_readback_ms"] = readback_ms

        mismatches = self.validate_gpu_edge_results(edges, results)
        self.timing_diagnostics["gpu_edge_validation_mismatches"] = mismatches
        if mismatches:
            self.static_edge_cache.clear()
            self.static_edge_cache_complete = False
            self.static_edge_cache_source = "lazy_cpu"
            self.timing_diagnostics["gpu_edge_status"] = "validation_failed_fallback_cpu"
            print(f"GPU nav edge validation failed with {mismatches} mismatch(es); falling back to CPU lazy edge cache.")
            return

        self.static_edge_cache = {key: bool(results[index]) for index, (key, _start, _end) in enumerate(edges)}
        self.static_edge_cache_complete = True
        self.static_edge_cache_source = "gpu"
        self.timing_diagnostics["gpu_edge_status"] = "enabled"

    def detect_compute_shader_context(self) -> str:
        from OpenGL.GL import GL_VERSION, glGetString

        version_bytes = glGetString(GL_VERSION)
        if not version_bytes:
            raise RuntimeError("no current OpenGL context")
        version = version_bytes.decode("ascii", errors="replace") if isinstance(version_bytes, bytes) else str(version_bytes)
        major_minor = version.split()[0].split(".")
        major = int(major_minor[0]) if major_minor and major_minor[0].isdigit() else 0
        minor = int(major_minor[1]) if len(major_minor) > 1 and major_minor[1].isdigit() else 0
        if (major, minor) < (4, 3):
            raise RuntimeError(f"OpenGL {version} does not support compute shaders")
        return version

    def dispatch_edge_compute(
        self,
        edge_meta: object,
        edge_sample_indices: object,
        edge_sample_distances: object,
        sample_data: object,
        edge_count: int,
    ) -> tuple[object, float, float, float, str]:
        import numpy as np
        from OpenGL.GL import (
            GL_BUFFER_UPDATE_BARRIER_BIT,
            GL_COMPILE_STATUS,
            GL_COMPUTE_SHADER,
            GL_LINK_STATUS,
            GL_SHADER_STORAGE_BARRIER_BIT,
            GL_SHADER_STORAGE_BUFFER,
            GL_STATIC_DRAW,
            GL_VERSION,
            glAttachShader,
            glBindBuffer,
            glBindBufferBase,
            glBufferData,
            glCompileShader,
            glCreateProgram,
            glCreateShader,
            glDeleteBuffers,
            glDeleteProgram,
            glDeleteShader,
            glDispatchCompute,
            glFinish,
            glGenBuffers,
            glGetBufferSubData,
            glGetProgramInfoLog,
            glGetProgramiv,
            glGetShaderInfoLog,
            glGetShaderiv,
            glGetString,
            glLinkProgram,
            glMemoryBarrier,
            glShaderSource,
            glUseProgram,
        )

        version_bytes = glGetString(GL_VERSION)
        if not version_bytes:
            raise RuntimeError("no current OpenGL context")
        version = version_bytes.decode("ascii", errors="replace") if isinstance(version_bytes, bytes) else str(version_bytes)
        major_minor = version.split()[0].split(".")
        major = int(major_minor[0]) if major_minor and major_minor[0].isdigit() else 0
        minor = int(major_minor[1]) if len(major_minor) > 1 and major_minor[1].isdigit() else 0
        if (major, minor) < (4, 3):
            raise RuntimeError(f"OpenGL {version} does not support compute shaders")

        shader_source = f"""
#version 430
layout(local_size_x = 128) in;
layout(std430, binding = 0) readonly buffer EdgeMeta {{
    ivec4 edges[];
}};
layout(std430, binding = 1) readonly buffer SampleData {{
    vec4 samples[];
}};
layout(std430, binding = 2) readonly buffer EdgeSampleIndices {{
    int sampleIndices[];
}};
layout(std430, binding = 3) readonly buffer EdgeSampleDistances {{
    float sampleDistances[];
}};
layout(std430, binding = 4) writeonly buffer EdgeResult {{
    uint results[];
}};
uniform int edgeCount;
uniform float waterThreshold;
uniform float maxWalkableSlope;

void main() {{
    uint edgeIndex = gl_GlobalInvocationID.x;
    if (edgeIndex >= uint(edgeCount)) {{
        return;
    }}
    ivec4 meta = edges[edgeIndex];
    int offset = meta.x;
    int count = meta.y;
    bool ok = count > 0;
    float lastHeight = 0.0;
    for (int i = 0; i < count; ++i) {{
        int edgeSampleIndex = offset + i;
        vec4 terrainSample = samples[sampleIndices[edgeSampleIndex]];
        float height = terrainSample.x;
        float water = terrainSample.y;
        float walkable = terrainSample.z;
        float distanceFromPrevious = sampleDistances[edgeSampleIndex];
        if (walkable < 0.5 || water > waterThreshold) {{
            ok = false;
            break;
        }}
        if (i > 0 && abs(height - lastHeight) / max(0.001, distanceFromPrevious) > maxWalkableSlope) {{
            ok = false;
            break;
        }}
        lastHeight = height;
    }}
    results[edgeIndex] = ok ? 1u : 0u;
}}
"""
        shader = glCreateShader(GL_COMPUTE_SHADER)
        program = glCreateProgram()
        buffers = glGenBuffers(5)
        buffer_ids = [int(buffers[index]) for index in range(5)] if hasattr(buffers, "__len__") else [int(buffers)]
        try:
            glShaderSource(shader, shader_source)
            glCompileShader(shader)
            if not glGetShaderiv(shader, GL_COMPILE_STATUS):
                raise RuntimeError(glGetShaderInfoLog(shader).decode("utf-8", errors="replace"))
            glAttachShader(program, shader)
            glLinkProgram(program)
            if not glGetProgramiv(program, GL_LINK_STATUS):
                raise RuntimeError(glGetProgramInfoLog(program).decode("utf-8", errors="replace"))

            results = np.zeros(edge_count, dtype=np.uint32)
            upload_start = time.perf_counter()
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer_ids[0])
            glBufferData(GL_SHADER_STORAGE_BUFFER, edge_meta.nbytes, edge_meta, GL_STATIC_DRAW)
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, buffer_ids[0])
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer_ids[1])
            glBufferData(GL_SHADER_STORAGE_BUFFER, sample_data.nbytes, sample_data, GL_STATIC_DRAW)
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, buffer_ids[1])
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer_ids[2])
            glBufferData(GL_SHADER_STORAGE_BUFFER, edge_sample_indices.nbytes, edge_sample_indices, GL_STATIC_DRAW)
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 2, buffer_ids[2])
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer_ids[3])
            glBufferData(GL_SHADER_STORAGE_BUFFER, edge_sample_distances.nbytes, edge_sample_distances, GL_STATIC_DRAW)
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 3, buffer_ids[3])
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer_ids[4])
            glBufferData(GL_SHADER_STORAGE_BUFFER, results.nbytes, results, GL_STATIC_DRAW)
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 4, buffer_ids[4])
            upload_ms = (time.perf_counter() - upload_start) * 1000.0

            from OpenGL.GL import glGetUniformLocation, glUniform1f, glUniform1i

            glUseProgram(program)
            glUniform1i(glGetUniformLocation(program, "edgeCount"), edge_count)
            glUniform1f(glGetUniformLocation(program, "waterThreshold"), WATER_BLOCK_THRESHOLD)
            glUniform1f(glGetUniformLocation(program, "maxWalkableSlope"), self.world.max_walkable_slope)
            dispatch_start = time.perf_counter()
            glDispatchCompute((edge_count + 127) // 128, 1, 1)
            glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_BUFFER_UPDATE_BARRIER_BIT)
            glFinish()
            gpu_ms = (time.perf_counter() - dispatch_start) * 1000.0

            readback_start = time.perf_counter()
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer_ids[4])
            readback = glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, results.nbytes)
            readback_ms = (time.perf_counter() - readback_start) * 1000.0
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)
            glUseProgram(0)
            return np.frombuffer(readback, dtype=np.uint32).copy(), upload_ms, gpu_ms, readback_ms, version
        finally:
            try:
                glUseProgram(0)
                glDeleteBuffers(len(buffer_ids), buffer_ids)
                glDeleteProgram(program)
                glDeleteShader(shader)
            except Exception:
                pass

    def validate_gpu_edge_results(
        self,
        edges: list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]],
        results: object,
        sample_count: int = 500,
    ) -> int:
        if not edges:
            return 0
        rng = random.Random(7331)
        indices = list(range(len(edges)))
        rng.shuffle(indices)
        indices = indices[: min(len(indices), sample_count)]
        mismatches = 0
        for index in indices:
            _key, start, end = edges[index]
            cpu_result = self.is_segment_terrain_traversable(start, end)
            gpu_result = bool(results[index])
            if cpu_result != gpu_result:
                mismatches += 1
                if mismatches <= 8:
                    print(
                        "GPU nav edge mismatch",
                        {"index": index, "start": start, "end": end, "cpu": cpu_result, "gpu": gpu_result},
                    )
        return mismatches

    def run_path_timing_probe(self) -> None:
        cells: list[tuple[int, int]] = []
        for gy, row in enumerate(self.walkable):
            for gx, ok in enumerate(row):
                if ok:
                    cells.append((gx, gy))
        if len(cells) < 2:
            self.timing_diagnostics["path_timing_probe"] = "skipped_no_walkable_cells"
            return
        start_cell = min(cells, key=lambda cell: cell[0] + cell[1])
        goal_cell = max(cells, key=lambda cell: cell[0] + cell[1])
        start = self.grid_to_world(*start_cell)
        goal = self.grid_to_world(*goal_cell)
        first_start = time.perf_counter()
        first_path = self.find_path(start, goal)
        first_ms = (time.perf_counter() - first_start) * 1000.0
        repeated_start = time.perf_counter()
        repeated_path = self.find_path(start, goal)
        repeated_ms = (time.perf_counter() - repeated_start) * 1000.0
        self.timing_diagnostics["first_long_path_query_ms"] = first_ms
        self.timing_diagnostics["repeated_long_path_query_ms"] = repeated_ms
        self.timing_diagnostics["timing_probe_first_path_len"] = len(first_path)
        self.timing_diagnostics["timing_probe_repeated_path_len"] = len(repeated_path)

    def diagnostics_summary(self) -> str:
        status = self.timing_diagnostics.get("gpu_edge_status", self.static_edge_cache_source)
        grid_ms = float(self.timing_diagnostics.get("navigation_grid_build_ms", 0.0))
        field_ms = float(self.timing_diagnostics.get("candidate_nav_sample_field_prepare_ms", 0.0))
        upload_ms = float(self.timing_diagnostics.get("candidate_gpu_edge_upload_ms", 0.0))
        gpu_ms = float(self.timing_diagnostics.get("candidate_gpu_edge_compute_ms", 0.0))
        read_ms = float(self.timing_diagnostics.get("candidate_gpu_edge_readback_ms", 0.0))
        query_ms = float(self.timing_diagnostics.get("last_path_query_ms", 0.0))
        first_ms = float(self.timing_diagnostics.get("first_long_path_query_ms", 0.0))
        repeat_ms = float(self.timing_diagnostics.get("repeated_long_path_query_ms", 0.0))
        path_label = f"probe {first_ms:.1f}/{repeat_ms:.1f}ms" if self.debug_timing else f"query {query_ms:.1f}ms"
        return f"Nav {status} grid {grid_ms:.0f}ms candidate field {field_ms:.0f}ms upload {upload_ms:.1f}ms gpu {gpu_ms:.1f}ms read {read_ms:.1f}ms {path_label}"

    def is_segment_traversable(self, start: tuple[float, float], end: tuple[float, float], check_blockers: bool = True) -> bool:
        if not self.is_segment_terrain_traversable(start, end):
            return False
        return not check_blockers or not self.is_segment_blocked_by_circle(start, end)

    def is_segment_terrain_traversable(self, start: tuple[float, float], end: tuple[float, float]) -> bool:
        sx, sz = start
        ex, ez = end
        distance = math.hypot(ex - sx, ez - sz)
        if distance <= 0.001:
            return self.world.is_walkable(sx, sz)
        spacing = max(1.0, self.world.scale * SEGMENT_SAMPLE_SPACING_FACTOR)
        steps = max(2, int(math.ceil(distance / spacing)))
        last_x = sx
        last_z = sz
        last_sample = self.world.sample(sx, sz)
        if not self.is_sample_terrain_traversable(last_sample):
            return False
        for index in range(1, steps + 1):
            t = index / steps
            x = mix(sx, ex, t)
            z = mix(sz, ez, t)
            sample = self.world.sample(x, z)
            if not self.is_sample_terrain_traversable(sample):
                return False
            sample_distance = max(0.001, math.hypot(x - last_x, z - last_z))
            if abs(sample.height - last_sample.height) / sample_distance > self.world.max_walkable_slope:
                return False
            last_x = x
            last_z = z
            last_sample = sample
        return True

    def is_sample_terrain_traversable(self, sample: TerrainSample) -> bool:
        return sample.walkable and sample.water <= WATER_BLOCK_THRESHOLD

    def static_edge_key(self, ax: int, ay: int, bx: int, by: int) -> tuple[int, int, int, int]:
        if (bx, by) < (ax, ay):
            return bx, by, ax, ay
        return ax, ay, bx, by

    def is_nav_edge_traversable(self, ax: int, ay: int, bx: int, by: int) -> bool:
        key = self.static_edge_key(ax, ay, bx, by)
        if self.static_edge_cache_complete:
            static_result = self.static_edge_cache[key]
        else:
            static_result = self.static_edge_cache.get(key)
        if static_result is None:
            static_result = self.is_segment_terrain_traversable(self.grid_to_world(ax, ay), self.grid_to_world(bx, by))
            self.static_edge_cache[key] = static_result
        if not static_result:
            return False
        return not self.is_segment_blocked_by_circle(self.grid_to_world(ax, ay), self.grid_to_world(bx, by))

    def is_nav_edge_search_allowed(self, ax: int, ay: int, bx: int, by: int) -> bool:
        key = self.static_edge_key(ax, ay, bx, by)
        static_result = self.static_edge_cache.get(key)
        if static_result is False:
            return False
        return not self.is_segment_blocked_by_circle(self.grid_to_world(ax, ay), self.grid_to_world(bx, by))

    def validate_static_edges(self, edges: list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]]) -> None:
        if not edges:
            return
        validation_start = time.perf_counter()
        results: object | None = None
        used_gpu = False
        try:
            self.detect_compute_shader_context()
            prep_start = time.perf_counter()
            edge_meta, edge_sample_indices, edge_sample_distances, sample_data = self.build_edge_sample_buffers(edges)
            self.timing_diagnostics["candidate_nav_sample_field_prepare_ms"] = (
                float(self.timing_diagnostics.get("candidate_nav_sample_field_prepare_ms", 0.0))
                + (time.perf_counter() - prep_start) * 1000.0
            )
            results, upload_ms, gpu_ms, readback_ms, version = self.dispatch_edge_compute(
                edge_meta,
                edge_sample_indices,
                edge_sample_distances,
                sample_data,
                len(edges),
            )
            self.timing_diagnostics["opengl_version"] = version
            self.timing_diagnostics["candidate_gpu_edge_upload_ms"] = float(self.timing_diagnostics.get("candidate_gpu_edge_upload_ms", 0.0)) + upload_ms
            self.timing_diagnostics["candidate_gpu_edge_compute_ms"] = float(self.timing_diagnostics.get("candidate_gpu_edge_compute_ms", 0.0)) + gpu_ms
            self.timing_diagnostics["candidate_gpu_edge_readback_ms"] = float(self.timing_diagnostics.get("candidate_gpu_edge_readback_ms", 0.0)) + readback_ms
            mismatches = self.validate_gpu_edge_results(edges, results)
            self.timing_diagnostics["candidate_gpu_edge_validation_mismatches"] = (
                int(self.timing_diagnostics.get("candidate_gpu_edge_validation_mismatches", 0)) + mismatches
            )
            if mismatches:
                results = None
            else:
                used_gpu = True
        except Exception as exc:
            self.timing_diagnostics["candidate_gpu_edge_status"] = f"fallback_cpu: {exc.__class__.__name__}"

        if results is None:
            cpu_start = time.perf_counter()
            cpu_results = [self.is_segment_terrain_traversable(start, end) for _key, start, end in edges]
            self.timing_diagnostics["candidate_cpu_edge_validation_ms"] = (
                float(self.timing_diagnostics.get("candidate_cpu_edge_validation_ms", 0.0))
                + (time.perf_counter() - cpu_start) * 1000.0
            )
            results = cpu_results

        for index, (key, _start, _end) in enumerate(edges):
            self.static_edge_cache[key] = bool(results[index])
        self.timing_diagnostics["candidate_edge_validation_batches"] = int(self.timing_diagnostics.get("candidate_edge_validation_batches", 0)) + 1
        self.timing_diagnostics["candidate_edge_validation_count"] = int(self.timing_diagnostics.get("candidate_edge_validation_count", 0)) + len(edges)
        self.timing_diagnostics["candidate_edge_validation_ms"] = (
            float(self.timing_diagnostics.get("candidate_edge_validation_ms", 0.0))
            + (time.perf_counter() - validation_start) * 1000.0
        )
        self.timing_diagnostics["candidate_edge_validation_mode"] = "gpu" if used_gpu else "cpu"

    def path_unknown_edges(self, cells: list[tuple[int, int]]) -> list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]]:
        edges: list[tuple[tuple[int, int, int, int], tuple[float, float], tuple[float, float]]] = []
        seen: set[tuple[int, int, int, int]] = set()
        for index in range(1, len(cells)):
            ax, ay = cells[index - 1]
            bx, by = cells[index]
            key = self.static_edge_key(ax, ay, bx, by)
            if key in seen or key in self.static_edge_cache:
                continue
            seen.add(key)
            edges.append((key, self.grid_to_world(ax, ay), self.grid_to_world(bx, by)))
        return edges

    def nearest_walkable_grid(self, x: float, z: float, radius: int = 8) -> tuple[int, int] | None:
        sx, sy = self.world_to_grid(x, z)
        if self.is_grid_walkable(sx, sy):
            return sx, sy
        best: tuple[int, int] | None = None
        best_dist = float("inf")
        for r in range(1, radius + 1):
            for gy in range(sy - r, sy + r + 1):
                for gx in range(sx - r, sx + r + 1):
                    if not self.is_grid_walkable(gx, gy):
                        continue
                    dist = abs(gx - sx) + abs(gy - sy)
                    if dist < best_dist:
                        best = (gx, gy)
                        best_dist = dist
            if best is not None:
                return best
        return None

    def find_path(self, start: tuple[float, float], goal: tuple[float, float]) -> list[tuple[float, float]]:
        start_grid = self.nearest_walkable_grid(*start)
        goal_grid = self.nearest_walkable_grid(*goal)
        if start_grid is None or goal_grid is None:
            return []
        if start_grid == goal_grid:
            return [goal] if self.is_segment_traversable(start, goal) else []

        query_start = time.perf_counter()
        for validation_pass in range(MAX_PATH_VALIDATION_PASSES):
            cells = self.find_candidate_cells(start_grid, goal_grid)
            if not cells:
                self.timing_diagnostics["last_path_validation_passes"] = validation_pass
                self.timing_diagnostics["last_path_query_ms"] = (time.perf_counter() - query_start) * 1000.0
                return []
            unknown_edges = self.path_unknown_edges(cells)
            if unknown_edges:
                self.validate_static_edges(unknown_edges)
                if any(self.static_edge_cache.get(key) is False for key, _start, _end in unknown_edges):
                    continue
            points = [self.grid_to_world(gx, gy) for gx, gy in cells]
            if points and not self.is_segment_traversable(start, points[0]):
                self.timing_diagnostics["last_path_validation_passes"] = validation_pass + 1
                self.timing_diagnostics["last_path_query_ms"] = (time.perf_counter() - query_start) * 1000.0
                return []
            if points and math.hypot(points[-1][0] - goal[0], points[-1][1] - goal[1]) > 0.001:
                if not self.is_segment_traversable(points[-1], goal):
                    self.timing_diagnostics["last_path_validation_passes"] = validation_pass + 1
                    self.timing_diagnostics["last_path_query_ms"] = (time.perf_counter() - query_start) * 1000.0
                    return []
                points.append(goal)
            self.timing_diagnostics["last_path_validation_passes"] = validation_pass + 1
            self.timing_diagnostics["last_path_query_ms"] = (time.perf_counter() - query_start) * 1000.0
            return points

        self.timing_diagnostics["last_path_validation_passes"] = MAX_PATH_VALIDATION_PASSES
        self.timing_diagnostics["last_path_query_ms"] = (time.perf_counter() - query_start) * 1000.0
        return []

    def find_candidate_cells(self, start_grid: tuple[int, int], goal_grid: tuple[int, int]) -> list[tuple[int, int]]:
        open_heap: list[tuple[float, tuple[int, int]]] = []
        heapq.heappush(open_heap, (0.0, start_grid))
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        cost_so_far: dict[tuple[int, int], float] = {start_grid: 0.0}
        neighbors = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414))

        while open_heap:
            _priority, current = heapq.heappop(open_heap)
            if current == goal_grid:
                break
            cx, cy = current
            for dx, dy, base_cost in neighbors:
                nx = cx + dx
                ny = cy + dy
                if not self.is_grid_walkable(nx, ny):
                    continue
                if dx != 0 and dy != 0 and (not self.is_grid_walkable(cx + dx, cy) or not self.is_grid_walkable(cx, cy + dy)):
                    continue
                if not self.is_nav_edge_search_allowed(cx, cy, nx, ny):
                    continue
                new_cost = cost_so_far[current] + base_cost * self.slope_cost[ny][nx]
                neighbor = (nx, ny)
                if neighbor not in cost_so_far or new_cost < cost_so_far[neighbor]:
                    cost_so_far[neighbor] = new_cost
                    priority = new_cost + math.hypot(goal_grid[0] - nx, goal_grid[1] - ny)
                    heapq.heappush(open_heap, (priority, neighbor))
                    came_from[neighbor] = current

        if goal_grid not in came_from:
            return []
        cells = [goal_grid]
        current = goal_grid
        while current != start_grid:
            current = came_from[current]
            cells.append(current)
        cells.reverse()
        return cells

    def is_path_traversable(self, points: list[tuple[float, float]]) -> bool:
        if not points:
            return False
        return all(self.is_segment_traversable(points[index - 1], points[index]) for index in range(1, len(points)))


def simplify_path(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    out = [points[0]]
    prev_dx = 0
    prev_dz = 0
    for index in range(1, len(points)):
        dx = round(points[index][0] - points[index - 1][0], 3)
        dz = round(points[index][1] - points[index - 1][1], 3)
        if index > 1 and (dx, dz) != (prev_dx, prev_dz):
            out.append(points[index - 1])
        prev_dx = dx
        prev_dz = dz
    out.append(points[-1])
    return out


@dataclass
class MoveCommand:
    target_x: float
    target_z: float
    path: list[tuple[float, float]]
    repath_timer: float = 0.0
    repath_attempts: int = 0


@dataclass
class BuildCommand:
    building_type: BuildingType
    x: float
    z: float
    path: list[tuple[float, float]]
    started: bool = False
    building_id: int | None = None
    repath_timer: float = 0.0
    repath_attempts: int = 0


@dataclass
class AttackCommand:
    target_unit_id: int
    path: list[tuple[float, float]] = field(default_factory=list)
    repath_timer: float = 0.0


@dataclass
class StrategyUnit:
    id: int
    owner: int
    x: float
    z: float
    y: float
    role: str = "ARCHITECT"
    speed: float = DEFAULT_UNIT_SPEED
    radius: float = UNIT_RADIUS
    command: MoveCommand | BuildCommand | AttackCommand | None = None
    path_index: int = 0
    selected: bool = False
    state: str = "IDLE"
    health: float = SOLDIER_HEALTH
    max_health: float = SOLDIER_HEALTH
    attack_damage: float = 0.0
    attack_range: float = 0.0
    attack_cooldown: float = 0.0
    attack_timer: float = 0.0

    @property
    def alive(self) -> bool:
        return self.health > 0.0 and self.state != "DEAD"


@dataclass
class Building:
    id: int
    owner: int
    building_type: BuildingType
    x: float
    z: float
    y: float
    progress: float = 0.0
    complete: bool = False


@dataclass(frozen=True)
class PlacementResult:
    valid: bool
    reason: str


class Phase1StrategyGame:
    def __init__(self, world: WorldInterface, progress_callback: object | None = None, player_nation_id: int = 0) -> None:
        self.world = world
        self.nav = NavigationGrid(world)
        self.nav.rebuild(progress_callback)
        self.player_nation_id = player_nation_id
        self.diplomacy_target_id = 1 if player_nation_id != 1 else 0
        self.game_time = 0.0
        self.paused = False
        self.time_scale = 1.0
        self.capital_positions: tuple[tuple[float, float], ...] = ()
        self.nations: list[Nation] = []
        self.units: list[StrategyUnit] = []
        self.buildings: list[Building] = []
        self.selected_ids: set[int] = set()
        self.next_building_id = 1
        self.next_unit_id = 1
        self.status = "PHASE 4: nations ready"
        self.create_nations()
        self.spawn_initial_units()
        self.status = f"PHASE 4: nations ready | {self.nav.diagnostics_summary()}"

    def rebuild_navigation(self, progress_callback: object | None = None) -> None:
        self.nav.rebuild(progress_callback)
        self.buildings.clear()
        self.nav.set_building_blockers(self.buildings)
        self.capital_positions = self.establish_capital_positions()
        self.create_nations()
        self.spawn_initial_units()
        self.status = f"Navigation rebuilt for new world seed | {self.nav.diagnostics_summary()}"

    def create_nations(self) -> None:
        self.nations = []
        if len(self.capital_positions) != CAPITAL_COUNT:
            self.capital_positions = self.establish_capital_positions()
        for nation_id, (x, z) in enumerate(self.capital_positions):
            self.nations.append(
                Nation(
                    id=nation_id,
                    name=NATION_NAMES[nation_id],
                    color=NATION_COLORS[nation_id],
                    capital_x=x,
                    capital_z=z,
                    territory=[(x, z, 90.0)],
                )
            )
        for nation in self.nations:
            nation.diplomatic_relations = {
                other.id: (RELATION_ALLIED if other.id == nation.id else RELATION_NEUTRAL)
                for other in self.nations
            }
            nation.current_wars.clear()
            nation.alliances = {nation.id}
        if len(self.nations) > 1:
            first_rival = 1 if self.player_nation_id != 1 else 0
            self.set_relation(self.player_nation_id, first_rival, RELATION_AT_WAR)
            self.diplomacy_target_id = first_rival

    def establish_capital_positions(self) -> tuple[tuple[float, float], ...]:
        # ── 1. main component 구축 ───────────────────────────────────
        GS = self.nav.resolution

        center_gx = GS // 2
        center_gy = GS // 2

        if not self.nav.is_grid_walkable(
            center_gx,
            center_gy
        ):
            found = False

            for r in range(1, GS // 2):
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        nx = center_gx + dx
                        ny = center_gy + dy

                        if (
                            0 <= nx < GS
                            and 0 <= ny < GS
                            and self.nav.is_grid_walkable(
                                nx,
                                ny
                            )
                        ):
                            center_gx = nx
                            center_gy = ny
                            found = True
                            break

                    if found:
                        break

                if found:
                    break

        from collections import deque

        visited: set[tuple[int, int]] = set()
        queue: deque[tuple[int, int]] = deque()

        start = (center_gx, center_gy)

        visited.add(start)
        queue.append(start)

        component_budget = max(CAPITAL_COUNT * 260, GS * GS // 5)

        while queue and len(visited) < component_budget:
            cx, cy = queue.popleft()

            for dx, dy in (
                (1, 0),
                (-1, 0),
                (0, 1),
                (0, -1),
            ):
                nx = cx + dx
                ny = cy + dy

                if (nx, ny) in visited:
                    continue

                if not (
                    0 <= nx < GS
                    and 0 <= ny < GS
                ):
                    continue

                if not self.nav.is_grid_walkable(
                    nx,
                    ny
                ):
                    continue

                if not self.nav.is_nav_edge_traversable(
                    cx,
                    cy,
                    nx,
                    ny
                ):
                    continue

                visited.add((nx, ny))
                queue.append((nx, ny))

        main_component: set[tuple[int, int]] = visited

        candidates: list[tuple[float, float, float]] = []

        seed = getattr(
            getattr(
                self.world,
                "terrain",
                None
            ),
            "seed",
            0.0
        )

        grid = CAPITAL_CANDIDATE_GRID

        for gy in range(grid):
            for gx in range(grid):
                index = gy * grid + gx

                jitter_x = (
                    self.seeded_unit(
                        seed,
                        index * 2
                    ) - 0.5
                ) * 0.52

                jitter_z = (
                    self.seeded_unit(
                        seed,
                        index * 2 + 1
                    ) - 0.5
                ) * 0.52

                u = clamp(
                    (gx + 0.5 + jitter_x) / grid,
                    0.0,
                    1.0
                )

                v = clamp(
                    (gy + 0.5 + jitter_z) / grid,
                    0.0,
                    1.0
                )

                x, z = self.world.uv_to_world(
                    u,
                    v
                )

                if not self.is_valid_capital_position(x, z):
                    continue

                nav_cell = self.nav.nearest_walkable_grid(
                    x,
                    z
                )

                if nav_cell is None:
                    continue

                nav_x, nav_z = self.nav.grid_to_world(
                    *nav_cell
                )

                if not self.nav.is_segment_traversable(
                    (x, z),
                    (nav_x, nav_z)
                ):
                    continue

                if nav_cell not in main_component:
                    continue

                center_bias = (
                    1.0
                    - min(
                        1.0,
                        math.hypot(
                            u - 0.5,
                            v - 0.5
                        ) * 1.9
                    )
                )

                seed_score = self.seeded_unit(
                    seed,
                    index + 9001
                )

                score = (
                    seed_score * 0.72
                    + center_bias * 0.28
                )

                candidates.append(
                    (
                        score,
                        x,
                        z
                    )
                )

        candidates.sort(reverse=True)

        selected: list[tuple[float, float]] = []

        half = self.world.half_extent

        for min_distance in (
            half * 0.34,
            half * 0.28,
            half * 0.22,
            half * 0.16,
            0.0,
        ):
            selected.clear()

            for _score, x, z in candidates:
                if all(
                    math.hypot(
                        x - ox,
                        z - oz
                    ) >= min_distance
                    for ox, oz in selected
                ):
                    selected.append(
                        (
                            x,
                            z
                        )
                    )

                    if len(selected) == CAPITAL_COUNT:
                        return tuple(selected)

        raise RuntimeError(
            "Unable to establish 8 valid capital positions for this world."
        )

    def is_valid_capital_position(self, x: float, z: float) -> bool:
        if not self.world.is_inside(x, z):
            return False

        if self.world.is_water(x, z):
            return False

        sample = self.world.sample(x, z)

        h_ratio = (
            sample.height
            / self.world.height_scale
        )

        return (
            sample.walkable
            and sample.water <= WATER_BLOCK_THRESHOLD
            and sample.slope <= CAPITAL_MAX_SLOPE
            and h_ratio <= 0.32
            and h_ratio >= 0.10
        )

    def seeded_unit(self, seed: float, salt: int) -> float:
        value = math.sin((seed + 13.37) * 0.017 + (salt + 1) * 12.9898) * 43758.5453123
        return value - math.floor(value)

    def get_nation(self, nation_id: int) -> Nation | None:
        for nation in self.nations:
            if nation.id == nation_id:
                return nation
        return None

    def spawn_initial_units(self) -> None:
        self.units.clear()
        self.next_unit_id = 1
        for offset_x, offset_z, role in ((0.0, 0.0, "ARCHITECT"), (18.0, 8.0, "ARCHITECT"), (-16.0, 12.0, "SOLDIER"), (12.0, -16.0, "SOLDIER")):
            self.spawn_unit_near_capital(self.player_nation_id, offset_x, offset_z, role)
        for nation in self.nations:
            if nation.id == self.player_nation_id:
                continue
            self.spawn_unit_near_capital(nation.id, -12.0, 0.0, "SOLDIER")
        if self.units:
            self.units[0].selected = True
            self.selected_ids = {self.units[0].id}

    def spawn_unit_near_capital(self, owner: int, offset_x: float, offset_z: float, role: str) -> StrategyUnit | None:
        nation = self.get_nation(owner)
        if nation is None:
            return None
        return self.spawn_unit_at_world(owner, nation.capital_x + offset_x, nation.capital_z + offset_z, role)

    def spawn_unit_at_uv(self, owner: int, u: float, v: float, role: str) -> StrategyUnit | None:
        x, z = self.world.uv_to_world(u, v)
        return self.spawn_unit_at_world(owner, x, z, role)

    def spawn_unit_at_world(self, owner: int, x: float, z: float, role: str) -> StrategyUnit | None:
        cell = self.nav.nearest_walkable_grid(x, z, radius=18)
        if cell is None:
            return None
        wx, wz = self.nav.grid_to_world(*cell)
        unit = StrategyUnit(
            id=self.next_unit_id,
            owner=owner,
            x=wx,
            z=wz,
            y=self.world.terrain_height(wx, wz),
            role=role,
            speed=SOLDIER_SPEED if role == "SOLDIER" else DEFAULT_UNIT_SPEED,
            attack_damage=SOLDIER_ATTACK_DAMAGE if role == "SOLDIER" else 0.0,
            attack_range=SOLDIER_ATTACK_RANGE if role == "SOLDIER" else 0.0,
            attack_cooldown=SOLDIER_ATTACK_COOLDOWN if role == "SOLDIER" else 0.0,
        )
        self.next_unit_id += 1
        self.units.append(unit)
        nation = self.get_nation(owner)
        if nation is not None:
            nation.unit_ids.append(unit.id)
        return unit

    def update(self, dt: float) -> None:
        if self.paused:
            return
        remaining = max(0.0, min(dt, 0.08)) * self.time_scale
        while remaining > 0.0001:
            step = min(0.08, remaining)
            self.simulation_step(step)
            remaining -= step

    def simulation_step(self, dt: float) -> None:
        self.game_time += dt
        for unit in self.units:
            if unit.attack_timer > 0.0:
                unit.attack_timer = max(0.0, unit.attack_timer - dt)
            self.update_unit(unit, dt)
        self.update_construction(dt)
        self.apply_separation()

    def set_time_scale(self, scale: float) -> None:
        self.time_scale = clamp(scale, 0.25, 4.0)
        self.paused = False
        self.status = f"Game speed {self.time_scale:g}x"

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.status = "Paused" if self.paused else f"Game speed {self.time_scale:g}x"

    def update_unit(self, unit: StrategyUnit, dt: float) -> None:
        if not unit.alive:
            unit.command = None
            unit.state = "DEAD"
            return
        if isinstance(unit.command, AttackCommand):
            self.update_attack(unit, unit.command, dt)
            return
        if isinstance(unit.command, (MoveCommand, BuildCommand)) and unit.command.repath_timer > 0.0 and unit.state in {"BLOCKED", "NO_PATH"}:
            unit.command.repath_timer = max(0.0, unit.command.repath_timer - dt)
            return
        if unit.command is None:
            if unit.state not in {"BLOCKED", "NO_PATH"}:
                unit.state = "IDLE"
            return
        if unit.path_index >= len(unit.command.path):
            if isinstance(unit.command, MoveCommand) and unit.state in {"BLOCKED", "NO_PATH"}:
                self.repath_move_command(unit, unit.command)
                return
            if isinstance(unit.command, BuildCommand) and not unit.command.started and unit.state in {"BLOCKED", "NO_PATH"}:
                self.repath_build_command(unit, unit.command)
                return
            if not isinstance(unit.command, BuildCommand):
                unit.state = "IDLE"
            return
        target_x, target_z = unit.command.path[unit.path_index]
        dx = target_x - unit.x
        dz = target_z - unit.z
        distance = math.hypot(dx, dz)
        if distance < 1.4:
            unit.path_index += 1
            if unit.path_index >= len(unit.command.path):
                if isinstance(unit.command, BuildCommand):
                    self.start_building(unit, unit.command)
                else:
                    unit.command = None
                    unit.state = "IDLE"
            return
        step = min(distance, unit.speed * dt / self.world.movement_cost_multiplier(unit.x, unit.z))
        nx = unit.x + dx / distance * step
        nz = unit.z + dz / distance * step
        nxt = self.world.sample(nx, nz)
        if not nxt.walkable:
            self.handle_runtime_blocked(unit, "terrain")
            return
        if self.nav.is_blocked_by_circle(nx, nz):
            self.handle_runtime_blocked(unit, "building")
            return
        unit.x = nx
        unit.z = nz
        unit.y = nxt.height
        if isinstance(unit.command, (MoveCommand, BuildCommand)):
            unit.command.repath_attempts = 0
        unit.state = "MOVING"

    def handle_runtime_blocked(self, unit: StrategyUnit, reason: str) -> None:
        command = unit.command
        if isinstance(command, MoveCommand):
            if self.repath_move_command(unit, command):
                self.status = f"Replanned around {reason}"
                return
            self.status = f"No route around {reason}"
            return
        if isinstance(command, BuildCommand) and not command.started:
            if self.repath_build_command(unit, command):
                self.status = f"Replanned construction route around {reason}"
                return
            self.status = f"Construction site unreachable around {reason}"
            return
        unit.command = None
        unit.state = "BLOCKED"
        self.status = f"Movement blocked by {reason}"

    def repath_move_command(self, unit: StrategyUnit, command: MoveCommand) -> bool:
        if command.repath_attempts >= MAX_REPATH_ATTEMPTS:
            unit.command = None
            unit.state = "NO_PATH"
            return False
        path = self.nav.find_path((unit.x, unit.z), (command.target_x, command.target_z))
        if not path:
            self.mark_repath_failed(unit, command)
            return False
        command.path = path
        command.repath_timer = 0.0
        command.repath_attempts = 0
        unit.path_index = 0
        unit.state = "MOVING"
        return True

    def repath_build_command(self, unit: StrategyUnit, command: BuildCommand) -> bool:
        if command.repath_attempts >= MAX_REPATH_ATTEMPTS:
            unit.command = None
            unit.state = "NO_PATH"
            return False
        placement = self.validate_placement(command.x, command.z, command.building_type)
        if not placement.valid:
            unit.command = None
            unit.state = "NO_PATH"
            self.status = placement.reason
            return False
        work_point = self.find_build_work_point(unit, command.x, command.z, command.building_type)
        if work_point is None:
            self.mark_repath_failed(unit, command)
            return False
        path = self.nav.find_path((unit.x, unit.z), work_point)
        if not path or not self.is_build_path_endpoint_valid(path, command.x, command.z, command.building_type):
            self.mark_repath_failed(unit, command)
            return False
        command.path = path
        command.repath_timer = 0.0
        command.repath_attempts = 0
        unit.path_index = 0
        unit.state = "MOVING"
        return True

    def mark_repath_failed(self, unit: StrategyUnit, command: MoveCommand | BuildCommand) -> None:
        command.repath_attempts += 1
        command.path = []
        command.repath_timer = REPATH_COOLDOWN
        unit.path_index = 0
        unit.state = "NO_PATH"
        if command.repath_attempts >= MAX_REPATH_ATTEMPTS:
            unit.command = None

    def update_attack(self, unit: StrategyUnit, command: AttackCommand, dt: float) -> None:
        target = self.get_unit(command.target_unit_id)
        if target is None or not target.alive:
            unit.command = None
            unit.path_index = 0
            unit.state = "IDLE"
            self.status = "Target eliminated"
            return
        if not self.is_hostile(unit, target):
            unit.command = None
            unit.path_index = 0
            unit.state = "IDLE"
            self.status = "Target is not hostile"
            return

        distance = math.hypot(target.x - unit.x, target.z - unit.z)
        if distance <= unit.attack_range and self.has_line_of_sight(unit.x, unit.z, target.x, target.z):
            command.path.clear()
            unit.path_index = 0
            unit.state = "ATTACKING"
            if unit.attack_timer <= 0.0:
                self.apply_damage(unit, target)
            return

        command.repath_timer -= dt
        if command.repath_timer <= 0.0 or unit.path_index >= len(command.path):
            path = self.find_attack_path(unit, target)
            command.repath_timer = 0.45
            if not path:
                unit.state = "NO_PATH" if distance > unit.attack_range else "BLOCKED"
                self.status = "No attack path" if distance > unit.attack_range else "No line of sight"
                return
            command.path = path
            unit.path_index = 0

        self.follow_path_step(unit, command.path, dt, "ATTACK_MOVING")

    def follow_path_step(self, unit: StrategyUnit, path: list[tuple[float, float]], dt: float, moving_state: str) -> None:
        if unit.path_index >= len(path):
            return
        target_x, target_z = path[unit.path_index]
        dx = target_x - unit.x
        dz = target_z - unit.z
        distance = math.hypot(dx, dz)
        if distance < 1.4:
            unit.path_index += 1
            return
        step = min(distance, unit.speed * dt / self.world.movement_cost_multiplier(unit.x, unit.z))
        nx = unit.x + dx / distance * step
        nz = unit.z + dz / distance * step
        nxt = self.world.sample(nx, nz)
        if not nxt.walkable:
            unit.state = "BLOCKED"
            unit.path_index = len(path)
            self.status = "Movement blocked by terrain"
            return
        if self.nav.is_blocked_by_circle(nx, nz):
            unit.state = "BLOCKED"
            unit.path_index = len(path)
            self.status = "Movement blocked by building"
            return
        unit.x = nx
        unit.z = nz
        unit.y = nxt.height
        unit.state = moving_state

    def find_attack_path(self, attacker: StrategyUnit, target: StrategyUnit) -> list[tuple[float, float]]:
        candidates: list[tuple[float, float]] = []
        for radius_factor in (0.72, 0.55, 0.90):
            radius = max(attacker.radius + target.radius + 2.0, attacker.attack_range * radius_factor)
            for index in range(16):
                angle = math.tau * index / 16.0
                candidates.append((target.x + math.cos(angle) * radius, target.z + math.sin(angle) * radius))
        candidates.sort(key=lambda point: math.hypot(point[0] - attacker.x, point[1] - attacker.z))
        for candidate in candidates:
            if not self.world.is_walkable(*candidate):
                continue
            if self.nav.is_blocked_by_circle(*candidate):
                continue
            if math.hypot(candidate[0] - target.x, candidate[1] - target.z) > attacker.attack_range:
                continue
            if not self.has_line_of_sight(candidate[0], candidate[1], target.x, target.z):
                continue
            path = self.nav.find_path((attacker.x, attacker.z), candidate)
            if path and self.is_attack_path_endpoint_valid(path, attacker, target):
                return path
        return []

    def is_attack_path_endpoint_valid(self, path: list[tuple[float, float]], attacker: StrategyUnit, target: StrategyUnit) -> bool:
        if not path:
            return False
        end_x, end_z = path[-1]
        return math.hypot(end_x - target.x, end_z - target.z) <= attacker.attack_range and self.has_line_of_sight(end_x, end_z, target.x, target.z)

    def apply_damage(self, attacker: StrategyUnit, target: StrategyUnit) -> None:
        target.health = max(0.0, target.health - attacker.attack_damage)
        attacker.attack_timer = attacker.attack_cooldown
        self.status = f"Unit {attacker.id} hit unit {target.id}"
        if target.health <= 0.0:
            target.command = None
            target.path_index = 0
            target.selected = False
            self.selected_ids.discard(target.id)
            target.state = "DEAD"
            self.status = f"Unit {target.id} eliminated"

    def has_line_of_sight(self, ax: float, az: float, bx: float, bz: float) -> bool:
        distance = math.hypot(bx - ax, bz - az)
        if distance <= 0.001:
            return True
        steps = max(4, min(72, int(distance / max(1.0, self.world.scale * 0.75))))
        start_y = self.world.terrain_height(ax, az) + LINE_OF_SIGHT_EYE_HEIGHT
        end_y = self.world.terrain_height(bx, bz) + LINE_OF_SIGHT_EYE_HEIGHT
        for step_index in range(1, steps):
            t = step_index / steps
            x = mix(ax, bx, t)
            z = mix(az, bz, t)
            ray_y = mix(start_y, end_y, t)
            if self.world.terrain_height(x, z) > ray_y + LINE_OF_SIGHT_TERRAIN_MARGIN:
                return False
            for building in self.buildings:
                if math.hypot(x - building.x, z - building.z) <= building.building_type.footprint_radius:
                    if ray_y <= building.y + building.building_type.height:
                        return False
        return True

    def start_building(self, unit: StrategyUnit, command: BuildCommand) -> None:
        if command.started:
            unit.state = "BUILDING"
            return
        if not self.is_build_distance_valid(unit.x, unit.z, command.x, command.z, command.building_type):
            unit.command = None
            unit.state = "BLOCKED"
            self.status = "Architect is not in build range"
            return
        placement = self.validate_placement(command.x, command.z, command.building_type)
        if not placement.valid:
            unit.command = None
            unit.state = "IDLE"
            self.status = placement.reason
            return
        building = Building(
            id=self.next_building_id,
            owner=unit.owner,
            building_type=command.building_type,
            x=command.x,
            z=command.z,
            y=self.world.terrain_height(command.x, command.z),
        )
        self.next_building_id += 1
        self.buildings.append(building)
        nation = self.get_nation(building.owner)
        if nation is not None:
            nation.building_ids.append(building.id)
        self.nav.set_building_blockers(self.buildings)
        command.started = True
        command.building_id = building.id
        unit.state = "BUILDING"
        self.status = f"Constructing {command.building_type.name}"

    def update_construction(self, dt: float) -> None:
        for unit in self.units:
            command = unit.command
            if not isinstance(command, BuildCommand) or not command.started or command.building_id is None:
                continue
            building = self.get_building(command.building_id)
            if building is None:
                unit.command = None
                unit.state = "IDLE"
                continue
            if building.complete:
                unit.command = None
                unit.state = "IDLE"
                continue
            if not self.is_build_distance_valid(unit.x, unit.z, building.x, building.z, building.building_type):
                unit.state = "BLOCKED"
                continue
            building.progress = min(building.building_type.build_time, building.progress + dt)
            unit.state = "BUILDING"
            if building.progress >= building.building_type.build_time:
                building.complete = True
                unit.command = None
                unit.state = "IDLE"
                self.status = f"{building.building_type.name} complete"

    def get_building(self, building_id: int) -> Building | None:
        for building in self.buildings:
            if building.id == building_id:
                return building
        return None

    def get_unit(self, unit_id: int) -> StrategyUnit | None:
        for unit in self.units:
            if unit.id == unit_id:
                return unit
        return None

    def relation_between(self, a_id: int, b_id: int) -> str:
        nation = self.get_nation(a_id)
        if nation is None:
            return RELATION_NEUTRAL
        return nation.diplomatic_relations.get(b_id, RELATION_NEUTRAL)

    def set_relation(self, a_id: int, b_id: int, relation: str) -> None:
        a = self.get_nation(a_id)
        b = self.get_nation(b_id)
        if a is None or b is None or a.id == b.id:
            return
        a.diplomatic_relations[b.id] = relation
        b.diplomatic_relations[a.id] = relation
        for left, right in ((a, b), (b, a)):
            if relation == RELATION_AT_WAR:
                left.current_wars.add(right.id)
                left.alliances.discard(right.id)
            else:
                left.current_wars.discard(right.id)
                if relation == RELATION_ALLIED:
                    left.alliances.add(right.id)
                else:
                    left.alliances.discard(right.id)

    def are_at_war(self, a_id: int, b_id: int) -> bool:
        return self.relation_between(a_id, b_id) == RELATION_AT_WAR

    def declare_war(self, target_id: int) -> None:
        if target_id == self.player_nation_id or self.get_nation(target_id) is None:
            self.status = "No valid diplomacy target"
            return
        self.set_relation(self.player_nation_id, target_id, RELATION_AT_WAR)
        self.status = f"Declared war on {self.nation_name(target_id)}"

    def make_peace(self, target_id: int) -> None:
        if target_id == self.player_nation_id or self.get_nation(target_id) is None:
            self.status = "No valid diplomacy target"
            return
        self.set_relation(self.player_nation_id, target_id, RELATION_NEUTRAL)
        self.status = f"Peace with {self.nation_name(target_id)}"

    def form_alliance(self, target_id: int) -> None:
        if target_id == self.player_nation_id or self.get_nation(target_id) is None:
            self.status = "No valid diplomacy target"
            return
        self.set_relation(self.player_nation_id, target_id, RELATION_ALLIED)
        self.status = f"Alliance with {self.nation_name(target_id)}"

    def cycle_diplomacy_target(self, step: int = 1) -> None:
        if len(self.nations) <= 1:
            return
        ids = [nation.id for nation in self.nations if nation.id != self.player_nation_id]
        if self.diplomacy_target_id not in ids:
            self.diplomacy_target_id = ids[0]
            return
        index = ids.index(self.diplomacy_target_id)
        self.diplomacy_target_id = ids[(index + step) % len(ids)]
        self.status = f"Diplomacy target: {self.nation_name(self.diplomacy_target_id)}"

    def nation_name(self, nation_id: int) -> str:
        nation = self.get_nation(nation_id)
        return nation.name if nation is not None else f"Nation {nation_id}"

    def nation_color(self, nation_id: int) -> tuple[float, float, float]:
        nation = self.get_nation(nation_id)
        return nation.color if nation is not None else (0.75, 0.75, 0.75)

    def diplomacy_summary(self) -> str:
        target = self.get_nation(self.diplomacy_target_id)
        if target is None:
            return "Diplomacy: none"
        relation = self.relation_between(self.player_nation_id, target.id)
        return f"{self.nation_name(self.player_nation_id)} -> {target.name}: {relation}"

    def is_hostile(self, a: StrategyUnit, b: StrategyUnit) -> bool:
        return self.are_at_war(a.owner, b.owner)

    def is_player_owned(self, unit: StrategyUnit) -> bool:
        return unit.owner == self.player_nation_id

    def apply_separation(self) -> None:
        for i, a in enumerate(self.units):
            if not a.alive:
                continue
            for b in self.units[i + 1 :]:
                if not b.alive:
                    continue
                dx = b.x - a.x
                dz = b.z - a.z
                dist = math.hypot(dx, dz)
                min_dist = a.radius + b.radius
                if dist >= min_dist:
                    continue
                if dist <= 0.001:
                    axis_index = (a.id * 31 + b.id * 17) % 8
                    angle = axis_index * (math.tau / 8.0)
                    dx = math.cos(angle)
                    dz = math.sin(angle)
                    dist = 1.0
                push = (min_dist - dist) * 0.18
                ox = dx / dist * push
                oz = dz / dist * push
                ax = a.x - ox
                az = a.z - oz
                bx = b.x + ox
                bz = b.z + oz
                if self.world.is_walkable(ax, az) and not self.nav.is_blocked_by_circle(ax, az):
                    a.x = ax
                    a.z = az
                    a.y = self.world.terrain_height(ax, az)
                if self.world.is_walkable(bx, bz) and not self.nav.is_blocked_by_circle(bx, bz):
                    b.x = bx
                    b.z = bz
                    b.y = self.world.terrain_height(bx, bz)

    def select_nearest(self, x: float, z: float) -> None:
        nearest: StrategyUnit | None = None
        nearest_dist = SELECTION_RADIUS
        for unit in self.units:
            if not unit.alive or not self.is_player_owned(unit):
                continue
            dist = math.hypot(unit.x - x, unit.z - z)
            if dist < nearest_dist:
                nearest = unit
                nearest_dist = dist
        self.selected_ids.clear()
        for unit in self.units:
            unit.selected = unit is nearest
            if unit.selected:
                self.selected_ids.add(unit.id)
        self.status = "Unit selected" if nearest else "No unit selected"

    def select_in_rect(self, unit_ids: set[int]) -> None:
        self.selected_ids = {
            unit_id
            for unit_id in unit_ids
            if (unit := self.get_unit(unit_id)) is not None and unit.alive and self.is_player_owned(unit)
        }
        for unit in self.units:
            unit.selected = unit.id in self.selected_ids
        self.status = f"{len(self.selected_ids)} unit(s) selected"

    def player_selected_units(self) -> list[StrategyUnit]:
        selected: list[StrategyUnit] = []
        valid_ids: set[int] = set()
        for unit in self.units:
            is_selected = unit.id in self.selected_ids and unit.alive and self.is_player_owned(unit)
            unit.selected = is_selected
            if is_selected:
                selected.append(unit)
                valid_ids.add(unit.id)
        self.selected_ids = valid_ids
        return selected

    def issue_move(self, x: float, z: float) -> None:
        selected = self.player_selected_units()
        if not selected:
            self.status = "No selected unit"
            return
        if not self.world.is_walkable(x, z):
            self.status = "Target is not walkable"
            return
        if self.nav.is_blocked_by_circle(x, z):
            self.status = "Target is blocked by building"
            return
        assigned = 0
        for index, unit in enumerate(selected):
            offset_x = ((index % 2) - 0.5) * unit.radius * 2.6
            offset_z = ((index // 2) - 0.5) * unit.radius * 2.6
            target = (x + offset_x, z + offset_z)
            if not self.world.is_walkable(*target):
                target = (x, z)
            path = self.nav.find_path((unit.x, unit.z), target)
            if not path:
                unit.command = None
                unit.state = "NO_PATH"
                continue
            unit.command = MoveCommand(target_x=target[0], target_z=target[1], path=path)
            unit.path_index = 0
            unit.state = "MOVING"
            assigned += 1
        self.status = "Move command issued" if assigned else "No valid path"

    def selected_architects(self) -> list[StrategyUnit]:
        return [unit for unit in self.player_selected_units() if unit.role == "ARCHITECT"]

    def selected_soldiers(self) -> list[StrategyUnit]:
        return [unit for unit in self.player_selected_units() if unit.role == "SOLDIER"]

    def find_enemy_unit_at(self, x: float, z: float) -> StrategyUnit | None:
        selected = self.player_selected_units()
        selected_owners = {unit.owner for unit in selected}
        nearest: StrategyUnit | None = None
        nearest_dist = ATTACK_TARGET_RADIUS
        for unit in self.units:
            if not unit.alive or unit.owner in selected_owners:
                continue
            if selected and not any(self.is_hostile(source, unit) for source in selected):
                continue
            dist = math.hypot(unit.x - x, unit.z - z)
            if dist < nearest_dist:
                nearest = unit
                nearest_dist = dist
        return nearest

    def issue_attack(self, target_id: int) -> None:
        target = self.get_unit(target_id)
        if target is None or not target.alive:
            self.status = "No valid target"
            return
        soldiers = self.selected_soldiers()
        if not soldiers:
            self.status = "Select a soldier first"
            return
        assigned = 0
        for soldier in soldiers:
            if self.assign_attack_command(soldier, target):
                assigned += 1
        self.status = f"Attack command: unit {target.id}" if assigned else "Target is not hostile"

    def assign_attack_command(self, attacker: StrategyUnit, target: StrategyUnit) -> bool:
        if attacker.role != "SOLDIER" or not attacker.alive:
            return False
        if not target.alive or not self.is_hostile(attacker, target):
            return False
        attacker.command = AttackCommand(target_unit_id=target.id)
        attacker.path_index = 0
        attacker.state = "ATTACKING"
        return True

    def issue_build(self, x: float, z: float, building_type: BuildingType = HOUSE) -> None:
        architects = self.selected_architects()
        if not architects:
            self.status = "Select an architect first"
            return
        placement = self.validate_placement(x, z, building_type)
        if not placement.valid:
            self.status = placement.reason
            return
        architect = architects[0]
        work_point = self.find_build_work_point(architect, x, z, building_type)
        if work_point is None:
            self.status = "No path to construction site"
            return
        path = self.nav.find_path((architect.x, architect.z), work_point)
        if not path:
            self.status = "No path to construction site"
            return
        if not self.is_build_path_endpoint_valid(path, x, z, building_type):
            self.status = "No path reaches construction range"
            return
        architect.command = BuildCommand(building_type=building_type, x=x, z=z, path=path)
        architect.path_index = 0
        architect.state = "MOVING"
        self.status = f"Build command: {building_type.name}"

    def find_build_work_point(self, architect: StrategyUnit, x: float, z: float, building_type: BuildingType) -> tuple[float, float] | None:
        candidates: list[tuple[float, float]] = []
        min_distance = building_type.footprint_radius + UNIT_RADIUS + 1.0
        max_distance = building_type.footprint_radius + BUILD_RANGE - 0.6
        for distance in (min_distance, (min_distance + max_distance) * 0.5, max_distance):
            for index in range(20):
                angle = math.tau * index / 20.0
                candidates.append((x + math.cos(angle) * distance, z + math.sin(angle) * distance))
        candidates.sort(key=lambda point: math.hypot(point[0] - architect.x, point[1] - architect.z))
        for candidate in candidates:
            if not self.world.is_walkable(*candidate):
                continue
            if self.point_overlaps_building(candidate[0], candidate[1], UNIT_RADIUS):
                continue
            path = self.nav.find_path((architect.x, architect.z), candidate)
            if path and self.is_build_path_endpoint_valid(path, x, z, building_type):
                return candidate
        return None

    def is_build_path_endpoint_valid(self, path: list[tuple[float, float]], x: float, z: float, building_type: BuildingType) -> bool:
        if not path:
            return False
        end_x, end_z = path[-1]
        return self.is_build_distance_valid(end_x, end_z, x, z, building_type)

    def is_build_distance_valid(self, worker_x: float, worker_z: float, x: float, z: float, building_type: BuildingType) -> bool:
        distance = math.hypot(worker_x - x, worker_z - z)
        min_distance = building_type.footprint_radius + UNIT_RADIUS
        max_distance = building_type.footprint_radius + BUILD_RANGE
        return min_distance <= distance <= max_distance

    def validate_placement(self, x: float, z: float, building_type: BuildingType = HOUSE) -> PlacementResult:
        if not self.world.is_inside(x, z):
            return PlacementResult(False, "Cannot build outside the world")
        if self.world.is_water(x, z):
            return PlacementResult(False, "Cannot build on water")
        center = self.world.sample(x, z)
        if not center.walkable:
            return PlacementResult(False, "Cannot build on blocked terrain")
        if center.slope > BUILDING_PLACEMENT_MAX_SLOPE:
            return PlacementResult(False, "Terrain is too steep")
        if self.point_overlaps_building(x, z, building_type.footprint_radius):
            return PlacementResult(False, "Building overlaps another building")

        radius = building_type.footprint_radius
        samples = [(0.0, 0.0)]
        for index in range(12):
            angle = math.tau * index / 12.0
            samples.append((math.cos(angle) * radius, math.sin(angle) * radius))
        heights: list[float] = []
        for ox, oz in samples:
            sx = x + ox
            sz = z + oz
            if not self.world.is_inside(sx, sz):
                return PlacementResult(False, "Footprint leaves the world")
            sample = self.world.sample(sx, sz)
            if sample.water > WATER_BLOCK_THRESHOLD:
                return PlacementResult(False, "Footprint touches water")
            if not sample.walkable or sample.slope > BUILDING_PLACEMENT_MAX_SLOPE:
                return PlacementResult(False, "Footprint terrain is not flat enough")
            heights.append(sample.height)
        if max(heights) - min(heights) > 7.0:
            return PlacementResult(False, "Footprint is too uneven")
        return PlacementResult(True, "Placement valid")

    def point_overlaps_building(self, x: float, z: float, radius: float) -> bool:
        for building in self.buildings:
            distance = math.hypot(x - building.x, z - building.z)
            if distance < radius + building.building_type.footprint_radius:
                return True
        return False
