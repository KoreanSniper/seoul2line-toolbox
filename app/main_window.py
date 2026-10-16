from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app.config import APP_DIR, AppConfig
from app.branding import apply_window_icon, configure_app_id, logo_image
from app.automation.runtime import AutomationRuntime
from app.economy import currency_color, ensure_daily_grant, format_coins, wallet_entries
from app.screenshot import ScreenshotHotkeyManager
from app.tool_registry import MenuSpec, ToolRegistry, ToolSpec, load_builtin_tools
from app.tools.minigame_korean_stocks import StockPriceEngine
from app.ui import RoundedButton, RoundedFrame, rounded_rect
from app.palette import ThemeMode, palette
from app.theme_art import gradient_image, icon, tool_icon
from app.plugin_system import PluginManager
from app.update_ui import UpdateController
from app.version import VERSION

SECTION_DESCRIPTIONS = {
    "홈": "도구 목록",
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
        apply_window_icon(self)
        self.geometry("1440x860")
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
        self.dark_mode = ThemeMode(self.config_store.get("theme", default="dark"))
        self.section_buttons: dict[str, RoundedButton] = {}
        self.tool_buttons: dict[str, RoundedButton] = {}
        self.menu_buttons: dict[str, RoundedButton] = {}
        self.command_palette: tk.Frame | None = None
        self.palette_query: tk.StringVar | None = None
        self.palette_results: tk.Frame | None = None
        self.palette_commands: list[PaletteCommand] = []
        self.palette_selection = 0
        self.palette_matches: list[PaletteCommand] = []
        self.gpt_panel_visible = False
        self.tool_nav_collapsed = False
        self.tool_nav_width = 224
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
        self.bind_all("<Button-1>", self._dismiss_search_outside, add="+")
        self.bind("<Configure>", self._resize_search, add="+")
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
        self._build_search_header()
        body = tk.Frame(self.shell, bg=colors["app"])
        body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(body, width=174, bg=colors["sidebar"], highlightthickness=1, highlightbackground=colors["border_soft"])
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main_pane = tk.PanedWindow(
            body,
            orient="horizontal",
            bg=colors["border_soft"],
            bd=0,
            sashwidth=1,
            sashrelief="flat",
            showhandle=False,
            opaqueresize=True,
        )
        self.main_pane.pack(side="left", fill="both", expand=True)

        self.tool_nav = tk.Frame(self.main_pane, width=224, bg=colors["nav"], highlightthickness=1, highlightbackground=colors["border_soft"])
        self.tool_nav.pack_propagate(False)

        self.content_area = tk.Frame(self.main_pane, bg=colors["app"])
        self.main_pane.add(self.tool_nav, minsize=200, width=224, stretch="never")
        self.main_pane.add(self.content_area, minsize=520, stretch="always")
        if self.tool_nav_collapsed:
            self.main_pane.forget(self.tool_nav)

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
        tk.Label(logo, text="도구함", font=("Malgun Gothic", 9), fg=colors["sidebar_muted"], bg=colors["sidebar"]).pack(anchor="w", padx=20)

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
        self.nav_toggle = RoundedButton(
            bottom, "도구 목록 펼치기" if self.tool_nav_collapsed else "도구 목록 접기",
            self.toggle_tool_nav, colors, height=36,
        )
        self.nav_toggle.configure(height=25)
        self.nav_toggle.height = 25
        self.nav_toggle.pack(fill="x", padx=18, pady=(0, 8))
        self.section_buttons["설정"] = self._sidebar_button(bottom, "설정")

    def toggle_tool_nav(self) -> None:
        if self.tool_nav_collapsed:
            self.main_pane.add(self.tool_nav, before=self.content_area, minsize=200,
                               width=self.tool_nav_width, stretch="never")
        else:
            self.tool_nav_width = max(200, self.tool_nav.winfo_width())
            self.main_pane.forget(self.tool_nav)
        self.tool_nav_collapsed = not self.tool_nav_collapsed
        self.nav_toggle.text = "도구 목록 펼치기" if self.tool_nav_collapsed else "도구 목록 접기"
        self.nav_toggle._draw()

    def _sidebar_button(self, parent: tk.Widget, section: str) -> RoundedButton:
        colors = palette(self.dark_mode)
        icon_names = {'홈': 'home', '게임': 'game', '네트워크': 'network', '파일': 'folder',
                      '자동화': 'gear', '미니게임': 'game', '설정': 'gear', '개발자': 'monitor'}
        button = RoundedButton(
            parent,
            text=section,
            command=lambda: self.show_section(section),
            colors=colors,
            compact=False,
            radius=7,
            anchor="w",
            height=44,
            role='sidebar',
            icon_name=icon_names.get(section, 'grid'),
        )
        button.pack(fill="x", padx=18, pady=4)
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
        header.pack(fill="x", padx=22, pady=(24, 28))
        title_row = tk.Frame(header, bg=colors['nav'])
        title_row.pack(fill='x')
        tk.Label(title_row, text=section, font=("Malgun Gothic", 17, "bold"), fg=colors["text"], bg=colors["nav"]).pack(side='left')
        tk.Button(title_row, text='‹', command=self.toggle_tool_nav, relief='flat', bd=0,
                  bg=colors['nav'], fg=colors['muted'], cursor='hand2',
                  font=('Segoe UI', 16)).pack(side='right')
        tk.Label(
            header,
            text=(self.registry.section_spec(section).description if self.registry.section_spec(section) else SECTION_DESCRIPTIONS.get(section, "")),
            font=("Malgun Gothic", 10),
            fg=colors["muted"],
            bg=colors["nav"],
            wraplength=180,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        tk.Label(self.tool_nav, text="설정 메뉴" if section == "설정" else "도구", font=("Malgun Gothic", 11, "bold"), fg=colors["text"], bg=colors["nav"]).pack(anchor="w", padx=22, pady=(2, 12))
        list_canvas = tk.Canvas(self.tool_nav, bg=colors["nav"], highlightthickness=0, bd=0)
        list_canvas.pack(fill="both", expand=True, padx=12)
        list_host = tk.Frame(list_canvas, bg=colors["nav"])
        list_window = list_canvas.create_window((0, 0), window=list_host, anchor="nw")
        list_host.bind("<Configure>", lambda _event: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        def resize_list(event):
            list_canvas.itemconfigure(list_window, width=event.width)
            list_canvas.delete('nav_background')
            list_canvas._background = gradient_image(
                list_canvas, event.width, event.height, colors['nav'],
                colors['nav'])
            list_canvas.create_image(0, 0, image=list_canvas._background, anchor='nw', tags='nav_background')
            list_canvas.tag_lower('nav_background')
        list_canvas.bind('<Configure>', resize_list)
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
            radius=8,
            anchor="w",
            height=50,
            role='tool',
            icon_name=tool_icon(tool.id),
        )
        button.pack(fill="x", pady=5, padx=5)
        return button

    def _menu_button(self, parent: tk.Widget, menu: MenuSpec) -> RoundedButton:
        colors = palette(self.dark_mode)
        button = RoundedButton(
            parent,
            text=menu.label,
            command=lambda spec=menu: self.run_menu(spec),
            colors=colors,
            compact=False,
            radius=12,
            anchor="w",
            height=38,
            icon_name='puzzle',
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
        chrome.pack(fill="both", expand=True, padx=28, pady=(24, 30))

        topbar = tk.Frame(chrome, bg=colors["app"], height=66)
        topbar.pack(fill="x", pady=(0, 24))
        topbar.pack_propagate(False)
        heading = tk.Label(topbar, text=tool.label, font=("Malgun Gothic", 20, "bold"), fg=colors["text"], bg=colors["app"], anchor="w", justify="left")
        heading.place(x=0, y=0)
        heading.bind("<Configure>", lambda event: heading.configure(wraplength=max(180, event.width)))
        actions = tk.Frame(topbar, bg=colors["app"])
        actions.place(relx=1, y=12, anchor='ne')
        has_actions = tool.section in ('미니게임', '개발자')
        def resize_actions(event):
            stacked = has_actions and event.width < 760
            topbar.configure(height=(112 if stacked else 66) if has_actions else 42)
            actions.place_configure(y=58 if stacked else 12)
            if self.stock_price_button is not None:
                self.stock_price_button.configure(width=180 if event.width < 540 else 220)
        topbar.bind('<Configure>', resize_actions)
        self.wallet_chip = None
        self.stock_price_button = None
        if tool.section == '미니게임':
            self.wallet_chip = tk.Canvas(actions, width=230, height=44, bg=colors["app"], highlightthickness=0, bd=0)
            self.wallet_chip.pack(side="right", padx=(12, 0))
            self.wallet_chip.bind("<Configure>", lambda _event: self.refresh_wallet_display())
            self.refresh_wallet_display()
        if tool.id == 'minigame.korean_stocks':
            self.stock_price_button = RoundedButton(
                actions, self._stock_price_button_text(), self.toggle_stock_price, colors,
                compact=True, radius=6, height=40, role='action', icon_name='power')
            self.stock_price_button.configure(width=220)
            self.stock_price_button.pack(side="right", padx=(8, 0))
        if tool.section == "개발자":
            RoundedButton(actions, "GPT", self.toggle_gpt_panel, colors, compact=True, radius=10).pack(side="left", padx=(0, 8))

        if tool.id == 'home.overview':
            host_panel = tk.Frame(chrome, bg=colors['app'])
            host_body = host_panel
        else:
            host_panel = RoundedFrame(chrome, colors, colors["panel"], colors["border"], radius=14, padding=4)
            host_body = host_panel.body
        host_panel.pack(fill="both", expand=True)
        try:
            tool.factory(host_body, self).pack(fill="both", expand=True)
        except Exception as exc:
            # 특정 도구 초기화 실패가 전체 Toolbox 화면 전환을 막지 않게 격리한다.
            tk.Label(
                host_body,
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
        height = 44
        rounded_rect(chip, 1, 1, width - 1, height - 1, 9, fill=colors["field"], outline=colors["border"])
        entries = wallet_entries(self.config_store)
        name, currency, amount = entries[0]
        chip.create_oval(16, 14, 32, 30, fill=currency_color(currency), outline="")
        chip.create_text(45, 22, text=name, anchor="w", fill=colors["text"], font=("Malgun Gothic", 9, "bold"))
        chip.create_line(114, 14, 114, 30, fill=colors['border'])
        suffix = f"  +{len(entries) - 1}" if len(entries) > 1 else ""
        chip.create_text(width - 14, 22, text=f"{format_coins(amount, currency)}{suffix}", anchor="e", fill=colors["action_ink"], font=("Segoe UI", 11, "bold"))

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
        self._close_command_palette()
        self.dark_mode = ThemeMode(self.config_store.get("theme", default="dark"))
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
            text="질문이나 코드를 적고 복사할 수 있습니다.",
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
        if self.main_pane is not None and not self.tool_nav_collapsed and self.main_pane.winfo_width() > 0:
            try:
                self.main_pane.sash_place(0, self.tool_nav_width, 1)
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

    def _build_search_header(self) -> None:
        colors = palette(self.dark_mode)
        search_bg = colors.get('search_field', colors['field'])
        search_fg = colors.get('search_text', colors['text'])
        search_muted = colors.get('search_muted', colors['subtle'])
        header_bg = colors.get("header", colors["sidebar"])
        self.header = tk.Frame(self.shell, bg=header_bg, height=76,
                               highlightthickness=1, highlightbackground=colors["border_soft"])
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        self._header_logo = logo_image(self, 40)
        tk.Label(self.header, image=self._header_logo,
                 bg=header_bg).place(x=24, rely=.5, anchor="w")
        self.wordmark = tk.Label(self.header, text="Toolbox", font=("Segoe UI", 21, "bold"),
                                 fg=colors["sidebar_text"], bg=header_bg)
        self.wordmark.place(x=80, rely=.5, anchor="w")
        tk.Label(self.header, text=f"v{VERSION}", font=("Segoe UI", 9),
                 fg=colors["sidebar_muted"], bg=header_bg).place(relx=1, x=-20, rely=.5, anchor="e")
        self.search_box = RoundedFrame(self.header, colors, fill=search_bg,
                                       border=colors["search_border"], radius=9, padding=10)
        self.search_box.place(relx=.5, rely=.5, anchor="center", width=640, height=44)
        search_icon = tk.Canvas(self.search_box.body, width=25, height=24,
                                bg=search_bg, highlightthickness=0, bd=0)
        search_icon.pack(side='left', padx=(4, 12))
        icon(search_icon, 'search', 1, 1, 21, colors['hero_accent'])
        search_icon.bind('<Button-1>', self._open_command_palette)
        shortcut = tk.Label(self.search_box.body, text="Ctrl + K", font=("Segoe UI", 8),
                            bg=colors.get('shortcut_bg', colors["panel_soft"]),
                            fg=colors.get('shortcut_text', colors["action_ink"]), padx=7, pady=2,
                            cursor="hand2")
        shortcut.pack(side="right", padx=(10, 2))
        shortcut.bind("<Button-1>", self._open_command_palette)
        self.palette_query = tk.StringVar(self)
        self.search_entry = tk.Entry(self.search_box.body, textvariable=self.palette_query,
                                     bg=search_bg, fg=search_fg,
                                     insertbackground=colors["accent"], relief="flat", bd=0,
                                     font=("Segoe UI", 11))
        self.search_entry.pack(side="left", fill="both", expand=True)
        self.search_hint = tk.Label(self.search_entry, text="도구·메뉴 검색",
                                    bg=search_bg, fg=search_muted,
                                    font=("Segoe UI", 10), cursor="xterm")
        self.search_hint.place(x=0, rely=.5, anchor="w")
        self.search_hint.bind("<Button-1>", self._open_command_palette)
        self.palette_query.trace_add("write", self._search_query_changed)
        self.search_entry.bind("<FocusIn>", self._open_command_palette)
        self.search_entry.bind("<Button-1>", self._click_search)
        self.search_entry.bind("<Escape>", self._escape_search)
        self.search_entry.bind("<Return>", lambda _event: self._run_first_palette_command())
        self.search_entry.bind("<Down>", lambda _event: self._move_search_selection(1))
        self.search_entry.bind("<Up>", lambda _event: self._move_search_selection(-1))
        self.header.bind("<Configure>", self._resize_search)

    def _click_search(self, event: tk.Event) -> None:
        # Preserve Entry's normal caret placement and mouse text selection.
        self._open_command_palette(event)

    def _resize_search(self, event: tk.Event | None = None) -> None:
        if event is not None and event.widget not in (self, self.header):
            return
        width = max(320, min(646, self.header.winfo_width() - 380))
        narrow = self.header.winfo_width() < 1100
        self.wordmark.configure(font=('Segoe UI', 17 if narrow else 21, 'bold'))
        self.wordmark.place_configure(x=74 if narrow else 80)
        self.search_box.place_configure(width=width)
        if self.command_palette is not None:
            self.command_palette.place_configure(relx=.5, x=0, y=68, width=width)

    def _search_query_changed(self, *_args: str) -> None:
        if self.palette_query.get():
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=0, rely=.5, anchor="w")
        self.palette_selection = 0
        if self.command_palette is not None:
            self._refresh_palette_results()
        elif self.palette_query.get() and self.focus_get() == self.search_entry:
            self._open_command_palette()

    def _open_command_palette(self, event: tk.Event | None = None) -> str:
        self.search_entry.focus_set()
        if event is not None and getattr(event, "keysym", "").lower() == "k":
            self.search_entry.selection_range(0, "end")
        self.palette_commands = self._build_palette_commands()
        if self.command_palette is None or not self.command_palette.winfo_exists():
            colors = palette(self.dark_mode)
            self.palette_selection = 0
            self.command_palette = tk.Frame(self.shell, bg=colors["panel"],
                                            highlightthickness=1, highlightbackground=colors["border"])
            tk.Label(self.command_palette, text="빠른 이동   ·   ↑ ↓ 선택   Enter 실행   Esc 닫기",
                     font=("Segoe UI", 8), bg=colors["panel"], fg=colors["muted"],
                     anchor="w").pack(fill="x", padx=16, pady=(12, 6))
            self.palette_results = tk.Frame(self.command_palette, bg=colors["panel"])
            self.palette_results.pack(fill="both", expand=True, pady=(0, 8))
            self._resize_search()
        self._refresh_palette_results()
        self.command_palette.lift()
        return "break"

    def _move_search_selection(self, direction: int) -> str:
        if self.command_palette is None:
            self._open_command_palette()
        if self.palette_matches:
            self.palette_selection = (self.palette_selection + direction) % len(self.palette_matches)
            self._refresh_palette_results()
        return "break"

    def _escape_search(self, _event: tk.Event | None = None) -> str:
        self._close_command_palette()
        self.workspace.focus_set()
        return "break"

    def _dismiss_search_outside(self, event: tk.Event) -> None:
        widget = event.widget
        while widget is not None:
            if widget in (self.search_box, self.command_palette):
                return
            widget = getattr(widget, "master", None)
        self._close_command_palette()

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
        ][:6]
        self.palette_matches = matches
        self.palette_selection = min(self.palette_selection, max(0, len(matches) - 1))
        if not matches:
            tk.Label(self.palette_results, text="검색 결과가 없습니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 10)).pack(anchor="w", padx=8, pady=12)
            return
        for index, command in enumerate(matches):
            fill = colors["accent_soft"] if index == self.palette_selection else colors["panel"]
            item = tk.Frame(self.palette_results, bg=fill, highlightthickness=1, highlightbackground=colors["accent"] if index == self.palette_selection else colors["border_soft"])
            item.pack(fill="x", padx=6, pady=4)
            item.bind("<Button-1>", lambda _event, command=command: self._run_palette_command(command))
            title = tk.Label(item, text=command.title, fg=colors["text"], bg=fill, font=("Segoe UI", 10, "bold"), anchor="w")
            title.pack(fill="x", padx=12, pady=(9, 1))
            title.bind("<Button-1>", lambda _event, command=command: self._run_palette_command(command))
            subtitle = tk.Label(item, text=command.subtitle, fg=colors["muted"], bg=fill, font=("Segoe UI", 8), anchor="w")
            subtitle.pack(fill="x", padx=12, pady=(0, 9))
            subtitle.bind("<Button-1>", lambda _event, command=command: self._run_palette_command(command))

    def _run_first_palette_command(self) -> str:
        if self.command_palette is None:
            self._open_command_palette()
        if self.palette_matches:
            self._run_palette_command(self.palette_matches[self.palette_selection])
        return "break"

    def _run_palette_command(self, command: PaletteCommand) -> None:
        self._close_command_palette()
        command.action()

    def _close_command_palette(self) -> None:
        if self.command_palette and self.command_palette.winfo_exists():
            self.command_palette.destroy()
        self.command_palette = None
        self.palette_results = None
        self.palette_matches = []
        self.palette_selection = 0
        if self.palette_query is not None:
            self.palette_query.set("")


def main() -> None:
    configure_app_id()
    from app.single_instance import acquire_installed_instance
    if not acquire_installed_instance():
        messagebox.showinfo("seoul2line Toolbox", "앱이 이미 실행 중입니다.")
        return
    app = Seoul2LineToolbox()
    app.mainloop()
