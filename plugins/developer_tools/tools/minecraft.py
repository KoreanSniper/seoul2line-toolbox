from __future__ import annotations

import json
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette


@dataclass(frozen=True)
class PermanentBlock:
    kind: str
    command: str
    conditional: bool = False


@dataclass(frozen=True)
class CommandPlan:
    description: str
    setup_once: tuple[str, ...]
    permanent: tuple[PermanentBlock, ...]


TEMPLATE_NAMES = {
    "timer": "⏱️ 반복 타이머",
    "periodic_command": "🔂 주기적 명령 실행",
    "countdown": "⌛ 카운트다운",
    "title_notice": "📣 타이틀 알림",
    "bossbar_timer": "🟪 보스바 타이머",
    "player_score": "👤 플레이어별 점수",
    "event_toggle": "🔌 이벤트 ON/OFF",
    "wave_system": "🌊 웨이브 시스템",
    "cooldown": "❄️ 쿨다운 시스템",
    "random": "🎲 랜덤 실행",
    "zone_enter": "📍 구역 진입 감지",
    "zone_enter_exit": "🚪 구역 입장/퇴장 감지",
    "first_join": "👤 플레이어 최초 접속 감지",
    "once_trigger": "🔁 1회 실행 트리거",
    "score_condition": "📊 스코어 조건 실행",
    "counter": "🔢 카운터",
    "game_flow": "🏁 게임 시작/종료 시스템",
    "team_assign": "👥 팀 자동 배정",
    "death_detect": "☠️ 사망 감지",
    "kill_goal": "🏆 킬 수 목표 달성",
    "health_condition": "❤️ 체력 조건 감지",
    "item_hold": "📦 특정 아이템 소지 감지",
    "item_use": "🗡️ 특정 아이템 사용 감지",
    "alive_count": "🧍 남은 플레이어 수 감지",
    "respawn_reset": "🔄 리스폰 후 초기화",
    "score_race_win": "🎯 목표 점수 먼저 달성 승리",
    "out_of_bounds": "🚫 영역 이탈 시 탈락",
    "time_limit_game": "🕒 제한시간 게임",
    "execute_at": "execute 위치 실행",
    "condition": "조건 검사 후 실행",
    "positioned_chain": "좌표 기준 체인 실행",
    "custom": "직접 입력",
}
TEMPLATE_KEYS_BY_LABEL = {label: key for key, label in TEMPLATE_NAMES.items()}
FIELD_ORDER = (
    "target",
    "action",
    "condition",
    "objective",
    "interval",
    "start_value",
    "end_action",
    "ready_action",
    "use_action",
    "weights",
    "range",
    "enter_action",
    "exit_action",
    "tag_name",
    "reusable",
    "score_range",
    "target_value",
    "done_action",
    "team_names",
    "start_action",
    "stop_action",
    "item_id",
)
VISIBLE_FIELDS = {
    "timer": ("interval", "condition", "action", "objective"),
    "periodic_command": ("interval", "action", "objective"),
    "countdown": ("start_value", "end_action", "objective"),
    "title_notice": ("target", "action", "interval"),
    "bossbar_timer": ("start_value", "end_action", "objective"),
    "player_score": ("target", "objective", "target_value", "done_action"),
    "event_toggle": ("condition", "start_action", "stop_action", "objective"),
    "wave_system": ("interval", "target_value", "action", "done_action", "objective"),
    "cooldown": ("target", "interval", "ready_action", "use_action", "objective"),
    "random": ("weights", "objective"),
    "zone_enter": ("target", "range", "action"),
    "zone_enter_exit": ("target", "range", "enter_action", "exit_action", "tag_name"),
    "first_join": ("target", "tag_name", "action"),
    "once_trigger": ("condition", "action", "tag_name", "reusable"),
    "score_condition": ("target", "objective", "score_range", "action"),
    "counter": ("target", "objective", "target_value", "done_action"),
    "game_flow": ("condition", "start_action", "stop_action", "objective"),
    "team_assign": ("target", "team_names"),
    "death_detect": ("target", "action", "objective"),
    "kill_goal": ("target", "objective", "target_value", "done_action"),
    "health_condition": ("target", "objective", "score_range", "action"),
    "item_hold": ("target", "item_id", "action"),
    "item_use": ("target", "item_id", "action", "objective"),
    "alive_count": ("objective", "target_value", "done_action"),
    "respawn_reset": ("target", "action", "objective"),
    "score_race_win": ("target", "objective", "target_value", "done_action"),
    "out_of_bounds": ("target", "range", "action"),
    "time_limit_game": ("start_value", "end_action", "objective"),
    "condition": ("condition", "action"),
    "positioned_chain": ("action",),
    "custom": (),
}
FIELD_LABELS = {
    "target": "대상",
    "action": "실행 커맨드",
    "condition": "조건",
    "objective": "목표 이름",
    "interval": "간격 tick",
    "start_value": "시작값",
    "end_action": "종료 커맨드",
    "ready_action": "준비 커맨드",
    "use_action": "사용 커맨드",
    "weights": "확률/가중치",
    "range": "범위",
    "enter_action": "입장 커맨드",
    "exit_action": "퇴장 커맨드",
    "tag_name": "태그명",
    "reusable": "재사용 여부",
    "score_range": "점수 범위",
    "target_value": "목표값",
    "done_action": "완료 커맨드",
    "team_names": "팀 목록",
    "start_action": "시작 커맨드",
    "stop_action": "종료 커맨드",
    "item_id": "아이템 ID",
}
SELECTOR_ARGUMENTS = (
    ("type", "엔티티 ID / 타입 태그", "minecraft:zombie"),
    ("name", "엔티티 이름", "Steve"),
    ("tag", "/tag 태그", "boss"),
    ("team", "scoreboard 팀", "red"),
    ("distance", "거리 범위", "..10"),
    ("x", "기준 X", "100"),
    ("y", "기준 Y", "64"),
    ("z", "기준 Z", "-200"),
    ("dx", "X 선택 영역", "10"),
    ("dy", "Y 선택 영역", "5"),
    ("dz", "Z 선택 영역", "10"),
    ("x_rotation", "상하 시선 각도", "-30..30"),
    ("y_rotation", "좌우 시선 각도", "-90..90"),
    ("scores", "스코어 조건", "{kills=5..10}"),
    ("level", "경험치 레벨", "10..30"),
    ("gamemode", "게임모드", "survival"),
    ("advancements", "발전과제 조건", "{story/smelt_iron=true}"),
    ("nbt", "엔티티 NBT", "{OnGround:true}"),
    ("predicate", "데이터팩 predicate", "mypack:test"),
    ("limit", "최대 선택 개수", "1"),
    ("sort", "선택 순서", "nearest"),
)
MINECRAFT_TOOL_NAMES = {
    "one_command": "One Command Generator",
    "selector": "Entity Selector Builder",
    "execute": "Execute Builder",
    "tellraw": "Tellraw Builder",
    "give": "Item / Give Generator",
    "summon": "Summon Generator",
    "playsound": "Playsound Finder",
    "scoreboard": "Scoreboard Generator",
    "formatter": "Command Formatter",
}


