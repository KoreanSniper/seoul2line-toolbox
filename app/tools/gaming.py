from __future__ import annotations

import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette


LAUNCHER_META = (
    ("Valorant", "valorant", "Riot Client 또는 VALORANT 실행 파일"),
    ("Minecraft", "minecraft_launcher", "Minecraft Launcher 실행 파일"),
    ("Steam", "steam", "steam://open/main 같은 URI 또는 Steam 실행 파일"),
)


def _launch(target: str) -> tuple[bool, str]:
    if not target.strip():
        return False, "실행 경로나 URI가 비어 있습니다. 설정에서 먼저 지정해 주세요."
    try:
        if "://" in target:
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen([target], shell=False)
        return True, "실행 명령을 보냈습니다."
    except OSError as exc:
        return False, str(exc)


def _minecraft_versions(path: str) -> list[str]:
    versions_dir = Path(path).expanduser()
    if not versions_dir.exists():
        return []
    return sorted([item.name for item in versions_dir.iterdir() if item.is_dir()], reverse=True)


class GamingTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        self.status = tk.StringVar(value="런처 대기 중")
        self.launchers = app.config_store.get("launchers", default={})
        self.minecraft_cfg = app.config_store.get("minecraft", default={})
        self.launcher_vars = {key: tk.StringVar(value=self.launchers.get(key, "")) for _name, key, _hint in LAUNCHER_META}
        self.selected_version = tk.StringVar(value=self.minecraft_cfg.get("selected_version", ""))
        self._build()

    def _build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="게임", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="자주 쓰는 게임 런처를 저장하고 한 번에 실행합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(3, 0))
        RoundedButton(header, "설정 열기", lambda: self.app.show_section("설정"), colors, compact=True, radius=10, anchor="center").grid(row=0, column=1, rowspan=2, sticky="e")

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        launcher_panel = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=18, padding=14)
        launcher_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(launcher_panel.body, text="원클릭 실행", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(launcher_panel.body, text="경로를 저장해두면 다음부터 바로 실행할 수 있습니다.", fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 10))
        for name, key, hint in LAUNCHER_META:
            self.launcher_card(launcher_panel.body, name, key, hint)

        version_panel = RoundedFrame(body, colors, colors["panel_soft"], colors["border"], radius=18, padding=14)
        version_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        version_panel.body.columnconfigure(0, weight=1)
        version_panel.body.rowconfigure(2, weight=1)
        tk.Label(version_panel.body, text="Minecraft 버전", fg=colors["text"], bg=colors["panel_soft"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(version_panel.body, text="설정된 versions 폴더에서 감지합니다.", fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(3, 10))

        list_wrap = tk.Frame(version_panel.body, bg=colors["panel_soft"])
        list_wrap.grid(row=2, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)
        self.version_box = tk.Listbox(
            list_wrap,
            height=12,
            bg=colors["field"],
            fg=colors["text"],
            selectbackground=colors["accent_soft"],
            selectforeground=colors["accent"],
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
            activestyle="none",
            exportselection=False,
            font=("Consolas", 10),
        )
        scroll = styled_scrollbar(list_wrap, "vertical", self.version_box.yview, colors)
        self.version_box.configure(yscrollcommand=scroll.set)
        self.version_box.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.version_box.bind("<<ListboxSelect>>", self.sync_selection)
        self.reload_versions()

        bottom = tk.Frame(version_panel.body, bg=colors["panel_soft"])
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        RoundedButton(bottom, "버전 저장", self.save_version, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        RoundedButton(bottom, "목록 갱신", self.reload_versions, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=1, sticky="ew")

        tk.Label(self, textvariable=self.status, fg=colors["muted"], bg=colors["panel"], anchor="w", font=("Segoe UI", 9)).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))

    def launcher_card(self, parent: tk.Widget, name: str, key: str, hint: str) -> None:
        colors = self.colors
        card = tk.Frame(parent, bg=colors["panel_soft"], highlightthickness=1, highlightbackground=colors["border"])
        card.pack(fill="x", pady=(0, 10))
        card.columnconfigure(0, weight=1)
        title_row = tk.Frame(card, bg=colors["panel_soft"])
        title_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        title_row.columnconfigure(0, weight=1)
        tk.Label(title_row, text=name, fg=colors["text"], bg=colors["panel_soft"], font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        actions = tk.Frame(title_row, bg=colors["panel_soft"])
        actions.grid(row=0, column=1, sticky="e")
        RoundedButton(actions, "찾기", lambda value=key: self.browse_exe(value), colors, compact=True, radius=10, anchor="center", height=34).pack(side="left", padx=(0, 6))
        RoundedButton(actions, "실행", lambda value=key: self.save_and_launch(value), colors, accent=True, compact=True, radius=10, anchor="center", height=34).pack(side="left")
        tk.Label(card, text=hint, fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9), anchor="w", wraplength=460, justify="left").grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        entry = styled_entry(card, colors, self.launcher_vars[key])
        entry.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12), ipady=8)

    def browse_exe(self, key: str) -> None:
        path = filedialog.askopenfilename(title="실행 파일 선택", filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*.*")])
        if path:
            self.launcher_vars[key].set(path)
            self.app.config_store.set("launchers", key, value=path)
            self.status.set(f"{key} 경로 저장")

    def save_and_launch(self, key: str) -> None:
        target = self.launcher_vars[key].get()
        self.app.config_store.set("launchers", key, value=target)
        ok, msg = _launch(target)
        self.status.set(msg)
        (messagebox.showinfo if ok else messagebox.showerror)("seoul2line Toolbox", msg)

    def reload_versions(self) -> None:
        versions = _minecraft_versions(self.minecraft_cfg.get("versions_path", ""))
        self.version_box.delete(0, "end")
        for version in versions or ["버전 폴더를 찾지 못했습니다"]:
            self.version_box.insert("end", version)
        if self.selected_version.get() in versions:
            self.version_box.selection_set(versions.index(self.selected_version.get()))
        self.status.set(f"Minecraft 버전 {len(versions)}개 감지")

    def sync_selection(self, _event=None) -> None:
        selection = self.version_box.curselection()
        if not selection:
            return
        value = self.version_box.get(selection[0])
        if value != "버전 폴더를 찾지 못했습니다":
            self.selected_version.set(value)
            self.status.set(f"Minecraft 버전 선택: {value}")

    def save_version(self) -> None:
        if not self.selected_version.get():
            messagebox.showwarning("seoul2line Toolbox", "저장할 Minecraft 버전을 선택하세요.")
            return
        self.app.config_store.set("minecraft", "selected_version", value=self.selected_version.get())
        self.status.set(f"Minecraft 버전 저장: {self.selected_version.get()}")
        messagebox.showinfo("seoul2line Toolbox", "마인크래프트 버전 설정을 저장했습니다.")


def styled_entry(parent: tk.Widget, colors: dict[str, str], variable: tk.StringVar) -> tk.Entry:
    return tk.Entry(
        parent,
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


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return GamingTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("gaming.launchers", "게임 실행기", "게임", build, 0))
