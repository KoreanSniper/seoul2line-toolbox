from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any
import zipfile

from app.tool_registry import MenuSpec, SectionSpec, ToolRegistry, ToolSpec
from app.paths import application_root, data_directory
from app.file_ops import retry_on_windows_lock


PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    path: Path
    entrypoint: str
    enabled: bool = True
    status: str = "발견됨"
    error: str = ""


class PluginRegistry:
    """Plugin-facing registry that marks tools with their owning plugin."""

    def __init__(self, registry: ToolRegistry, plugin_id: str) -> None:
        self._registry = registry
        self._plugin_id = plugin_id

    def register(self, spec: ToolSpec) -> None:
        self._registry.register(
            ToolSpec(spec.id, spec.label, spec.section, spec.factory, spec.order, self._plugin_id)
        )

    def register_menu(self, spec: MenuSpec) -> None:
        self._registry.register_menu(
            MenuSpec(spec.id, spec.label, spec.section, spec.action, spec.order, self._plugin_id)
        )

    def register_section(self, spec: SectionSpec) -> None:
        self._registry.register_section(
            SectionSpec(spec.label, spec.icon, spec.description, spec.order, self._plugin_id)
        )


class PluginManager:
    def __init__(self, config_store: Any, project_root: Path | None = None) -> None:
        root = project_root or application_root()
        user_root = root / "user_data" if project_root is not None else data_directory()
        self.roots = (root / "plugins", user_root / "plugins")
        self.config_store = config_store
        self.plugins: list[PluginInfo] = []

    def load_into(self, registry: ToolRegistry) -> list[PluginInfo]:
        self.plugins = self.discover()
        seen_ids: set[str] = set()
        for plugin in self.plugins:
            if plugin.id in seen_ids:
                plugin.status = "중복 ID"
                plugin.error = "같은 ID의 플러그인이 이미 발견되었습니다."
                continue
            seen_ids.add(plugin.id)
            if not plugin.enabled:
                plugin.status = "비활성화"
                continue
            self._load_plugin(plugin, registry)
        return self.plugins

    def discover(self) -> list[PluginInfo]:
        discovered: list[PluginInfo] = []
        for root in self.roots:
            if not root.is_dir():
                continue
            try:
                candidates = sorted(root.iterdir(), key=lambda path: path.name.lower())
            except OSError:
                continue
            for candidate in candidates:
                if candidate.is_dir():
                    manifest_path = candidate / "plugin.json"
                    if manifest_path.is_file():
                        discovered.append(self._read_manifest(manifest_path, candidate))
                elif candidate.suffix.lower() == ".py" and not candidate.name.startswith("_"):
                    discovered.append(
                        PluginInfo(
                            id=candidate.stem,
                            name=candidate.stem.replace("_", " ").title(),
                            version="0.0.0",
                            path=candidate.parent,
                            entrypoint=candidate.name,
                            enabled=self._is_enabled(candidate.stem),
                        )
                    )
        return discovered

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        enabled_map = self.config_store.get("plugins", "enabled", default={})
        if not isinstance(enabled_map, dict):
            enabled_map = {}
        enabled_map = dict(enabled_map)
        enabled_map[plugin_id] = bool(enabled)
        self.config_store.set("plugins", "enabled", value=enabled_map)

    def install_zip(self, archive_path: Path) -> PluginInfo:
        """Validate and stage a ZIP without executing code, then install atomically."""
        try:
            return self._install_zip(archive_path)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            raise ValueError(f"ZIP 파일을 읽을 수 없습니다: {exc}") from exc

    def _install_zip(self, archive_path: Path) -> PluginInfo:
        # Stage beside the destination so the final rename stays on one filesystem.
        install_root = self.roots[1]
        install_root.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(item.file_size for item in entries) > 256 * 1024 * 1024:
                raise ValueError("ZIP은 파일 10,000개, 압축 해제 크기 256MB 이하여야 합니다.")
            seen: set[str] = set()
            for item in entries:
                parts = item.filename.rstrip("/").split("/")
                if (
                    "\\" in item.orig_filename or "\x00" in item.orig_filename
                    or any(not part or part in (".", "..") or part.endswith((".", " "))
                           or re.search(r'[<>:"|?*\x00-\x1f]', part)
                           or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                           for part in parts)
                ):
                    raise ValueError("ZIP에 안전하지 않은 파일 경로가 있습니다.")
                mode = item.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError("ZIP의 링크 또는 특수 파일은 설치할 수 없습니다.")
                if item.flag_bits & 1:
                    raise ValueError("암호화된 ZIP은 설치할 수 없습니다.")
                key = "/".join(parts).casefold()
                if key in seen:
                    raise ValueError("ZIP에 중복 파일 경로가 있습니다.")
                seen.add(key)

            manifests = [item for item in entries if not item.is_dir()
                         and item.filename.split("/")[-1] == "plugin.json"]
            if len(manifests) != 1:
                raise ValueError("ZIP에는 플러그인 하나의 plugin.json이 있어야 합니다.")
            manifest_parts = manifests[0].filename.split("/")
            if len(manifest_parts) > 2:
                raise ValueError("plugin.json은 ZIP 최상위 또는 바로 아래 플러그인 폴더에 있어야 합니다.")

            with tempfile.TemporaryDirectory(prefix="plugin-install-", dir=install_root.parent) as temporary:
                staging = Path(temporary)
                for item in entries:
                    target = staging.joinpath(*item.filename.rstrip("/").split("/"))
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as source, target.open("xb") as output:
                            shutil.copyfileobj(source, output)
                plugin_root = staging.joinpath(*manifest_parts[:-1])
                plugin = self._read_manifest(plugin_root / "plugin.json", plugin_root)
                if plugin.error:
                    raise ValueError(f"plugin.json 오류: {plugin.error}")
                if plugin.id.endswith("."):
                    raise ValueError("플러그인 ID는 마침표로 끝날 수 없습니다.")
                entrypoint = plugin_root / plugin.entrypoint
                components = [path for directory in ("menus", "tools")
                              for path in (plugin_root / directory).glob("*.py")
                              if not path.name.startswith("_")]
                if not entrypoint.is_file() and not components:
                    raise ValueError("플러그인 실행 파일이나 menus/tools의 Python 파일이 없습니다.")
                if any(existing.id.casefold() == plugin.id.casefold() for existing in self.discover()):
                    raise ValueError(f"이미 설치된 플러그인 ID입니다: {plugin.id}")
                # A prefix avoids reserved Windows directory names even for valid IDs.
                destination = install_root / f"plugin_{plugin.id}"
                if destination.exists() or destination.is_symlink():
                    raise ValueError("설치할 폴더가 이미 있습니다. 기존 파일은 덮어쓰지 않습니다.")
                install_root.mkdir(parents=True, exist_ok=True)
                retry_on_windows_lock(plugin_root.rename, destination)
                plugin.path = destination
                return plugin

    def _is_enabled(self, plugin_id: str) -> bool:
        enabled_map = self.config_store.get("plugins", "enabled", default={})
        if not isinstance(enabled_map, dict):
            return True
        value = enabled_map.get(plugin_id, True)
        return value is not False

    def _read_manifest(self, manifest_path: Path, plugin_root: Path) -> PluginInfo:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("manifest root must be an object")
            plugin_id = raw.get("id")
            if not isinstance(plugin_id, str) or not PLUGIN_ID_RE.fullmatch(plugin_id):
                raise ValueError("id는 영문, 숫자, ., -, _로 구성된 1~64자여야 합니다")
            name = raw.get("name", plugin_id)
            version = raw.get("version", "0.0.0")
            entrypoint = raw.get("entrypoint", "plugin.py")
            if not all(isinstance(value, str) and value.strip() for value in (name, version, entrypoint)):
                raise ValueError("name, version, entrypoint는 문자열이어야 합니다")
            info = PluginInfo(
                id=plugin_id,
                name=name.strip(),
                version=version.strip(),
                path=plugin_root,
                entrypoint=entrypoint.strip(),
                enabled=self._is_enabled(plugin_id),
            )
            entry_path = (plugin_root / info.entrypoint).resolve()
            if plugin_root.resolve() not in entry_path.parents and entry_path != plugin_root.resolve():
                raise ValueError("entrypoint가 플러그인 폴더 밖을 가리킵니다")
            return info
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return PluginInfo(
                id=manifest_path.parent.name,
                name=manifest_path.parent.name,
                version="?",
                path=plugin_root,
                entrypoint="plugin.py",
                enabled=False,
                status="매니페스트 오류",
                error=str(exc),
            )

    def _load_plugin(self, plugin: PluginInfo, registry: ToolRegistry) -> None:
        try:
            plugin_registry = PluginRegistry(registry, plugin.id)
            entry_path = (plugin.path / plugin.entrypoint).resolve()
            if entry_path.is_file():
                self._load_module(entry_path, plugin.id, plugin_registry, required=False)
            for directory_name in ("menus", "tools"):
                component_dir = plugin.path / directory_name
                if not component_dir.is_dir():
                    continue
                for component_path in sorted(component_dir.glob("*.py"), key=lambda path: path.name.lower()):
                    if not component_path.name.startswith("_"):
                        self._load_module(component_path, f"{plugin.id}_{directory_name}", plugin_registry, required=True)
            plugin.status = "활성"
        except Exception as exc:  # plugin code must not stop the host application
            plugin.status = "로드 실패"
            plugin.error = f"{type(exc).__name__}: {exc}"

    def _load_module(self, path: Path, plugin_id: str, registry: PluginRegistry, *, required: bool) -> None:
        module_name = f"_seoul2line_plugin_{re.sub(r'[^A-Za-z0-9_]', '_', plugin_id)}_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"플러그인 모듈을 만들 수 없습니다: {path.name}")
        module = importlib.util.module_from_spec(spec)
        # Some standard-library helpers, including dataclasses, expect the module
        # to be visible in sys.modules while it is being initialized.
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        register = getattr(module, "register", None)
        if callable(register):
            register(registry)
        elif required:
            raise AttributeError(f"{path.parent.name}/{path.name}에 register(registry) 함수가 필요합니다")