class MinecraftToolkit(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.shared_selector = tk.StringVar(value="@e[type=minecraft:zombie,distance=..10,sort=nearest,limit=1]")
        self.shared_command = tk.StringVar(value="say 실행됨")
        self.current_tool = "one_command"
        self.buttons: dict[str, RoundedButton] = {}
        self.content: tk.Frame | None = None
        self._build()
        self.show_tool("one_command")

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        nav = RoundedFrame(self, colors, colors["panel_soft"], colors["border"], radius=16, padding=12)
        nav.grid(row=0, column=0, sticky="ns", padx=(18, 10), pady=18)
        tk.Label(nav.body, text="Minecraft", font=("Segoe UI", 17, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(anchor="w")
        tk.Label(nav.body, text="연결형 커맨드 작업환경", font=("Segoe UI", 9), fg=colors["muted"], bg=colors["panel_soft"]).pack(anchor="w", pady=(2, 14))

        for key, label in MINECRAFT_TOOL_NAMES.items():
            button = RoundedButton(nav.body, label, lambda value=key: self.show_tool(value), colors, compact=True, radius=10)
            button.pack(fill="x", pady=4)
            self.buttons[key] = button

        self.content = tk.Frame(self, bg=colors["panel"])
        self.content.grid(row=0, column=1, sticky="nsew", padx=(0, 18), pady=18)

    def show_tool(self, key: str) -> None:
        if self.content is None:
            return
        self.current_tool = key
        for child in self.content.winfo_children():
            child.destroy()
        for name, button in self.buttons.items():
            button.set_active(name == key)

        builders = {
            "one_command": lambda: MinecraftCommandTool(self.content, self.app, self.shared_selector),
            "selector": lambda: SelectorBuilderTool(self.content, self.app, self.shared_selector, self.open_execute),
            "execute": lambda: ExecuteBuilderTool(self.content, self.app, self.shared_selector, self.shared_command),
            "tellraw": lambda: TellrawBuilderTool(self.content, self.app),
            "give": lambda: GiveBuilderTool(self.content, self.app, self.shared_selector),
            "summon": lambda: SummonBuilderTool(self.content, self.app),
            "playsound": lambda: PlaysoundFinderTool(self.content, self.app, self.shared_selector),
            "scoreboard": lambda: ScoreboardBuilderTool(self.content, self.app),
            "formatter": lambda: CommandFormatterTool(self.content, self.app),
        }
        widget = builders.get(key, builders["one_command"])()
        widget.pack(fill="both", expand=True)

    def open_execute(self) -> None:
        self.show_tool("execute")


class MinecraftCommandTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object, shared_selector: tk.StringVar | None = None) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.shared_selector = shared_selector
        self.template_label = tk.StringVar(value=TEMPLATE_NAMES["timer"])
        self.target = tk.StringVar(value=shared_selector.get() if shared_selector else "@p")
        self.selector_base = tk.StringVar(value="@e")
        self.selector_result = tk.StringVar(value=shared_selector.get() if shared_selector else "@e")
        self.selector_arg_values: dict[str, tk.StringVar] = {}
        self.action = tk.StringVar(value="say 실행됨")
        self.condition = tk.StringVar(value="block ~ ~-1 ~ minecraft:stone")
        self.objective = tk.StringVar(value="s2_timer")
        self.interval = tk.StringVar(value="20")
        self.start_value = tk.StringVar(value="60")
        self.end_action = tk.StringVar(value="say 종료")
        self.ready_action = tk.StringVar(value="say 준비 완료")
        self.use_action = tk.StringVar(value="say 스킬 사용")
        self.weights = tk.StringVar(value="1,1,1")
        self.range = tk.StringVar(value="5")
        self.enter_action = tk.StringVar(value="say 입장")
        self.exit_action = tk.StringVar(value="say 퇴장")
        self.tag_name = tk.StringVar(value="s2_tag")
        self.reusable = tk.StringVar(value="아니오")
        self.score_range = tk.StringVar(value="10..")
        self.target_value = tk.StringVar(value="10")
        self.done_action = tk.StringVar(value="say 완료")
        self.team_names = tk.StringVar(value="red,blue")
        self.start_action = tk.StringVar(value="say 게임 시작")
        self.stop_action = tk.StringVar(value="say 게임 종료")
        self.item_id = tk.StringVar(value="minecraft:diamond")
        self.origin_x = tk.StringVar(value="~")
        self.origin_y = tk.StringVar(value="~1")
        self.origin_z = tk.StringVar(value="~")
        self.custom_commands: tk.Text | None = None
        self.custom_label: tk.Label | None = None
        self.custom_frame: tk.Frame | None = None
        self.fields_host: tk.Frame | None = None
        self.field_rows: dict[str, tk.Frame] = {}
        self.field_labels: dict[str, tk.Label] = {}
        self.setup_preview: tk.Text | None = None
        self.block_list: tk.Frame | None = None
        self.output: tk.Text | None = None
        self.desc: tk.Label | None = None
        self.selector_group: tk.Frame | None = None
        self.selector_panel: RoundedFrame | None = None
        self.preset_buttons: dict[str, RoundedButton] = {}
        self._update_job: str | None = None
        self._build()
        self._watch_inputs()
        self._sync_visible_fields()
        self.generate()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        root = tk.PanedWindow(self, orient="horizontal", bg=colors["panel"], sashwidth=10, showhandle=False, bd=0)
        root.pack(fill="both", expand=True, padx=18, pady=18)

        left_panel = self._panel(root)
        right_panel = self._panel(root)
        root.add(left_panel, minsize=370)
        root.add(right_panel, minsize=500)
        left = left_panel.body
        right = right_panel.body

        tk.Label(left, text="프리셋", font=("Segoe UI", 14, "bold"), fg=colors["text"], bg=left.cget("bg")).pack(anchor="w")
        preset_shell = RoundedFrame(left, colors, colors["surface"], colors["border"], radius=12, padding=6)
        preset_shell.pack(fill="x", pady=(10, 16))
        preset_canvas = tk.Canvas(preset_shell.body, height=148, bg=colors["surface"], highlightthickness=0, bd=0)
        preset_scroll = styled_scrollbar(preset_shell.body, "vertical", preset_canvas.yview, colors)
        preset_body = tk.Frame(preset_canvas, bg=colors["surface"])
        preset_window = preset_canvas.create_window((0, 0), window=preset_body, anchor="nw")
        preset_body.bind("<Configure>", lambda _event: preset_canvas.configure(scrollregion=preset_canvas.bbox("all")))
        preset_canvas.bind("<Configure>", lambda event: preset_canvas.itemconfigure(preset_window, width=event.width))
        preset_canvas.configure(yscrollcommand=preset_scroll.set)
        preset_canvas.pack(side="left", fill="both", expand=True)
        preset_scroll.pack(side="right", fill="y")
        self._bind_wheel(preset_canvas)
        for key, label in TEMPLATE_NAMES.items():
            button = RoundedButton(
                preset_body,
                label,
                command=lambda value=label: self.template_label.set(value),
                colors=colors,
                compact=True,
                radius=10,
            )
            button.pack(fill="x", pady=4)
            self.preset_buttons[key] = button

        self.desc = tk.Label(left, text="", fg=colors["muted"], bg=left.cget("bg"), wraplength=350, justify="left")
        self.desc.pack(anchor="w", pady=(0, 18))

        self.fields_host = tk.Frame(left, bg=left.cget("bg"))
        self.fields_host.pack(fill="x")
        self._entry(self.fields_host, "대상", self.target, "target")
        self._entry(self.fields_host, "실행 커맨드", self.action, "action")
        self._entry(self.fields_host, "조건", self.condition, "condition")
        self._entry(self.fields_host, "타이머 목표", self.objective, "objective")
        self._entry(self.fields_host, "반복 tick", self.interval, "interval")
        self._entry(self.fields_host, "시작값", self.start_value, "start_value")
        self._entry(self.fields_host, "종료 커맨드", self.end_action, "end_action")
        self._entry(self.fields_host, "준비 커맨드", self.ready_action, "ready_action")
        self._entry(self.fields_host, "사용 커맨드", self.use_action, "use_action")
        self._entry(self.fields_host, "확률/가중치", self.weights, "weights")
        self._entry(self.fields_host, "범위", self.range, "range")
        self._entry(self.fields_host, "입장 커맨드", self.enter_action, "enter_action")
        self._entry(self.fields_host, "퇴장 커맨드", self.exit_action, "exit_action")
        self._entry(self.fields_host, "태그명", self.tag_name, "tag_name")
        self._entry(self.fields_host, "재사용 여부", self.reusable, "reusable")
        self._entry(self.fields_host, "점수 범위", self.score_range, "score_range")
        self._entry(self.fields_host, "목표값", self.target_value, "target_value")
        self._entry(self.fields_host, "완료 커맨드", self.done_action, "done_action")
        self._entry(self.fields_host, "팀 목록", self.team_names, "team_names")
        self._entry(self.fields_host, "시작 커맨드", self.start_action, "start_action")
        self._entry(self.fields_host, "종료 커맨드", self.stop_action, "stop_action")
        self._entry(self.fields_host, "아이템 ID", self.item_id, "item_id")
        self._build_selector_builder(left)

        coord_row = tk.Frame(left, bg=left.cget("bg"))
        coord_row.pack(fill="x", pady=(12, 10))
        tk.Label(coord_row, text="설치 좌표", width=12, anchor="w", fg=colors["muted"], bg=left.cget("bg")).pack(side="left")
        for label, variable in (("X", self.origin_x), ("Y", self.origin_y), ("Z", self.origin_z)):
            tk.Label(coord_row, text=label, fg=colors["muted"], bg=left.cget("bg")).pack(side="left", padx=(8, 4))
            self._entry_widget(coord_row, variable, width=7).pack(side="left", padx=(0, 4))

        self.custom_label = tk.Label(left, text="직접 입력 커맨드", font=("Segoe UI", 11, "bold"), fg=colors["text"], bg=left.cget("bg"))
        custom_panel = RoundedFrame(left, colors, colors["surface"], colors["border"], radius=12, padding=8)
        self.custom_frame = custom_panel
        self.custom_commands = tk.Text(custom_panel.body, height=8, bg=colors["surface"], fg=colors["text"], insertbackground=colors["text"], wrap="none", bd=0, padx=10, pady=10, font=("Consolas", 10))
        self.custom_commands.pack(fill="both", expand=True)
        self.custom_commands.insert("1.0", "say 첫 번째 커맨드\nsay 두 번째 커맨드")
        self.custom_commands.bind("<KeyRelease>", lambda _event: self.schedule_generate())

        tk.Label(right, text="설치 시 1회 실행 명령", font=("Segoe UI", 12, "bold"), fg=colors["text"], bg=right.cget("bg")).pack(anchor="w")
        setup_frame = RoundedFrame(right, colors, colors["surface"], colors["border"], radius=12, padding=8)
        setup_frame.pack(fill="x", pady=(8, 16))
        self.setup_preview = tk.Text(setup_frame.body, height=4, bg=colors["surface"], fg=colors["text"], wrap="word", bd=0, padx=10, pady=10, font=("Consolas", 10))
        self.setup_preview.pack(fill="x")

        tk.Label(right, text="영구적으로 설치되는 커맨드블록", font=("Segoe UI", 12, "bold"), fg=colors["text"], bg=right.cget("bg")).pack(anchor="w")
        table = RoundedFrame(right, colors, colors["surface"], colors["border"], radius=12, padding=0)
        table.pack(fill="x", pady=(8, 16))
        header = tk.Frame(table.body, bg=colors["panel"])
        header.pack(fill="x")
        for text, width in (("순서", 52), ("종류", 72), ("조건", 84)):
            tk.Label(header, text=text, width=width // 8, fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 1), pady=8)
        tk.Label(header, text="커맨드", anchor="w", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9, "bold")).pack(side="left", fill="x", expand=True, padx=10)
        self.block_list = tk.Frame(table.body, bg=colors["surface"])
        self.block_list.pack(fill="x")

        result_row = tk.Frame(right, bg=right.cget("bg"))
        result_row.pack(fill="x")
        tk.Label(result_row, text="원커맨드 결과", font=("Segoe UI", 12, "bold"), fg=colors["text"], bg=right.cget("bg")).pack(side="left")
        RoundedButton(result_row, "복사", self.copy_output, colors, accent=True, compact=True, radius=10).pack(side="right", fill="x")

        output_frame = RoundedFrame(right, colors, colors["surface"], colors["border"], radius=12, padding=8)
        output_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.output = tk.Text(output_frame.body, bg=colors["surface"], fg=colors["text"], insertbackground=colors["text"], wrap="none", height=8, bd=0, padx=10, pady=10, font=("Consolas", 10))
        self.output.pack(side="top", fill="both", expand=True)
        xscroll = styled_scrollbar(output_frame.body, "horizontal", self.output.xview, colors)
        xscroll.pack(side="bottom", fill="x")
        self.output.configure(xscrollcommand=xscroll.set)

        tk.Label(
            right,
            text="일반 커맨드블록에 붙여넣고 1회 실행하면 설치 시 명령이 먼저 실행되고, 지정 좌표 위로 반복/체인 커맨드블록이 순서대로 설치됩니다.",
            fg=colors["muted"],
            bg=right.cget("bg"),
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

    def _panel(self, parent: tk.Widget) -> RoundedFrame:
        colors = palette(self.app.dark_mode)
        panel = RoundedFrame(parent, colors, colors["panel_soft"], colors["border"], radius=16, padding=16)
        panel.pack_propagate(False)
        return panel

    def _bind_wheel(self, canvas: tk.Canvas) -> None:
        def on_wheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

    def _build_selector_builder(self, parent: tk.Widget) -> None:
        colors = palette(self.app.dark_mode)
        group = tk.Frame(parent, bg=parent.cget("bg"))
        group.pack(fill="x")
        self.selector_group = group
        tk.Label(group, text="대상 선택자 인자", font=("Segoe UI", 11, "bold"), fg=colors["text"], bg=group.cget("bg")).pack(anchor="w", pady=(16, 8))
        panel = RoundedFrame(group, colors, colors["surface"], colors["border"], radius=12, padding=8)
        panel.pack(fill="x")
        self.selector_panel = panel

        top = tk.Frame(panel.body, bg=colors["surface"])
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="기본 선택자", width=12, anchor="w", fg=colors["muted"], bg=colors["surface"]).pack(side="left")
        self._entry_widget(top, self.selector_base, width=8).pack(side="left")
        tk.Label(top, textvariable=self.selector_result, anchor="w", fg=colors["accent"], bg=colors["surface"], font=("Consolas", 10)).pack(side="left", fill="x", expand=True, padx=10)

        canvas = tk.Canvas(panel.body, height=178, bg=colors["surface"], highlightthickness=0, bd=0)
        scroll = styled_scrollbar(panel.body, "vertical", canvas.yview, colors)
        body = tk.Frame(canvas, bg=colors["surface"])
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._bind_wheel(canvas)

        for key, label, example in SELECTOR_ARGUMENTS:
            row = tk.Frame(body, bg=colors["surface"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=key, width=12, anchor="w", fg=colors["text"], bg=colors["surface"], font=("Consolas", 9, "bold")).pack(side="left")
            tk.Label(row, text=label, width=17, anchor="w", fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9)).pack(side="left")
            value = tk.StringVar()
            self.selector_arg_values[key] = value
            self._entry_widget(row, value, width=15).pack(side="left", fill="x", expand=True, padx=(8, 0))
            tk.Label(row, text=example, width=18, anchor="w", fg=colors["subtle"], bg=colors["surface"], font=("Consolas", 8)).pack(side="left", padx=(8, 0))

        actions = tk.Frame(panel.body, bg=colors["surface"])
        actions.pack(fill="x", pady=(8, 0))
        RoundedButton(actions, "대상에 적용", self.apply_selector_to_target, colors, accent=True, compact=True, radius=10).pack(side="left", fill="x")
        RoundedButton(actions, "비우기", self.clear_selector_args, colors, compact=True, radius=10).pack(side="left", padx=8, fill="x")

    def _entry(self, parent: tk.Widget, label: str, variable: tk.StringVar, key: str) -> None:
        colors = palette(self.app.dark_mode)
        bg = parent.cget("bg")
        row = tk.Frame(parent, bg=bg)
        label_widget = tk.Label(row, text=label, width=12, anchor="w", fg=colors["muted"], bg=bg)
        label_widget.pack(side="left")
        self._entry_widget(row, variable).pack(side="left", fill="x", expand=True)
        self.field_rows[key] = row
        self.field_labels[key] = label_widget

    def _entry_widget(self, parent: tk.Widget, variable: tk.StringVar, width: int | None = None) -> tk.Entry:
        colors = palette(self.app.dark_mode)
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width or 18,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
            font=("Segoe UI", 10),
        )

    def _flat_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        accent: bool = False,
        compact: bool = False,
        align: str = "w",
    ) -> tk.Button:
        colors = palette(self.app.dark_mode)
        return tk.Button(
            parent,
            text=text,
            command=command,
            anchor=align,
            relief="flat",
            bd=0,
            padx=10 if compact else 14,
            pady=7 if compact else 10,
            bg=colors["accent"] if accent else colors["surface_hover"],
            fg=colors["accent_text"] if accent else colors["text"],
            activebackground=colors["accent"] if accent else colors["accent_soft"],
            activeforeground=colors["accent_text"] if accent else colors["text"],
            font=("Segoe UI", 9, "bold"),
        )

    def _watch_inputs(self) -> None:
        self.template_label.trace_add("write", lambda *_args: self._on_template_changed())
        self.selector_base.trace_add("write", lambda *_args: self._on_selector_changed())
        for variable in (
            self.target,
            self.action,
            self.condition,
            self.objective,
            self.interval,
            self.start_value,
            self.end_action,
            self.ready_action,
            self.use_action,
            self.weights,
            self.range,
            self.enter_action,
            self.exit_action,
            self.tag_name,
            self.reusable,
            self.score_range,
            self.target_value,
            self.done_action,
            self.team_names,
            self.start_action,
            self.stop_action,
            self.item_id,
            self.origin_x,
            self.origin_y,
            self.origin_z,
        ):
            variable.trace_add("write", lambda *_args: self.schedule_generate())
        for variable in self.selector_arg_values.values():
            variable.trace_add("write", lambda *_args: self._on_selector_changed())

    def _on_selector_changed(self) -> None:
        selector = self.build_selector()
        self.selector_result.set(selector)
        if "target" in self._visible_field_keys():
            self.target.set(selector)
        self.schedule_generate()

    def _on_template_changed(self) -> None:
        self._sync_visible_fields()
        self.schedule_generate()

    def _sync_visible_fields(self) -> None:
        visible = self._visible_field_keys()
        labels = self._field_labels_for_template()
        for key in FIELD_ORDER:
            self.field_rows[key].pack_forget()
        for key in visible:
            self.field_labels[key].configure(text=labels.get(key, self.field_labels[key].cget("text")))
            self.field_rows[key].pack(fill="x", pady=7)
        key = self.current_template_key()
        uses_text_commands = key in {"custom", "random"}
        if self.custom_label and self.custom_frame:
            self.custom_label.pack_forget()
            self.custom_frame.pack_forget()
            if uses_text_commands:
                label = "랜덤 후보 커맨드" if key == "random" else "직접 입력 커맨드"
                self.custom_label.configure(text=label)
                self.custom_label.pack(anchor="w", pady=(18, 8))
                self.custom_frame.pack(fill="both", expand=True)
        if self.selector_group:
            self.selector_group.pack_forget()
            if "target" in visible:
                self.selector_group.pack(fill="x", after=self.fields_host)
        self._sync_preset_buttons()

    def _sync_preset_buttons(self) -> None:
        colors = palette(self.app.dark_mode)
        active_key = self.current_template_key()
        for key, button in self.preset_buttons.items():
            button.set_active(key == active_key)

    def _visible_field_keys(self) -> tuple[str, ...]:
        return VISIBLE_FIELDS.get(self.current_template_key(), ("target", "action"))

    def _field_labels_for_template(self) -> dict[str, str]:
        key = self.current_template_key()
        labels = FIELD_LABELS.copy()
        if key == "timer":
            labels.update({"condition": "실행 조건", "action": "반복 실행 커맨드", "objective": "타이머 목표"})
            return labels
        if key == "periodic_command":
            labels.update({"action": "주기 실행 커맨드", "objective": "주기 목표"})
            return labels
        if key == "countdown":
            labels.update({"start_value": "시작 초", "objective": "카운트다운 목표"})
            return labels
        if key == "title_notice":
            labels.update({"action": "타이틀 문구", "interval": "반복 tick"})
            return labels
        if key == "bossbar_timer":
            labels.update({"start_value": "시작 초", "objective": "보스바 목표"})
            return labels
        if key == "event_toggle":
            labels.update({"condition": "토글 조건", "objective": "이벤트 목표"})
            return labels
        if key == "wave_system":
            labels.update({"interval": "웨이브 간격", "target_value": "최대 웨이브", "action": "웨이브 커맨드"})
            return labels
        if key == "cooldown":
            labels.update({"interval": "쿨다운 tick", "objective": "쿨다운 목표"})
            return labels
        if key == "random":
            labels.update({"weights": "가중치", "objective": "랜덤 목표"})
            return labels
        if key in {"zone_enter", "zone_enter_exit", "out_of_bounds"}:
            labels.update({"range": "반경"})
            return labels
        if key == "once_trigger":
            labels.update({"tag_name": "잠금 태그", "reusable": "재사용 yes/no"})
            return labels
        if key == "team_assign":
            labels.update({"team_names": "팀 목록 CSV"})
            return labels
        if key == "item_use":
            labels.update({"objective": "사용 감지 목표"})
            return labels
        if key == "condition":
            labels.update({"condition": "검사 조건", "action": "조건 만족 시 실행"})
            return labels
        if key == "positioned_chain":
            labels.update({"action": "좌표에서 실행"})
            return labels
        return labels

    def current_template_key(self) -> str:
        return TEMPLATE_KEYS_BY_LABEL.get(self.template_label.get(), "execute_at")

    def build_selector(self) -> str:
        base = self.selector_base.get().strip() or "@e"
        args = []
        for key, _label, _example in SELECTOR_ARGUMENTS:
            value = self.selector_arg_values[key].get().strip()
            if not value:
                continue
            args.append(value if value.startswith(f"{key}=") else f"{key}={format_selector_value(key, value)}")
        if not args:
            return base
        if "[" in base and base.endswith("]"):
            before, existing = base[:-1].split("[", 1)
            merged = ",".join(part for part in (existing, ",".join(args)) if part)
            return f"{before}[{merged}]"
        return f"{base}[{','.join(args)}]"

    def apply_selector_to_target(self) -> None:
        selector = self.build_selector()
        self.target.set(selector)
        if self.shared_selector is not None:
            self.shared_selector.set(selector)

    def clear_selector_args(self) -> None:
        for value in self.selector_arg_values.values():
            value.set("")

    def schedule_generate(self) -> None:
        if self._update_job:
            self.after_cancel(self._update_job)
        self._update_job = self.after(80, self.generate)

    def generate(self) -> None:
        self._update_job = None
        plan = self._build_plan()
        one_command = build_falling_block_installer(
            plan,
            self.origin_x.get().strip() or "~",
            self.origin_y.get().strip() or "~1",
            self.origin_z.get().strip() or "~",
        )
        if self.desc:
            self.desc.configure(text=plan.description)
        if self.setup_preview:
            self.setup_preview.delete("1.0", "end")
            self.setup_preview.insert("1.0", preview_setup(plan.setup_once))
        if self.block_list:
            for child in self.block_list.winfo_children():
                child.destroy()
            for index, block in enumerate(plan.permanent, start=1):
                self._block_row(self.block_list, index, block)
        if self.output:
            self.output.delete("1.0", "end")
            self.output.insert("1.0", one_command)

    def _build_plan(self) -> CommandPlan:
        values = {
            "target": self.target.get().strip() or "@p",
            "action": normalize_command(self.action.get().strip() or "say 실행됨"),
            "condition": self.condition.get().strip() or "block ~ ~-1 ~ minecraft:stone",
            "objective": self.objective.get().strip() or "s2_timer",
            "interval": self.interval.get().strip() or "20",
            "start_value": self.start_value.get().strip() or "60",
            "end_action": normalize_command(self.end_action.get().strip() or "say 종료"),
            "ready_action": normalize_command(self.ready_action.get().strip() or "say 준비 완료"),
            "use_action": normalize_command(self.use_action.get().strip() or "say 스킬 사용"),
            "weights": self.weights.get().strip() or "1,1,1",
            "range": self.range.get().strip() or "5",
            "enter_action": normalize_command(self.enter_action.get().strip() or "say 입장"),
            "exit_action": normalize_command(self.exit_action.get().strip() or "say 퇴장"),
            "tag_name": self.tag_name.get().strip() or "s2_tag",
            "reusable": self.reusable.get().strip().lower(),
            "score_range": self.score_range.get().strip() or "10..",
            "target_value": self.target_value.get().strip() or "10",
            "done_action": normalize_command(self.done_action.get().strip() or "say 완료"),
            "team_names": self.team_names.get().strip() or "red,blue",
            "start_action": normalize_command(self.start_action.get().strip() or "say 게임 시작"),
            "stop_action": normalize_command(self.stop_action.get().strip() or "say 게임 종료"),
            "item_id": self.item_id.get().strip() or "minecraft:diamond",
            "x": self.origin_x.get().strip() or "~",
            "y": self.origin_y.get().strip() or "~1",
            "z": self.origin_z.get().strip() or "~",
        }
        key = self.current_template_key()
        if key == "timer":
            tick_command = f"execute if {values['condition']} run scoreboard players add #timer {values['objective']} 1"
            return CommandPlan(
                "초기화 명령은 설치 시 한 번만 실행하고, 타이머 증가/검사/리셋만 영구 커맨드블록으로 설치합니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard players set #timer {values['objective']} 0",
                ),
                (
                    PermanentBlock("반복", tick_command, False),
                    PermanentBlock("체인", f"execute if score #timer {values['objective']} matches {values['interval']}.. run {values['action']}", False),
                    PermanentBlock("체인", f"execute if score #timer {values['objective']} matches {values['interval']}.. run scoreboard players set #timer {values['objective']} 0", False),
                ),
            )
        if key == "periodic_command":
            return CommandPlan(
                "N틱마다 지정 커맨드를 실행하는 가장 기본적인 주기 실행 시스템입니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard players set #period {values['objective']} 0",
                ),
                (
                    PermanentBlock("반복", f"scoreboard players add #period {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #period {values['objective']} matches {values['interval']}.. run {values['action']}", False),
                    PermanentBlock("체인", f"execute if score #period {values['objective']} matches {values['interval']}.. run scoreboard players set #period {values['objective']} 0", False),
                ),
            )
        if key == "countdown":
            tick_objective = f"{values['objective']}_tick"
            return CommandPlan(
                "설치할 때 카운트다운 값을 한 번 세팅하고, 영구 블록은 초 단위 감소와 종료 커맨드만 담당합니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard objectives add {tick_objective} dummy",
                    f"scoreboard players set #countdown {values['objective']} {values['start_value']}",
                    f"scoreboard players set #tick {tick_objective} 0",
                ),
                (
                    PermanentBlock("반복", f"scoreboard players add #tick {tick_objective} 1", False),
                    PermanentBlock("체인", f"execute if score #tick {tick_objective} matches 20.. if score #countdown {values['objective']} matches 1.. run scoreboard players remove #countdown {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #tick {tick_objective} matches 20.. run scoreboard players set #tick {tick_objective} 0", False),
                    PermanentBlock("체인", f"title @a actionbar [{{\"text\":\"남은 시간 \"}},{{\"score\":{{\"name\":\"#countdown\",\"objective\":\"{values['objective']}\"}}}}]", False),
                    PermanentBlock("체인", f"execute if score #countdown {values['objective']} matches ..0 run {values['end_action']}", False),
                ),
            )
        if key == "title_notice":
            return CommandPlan(
                "지정 대상에게 일정 tick마다 title 알림을 띄웁니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard players set #title {values['objective']} 0",
                ),
                (
                    PermanentBlock("반복", f"scoreboard players add #title {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #title {values['objective']} matches {values['interval']}.. run title {values['target']} title {json.dumps({'text': values['action']}, ensure_ascii=False)}", False),
                    PermanentBlock("체인", f"execute if score #title {values['objective']} matches {values['interval']}.. run scoreboard players set #title {values['objective']} 0", False),
                ),
            )
        if key == "bossbar_timer":
            tick_objective = f"{values['objective']}_tick"
            bossbar_id = f"seoul2line:{values['objective']}"
            return CommandPlan(
                "보스바를 만들고 제한시간을 1초마다 줄이며 0초가 되면 종료 커맨드를 실행합니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard objectives add {tick_objective} dummy",
                    f"scoreboard players set #bossbar {values['objective']} {values['start_value']}",
                    f"scoreboard players set #tick {tick_objective} 0",
                    f"bossbar add {bossbar_id} \"Timer\"",
                    f"bossbar set {bossbar_id} players @a",
                    f"bossbar set {bossbar_id} max {values['start_value']}",
                ),
                (
                    PermanentBlock("반복", f"scoreboard players add #tick {tick_objective} 1", False),
                    PermanentBlock("체인", f"execute if score #tick {tick_objective} matches 20.. if score #bossbar {values['objective']} matches 1.. run scoreboard players remove #bossbar {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #tick {tick_objective} matches 20.. run scoreboard players set #tick {tick_objective} 0", False),
                    PermanentBlock("체인", f"execute store result bossbar {bossbar_id} value run scoreboard players get #bossbar {values['objective']}", False),
                    PermanentBlock("체인", f"execute if score #bossbar {values['objective']} matches ..0 run {values['end_action']}", False),
                ),
            )
        if key == "player_score":
            return CommandPlan(
                "플레이어별 점수를 만들고 목표값 이상이면 완료 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (
                    PermanentBlock("반복", f"execute as {values['target']} run scoreboard players add @s {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute as {values['target']} if score @s {values['objective']} matches {values['target_value']}.. run {values['done_action']}", False),
                ),
            )
        if key == "event_toggle":
            return CommandPlan(
                "조건이 만족되면 이벤트를 켜고, 만족되지 않으면 끄는 토글 점수 시스템입니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard players set #event {values['objective']} 0",
                ),
                (
                    PermanentBlock("반복", f"execute if {values['condition']} if score #event {values['objective']} matches 0 run {values['start_action']}", False),
                    PermanentBlock("체인", f"execute if {values['condition']} run scoreboard players set #event {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute unless {values['condition']} if score #event {values['objective']} matches 1 run {values['stop_action']}", False),
                    PermanentBlock("체인", f"execute unless {values['condition']} run scoreboard players set #event {values['objective']} 0", False),
                ),
            )
        if key == "wave_system":
            return CommandPlan(
                "일정 tick마다 웨이브 수를 올리고, 각 웨이브 커맨드와 완료 커맨드를 실행합니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard players set #wave {values['objective']} 0",
                    f"scoreboard players set #wave_tick {values['objective']} 0",
                ),
                (
                    PermanentBlock("반복", f"scoreboard players add #wave_tick {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #wave_tick {values['objective']} matches {values['interval']}.. run scoreboard players add #wave {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #wave_tick {values['objective']} matches {values['interval']}.. run scoreboard players set #wave_tick {values['objective']} 0", False),
                    PermanentBlock("체인", f"execute if score #wave {values['objective']} matches ..{values['target_value']} run {values['action']}", False),
                    PermanentBlock("체인", f"execute if score #wave {values['objective']} matches {values['target_value']}.. run {values['done_action']}", False),
                ),
            )
        if key == "cooldown":
            return CommandPlan(
                "플레이어별 쿨다운 점수를 설치 시 생성하고, 준비/사용 커맨드를 같은 체인에서 확인할 수 있게 설치합니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (
                    PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches 1.. run scoreboard players remove @s {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute as {values['target']} if score @s {values['objective']} matches 0 run {values['ready_action']}", False),
                    PermanentBlock("체인", f"execute as {values['target']} if score @s {values['objective']} matches 0 run {values['use_action']}", False),
                    PermanentBlock("체인", f"execute as {values['target']} if score @s {values['objective']} matches 0 run scoreboard players set @s {values['objective']} {values['interval']}", False),
                ),
            )
        if key == "random":
            lines = self._custom_lines(("say 첫 번째 랜덤", "say 두 번째 랜덤", "say 세 번째 랜덤"))
            weighted_lines = weighted_commands(lines, values["weights"])
            return CommandPlan(
                "후보 커맨드 중 하나를 뽑아 실행합니다. 가중치 입력은 후보별 선택 확률에 반영됩니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (
                    PermanentBlock("반복", f"execute store result score #pick {values['objective']} run random value 1..{len(weighted_lines)}", False),
                    *tuple(PermanentBlock("체인", f"execute if score #pick {values['objective']} matches {index} run {command}", False) for index, command in enumerate(weighted_lines, start=1)),
                ),
            )
        if key == "zone_enter":
            return CommandPlan(
                "설치 좌표를 중심으로 지정 반경 안에 대상이 들어오면 커맨드를 실행합니다.",
                (),
                (PermanentBlock("반복", f"execute as {values['target']} positioned {values['x']} {values['y']} {values['z']} if entity @s[distance=..{values['range']}] run {values['action']}", False),),
            )
        if key == "zone_enter_exit":
            return CommandPlan(
                "태그로 입장 상태를 기억해서 들어올 때와 나갈 때의 커맨드를 분리합니다.",
                (),
                (
                    PermanentBlock("반복", f"execute as {values['target']} positioned {values['x']} {values['y']} {values['z']} if entity @s[distance=..{values['range']},tag=!{values['tag_name']}] run {values['enter_action']}", False),
                    PermanentBlock("체인", f"execute as {values['target']} positioned {values['x']} {values['y']} {values['z']} if entity @s[distance=..{values['range']},tag=!{values['tag_name']}] run tag @s add {values['tag_name']}", False),
                    PermanentBlock("체인", f"execute as {values['target']} if entity @s[tag={values['tag_name']}] positioned {values['x']} {values['y']} {values['z']} unless entity @s[distance=..{values['range']}] run {values['exit_action']}", False),
                    PermanentBlock("체인", f"execute as {values['target']} if entity @s[tag={values['tag_name']}] positioned {values['x']} {values['y']} {values['z']} unless entity @s[distance=..{values['range']}] run tag @s remove {values['tag_name']}", False),
                ),
            )
        if key == "first_join":
            return CommandPlan(
                "태그가 없는 플레이어에게만 커맨드를 실행한 뒤 태그를 붙여 최초 1회만 작동합니다.",
                (),
                (
                    PermanentBlock("반복", f"execute as {values['target']} if entity @s[tag=!{values['tag_name']}] run {values['action']}", False),
                    PermanentBlock("체인", f"execute as {values['target']} if entity @s[tag=!{values['tag_name']}] run tag @s add {values['tag_name']}", False),
                ),
            )
        if key == "once_trigger":
            setup = () if is_truthy(values["reusable"]) else (f"scoreboard objectives add {values['objective']} dummy", f"scoreboard players set #once {values['objective']} 0")
            lock = () if is_truthy(values["reusable"]) else (PermanentBlock("체인", f"execute if {values['condition']} run scoreboard players set #once {values['objective']} 1", False),)
            guard = "" if is_truthy(values["reusable"]) else f"if score #once {values['objective']} matches 0 "
            return CommandPlan(
                "조건 만족 시 한 번 실행합니다. 재사용을 yes로 두면 잠금 없이 조건마다 다시 실행됩니다.",
                setup,
                (
                    PermanentBlock("반복", f"execute {guard}if {values['condition']} run {values['action']}", False),
                    *lock,
                ),
            )
        if key == "score_condition":
            return CommandPlan(
                "대상의 scoreboard 값이 지정 범위에 들어오면 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches {values['score_range']} run {values['action']}", False),),
            )
        if key == "counter":
            return CommandPlan(
                "대상 점수를 누적하고 목표값에 도달하면 완료 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (
                    PermanentBlock("반복", f"scoreboard players add {values['target']} {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score {values['target']} {values['objective']} matches {values['target_value']}.. run {values['done_action']}", False),
                ),
            )
        if key == "game_flow":
            return CommandPlan(
                "조건을 게임 종료 조건으로 사용하고, 실행 상태 점수로 시작/종료 흐름을 나눕니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard players set #running {values['objective']} 0",
                ),
                (
                    PermanentBlock("반복", f"execute if score #running {values['objective']} matches 0 run {values['start_action']}", False),
                    PermanentBlock("체인", f"execute if score #running {values['objective']} matches 0 run scoreboard players set #running {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #running {values['objective']} matches 1 if {values['condition']} run {values['stop_action']}", False),
                    PermanentBlock("체인", f"execute if score #running {values['objective']} matches 1 if {values['condition']} run scoreboard players set #running {values['objective']} 0", False),
                ),
            )
        if key == "team_assign":
            teams = split_csv(values["team_names"]) or ("red", "blue")
            setup = tuple(f"team add {team}" for team in teams)
            blocks = tuple(PermanentBlock("반복" if index == 0 else "체인", f"team join {team} @r[team=,limit=1,sort=random]", False) for index, team in enumerate(teams))
            return CommandPlan("팀을 설치 시 생성하고, 팀이 없는 플레이어를 무작위로 한 명씩 배정합니다.", setup, blocks)
        if key == "death_detect":
            return CommandPlan(
                "deathCount 목표를 만들고 사망 점수가 올라간 플레이어에게 커맨드를 실행한 뒤 값을 초기화합니다.",
                (f"scoreboard objectives add {values['objective']} deathCount",),
                (
                    PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches 1.. run {values['action']}", False),
                    PermanentBlock("체인", f"scoreboard players set {values['target']} {values['objective']} 0", False),
                ),
            )
        if key == "kill_goal":
            return CommandPlan(
                "playerKillCount 목표로 킬 수를 감지하고 목표값 이상이면 완료 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} playerKillCount",),
                (PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches {values['target_value']}.. run {values['done_action']}", False),),
            )
        if key == "health_condition":
            return CommandPlan(
                "health 목표를 설치하고 체력이 지정 범위에 들어온 대상에게 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} health",),
                (PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches {values['score_range']} run {values['action']}", False),),
            )
        if key == "item_hold":
            return CommandPlan(
                "대상이 메인 손에 특정 아이템을 들고 있으면 커맨드를 실행합니다.",
                (),
                (PermanentBlock("반복", f"execute as {values['target']} if items entity @s weapon.mainhand {values['item_id']} run {values['action']}", False),),
            )
        if key == "item_use":
            stat = f"minecraft.used:{values['item_id']}"
            return CommandPlan(
                "아이템 사용 통계를 scoreboard로 만들고 사용 감지 후 점수를 초기화합니다.",
                (f"scoreboard objectives add {values['objective']} {stat}",),
                (
                    PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches 1.. run {values['action']}", False),
                    PermanentBlock("체인", f"scoreboard players set {values['target']} {values['objective']} 0", False),
                ),
            )
        if key == "alive_count":
            return CommandPlan(
                "생존 플레이어 수를 점수에 저장하고 목표값 이하가 되면 완료 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (
                    PermanentBlock("반복", f"execute store result score #alive {values['objective']} if entity @a[gamemode=!spectator]", False),
                    PermanentBlock("체인", f"execute if score #alive {values['objective']} matches ..{values['target_value']} run {values['done_action']}", False),
                ),
            )
        if key == "respawn_reset":
            return CommandPlan(
                "리스폰 후 deathCount 값을 보고 초기화 커맨드를 실행한 뒤 감지 점수를 지웁니다.",
                (f"scoreboard objectives add {values['objective']} deathCount",),
                (
                    PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches 1.. run {values['action']}", False),
                    PermanentBlock("체인", f"scoreboard players set {values['target']} {values['objective']} 0", False),
                ),
            )
        if key == "score_race_win":
            return CommandPlan(
                "목표 점수에 먼저 도달한 플레이어를 감지해 승리 커맨드를 실행합니다.",
                (f"scoreboard objectives add {values['objective']} dummy",),
                (PermanentBlock("반복", f"execute as {values['target']} if score @s {values['objective']} matches {values['target_value']}.. run {values['done_action']}", False),),
            )
        if key == "out_of_bounds":
            return CommandPlan(
                "설치 좌표 반경 밖으로 나간 대상을 감지해 탈락 커맨드를 실행합니다.",
                (),
                (PermanentBlock("반복", f"execute as {values['target']} positioned {values['x']} {values['y']} {values['z']} unless entity @s[distance=..{values['range']}] run {values['action']}", False),),
            )
        if key == "time_limit_game":
            tick_objective = f"{values['objective']}_tick"
            return CommandPlan(
                "제한시간을 점수로 관리하고 0초가 되면 종료 커맨드를 실행합니다.",
                (
                    f"scoreboard objectives add {values['objective']} dummy",
                    f"scoreboard objectives add {tick_objective} dummy",
                    f"scoreboard players set #limit {values['objective']} {values['start_value']}",
                    f"scoreboard players set #tick {tick_objective} 0",
                ),
                (
                    PermanentBlock("반복", f"scoreboard players add #tick {tick_objective} 1", False),
                    PermanentBlock("체인", f"execute if score #tick {tick_objective} matches 20.. if score #limit {values['objective']} matches 1.. run scoreboard players remove #limit {values['objective']} 1", False),
                    PermanentBlock("체인", f"execute if score #tick {tick_objective} matches 20.. run scoreboard players set #tick {tick_objective} 0", False),
                    PermanentBlock("체인", f"execute if score #limit {values['objective']} matches ..0 run {values['end_action']}", False),
                ),
            )
        if key == "condition":
            return CommandPlan(
                "조건을 만족할 때만 지정 커맨드를 실행하는 반복 커맨드블록을 설치합니다.",
                (),
                (PermanentBlock("반복", f"execute if {values['condition']} run {values['action']}", False),),
            )
        if key == "positioned_chain":
            return CommandPlan(
                "설치 좌표를 기준으로 커맨드를 실행하는 체인을 설치합니다.",
                (),
                (PermanentBlock("반복", f"execute positioned {values['x']} {values['y']} {values['z']} run {values['action']}", False),),
            )
        if key == "custom":
            assert self.custom_commands is not None
            lines = self._custom_lines(("say seoul2line Toolbox",))
            blocks = tuple(PermanentBlock("반복" if i == 0 else "체인", command, False) for i, command in enumerate(lines or ["say seoul2line Toolbox"]))
            return CommandPlan("직접 입력한 커맨드를 순서대로 영구 커맨드블록으로 설치합니다.", (), blocks)
        return CommandPlan(
            "대상 엔티티 위치에서 지정 커맨드를 실행하는 반복 커맨드블록을 설치합니다.",
            (),
            (PermanentBlock("반복", f"execute as {values['target']} at @s run {values['action']}", False),),
        )

    def _custom_lines(self, fallback: tuple[str, ...]) -> tuple[str, ...]:
        if self.custom_commands is None:
            return fallback
        lines = tuple(normalize_command(line) for line in self.custom_commands.get("1.0", "end-1c").splitlines() if line.strip())
        return lines or fallback

    def copy_output(self) -> None:
        text = self.output.get("1.0", "end-1c") if self.output else ""
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("마인크래프트 커맨드", "원커맨드를 클립보드에 복사했습니다.")

    def _block_row(self, parent: tk.Widget, index: int, block: PermanentBlock) -> None:
        colors = palette(self.app.dark_mode)
        row = tk.Frame(parent, bg=colors["surface"])
        row.pack(fill="x")
        condition = "조건" if block.conditional else "무조건"
        for value, width in ((str(index), 52), (block.kind, 72), (condition, 84)):
            tk.Label(row, text=value, width=width // 8, fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 9)).pack(side="left", padx=(0, 1), pady=7)
        tk.Label(
            row,
            text=block.command,
            anchor="w",
            fg=colors["text"],
            bg=colors["surface"],
            font=("Consolas", 9),
        ).pack(side="left", fill="x", expand=True, padx=10)


class MiniBuilder(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object, title: str, subtitle: str) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.vars: dict[str, tk.StringVar] = {}
        self.output: tk.Text | None = None
        colors = palette(app.dark_mode)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        head = tk.Frame(self, bg=colors["panel"])
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text=title, font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(head, text=subtitle, font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).grid(row=1, column=0, sticky="w", pady=(2, 0))
        RoundedButton(head, "복사", self.copy_output, colors, accent=True, compact=True, radius=10).grid(row=0, column=1, rowspan=2, sticky="e")

        self.body_panel = RoundedFrame(self, colors, colors["panel_soft"], colors["border"], radius=16, padding=16)
        self.body_panel.grid(row=1, column=0, sticky="nsew")
        self.body_panel.body.columnconfigure(0, weight=1)

    def entry(self, label: str, key: str, default: str = "") -> tk.StringVar:
        colors = palette(self.app.dark_mode)
        row = tk.Frame(self.body_panel.body, bg=colors["panel_soft"])
        row.pack(fill="x", pady=7)
        tk.Label(row, text=label, width=16, anchor="w", fg=colors["muted"], bg=colors["panel_soft"]).pack(side="left")
        variable = tk.StringVar(value=default)
        variable.trace_add("write", lambda *_args: self.generate())
        tk.Entry(
            row,
            textvariable=variable,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
            font=("Segoe UI", 10),
        ).pack(side="left", fill="x", expand=True)
        self.vars[key] = variable
        return variable

    def output_box(self, height: int = 8) -> tk.Text:
        colors = palette(self.app.dark_mode)
        panel = RoundedFrame(self.body_panel.body, colors, colors["surface"], colors["border"], radius=12, padding=8)
        panel.pack(fill="both", expand=True, pady=(14, 0))
        self.output = tk.Text(panel.body, height=height, bg=colors["surface"], fg=colors["text"], insertbackground=colors["text"], wrap="none", bd=0, padx=10, pady=10, font=("Consolas", 10))
        self.output.pack(side="top", fill="both", expand=True)
        scroll = styled_scrollbar(panel.body, "horizontal", self.output.xview, colors)
        scroll.pack(side="bottom", fill="x")
        self.output.configure(xscrollcommand=scroll.set)
        return self.output

    def set_output(self, value: str) -> None:
        if self.output is None:
            return
        self.output.delete("1.0", "end")
        self.output.insert("1.0", value)

    def get(self, key: str, default: str = "") -> str:
        return self.vars[key].get().strip() or default

    def copy_output(self) -> None:
        text = self.output.get("1.0", "end-1c") if self.output else ""
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Minecraft Toolkit", "결과를 클립보드에 복사했습니다.")

    def generate(self) -> None:
        pass


class SelectorBuilderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object, shared_selector: tk.StringVar, open_execute) -> None:
        self.shared_selector = shared_selector
        self.open_execute = open_execute
        self.selector_arg_values: dict[str, tk.StringVar] = {}
        super().__init__(parent, app, "Entity Selector Builder", "@e[...] 대상 선택자를 만들고 다른 Builder로 보냅니다.")
        self.entry("기본 선택자", "base", "@e")
        self.result_label = tk.Label(self.body_panel.body, text="", anchor="w", fg=palette(app.dark_mode)["accent"], bg=palette(app.dark_mode)["panel_soft"], font=("Consolas", 10))
        self.result_label.pack(fill="x", pady=(4, 10))
        self._argument_grid()
        actions = tk.Frame(self.body_panel.body, bg=palette(app.dark_mode)["panel_soft"])
        actions.pack(fill="x", pady=(10, 0))
        RoundedButton(actions, "Execute Builder로 보내기", self.send_to_execute, palette(app.dark_mode), accent=True, compact=True, radius=10).pack(side="left", fill="x")
        RoundedButton(actions, "One Command용으로 저장", self.save_selector, palette(app.dark_mode), compact=True, radius=10).pack(side="left", padx=8, fill="x")
        self.output_box(5)
        self.generate()

    def _argument_grid(self) -> None:
        colors = palette(self.app.dark_mode)
        panel = RoundedFrame(self.body_panel.body, colors, colors["surface"], colors["border"], radius=12, padding=8)
        panel.pack(fill="both", expand=True)
        canvas = tk.Canvas(panel.body, height=260, bg=colors["surface"], highlightthickness=0, bd=0)
        scroll = styled_scrollbar(panel.body, "vertical", canvas.yview, colors)
        body = tk.Frame(canvas, bg=colors["surface"])
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for key, label, example in SELECTOR_ARGUMENTS:
            row = tk.Frame(body, bg=colors["surface"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=key, width=13, anchor="w", fg=colors["text"], bg=colors["surface"], font=("Consolas", 9, "bold")).pack(side="left")
            tk.Label(row, text=label, width=19, anchor="w", fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9)).pack(side="left")
            value = tk.StringVar()
            value.trace_add("write", lambda *_args: self.generate())
            self.selector_arg_values[key] = value
            tk.Entry(row, textvariable=value, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"], relief="flat", bd=0, highlightthickness=1, highlightbackground=colors["border"], highlightcolor=colors["accent"], font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True, padx=(8, 0))
            tk.Label(row, text=example, width=18, anchor="w", fg=colors["subtle"], bg=colors["surface"], font=("Consolas", 8)).pack(side="left", padx=(8, 0))

    def build_selector(self) -> str:
        base = self.get("base", "@e")
        args = []
        for key, _label, _example in SELECTOR_ARGUMENTS:
            value = self.selector_arg_values[key].get().strip()
            if value:
                args.append(value if value.startswith(f"{key}=") else f"{key}={format_selector_value(key, value)}")
        return base if not args else f"{base}[{','.join(args)}]"

    def save_selector(self) -> None:
        self.shared_selector.set(self.build_selector())

    def send_to_execute(self) -> None:
        self.save_selector()
        self.open_execute()

    def generate(self) -> None:
        selector = self.build_selector()
        if hasattr(self, "result_label"):
            self.result_label.configure(text=selector)
        self.set_output(selector)


class ExecuteBuilderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object, shared_selector: tk.StringVar, shared_command: tk.StringVar) -> None:
        self.shared_selector = shared_selector
        self.shared_command = shared_command
        super().__init__(parent, app, "Execute Builder", "Selector Builder에서 보낸 대상을 execute as/at 문장으로 이어붙입니다.")
        self.entry("대상", "target", shared_selector.get())
        self.entry("실행 위치", "at", "@s")
        self.entry("조건", "condition", "")
        self.entry("실행 커맨드", "command", shared_command.get())
        self.output_box()
        self.generate()

    def generate(self) -> None:
        target = self.get("target", self.shared_selector.get())
        self.shared_selector.set(target)
        command = normalize_command(self.get("command", "say 실행됨"))
        self.shared_command.set(command)
        condition = self.get("condition")
        prefix = f"execute as {target} at {self.get('at', '@s')}"
        if condition:
            prefix += f" if {condition}"
        self.set_output(f"{prefix} run {command}")


class TellrawBuilderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, app, "Tellraw Builder", "JSON 텍스트 커맨드를 빠르게 만듭니다.")
        self.entry("대상", "target", "@a")
        self.entry("텍스트", "text", "Hello World")
        self.entry("색상", "color", "aqua")
        self.output_box()
        self.generate()

    def generate(self) -> None:
        payload = {"text": self.get("text", "Hello World"), "color": self.get("color", "white")}
        self.set_output(f"tellraw {self.get('target', '@a')} {json.dumps(payload, ensure_ascii=False)}")


class GiveBuilderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object, shared_selector: tk.StringVar) -> None:
        self.shared_selector = shared_selector
        super().__init__(parent, app, "Item / Give Generator", "대상과 아이템 정보를 넣어 give 커맨드를 만듭니다.")
        self.entry("대상", "target", shared_selector.get())
        self.entry("아이템 ID", "item", "minecraft:diamond_sword")
        self.entry("개수", "count", "1")
        self.entry("컴포넌트/NBT", "nbt", "")
        self.output_box()
        self.generate()

    def generate(self) -> None:
        target = self.get("target", self.shared_selector.get())
        self.shared_selector.set(target)
        nbt = self.get("nbt")
        suffix = nbt if nbt.startswith("[") or nbt.startswith("{") else nbt
        self.set_output(f"give {target} {self.get('item', 'minecraft:stone')}{suffix} {self.get('count', '1')}")


class SummonBuilderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, app, "Summon Generator", "엔티티 소환 커맨드를 생성합니다.")
        self.entry("엔티티 ID", "entity", "minecraft:zombie")
        self.entry("X", "x", "~")
        self.entry("Y", "y", "~")
        self.entry("Z", "z", "~")
        self.entry("NBT", "nbt", "{CustomName:'\"S2\"'}")
        self.output_box()
        self.generate()

    def generate(self) -> None:
        self.set_output(f"summon {self.get('entity', 'minecraft:zombie')} {self.get('x', '~')} {self.get('y', '~')} {self.get('z', '~')} {self.get('nbt')}")


class PlaysoundFinderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object, shared_selector: tk.StringVar) -> None:
        self.shared_selector = shared_selector
        super().__init__(parent, app, "Playsound Finder", "자주 쓰는 사운드 ID를 playsound 커맨드로 만듭니다.")
        self.entry("사운드 ID", "sound", "minecraft:entity.player.levelup")
        self.entry("카테고리", "source", "master")
        self.entry("대상", "target", shared_selector.get())
        self.entry("볼륨", "volume", "1")
        self.entry("피치", "pitch", "1")
        self.output_box()
        self.generate()

    def generate(self) -> None:
        target = self.get("target", self.shared_selector.get())
        self.shared_selector.set(target)
        self.set_output(f"playsound {self.get('sound')} {self.get('source', 'master')} {target} ~ ~ ~ {self.get('volume', '1')} {self.get('pitch', '1')}")


class ScoreboardBuilderTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, app, "Scoreboard Generator", "objective 생성과 플레이어 점수 조작 커맨드를 만듭니다.")
        self.entry("목표 이름", "objective", "s2_score")
        self.entry("기준", "criteria", "dummy")
        self.entry("대상", "target", "@p")
        self.entry("값", "value", "1")
        self.output_box(7)
        self.generate()

    def generate(self) -> None:
        objective = self.get("objective", "s2_score")
        target = self.get("target", "@p")
        value = self.get("value", "1")
        self.set_output("\n".join((
            f"scoreboard objectives add {objective} {self.get('criteria', 'dummy')}",
            f"scoreboard players set {target} {objective} {value}",
            f"scoreboard players add {target} {objective} {value}",
            f"execute if score {target} {objective} matches {value}.. run say 조건 만족",
        )))


class CommandFormatterTool(MiniBuilder):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, app, "Command Formatter", "여러 줄 커맨드를 정리하고 슬래시를 제거합니다.")
        tk.Label(self.body_panel.body, text="입력", font=("Segoe UI", 11, "bold"), fg=palette(app.dark_mode)["text"], bg=palette(app.dark_mode)["panel_soft"]).pack(anchor="w")
        self.source = tk.Text(self.body_panel.body, height=9, bg=palette(app.dark_mode)["field"], fg=palette(app.dark_mode)["text"], insertbackground=palette(app.dark_mode)["text"], wrap="none", bd=0, padx=10, pady=10, font=("Consolas", 10))
        self.source.pack(fill="both", expand=True, pady=(8, 0))
        self.source.insert("1.0", "/execute as @a at @s run say hello\n/give @p minecraft:stone 1")
        self.source.bind("<KeyRelease>", lambda _event: self.generate())
        self.output_box(9)
        self.generate()

    def generate(self) -> None:
        lines = [normalize_command(line) for line in self.source.get("1.0", "end-1c").splitlines() if line.strip()]
        self.set_output("\n".join(lines))


