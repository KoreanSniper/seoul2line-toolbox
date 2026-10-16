"""Home shortcuts and tool list."""
import tkinter as tk

from app.palette import palette
from app.theme_art import gradient_image, icon, icon_image, tool_icon
from app.tool_registry import ToolSpec


class ActionCard(tk.Canvas):
    def __init__(self, parent, colors, title, description, icon_name, command):
        super().__init__(parent, bg=colors['app'], bd=0, highlightthickness=0,
                         takefocus=True, cursor='hand2', height=144)
        self.colors, self.title, self.description = colors, title, description
        self.icon_name, self.command = icon_name, command
        self.hover = False
        self.bind('<Configure>', lambda _event: self.draw())
        self.bind('<Enter>', lambda _event: self.highlight(True))
        self.bind('<Leave>', lambda _event: self.highlight(False))
        self.bind('<FocusIn>', lambda _event: self.highlight(True))
        self.bind('<FocusOut>', lambda _event: self.highlight(False))
        self.bind('<Button-1>', lambda _event: self.invoke())
        self.bind('<Return>', self.invoke)
        self.bind('<space>', self.invoke)

    def invoke(self, _event=None):
        self.command()
        return 'break'

    def highlight(self, active):
        self.hover = active
        self.draw()

    def draw(self):
        c = self.colors
        self.delete('all')
        w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        start = c['surface_hover'] if self.hover else c['surface']
        self._background = gradient_image(self, w, h, start, start, radius=6,
                                          border=c['accent'] if self.hover else c['border_soft'])
        self.create_image(0, 0, image=self._background, anchor='nw')
        top = 20
        icon(self, self.icon_name, 18, top + 2, 23, c['muted'], width=2)
        text_x = 58
        title_font = ('Malgun Gothic', 11, 'bold')
        self.create_text(text_x, top + 2, text=self.title, anchor='nw',
                         width=max(80, w - text_x - 30), font=title_font,
                         fill=c['text'])
        self.create_text(text_x, top + 30, text=self.description, anchor='nw',
                         width=max(80, w - text_x - 24), font=('Malgun Gothic', 10),
                         fill=c['muted'])


