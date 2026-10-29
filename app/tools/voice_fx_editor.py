"""Reusable, themed ordered-chain and shared-preset editor (Tk UI thread only)."""
from copy import deepcopy
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from app.services.voice_fx import EFFECTS, builtin_presets, default_settings, validate_settings
from app.services.voice_fx_store import PresetStore
from app.ui import RoundedButton, styled_scrollbar


class VoiceFXEditor(tk.Frame):
    def __init__(self, parent, colors, status, store=None):
        super().__init__(parent, bg=colors["panel"])
        self.colors, self.status = colors, status
        self.store = store or PresetStore()
        self.settings = default_settings()
        self.selected_id = None
        self.save_timer = None
        self.variables = []
        self.expanded = {"pitch", "speed", "formant"}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        self.enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="음성 변조 활성화", variable=self.enabled, command=self.change_enabled,
                       bg=colors["panel"], fg=colors["text"], selectcolor=colors["field"], activebackground=colors["panel"], activeforeground=colors["text"]).grid(row=0, column=0, sticky="w")
        preset_row = tk.Frame(self, bg=colors["panel"])
        preset_row.grid(row=1, column=0, sticky="ew", pady=5)
        preset_row.columnconfigure(1, weight=1)
        self.label(preset_row, "프리셋").grid(row=0, column=0, padx=(0, 10))
        self.preset = ttk.Combobox(preset_row, state="readonly", width=18)
        self.preset.grid(row=0, column=1, sticky="ew")
        self.preset.bind("<<ComboboxSelected>>", self.select_preset)
        self.button(preset_row, "초기화", self.reset).grid(row=0, column=2, padx=(8, 0))
        self.manage_open = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="사용자 프리셋 관리 ▾", variable=self.manage_open, command=self.toggle_manager,
                       bg=colors["panel"], fg=colors["text"], selectcolor=colors["field"], activebackground=colors["panel"], activeforeground=colors["text"]).grid(row=2, column=0, sticky="w")
        self.manager = tk.Frame(self, bg=colors["panel"])
        operations = [("새로 저장", self.save_new), ("선택 덮어쓰기", self.update_selected), ("이름 변경", self.rename_selected),
                      ("복제", self.save_new), ("삭제", self.delete_selected), ("가져오기", self.import_presets), ("내보내기", self.export_preset)]
        for index, (label, action) in enumerate(operations):
            self.manager.columnconfigure(index % 3, weight=1)
            self.button(self.manager, label, action).grid(row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
        wrap = tk.Frame(self, bg=colors["panel"])
        wrap.grid(row=4, column=0, sticky="nsew", pady=(5, 0))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, bg=colors["panel"], highlightthickness=0, height=220)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = styled_scrollbar(wrap, "vertical", self.canvas.yview, colors)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)
        self.body = tk.Frame(self.canvas, bg=colors["panel"])
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=max(1, e.width)))
        self.refresh_presets()
        try:
            current = self.store.current()
            self.load(current or default_settings())
        except (OSError, ValueError) as exc:
            self.load(default_settings())
            self.status.set(str(exc))

    def label(self, parent, text):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.colors["text"], anchor="w")

    def button(self, parent, text, command):
        button = RoundedButton(parent, text, command, self.colors, compact=True)
        button.configure(width=max(54, len(text) * 15 + 16))
        return button

    def wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self.wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def refresh_presets(self):
        try:
            self.presets = self.store.all()
        except (OSError, ValueError) as exc:
            self.presets = builtin_presets()
            self.status.set(str(exc))
        self.preset.configure(values=[p["name"] for p in self.presets] + ["사용자 정의"])

    def snapshot(self):
        return validate_settings(deepcopy(self.settings))

    def load(self, settings, identity=None):
        self.settings = validate_settings(deepcopy(settings))
        # Imported partial chains gain disabled controls; their original order stays intact.
        present = {n["id"] for n in self.settings["chain"]}
        self.settings["chain"] += [n for n in default_settings()["chain"] if n["id"] not in present]
        self.enabled.set(self.settings["enabled"])
        self.selected_id = identity
        matching = next((p for p in self.presets if p["settings"] == self.settings), None)
        self.preset.set(matching["name"] if matching else "사용자 정의")
        if matching and identity is None:
            self.selected_id = matching["id"]
        self.render_chain()

    def render_chain(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.variables.clear()
        for index, node in enumerate(self.settings["chain"]):
            key = node["id"]
            panel = tk.Frame(self.body, bg=self.colors["surface"], padx=8, pady=5)
            panel.pack(fill="x", pady=3)
            panel.columnconfigure(0, weight=1)
            head = tk.Frame(panel, bg=self.colors["surface"])
            head.grid(row=0, column=0, sticky="ew")
            head.columnconfigure(1, weight=1)
            active = tk.BooleanVar(value=node["enabled"])
            self.variables.append(active)
            tk.Checkbutton(head, variable=active, command=lambda n=node, v=active: self.toggle_node(n, v),
                bg=self.colors["surface"], selectcolor=self.colors["field"], activebackground=self.colors["surface"]).grid(row=0, column=0)
            self.button(head, ("▾ " if key in self.expanded else "▸ ") + EFFECTS[key][0], lambda k=key: self.expand(k)).grid(row=0, column=1, sticky="w")
            self.button(head, "↑", lambda i=index: self.move(i, -1)).grid(row=0, column=2, padx=2)
            self.button(head, "↓", lambda i=index: self.move(i, 1)).grid(row=0, column=3)
            if key in self.expanded:
                details = tk.Frame(panel, bg=self.colors["surface"])
                details.grid(row=1, column=0, sticky="ew")
                details.columnconfigure(1, weight=1)
                for row, (name, (label, low, high, _, step)) in enumerate(EFFECTS[key][1].items()):
                    self.label(details, label).grid(row=row, column=0, sticky="w", padx=(0, 8))
                    value = tk.DoubleVar(value=node["params"][name])
                    self.variables.append(value)
                    tk.Scale(details, variable=value, from_=low, to=high, resolution=step, orient="horizontal",
                        bg=self.colors["surface"], fg=self.colors["text"], troughcolor=self.colors["field"], highlightthickness=0,
                        length=140).grid(row=row, column=1, sticky="ew")
                    value.trace_add("write", lambda *_, n=node, p=name, v=value: self.parameter(n, p, v))
        self.bind_wheel(self.body)
        self.bind_wheel(self.canvas)

    def expand(self, key):
        if key in self.expanded:
            self.expanded.remove(key)
        else:
            self.expanded.add(key)
        self.render_chain()

    def change_enabled(self):
        self.settings["enabled"] = self.enabled.get()
        self.changed()

    def toggle_node(self, node, value):
        node["enabled"] = value.get()
        self.changed()

    def parameter(self, node, name, variable):
        value = variable.get()
        if value != node["params"][name]:
            node["params"][name] = value
            self.changed()

    def move(self, index, direction):
        chain = self.settings["chain"]
        other = index + direction
        if 0 <= other < len(chain):
            chain[index], chain[other] = chain[other], chain[index]
            self.changed()
            self.render_chain()

    def changed(self):
        self.preset.set("사용자 정의 · 수정됨")
        if self.save_timer is not None:
            self.after_cancel(self.save_timer)
        self.save_timer = self.after(500, self.persist)

    def persist(self):
        self.save_timer = None
        try:
            self.store.save_current(self.snapshot())
        except (OSError, ValueError) as exc:
            self.status.set("변조 설정 저장 실패: " + str(exc))

    def select_preset(self, _event=None):
        index = self.preset.current()
        if 0 <= index < len(self.presets):
            record = self.presets[index]
            self.load(record["settings"], record["id"])
            self.persist()
        elif index == len(self.presets):
            self.selected_id = None

    def reset(self):
        self.load(default_settings(), "builtin-original")
        self.persist()

    def toggle_manager(self):
        if self.manage_open.get():
            self.manager.grid(row=3, column=0, sticky="ew")
        else:
            self.manager.grid_remove()

    def perform(self, operation):
        try:
            result = operation()
            self.refresh_presets()
            if isinstance(result, dict):
                self.load(result["settings"], result["id"])
            self.status.set("프리셋 처리 완료")
        except (OSError, ValueError) as exc:
            self.status.set("프리셋 처리 실패: " + str(exc))

    def save_new(self):
        name = simpledialog.askstring("프리셋 저장 / 복제", "새 프리셋 이름 (1~60자)", parent=self)
        if name is not None:
            self.perform(lambda: self.store.save(name, self.snapshot()))

    def selected_user(self):
        if not self.selected_id or self.selected_id.startswith("builtin-"):
            raise ValueError("사용자 프리셋을 먼저 선택하세요. 기본 프리셋은 새로 저장·복제할 수 있습니다.")
        record = next((p for p in self.store.users() if p["id"] == self.selected_id), None)
        if record is None:
            raise ValueError("선택한 사용자 프리셋이 없습니다. 목록을 다시 불러오세요.")
        return record

    def update_selected(self):
        def update():
            record = self.selected_user()
            return self.store.save(record["name"], self.snapshot(), record["id"])
        self.perform(update)

    def rename_selected(self):
        def rename():
            record = self.selected_user()
            name = simpledialog.askstring("이름 변경", "새 프리셋 이름", initialvalue=record["name"], parent=self)
            return self.store.save(name, record["settings"], record["id"]) if name is not None else None
        self.perform(rename)

    def delete_selected(self):
        def delete():
            record = self.selected_user()
            self.store.delete(record["id"])
            self.selected_id = None
            self.preset.set("사용자 정의")
        self.perform(delete)

    def import_presets(self):
        path = filedialog.askopenfilename(parent=self, title="프리셋 가져오기", filetypes=[("Voice FX JSON", "*.json")])
        if path:
            self.perform(lambda: self.store.import_file(path)[0])

    def export_preset(self):
        path = filedialog.asksaveasfilename(parent=self, title="현재 효과 체인 내보내기", defaultextension=".json", filetypes=[("Voice FX JSON", "*.json")])
        if path:
            record = {"version": 1, "id": "exported", "name": self.preset.get()[:60] or "사용자 정의", "settings": self.snapshot()}
            self.perform(lambda: self.store.export(path, record))

    def destroy(self):
        if self.save_timer is not None:
            self.after_cancel(self.save_timer)
            self.save_timer = None
            self.persist()
        super().destroy()
        self.variables.clear()
        self.enabled = self.manage_open = None