def preview_setup(commands: tuple[str, ...]) -> str:
    if not commands:
        return "설치 시 1회 실행 명령 없음"
    return "\n".join(f"{i + 1}. {command}" for i, command in enumerate(commands))


def preview_blocks(blocks: tuple[PermanentBlock, ...]) -> str:
    lines = []
    for index, block in enumerate(blocks, start=1):
        condition = "조건" if block.conditional else "무조건"
        lines.append(f"{index}. {block.kind} | {condition} | {block.command}")
    return "\n".join(lines)


def normalize_command(command: str) -> str:
    command = command.strip()
    return command[1:] if command.startswith("/") else command


def format_selector_value(key: str, value: str) -> str:
    if key == "name" and " " in value and not (value.startswith('"') and value.endswith('"')):
        return json.dumps(value, ensure_ascii=False)
    return value


def split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def weighted_commands(commands: tuple[str, ...], weights: str) -> tuple[str, ...]:
    parsed = []
    for part in split_csv(weights):
        try:
            parsed.append(max(1, int(part)))
        except ValueError:
            parsed.append(1)
    if not parsed:
        parsed = [1] * len(commands)
    expanded = []
    for index, command in enumerate(commands):
        weight = parsed[index] if index < len(parsed) else 1
        expanded.extend([command] * min(weight, 20))
    return tuple(expanded or commands)


