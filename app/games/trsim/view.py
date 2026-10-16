from __future__ import annotations

import json
import math
import random
import tempfile
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import messagebox
from app.config import APP_DIR


APP_TITLE = "TRSim - Rail Panic Dispatcher"
SAVE_PATH = APP_DIR / 'trsim' / 'dispatcher_save.json'
TICK_MS = 33

BG = "#08111f"
PANEL = "#101b2b"
PANEL_SOFT = "#17243a"
TEXT = "#e8f1ff"
MUTED = "#8ca2c4"
ACCENT = "#54a0ff"
DANGER = "#ff5c7a"
WARN = "#feca57"
GOOD = "#1dd1a1"
RAIL = "#4b6584"

GOODS = [
    ("승객", "#54a0ff", 80),
    ("우편", "#feca57", 110),
    ("식량", "#1dd1a1", 130),
    ("부품", "#a55eea", 150),
    ("응급", "#ff5c7a", 220),
]


@dataclass
class Node:
    name: str
    x: float
    y: float
    kind: str
    switch: int = 0


@dataclass
class Edge:
    a: int
    b: int


@dataclass
class Train:
    node: int
    target: int
    next_node: int
    progress: float
    speed: float
    cargo: str
    color: str
    reward: int
    deadline: int
    wait: int = 0
    paused: bool = False


@dataclass
class FloatingText:
    x: float
    y: float
    text: str
    color: str
    life: int = 70


