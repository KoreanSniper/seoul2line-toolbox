from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app.config import APP_DIR, AppConfig
from app.automation.runtime import AutomationRuntime
from app.economy import currency_color, ensure_daily_grant, format_coins, wallet_entries
from app.screenshot import ScreenshotHotkeyManager
from app.tool_registry import MenuSpec, ToolRegistry, ToolSpec, load_builtin_tools
from app.tools.minigame_korean_stocks import StockPriceEngine
from app.ui import RoundedButton, RoundedFrame, rounded_rect
from app.palette import palette
from app.plugin_system import PluginManager
from app.update_ui import UpdateController
from app.version import VERSION

SECTION_DESCRIPTIONS = {
    "홈": "전체 도구 개요와 빠른 시작",
    "게임": "게임 실행과 버전 선택",
    "네트워크": "연결 상태와 응답 시간",
    "파일": "생성, 이동, 수정, 정리",
    "미니게임": "작은 게임과 샌드박스",
    "설정": "테마와 단축키, 실행 경로",
}


SECTION_ICONS = {
    "홈": "H",
    "게임": "G",
    "네트워크": "N",
    "파일": "F",
    "미니게임": "M",
    "설정": "S",
}


@dataclass(frozen=True)
class PaletteCommand:
    title: str
    subtitle: str
    keywords: str
    action: Callable[[], object]