def is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "예", "네", "사용", "가능"}


def build_falling_block_installer(plan: CommandPlan, x: str, y: str, z: str) -> str:
    install_commands = [normalize_command(command) for command in plan.setup_once]
    for index, block in enumerate(plan.permanent):
        block_name = "minecraft:repeating_command_block" if block.kind == "반복" else "minecraft:chain_command_block"
        block_y = relative_y(y, index)
        conditional = "conditional=true," if block.conditional else ""
        install_commands.append(
            f"setblock {x} {block_y} {z} {block_name}[{conditional}facing=up]{{Command:{nbt_string(normalize_command(block.command))},auto:1b}} replace"
        )
    install_commands.append("kill @e[type=minecraft:command_block_minecart,distance=..2]")

    passengers = ",".join(
        "{id:\"minecraft:command_block_minecart\",Command:" + nbt_string(command) + "}"
        for command in install_commands
    )
    return (
        "summon minecraft:falling_block ~ ~1 ~ "
        "{BlockState:{Name:\"minecraft:redstone_block\"},Time:1,Passengers:["
        "{id:\"minecraft:falling_block\",BlockState:{Name:\"minecraft:activator_rail\"},Time:1,Passengers:["
        f"{passengers}"
        "]}]}"
    )


def relative_y(base: str, offset: int) -> str:
    base = base.strip()
    if base.startswith("~"):
        if base == "~":
            return f"~{offset}" if offset else "~"
        try:
            return f"~{float(base[1:] or 0) + offset:g}"
        except ValueError:
            return base
    try:
        return f"{float(base) + offset:g}"
    except ValueError:
        return base


def nbt_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return MinecraftToolkit(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("developer.minecraft_commands", "Minecraft Toolkit", "개발자", build, 0))