class RailPanic(tk.Frame):
    def __init__(self, parent, app=None, *, save_path=None) -> None:
        super().__init__(parent, bg=BG)
        self.root = self
        self.save_path = Path(save_path) if save_path is not None else SAVE_PATH
        self._tick_job = None
        self._scale = 1.
        self._offset = (0., 0.)
        self.panel_visible = False
        self.rng = random.Random()
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.adj: dict[int, list[int]] = {}
        self.trains: list[Train] = []
        self.floating: list[FloatingText] = []
        self.day = 1
        self.score = 0
        self.money = 900
        self.reputation = 100
        self.wave = 1
        self.spawn_timer = 0
        self.paused = False
        self.selected_node: int | None = None
        self.message = "분기기를 바꿔 열차를 목적지까지 보내세요."
        self.event_log = ["역을 클릭하면 분기 방향이 바뀝니다.", "열차를 클릭하면 잠깐 정차/재출발합니다."]
        self.show_paths = True
        self._build_world()
        self._build_ui()
        self._bind_keys()
        self.bind('<Destroy>', self._destroyed, add='+')
        self._tick()

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self, bg=PANEL)
        toolbar.pack(fill="x", padx=8, pady=(8, 0))
        self.stats = tk.Label(toolbar, bg=PANEL, fg=TEXT, anchor="w",
                              font=("Malgun Gothic", 10, "bold"))
        self.stats.pack(fill="x", padx=8, pady=(6, 4))
        controls = tk.Frame(toolbar, bg=PANEL)
        controls.pack(fill="x", padx=4, pady=(0, 6))
        self.controls = []
        for text, command in (("새 판", self.new_game), ("저장", self.save_game),
                              ("불러오기", self.load_game), ("경로 P", self.toggle_paths),
                              ("일시정지 Space", self.toggle_pause), ("관제실", self.toggle_panel)):
            button = tk.Button(controls, text=text, command=command, bg=PANEL_SOFT, fg=TEXT,
                               activebackground=RAIL, activeforeground=TEXT, relief="flat",
                               font=("Malgun Gothic", 9), padx=6, pady=5, cursor="hand2")
            self.controls.append(button)
        def arrange(event):
            columns = 6 if event.width >= 680 else 3
            for column in range(6):
                controls.columnconfigure(column, weight=1 if column < columns else 0)
            for index, button in enumerate(self.controls):
                button.grid(row=index // columns, column=index % columns, sticky="ew", padx=3, pady=2)
        controls.bind("<Configure>", arrange)
        tk.Label(self, text="역 클릭: 분기 전환  ·  열차 클릭: 정차/재출발  ·  맵 클릭 후 1~9 / P / Space / Ctrl+S / Ctrl+L",
                 bg=BG, fg=MUTED, font=("Malgun Gothic", 9), anchor="w",
                 wraplength=470).pack(fill="x", padx=14, pady=6)
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=1,
                                highlightbackground=PANEL_SOFT, highlightcolor=ACCENT, takefocus=True)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        self.panel = tk.Frame(self.body, bg=PANEL, width=270)
        self.panel.grid_propagate(False)
        self.panel.pack_propagate(False)
        tk.Label(self.panel, text="관제실", bg=PANEL, fg=TEXT,
                 font=("Malgun Gothic", 16, "bold")).pack(anchor="w", padx=12, pady=12)
        details = tk.Canvas(self.panel, bg=PANEL, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(self.panel, orient="vertical", command=details.yview)
        scroll.pack(side="right", fill="y")
        details.pack(fill="both", expand=True)
        details.configure(yscrollcommand=scroll.set)
        info = tk.Frame(details, bg=PANEL)
        window = details.create_window(0, 0, window=info, anchor="nw")
        details.bind("<Configure>", lambda event: details.itemconfigure(window, width=event.width))
        info.bind("<Configure>", lambda _event: details.configure(scrollregion=details.bbox("all")))
        self.help, self.train_list, self.log, self.legend = [
            tk.Label(info, bg=PANEL, fg=color, justify="left", anchor="w",
                     wraplength=225, font=("Malgun Gothic", 9), padx=10, pady=8)
            for color in (TEXT, TEXT, WARN, MUTED)]
        for label in (self.help, self.train_list, self.log, self.legend):
            label.pack(fill="x")
            label.bind("<MouseWheel>", lambda event: details.yview_scroll(-int(event.delta / 120), "units"))
        self.body.bind("<Configure>", self._resize_panel)

    def _resize_panel(self, _event=None):
        self.panel.place_forget()
        if self.body.winfo_width() >= 850:
            self.panel.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        else:
            self.panel.grid_remove()
            if self.panel_visible:
                self.panel.place(relx=1, y=0, anchor="ne", width=270, relheight=1)
                self.panel.lift()

    def toggle_panel(self):
        self.panel_visible = not self.panel_visible
        self._resize_panel()

    def _bind_keys(self) -> None:
        actions = {"<space>": self.toggle_pause, "<p>": self.toggle_paths, "<P>": self.toggle_paths,
                   "<n>": self.new_game, "<N>": self.new_game,
                   "<Control-s>": self.save_game, "<Control-S>": self.save_game,
                   "<Control-l>": self.load_game, "<Control-L>": self.load_game}
        for sequence, action in actions.items():
            self.canvas.bind(sequence, lambda _event, action=action: self._shortcut(action))
        for index in range(1, 10):
            self.canvas.bind(str(index), lambda _event, index=index: self._shortcut(
                lambda: self.switch_node_by_number(index - 1)))

    @staticmethod
    def _shortcut(action):
        action()
        return "break"

    def _destroyed(self, event):
        if event.widget == self and self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None

    def _build_world(self) -> None:
        self.nodes = [
            Node("서울", 540, 120, "hub"), Node("인천", 390, 145, "city"), Node("수원", 500, 220, "city"),
            Node("춘천", 660, 95, "city"), Node("강릉", 820, 150, "port"), Node("대전", 560, 335, "hub"),
            Node("청주", 690, 280, "city"), Node("전주", 470, 450, "city"), Node("광주", 440, 570, "city"),
            Node("목포", 300, 620, "port"), Node("대구", 720, 440, "hub"), Node("포항", 890, 420, "port"),
            Node("울산", 820, 560, "city"), Node("부산", 700, 650, "port"),
        ]
        pairs = [
            (1, 0), (0, 2), (0, 3), (3, 4), (2, 5), (5, 6), (6, 4),
            (5, 7), (7, 8), (8, 9), (5, 10), (10, 11), (10, 12),
            (12, 13), (10, 13), (6, 10), (2, 7), (4, 11),
        ]
        self.edges = [Edge(a, b) for a, b in pairs]
        self._rebuild_adjacency()
        for index, node in enumerate(self.nodes):
            if self.adj[index]:
                node.switch = self.adj[index][0]

    def _rebuild_adjacency(self) -> None:
        self.adj = {index: [] for index in range(len(self.nodes))}
        for edge in self.edges:
            self.adj[edge.a].append(edge.b)
            self.adj[edge.b].append(edge.a)
        for key in self.adj:
            self.adj[key].sort(key=lambda other: math.atan2(self.nodes[other].y - self.nodes[key].y, self.nodes[other].x - self.nodes[key].x))

    def new_game(self) -> None:
        if self.trains and not messagebox.askyesno("새 판", "현재 관제 상황을 버리고 새 판을 시작할까요?"):
            return
        self.trains.clear()
        self.floating.clear()
        self.day = 1
        self.score = 0
        self.money = 900
        self.reputation = 100
        self.wave = 1
        self.spawn_timer = 0
        self.paused = False
        for index, node in enumerate(self.nodes):
            if self.adj[index]:
                node.switch = self.adj[index][0]
        self.event_log = ["새 관제 근무 시작.", "혼잡해지기 전에 분기 방향을 잡아두세요."]
        self.draw()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.add_event("관제 시계 정지." if self.paused else "운행 재개.")
        self.draw()

    def toggle_paths(self) -> None:
        self.show_paths = not self.show_paths
        self.add_event("추천 경로 표시 켬." if self.show_paths else "추천 경로 표시 끔.")
        self.draw()

    def add_event(self, text: str) -> None:
        self.event_log.insert(0, text)
        self.event_log = self.event_log[:6]

    def _tick(self) -> None:
        if not self.paused:
            self.day += 1
            self.spawn_timer -= 1
            if self.spawn_timer <= 0:
                self.spawn_train()
                base = max(42, 140 - self.wave * 9)
                self.spawn_timer = self.rng.randint(base, base + 70)
            if self.day % 650 == 0:
                self.wave += 1
                self.money += 180
                self.add_event(f"러시아워 {self.wave}단계. 보너스 예산 +180")
            self.move_trains()
            self.check_collisions()
            self.decay_floating()
        self.draw()
        self._tick_job = self.after(TICK_MS, self._tick)

    def spawn_train(self) -> None:
        if len(self.trains) >= 14:
            self.reputation = max(0, self.reputation - 2)
            self.add_event("선로가 포화 상태입니다. 평판 -2")
            return
        start = self.rng.randrange(len(self.nodes))
        target = self.rng.randrange(len(self.nodes))
        while target == start:
            target = self.rng.randrange(len(self.nodes))
        route = self.shortest_path(start, target)
        if len(route) < 2:
            return
        cargo, color, reward_base = self.rng.choice(GOODS)
        speed = self.rng.uniform(0.006, 0.0095) + self.wave * 0.00045
        deadline = self.day + int(max(280, len(route) * 145 - self.wave * 10))
        reward = reward_base + len(route) * 40 + self.wave * 15
        train = Train(start, target, route[1], 0.0, speed, cargo, color, reward, deadline)
        self.trains.append(train)
        self.add_event(f"{cargo} 열차 출발: {self.nodes[start].name} -> {self.nodes[target].name}")

    def move_trains(self) -> None:
        for train in list(self.trains):
            if train.paused:
                train.wait += 1
                if train.wait > 180:
                    train.paused = False
                    train.wait = 0
                continue
            if self.day > train.deadline:
                self.fail_train(train, "기한 초과")
                continue
            train.progress += train.speed
            if train.progress < 1.0:
                continue
            previous = train.node
            train.node = train.next_node
            train.progress = 0.0
            if train.node == train.target:
                self.deliver_train(train)
                continue
            next_node = self.nodes[train.node].switch
            if next_node not in self.adj[train.node]:
                route = self.shortest_path(train.node, train.target)
                next_node = route[1] if len(route) > 1 else train.target
            if next_node == previous and len(self.adj[train.node]) > 1:
                options = [item for item in self.adj[train.node] if item != previous]
                next_node = options[0]
            train.next_node = next_node

    def deliver_train(self, train: Train) -> None:
        bonus = max(0, train.deadline - self.day) // 5
        value = train.reward + bonus
        self.score += value
        self.money += value // 5
        self.reputation = min(100, self.reputation + 1)
        self.float_at(train, f"+{value}", GOOD)
        self.add_event(f"{train.cargo} 배송 완료: {self.nodes[train.target].name} +{value}")
        self.trains.remove(train)

    def fail_train(self, train: Train, reason: str) -> None:
        self.reputation = max(0, self.reputation - 8)
        self.money = max(0, self.money - 80)
        self.float_at(train, "-평판", DANGER)
        self.add_event(f"{reason}: {train.cargo} 열차 손실")
        if train in self.trains:
            self.trains.remove(train)

    def check_collisions(self) -> None:
        seen: dict[tuple[int, int, int], Train] = {}
        for train in list(self.trains):
            if train.paused:
                continue
            position = train.progress if train.node < train.next_node else 1 - train.progress
            key = tuple(sorted((train.node, train.next_node))) + (min(11, int(position * 12)),)
            other = seen.get(key)
            if other and not other.paused:
                self.fail_train(train, "충돌 사고")
                if other in self.trains:
                    self.fail_train(other, "충돌 사고")
                return
            seen[key] = train

    def float_at(self, train: Train, text: str, color: str) -> None:
        x, y = self.train_position(train)
        self.floating.append(FloatingText(x, y, text, color))

    def decay_floating(self) -> None:
        for item in self.floating:
            item.y -= 0.45
            item.life -= 1
        self.floating = [item for item in self.floating if item.life > 0]

    def switch_node_by_number(self, index: int) -> None:
        if 0 <= index < len(self.nodes):
            self.cycle_switch(index)

    def cycle_switch(self, index: int) -> None:
        options = self.adj[index]
        if not options:
            return
        node = self.nodes[index]
        if node.switch not in options:
            node.switch = options[0]
        else:
            node.switch = options[(options.index(node.switch) + 1) % len(options)]
        self.selected_node = index
        self.add_event(f"{node.name} 분기 -> {self.nodes[node.switch].name}")
        self.draw()

    def on_click(self, event) -> None:
        self.canvas.focus_set()
        x, y = self.world_position(event.x, event.y)
        hit_train = self.train_at(x, y)
        if hit_train:
            hit_train.paused = not hit_train.paused
            hit_train.wait = 0
            self.add_event(f"{hit_train.cargo} 열차 {'정차' if hit_train.paused else '재출발'}")
            return
        hit_node = self.node_at(x, y)
        if hit_node is not None:
            self.cycle_switch(hit_node)

    def on_motion(self, event) -> None:
        self.selected_node = self.node_at(*self.world_position(event.x, event.y))
        self.draw()

    def world_position(self, x, y):
        return ((x - self._offset[0]) / self._scale, (y - self._offset[1]) / self._scale)

    def node_at(self, x: float, y: float) -> int | None:
        for index, node in enumerate(self.nodes):
            if math.hypot(node.x - x, node.y - y) <= 18:
                return index
        return None

    def train_at(self, x: float, y: float) -> Train | None:
        for train in reversed(self.trains):
            tx, ty = self.train_position(train)
            if math.hypot(tx - x, ty - y) <= 14:
                return train
        return None

    def train_position(self, train: Train) -> tuple[float, float]:
        a = self.nodes[train.node]
        b = self.nodes[train.next_node]
        t = train.progress
        return a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t

    def shortest_path(self, start: int, target: int) -> list[int]:
        queue = [start]
        prev = {start: None}
        for current in queue:
            if current == target:
                break
            for nxt in self.adj[current]:
                if nxt not in prev:
                    prev[nxt] = current
                    queue.append(nxt)
        if target not in prev:
            return []
        path = []
        cur: int | None = target
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        return list(reversed(path))

    def draw(self) -> None:
        self.canvas.delete("all")
        self.draw_background()
        self.draw_edges()
        if self.show_paths:
            self.draw_train_paths()
        self.draw_nodes()
        self.draw_trains()
        self.draw_floating()
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self._scale = max(.1, min((width - 32) / 700, (height - 32) / 660))
        self._offset = ((width - 700 * self._scale) / 2 - 250 * self._scale,
                        (height - 660 * self._scale) / 2 - 50 * self._scale)
        self.canvas.scale('all', 0, 0, self._scale, self._scale)
        self.canvas.move('all', *self._offset)
        self.update_panel()

    def draw_background(self) -> None:
        w = max(self.canvas.winfo_width(), 900)
        h = max(self.canvas.winfo_height(), 620)
        self.canvas.create_rectangle(0, 0, w, h, fill=BG, outline="")
        for x in range(40, w, 80):
            self.canvas.create_line(x, 0, x, h, fill="#0d1b2d")
        for y in range(40, h, 80):
            self.canvas.create_line(0, y, w, y, fill="#0d1b2d")

    def draw_edges(self) -> None:
        for edge in self.edges:
            a = self.nodes[edge.a]
            b = self.nodes[edge.b]
            self.canvas.create_line(a.x, a.y, b.x, b.y, fill="#07101d", width=11, capstyle="round")
            self.canvas.create_line(a.x, a.y, b.x, b.y, fill=RAIL, width=6, capstyle="round")
            self.canvas.create_line(a.x, a.y, b.x, b.y, fill="#9fb3c8", width=1, dash=(8, 10))

    def draw_train_paths(self) -> None:
        for train in self.trains:
            path = self.shortest_path(train.node, train.target)
            if len(path) < 2:
                continue
            coords = []
            for index in path:
                node = self.nodes[index]
                coords.extend((node.x, node.y))
            self.canvas.create_line(*coords, fill=train.color, width=2, dash=(5, 7), stipple="gray50")

    def draw_nodes(self) -> None:
        for index, node in enumerate(self.nodes):
            selected = index == self.selected_node
            radius = 17 if node.kind == "hub" else 14
            fill = "#1e3799" if node.kind == "hub" else "#25364f"
            if node.kind == "port":
                fill = "#0f5f7a"
            self.canvas.create_oval(node.x - radius, node.y - radius, node.x + radius, node.y + radius, fill=fill, outline=ACCENT if selected else "#7f9cc0", width=3 if selected else 2)
            if self.adj[index]:
                target = self.nodes[node.switch]
                ang = math.atan2(target.y - node.y, target.x - node.x)
                self.canvas.create_line(node.x, node.y, node.x + math.cos(ang) * 30, node.y + math.sin(ang) * 30, fill=WARN, width=4, arrow="last")
            self.canvas.create_text(node.x, node.y + radius + 13, text=f"{index + 1}. {node.name}", fill=TEXT, font=("Malgun Gothic", 9, "bold"))

    def draw_trains(self) -> None:
        for train in self.trains:
            x, y = self.train_position(train)
            target = self.nodes[train.target]
            outline = "#ffffff" if not train.paused else WARN
            self.canvas.create_oval(x - 11, y - 11, x + 11, y + 11, fill=train.color, outline=outline, width=3)
            self.canvas.create_text(x, y - 22, text=self.nodes[train.target].name, fill=TEXT, font=("Malgun Gothic", 8, "bold"))
            left = max(0, train.deadline - self.day)
            bar = min(28, left / 10)
            self.canvas.create_rectangle(x - 14, y + 15, x + 14, y + 19, fill="#26384f", outline="")
            self.canvas.create_rectangle(x - 14, y + 15, x - 14 + bar, y + 19, fill=GOOD if left > 180 else WARN if left > 80 else DANGER, outline="")
            if train.paused:
                self.canvas.create_text(x, y + 31, text="STOP", fill=WARN, font=("Consolas", 8, "bold"))
            self.canvas.create_line(x, y, target.x, target.y, fill=train.color, width=1, dash=(2, 8))

    def draw_floating(self) -> None:
        for item in self.floating:
            self.canvas.create_text(item.x, item.y, text=item.text, fill=item.color, font=("Malgun Gothic", 12, "bold"))

    def update_panel(self) -> None:
        self.stats.configure(text=f"점수 {self.score} | 예산 {self.money} | 평판 {self.reputation} | 러시아워 {self.wave} | 열차 {len(self.trains)}" + (" | PAUSE" if self.paused else ""))
        self.help.configure(
            text=(
                "목표: 열차를 목적지 역까지 보내 점수와 예산을 얻기.\n\n"
                "역 클릭: 분기 방향 변경\n"
                "열차 클릭: 잠깐 정차/재출발\n"
                "1~9: 해당 번호 역 분기 변경\n"
                "P: 추천 경로 표시 토글\n"
                "Space: 일시정지"
            )
        )
        lines = []
        for train in sorted(self.trains, key=lambda item: item.deadline)[:9]:
            left = max(0, train.deadline - self.day)
            state = "정차" if train.paused else "운행"
            lines.append(f"{state} {train.cargo}: {self.nodes[train.node].name}->{self.nodes[train.target].name} / {left}")
        self.train_list.configure(text="운행 중\n" + ("\n".join(lines) if lines else "대기 중인 열차가 없습니다."))
        self.log.configure(text="\n".join(self.event_log[:5]))
        self.legend.configure(
            text=(
                "팁\n"
                "- 같은 선로 같은 구간에 열차가 겹치면 충돌합니다.\n"
                "- 분기 화살표는 다음에 열차가 나갈 방향입니다.\n"
                "- 급한 열차는 클릭해서 멈춘 뒤 분기를 정리하세요."
            )
        )

    def save_game(self) -> None:
        data = {
            "day": self.day,
            "score": self.score,
            "money": self.money,
            "reputation": self.reputation,
            "wave": self.wave,
            "spawn_timer": self.spawn_timer,
            "switches": [node.switch for node in self.nodes],
            "trains": [asdict(train) for train in self.trains],
            "event_log": self.event_log,
        }
        data['paused'] = self.paused
        data['show_paths'] = self.show_paths
        temporary = None
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.save_path.parent,
                                             prefix='trsim-', suffix='.tmp', delete=False) as output:
                temporary = Path(output.name)
                json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.replace(self.save_path)
        except (OSError, ValueError) as exc:
            self.add_event(f'저장 실패: {exc}')
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.add_event("관제 상황 저장 완료.")

    def load_game(self) -> None:
        if not self.save_path.exists():
            self.add_event("저장 파일이 없습니다.")
            return
        try:
            if self.save_path.stat().st_size > 1_000_000:
                raise ValueError('저장 파일이 너무 큽니다.')
            data = json.loads(self.save_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError('잘못된 저장 형식입니다.')
            for key, minimum, maximum in (('day', 1, 10**12), ('score', 0, 10**15),
                                           ('money', 0, 10**15), ('reputation', 0, 100),
                                           ('wave', 1, 10**8), ('spawn_timer', 0, 10**8)):
                value = data.get(key)
                if type(value) is not int or not minimum <= value <= maximum:
                    raise ValueError(f'잘못된 관제 값: {key}')
            switches = data.get('switches')
            if not isinstance(switches, list) or len(switches) != len(self.nodes):
                raise ValueError('분기 정보가 올바르지 않습니다.')
            if any(type(switch) is not int or switch not in self.adj[index]
                   for index, switch in enumerate(switches)):
                raise ValueError('연결되지 않은 분기가 있습니다.')
            records = data.get('trains')
            if not isinstance(records, list) or len(records) > 14:
                raise ValueError('열차 정보가 올바르지 않습니다.')
            trains = [Train(**record) for record in records]
            for train in trains:
                if (any(type(value) is not int or not 0 <= value < len(self.nodes)
                        for value in (train.node, train.next_node, train.target))
                    or train.next_node not in self.adj[train.node]):
                    raise ValueError('열차 경로가 올바르지 않습니다.')
                if any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (train.speed, train.progress)):
                    raise ValueError('열차 속도·위치가 올바르지 않습니다.')
                if not 0 < train.speed <= 1 or not 0 <= train.progress < 1:
                    raise ValueError('열차 속도·위치가 범위를 벗어났습니다.')
                if any(type(value) is not int or value < 0 for value in (train.reward, train.deadline, train.wait)):
                    raise ValueError('열차 보상·시간이 올바르지 않습니다.')
                if (type(train.paused) is not bool or not isinstance(train.cargo, str)
                    or len(train.cargo) > 40 or not isinstance(train.color, str)
                    or len(train.color) != 7 or not train.color.startswith('#')):
                    raise ValueError('열차 표시 정보가 올바르지 않습니다.')
                int(train.color[1:], 16)
            logs = data.get('event_log', [])
            if not isinstance(logs, list) or any(not isinstance(line, str) or len(line) > 500 for line in logs):
                raise ValueError('실행 기록이 올바르지 않습니다.')
            for key in ('paused', 'show_paths'):
                if key in data and type(data[key]) is not bool:
                    raise ValueError('화면 설정이 올바르지 않습니다.')
        except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as exc:
            self.add_event(f'불러오기 실패: {exc}')
            return
        for key in ('day', 'score', 'money', 'reputation', 'wave', 'spawn_timer'):
            setattr(self, key, data[key])
        for node, switch in zip(self.nodes, switches):
            node.switch = switch
        self.trains = trains
        self.event_log = logs[:6]
        self.paused = data.get('paused', False)
        self.show_paths = data.get('show_paths', True)
        self.floating.clear()
        self.selected_node = None
        self.add_event("관제 상황 불러오기 완료.")
        self.draw()
