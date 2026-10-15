from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from app.config import CONFIG_PATH
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette


FIELD_LABELS = {
    "valorant": "Valorant 실행 경로",
    "minecraft_launcher": "Minecraft 실행 경로",
    "steam": "Steam 실행 URI",
    "versions_path": "Minecraft 버전 폴더",
    "quick_delete": "삭제 단축키",
    "quick_move": "이동 단축키",
    "quick_new_file": "파일 생성 단축키",
    "quick_refresh": "새로고침 단축키",
}


def build(parent: tk.Widget, app: object) -> tk.Widget:
    colors = palette(app.dark_mode)
    frame = tk.Frame(parent, bg=colors["panel"])
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    canvas = tk.Canvas(frame, bg=colors["panel"], highlightthickness=0, bd=0)
    scroll = styled_scrollbar(frame, "vertical", canvas.yview, colors)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")

    body = tk.Frame(canvas, bg=colors["panel"])
    window_id = canvas.create_window(0, 0, window=body, anchor="nw")
    body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))

    content = tk.Frame(body, bg=colors["panel"])
    content.pack(fill="both", expand=True, padx=18, pady=18)
    content.columnconfigure(0, weight=1)
    content.columnconfigure(1, weight=1)

    theme_value = app.config_store.get("theme", default="dark")
    theme = tk.StringVar(value="어두운 모드" if theme_value == "dark" else "밝은 모드")
    theme_buttons: dict[str, RoundedButton] = {}
    hotkeys = app.config_store.get("hotkeys", default={})
    launcher_cfg = app.config_store.get("launchers", default={})
    minecraft_cfg = app.config_store.get("minecraft", default={})

    header = tk.Frame(content, bg=colors["panel"])
    header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
    header.columnconfigure(0, weight=1)
    tk.Label(header, text="설정", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
    tk.Label(header, text="실행 경로, 단축키, 테마를 한 곳에서 관리합니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).grid(row=1, column=0, sticky="w", pady=(3, 0))

    theme_card = card(content, colors, "테마", "전체 UI 색상 모드")
    theme_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
    theme_row = tk.Frame(theme_card.body, bg=colors["panel_soft"])
    theme_row.pack(fill="x", pady=(10, 0))

    def set_theme(label: str) -> None:
        theme.set(label)
        for name, button in theme_buttons.items():
            button.set_active(name == label)

    for label in ("어두운 모드", "밝은 모드"):
        button = RoundedButton(theme_row, label, lambda value=label: set_theme(value), colors, compact=True, radius=10, anchor="center")
        button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        theme_buttons[label] = button
    set_theme(theme.get())

    fields: dict[tuple[str, str], tk.StringVar] = {}
    groups = [
        ("실행 경로", [("launchers", "valorant"), ("launchers", "minecraft_launcher"), ("launchers", "steam")], launcher_cfg),
        ("마인크래프트", [("minecraft", "versions_path")], minecraft_cfg),
        ("단축키", [("hotkeys", key) for key in sorted(hotkeys)], hotkeys),
    ]
    config_card = card(content, colors, "경로와 단축키", "게임 실행, 마인크래프트 버전 폴더, 파일 작업 단축키")
    config_card.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(8, 0), pady=(0, 12))
    for title, keys, source in groups:
        section_title(config_card.body, colors, title)
        for group, key in keys:
            var = tk.StringVar(value=source.get(key, ""))
            labeled_entry(config_card.body, colors, FIELD_LABELS.get(key, key), var)
            fields[(group, key)] = var

    def save() -> None:
        updates = {("theme",): "dark" if theme.get() == "어두운 모드" else "light"}
        for (group, key), var in fields.items():
            updates[(group, key)] = var.get()
        app.config_store.set_many(updates)
        messagebox.showinfo("seoul2line Toolbox", f"설정을 저장했습니다.\n{CONFIG_PATH}")
        app.reload_theme()

    save_card = card(content, colors, "저장", "바꾼 설정을 즉시 config.json에 기록합니다.")
    save_card.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
    RoundedButton(save_card.body, "설정 저장", save, colors, accent=True, radius=10, anchor="center").pack(fill="x", pady=(10, 0))

    plugin_card = card(content, colors, "플러그인", "plugins 또는 user_data/plugins의 확장 기능")
    plugin_card.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 12))
    plugin_list = tk.Frame(plugin_card.body, bg=colors["panel_soft"])
    plugin_list.pack(fill="x", pady=(10, 0))
    plugins = getattr(app.plugin_manager, "plugins", [])
    if not plugins:
        tk.Label(plugin_list, text="발견된 플러그인이 없습니다.", fg=colors["muted"], bg=colors["panel_soft"]).pack(anchor="w")
    for plugin in plugins:
        status = plugin.status
        if plugin.error:
            status = f"{status}: {plugin.error}"
        line = tk.Frame(plugin_list, bg=colors["panel_soft"])
        line.pack(fill="x", pady=3)
        line.columnconfigure(1, weight=1)
        tk.Label(
            line,
            text=f"{plugin.name}  v{plugin.version}",
            fg=colors["text"],
            bg=colors["panel_soft"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(line, text=f"[{plugin.id}] {status}", fg=colors["muted"], bg=colors["panel_soft"], anchor="w").grid(row=0, column=1, sticky="w", padx=(12, 0))
        RoundedButton(
            line,
            "비활성화" if plugin.enabled else "활성화",
            lambda plugin=plugin: toggle_plugin(plugin.id, plugin.enabled),
            colors,
            compact=True,
            radius=8,
        ).grid(row=0, column=2, sticky="e", padx=(10, 0))

    def toggle_plugin(plugin_id: str, currently_enabled: bool) -> None:
        app.plugin_manager.set_enabled(plugin_id, not currently_enabled)
        app.reload_plugins()

    def install_plugin() -> None:
        selected = filedialog.askopenfilename(
            parent=frame, title="플러그인 ZIP 파일 선택", filetypes=[("ZIP 압축 파일", "*.zip")]
        )
        if not selected:
            return
        if not messagebox.askyesno(
            "플러그인 설치 안전 경고",
            f"선택한 파일: {Path(selected).name}\n\n"
            "플러그인은 앱과 같은 권한으로 Python 코드를 실행합니다.\n"
            "악성 코드는 파일을 읽거나 삭제하고 네트워크에 접근할 수 있습니다.\n\n"
            "신뢰할 수 있는 출처의 파일인지 확인하세요.\n"
            f"계속하면 압축을 풀어 다음 폴더에 설치하고 즉시 불러옵니다.\n{app.plugin_manager.roots[1]}\n\n"
            "이 플러그인을 설치하시겠습니까?",
            parent=frame, icon="warning", default=messagebox.NO,
        ):
            return
        try:
            plugin = app.plugin_manager.install_zip(Path(selected))
        except (OSError, ValueError) as exc:
            messagebox.showerror("플러그인 설치 실패", str(exc), parent=frame)
            return
        app.reload_plugins()
        loaded = next((item for item in app.plugin_manager.plugins if item.id == plugin.id), plugin)
        if loaded.error:
            messagebox.showwarning("플러그인 설치 완료 · 로드 실패", f"{plugin.name} 설치 완료\n{plugin.path}\n\n{loaded.error}")
        else:
            messagebox.showinfo("플러그인 설치 완료", f"{plugin.name} 설치 완료\n{plugin.path}\n\n상태: {loaded.status}")

    actions = tk.Frame(plugin_card.body, bg=colors["panel_soft"])
    actions.pack(fill="x", pady=(10, 0))
    RoundedButton(actions, "ZIP 파일 선택하기", install_plugin, colors, accent=True, compact=True, radius=10).pack(side="left", padx=(0, 8))
    RoundedButton(actions, "플러그인 다시 검색", app.reload_plugins, colors, accent=True, compact=True, radius=10).pack(side="left")
    tk.Label(
        actions,
        text="플러그인은 Python 코드를 실행하므로 신뢰할 수 있는 파일만 넣으세요.",
        fg=colors["muted"],
        bg=colors["panel_soft"],
        font=("Segoe UI", 8),
    ).pack(side="left", padx=(12, 0))

    tk.Label(
        content,
        text="ZIP 파일을 선택하고 안전 경고를 확인하면 플러그인이 자동으로 설치됩니다.",
        fg=colors["muted"],
        bg=colors["panel"],
        wraplength=760,
        justify="left",
    ).grid(row=4, column=0, columnspan=2, sticky="w")
    update_card = card(content, colors, "앱 업데이트", "GitHub 정식 릴리스의 설치본을 확인합니다.")
    update_card.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    automatic = tk.BooleanVar(value=app.config_store.get("updates", "automatic", default=True))
    tk.Checkbutton(update_card.body, text="시작 시 자동 업데이트 확인 (설치본)", variable=automatic,
                   command=lambda: app.config_store.set("updates", "automatic", value=automatic.get()),
                   bg=colors["panel_soft"], fg=colors["text"], selectcolor=colors["field"],
                   activebackground=colors["panel_soft"], activeforeground=colors["text"]).pack(anchor="w", pady=8)
    RoundedButton(update_card.body, "업데이트 확인", app.updater.check, colors, compact=True).pack(anchor="w")
    tk.Label(update_card.body, textvariable=app.updater.status, bg=colors["panel_soft"], fg=colors["muted"], wraplength=650, justify="left").pack(anchor="w", pady=8)
    return frame


def card(parent: tk.Widget, colors: dict[str, str], title: str, subtitle: str) -> RoundedFrame:
    panel = RoundedFrame(parent, colors, colors["panel_soft"], colors["border"], radius=18, padding=16)
    tk.Label(panel.body, text=title, font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(anchor="w")
    tk.Label(panel.body, text=subtitle, font=("Segoe UI", 9), fg=colors["muted"], bg=colors["panel_soft"]).pack(anchor="w", pady=(3, 0))
    return panel


def section_title(parent: tk.Widget, colors: dict[str, str], text: str) -> None:
    tk.Label(parent, text=text, font=("Segoe UI", 10, "bold"), fg=colors["accent"], bg=colors["panel_soft"]).pack(anchor="w", pady=(14, 6))


def labeled_entry(parent: tk.Widget, colors: dict[str, str], label: str, variable: tk.StringVar) -> None:
    row = tk.Frame(parent, bg=colors["panel_soft"])
    row.pack(fill="x", pady=5)
    row.columnconfigure(1, weight=1)
    tk.Label(row, text=label, fg=colors["muted"], bg=colors["panel_soft"], width=20, anchor="w", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=(0, 10))
    entry = tk.Entry(
        row,
        textvariable=variable,
        bg=colors["field"],
        fg=colors["text"],
        insertbackground=colors["accent"],
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=colors["border"],
        highlightcolor=colors["accent"],
        font=("Segoe UI", 9),
    )
    entry.grid(row=0, column=1, sticky="ew", ipady=8)


def register(registry) -> None:
    registry.register(ToolSpec("settings.preferences", "환경 설정", "설정", build, 0))
