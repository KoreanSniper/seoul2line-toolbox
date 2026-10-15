from __future__ import annotations

import tkinter as tk
import time
from copy import deepcopy

from app.economy import add_coins, balance, format_coins, spend_coins
from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton


STATE_KEY = "factory_automation"
WORLD_VERSION = 3
CELL_SIZE = 64

BUILDINGS = {
    "generator": {"name": "생성기", "cost": 320, "color": "#22c55e", "short": "G"},
    "conveyor": {"name": "컨베이어", "cost": 180, "color": "#38bdf8", "short": "C"},
    "seller": {"name": "판매기", "cost": 460, "color": "#f97316", "short": "S"},
    "splitter": {"name": "분배기", "cost": 620, "color": "#c084fc", "short": "D"},
    "merger": {"name": "합류기", "cost": 700, "color": "#f472b6", "short": "M"},
    "warehouse": {"name": "창고", "cost": 540, "color": "#facc15", "short": "W"},
    "booster": {"name": "가속기", "cost": 900, "color": "#ef4444", "short": "B"},
    "miner": {"name": "채굴기", "cost": 800, "color": "#64748b", "short": "MIN"},
    "smelter": {"name": "제련기", "cost": 1400, "ore_cost": 5, "color": "#fb923c", "short": "SM"},
    "furnace": {"name": "용광로", "cost": 2800, "ore_cost": 15, "color": "#dc2626", "short": "F"},
}
FLOW_BLOCKS = {"conveyor", "splitter", "merger", "warehouse", "booster", "smelter", "furnace"}
SOURCE_BLOCKS = {"generator", "miner"}
DIRECTIONS = (("right", "→"), ("down", "↓"), ("left", "←"), ("up", "↑"))
DIRECTION_DELTAS = {"right": (1, 0), "down": (0, 1), "left": (-1, 0), "up": (0, -1)}
DEFAULT_STATE = {
    "world_version": WORLD_VERSION,
    "blocks": {},
    "pending_coins": 0.0,
    "last_run": 0,
    "discovered": {},
    "minerals": 0,
}


