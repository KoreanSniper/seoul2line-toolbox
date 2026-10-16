from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.paths import data_directory, migrate_legacy_data


APP_DIR = data_directory()
CONFIG_PATH = APP_DIR / "config.json"

VALID_THEMES = {"dark", "light", "green"}
DEFAULT_HOTKEYS = {
    "quick_new_file": "<Control-n>",
    "quick_delete": "<Delete>",
    "quick_move": "<Control-m>",
    "quick_refresh": "<F5>",
}
_KNOWN_KEYSYMS = {
    "BackSpace", "Delete", "End", "Escape", "Home", "Insert", "Next",
    "Prior", "Return", "space", "Tab", "Up", "Down", "Left", "Right",
}


DEFAULT_CONFIG: dict[str, Any] = {
    "theme": "dark",
    "launchers": {
        "valorant": "",
        "minecraft_launcher": "",
        "steam": "steam://open/main",
    },
    "minecraft": {
        "versions_path": ".minecraft/versions",
        "selected_version": "",
    },
    "hotkeys": {
        **DEFAULT_HOTKEYS,
    },
    "files": {
        "workspace": ".",
    },
    "music": {
        "playlist": [],
        "volume": 0.55,
        "mode": "목록 반복",
    },
    "toolbox_wallet": {
        "currencies": {
            "tool_coin": 2500,
        },
        "last_daily_grant": "",
    },
    "factory_automation": {
        "generators": 1,
        "conveyors": 1,
        "sellers": 1,
        "buildings": {
            "0,0": "generator",
            "1,0": "conveyor",
            "2,0": "seller",
        },
        "storage_level": 1,
        "power_level": 1,
        "quality": 1,
        "storage": 0.0,
        "tier": 1,
        "efficiency": 1,
        "total_sold": 0,
        "total_earned": 0,
        "claimed_milestones": [],
        "last_saved": 0,
    },
}


@dataclass
class AppConfig:
    data: dict[str, Any] = field(default_factory=lambda: deepcopy(DEFAULT_CONFIG))
    _save_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @classmethod
    def load(cls) -> "AppConfig":
        migrate_legacy_data(APP_DIR)
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            cfg = cls()
            cfg.save()
            return cfg

        parse_failed = False
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, MemoryError, OSError, UnicodeError):
            loaded = {}
            parse_failed = True

        # JSON 문법은 맞지만 루트가 배열이나 문자열이면 설정으로 사용할 수 없습니다.
        if not isinstance(loaded, dict):
            loaded = {}
            parse_failed = True

        if parse_failed:
            # 복구 전에 원본을 남겨 사용자가 직접 되살릴 수 있게 합니다.
            _backup_config("invalid")
            cfg = cls(_normalise_config(DEFAULT_CONFIG))
            cfg.save()
            return cfg

        merged = _deep_merge(DEFAULT_CONFIG, loaded)
        repaired = _normalise_config(merged)
        cfg = cls(repaired)
        # 손상된 항목은 다음 실행에서도 반복 복구되지 않도록 즉시 기록합니다.
        if repaired != merged:
            _backup_config("before-repair")
            cfg.save()
        return cfg

    def save(self) -> None:
        with self._save_lock:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            temp_path = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.tmp")
            temp_path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # 큰 설정 파일을 쓰는 중 프로세스가 종료되어도 기존 파일이 빈 파일이 되지 않게 합니다.
            temp_path.replace(CONFIG_PATH)

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, *keys: str, value: Any) -> None:
        self.set_many({keys: value})

    def set_many(self, updates: dict[tuple[str, ...], Any]) -> None:
        """여러 설정을 한 번만 정규화·저장합니다."""
        with self._save_lock:
            for keys, value in updates.items():
                if not keys:
                    continue
                node = self.data
                for key in keys[:-1]:
                    child = node.setdefault(key, {})
                    if not isinstance(child, dict):
                        child = {}
                        node[key] = child
                    node = child
                node[keys[-1]] = value
            self.data = _normalise_config(self.data)
            self.save()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _backup_config(reason: str) -> Path | None:
    """자동 복구 전에 기존 config.json을 복사하지 않고 이름만 바꿔 보존합니다."""
    if not CONFIG_PATH.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.{reason}.{stamp}.bak")
    try:
        # copy2가 아니라 rename이므로 2천만 줄 파일을 디스크에 한 벌 더 만들지 않습니다.
        CONFIG_PATH.replace(backup)
    except OSError:
        return None
    return backup


