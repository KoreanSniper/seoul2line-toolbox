from __future__ import annotations

import math
import random
import tkinter as tk
import time

from app.games.orbit_lab.model import BODY_COLORS, TIME_SCALES, OrbitSystem, SpaceCamera
from app.palette import palette
from app.ui import RoundedButton, styled_scrollbar


class OrbitLabView(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        colors = palette(app.dark_mode)
        super().__init__(parent, bg=colors["panel"])
        self.camera = SpaceCamera()
        self.system = OrbitSystem()
        self.placement: str | None = None
        self.last_tick = time.perf_counter()
        self.tick_id: str | None = None
        self.pan_anchor: tuple[int, int] | None = None
        rng = random.Random(7)
        self.stars = [(rng.uniform(-3000, 3000), rng.uniform(-2400, 2400), rng.choice((1, 1, 2))) for _ in range(1600)]
        header = tk.Frame(self, bg=colors["panel"])
        header.pack(fill="x", padx=14, pady=10)
        tk.Label(header, text="Orbit Lab", font=("Segoe UI", 20, "bold"), bg=colors["panel"], fg=colors["text"]).pack(side="left")
        RoundedButton(header, "카메라 원점", self.reset_camera, colors, compact=True).pack(side="right")
        controls = tk.Frame(self, bg=colors["panel"])
        controls.pack(fill="x", padx=14, pady=(0, 6))
        RoundedButton(controls, "일시정지/계속", self.toggle_pause, colors, compact=True).pack(side="left")
        RoundedButton(controls, "한 단계", self.single_step, colors, compact=True).pack(side="left", padx=8)
        self.speed_choice = tk.StringVar(value="1")
        menu = tk.OptionMenu(controls, self.speed_choice, *(f"{rate:g}" for rate in TIME_SCALES), command=self.change_speed)
        menu.configure(bg=colors["field"], fg=colors["text"], relief="flat", highlightthickness=0)
        menu.pack(side="left")
        tk.Label(controls, text="배속", bg=colors["panel"], fg=colors["muted"]).pack(side="left", padx=6)
        self.status = tk.StringVar()
        self.status_label = tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["muted"], anchor="w", justify="left", wraplength=640)
        self.status_label.pack(fill="x", padx=14)
        self.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 28)) if event.widget is self else None)
        body = tk.Frame(self, bg=colors["panel"])
        body.pack(fill="both", expand=True, padx=14, pady=8)
        self.canvas = tk.Canvas(body, bg="#0b1222", highlightthickness=0, takefocus=True)
        self.canvas.pack(side="left", fill="both", expand=True)
        sidebar = tk.Frame(body, bg=colors["panel_soft"])
        sidebar.pack(side="right", fill="y", padx=(10, 0))
        side_canvas = tk.Canvas(sidebar, width=220, bg=colors["panel_soft"], highlightthickness=0)
        scroll = styled_scrollbar(sidebar, "vertical", side_canvas.yview, colors)
        scroll.pack(side="right", fill="y")
        side_canvas.pack(side="left", fill="both", expand=True)
        side_canvas.configure(yscrollcommand=scroll.set)
        panel = tk.Frame(side_canvas, bg=colors["panel_soft"])
        window = side_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _event: side_canvas.configure(scrollregion=side_canvas.bbox("all")))
        side_canvas.bind("<Configure>", lambda event: side_canvas.itemconfigure(window, width=event.width))
        self.body_list = tk.Listbox(panel, height=5, width=25, bg=colors["field"], fg=colors["text"], exportselection=False)
        self.body_list.pack(fill="x", padx=8, pady=8)
        self.body_list.bind("<<ListboxSelect>>", self.list_select)
        self.body_name = tk.StringVar(value="행성")
        self.mass = tk.StringVar(value="12000")
        self.radius = tk.StringVar(value="30")
        for title, variable in (("이름", self.body_name), ("질량", self.mass), ("반지름", self.radius)):
            tk.Label(panel, text=title, bg=colors["panel_soft"], fg=colors["muted"], anchor="w").pack(fill="x", padx=8)
            tk.Entry(panel, textvariable=variable, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"]).pack(fill="x", padx=8, pady=(0, 6))
        for label, command in (("행성 배치", lambda: self.start_placement("planet")),
                               ("선택 천체의 위성 배치", lambda: self.start_placement("moon")),
                               ("선택 천체 질량 적용", self.apply_mass), ("선택 천체 삭제", self.remove_body)):
            RoundedButton(panel, label, command, colors, compact=True).pack(fill="x", padx=8, pady=3)
        self.body_info = tk.StringVar()
        tk.Label(panel, textvariable=self.body_info, bg=colors["panel_soft"], fg=colors["muted"],
                 justify="left", wraplength=200, anchor="nw").pack(fill="x", padx=8, pady=10)
        self.launch_speed = tk.StringVar(value="24")
        self.heading = tk.StringVar(value="90")
        for title, variable in (("발사 속도", self.launch_speed), ("방향: 0° 오른쪽 / 90° 위", self.heading)):
            tk.Label(panel, text=title, bg=colors["panel_soft"], fg=colors["muted"], anchor="w").pack(fill="x", padx=8)
            tk.Entry(panel, textvariable=variable, bg=colors["field"], fg=colors["text"], insertbackground=colors["text"]).pack(fill="x", padx=8, pady=(0, 6))
        RoundedButton(panel, "선택 천체에서 발사", self.launch, colors, compact=True).pack(fill="x", padx=8, pady=4)
        rotate_row = tk.Frame(panel, bg=colors["panel_soft"])
        rotate_row.pack(fill="x", padx=8)
        RoundedButton(rotate_row, "Q ↶ 5°", lambda: self.rotate(5), colors, compact=True).pack(side="left", fill="x", expand=True)
        RoundedButton(rotate_row, "E ↷ 5°", lambda: self.rotate(-5), colors, compact=True).pack(side="left", fill="x", expand=True)
        self.throttle = tk.DoubleVar(value=0)
        tk.Scale(panel, from_=0, to=100, orient="horizontal", variable=self.throttle, command=self.throttle_changed,
                 label="우주선 추력 (%)", bg=colors["panel_soft"], fg=colors["text"], highlightthickness=0).pack(fill="x", padx=8, pady=8)
        tk.Label(self, text="좌클릭: 천체 선택/배치 · 우클릭/Esc: 배치 취소 · 가운데 드래그/WASD: 이동 · 휠: 확대·축소",
                 bg=colors["panel"], fg=colors["muted"], anchor="w").pack(fill="x", padx=14, pady=(0, 8))
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Button-3>", self.cancel_placement)
        self.canvas.bind("<ButtonPress-2>", self.pan_start)
        self.canvas.bind("<B2-Motion>", self.pan_move)
        self.canvas.bind("<ButtonRelease-2>", lambda _event: setattr(self, "pan_anchor", None))
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<KeyPress>", self.key)
        self.bind("<Destroy>", self.close, add="+")
        self.draw()
        self.tick_id = self.after(33, self.tick)

    def close(self, event: tk.Event) -> None:
        if event.widget is self and self.tick_id is not None:
            self.after_cancel(self.tick_id)
            self.tick_id = None

    def tick(self) -> None:
        now = time.perf_counter()
        if self.winfo_ismapped():
            self.system.advance_real_time(now - self.last_tick)
            self.draw()
        self.last_tick = now
        self.tick_id = self.after(33, self.tick)

    def toggle_pause(self) -> None:
        self.system.paused = not self.system.paused
        self.last_tick = time.perf_counter()
        self.draw()

    def change_speed(self, _value=None) -> None:
        self.system.set_time_scale(float(self.speed_choice.get()))
        self.draw()

    def single_step(self) -> None:
        self.system.single_step()
        self.draw()

    def start_placement(self, kind: str) -> None:
        if kind == "moon" and self.system.selected is None:
            self.system.notice = "중심이 될 천체를 먼저 선택하세요."
        else:
            self.placement = kind
            self.body_name.set("행성" if kind == "planet" else "위성")
            self.mass.set("12000" if kind == "planet" else "12")
            self.radius.set("30" if kind == "planet" else "8")
            self.system.notice = "질량·반지름을 입력한 뒤 우주 공간을 클릭하세요."
        self.draw()

    def cancel_placement(self, _event=None) -> None:
        self.placement = None
        self.system.notice = "배치를 취소했습니다."
        self.draw()

    def click(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        x, y = self.camera.to_world(event.x, event.y)
        if self.placement:
            try:
                args = (self.body_name.get(), float(self.mass.get()), float(self.radius.get()), x, y)
                if self.placement == "moon":
                    self.system.add_moon(self.system.selected_id, *args)
                else:
                    self.system.add_body("planet", *args)
            except (ValueError, OverflowError) as exc:
                self.system.notice = str(exc)
            else:
                self.system.notice = "천체를 추가했습니다. 위성에는 원 궤도 초기 속도가 적용됩니다."
                self.placement = None
        else:
            selected = self.system.body_at(x, y, 6 / self.camera.zoom)
            self.system.selected_id = selected.id if selected else None
            self.sync_fields()
        self.draw()

    def sync_fields(self) -> None:
        body = self.system.selected
        if body:
            self.body_name.set(body.name)
            self.mass.set(f"{body.mass:g}")
            self.radius.set(f"{body.radius:g}")
            if body.kind == "ship":
                self.heading.set(f"{body.heading:g}")
                self.throttle.set(body.throttle * 100)

    def launch(self) -> None:
        try:
            self.system.launch_ship(self.system.selected_id, float(self.launch_speed.get()), float(self.heading.get()))
            self.sync_fields()
        except (ValueError, OverflowError) as exc:
            self.system.notice = str(exc)
        self.draw()

    def rotate(self, delta: float) -> None:
        try:
            self.system.rotate_ship(delta)
            self.heading.set(f"{self.system.selected.heading:g}")
        except ValueError as exc:
            self.system.notice = str(exc)
        self.draw()

    def throttle_changed(self, _value=None) -> None:
        if self.system.selected is not None and self.system.selected.kind == "ship":
            self.system.set_throttle(self.throttle.get() / 100)
            self.draw()

    def list_select(self, _event=None) -> None:
        selection = self.body_list.curselection()
        if selection:
            self.system.selected_id = self.system.bodies[selection[0]].id
            self.sync_fields()
            self.draw()

    def apply_mass(self) -> None:
        try:
            self.system.set_mass(self.system.selected_id, float(self.mass.get()))
            self.system.notice = "질량을 적용했습니다. 기존 속도는 유지됩니다."
        except (ValueError, OverflowError) as exc:
            self.system.notice = str(exc)
        self.draw()

    def remove_body(self) -> None:
        try:
            self.system.remove_selected()
            self.system.notice = "천체를 삭제했습니다."
        except ValueError as exc:
            self.system.notice = str(exc)
        self.draw()

    def reset_camera(self) -> None:
        self.camera.x = self.camera.y = 0
        self.camera.zoom = 1
        self.draw()

    def resize(self, event: tk.Event) -> None:
        self.camera.resize(event.width, event.height)
        self.draw()

    def pan_start(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        self.pan_anchor = event.x, event.y

    def pan_move(self, event: tk.Event) -> None:
        if self.pan_anchor is not None:
            x, y = self.pan_anchor
            self.camera.pan(x - event.x, y - event.y)
            self.pan_anchor = event.x, event.y
            self.draw()

    def wheel(self, event: tk.Event) -> str:
        self.camera.zoom_at(1.2 if event.delta > 0 else 1 / 1.2, event.x, event.y)
        self.draw()
        return "break"

    def key(self, event: tk.Event) -> str | None:
        if event.keysym.lower() in ("q", "e"):
            self.rotate(5 if event.keysym.lower() == "q" else -5)
            return "break"
        if event.keysym == "space":
            self.toggle_pause()
            return "break"
        if event.keysym == "Escape":
            self.cancel_placement()
            return "break"
        movement = {"w": (0, -48), "Up": (0, -48), "s": (0, 48), "Down": (0, 48),
                    "a": (-48, 0), "Left": (-48, 0), "d": (48, 0), "Right": (48, 0)}.get(event.keysym)
        if movement:
            self.camera.pan(*movement)
            self.draw()
            return "break"
        return None

    def draw(self) -> None:
        self.canvas.delete("all")
        width, height = self.camera.width, self.camera.height
        for x, y, size in self.stars:
            sx, sy = self.camera.to_screen(x, y)
            if 0 <= sx <= width and 0 <= sy <= height:
                self.canvas.create_oval(sx, sy, sx + size, sy + size, fill="#8fa6c7", outline="")
        # Choose grid spacing that remains readable at every scale.
        spacing = 10 ** math.ceil(math.log10(70 / self.camera.zoom))
        left, top = self.camera.to_world(0, 0)
        right, bottom = self.camera.to_world(width, height)
        for col in range(math.floor(left / spacing), math.ceil(right / spacing) + 1):
            sx, _ = self.camera.to_screen(col * spacing, 0)
            self.canvas.create_line(sx, 0, sx, height, fill="#152338")
        for row in range(math.floor(top / spacing), math.ceil(bottom / spacing) + 1):
            _, sy = self.camera.to_screen(0, row * spacing)
            self.canvas.create_line(0, sy, width, sy, fill="#152338")
        ox, oy = self.camera.to_screen(0, 0)
        self.canvas.create_line(ox - 8, oy, ox + 8, oy, fill="#5077a7")
        self.canvas.create_line(ox, oy - 8, ox, oy + 8, fill="#5077a7")
        self.canvas.create_line(16, height - 20, 16 + spacing * self.camera.zoom, height - 20, fill="#d4e5f5", width=2)
        self.canvas.create_text(16, height - 28, text=f"거리 {spacing:g}", fill="#d4e5f5", anchor="sw")
        for body in self.system.bodies:
            sx, sy = self.camera.to_screen(body.x, body.y)
            radius = max(3, body.radius * self.camera.zoom)
            self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius,
                                    fill=BODY_COLORS[body.kind], outline="#f8df8a" if body.id == self.system.selected_id else "#324761", width=2)
            self.canvas.create_text(sx, sy + radius + 12, text=body.name, fill="#e5edf9", font=("Segoe UI", 9))
            if body.kind == "ship":
                angle = math.radians(body.heading)
                dx, dy = math.cos(angle), -math.sin(angle)
                self.canvas.create_line(sx, sy, sx + dx * (radius + 16), sy + dy * (radius + 16), fill="#fff4b4", arrow="last")
                if body.throttle > 0 and body.fuel > 0:
                    self.canvas.create_line(sx - dx * radius, sy - dy * radius,
                                            sx - dx * (radius + 24 * body.throttle), sy - dy * (radius + 24 * body.throttle), fill="#ff995d", width=3)
        entries = [f"{body.id}. {body.name} · M {body.mass:g}" for body in self.system.bodies]
        if tuple(entries) != self.body_list.get(0, "end"):
            self.body_list.delete(0, "end")
            for entry in entries:
                self.body_list.insert("end", entry)
        self.body_list.selection_clear(0, "end")
        for index, body in enumerate(self.system.bodies):
            if body.id == self.system.selected_id:
                self.body_list.selection_set(index)
        selected = self.system.selected
        self.body_info.set(f"{selected.name}\n질량 {selected.mass:g}\n반지름 {selected.radius:g}\n위치 ({selected.x:.1f}, {selected.y:.1f})"
                           if selected else "선택한 천체가 없습니다.")
        if selected and selected.kind == "ship":
            self.body_info.set(self.body_info.get() + f"\n연료 {selected.fuel:.1f}\n방향 {selected.heading:.0f}° · 추력 {selected.throttle:.0%}")
        state = "일시정지" if self.system.paused else f"{self.system.time_scale:g}배속"
        if self.system.physics_limited and not self.system.paused:
            state += f" (연산량 제한 · 실제 {self.system.effective_speed:.1f}배)"
        self.status.set(f"시간 {self.system.elapsed:.1f} · {state} · 확대 {self.camera.zoom:.0%} · {self.system.notice}")