class FactoryWorld(tk.Frame):
    """무한 격자 위에 설비를 배치하는 가벼운 공장 월드."""

    def __init__(self, parent: tk.Widget, app: object) -> None:
        colors = palette(app.dark_mode)
        super().__init__(parent, bg=colors["panel"])
        self.app = app
        self.colors = colors
        self.state = self._load_state()
        self.blocks: dict[str, dict[str, object]] = self.state["blocks"]
        self.discovered: dict[str, str] = self.state["discovered"]
        self.camera_x = 0
        self.camera_y = 0
        self.move_keys: set[str] = set()
        self._move_job: str | None = None
        self.selected_building: str | None = None
        self.hover_cell: tuple[int, int] | None = None
        self.last_tick = time.time()
        self.last_persist = 0.0
        self.offline_earnings = 0
        self._tick_job: str | None = None
        self._animation_job: str | None = None
        self._coin_items: list[tuple[int, int, list[tuple[int, int]], str]] = []
        self._ticker_item: int | None = None
        self._ticker_x = 0.0
        self._resource_text = ""
        self.inventory_visible = False
        self.canvas: tk.Canvas | None = None
        self.inventory: tk.Frame | None = None
        self.status = tk.StringVar(value="E: 인벤토리 / WASD: 이동 / 좌클릭: 설치 / 우클릭: 메뉴")
        self._build()
        self._apply_offline_progress()
        self._discover_area()
        if self.offline_earnings:
            self.status.set(f"오프라인 생산 정산: {format_coins(self.offline_earnings)}")
        self.focus_set()
        self.bind("<KeyPress>", self._on_key, add="+")
        self.bind("<KeyRelease>", self._on_key_release, add="+")
        self._draw()
        self._tick_job = self.after(500, self._tick)
        self._animation_job = self.after(50, self._animate)

    def _load_state(self) -> dict[str, object]:
        stored = self.app.config_store.get(STATE_KEY, default={})
        # 이전 공장 규칙과 저장 데이터는 새 조작 방식과 호환하지 않으므로 초기화한다.
        if not isinstance(stored, dict) or int(stored.get("world_version", 0)) != WORLD_VERSION:
            state = deepcopy(DEFAULT_STATE)
            self.app.config_store.set(STATE_KEY, value=state)
            return state
        blocks = stored.get("blocks", {})
        if not isinstance(blocks, dict):
            blocks = {}
        clean: dict[str, dict[str, object]] = {}
        for key, block in blocks.items():
            if not isinstance(block, dict) or block.get("type") not in BUILDINGS:
                continue
            clean[str(key)] = {
                "type": str(block["type"]),
                "level": max(1, int(block.get("level", 1))),
                "direction": str(block.get("direction", "right")),
            }
        discovered = stored.get("discovered", {})
        if not isinstance(discovered, dict):
            discovered = {}
        return {
            "world_version": WORLD_VERSION,
            "blocks": clean,
            "pending_coins": max(0.0, float(stored.get("pending_coins", 0.0))),
            "last_run": max(0, int(stored.get("last_run", 0))),
            "discovered": {str(key): str(value) for key, value in discovered.items()},
            "minerals": max(0, int(stored.get("minerals", 0))),
        }

    def _save_state(self) -> None:
        self.state["world_version"] = WORLD_VERSION
        self.state["blocks"] = self.blocks
        self.state["discovered"] = self.discovered
        self.state["minerals"] = max(0, int(self.state.get("minerals", 0)))
        self.state["last_run"] = int(time.time())
        self.app.config_store.set(STATE_KEY, value=self.state)

    def _production_routes(self) -> list[tuple[dict[str, object], dict[str, object], list[tuple[int, int]]]]:
        """방향을 따라 생성기에서 판매기까지 이어진 경로와 칸 목록을 찾는다."""
        routes: list[tuple[dict[str, object], dict[str, object], list[tuple[int, int]]]] = []
        for key, generator in self.blocks.items():
            if generator.get("type") not in SOURCE_BLOCKS:
                continue
            try:
                gx, gy = (int(value) for value in key.split(",", 1))
            except (TypeError, ValueError):
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                current = self._key(gx + dx, gy + dy)
                visited = {key}
                route = [(gx, gy)]
                while current not in visited:
                    visited.add(current)
                    try:
                        cx, cy = (int(value) for value in current.split(",", 1))
                    except (TypeError, ValueError):
                        break
                    route.append((cx, cy))
                    block = self.blocks.get(current)
                    if block is None:
                        break
                    if block.get("type") == "seller":
                        routes.append((generator, block, route))
                        break
                    if block.get("type") not in FLOW_BLOCKS:
                        break
                    if block.get("type") == "merger":
                        outputs = []
                        for out_dx, out_dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            output_key = self._key(cx + out_dx, cy + out_dy)
                            output_block = self.blocks.get(output_key)
                            if output_key not in visited and isinstance(output_block, dict) and (
                                output_block.get("type") in FLOW_BLOCKS or output_block.get("type") == "seller"
                            ):
                                outputs.append(output_key)
                        if not outputs:
                            break
                        current = outputs[int(time.time() * 2 + cx + cy) % len(outputs)]
                    else:
                        delta = DIRECTION_DELTAS.get(str(block.get("direction", "right")), (1, 0))
                        current = self._key(cx + delta[0], cy + delta[1])
        return routes

    def _production_paths(self) -> list[tuple[dict[str, object], dict[str, object]]]:
        return [(generator, seller) for generator, seller, _route in self._production_routes()]

    def _income_rate(self) -> float:
        rate = 0.0
        for generator, seller, route in self._production_routes():
            multiplier = 1.0
            for gx, gy in route:
                block = self.blocks.get(self._key(gx, gy), {})
                if block.get("type") == "booster":
                    multiplier += 0.5 * max(1, int(block.get("level", 1)))
            rate += 0.35 * max(1, int(generator.get("level", 1))) * max(1, int(seller.get("level", 1))) * multiplier
        return rate

    def _apply_offline_progress(self) -> None:
        now = int(time.time())
        last_run = int(self.state.get("last_run", now))
        elapsed = max(0, min(7 * 24 * 60 * 60, now - last_run))
        earnings = int(elapsed * self._income_rate())
        if earnings:
            add_coins(self.app.config_store, earnings)
            self.offline_earnings = earnings
        self.state["last_run"] = now
        self._save_state()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=self.colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="공장 월드", font=("Segoe UI", 20, "bold"), fg=self.colors["text"], bg=self.colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, textvariable=self.status, font=("Segoe UI", 9), fg=self.colors["muted"], bg=self.colors["panel"]).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.resource_ticker = tk.Canvas(header, height=26, bg=self.colors["panel"], highlightthickness=0, bd=0)
        self.resource_ticker.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._update_resource_text()
        body = tk.Frame(self, bg=self.colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, bg=self.colors["surface"], highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        self.canvas.bind("<Button-1>", self._place)
        self.canvas.bind("<Button-3>", self._block_menu)
        self.canvas.bind("<Motion>", self._hover)
        self._build_inventory(body)

    def _build_inventory(self, parent: tk.Widget) -> None:
        self.inventory = tk.Frame(parent, bg=self.colors["panel_soft"], highlightthickness=1, highlightbackground=self.colors["border"])
        self.inventory.place(relx=1.0, rely=0.0, anchor="ne", relwidth=0.28, relheight=1.0)
        tk.Label(self.inventory, text="인벤토리", font=("Segoe UI", 14, "bold"), fg=self.colors["text"], bg=self.colors["panel_soft"]).pack(anchor="w", padx=14, pady=(14, 4))
        tk.Label(self.inventory, text="설비를 선택한 뒤 월드에서 좌클릭하세요.", font=("Segoe UI", 9), fg=self.colors["muted"], bg=self.colors["panel_soft"], wraplength=220, justify="left").pack(anchor="w", padx=14, pady=(0, 12))
        for key, meta in BUILDINGS.items():
            cost_text = format_coins(int(meta["cost"]))
            ore_cost = int(meta.get("ore_cost", 0))
            if ore_cost:
                cost_text += f" + 광물 {ore_cost}"
            RoundedButton(
                self.inventory,
                f"{meta['name']}  {cost_text}",
                lambda key=key: self._select_building(key),
                self.colors,
                compact=True,
                radius=9,
            ).pack(fill="x", padx=12, pady=4)
        tk.Label(self.inventory, text="E를 누르면 닫습니다.", font=("Segoe UI", 8), fg=self.colors["subtle"], bg=self.colors["panel_soft"]).pack(anchor="w", padx=14, pady=(16, 0))
        self.inventory.place_forget()

    def _focus_world(self, _event: tk.Event) -> None:
        self.focus_set()

    def _on_key(self, event: tk.Event) -> None:
        key = str(event.keysym).lower()
        if key == "e":
            self._toggle_inventory()
            return
        movement = {"w": (0, -1), "a": (-1, 0), "s": (0, 1), "d": (1, 0)}
        if key in movement:
            self.move_keys.add(key)
            if self._move_job is None:
                self._smooth_move()

    def _on_key_release(self, event: tk.Event) -> None:
        self.move_keys.discard(str(event.keysym).lower())

    def _smooth_move(self) -> None:
        self._move_job = None
        if not self.winfo_exists() or not self.move_keys:
            return
        dx = (1 if "d" in self.move_keys else 0) - (1 if "a" in self.move_keys else 0)
        dy = (1 if "s" in self.move_keys else 0) - (1 if "w" in self.move_keys else 0)
        self.camera_x += dx * 0.12
        self.camera_y += dy * 0.12
        self.status.set(f"위치 {round(self.camera_x, 1)}, {round(self.camera_y, 1)} / E: 인벤토리")
        self._discover_area()
        self._draw()
        self._move_job = self.after(20, self._smooth_move)

    @staticmethod
    def _resource_at(gx: int, gy: int) -> tuple[str, int, str] | None:
        if abs(gx) + abs(gy) < 3:
            return None
        seed = abs(gx * 92821 + gy * 68917 + gx * gy * 17) % 101
        if seed == 7:
            return ("구리 광맥", 180, "#b87333")
        if seed == 13:
            return ("황금 지대", 520, "#facc15")
        if seed == 29:
            return ("보너스 유적", 900, "#a78bfa")
        return None

    def _discover_area(self) -> None:
        found: list[str] = []
        center_x = round(self.camera_x)
        center_y = round(self.camera_y)
        for gx in range(center_x - 3, center_x + 4):
            for gy in range(center_y - 3, center_y + 4):
                key = self._key(gx, gy)
                resource = self._resource_at(gx, gy)
                if resource is not None and key not in self.discovered:
                    name, reward, _color = resource
                    self.discovered[key] = name
                    mineral_gain = {"구리 광맥": 1, "황금 지대": 3, "보너스 유적": 8}.get(name, 1)
                    self.state["minerals"] = int(self.state.get("minerals", 0)) + mineral_gain
                    add_coins(self.app.config_store, reward)
                    found.append(f"{name} 발견 +광물 {mineral_gain} / {format_coins(reward)}")
        if found:
            self._save_state()
            self.status.set(" / ".join(found[:2]))

    def _toggle_inventory(self) -> None:
        self.inventory_visible = not self.inventory_visible
        if self.inventory is None:
            return
        if self.inventory_visible:
            self.inventory.place(relx=1.0, rely=0.0, anchor="ne", relwidth=0.28, relheight=1.0)
        else:
            self.inventory.place_forget()
        self.focus_set()

    def _select_building(self, building_key: str) -> None:
        self.selected_building = building_key
        meta = BUILDINGS[building_key]
        self.status.set(f"{meta['name']} 선택 / 비용 {format_coins(int(meta['cost']))} / 월드를 좌클릭하세요.")
        self.focus_set()

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        now = time.time()
        elapsed = max(0.0, min(2.0, now - self.last_tick))
        self.last_tick = now
        self._update_resource_text()
        self.state["pending_coins"] = float(self.state.get("pending_coins", 0.0)) + self._income_rate() * elapsed
        payout = int(self.state["pending_coins"])
        if payout > 0:
            self.state["pending_coins"] = float(self.state["pending_coins"]) - payout
            self.state["minerals"] = int(self.state.get("minerals", 0)) + payout
            add_coins(self.app.config_store, payout)
        if time.time() - self.last_persist >= 5:
            self._save_state()
            self.last_persist = time.time()
        self._update_coin_positions()
        self._tick_job = self.after(500, self._tick)

    def _animate(self) -> None:
        if not self.winfo_exists():
            return
        self._update_coin_positions()
        self._update_resource_ticker()
        self._animation_job = self.after(50, self._animate)

    def _update_resource_text(self) -> None:
        counts: dict[str, int] = {}
        for name in self.discovered.values():
            counts[name] = counts.get(name, 0) + 1
        parts = [f"툴코인 {balance(self.app.config_store):,} TC", f"보유 광물 {int(self.state.get('minerals', 0))}개"]
        parts.extend(f"{name} {count}곳" for name, count in sorted(counts.items()))
        text = "   |   ".join(parts)
        if text == self._resource_text:
            return
        self._resource_text = text
        if self._ticker_item is None:
            self._ticker_x = max(40, self.resource_ticker.winfo_width())
            self._ticker_item = self.resource_ticker.create_text(
                self._ticker_x,
                13,
                text=text,
                anchor="w",
                fill=self.colors["text"],
                font=("Segoe UI", 9, "bold"),
            )
        else:
            self.resource_ticker.itemconfigure(self._ticker_item, text=text)

    def _update_resource_ticker(self) -> None:
        if self._ticker_item is None or not self.resource_ticker.winfo_exists():
            return
        self._update_resource_text()
        self.resource_ticker.move(self._ticker_item, -0.7, 0)
        bbox = self.resource_ticker.bbox(self._ticker_item)
        if bbox and bbox[2] < 0:
            self.resource_ticker.coords(self._ticker_item, max(40, self.resource_ticker.winfo_width()), 13)

    def _hover(self, event: tk.Event) -> None:
        cell = self._screen_to_cell(int(event.x), int(event.y))
        if cell == self.hover_cell:
            return
        self.hover_cell = cell
        self._draw()

    def _screen_to_cell(self, x: int, y: int) -> tuple[int, int]:
        assert self.canvas is not None
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        return (
            round(round((x - width / 2) / CELL_SIZE) + self.camera_x),
            round(round((y - height / 2) / CELL_SIZE) + self.camera_y),
        )

    def _cell_to_screen(self, gx: int, gy: int) -> tuple[float, float]:
        assert self.canvas is not None
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        return ((gx - self.camera_x) * CELL_SIZE + width / 2, (gy - self.camera_y) * CELL_SIZE + height / 2)

    @staticmethod
    def _key(gx: int, gy: int) -> str:
        return f"{gx},{gy}"

    def _place(self, event: tk.Event) -> None:
        if not self.selected_building:
            self._toggle_inventory()
            return
        gx, gy = self._screen_to_cell(int(event.x), int(event.y))
        key = self._key(gx, gy)
        if key in self.blocks:
            self.status.set("이미 설치된 블록입니다. 우클릭으로 메뉴를 여세요.")
            return
        meta = BUILDINGS[self.selected_building]
        cost = int(meta["cost"])
        ore_cost = int(meta.get("ore_cost", 0))
        minerals = int(self.state.get("minerals", 0))
        if self.selected_building == "miner" and key not in self.discovered:
            self.status.set("채굴기는 발견한 광맥 위에만 설치할 수 있습니다.")
            return
        if minerals < ore_cost:
            self.status.set(f"광물 {ore_cost}개가 필요합니다. 현재 {minerals}개")
            return
        if not spend_coins(self.app.config_store, cost):
            self.status.set(f"{meta['name']} 설치에 {format_coins(cost)}가 필요합니다.")
            return
        self.blocks[key] = {"type": self.selected_building, "level": 1, "direction": "right"}
        self.state["minerals"] = minerals - ore_cost
        self._save_state()
        self.status.set(f"{meta['name']} 설치 완료: {gx}, {gy}")
        self._draw()

    def _block_menu(self, event: tk.Event) -> None:
        gx, gy = self._screen_to_cell(int(event.x), int(event.y))
        key = self._key(gx, gy)
        block = self.blocks.get(key)
        if block is None:
            self.status.set(f"빈 칸 {gx}, {gy}")
            return
        menu = tk.Menu(self, tearoff=False)
        meta = BUILDINGS[str(block["type"])]
        level = int(block.get("level", 1))
        menu.add_command(label=f"{meta['name']} Lv.{level}", state="disabled")
        menu.add_separator()
        menu.add_command(label=f"업그레이드 ({format_coins(self._upgrade_cost(block))})", command=lambda: self._upgrade(key))
        if block["type"] in FLOW_BLOCKS:
            direction_menu = tk.Menu(menu, tearoff=False)
            for direction, symbol in DIRECTIONS:
                direction_menu.add_command(label=symbol, command=lambda direction=direction: self._change_direction(key, direction))
            menu.add_cascade(label="방향 변경", menu=direction_menu)
        menu.add_command(label="삭제", command=lambda: self._delete(key))
        menu.tk_popup(int(event.x_root), int(event.y_root))

    def _upgrade_cost(self, block: dict[str, object]) -> int:
        meta = BUILDINGS[str(block["type"])]
        return int(meta["cost"]) * max(1, int(block.get("level", 1)))

    def _upgrade(self, key: str) -> None:
        block = self.blocks.get(key)
        if block is None:
            return
        cost = self._upgrade_cost(block)
        if not spend_coins(self.app.config_store, cost):
            self.status.set(f"업그레이드에 {format_coins(cost)}가 필요합니다.")
            return
        block["level"] = int(block.get("level", 1)) + 1
        self._save_state()
        self.status.set(f"업그레이드 완료 / 현재 Lv.{block['level']}")
        self._draw()

    def _change_direction(self, key: str, direction: str) -> None:
        block = self.blocks.get(key)
        if block is None:
            return
        block["direction"] = direction
        self._save_state()
        self.status.set(f"컨베이어 방향 {dict(DIRECTIONS)[direction]}")
        self._draw()

    def _delete(self, key: str) -> None:
        block = self.blocks.pop(key, None)
        if block is None:
            return
        refund = int(BUILDINGS[str(block["type"])] ["cost"]) // 2
        add_coins(self.app.config_store, refund)
        self._save_state()
        self.status.set(f"블록 삭제 / {format_coins(refund)} 환불")
        self._draw()

    def _flow_connections(self, gx: int, gy: int, block: dict[str, object]) -> list[tuple[int, int]]:
        connections: list[tuple[int, int]] = []
        block_type = str(block.get("type"))
        if block_type == "merger":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if self._key(gx + dx, gy + dy) in self.blocks:
                    connections.append((gx + dx, gy + dy))
        else:
            dx, dy = DIRECTION_DELTAS.get(str(block.get("direction", "right")), (1, 0))
            if self._key(gx + dx, gy + dy) in self.blocks:
                connections.append((gx + dx, gy + dy))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor_key = self._key(gx + dx, gy + dy)
            neighbor = self.blocks.get(neighbor_key)
            if not isinstance(neighbor, dict):
                continue
            if neighbor.get("type") in SOURCE_BLOCKS:
                connections.append((gx + dx, gy + dy))
                continue
            if neighbor.get("type") in FLOW_BLOCKS:
                out_dx, out_dy = DIRECTION_DELTAS.get(str(neighbor.get("direction", "right")), (1, 0))
                if (gx + dx + out_dx, gy + dy + out_dy) == (gx, gy):
                    connections.append((gx + dx, gy + dy))
        return list(dict.fromkeys(connections))

    def _source_coin_color(self, source: dict[str, object]) -> str:
        if source.get("type") != "miner":
            return "#22c55e"
        source_key = next((key for key, block in self.blocks.items() if block is source), "")
        try:
            gx, gy = (int(value) for value in source_key.split(",", 1))
        except (TypeError, ValueError):
            return "#f97316"
        resource = self._resource_at(gx, gy)
        return resource[2] if resource is not None else "#f97316"

    def _draw(self) -> None:
        if self.canvas is None or not self.winfo_exists():
            return
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        center_x = round(self.camera_x)
        center_y = round(self.camera_y)
        left = center_x - int(width / CELL_SIZE) - 2
        right = center_x + int(width / CELL_SIZE) + 2
        top = center_y - int(height / CELL_SIZE) - 2
        bottom = center_y + int(height / CELL_SIZE) + 2
        for gx in range(left, right + 1):
            x, _ = self._cell_to_screen(gx, center_y)
            canvas.create_line(x, 0, x, height, fill=self.colors["border_soft"])
        for gy in range(top, bottom + 1):
            _, y = self._cell_to_screen(center_x, gy)
            canvas.create_line(0, y, width, y, fill=self.colors["border_soft"])
        for gx in range(left, right + 1):
            for gy in range(top, bottom + 1):
                key = self._key(gx, gy)
                resource = self._resource_at(gx, gy)
                if key not in self.discovered or resource is None or key in self.blocks:
                    continue
                x, y = self._cell_to_screen(gx, gy)
                _name, _reward, color = resource
                canvas.create_oval(x - 14, y - 14, x + 14, y + 14, fill=color, outline=self.colors["text"], width=2)
                canvas.create_text(x, y, text="$", fill="#111827", font=("Segoe UI", 14, "bold"))
        for key, block in sorted(self.blocks.items(), key=lambda item: str(item[1].get("type")) != "conveyor"):
            try:
                gx, gy = (int(value) for value in key.split(",", 1))
            except (TypeError, ValueError):
                continue
            x, y = self._cell_to_screen(gx, gy)
            if not (-CELL_SIZE <= x <= width + CELL_SIZE and -CELL_SIZE <= y <= height + CELL_SIZE):
                continue
            meta = BUILDINGS.get(str(block["type"]))
            if meta is None:
                continue
            if block["type"] in FLOW_BLOCKS:
                for nx, ny in self._flow_connections(gx, gy, block):
                    next_x, next_y = self._cell_to_screen(nx, ny)
                    line_options = {"fill": meta["color"], "width": 18}
                    if block["type"] == "conveyor":
                        line_options["stipple"] = "gray50"
                    canvas.create_line(x, y, next_x, next_y, **line_options)
                if block["type"] == "merger":
                    box = (x - 24, y - 24, x + 24, y + 24)
                else:
                    horizontal = str(block.get("direction", "right")) in {"left", "right"}
                    box = (x - 28, y - 17, x + 28, y + 17) if horizontal else (x - 17, y - 28, x + 17, y + 28)
                box_options = {"fill": meta["color"], "outline": self.colors["text"], "width": 2}
                if block["type"] == "conveyor":
                    box_options["stipple"] = "gray50"
                canvas.create_rectangle(*box, **box_options)
            else:
                canvas.create_rectangle(x - 25, y - 25, x + 25, y + 25, fill=meta["color"], outline=self.colors["text"], width=2)
            canvas.create_text(x, y - 7, text=meta["short"], fill="#081018", font=("Segoe UI", 15, "bold"))
            if block["type"] in FLOW_BLOCKS:
                canvas.create_text(x, y + 15, text=dict(DIRECTIONS).get(str(block.get("direction", "right")), "→"), fill="#081018", font=("Segoe UI", 13, "bold"))
            elif block["type"] in {"generator", "miner"}:
                coin_color = self._source_coin_color(block)
                canvas.create_oval(x + 12, y - 20, x + 25, y - 7, fill=coin_color, outline="#fff7ed")
                canvas.create_text(x + 18, y - 13, text="TC", fill="#431407" if block["type"] == "miner" else "#052e16", font=("Segoe UI", 5, "bold"))
            else:
                canvas.create_text(x, y + 15, text=f"Lv.{int(block.get('level', 1))}", fill="#081018", font=("Segoe UI", 9, "bold"))
        self._coin_items = []
        for generator, _seller, route in self._production_routes():
            if len(route) < 2:
                continue
            coin_color = self._source_coin_color(generator)
            coin = canvas.create_oval(0, 0, 0, 0, fill=coin_color, outline="#fff7ed", width=2)
            label = canvas.create_text(0, 0, text="TC", fill="#052e16", font=("Segoe UI", 5, "bold"))
            self._coin_items.append((coin, label, route, coin_color))
        self._update_coin_positions()
        if self.selected_building and self.hover_cell is not None:
            gx, gy = self.hover_cell
            ghost_key = self._key(gx, gy)
            if ghost_key not in self.blocks:
                meta = BUILDINGS[self.selected_building]
                x, y = self._cell_to_screen(gx, gy)
                canvas.create_rectangle(
                    x - 25,
                    y - 25,
                    x + 25,
                    y + 25,
                    fill=meta["color"],
                    outline=self.colors["text"],
                    width=2,
                    stipple="gray50",
                )
                canvas.create_text(x, y, text=meta["short"], fill=self.colors["text"], font=("Segoe UI", 15, "bold"))
        canvas.create_text(16, 16, text=f"무한 월드  위치 {self.camera_x}, {self.camera_y}", anchor="nw", fill=self.colors["text"], font=("Segoe UI", 14, "bold"))

    def _update_coin_positions(self) -> None:
        if self.canvas is None:
            return
        for coin, label, route, _coin_color in self._coin_items:
            if len(route) < 2:
                continue
            segment_count = len(route) - 1
            progress = (time.time() * 1.2) % segment_count
            index = min(int(progress), segment_count - 1)
            fraction = min(progress - index, 0.98)
            start_x, start_y = self._cell_to_screen(*route[index])
            end_x, end_y = self._cell_to_screen(*route[index + 1])
            coin_x = start_x + (end_x - start_x) * fraction
            coin_y = start_y + (end_y - start_y) * fraction
            self.canvas.coords(coin, coin_x - 9, coin_y - 9, coin_x + 9, coin_y + 9)
            self.canvas.coords(label, coin_x, coin_y)

    def destroy(self) -> None:
        if self._move_job is not None:
            try:
                self.after_cancel(self._move_job)
            except tk.TclError:
                pass
            self._move_job = None
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except tk.TclError:
                pass
            self._tick_job = None
        if self._animation_job is not None:
            try:
                self.after_cancel(self._animation_job)
            except tk.TclError:
                pass
            self._animation_job = None
        self._save_state()
        self.unbind("<KeyPress>")
        self.unbind("<KeyRelease>")
        super().destroy()


class FactoryLauncher(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.window: tk.Toplevel | None = None
        colors = palette(app.dark_mode)
        tk.Label(self, text="공장 월드", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w", padx=24, pady=(24, 6))
        tk.Label(self, text="무한 격자를 이동하며 블록을 배치하는 공장 샌드박스입니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).pack(anchor="w", padx=24)
        RoundedButton(self, "공장 창 열기", self.open_factory, colors, accent=True, radius=12).pack(anchor="w", padx=24, pady=24)

    def open_factory(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return
        self.window = tk.Toplevel(self)
        self.window.title("공장 월드")
        self.window.geometry("1100x760")
        self.window.minsize(760, 520)
        world = FactoryWorld(self.window, self.app)
        world.pack(fill="both", expand=True)

        def close() -> None:
            world.destroy()
            self.window.destroy()
            self.window = None

        self.window.protocol("WM_DELETE_WINDOW", close)


FactoryAutomationGame = FactoryWorld


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return FactoryLauncher(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("minigame.factory", "공장 자동화", "미니게임", build, 25))
