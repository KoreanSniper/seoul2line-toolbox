from __future__ import annotations

import random
import tkinter as tk

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, rounded_rect
from app.palette import palette


MOODS = (
    ("물결", "#2dd4bf", "#164e63", "천천히 흐르는 선만 보기"),
    ("밤하늘", "#8b5cf6", "#1e1b4b", "점 몇 개 찍어두고 멍때리기"),
    ("회로", "#22c55e", "#143524", "작게 반짝이는 격자 느낌"),
    ("노을", "#f59e0b", "#3f1d16", "따뜻한 색 덩어리 보기"),
)

THOUGHTS = (
    "지금은 아무것도 안 해도 됨.",
    "잠깐 멈춘다고 시스템이 무너지진 않음.",
    "생각이 안 나면 안 나는 대로 두기.",
    "커서 깜빡이는 것도 일종의 콘텐츠임.",
    "할 일은 많고, 지금은 그냥 보기.",
    "이 화면은 생산성의 반대편 대기실.",
)


class ChillHub(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.mood_index = 0
        self.thought = tk.StringVar(value=random.choice(THOUGHTS))
        self.canvas: tk.Canvas | None = None
        self._build()
        self.draw_scene()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="미니게임", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="툴박스 안에 넣어둔 작은 게임과 샌드박스 모음입니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).grid(row=1, column=0, sticky="w", pady=(2, 0))
        RoundedButton(header, "다른 장면", self.next_mood, colors, accent=True, compact=True, radius=10).grid(row=0, column=1, rowspan=2, sticky="e")

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        scene_panel = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=18, padding=14)
        scene_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        scene_panel.body.rowconfigure(0, weight=1)
        scene_panel.body.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(scene_panel.body, bg=colors["surface"], highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self.draw_scene())
        self.canvas.bind("<Button-1>", lambda _event: self.next_thought())

        side = tk.Frame(body, bg=colors["panel"])
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)

        thought_panel = RoundedFrame(side, colors, colors["panel_soft"], colors["border"], radius=16, padding=16)
        thought_panel.pack(fill="x")
        tk.Label(thought_panel.body, text="미니게임 노트", font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(anchor="w")
        tk.Label(
            thought_panel.body,
            textvariable=self.thought,
            font=("Segoe UI", 11),
            fg=colors["muted"],
            bg=colors["panel_soft"],
            wraplength=300,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(12, 14))
        RoundedButton(thought_panel.body, "문장 바꾸기", self.next_thought, colors, compact=True, radius=10).pack(anchor="w", fill="x")

        ideas_panel = RoundedFrame(side, colors, colors["panel_soft"], colors["border"], radius=16, padding=16)
        ideas_panel.pack(fill="both", expand=True, pady=(14, 0))
        tk.Label(ideas_panel.body, text="현재 들어온 것들", font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(anchor="w")
        for title, desc in (
            ("항성계", "GPU 항성계 샌드박스"),
            ("TRSim", "철도 건설 물류 경영"),
            ("공장 자동화", "자원 생성기 → 컨베이어 → 판매"),
            ("한국 주식", "실제 종가 기반 매수/매도"),
            ("산 만들기", "3D 랜덤 산악 지형 생성"),
            ("물멍", "천천히 움직이는 파형"),
            ("별멍", "클릭할 때만 별 추가"),
        ):
            self._idea_row(ideas_panel.body, title, desc)

    def _idea_row(self, parent: tk.Widget, title: str, desc: str) -> None:
        colors = palette(self.app.dark_mode)
        row = tk.Frame(parent, bg=colors["panel_soft"])
        row.pack(fill="x", pady=(12, 0))
        tk.Label(row, text=title, font=("Segoe UI", 10, "bold"), fg=colors["text"], bg=colors["panel_soft"], width=9, anchor="w").pack(side="left")
        tk.Label(row, text=desc, font=("Segoe UI", 9), fg=colors["muted"], bg=colors["panel_soft"], anchor="w").pack(side="left", fill="x", expand=True)

    def next_mood(self) -> None:
        self.mood_index = (self.mood_index + 1) % len(MOODS)
        self.draw_scene()

    def next_thought(self) -> None:
        current = self.thought.get()
        choices = [item for item in THOUGHTS if item != current]
        self.thought.set(random.choice(choices or THOUGHTS))

    def draw_scene(self) -> None:
        if self.canvas is None:
            return
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 320)
        name, accent, deep, caption = MOODS[self.mood_index]
        rounded_rect(canvas, 8, 8, width - 8, height - 8, 22, fill=deep, outline=palette(self.app.dark_mode)["border"])
        canvas.create_text(28, 28, text=name, anchor="nw", fill=palette(self.app.dark_mode)["text"], font=("Segoe UI", 18, "bold"))
        canvas.create_text(28, 60, text=caption, anchor="nw", fill=palette(self.app.dark_mode)["muted"], font=("Segoe UI", 10))

        random.seed(self.mood_index)
        if name == "물결":
            for row in range(8):
                points = []
                y = 120 + row * 18
                for step in range(0, width - 80, 28):
                    points.extend((40 + step, y + ((step // 28 + row) % 3 - 1) * 8))
                canvas.create_line(*points, fill=accent, width=2, smooth=True)
        elif name == "밤하늘":
            for _ in range(58):
                x = random.randint(34, width - 36)
                y = random.randint(92, height - 36)
                size = random.choice((1, 1, 2, 2, 3))
                canvas.create_oval(x, y, x + size, y + size, fill=accent, outline="")
        elif name == "회로":
            for x in range(44, width - 30, 44):
                canvas.create_line(x, 100, x, height - 34, fill="#1f6f4a")
            for y in range(110, height - 30, 36):
                canvas.create_line(34, y, width - 34, y, fill="#1f6f4a")
            for _ in range(26):
                x = random.randrange(44, max(45, width - 44), 44)
                y = random.randrange(110, max(111, height - 44), 36)
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=accent, outline="")
        else:
            for i in range(7):
                x1 = 40 + i * 54
                y1 = 115 + i * 14
                canvas.create_oval(x1, y1, width - 48 - i * 32, height + 80 - i * 42, fill=["#7c2d12", "#b45309", "#f59e0b", "#fb7185"][i % 4], outline="")


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return ChillHub(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("minigame.hub", "미니게임 허브", "미니게임", build, 0))
