from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

from app.config import DEFAULT_HOTKEYS, _is_valid_hotkey
from app.palette import THEME_LABELS, THEME_SWATCHES, palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar


FIELD_LABELS = {
    "valorant": "Valorant 실행 파일",
    "minecraft_launcher": "Minecraft 실행 파일",
    "steam": "Steam 실행 URI",
    "versions_path": "Minecraft 버전 폴더",
    "quick_delete": "파일 삭제",
    "quick_move": "파일 이동",
    "quick_new_file": "새 파일 만들기",
    "quick_refresh": "파일 목록 새로고침",
}


class SettingsPage(tk.Frame):
    def __init__(self, parent, app, description: str, editable: bool = True):
        self.app = app
        self.colors = palette(app.dark_mode)
        colors = self.colors
        super().__init__(parent, bg=colors["panel"])
        if not hasattr(app, "_settings_drafts"):
            app._settings_drafts = {}
        self.variables: dict[tuple[str, ...], tk.Variable] = {}
        self.validator: Callable[[], str | None] = lambda: None
        self.status = tk.StringVar(self, value="저장된 설정입니다.")
        if editable:
            footer = tk.Frame(self, bg=colors["panel"], padx=12, pady=10)
            footer.pack(side="bottom", fill="x")
            buttons = tk.Frame(footer, bg=colors["panel"])
            buttons.pack(fill="x")
            RoundedButton(buttons, "저장", self.save, colors, accent=True,
                          compact=True).pack(side="right", fill="x", expand=True)
            RoundedButton(buttons, "되돌리기", self.discard, colors,
                          compact=True).pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.status_label = tk.Label(footer, textvariable=self.status, bg=colors["panel"],
                                         fg=colors["muted"], anchor="w", justify="left",
                                         font=("Segoe UI", 9))
            self.status_label.pack(fill="x", pady=(7, 0))
            self.status_label.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(120, e.width)))
        shell = tk.Frame(self, bg=colors["panel"])
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, bg=colors["panel"], highlightthickness=0, bd=0)
        scroll = styled_scrollbar(shell, "vertical", self.canvas.yview, colors)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.content = tk.Frame(self.canvas, bg=colors["panel"])
        window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        if description:
            self.note(self.content, description, panel=False)

    def note(self, parent, text, panel=True):
        label = tk.Label(parent, text=text, bg=self.colors["panel_soft" if panel else "panel"],
                         fg=self.colors["muted"], justify="left", anchor="w", font=("Segoe UI", 9))
        label.pack(fill="x", padx=12 if not panel else 0, pady=(8, 10))
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(100, e.width)))
        return label

    def card(self, title, subtitle):
        colors = self.colors
        panel = RoundedFrame(self.content, colors, colors["panel_soft"], colors["border"], radius=10, padding=14)
        panel.pack(fill="x", padx=12, pady=(0, 12))
        heading = tk.Label(panel.body, text=title, font=("Segoe UI", 12, "bold"),
                           fg=colors["text"], bg=colors["panel_soft"], anchor="w", justify="left")
        heading.pack(fill="x")
        heading.bind("<Configure>", lambda e: heading.configure(wraplength=max(100, e.width)))
        if subtitle:
            self.note(panel.body, subtitle)
        return panel.body

    def variable(self, key, boolean=False):
        value = self.app._settings_drafts.get(key, self.stored(key))
        variable = (tk.BooleanVar if boolean else tk.StringVar)(self, value=value)
        self.variables[key] = variable
        variable.trace_add("write", lambda *_args: self.changed())
        self.changed()
        return variable

    def stored(self, key):
        default = True if key == ("updates", "automatic") else None
        return self.app.config_store.get(*key, default=default)

    def changed(self):
        count = 0
        for key, variable in self.variables.items():
            value = variable.get()
            if value == self.stored(key):
                self.app._settings_drafts.pop(key, None)
            else:
                self.app._settings_drafts[key] = value
                count += 1
        self.status.set(f"저장하지 않은 변경 {count}개" if count else "저장됨")
        if hasattr(self, "status_label"):
            self.status_label.configure(fg=self.colors["muted"])

    def save(self):
        if all(variable.get() == self.stored(key) for key, variable in self.variables.items()):
            self.status.set("저장할 변경사항이 없습니다.")
            return
        error = self.validator()
        if error:
            self.status.set(error)
            self.status_label.configure(fg=self.colors["danger"])
            return
        updates = {key: variable.get() for key, variable in self.variables.items()}
        previous_theme = self.app.config_store.get("theme")
        try:
            self.app.config_store.set_many(updates)
        except (OSError, ValueError) as exc:
            self.status.set(f"저장하지 못했습니다: {exc}")
            self.status_label.configure(fg=self.colors["danger"])
            return
        for key, variable in self.variables.items():
            variable.set(self.stored(key))
            self.app._settings_drafts.pop(key, None)
        self.status.set("변경사항을 저장했습니다.")
        if previous_theme != self.app.config_store.get("theme"):
            self.app.reload_theme()

    def discard(self):
        for key, variable in self.variables.items():
            variable.set(self.stored(key))
            self.app._settings_drafts.pop(key, None)
        self.changed()
        self.status.set("저장된 값으로 되돌렸습니다.")

    def entry(self, parent, label, variable, picker=None):
        colors = self.colors
        row = tk.Frame(parent, bg=colors["panel_soft"])
        row.pack(fill="x", pady=(4, 10))
        tk.Label(row, text=label, bg=colors["panel_soft"], fg=colors["text"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 5))
        line = tk.Frame(row, bg=colors["panel_soft"])
        line.pack(fill="x")
        if picker:
            button = RoundedButton(line, "찾기", lambda: self.pick(variable, picker), colors, compact=True)
            button.configure(width=65)
            button.pack(side="right", padx=(8, 0))
        entry = tk.Entry(line, textvariable=variable, bg=colors["field"], fg=colors["text"],
                         insertbackground=colors["accent"], relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=colors["border"],
                         highlightcolor=colors["accent"], font=("Consolas", 10))
        entry.pack(fill="x", expand=True, ipady=7)
        return entry

    def pick(self, variable, kind):
        if kind == "directory":
            selected = filedialog.askdirectory(parent=self, title="폴더 선택")
        else:
            selected = filedialog.askopenfilename(parent=self, title="실행 파일 선택",
                                                  filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*.*")])
        if selected:
            variable.set(selected)

    def finish(self):
        def scroll(event):
            if self.canvas.winfo_height() < self.content.winfo_reqheight():
                self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
        def bind(widget):
            widget.bind("<MouseWheel>", scroll, add="+")
            for child in widget.winfo_children():
                bind(child)
        bind(self)
        return self


def build(parent, app):
    page = SettingsPage(parent, app, "")
    body = page.card("테마", "")
    theme = page.variable(("theme",))
    buttons = {}
    for name, label in THEME_LABELS.items():
        button = RoundedButton(body, label, lambda name=name: theme.set(name), page.colors, compact=True)
        button.pack(fill="x", pady=3)
        buttons[name] = button
    swatches = tk.Canvas(body, height=24, bg=page.colors["panel_soft"], highlightthickness=0)
    swatches.pack(fill="x", pady=(12, 0))
    def refresh(*_args):
        for name, button in buttons.items():
            button.set_active(name == theme.get())
        swatches.delete("all")
        width = swatches.winfo_width()
        for index, color in enumerate(THEME_SWATCHES[theme.get()]):
            swatches.create_rectangle(index * width / 10, 0, (index + 1) * width / 10, 24, fill=color, outline="")
    theme.trace_add("write", refresh)
    swatches.bind("<Configure>", refresh)
    refresh()
    return page.finish()


def build_paths(parent, app):
    page = SettingsPage(parent, app, "실행 파일과 Minecraft 폴더를 지정합니다. ‘찾기’로 직접 선택할 수 있습니다.")
    body = page.card("게임 실행", "실행 파일은 비워 두어도 됩니다. Steam은 steam:// 주소를 사용합니다.")
    for key in ("valorant", "minecraft_launcher", "steam"):
        variable = page.variable(("launchers", key))
        page.entry(body, FIELD_LABELS[key], variable, picker="file" if key != "steam" else None)
    body = page.card("Minecraft", "상대 경로 또는 버전 파일이 들어 있는 폴더를 선택하세요.")
    page.entry(body, FIELD_LABELS["versions_path"], page.variable(("minecraft", "versions_path")), picker="directory")
    def validate():
        try:
            for key in ("valorant", "minecraft_launcher"):
                value = page.variables[("launchers", key)].get()
                if value and not Path(value).expanduser().is_file():
                    return f"{FIELD_LABELS[key]}: 존재하는 파일을 선택하세요."
            steam = page.variables[("launchers", "steam")].get().strip()
            if steam and not steam.startswith("steam://"):
                return "Steam 주소는 steam://로 시작해야 합니다."
            value = page.variables[("minecraft", "versions_path")].get().strip()
            if not value or (Path(value).expanduser().is_absolute() and not Path(value).expanduser().is_dir()):
                return "Minecraft 버전 폴더를 확인하세요."
        except (OSError, ValueError):
            return "경로를 확인하세요. 사용할 수 없는 경로가 포함되어 있습니다."
        return None
    page.validator = validate
    return page.finish()


def build_hotkeys(parent, app):
    page = SettingsPage(parent, app, "파일 작업 단축키를 수정합니다. 잘못된 형식이나 중복은 저장 전에 안내합니다.")
    body = page.card("파일 작업", "예: <Control-n>, <Control-Shift-m>, <F5>, <Delete>")
    for key in DEFAULT_HOTKEYS:
        page.entry(body, FIELD_LABELS[key], page.variable(("hotkeys", key)))
    page.note(body, "전체 도구 검색 Ctrl+K와 영역 캡쳐 PrintScreen은 별도 공통 단축키입니다.")
    def validate():
        seen = set()
        for key, variable in page.variables.items():
            value = variable.get()
            if not _is_valid_hotkey(value):
                return f"{FIELD_LABELS[key[-1]]}: <Control-n>과 같은 형식으로 입력하세요."
            if value.lower() == "<control-k>":
                return "Ctrl+K는 전체 도구 검색에 사용됩니다. 다른 키를 선택하세요."
            normalized = value.lower()
            if normalized in seen:
                return "같은 단축키가 중복되었습니다. 서로 다른 키를 지정하세요."
            seen.add(normalized)
        return None
    page.validator = validate
    return page.finish()


def build_plugins(parent, app):
    page = SettingsPage(parent, app, "", editable=False)
    frame = page
    colors = page.colors
    def toggle_plugin(plugin_id: str, currently_enabled: bool) -> None:
        app.plugin_manager.set_enabled(plugin_id, not currently_enabled)
        reload_plugins()

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
        reload_plugins()
        loaded = next((item for item in app.plugin_manager.plugins if item.id == plugin.id), plugin)
        if loaded.error:
            messagebox.showwarning("플러그인 설치 완료 · 로드 실패", f"{plugin.name} 설치 완료\n{plugin.path}\n\n{loaded.error}")
        else:
            messagebox.showinfo("플러그인 설치 완료", f"{plugin.name} 설치 완료\n{plugin.path}\n\n상태: {loaded.status}")

    def reload_plugins():
        app.reload_plugins()
        target = next(tool for tool in app.registry.tools_for("설정") if tool.id == "settings.plugins")
        app.show_tool(target)

    actions = page.card("플러그인 추가", "ZIP 파일로 설치합니다.")
    RoundedButton(actions, "ZIP 파일 선택", install_plugin, colors, accent=True).pack(fill="x", pady=4)
    RoundedButton(actions, "플러그인 다시 검색", reload_plugins, colors, compact=True).pack(fill="x", pady=4)
    plugins = getattr(app.plugin_manager, "plugins", [])
    enabled = sum(1 for plugin in plugins if plugin.enabled and not plugin.error)
    page.note(page.content, f"설치됨 {len(plugins)}개 · 사용 중 {enabled}개", panel=False)
    if not plugins:
        body = page.card("설치된 플러그인이 없습니다", "ZIP 파일을 선택해 추가할 수 있습니다.")
    for plugin in plugins:
        body = page.card(f"{plugin.name} · v{plugin.version}", f"{plugin.id} · {plugin.status}")
        if plugin.error:
            page.note(body, plugin.error)
        RoundedButton(body, "비활성화" if plugin.enabled else "활성화",
                      lambda plugin=plugin: toggle_plugin(plugin.id, plugin.enabled), colors,
                      compact=True).pack(fill="x", pady=(4, 0))
    return page.finish()


def build_updates(parent, app):
    page = SettingsPage(parent, app, "")
    body = page.card("자동 업데이트", "설치본은 시작 시와 실행 중 6시간마다 새 버전을 확인합니다.")
    automatic = page.variable(("updates", "automatic"), boolean=True)
    tk.Checkbutton(body, text="자동으로 업데이트 확인", variable=automatic,
                   bg=page.colors["panel_soft"], fg=page.colors["text"], selectcolor=page.colors["field"],
                   activebackground=page.colors["panel_soft"], activeforeground=page.colors["text"]).pack(anchor="w", pady=6)
    body = page.card("업데이트 상태", "수동 확인은 저장하지 않아도 바로 실행됩니다.")
    RoundedButton(body, "지금 업데이트 확인", app.updater.check, page.colors, compact=True).pack(fill="x", pady=4)
    status = page.note(body, "")
    status.configure(textvariable=app.updater.status)
    page.note(body, "업데이트 후에도 사용자 설정과 저장 파일은 유지됩니다.")
    return page.finish()


def register(registry):
    registry.register(ToolSpec("settings.preferences", "테마 및 화면", "설정", build, 0))
    registry.register(ToolSpec("settings.paths", "실행 경로", "설정", build_paths, 10))
    registry.register(ToolSpec("settings.hotkeys", "단축키", "설정", build_hotkeys, 20))
    registry.register(ToolSpec("settings.plugins", "플러그인", "설정", build_plugins, 30))
    registry.register(ToolSpec("settings.updates", "업데이트", "설정", build_updates, 40))
