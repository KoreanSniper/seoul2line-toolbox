from __future__ import annotations

from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import tempfile

from app.games.micro_warfare.model import (
    Battlefield, Building, BUILDING_SPECS, GAME_MODES, ProductionOrder, ResourceNode, Unit, UNIT_SPECS, WarfareGame,
)


def snapshot(game: WarfareGame) -> dict:
    return {
        "version": 1, "mode": game.mode, "result": game.result, "paused": game.paused,
        "ai_enabled": game.ai_enabled, "elapsed": game.elapsed, "ai_timer": game.ai_timer,
        "world": asdict(game.world), "units": [asdict(unit) for unit in game.units],
        "buildings": [asdict(building) for building in game.buildings],
        "resources": [asdict(node) for node in game.resources],
        "stock": game.stock, "enemy_stock": game.enemy_stock, "storage_capacity": game.storage_capacity,
        "next_unit_id": game.next_unit_id, "next_building_id": game.next_building_id,
        "selected_ids": sorted(game.selected_ids), "selected_building": game.selected_building,
        "statistics": {str(owner): values for owner, values in game.statistics.items()},
    }


def save_game(game: WarfareGame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".warfare-", suffix=".tmp", delete=False) as output:
            temporary = output.name
            json.dump(snapshot(game), output, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()


def number(value, lower: float = 0, upper: float = 1e12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError("저장 데이터의 숫자 범위가 잘못되었습니다.")
    return value


def integer(value, lower: int = 0, upper: int = 1000000) -> int:
    number(value, lower, upper)
    if not isinstance(value, int):
        raise ValueError("저장 데이터에 정수가 필요합니다.")
    return value


def position(value, game: WarfareGame) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("저장 좌표가 잘못되었습니다.")
    x, y = number(value[0]), number(value[1])
    if not game.world.contains(x, y):
        raise ValueError("저장 좌표가 전장 밖에 있습니다.")
    return x, y


def restore(data: dict) -> WarfareGame:
    try:
        if data["version"] != 1 or data["mode"] not in GAME_MODES:
            raise ValueError("지원하지 않는 저장 버전 또는 게임 모드입니다.")
        raw_world = data["world"]
        if raw_world["width"] != 80 or raw_world["height"] != 60:
            raise ValueError("저장 전장 크기가 잘못되었습니다.")
        tiles = raw_world["tiles"]
        if len(tiles) != 60 or any(len(row) != 80 or any(tile not in ("grass", "forest", "water", "rock") for tile in row) for row in tiles):
            raise ValueError("저장 지형이 잘못되었습니다.")
        seed = integer(raw_world["seed"])
        game = WarfareGame(seed, mode=data["mode"], ai_enabled=False)
        game.world = Battlefield(80, 60, seed, tiles)
        for field in ("paused", "ai_enabled"):
            if type(data[field]) is not bool:
                raise ValueError("저장 상태가 잘못되었습니다.")
            setattr(game, field, data[field])
        if game.mode == "sandbox" and game.ai_enabled:
            raise ValueError("샌드박스에는 적 경제 AI를 사용할 수 없습니다.")
        if data["result"] not in ("running", "victory", "defeat", "draw"):
            raise ValueError("저장된 승패 상태가 잘못되었습니다.")
        game.result = data["result"]
        game.elapsed, game.ai_timer = number(data["elapsed"]), number(data["ai_timer"], -1e12)
        for name in ("stock", "enemy_stock"):
            stock = data[name]
            setattr(game, name, {kind: number(stock[kind]) for kind in ("ore", "wood")})
        game.storage_capacity = number(data["storage_capacity"])
        for key, limit in (("units", 256), ("buildings", 256), ("resources", 128)):
            if not isinstance(data[key], list) or len(data[key]) > limit:
                raise ValueError("저장 개체 수가 너무 많습니다.")
        game.units = []
        for raw in data["units"]:
            raw = dict(raw)
            if raw["role"] not in UNIT_SPECS:
                raise ValueError("알 수 없는 유닛입니다.")
            integer(raw["id"], 1)
            integer(raw["owner"], 0, 1)
            position((raw["x"], raw["y"]), game)
            number(raw["hp"], 0.001, UNIT_SPECS[raw["role"]]["hp"])
            number(raw["speed"], .1, 200)
            number(raw["cargo"], 0, 20)
            number(raw["cooldown"], 0, 2)
            number(raw["repath_remaining"], 0, 2)
            if raw["cargo_kind"] not in ("ore", "wood") or type(raw["returning"]) is not bool:
                raise ValueError("운반 상태가 잘못되었습니다.")
            for key in ("resource_id", "building_id"):
                if raw[key] is not None:
                    integer(raw[key], 1)
            raw["target"] = position(raw["target"], game) if raw["target"] is not None else None
            if len(raw["path"]) > 5000:
                raise ValueError("저장 경로가 너무 깁니다.")
            raw["path"] = [position(point, game) for point in raw["path"]]
            if raw["attack_target"] is not None:
                kind, target_id = raw["attack_target"]
                if kind not in ("unit", "building"):
                    raise ValueError("공격 대상이 잘못되었습니다.")
                raw["attack_target"] = (kind, integer(target_id, 1))
            game.units.append(Unit(**raw))
        game.buildings = []
        for raw in data["buildings"]:
            raw = dict(raw)
            if raw["kind"] not in BUILDING_SPECS:
                raise ValueError("알 수 없는 건물입니다.")
            integer(raw["id"], 1)
            integer(raw["owner"], 0, 1)
            integer(raw["col"], 0, 78)
            integer(raw["row"], 0, 58)
            integer(raw["level"], 1, 3)
            number(raw["hp"], .001, 1000 if raw["kind"] == "hq" else 500)
            number(raw["progress"], 0, BUILDING_SPECS[raw["kind"]]["time"] + 1)
            number(raw["upgrade_remaining"], 0, 10)
            if len(raw["queue"]) > 5:
                raise ValueError("생산 대기열이 너무 깁니다.")
            queue = []
            for item in raw["queue"]:
                if item["kind"] not in UNIT_SPECS or UNIT_SPECS[item["kind"]]["building"] != raw["kind"]:
                    raise ValueError("생산 대기열의 유닛 종류가 잘못되었습니다.")
                queue.append(ProductionOrder(item["kind"], number(item["progress"], 0, UNIT_SPECS[item["kind"]]["time"])))
            raw["queue"] = queue
            game.buildings.append(Building(**raw))
        game.resources = []
        for raw in data["resources"]:
            integer(raw["id"], 1)
            if raw["kind"] not in ("ore", "wood"):
                raise ValueError("자원 종류가 잘못되었습니다.")
            position((raw["x"], raw["y"]), game)
            number(raw["amount"])
            game.resources.append(ResourceNode(**raw))
        for items in (game.units, game.buildings, game.resources):
            if len({item.id for item in items}) != len(items):
                raise ValueError("중복된 개체 ID가 있습니다.")
        game.next_unit_id = integer(data["next_unit_id"], max((unit.id for unit in game.units), default=0) + 1)
        game.next_building_id = integer(data["next_building_id"], max((item.id for item in game.buildings), default=0) + 1)
        game.selected_ids = {integer(item, 1) for item in data["selected_ids"]}
        if not game.selected_ids.issubset({unit.id for unit in game.units if unit.owner == 0}):
            raise ValueError("선택된 유닛 정보가 잘못되었습니다.")
        game.selected_building = data["selected_building"]
        if game.selected_building is not None and game.selected_building not in {item.id for item in game.buildings if item.owner == 0}:
            raise ValueError("선택된 건물 정보가 잘못되었습니다.")
        game.statistics = {owner: {key: number(data["statistics"][str(owner)][key]) for key in values}
                           for owner, values in game.statistics.items()}
        return game
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("저장 파일의 필수 항목이나 형식이 잘못되었습니다.") from exc


def load_game(path: Path) -> WarfareGame:
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("저장 파일은 10MB 이하여야 합니다.")
    try:
        return restore(json.loads(path.read_text(encoding="utf-8")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("올바른 UTF-8 JSON 저장 파일이 아닙니다.") from exc