class Seoul2LineToolbox(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"seoul2line Toolbox {VERSION}")
        self.geometry("1280x760")
        self.minsize(980, 620)

        self.config_store = AppConfig.load()
        self.config_store.owner = self
        ensure_daily_grant(self.config_store)
        self.plugin_manager = PluginManager(self.config_store)
        self.registry: ToolRegistry = load_builtin_tools()
        self.plugin_manager.load_into(self.registry)
        self.automation = AutomationRuntime(APP_DIR / "automation")
        self.automation_notifications: list[str] = []
        self._automation_job = self.after(300, self._poll_automation)
        self.current_section = "홈"
        self.current_tool_id: str | None = None
        self.dark_mode = self.config_store.get("theme", default="dark") == "dark"
        self.section_buttons: dict[str, RoundedButton] = {}
        self.tool_buttons: dict[str, RoundedButton] = {}
        self.menu_buttons: dict[str, RoundedButton] = {}
        self.command_palette: tk.Toplevel | None = None
        self.palette_query: tk.StringVar | None = None
        self.palette_results: tk.Frame | None = None
        self.palette_commands: list[PaletteCommand] = []
        self.gpt_panel_visible = False
        self.gpt_panel: tk.Frame | None = None
        self.gpt_prompt: tk.Text | None = None
        self.main_pane: tk.PanedWindow | None = None
        self.dev_pane: tk.PanedWindow | None = None
        self.gpt_help_label: tk.Label | None = None
        self.wallet_chip: tk.Canvas | None = None
        self.stock_price_button: RoundedButton | None = None
        self._source_snapshot = self._source_signature()
        self._reload_candidate: tuple[tuple[str, int, int], ...] | None = None
        self._reload_job: str | None = None
        self.stock_price_engine = StockPriceEngine(self)
        self.screenshot_manager = ScreenshotHotkeyManager(self)

        self._configure_style()
        self._build_layout()
        self.bind_all("<Control-k>", self._open_command_palette)
        self.bind_all("<Control-K>", self._open_command_palette)
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.screenshot_manager.start()
        self.show_section("홈")
        self._watch_source_files()
        self.updater = UpdateController(self)

    

    def _configure_style(self) -> None:
        colors = palette(self.dark_mode)
        self.configure(bg=colors["app"])
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=colors["panel"])
        style.configure("TLabel", background=colors["panel"], foreground=colors["text"])
        style.configure(
            "TButton",
            padding=(12, 8),
            background=colors["surface_hover"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            lightcolor=colors["surface_hover"],
            darkcolor=colors["surface_hover"],
            relief="flat",
            font=("Segoe UI", 9),
        )
        style.map("TButton", background=[("active", colors["accent_soft"])])
        style.configure(
            "Accent.TButton",
            padding=(14, 8),
            background=colors["accent"],
            foreground=colors["accent_text"],
            bordercolor=colors["accent"],
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "TEntry",
            fieldbackground=colors["field"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            padding=7,
        )
        style.configure(
            "TCombobox",
            fieldbackground=colors["field"],
            background=colors["surface_hover"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            arrowcolor=colors["muted"],
            padding=7,
        )
        style.configure("Treeview", background=colors["surface"], fieldbackground=colors["surface"], foreground=colors["text"], rowheight=28, bordercolor=colors["border"])
        style.configure("Treeview.Heading", background=colors["panel_soft"], foreground=colors["muted"], relief="flat", font=("Segoe UI", 9, "bold"))

    def _build_layout(self) -> None:
        colors = palette(self.dark_mode)
        self.shell = tk.Frame(self, bg=colors["app"])
        self.shell.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.shell, width=88, bg=colors["sidebar"], highlightthickness=1, highlightbackground=colors["border_soft"])
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main_pane = tk.PanedWindow(
            self.shell,
            orient="horizontal",
            bg=colors["border_soft"],
            bd=0,
            sashwidth=7,
            sashrelief="flat",
            showhandle=False,
            opaqueresize=True,
        )
        self.main_pane.pack(side="left", fill="both", expand=True)

        self.tool_nav = tk.Frame(self.main_pane, width=280, bg=colors["nav"], highlightthickness=1, highlightbackground=colors["border_soft"])
        self.tool_nav.pack_propagate(False)

        self.content_area = tk.Frame(self.main_pane, bg=colors["app"])
        self.main_pane.add(self.tool_nav, minsize=210, width=280, stretch="never")
        self.main_pane.add(self.content_area, minsize=520, stretch="always")

        self.dev_pane = tk.PanedWindow(
            self.content_area,
            orient="horizontal",
            bg=colors["border_soft"],
            bd=0,
            sashwidth=7,
            sashrelief="flat",
            showhandle=False,
            opaqueresize=True,
        )
        self.dev_pane.pack(fill="both", expand=True)

        self.workspace = tk.Frame(self.dev_pane, bg=colors["app"])
        self.dev_pane.add(self.workspace, minsize=460, stretch="always")

        self.gpt_panel = tk.Frame(self.dev_pane, width=360, bg=colors["nav"], highlightthickness=1, highlightbackground=colors["border_soft"])
        self.gpt_panel.pack_propagate(False)
        self.gpt_panel.bind("<Configure>", lambda _event: self._update_responsive_wraps())
        self._build_gpt_panel()
        self._sync_gpt_panel()
        self.after(80, self._set_initial_panes)

        self._build_sidebar()

    def _build_sidebar(self) -> None:
        colors = palette(self.dark_mode)
        for child in self.sidebar.winfo_children():
            child.destroy()

        logo = tk.Frame(self.sidebar, bg=colors["sidebar"])
        logo.pack(fill="x", pady=(16, 18))
        tk.Label(logo, text="S2", font=("Segoe UI", 15, "bold"), fg=colors["accent"], bg=colors["sidebar"]).pack()
        tk.Label(logo, text="Toolbox", font=("Segoe UI", 7), fg=colors["subtle"], bg=colors["sidebar"]).pack()

        self.section_buttons.clear()
        top_canvas = tk.Canvas(self.sidebar, bg=colors["sidebar"], highlightthickness=0, bd=0)
        top_canvas.pack(fill="both", expand=True)
        top = tk.Frame(top_canvas, bg=colors["sidebar"])
        top_window = top_canvas.create_window((0, 0), window=top, anchor="nw", width=86)
        top.bind("<Configure>", lambda _event: top_canvas.configure(scrollregion=top_canvas.bbox("all")))
        top_canvas.bind("<Configure>", lambda event: top_canvas.itemconfigure(top_window, width=event.width))
        self._bind_wheel(top_canvas)
        for section in [s for s in self.registry.sections() if s != "설정"]:
            self.section_buttons[section] = self._sidebar_button(top, section)

        bottom = tk.Frame(self.sidebar, bg=colors["sidebar"])
        bottom.pack(side="bottom", fill="x", pady=(8, 14))
        self.section_buttons["설정"] = self._sidebar_button(bottom, "설정")

    def _sidebar_button(self, parent: tk.Widget, section: str) -> RoundedButton:
        colors = palette(self.dark_mode)
        section_spec = self.registry.section_spec(section)
        icon = section_spec.icon if section_spec else SECTION_ICONS.get(section, section[:1])
        button = RoundedButton(
            parent,
            text=f"{icon}\n{section}",
            command=lambda: self.show_section(section),
            colors=colors,
            compact=False,
            radius=14,
            anchor="center",
            height=58,
        )
        button.pack(fill="x", padx=10, pady=3)
        return button

    def _set_active_sidebar(self) -> None:
        colors = palette(self.dark_mode)
        for section, button in self.section_buttons.items():
            button.set_active(section == self.current_section)

    def show_section(self, section: str) -> None:
        self.current_section = section
        self._set_active_sidebar()
        if section != "개발자":
            self.gpt_panel_visible = False
        self._sync_gpt_panel()
        tools = self.registry.tools_for(section)
        menus = self.registry.menus_for(section)
        first = tools[0] if tools else None
        self._render_tool_nav(section, tools, menus)
        if first:
            self.show_tool(first)
        else:
            self._render_empty(section)

    def _render_tool_nav(self, section: str, tools: list[ToolSpec], menus: list[MenuSpec] | None = None) -> None:
        colors = palette(self.dark_mode)
        menus = menus if menus is not None else self.registry.menus_for(section)
        for child in self.tool_nav.winfo_children():
            child.destroy()
        self.tool_buttons.clear()
        self.menu_buttons.clear()

        header = tk.Frame(self.tool_nav, bg=colors["nav"])
        header.pack(fill="x", padx=18, pady=(20, 16))
        tk.Label(header, text=section, font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["nav"]).pack(anchor="w")
        tk.Label(
            header,
            text=(self.registry.section_spec(section).description if self.registry.section_spec(section) else SECTION_DESCRIPTIONS.get(section, "")),
            font=("Segoe UI", 9),
            fg=colors["muted"],
            bg=colors["nav"],
            wraplength=230,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        tk.Label(self.tool_nav, text="도구", font=("Segoe UI", 8, "bold"), fg=colors["subtle"], bg=colors["nav"]).pack(anchor="w", padx=18, pady=(2, 8))
        list_canvas = tk.Canvas(self.tool_nav, bg=colors["nav"], highlightthickness=0, bd=0)
        list_canvas.pack(fill="both", expand=True, padx=12)
        list_host = tk.Frame(list_canvas, bg=colors["nav"])
        list_window = list_canvas.create_window((0, 0), window=list_host, anchor="nw")
        list_host.bind("<Configure>", lambda _event: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.bind("<Configure>", lambda event: list_canvas.itemconfigure(list_window, width=event.width))
        self._bind_wheel(list_canvas)
        for tool in tools:
            self.tool_buttons[tool.id] = self._tool_button(list_host, tool)
        if menus:
            tk.Label(list_host, text="메뉴", font=("Segoe UI", 8, "bold"), fg=colors["subtle"], bg=colors["nav"]).pack(anchor="w", padx=6, pady=(16, 5))
            for menu in menus:
                self.menu_buttons[menu.id] = self._menu_button(list_host, menu)

    def _bind_wheel(self, canvas: tk.Canvas) -> None:
        def on_wheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

    def _tool_button(self, parent: tk.Widget, tool: ToolSpec) -> RoundedButton:
        colors = palette(self.dark_mode)
        button = RoundedButton(
            parent,
            text=tool.label,
            command=lambda spec=tool: self.show_tool(spec),
            colors=colors,
            compact=False,
            radius=12,
            anchor="w",
            height=42,
        )
        button.pack(fill="x", pady=3)
        return button

    def _menu_button(self, parent: tk.Widget, menu: MenuSpec) -> RoundedButton:
        colors = palette(self.dark_mode)
        button = RoundedButton(
            parent,
            text=f"[menu] {menu.label}",
            command=lambda spec=menu: self.run_menu(spec),
            colors=colors,
            compact=False,
            radius=12,
            anchor="w",
            height=38,
        )
        button.pack(fill="x", pady=3)
        return button

    def run_menu(self, menu: MenuSpec) -> None:
        try:
            menu.action(self)
        except Exception as exc:
            messagebox.showerror("플러그인 메뉴 오류", f"{menu.label}을(를) 실행하지 못했습니다.\n{type(exc).__name__}: {exc}")

    def show_tool(self, tool: ToolSpec) -> None:
        self.current_tool_id = tool.id
        colors = palette(self.dark_mode)
        for tool_id, button in self.tool_buttons.items():
            button.set_active(tool_id == tool.id)

        for child in self.workspace.winfo_children():
            child.destroy()

        chrome = tk.Frame(self.workspace, bg=colors["app"])
        chrome.pack(fill="both", expand=True, padx=22, pady=20)

        topbar = tk.Frame(chrome, bg=colors["app"])
        topbar.pack(fill="x", pady=(0, 14))
        tk.Label(topbar, text=tool.label, font=("Segoe UI", 18, "bold"), fg=colors["text"], bg=colors["app"]).pack(side="left")
        self.wallet_chip = tk.Canvas(topbar, width=230, height=34, bg=colors["app"], highlightthickness=0, bd=0)
        self.wallet_chip.pack(side="right", padx=(12, 0))
        self.wallet_chip.bind("<Configure>", lambda _event: self.refresh_wallet_display())
        self.refresh_wallet_display()
        self.stock_price_button = RoundedButton(
            topbar,
            self._stock_price_button_text(),
            self.toggle_stock_price,
            colors,
            compact=True,
            radius=10,
        )
        self.stock_price_button.pack(side="right", padx=(8, 0))
        if tool.section == "개발자":
            RoundedButton(topbar, "GPT", self.toggle_gpt_panel, colors, compact=True, radius=10).pack(side="right", padx=(8, 0))
        tk.Label(topbar, text="Ctrl+K", font=("Segoe UI", 9, "bold"), fg=colors["accent"], bg=colors["app"]).pack(side="right")
        tk.Label(topbar, text=f"{tool.section} / {tool.label}", font=("Segoe UI", 9), fg=colors["subtle"], bg=colors["app"]).pack(side="right", padx=(0, 12))

        host_panel = RoundedFrame(chrome, colors, colors["panel"], colors["border"], radius=18, padding=4)
        host_panel.pack(fill="both", expand=True)
        try:
            tool.factory(host_panel.body, self).pack(fill="both", expand=True)
        except Exception as exc:
            # 특정 도구 초기화 실패가 전체 Toolbox 화면 전환을 막지 않게 격리한다.
            tk.Label(
                host_panel.body,
                text=f"이 도구를 열지 못했습니다.\n{type(exc).__name__}: {exc}",
                fg=colors["danger"],
                bg=colors["panel"],
                justify="left",
                anchor="nw",
            ).pack(fill="both", expand=True, padx=18, pady=18)
        self._refresh_stock_price_button()

    def _stock_price_button_text(self) -> str:
        return "가격 갱신 종료" if self.stock_price_engine.running else "가격 갱신 시작"

    def toggle_stock_price(self) -> None:
        self.stock_price_engine.toggle()
        self._refresh_stock_price_button()

    def _refresh_stock_price_button(self) -> None:
        if self.stock_price_button is not None and self.stock_price_button.winfo_exists():
            self.stock_price_button.text = self._stock_price_button_text()
            self.stock_price_button._draw()

    def refresh_wallet_display(self) -> None:
        if self.wallet_chip is None or not self.wallet_chip.winfo_exists():
            return
        colors = palette(self.dark_mode)
        chip = self.wallet_chip
        chip.delete("all")
        width = max(chip.winfo_width(), 230)
        height = 34
        rounded_rect(chip, 1, 1, width - 1, height - 1, 17, fill=colors["surface_hover"], outline=colors["border"])
        entries = wallet_entries(self.config_store)
        name, currency, amount = entries[0]
        chip.create_oval(10, 8, 26, 24, fill=currency_color(currency), outline="")
        chip.create_text(36, 17, text=name, anchor="w", fill=colors["muted"], font=("Segoe UI", 8, "bold"))
        suffix = f"  +{len(entries) - 1}" if len(entries) > 1 else ""
        chip.create_text(width - 12, 17, text=f"{format_coins(amount, currency)}{suffix}", anchor="e", fill=colors["text"], font=("Segoe UI", 9, "bold"))

    def _render_empty(self, section: str) -> None:
        colors = palette(self.dark_mode)
        for child in self.workspace.winfo_children():
            child.destroy()
        box = tk.Frame(self.workspace, bg=colors["app"])
        box.pack(fill="both", expand=True, padx=22, pady=20)
        tk.Label(box, text=f"{section}에 등록된 도구가 없습니다.", font=("Segoe UI", 14, "bold"), fg=colors["text"], bg=colors["app"]).pack(anchor="w")

    def reload_plugins(self) -> None:
        current_section = self.current_section
        self.registry = load_builtin_tools()
        self.plugin_manager = PluginManager(self.config_store)
        self.plugin_manager.load_into(self.registry)
        self._build_sidebar()
        target = current_section if current_section in self.registry.sections() else "홈"
        self.show_section(target)

    def reload_theme(self) -> None:
        self.dark_mode = self.config_store.get("theme", default="dark") == "dark"
        self._configure_style()
        self.shell.destroy()
        self._build_layout()
        self.show_section(self.current_section)

    def _build_gpt_panel(self) -> None:
        if self.gpt_panel is None:
            return
        colors = palette(self.dark_mode)
        for child in self.gpt_panel.winfo_children():
            child.destroy()

        header = tk.Frame(self.gpt_panel, bg=colors["nav"])
        header.pack(fill="x", padx=16, pady=(16, 10))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="GPT", font=("Segoe UI", 18, "bold"), fg=colors["text"], bg=colors["nav"]).grid(row=0, column=0, sticky="w")
        RoundedButton(header, "닫기", self.toggle_gpt_panel, colors, compact=True, radius=10).grid(row=0, column=1, sticky="e")
        tk.Label(
            self.gpt_panel,
            text="개발 중 GPT에 던질 프롬프트를 임시로 정리하고 바로 복사합니다. 브라우저 임베딩은 불안정해서 제거했습니다.",
            font=("Segoe UI", 9),
            fg=colors["muted"],
            bg=colors["nav"],
            wraplength=310,
            justify="left",
        ).pack(fill="x", padx=16, pady=(0, 12))
        self.gpt_help_label = self.gpt_panel.winfo_children()[-1]

        actions = tk.Frame(self.gpt_panel, bg=colors["nav"])
        actions.pack(fill="x", padx=16, pady=(0, 12))
        RoundedButton(actions, "프롬프트 복사", self.copy_gpt_prompt, colors, accent=True, compact=True, radius=10).pack(side="left", fill="x", expand=True)

        panel = RoundedFrame(self.gpt_panel, colors, colors["surface"], colors["border"], radius=16, padding=12)
        panel.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        tk.Label(panel.body, text="프롬프트 임시 보관", font=("Segoe UI", 10, "bold"), fg=colors["text"], bg=colors["surface"]).pack(anchor="w", pady=(0, 8))
        self.gpt_prompt = tk.Text(
            panel.body,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["accent"],
            relief="flat",
            bd=0,
            wrap="word",
            font=("Segoe UI", 10),
            height=12,
        )
        self.gpt_prompt.pack(fill="both", expand=True)
        self.gpt_prompt.insert(
            "1.0",
            "지금 열려 있는 seoul2line Toolbox 개발자 도구 작업을 도와줘.\n\n요구사항:\n",
        )

    def toggle_gpt_panel(self) -> None:
        self.gpt_panel_visible = not self.gpt_panel_visible
        if self.gpt_panel_visible and self.current_section != "개발자":
            self.show_section("개발자")
            return
        self._sync_gpt_panel()

    def _sync_gpt_panel(self) -> None:
        if self.gpt_panel is None or self.dev_pane is None:
            return
        should_show = self.gpt_panel_visible and self.current_section == "개발자"
        has_panel = self._pane_contains(self.dev_pane, self.gpt_panel)
        if should_show and not has_panel:
            self.dev_pane.add(self.gpt_panel, minsize=260, width=360, stretch="never")
            self.after(40, self._place_gpt_sash)
        elif not should_show and has_panel:
            self.dev_pane.forget(self.gpt_panel)
        self._update_responsive_wraps()

    def _pane_contains(self, pane: tk.PanedWindow, child: tk.Widget) -> bool:
        return any(str(item) == str(child) for item in pane.panes())

    def _set_initial_panes(self) -> None:
        if self.main_pane is not None and self.main_pane.winfo_width() > 0:
            try:
                self.main_pane.sash_place(0, 280, 1)
            except tk.TclError:
                pass
        self._place_gpt_sash()

    def _place_gpt_sash(self) -> None:
        if self.dev_pane is None or self.gpt_panel is None or not self._pane_contains(self.dev_pane, self.gpt_panel):
            return
        width = self.dev_pane.winfo_width()
        if width <= 0:
            return
        try:
            self.dev_pane.sash_place(0, max(460, width - 360), 1)
        except tk.TclError:
            pass

    def _update_responsive_wraps(self) -> None:
        if self.gpt_panel is None or self.gpt_help_label is None:
            return
        width = max(220, self.gpt_panel.winfo_width() - 42)
        self.gpt_help_label.configure(wraplength=width)

    def _close_app(self) -> None:
        self.updater.close()
        self.after_cancel(self._automation_job)
        self.automation.close()
        if self._reload_job is not None:
            try:
                self.after_cancel(self._reload_job)
            except tk.TclError:
                pass
            self._reload_job = None
        self.screenshot_manager.stop()
        self.stock_price_engine.close()
        self.destroy()

    def drain_automation_events(self):
        import queue
        events = []
        while True:
            try:
                event = self.automation.events.get_nowait()
            except queue.Empty:
                break
            events.append(event)
            if event[1] == "notify":
                self.automation_notifications.append(event[2])
        return events

    def _poll_automation(self):
        # Editor consumes the same feed and queues notifications for this timer.
        if self.current_tool_id != "automation.editor":
            self.drain_automation_events()
        if self.automation_notifications:
            messages = self.automation_notifications[:10]
            del self.automation_notifications[:10]
            # Non-modal notification: large batches never block the GUI loop.
            notice = tk.Toplevel(self)
            notice.title("자동화 완료")
            tk.Label(notice, text="\n".join(messages), padx=24, pady=16).pack()
            notice.after(5000, notice.destroy)
        self._automation_job = self.after(300, self._poll_automation)

    def _source_signature(self) -> tuple[tuple[str, int, int], ...]:
        """실행 중인 Python 소스의 변경 여부만 확인한다. user_data는 감시하지 않는다."""
        root = Path(__file__).resolve().parents[1]
        paths = [root / "main.py"] + sorted((root / "app").rglob("*.py"))
        signature = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _watch_source_files(self) -> None:
        if getattr(sys, "frozen", False):
            return
        current = self._source_signature()
        if current != self._source_snapshot and self._reload_candidate is None:
            # 저장 중인 파일을 반쯤 읽어 재시작하지 않도록 잠시 안정화 시간을 둔다.
            self._reload_candidate = current
            self._reload_job = self.after(900, self._restart_if_source_stable)
        self.after(700, self._watch_source_files)

    def _restart_if_source_stable(self) -> None:
        self._reload_job = None
        current = self._source_signature()
        if self._reload_candidate != current:
            self._reload_candidate = current
            self._reload_job = self.after(900, self._restart_if_source_stable)
            return
        self.title("seoul2line Toolbox - 코드 변경 적용 중")
        self.automation.close()
        self.screenshot_manager.stop()
        self.stock_price_engine.close()
        # 새 프로세스가 같은 창을 이어받아 최신 모듈을 다시 import한다.
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def copy_gpt_prompt(self) -> None:
        if self.gpt_prompt is None:
            return
        self.clipboard_clear()
        self.clipboard_append(self.gpt_prompt.get("1.0", "end-1c"))

    def _open_command_palette(self, event: tk.Event | None = None) -> str:
        if self.command_palette and self.command_palette.winfo_exists():
            self.command_palette.lift()
            if self.palette_query is not None:
                self.palette_query.set("")
            self._refresh_palette_results()
            return "break"

        colors = palette(self.dark_mode)
        self.palette_commands = self._build_palette_commands()
        self.palette_query = tk.StringVar()
        self.command_palette = tk.Toplevel(self)
        self.command_palette.title("커맨드 팔레트")
        self.command_palette.configure(bg=colors["app"])
        self.command_palette.transient(self)
        self.command_palette.resizable(False, False)

        width = 640
        height = 460
        x = self.winfo_rootx() + max(24, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + 72
        self.command_palette.geometry(f"{width}x{height}+{x}+{y}")

        panel = tk.Frame(self.command_palette, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"])
        panel.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(panel, text="커맨드 팔레트", font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w", padx=18, pady=(16, 8))
        entry = tk.Entry(
            panel,
            textvariable=self.palette_query,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["accent"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 13),
        )
        entry.pack(fill="x", padx=18, ipady=10)
        entry.bind("<KeyRelease>", lambda _event: self._refresh_palette_results())
        entry.bind("<Escape>", lambda _event: self._close_command_palette())
        entry.bind("<Return>", lambda _event: self._run_first_palette_command())

        result_shell = tk.Frame(panel, bg=colors["panel"])
        result_shell.pack(fill="both", expand=True, padx=12, pady=14)
        canvas = tk.Canvas(result_shell, bg=colors["panel"], highlightthickness=0, bd=0)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(result_shell, orient="vertical", command=canvas.yview, bg=colors["panel"], troughcolor=colors["surface"], bd=0, relief="flat", highlightthickness=0)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)
        self.palette_results = tk.Frame(canvas, bg=colors["panel"])
        window_id = canvas.create_window((0, 0), window=self.palette_results, anchor="nw")
        self.palette_results.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda canvas_event: canvas.itemconfigure(window_id, width=canvas_event.width))
        self._bind_wheel(canvas)

        self.command_palette.bind("<Escape>", lambda _event: self._close_command_palette())
        self.command_palette.protocol("WM_DELETE_WINDOW", self._close_command_palette)
        self._refresh_palette_results()
        entry.focus_set()
        return "break"

    def _build_palette_commands(self) -> list[PaletteCommand]:
        commands: list[PaletteCommand] = []
        commands.append(
            PaletteCommand(
                title="GPT 메모 패널 토글",
                subtitle="개발자 화면 오른쪽 프롬프트 메모 패널을 열거나 닫습니다.",
                keywords="gpt chatgpt ai 개발자 오른쪽 패널 프롬프트 메모",
                action=self.toggle_gpt_panel,
            )
        )
        commands.append(
            PaletteCommand(
                title="영역 캡쳐",
                subtitle="PrintScreen과 같은 영역 선택 캡쳐를 바로 시작합니다.",
                keywords="printscreen screenshot capture 캡쳐 스크린샷 영역 선택",
                action=self.screenshot_manager.capture_now,
            )
        )
        for section in self.registry.sections():
            commands.append(
                PaletteCommand(
                    title=f"{section} 열기",
                    subtitle=(self.registry.section_spec(section).description if self.registry.section_spec(section) else SECTION_DESCRIPTIONS.get(section, "메뉴로 이동")),
                    keywords=f"{section} menu section",
                    action=lambda section=section: self.show_section(section),
                )
            )
            for tool in self.registry.tools_for(section):
                commands.append(
                    PaletteCommand(
                        title=tool.label,
                        subtitle=f"{tool.section} 도구 열기",
                        keywords=f"{tool.id} {tool.label} {tool.section}",
                        action=lambda tool=tool: self.show_tool_from_palette(tool),
                    )
                )
            for menu in self.registry.menus_for(section):
                commands.append(
                    PaletteCommand(
                        title=f"메뉴: {menu.label}",
                        subtitle=f"{menu.section} 플러그인 메뉴 실행",
                        keywords=f"{menu.id} {menu.label} {menu.section} menu plugin",
                        action=lambda menu=menu: self.run_menu(menu),
                    )
                )
        return commands

    def show_tool_from_palette(self, tool: ToolSpec) -> None:
        if tool.section != self.current_section:
            self.current_section = tool.section
            self._set_active_sidebar()
            self._render_tool_nav(tool.section, self.registry.tools_for(tool.section), self.registry.menus_for(tool.section))
        self.show_tool(tool)

    def _refresh_palette_results(self) -> None:
        if self.palette_results is None:
            return
        colors = palette(self.dark_mode)
        for child in self.palette_results.winfo_children():
            child.destroy()
        query = (self.palette_query.get() if self.palette_query else "").strip().lower()
        matches = [
            command
            for command in self.palette_commands
            if not query or query in command.title.lower() or query in command.subtitle.lower() or query in command.keywords.lower()
        ][:12]
        if not matches:
            tk.Label(self.palette_results, text="검색 결과가 없습니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 10)).pack(anchor="w", padx=8, pady=12)
            return
        for command in matches:
            item = tk.Frame(self.palette_results, bg=colors["surface_hover"], highlightthickness=1, highlightbackground=colors["border"])
            item.pack(fill="x", padx=6, pady=4)
            item.bind("<Button-1>", lambda _event, command=command: self._run_palette_command(command))
            title = tk.Label(item, text=command.title, fg=colors["text"], bg=colors["surface_hover"], font=("Segoe UI", 10, "bold"), anchor="w")
            title.pack(fill="x", padx=12, pady=(9, 1))
            title.bind("<Button-1>", lambda _event, command=command: self._run_palette_command(command))
            subtitle = tk.Label(item, text=command.subtitle, fg=colors["muted"], bg=colors["surface_hover"], font=("Segoe UI", 8), anchor="w")
            subtitle.pack(fill="x", padx=12, pady=(0, 9))
            subtitle.bind("<Button-1>", lambda _event, command=command: self._run_palette_command(command))

    def _run_first_palette_command(self) -> str:
        query = (self.palette_query.get() if self.palette_query else "").strip().lower()
        for command in self.palette_commands:
            if not query or query in command.title.lower() or query in command.subtitle.lower() or query in command.keywords.lower():
                self._run_palette_command(command)
                break
        return "break"

    def _run_palette_command(self, command: PaletteCommand) -> None:
        self._close_command_palette()
        command.action()

    def _close_command_palette(self) -> None:
        if self.command_palette and self.command_palette.winfo_exists():
            self.command_palette.destroy()
        self.command_palette = None
        self.palette_query = None
        self.palette_results = None


def main() -> None:
    from app.single_instance import acquire_installed_instance
    if not acquire_installed_instance():
        messagebox.showinfo("seoul2line Toolbox", "앱이 이미 실행 중입니다.")
        return
    app = Seoul2LineToolbox()
    app.mainloop()