def _normalise_config(config: dict[str, Any]) -> dict[str, Any]:
    """설정값을 실행 가능한 범위로 맞추고 잘못된 항목은 기본값으로 되돌립니다."""
    result = deepcopy(DEFAULT_CONFIG)
    if isinstance(config, dict):
        result = _deep_merge(result, config)

    if result.get("theme") not in VALID_THEMES:
        result["theme"] = DEFAULT_CONFIG["theme"]

    result["launchers"] = _normalise_launchers(result.get("launchers"))
    result["minecraft"] = _normalise_minecraft(result.get("minecraft"))
    result["hotkeys"] = _normalise_hotkeys(result.get("hotkeys"))
    result["music"] = _normalise_music(result.get("music"))
    result["toolbox_wallet"] = _normalise_wallet(result.get("toolbox_wallet"))
    return result


def _normalise_launchers(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, str] = {}
    for key in ("valorant", "minecraft_launcher"):
        candidate = source.get(key, "")
        if not isinstance(candidate, str) or not candidate.strip():
            result[key] = ""
            continue
        try:
            result[key] = str(Path(candidate).expanduser()) if Path(candidate).expanduser().is_file() else ""
        except (OSError, ValueError):
            result[key] = ""

    steam = source.get("steam", DEFAULT_CONFIG["launchers"]["steam"])
    if not isinstance(steam, str):
        steam = ""
    steam = steam.strip()
    result["steam"] = steam if not steam or steam.startswith("steam://") else DEFAULT_CONFIG["launchers"]["steam"]
    return result


def _normalise_minecraft(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    default_path = DEFAULT_CONFIG["minecraft"]["versions_path"]
    raw_path = source.get("versions_path", default_path)
    if not isinstance(raw_path, str) or not raw_path.strip():
        versions_path = default_path
    else:
        try:
            path = Path(raw_path).expanduser()
            versions_path = str(path) if not path.is_absolute() or path.is_dir() else default_path
        except (OSError, ValueError):
            versions_path = default_path

    selected = source.get("selected_version", "")
    if not isinstance(selected, str) or not re.fullmatch(r"[0-9][0-9A-Za-z._-]*", selected):
        selected = ""
    return {"versions_path": versions_path, "selected_version": selected}


def _normalise_hotkeys(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {
        key: candidate if _is_valid_hotkey(candidate) else default
        for key, default in DEFAULT_HOTKEYS.items()
        for candidate in [source.get(key, default)]
    }


def _is_valid_hotkey(value: Any) -> bool:
    """Tkinter가 인식할 수 있는 단순 키심만 허용합니다."""
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r"<((?:(?:Control|Alt|Shift|Command|Meta)-)*)([A-Za-z0-9]+)>", value)
    if not match:
        return False
    key = match.group(2)
    if key in _KNOWN_KEYSYMS or re.fullmatch(r"F(?:[1-9]|1[0-2])", key):
        return True
    return len(key) == 1 and key.isalnum()


def _normalise_music(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    raw_volume = source.get("volume", DEFAULT_CONFIG["music"]["volume"])
    try:
        volume = float(raw_volume)
        if not math.isfinite(volume) or not 0.0 <= volume <= 1.0:
            raise ValueError
    except (TypeError, ValueError):
        volume = DEFAULT_CONFIG["music"]["volume"]
    playlist = source.get("playlist", [])
    if not isinstance(playlist, list) or not all(isinstance(item, str) for item in playlist):
        playlist = []
    mode = source.get("mode", "목록 반복")
    if mode not in {"목록 반복", "한 곡 반복", "순서대로"}:
        mode = "목록 반복"
    return {"playlist": playlist, "volume": volume, "mode": mode}


def _normalise_wallet(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    currencies = source.get("currencies", {})
    if not isinstance(currencies, dict):
        currencies = {}
    cleaned: dict[str, int] = {}
    for currency, amount in currencies.items():
        if not isinstance(currency, str):
            continue
        try:
            cleaned[currency] = max(0, int(amount))
        except (TypeError, ValueError, OverflowError):
            cleaned[currency] = 0
    cleaned.setdefault("tool_coin", DEFAULT_CONFIG["toolbox_wallet"]["currencies"]["tool_coin"])
    last_grant = source.get("last_daily_grant", "")
    if not isinstance(last_grant, str):
        last_grant = ""
    return {"currencies": cleaned, "last_daily_grant": last_grant}
