from __future__ import annotations

import tkinter as tk
import time

from PIL import Image, ImageTk

from app.games.sandbox.model import MATERIALS, Sandbox
from app.palette import palette
from app.paths import data_directory
from app.ui import RoundedButton, styled_scrollbar


class SandboxView(tk.Frame):
    def __init__(self, parent, app):
        self.colors = c = palette(app.dark_mode)
        super().__init__(parent, bg=c["panel"])
        self.world = Sandbox()
        self.world.demo()
        self.paused = False
        self.tick_id = None
        self.selected = "sand"
        self.last_point = None
        self.pointer = None
        self.offset = (0, 0)
        self.scale = 1
        self.photo = None
        self.save_path = data_directory() / "sandbox" / "scene.json"
        self.brush_size = tk.IntVar(value=3)
        self.speed = tk.StringVar(value="1")
        self.status = tk.StringVar()
        self.material_label = tk.StringVar()
        self.message = "물과 모래 예제 · 왼쪽에서 재료를 골라 그려 보세요."
        self.buttons = {}
        header = tk.Frame(self, bg=c["panel"])
        header.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(header, text="Sandbox", bg=c["panel"], fg=c["text"],
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(header, text="입자 실험실", bg=c["panel"], fg=c["muted"]).pack(side="left", padx=12)
        controls = tk.Frame(self, bg=c["panel"])
        controls.pack(fill="x", padx=14, pady=4)
        for column, (label, command) in enumerate((
                ("일시정지/계속", self.toggle_pause), ("한 단계", self.single_step),
                ("예제", self.demo), ("모두 지우기", self.clear),
                ("저장", self.save), ("불러오기", self.load))):
            RoundedButton(controls, label, command, c, compact=True).grid(
                row=column // 3, column=column % 3, sticky="ew", padx=2, pady=2)
        for column in range(3):
            controls.columnconfigure(column, weight=1)
        body = tk.Frame(self, bg=c["panel"])
        body.pack(fill="both", expand=True, padx=14, pady=6)
        sidebar = tk.Frame(body, bg=c["panel_soft"], width=156)
        sidebar.pack(side="left", fill="y", padx=(0, 8))
        side_canvas = tk.Canvas(sidebar, width=145, bg=c["panel_soft"], highlightthickness=0)
        self.side_canvas = side_canvas
        scroll = styled_scrollbar(sidebar, "vertical", side_canvas.yview, c)
        scroll.pack(side="right", fill="y")
        side_canvas.pack(side="left", fill="both", expand=True)
        side_canvas.configure(yscrollcommand=scroll.set)
        panel = tk.Frame(side_canvas, bg=c["panel_soft"])
        window = side_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _: side_canvas.configure(scrollregion=side_canvas.bbox("all")))
        side_canvas.bind("<Configure>", lambda e: side_canvas.itemconfigure(window, width=e.width))
        tk.Label(panel, textvariable=self.material_label, bg=c["panel_soft"], fg=c["text"],
                 anchor="w").pack(fill="x", padx=6, pady=6)
        tk.Scale(panel, from_=1, to=12, orient="horizontal", variable=self.brush_size,
                 label="브러시 크기", bg=c["panel_soft"], fg=c["text"], troughcolor=c["field"],
                 highlightthickness=0).pack(fill="x", padx=4)
        speed = tk.OptionMenu(panel, self.speed, "1", "2", "4")
        speed.configure(bg=c["field"], fg=c["text"], highlightthickness=0)
        tk.Label(panel, text="단계 배속", bg=c["panel_soft"], fg=c["muted"]).pack()
        speed.pack(fill="x", padx=4, pady=(0, 8))
        choices = [(key, value[0], value[1]) for key, value in MATERIALS.items()]
        choices += [("heat", "가열 +100°C", "#ff793c"), ("cool", "냉각 −100°C", "#88e4f2")]
        for key, name, color in choices:
            row = tk.Frame(panel, bg=c["panel_soft"])
            row.pack(fill="x", padx=4, pady=1)
            tk.Label(row, text="●", fg=color, bg=c["panel_soft"]).pack(side="left")
            button = tk.Button(row, text=name, anchor="w", relief="flat", bd=0,
                               bg=c["field"], fg=c["text"], activebackground=c["accent_soft"],
                               activeforeground=c["text"], command=lambda key=key: self.select(key))
            button.pack(side="left", fill="x", expand=True)
            self.buttons[key] = button
            button.bind("<Up>", lambda _, key=key: self.cycle_material(key, -1))
            button.bind("<Down>", lambda _, key=key: self.cycle_material(key, 1))
        self.bind_sidebar_wheel(panel)
        side_canvas.bind("<MouseWheel>", self.scroll_materials)
        self.canvas = tk.Canvas(body, bg=MATERIALS["empty"][1], highlightthickness=0, takefocus=True)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.image_id = self.canvas.create_image(0, 0, anchor="nw")
        self.cursor_id = self.canvas.create_oval(0, 0, 0, 0, outline="#ffffff", state="hidden")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Button-1>", self.paint)
        self.canvas.bind("<B1-Motion>", self.paint)
        self.canvas.bind("<Button-3>", lambda e: self.paint(e, erase=True))
        self.canvas.bind("<B3-Motion>", lambda e: self.paint(e, erase=True))
        for event in ("<ButtonRelease-1>", "<ButtonRelease-3>", "<FocusOut>"):
            self.canvas.bind(event, lambda _: setattr(self, "last_point", None))
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Leave>", self.leave)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<KeyPress-space>", lambda _: self.toggle_pause())
        self.canvas.bind("<KeyPress-n>", lambda _: self.single_step())
        help_text = ("좌클릭·드래그: 그리기 / 우클릭: 지우기 / 휠: 크기 / Space: 정지 / N: 한 단계\n"
                     "기름·나무 + 불 → 연소 · 물 + 용암 → 돌·증기 · 화약 + 불 → 폭발 · 전기 + 금속 → 전도")
        self.help_label = tk.Label(self, text=help_text, bg=c["panel"], fg=c["muted"],
                                   justify="left", anchor="w", wraplength=700)
        self.help_label.pack(fill="x", padx=14)
        self.status_label = tk.Label(self, textvariable=self.status, bg=c["panel"], fg=c["text"],
                                    justify="left", anchor="w", wraplength=700)
        self.status_label.pack(fill="x", padx=14, pady=(4, 8))
        self.bind("<Configure>", self.resize)
        self.bind("<Destroy>", self.close, add="+")
        self.select("sand")
        self.draw()
        self.tick_id = self.after(33, self.tick)

    def resize(self, event):
        if event.widget is self:
            for label in (self.help_label, self.status_label):
                label.configure(wraplength=max(180, event.width - 28))

    def select(self, material):
        self.selected = material
        self.material_label.set("선택: " + (MATERIALS[material][0] if material in MATERIALS else "가열" if material == "heat" else "냉각"))
        for key, button in self.buttons.items():
            button.configure(bg=self.colors["accent_soft"] if key == material else self.colors["field"],
                             relief="sunken" if key == material else "flat")

    def bind_sidebar_wheel(self, widget):
        widget.bind("<MouseWheel>", self.scroll_materials)
        for child in widget.winfo_children():
            self.bind_sidebar_wheel(child)

    def scroll_materials(self, event):
        self.side_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def cycle_material(self, current, direction):
        keys = list(self.buttons)
        key = keys[(keys.index(current) + direction) % len(keys)]
        self.select(key)
        self.buttons[key].focus_set()
        # 선택한 버튼이 스크롤 영역 밖이면 해당 행을 표시한다.
        button = self.buttons[key]
        top = button.master.winfo_y()
        panel_height = max(1, button.master.master.winfo_height())
        low, high = self.side_canvas.yview()
        if top / panel_height < low or (top + button.winfo_height()) / panel_height > high:
            self.side_canvas.yview_moveto(max(0, (top - 8) / panel_height))
        return "break"

    def position(self, event):
        x = int((event.x - self.offset[0]) // self.scale)
        y = int((event.y - self.offset[1]) // self.scale)
        return (x, y) if 0 <= x < self.world.width and 0 <= y < self.world.height else None

    def paint(self, event, erase=False):
        self.canvas.focus_set()
        point = self.position(event)
        if point is None:
            self.last_point = None
            return
        x, y = point
        start = self.last_point or point
        distance = max(abs(x - start[0]), abs(y - start[1]), 1)
        for step in range(distance + 1):
            xx = round(start[0] + (x - start[0]) * step / distance)
            yy = round(start[1] + (y - start[1]) * step / distance)
            self.world.brush(xx, yy, self.brush_size.get(), "empty" if erase else self.selected)
        self.last_point = point
        self.pointer = point
        self.draw()

    def hover(self, event):
        self.pointer = self.position(event)
        self.update_status()
        self.draw_cursor()

    def leave(self, _event):
        self.pointer = self.last_point = None
        self.canvas.itemconfigure(self.cursor_id, state="hidden")

    def wheel(self, event):
        self.brush_size.set(max(1, min(12, self.brush_size.get() + (1 if event.delta > 0 else -1))))
        self.draw_cursor()
        return "break"

    def toggle_pause(self):
        self.paused = not self.paused
        self.update_status()
        return "break"

    def single_step(self):
        self.paused = True
        self.world.step()
        self.draw()
        return "break"

    def clear(self):
        self.world.clear()
        self.message = "캔버스를 비웠습니다."
        self.draw()

    def demo(self):
        self.world.demo()
        self.message = "물과 모래 예제를 불러왔습니다."
        self.draw()

    def save(self):
        try:
            self.world.save(self.save_path)
            self.message = "현재 장면을 저장했습니다."
        except (OSError, ValueError) as error:
            self.message = f"저장 실패: {error}"
        self.update_status()

    def load(self):
        try:
            world = Sandbox.load(self.save_path)
        except (OSError, ValueError, TypeError, OverflowError) as error:
            self.message = f"불러오기 실패: {error}"
        else:
            self.world = world
            self.pointer = self.last_point = None
            self.paused = True
            self.message = "저장한 장면을 불러왔습니다. 계속 버튼으로 시작하세요."
        self.draw()

    def tick(self):
        self.tick_id = None
        if self.winfo_ismapped():
            if not self.paused:
                start = time.perf_counter()
                for _ in range(int(self.speed.get())):
                    self.world.step()
                    if time.perf_counter() - start >= .025:
                        break
            self.draw()
        self.tick_id = self.after(33, self.tick)

    def draw_cursor(self):
        if self.pointer is None:
            self.canvas.itemconfigure(self.cursor_id, state="hidden")
            return
        x, y = self.pointer
        x = self.offset[0] + (x + .5) * self.scale
        y = self.offset[1] + (y + .5) * self.scale
        r = (self.brush_size.get() + .5) * self.scale
        self.canvas.coords(self.cursor_id, x - r, y - r, x + r, y + r)
        self.canvas.itemconfigure(self.cursor_id, state="normal")

    def draw(self):
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.scale = min(width / self.world.width, height / self.world.height)
        size = (max(1, int(self.world.width * self.scale)), max(1, int(self.world.height * self.scale)))
        self.offset = ((width - size[0]) // 2, (height - size[1]) // 2)
        colors = {key: bytes.fromhex(value[1][1:]) for key, value in MATERIALS.items()}
        raw = b"".join(colors[m] for m in self.world.cells)
        image = Image.frombytes("RGB", (self.world.width, self.world.height), raw)
        image = image.resize(size, Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(image, master=self.canvas)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        self.canvas.coords(self.image_id, *self.offset)
        self.draw_cursor()
        self.update_status()

    def update_status(self):
        count = len(self.world.cells) - self.world.cells.count("empty")
        info = f"{'일시정지' if self.paused else '실행 중'} · 입자 {count:,} · {self.world.ticks:,} 단계"
        if self.pointer is not None:
            x, y = self.pointer
            i = y * self.world.width + x
            info += f" · ({x}, {y}) {MATERIALS[self.world.cells[i]][0]} {self.world.heat[i]:.0f}°C"
        self.status.set(info + "\n" + self.message)

    def close(self, event):
        if event.widget is self:
            if self.tick_id is not None:
                self.after_cancel(self.tick_id)
                self.tick_id = None
            # Tk 객체는 종료 뒤 작업 스레드의 GC에서 정리되지 않게
            # 소유한 UI 스레드에서 마지막 참조를 해제한다.
            self.photo = None
            self.brush_size = self.speed = self.status = self.material_label = None