class HomeOverview(tk.Frame):
    def __init__(self, parent, app):
        self.colors = c = palette(app.dark_mode)
        super().__init__(parent, bg=c['app'])
        self.app = app
        self.canvas = tk.Canvas(self, bg=c['app'], bd=0, highlightthickness=0, yscrollincrement=1)
        self.canvas.pack(fill='both', expand=True)
        self.scrollbar = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.cards = []
        items = [
            ('도구 검색', 'Ctrl+K', 'search', app._open_command_palette),
            ('시스템 모니터', 'CPU·메모리·디스크 사용량',
             'monitor', lambda: self.open_tool('home.system_monitor')),
            ('자동화', '워크플로 편집·실행 기록',
             'workflow', lambda: self.open_tool('automation.editor', '자동화')),
            ('설정', '테마·단축키·플러그인',
             'palette', lambda: self.open_tool('settings.preferences', '설정')),
        ]
        self.card_windows = []
        for title, description, name, action in items:
            card = ActionCard(self.canvas, c, title, description, name, action)
            self.cards.append(card)
            self.card_windows.append(self.canvas.create_window(0, 0, window=card, anchor='nw'))
            card.bind('<MouseWheel>', self.wheel)
            card.bind('<FocusIn>', lambda _event, item=self.card_windows[-1]: self.reveal(item), add='+')
        for index, card in enumerate(self.cards):
            if index < len(self.cards) - 1:
                card.bind('<Tab>', lambda _event, target=index + 1: self.focus_card(target))
            if index:
                card.bind('<Shift-Tab>', lambda _event, target=index - 1: self.focus_card(target))
        self.catalog = tk.Frame(self.canvas, bg=c['app'])
        self.catalog_window = self.canvas.create_window(0, 0, window=self.catalog, anchor='nw')
        self.catalog_sections = []
        self.tool_links = []
        for section in app.registry.sections():
            tools = [tool for tool in app.registry.tools_for(section) if tool.id != 'home.overview']
            if not tools:
                continue
            group = tk.Frame(self.catalog, bg=c['app'])
            self.catalog_sections.append(group)
            tk.Label(group, text=section, bg=c['app'], fg=c['muted'],
                     font=('Malgun Gothic', 10, 'bold'), anchor='w').pack(fill='x', pady=(0, 8))
            for tool in tools:
                button = tk.Button(group, text=tool.label, command=lambda tool=tool: app.show_tool_from_palette(tool),
                                   anchor='w', bg=c['app'], fg=c['text'], relief='flat', bd=0,
                                   activebackground=c['surface_hover'], activeforeground=c['text'],
                                   font=('Malgun Gothic', 10), padx=4, pady=6, cursor='hand2',
                                   highlightthickness=1, highlightbackground=c['app'], highlightcolor=c['accent'])
                button.tool_icon = icon_image(button, tool_icon(tool.id), c['muted'], size=18)
                button.configure(image=button.tool_icon, compound='left', padx=6)
                button.pack(fill='x')
                button.bind('<Return>', lambda _event, button=button: button.invoke())
                button.bind('<Enter>', lambda _event, button=button: button.configure(bg=c['surface_hover']))
                button.bind('<Leave>', lambda _event, button=button: button.configure(bg=c['app']))
                button.bind('<FocusIn>', lambda _event, button=button: self.reveal_link(button))
                self.tool_links.append(button)
        if self.tool_links:
            self.cards[-1].bind('<Tab>', lambda _event: self.focus_link(0))
        for index, link in enumerate(self.tool_links):
            if index < len(self.tool_links) - 1:
                link.bind('<Tab>', lambda _event, index=index: self.focus_link(index + 1))
            link.bind('<Shift-Tab>', lambda _event, index=index:
                      self.focus_link(index - 1) if index else self.focus_card(len(self.cards) - 1))
        self.catalog.bind('<Configure>', lambda _event: self.sync_scroll())
        def bind_wheel(widget):
            widget.bind('<MouseWheel>', self.wheel)
            for child in widget.winfo_children():
                bind_wheel(child)
        bind_wheel(self.catalog)
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<Configure>', self.resize)

    def reveal_link(self, button):
        y = self.canvas.coords(self.catalog_window)[1] + button.master.winfo_y() + button.winfo_y()
        self.scroll_to(y, button.winfo_height())

    def focus_link(self, index):
        self.reveal_link(self.tool_links[index])
        self.canvas.update_idletasks()
        self.tool_links[index].focus_set()
        return 'break'

    def focus_card(self, index):
        self.reveal(self.card_windows[index])
        self.canvas.update_idletasks()
        self.cards[index].focus_set()
        return 'break'

    def open_tool(self, tool_id, section=None):
        for group in self.app.registry.sections():
            for tool in self.app.registry.tools_for(group):
                if tool.id == tool_id:
                    self.app.show_tool_from_palette(tool)
                    return
        if section and section in self.app.registry.sections():
            self.app.show_section(section)
        else:
            # Disabled plugin shortcuts lead to plugin settings instead of an empty section.
            for tool in self.app.registry.tools_for('설정'):
                if tool.id == 'settings.plugins':
                    self.app.show_tool_from_palette(tool)
                    return
            self.app.show_section('설정')

    def wheel(self, event):
        if self.canvas.yview() != (0., 1.):
            self.canvas.yview_scroll(-int(event.delta / 120) * 24, 'units')
        return 'break'

    def scroll_to(self, y, height):
        top = self.canvas.canvasy(0)
        total = max(1, float(self.canvas.cget('scrollregion').split()[-1]))
        if y < top:
            self.canvas.yview_moveto(y / total)
        elif y + height > top + self.canvas.winfo_height():
            self.canvas.yview_moveto((y + height - self.canvas.winfo_height()) / total)

    def reveal(self, item):
        _x, y = self.canvas.coords(item)
        self.scroll_to(y, int(self.canvas.itemcget(item, 'height')))

    def sync_scroll(self):
        viewport = max(1, self.canvas.winfo_height())
        _x, y = self.canvas.coords(self.catalog_window)
        height = max(viewport, y + self.catalog.winfo_reqheight() + 16)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), height))
        if height > viewport:
            self.scrollbar.place(relx=1, x=-1, y=0, anchor='ne', height=viewport)
        else:
            self.scrollbar.place_forget()
            self.canvas.yview_moveto(0)

    def resize(self, event):
        c = self.colors
        width = max(2, event.width - 22)
        self.canvas.delete('decoration')
        columns = 2 if width >= 680 else 1
        padding, gap, card_height, top = 2, 12, 104, 34
        count = sum(len([tool for tool in self.app.registry.tools_for(section)
                         if tool.id != 'home.overview']) for section in self.app.registry.sections())
        self.canvas.create_text(padding, 2, text=f'{count}개 도구', font=('Malgun Gothic', 10),
                                 fill=c['muted'], anchor='nw', tags='decoration')
        card_width = (width - padding * 2 - gap * (columns - 1)) / columns
        for index, item in enumerate(self.card_windows):
            self.canvas.coords(item, padding + index % columns * (card_width + gap),
                               top + index // columns * (card_height + gap))
            self.canvas.itemconfigure(item, width=card_width, height=card_height)
        catalog_top = top + (4 // columns) * (card_height + gap) + 28
        self.canvas.coords(self.catalog_window, padding, catalog_top)
        self.canvas.itemconfigure(self.catalog_window, width=width - 24)
        groups = max(1, min(3, width // 280))
        for column in range(3):
            self.catalog.columnconfigure(column, weight=1 if column < groups else 0, uniform='groups')
        for index, group in enumerate(self.catalog_sections):
            group.grid(row=index // groups, column=index % groups, sticky='new', padx=(0, 20), pady=(0, 24))
        link_width = max(100, (width - 24) // groups - 30)
        for link in self.tool_links:
            link.configure(wraplength=link_width)
        self.sync_scroll()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return HomeOverview(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec('home.overview', '개요', '홈', build, 0))
