from __future__ import annotations

import tkinter as tk
import time
from pathlib import Path
from tkinter import filedialog, messagebox

from app.config import APP_DIR
from app.games.micro_warfare.model import BUILDING_SPECS, GAME_MODES, UNIT_SPECS, Camera, TERRAIN_COLORS, TILE_SIZE, WarfareGame
from app.games.micro_warfare.storage import load_game, save_game
from app.palette import palette
from app.ui import RoundedButton, styled_scrollbar


class MicroWarfareView(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        colors = palette(app.dark_mode)
        super().__init__(parent, bg=colors["panel"])
        self.game = WarfareGame()
        self.world = self.game.world
        self.camera = Camera(self.world.pixel_width, self.world.pixel_height)
        self.pan_anchor: tuple[int, int] | None = None
        self.selection_start: tuple[float, float] | None = None
        self.selection_end: tuple[float, float] | None = None
        self.last_tick = time.perf_counter()
        self.tick_id: str | None = None
        self.build_kind: str | None = None
        self.build_cursor: tuple[int, int] | None = None
        header = tk.Frame(self, bg=colors["panel"])
        header.pack(fill="x", padx=14, pady=10)
        tk.Label(header, text="Micro Warfare", bg=colors["panel"], fg=colors["text"],
                 font=("Segoe UI", 19, "bold")).pack(anchor="w")
        controls = tk.Frame(header, bg=colors["panel"])
        controls.pack(fill="x", pady=(6, 0))
        RoundedButton(controls, "새 전장", self.new_world, colors, compact=True).pack(side="left")
        self.mode_choice = tk.StringVar(value=GAME_MODES[self.game.mode])
        mode_menu = tk.OptionMenu(controls, self.mode_choice, *GAME_MODES.values())
        mode_menu.configure(bg=colors["field"], fg=colors["text"], highlightthickness=0, relief="flat")
        mode_menu.pack(side="left", padx=8)
        RoundedButton(controls, "일시정지/계속", self.toggle_pause, colors, compact=True).pack(side="left")
        RoundedButton(controls, "자원 반납", self.deposit, colors, compact=True).pack(side="left", padx=8)
        actions = tk.Frame(self, bg=colors["panel"])
        actions.pack(fill="x", padx=14)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        for index, kind in enumerate(("barracks", "warehouse")):
            spec = BUILDING_SPECS[kind]
            RoundedButton(actions, f"{spec['name']} 건설 ({spec['ore']}/{spec['wood']})",
                          lambda kind=kind: self.start_build(kind), colors, compact=True).grid(row=0, column=index, sticky="ew", padx=(0, 8), pady=2)
        RoundedButton(actions, "업그레이드 (80/60 × Lv.)", self.upgrade, colors, compact=True).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=2)
        RoundedButton(actions, "건설 재개", self.resume_build, colors, compact=True).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=2)
        self.status = tk.StringVar()
        self.status_label = tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["muted"], anchor="w", justify="left", wraplength=640)
        self.status_label.pack(fill="x", padx=14)
        self.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 28)) if event.widget is self else None)
        body = tk.Frame(self, bg=colors["panel"])
        body.pack(fill="both", expand=True, padx=14, pady=8)
        self.canvas = tk.Canvas(body, bg="#111e1d", highlightthickness=0, takefocus=True)
        self.canvas.pack(side="left", fill="both", expand=True)
        sidebar = tk.Frame(body, bg=colors["panel_soft"])
        sidebar.pack(side="right", fill="y", padx=(10, 0))
        side_canvas = tk.Canvas(sidebar, bg=colors["panel_soft"], width=220, highlightthickness=0)
        side_scroll = styled_scrollbar(sidebar, "vertical", side_canvas.yview, colors)
        side_scroll.pack(side="right", fill="y")
        side_canvas.pack(side="left", fill="both", expand=True)
        side_canvas.configure(yscrollcommand=side_scroll.set)
        panel = tk.Frame(side_canvas, bg=colors["panel_soft"])
        panel_window = side_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _event: side_canvas.configure(scrollregion=side_canvas.bbox("all")))
        side_canvas.bind("<Configure>", lambda event: side_canvas.itemconfigure(panel_window, width=event.width))
        self.selection_info = tk.StringVar(value="유닛 또는 건물을 선택하세요.")
        tk.Label(panel, textvariable=self.selection_info, bg=colors["panel_soft"], fg=colors["text"],
                 justify="left", wraplength=210, anchor="nw").pack(fill="x", padx=8, pady=10)
        for kind, spec in UNIT_SPECS.items():
            RoundedButton(panel, f"{spec['name']} 생산 ({spec['ore']}/{spec['wood']})",
                          lambda kind=kind: self.produce(kind), colors, compact=True).pack(fill="x", padx=8, pady=4)
        tk.Label(panel, text="생산 대기열 (최대 5개)", bg=colors["panel_soft"], fg=colors["muted"]).pack(pady=(14, 4))
        self.queue_list = tk.Listbox(panel, height=7, width=26, bg=colors["field"], fg=colors["text"],
                                    selectbackground=colors["accent"], exportselection=False, relief="flat")
        self.queue_list.pack(fill="x", padx=8)
        RoundedButton(panel, "선택 생산 취소 · 환불", self.cancel_production, colors, compact=True).pack(fill="x", padx=8, pady=8)
        RoundedButton(panel, "게임 저장", self.save_current, colors, compact=True).pack(fill="x", padx=8, pady=4)
        RoundedButton(panel, "게임 불러오기", self.load_current, colors, compact=True).pack(fill="x", padx=8, pady=4)
        self.statistics_text = tk.StringVar()
        tk.Label(panel, textvariable=self.statistics_text, bg=colors["panel_soft"], fg=colors["muted"],
                 justify="left", anchor="nw").pack(fill="x", padx=8, pady=10)
        tk.Label(self, text="좌클릭/드래그: 선택 · Shift: 추가 · 우클릭: 이동/채굴/적 공격 · WASD/방향키/가운데 드래그: 카메라 · 휠: 확대",
                 bg=colors["panel"], fg=colors["muted"], anchor="w").pack(fill="x", padx=14, pady=(0, 8))
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<ButtonPress-1>", self.select_start)
        self.canvas.bind("<B1-Motion>", self.select_drag)
        self.canvas.bind("<ButtonRelease-1>", self.select_end)
        self.canvas.bind("<Button-3>", self.move_order)
        self.canvas.bind("<Motion>", self.motion)
        self.canvas.bind("<ButtonPress-2>", self.pan_start)
        self.canvas.bind("<B2-Motion>", self.pan_move)
        self.canvas.bind("<ButtonRelease-2>", lambda _event: setattr(self, "pan_anchor", None))
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<KeyPress>", self.key)
        self.bind("<Destroy>", self.close, add="+")
        self.draw()
        self.tick_id = self.after(33, self.tick)

    def new_world(self) -> None:
        mode = next(key for key, label in GAME_MODES.items() if label == self.mode_choice.get())
        self.game = WarfareGame(self.world.seed + 1, mode=mode)
        self.world = self.game.world
        self.selection_start = self.selection_end = None
        self.build_kind = None
        self.camera.x = self.camera.y = 0
        self.draw()

    def toggle_pause(self) -> None:
        if self.game.result == "running":
            self.game.paused = not self.game.paused
        self.draw()

    def save_current(self) -> None:
        directory = APP_DIR / "micro_warfare"
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("게임 저장 실패", str(exc), parent=self)
            return
        selected = filedialog.asksaveasfilename(parent=self, title="Micro Warfare 저장", initialdir=directory,
                                               initialfile="battle.json", defaultextension=".json", filetypes=[("JSON 저장 파일", "*.json")])
        if not selected:
            return
        try:
            save_game(self.game, Path(selected))
        except (OSError, ValueError) as exc:
            messagebox.showerror("게임 저장 실패", str(exc), parent=self)
            return
        self.game.notice = "게임을 저장했습니다."
        self.draw()

    def load_current(self) -> None:
        selected = filedialog.askopenfilename(parent=self, title="Micro Warfare 불러오기", initialdir=APP_DIR / "micro_warfare",
                                              filetypes=[("JSON 저장 파일", "*.json")])
        if not selected:
            return
        try:
            loaded = load_game(Path(selected))
        except (OSError, ValueError) as exc:
            messagebox.showerror("게임 불러오기 실패", str(exc), parent=self)
            return
        self.game, self.world = loaded, loaded.world
        self.camera = Camera(self.world.pixel_width, self.world.pixel_height,
                             width=self.canvas.winfo_width(), height=self.canvas.winfo_height())
        self.build_kind = None
        self.selection_start = self.selection_end = None
        self.mode_choice.set(GAME_MODES[loaded.mode])
        self.last_tick = time.perf_counter()
        self.game.notice = "저장한 게임을 불러왔습니다."
        self.draw()

    def close(self, event: tk.Event) -> None:
        if event.widget is self and self.tick_id is not None:
            self.after_cancel(self.tick_id)
            self.tick_id = None

    def tick(self) -> None:
        now = time.perf_counter()
        if self.winfo_ismapped():
            self.game.update(min(0.1, now - self.last_tick))
            self.draw()
        self.last_tick = now
        self.tick_id = self.after(33, self.tick)

    def select_start(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        if self.build_kind is not None:
            x, y = self.camera.to_world(event.x, event.y)
            if self.game.issue_build(self.build_kind, int(x // TILE_SIZE), int(y // TILE_SIZE)):
                self.build_kind = None
            self.draw()
            return
        self.selection_start = self.selection_end = self.camera.to_world(event.x, event.y)

    def select_drag(self, event: tk.Event) -> None:
        if self.selection_start is not None:
            self.selection_end = self.camera.to_world(event.x, event.y)
            self.draw()

    def select_end(self, event: tk.Event) -> None:
        if self.selection_start is not None:
            self.game.select(*self.selection_start, *self.camera.to_world(event.x, event.y), additive=bool(event.state & 1))
            self.selection_start = self.selection_end = None
            self.draw()

    def move_order(self, event: tk.Event) -> None:
        if self.build_kind:
            self.build_kind = None
            self.game.notice = "건물 배치를 취소했습니다."
            self.draw()
            return
        x, y = self.camera.to_world(event.x, event.y)
        node = self.game.resource_at(x, y)
        enemy = self.game.enemy_at(x, y)
        if enemy:
            self.game.issue_attack(enemy)
        elif node:
            self.game.issue_harvest(node)
        else:
            self.game.issue_move(x, y)
        self.draw()

    def start_build(self, kind: str) -> None:
        self.build_kind = kind
        self.game.notice = f"{BUILDING_SPECS[kind]['name']} 배치: 좌클릭 확정 · 우클릭/Esc 취소 · 비용 광석/목재"
        self.canvas.focus_set()
        self.draw()

    def motion(self, event: tk.Event) -> None:
        x, y = self.camera.to_world(event.x, event.y)
        self.build_cursor = (int(x // TILE_SIZE), int(y // TILE_SIZE))

    def upgrade(self) -> None:
        self.game.upgrade()
        self.draw()

    def resume_build(self) -> None:
        self.game.resume_build()
        self.draw()

    def produce(self, kind: str) -> None:
        self.game.enqueue(kind)
        self.draw()

    def cancel_production(self) -> None:
        selection = self.queue_list.curselection()
        self.game.cancel_production(selection[0] if selection else -1)
        self.draw()

    def deposit(self) -> None:
        self.game.issue_deposit()
        self.draw()

    def resize(self, event: tk.Event) -> None:
        self.camera.resize(event.width, event.height)
        self.draw()

    def pan_start(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        self.pan_anchor = (event.x, event.y)

    def pan_move(self, event: tk.Event) -> None:
        if self.pan_anchor is not None:
            x, y = self.pan_anchor
            self.camera.pan(x - event.x, y - event.y)
            self.pan_anchor = (event.x, event.y)
            self.draw()

    def wheel(self, event: tk.Event) -> str:
        self.camera.zoom_at(1.15 if event.delta > 0 else 1 / 1.15, event.x, event.y)
        self.draw()
        return "break"

    def key(self, event: tk.Event) -> str | None:
        if event.keysym == "Escape":
            self.build_kind = None
            self.selection_start = self.selection_end = None
            self.draw()
            return "break"
        move = {"w": (0, -64), "Up": (0, -64), "s": (0, 64), "Down": (0, 64),
                "a": (-64, 0), "Left": (-64, 0), "d": (64, 0), "Right": (64, 0)}.get(event.keysym)
        if move:
            self.camera.pan(*move)
            self.draw()
            return "break"
        return None

    def draw(self) -> None:
        self.canvas.delete("all")
        xs, ys = self.camera.visible_tiles(self.world)
        size = TILE_SIZE * self.camera.zoom
        for y in ys:
            for x in xs:
                sx, sy = self.camera.to_screen(x * TILE_SIZE, y * TILE_SIZE)
                self.canvas.create_rectangle(sx, sy, sx + size + 1, sy + size + 1,
                                             fill=TERRAIN_COLORS[self.world.tiles[y][x]], outline="")
        for building in self.game.buildings:
            sx, sy = self.camera.to_screen(building.col * TILE_SIZE, building.row * TILE_SIZE)
            width = 2 * TILE_SIZE * self.camera.zoom
            spec = BUILDING_SPECS[building.kind]
            self.canvas.create_rectangle(sx + 2, sy + 2, sx + width - 2, sy + width - 2,
                                         fill=spec['color'] if building.complete else "#393c3e",
                                         outline="#f8e686" if building.id == self.game.selected_building else ("#91c6fa" if building.owner == 0 else "#ff8080"), width=2)
            label = f"{spec['name']} Lv.{building.level}"
            if not building.complete:
                label += f"\n건설 {min(100, building.progress / spec['time'] * 100):.0f}%"
            elif building.upgrade_remaining:
                label += f"\n강화 {building.upgrade_remaining:.1f}초"
            self.canvas.create_text(sx + width / 2, sy + width / 2, text=label, fill="white", font=("Segoe UI", 8))
            max_hp = 1000 if building.kind == "hq" else 500
            self.canvas.create_rectangle(sx, sy - 6, sx + width, sy - 2, fill="#262a2d", outline="")
            self.canvas.create_rectangle(sx, sy - 6, sx + width * building.hp / max_hp, sy - 2, fill="#8aefb5", outline="")
        for node in self.game.resources:
            sx, sy = self.camera.to_screen(node.x, node.y)
            radius = 14 * self.camera.zoom
            self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius,
                                    fill=("#b9bac6" if node.kind == "ore" else "#af884f") if node.amount else "#555d5b", outline="")
            self.canvas.create_text(sx, sy + radius + 9, text=f"{'광석' if node.kind == 'ore' else '목재'} {node.amount:.0f}", fill="#e3e8e2")
        for unit in self.game.units:
            sx, sy = self.camera.to_screen(unit.x, unit.y)
            radius = 8 * self.camera.zoom
            self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius,
                                    fill="#60bfff" if unit.owner == 0 else "#f36a73",
                                    outline="#f8e686" if unit.id in self.game.selected_ids else "#102c35", width=2)
            self.canvas.create_text(sx, sy, text="W" if unit.role == "worker" else "S", fill="#10202c", font=("Segoe UI", 8, "bold"))
            self.canvas.create_rectangle(sx - radius, sy + radius + 3, sx + radius, sy + radius + 6, fill="#151e24", outline="")
            self.canvas.create_rectangle(sx - radius, sy + radius + 3,
                                         sx - radius + 2 * radius * unit.hp / UNIT_SPECS[unit.role]['hp'], sy + radius + 6, fill="#8aefb5", outline="")
            if unit.cargo:
                self.canvas.create_text(sx, sy - radius - 8, text=f"{unit.cargo:.0f}/20", fill="#f8e686", font=("Segoe UI", 8))
            if unit.id in self.game.selected_ids and unit.target:
                tx, ty = self.camera.to_screen(*unit.target)
                self.canvas.create_line(sx, sy, tx, ty, fill="#f8e686", dash=(3, 4))
            if unit.id in self.game.selected_ids and unit.attack_target:
                target = self.game.resolve_target(unit.attack_target)
                if target:
                    tx, ty = self.camera.to_screen(*self.game.target_position(target))
                    self.canvas.create_line(sx, sy, tx, ty, fill="#ff8080", dash=(2, 4))
        if self.selection_start is not None and self.selection_end is not None:
            self.canvas.create_rectangle(*self.camera.to_screen(*self.selection_start),
                                         *self.camera.to_screen(*self.selection_end), outline="#f8e686", dash=(4, 2))
        if self.build_kind and self.build_cursor:
            col, row = self.build_cursor
            sx, sy = self.camera.to_screen(col * TILE_SIZE, row * TILE_SIZE)
            size = 2 * TILE_SIZE * self.camera.zoom
            self.canvas.create_rectangle(sx, sy, sx + size, sy + size,
                                         outline="#ff8080" if self.game.placement_error(self.build_kind, col, row) else "#8aefb5", width=3)
        self.status.set(f"광석 {self.game.stock['ore']:.0f} · 목재 {self.game.stock['wood']:.0f} · "
                        f"보관 {sum(self.game.stock.values()):.0f}/{self.game.storage_capacity:.0f} · "
                        f"인구(예약 포함) {self.game.population_reserved}/{self.game.population_limit} · {self.game.notice}")
        banner = ("일시정지" if self.game.paused else "") if self.game.result == "running" else {"victory": "승리", "defeat": "패배", "draw": "무승부"}[self.game.result]
        if banner:
            cx, cy = self.camera.width / 2, self.camera.height / 2
            self.canvas.create_rectangle(cx - 170, cy - 50, cx + 170, cy + 50, fill="#152831", outline="#f8e686")
            self.canvas.create_text(cx, cy - 10, text=banner, fill="#f8e686", font=("Segoe UI", 24, "bold"))
            self.canvas.create_text(cx, cy + 25, text=GAME_MODES[self.game.mode], fill="white")
        building = next((item for item in self.game.buildings if item.id == self.game.selected_building), None)
        entries = []
        if building:
            self.selection_info.set(f"{BUILDING_SPECS[building.kind]['name']} Lv.{building.level}\n"
                                    f"{'건설 완료' if building.complete else '건설 중'}\n업그레이드: 광석 {80 * building.level} / 목재 {60 * building.level}\n"
                                    "건물 강화 시 생산 속도가 증가합니다.")
            entries = [f"{i + 1}. {UNIT_SPECS[order.kind]['name']} · "
                       f"{order.progress / UNIT_SPECS[order.kind]['time']:.0%}" for i, order in enumerate(building.queue)]
        else:
            workers = sum(unit.role == "worker" for unit in self.game.selected_units)
            self.selection_info.set(f"선택 {len(self.game.selected_units)}기\n일꾼 {workers}기 · 보병 {len(self.game.selected_units) - workers}기\n\n"
                                    "일꾼: 자원 우클릭으로 자동 채굴\n건물: 클릭 후 생산/강화\n건설 비용은 광석/목재 순서입니다.")
        if tuple(entries) != self.queue_list.get(0, "end"):
            selected = self.queue_list.curselection()
            self.queue_list.delete(0, "end")
            for entry in entries:
                self.queue_list.insert("end", entry)
            if selected and selected[0] < len(entries):
                self.queue_list.selection_set(selected[0])
        stats = self.game.statistics[0]
        self.statistics_text.set(f"{GAME_MODES[self.game.mode]} · {self.game.elapsed:.0f}초\n"
                                 f"생산 {stats['units_produced']:.0f} / 전사 {stats['units_lost']:.0f}\n"
                                 f"처치 {stats['kills']:.0f} / 건물 파괴 {stats['buildings_destroyed']:.0f}\n"
                                 f"피해량 {stats['damage_dealt']:.0f}\n"
                                 f"채집 광석 {stats['gathered_ore']:.0f}\n채집 목재 {stats['gathered_wood']:.0f}")
        self.canvas.create_text(12, 12, anchor="nw", fill="#d4e9dc", font=("Segoe UI", 9),
                                text="초원 · 숲 · 물 · 바위")
