from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import pkgutil
from typing import Callable, Iterable
import tkinter as tk


ToolFactory = Callable[[tk.Widget, object], tk.Widget]
MenuAction = Callable[[object], object]
SECTION_ORDER = {
    "Home": 0,
    "홈": 0,
    "Gaming": 10,
    "게임": 10,
    "Network": 30,
    "네트워크": 30,
    "Files": 40,
    "파일": 40,
    "Minigames": 50,
    "미니게임": 50,
    "Settings": 999,
    "설정": 999,
}


@dataclass(frozen=True)
class ToolSpec:
    id: str
    label: str
    section: str
    factory: ToolFactory
    order: int = 100
    plugin_id: str | None = None


@dataclass(frozen=True)
class MenuSpec:
    id: str
    label: str
    section: str
    action: MenuAction
    order: int = 100
    plugin_id: str | None = None


@dataclass(frozen=True)
class SectionSpec:
    label: str
    icon: str = "P"
    description: str = "플러그인 메뉴"
    order: int = 500
    plugin_id: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: list[ToolSpec] = []
        self._menus: list[MenuSpec] = []
        self._sections: list[SectionSpec] = []

    def register(self, spec: ToolSpec) -> None:
        self._tools.append(spec)

    def register_menu(self, spec: MenuSpec) -> None:
        self._menus.append(spec)

    def register_section(self, spec: SectionSpec) -> None:
        self._sections.append(spec)

    def sections(self) -> list[str]:
        labels = {tool.section for tool in self._tools}
        labels.update(menu.section for menu in self._menus)
        labels.update(section.label for section in self._sections)
        order = {section.label: section.order for section in self._sections}
        return sorted(labels, key=lambda label: (order.get(label, SECTION_ORDER.get(label, 500)), label))

    def tools_for(self, section: str) -> list[ToolSpec]:
        return sorted(
            [tool for tool in self._tools if tool.section == section],
            key=lambda item: (item.order, item.label),
        )

    def first_tool(self, section: str) -> ToolSpec | None:
        tools = self.tools_for(section)
        return tools[0] if tools else None

    def menus_for(self, section: str) -> list[MenuSpec]:
        return sorted(
            [menu for menu in self._menus if menu.section == section],
            key=lambda item: (item.order, item.label),
        )

    def section_spec(self, section: str) -> SectionSpec | None:
        for spec in self._sections:
            if spec.label == section:
                return spec
        return None


MODULE_ORDER = {
    "home": 0,
    "gaming": 10,
    "gaming_music": 11,
    "workspace_presets": 12,
    "system_monitor": 13,
    "network": 50,
    "network_lan_remote": 51,
    "files": 60,
    "file_converter": 61,
    "cursor_editor": 62,
    "clipboard_history": 61,
    "diff_tool": 62,
    "process_manager": 63,
    "screenshot_tool": 64,
    "chill": 65,
    "chill_starsystem_gpu": 66,
    "minigame_trsim": 67,
    "minigame_factory": 69,
    "minigame_korean_stocks": 70,
    "settings": 90,
}

def load_builtin_tools() -> ToolRegistry:
    registry = ToolRegistry()
    package = import_module("app.tools")
    discovered = [
        name
        for _finder, name, is_package in pkgutil.iter_modules(package.__path__)
        if not is_package and not name.startswith("_")
    ]
    for module_name in sorted(discovered, key=lambda name: (MODULE_ORDER.get(name, 999), name)):
        module = import_module(f"app.tools.{module_name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(registry)
    return registry


def cards(parent: tk.Widget, items: Iterable[tuple[str, str]]) -> tk.Frame:
    frame = tk.Frame(parent, bg=parent.cget("bg"))
    bg = parent.cget("bg")
    for i, (title, body) in enumerate(items):
        card = tk.Frame(frame, bg="#19232d" if bg != "#ffffff" else "#f6f8fb", highlightthickness=1, highlightbackground="#263342")
        card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=10, pady=10)
        tk.Label(card, text=title, font=("Segoe UI", 12, "bold"), fg="#edf2f7" if bg != "#ffffff" else "#16202a", bg=card.cget("bg")).pack(
            anchor="w", padx=18, pady=(16, 5)
        )
        tk.Label(
            card,
            text=body,
            font=("Segoe UI", 9),
            fg="#94a3b8" if bg != "#ffffff" else "#53616e",
            bg=card.cget("bg"),
            justify="left",
            wraplength=260,
        ).pack(anchor="w", padx=18, pady=(0, 16))
    frame.columnconfigure(0, weight=1)
    frame.columnconfigure(1, weight=1)
    return frame
