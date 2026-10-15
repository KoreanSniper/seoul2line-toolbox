from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid

from app.automation.graph import validate
from app.automation.conditions import migrate_workflow
from app.automation.condition_ui import ConditionEditor, parse_value
from app.automation.simple_ui import FIELD_LABELS, SIMPLE_LABELS, SimpleConditionEditor
from app.automation.smart_connections import connect_nodes, disconnect, prune_auto_connections, repair_inputs
from app.automation.storage import new_workflow
from app.palette import palette


def image_example(simple=False):
    workflow = new_workflow()
    workflow["name"] = "PNG → WEBP 자동 변환"
    types = ["trigger.folder_created", "logic.extension", "file.convert_image", "file.move", "output.notify"]
    configs = [{"path": "", "recursive": False}, {"extension": "png"}, {"format": "webp", "output_dir": ""}, {"output_dir": ""}, {"message": "이미지 변환 완료 · 파일 1개"}]
    for index, (type_id, config) in enumerate(zip(types, configs)):
        workflow["nodes"].append({"id": f"node_{index+1}", "type": type_id, "position": [50 + index * 340, 100 + (index % 2) * 90], "config": config})
        if index:
            prev, nid = f"node_{index}", f"node_{index+1}"
            workflow["connections"].append({"from_node": prev, "from_port": "true" if index == 2 else "flow", "to_node": nid, "to_port": "flow"})
            if index < 4:
                workflow["connections"].append({"from_node": prev, "from_port": "file_path", "to_node": nid, "to_port": "source_path"})
    workflow = migrate_workflow(workflow)
    workflow["nodes"][1]["config"].pop("legacy_config", None)
    if simple:
        workflow["nodes"] = workflow["nodes"][:4]
        workflow["connections"] = [e for e in workflow["connections"] if e["to_node"] != "node_5"]
        for index, node in enumerate(workflow["nodes"]):
            node["position"] = [50 + index % 2 * 300, 70 + index // 2 * 190]
    return workflow


class Editor(tk.Frame):
    def __init__(self, parent, app):
        self.colors = palette(app.dark_mode)
        super().__init__(parent, bg=self.colors["panel"])
        self.app, self.runtime = app, app.automation
        self.workflow = image_example(simple=True)
        self.mode = tk.StringVar(value="simple")
        self.active_mode = "simple"
        self.smart = tk.BooleanVar(value=True)
        self.selected = None
        self.selected_edge = None
        self.undo_stack, self.redo_stack = [], []
        self.scale = .8
        self.fit_pending = True
        self.offset = [20, 20]
        self.drag, self.connecting = None, None
        self.fields = {}
        self.form_snapshot = None
        self.condition_editor = None
        self.preview_outputs, self.preview_signature = {}, None
        self.bindings = []
        self._build()
        for sequence, action in (("<Control-s>", self.save), ("<Control-z>", self.undo), ("<Control-y>", self.redo), ("<Control-d>", self.duplicate), ("<Delete>", self.delete)):
            binding = app.bind(sequence, lambda event, fn=action: self._shortcut(event, fn), add="+")
            self.bindings.append((sequence, binding))
        self.bind("<Destroy>", self._destroyed, add="+")
        self.draw()
        self.poll_job = self.after(200, self.poll)

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=8)
        for title, command in (("새로", self.new), ("열기/가져오기", self.open), ("저장", self.save), ("내보내기", self.export), ("이미지 예제", self.example), ("실행", self.run), ("중지", lambda: self.runtime.stop(self.workflow["id"]))):
            ttk.Button(bar, text=title, command=command, padding=4).pack(side="left", padx=2)
        self.name = tk.StringVar(value=self.workflow["name"])
        ttk.Entry(self, textvariable=self.name).pack(fill="x", padx=10)
        modes = ttk.Frame(self)
        modes.pack(fill="x", padx=10, pady=(6, 0))
        ttk.Radiobutton(modes, text="간편 모드", variable=self.mode, value="simple", command=lambda: self.set_mode("simple")).pack(side="left")
        ttk.Radiobutton(modes, text="고급 모드", variable=self.mode, value="advanced", command=lambda: self.set_mode("advanced")).pack(side="left", padx=8)
        self.smart_toggle = ttk.Checkbutton(modes, text="연결 시 데이터 자동 연결", variable=self.smart)
        panes = tk.PanedWindow(self, orient="horizontal", bg=self.colors["border"], sashwidth=5)
        panes.pack(fill="both", expand=True, padx=8, pady=8)
        library = ttk.Frame(panes)
        panes.add(library, width=145, minsize=110)
        ttk.Label(library, text="노드 라이브러리").pack(anchor="w")
        query = tk.StringVar()
        ttk.Entry(library, textvariable=query).pack(fill="x", pady=5)
        self.library = tk.Listbox(library, exportselection=False, bg=self.colors["field"], fg=self.colors["text"], relief="flat", width=18)
        self.library.pack(fill="both", expand=True)
        self.library.bind("<Double-Button-1>", lambda e: self.add())
        ttk.Button(library, text="노드 추가", command=self.add).pack(fill="x")
        def search(*_):
            self.library.delete(0, "end")
            simple = self.mode.get() == "simple"
            self.library_specs = [s for s in self.runtime.registry.specs.values() if s.id != "logic.extension"
                                  and (not simple or s.id in SIMPLE_LABELS)
                                  and query.get().lower() in (s.label + s.category + SIMPLE_LABELS.get(s.id, "")).lower()]
            for spec in self.library_specs:
                self.library.insert("end", SIMPLE_LABELS[spec.id] if simple else f"{spec.category} · {spec.label}")
        query.trace_add("write", search)
        self.refresh_library = search
        search()
        center = ttk.Frame(panes)
        panes.add(center, stretch="always", minsize=180)
        self.canvas_help = tk.StringVar(value="오른쪽 연결점을 다음 노드로 끌어 연결 · 우클릭: 이동 · 휠: 확대/축소")
        ttk.Label(center, textvariable=self.canvas_help, wraplength=500).pack(anchor="w")
        ttk.Button(center, text="전체 보기", command=self.fit_canvas, padding=2).pack(anchor="e")
        self.canvas = tk.Canvas(center, bg=self.colors["app"], highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<MouseWheel>", self.zoom)
        self.canvas.bind("<ButtonPress-3>", lambda e: setattr(self, "pan", (e.x, e.y, *self.offset)))
        self.canvas.bind("<B3-Motion>", self.pan_motion)
        self.canvas.bind("<Configure>", self._canvas_configure)
        inspector_panel = ttk.Frame(panes)
        panes.add(inspector_panel, width=270, minsize=200)
        self.inspector_canvas = tk.Canvas(inspector_panel, bg=self.colors["panel"], highlightthickness=0)
        scroll = ttk.Scrollbar(inspector_panel, orient="vertical", command=self.inspector_canvas.yview)
        self.inspector_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.inspector_canvas.pack(side="left", fill="both", expand=True)
        self.inspector = ttk.Frame(self.inspector_canvas)
        inspector_window = self.inspector_canvas.create_window(0, 0, window=self.inspector, anchor="nw")
        self.inspector.bind("<Configure>", lambda e: self.inspector_canvas.configure(scrollregion=self.inspector_canvas.bbox("all")))
        self.inspector_canvas.bind("<Configure>", lambda e: self.inspector_canvas.itemconfigure(inspector_window, width=e.width))
        self.validation = tk.StringVar()
        ttk.Label(self, textvariable=self.validation, wraplength=900).pack(fill="x", padx=10)
        self.log = tk.Text(self, height=6, bg=self.colors["field"], fg=self.colors["text"], state="disabled", relief="flat")
        self.log.pack(fill="x", padx=8, pady=8)

    def _shortcut(self, event, fn):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)) and fn in (self.delete, self.duplicate, self.undo, self.redo):
            return
        fn()
        return "break"

    def _destroyed(self, event):
        if event.widget is self:
            for sequence, binding in self.bindings:
                self.app.unbind(sequence, binding)
            if hasattr(self, "poll_job"):
                self.after_cancel(self.poll_job)

    def remember(self):
        self.undo_stack.append(deepcopy(self.workflow))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def set_mode(self, mode):
        if mode not in {"simple", "advanced"}:
            return
        self.mode.set(self.active_mode)
        if not self.apply():
            return
        self.mode.set(mode)
        self.active_mode = mode
        self.drag, self.connecting = None, None
        self.selected_edge = None
        if mode == "advanced":
            self.smart_toggle.pack(side="left", padx=8)
            self.canvas_help.set("포트 드래그: 연결 · 실행선 연결 시 데이터 자동 추론 · 우클릭: 이동 · 휠: 확대/축소")
        else:
            self.smart_toggle.pack_forget()
            self.canvas_help.set("오른쪽 연결점을 다음 노드로 끌어 연결 · 우클릭: 이동 · 휠: 확대/축소")
        self.refresh_library()
        self.inspect()
        self.draw()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(deepcopy(self.workflow))
            self.workflow = self.undo_stack.pop()
            self.refresh()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(deepcopy(self.workflow))
            self.workflow = self.redo_stack.pop()
            self.refresh()

    def refresh(self):
        self.name.set(self.workflow.get("name", ""))
        self.selected = None
        self.selected_edge = None
        self.inspect()
        self.draw()

    def replace(self, workflow):
        self.remember()
        self.workflow = migrate_workflow(workflow)
        self.preview_outputs, self.preview_signature = {}, None
        self.refresh()

    def new(self):
        if messagebox.askyesno("새 워크플로", "저장하지 않은 편집 내용을 새 워크플로로 바꿀까요?", parent=self):
            self.replace(new_workflow())

    def example(self):
        if messagebox.askyesno("이미지 예제", "현재 편집 내용을 이미지 자동화 예제로 바꿀까요?", parent=self):
            self.replace(image_example(simple=self.mode.get() == "simple"))

    def open(self):
        path = filedialog.askopenfilename(parent=self, initialdir=self.runtime.store.root, filetypes=[("Workflow", "*.workflow.json"), ("JSON", "*.json")])
        if not path:
            return
        try:
            workflow = self.runtime.store.load(path)
            internal = Path(path).resolve().parent == self.runtime.store.root.resolve()
            if not internal:
                workflow["id"] = uuid.uuid4().hex
                workflow["enabled"] = False
            self.replace(workflow)
        except (ValueError, OSError) as exc:
            self.error(exc)

    def save(self):
        try:
            if not self.apply():
                return False
            self.workflow["name"] = self.name.get().strip() or "워크플로"
            # Edits to active graphs require a fresh explicit activation.
            if self.workflow["id"] in self.runtime.watches:
                self.runtime.disable(self.workflow["id"])
            self.workflow["enabled"] = False
            path = self.runtime.store.save(self.workflow)
            self.append(f"저장: {path}\n폴더 감시는 자동화 관리에서 활성화하세요.")
            return True
        except (ValueError, OSError) as exc:
            self.error(exc)
            return False

    def export(self):
        if not self.apply():
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".workflow.json", filetypes=[("Workflow", "*.workflow.json")])
        if path:
            try:
                exported = deepcopy(self.workflow)
                exported["enabled"] = False
                exported["name"] = self.name.get()
                Path(path).write_text(json.dumps(exported, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            except (OSError, ValueError) as exc:
                self.error(exc)

    def add(self):
        selection = self.library.curselection()
        if not selection:
            return
        spec = self.library_specs[selection[0]]
        self.remember()
        node = {"id": uuid.uuid4().hex[:12], "type": spec.id, "position": [(80 - self.offset[0]) / self.scale, (80 - self.offset[1]) / self.scale], "config": deepcopy(spec.defaults)}
        self.workflow["nodes"].append(node)
        self.selected = node["id"]
        self.inspect()
        self.draw()

    def duplicate(self):
        node = self.node()
        if node:
            self.remember()
            clone = deepcopy(node)
            clone["id"] = uuid.uuid4().hex[:12]
            clone["position"] = [v + 35 for v in node["position"]]
            self.workflow["nodes"].append(clone)
            self.selected = clone["id"]
            self.inspect()
            self.draw()

    def delete(self):
        if self.selected_edge is not None:
            self.remember()
            self.workflow = disconnect(self.workflow, self.runtime.registry, self.selected_edge, simple=self.mode.get() == "simple")
            self.selected_edge = None
        elif self.selected:
            self.remember()
            self.workflow["nodes"] = [n for n in self.workflow["nodes"] if n["id"] != self.selected]
            self.workflow["connections"] = [e for e in self.workflow["connections"] if self.selected not in (e["from_node"], e["to_node"])]
            self.workflow = prune_auto_connections(self.workflow, self.runtime.registry)
            self.selected = None
        self.inspect()
        self.draw()

    def node(self):
        return next((n for n in self.workflow["nodes"] if n["id"] == self.selected), None)

    def inspect(self):
        for child in self.inspector.winfo_children():
            child.destroy()
        self.fields = {}
        self.condition_editor = None
        self.form_snapshot = None
        node = self.node()
        if not node:
            ttk.Label(self.inspector, text="노드를 선택해 설정하세요.").pack(anchor="w")
            return
        spec = self.runtime.registry.get(node["type"])
        simple = self.mode.get() == "simple"
        ttk.Label(self.inspector, text=SIMPLE_LABELS.get(node["type"], spec.label if spec else "사용 불가 노드") if simple else spec.label if spec else "사용 불가 노드").pack(anchor="w", pady=8)
        if not simple:
            ttk.Label(self.inspector, text=node["id"]).pack(anchor="w")
        if not spec:
            return
        if node["type"] == "logic.condition":
            factory = SimpleConditionEditor if simple else ConditionEditor
            self.condition_editor = factory(self.inspector, self, node)
            self.condition_editor.pack(fill="x")
            self.form_snapshot = self.form_state()
            self.inspector_canvas.yview_moveto(0)
            return
        if simple and node["type"] not in SIMPLE_LABELS:
            ttk.Label(self.inspector, text="고급 노드입니다. 기존 설정과 연결은 유지됩니다.", wraplength=235).pack(anchor="w")
            ttk.Button(self.inspector, text="고급 모드에서 편집", command=lambda: self.set_mode("advanced")).pack(fill="x")
            return
        inputs = self.runtime.registry.inputs_for(node)
        keys = {**spec.defaults, **node.get("config", {})}
        for key, port in inputs.items():
            if port.type != "Flow" and not simple:
                keys.setdefault(key, "")
        if simple:
            allowed = {"path", "recursive"} if node["type"] == "trigger.folder_created" else {"format", "output_dir"} if node["type"] == "file.convert_image" else {"output_dir"}
            keys = {key: value for key, value in keys.items() if key in allowed}
            if node["type"].startswith("file."):
                connected = any(e["to_node"] == node["id"] and e["to_port"] == "source_path" for e in self.workflow["connections"])
                text = "입력 파일: 앞 단계의 결과 자동 사용" if connected else "입력 파일: 앞 단계와 연결하세요" if not node.get("config", {}).get("source_path") else "직접 지정한 입력 파일 사용 (고급 설정)"
                ttk.Label(self.inspector, text=text, wraplength=235).pack(anchor="w", pady=6)
        for key, value in keys.items():
            ttk.Label(self.inspector, text=FIELD_LABELS.get(key, key) if simple else key).pack(anchor="w", pady=(8, 0))
            edges = [e for e in self.workflow["connections"] if e["to_node"] == node["id"] and e["to_port"] == key]
            if edges:
                ttk.Label(self.inspector, text="자동 전달 ← " + ", ".join(f"{e['from_node']}.{e['from_port']}" for e in edges), wraplength=235).pack(anchor="w")
                continue
            port = inputs.get(key)
            type_id = port.type if port else "String"
            if type_id in {"FileList", "JSON", "Number"} and value != "":
                value = json.dumps(value, ensure_ascii=False)
            var = tk.BooleanVar(value=value) if isinstance(value, bool) else tk.StringVar(value=value)
            self.fields[key] = var
            if isinstance(value, bool):
                ttk.Checkbutton(self.inspector, variable=var, text="하위 폴더 포함").pack(anchor="w")
            else:
                if simple and key == "format":
                    ttk.Combobox(self.inspector, textvariable=var, values=("webp", "png", "jpg", "jpeg", "bmp", "gif", "tiff", "ico"), state="readonly").pack(fill="x")
                else:
                    ttk.Entry(self.inspector, textvariable=var).pack(fill="x")
                if key in {"path", "output_dir", "source_path", "file_path"}:
                    def browse(v=var, k=key):
                        result = filedialog.askdirectory(parent=self) if k in {"path", "output_dir"} else filedialog.askopenfilename(parent=self)
                        if result:
                            v.set(result)
                    ttk.Button(self.inspector, text="찾아보기", command=browse).pack(anchor="e")
        ttk.Button(self.inspector, text="설정 적용", command=self.apply).pack(fill="x", pady=10)
        self.form_snapshot = self.form_state()
        if simple:
            ttk.Button(self.inspector, text="세부 설정 (고급)", command=lambda: self.set_mode("advanced")).pack(fill="x")
        else:
            ttk.Label(self.inspector, text="데이터 연결이 있으면 직접 입력값보다 우선합니다.", wraplength=190).pack(anchor="w")

    def form_state(self):
        def state(value):
            if isinstance(value, tk.Variable):
                return value.get()
            if isinstance(value, dict):
                return {key: state(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return tuple(state(item) for item in value)
            return value
        fields = self.condition_editor.fields if self.condition_editor else self.fields
        operator = getattr(self.condition_editor, "operator", None)
        return state(fields), operator.get() if operator is not None else None

    def apply(self):
        node = self.node()
        if node and (self.fields or self.condition_editor):
            if self.form_snapshot == self.form_state():
                self.draw()
                return True
            try:
                if self.condition_editor:
                    config = self.condition_editor.collect()
                else:
                    config = deepcopy(node.get("config", {}))
                    ports = self.runtime.registry.inputs_for(node)
                    for key, var in self.fields.items():
                        port = ports.get(key)
                        config[key] = var.get() if isinstance(var, tk.BooleanVar) else parse_value(var.get(), port.type if port else "String")
            except ValueError as exc:
                self.error(exc)
                return False
            if config != node.get("config"):
                self.remember()
                node["config"] = config
            self.form_snapshot = self.form_state()
        self.draw()
        return True

    def draw(self):
        self.canvas.delete("all")
        self.ports, self.items = {}, {}
        simple = self.mode.get() == "simple"
        for node in self.workflow["nodes"]:
            spec = self.runtime.registry.get(node["type"])
            inputs = self.runtime.registry.inputs_for(node) if spec else {}
            outputs = self.runtime.registry.outputs_for(node) if spec else {}
            if simple:
                inputs = {name: port for name, port in inputs.items() if port.type == "Flow"}
                outputs = {name: port for name, port in outputs.items() if port.type == "Flow"}
            x, y = self.point(*node.get("position", [0, 0]))
            is_condition = node["type"] == "logic.condition"
            width = (205 if simple else 300 if is_condition else 195) * self.scale
            rows = max(len(inputs), len(outputs)) if spec else 1
            condition_blocks = node.get("config", {}).get("blocks", []) if is_condition else []
            condition_blocks = [b for b in condition_blocks if isinstance(b, dict)] if isinstance(condition_blocks, list) else []
            height = (95 if simple else 60 + rows * 27 + (30 + len(condition_blocks) * 27 if is_condition else 0)) * self.scale
            item = self.canvas.create_rectangle(x, y, x + width, y + height, fill=self.colors["surface"], outline=self.colors["accent"] if node["id"] == self.selected else self.colors["border"], width=2)
            self.items[item] = ("node", node["id"])
            title = spec.label if spec else f"사용 불가: {node['type']}"
            if simple:
                title = SIMPLE_LABELS.get(node["type"], "고급 · " + title)
            item = self.canvas.create_text(x + 12 * self.scale, y + 20 * self.scale, text=title, fill=self.colors["text"], anchor="w", font=("Segoe UI", max(8, int(11 * self.scale)), "bold"))
            self.items[item] = ("node", node["id"])
            if not spec:
                continue
            if simple:
                for direction, ports in (("in", inputs), ("out", outputs)):
                    if not ports:
                        continue
                    px, py = x if direction == "in" else x + width, y + 48 * self.scale
                    for name in ports:
                        self.ports[(node["id"], direction, name)] = (px, py)
                    self.ports[(node["id"], direction, "__node__")] = (px, py)
                    item = self.canvas.create_oval(px-8, py-8, px+8, py+8, fill=self.colors["accent"], outline="")
                    self.items[item] = ("link", node["id"], direction, "__node__")
                if node["type"] == "file.convert_image":
                    summary = "변환 형식: " + str(node.get("config", {}).get("format", "webp")).upper()
                elif is_condition:
                    formats = [self.runtime.registry.conditions.get(b.get("type")) for b in condition_blocks]
                    summary = formats[0].label if len(formats) == 1 and formats[0] else "복합 조건 · 고급 설정"
                elif node["type"] == "file.move":
                    summary = "앞 단계 결과 파일 이동"
                elif node["type"] == "trigger.folder_created":
                    summary = "새 파일이 생성되면 시작"
                else:
                    summary = "설정은 고급 모드에서 편집"
                caption = self.canvas.create_text(x+12*self.scale, y+61*self.scale, text=summary, anchor="w", width=180*self.scale, fill=self.colors["muted"], font=("Segoe UI", max(7, int(9*self.scale))))
                self.items[caption] = ("node", node["id"])
                continue
            for direction, ports in (("in", inputs), ("out", outputs)):
                for index, (name, port) in enumerate(ports.items()):
                    px, py = x if direction == "in" else x + width, y + (55 + index * 27) * self.scale
                    self.ports[(node["id"], direction, name)] = (px, py)
                    color = "#60a5fa" if port.type == "Flow" else "#34d399"
                    r = 6
                    item = self.canvas.create_oval(px-r, py-r, px+r, py+r, fill=color, outline="")
                    self.items[item] = ("port", node["id"], direction, name)
                    label = name + (" [+]" if port.allows_multiple and port.type != "Flow" else "")
                    self.canvas.create_text(px + (12 if direction == "in" else -12), py, text=label, fill=self.colors["muted"], anchor="w" if direction == "in" else "e", font=("Segoe UI", max(7, int(9 * self.scale))))
            if is_condition:
                for index, block in enumerate(condition_blocks):
                    spec_block = self.runtime.registry.conditions.get(block.get("type"))
                    by = y + (65 + rows * 27 + index * 27) * self.scale
                    card = self.canvas.create_rectangle(x+10*self.scale, by, x+width-10*self.scale, by+23*self.scale, fill=self.colors["panel_soft"], outline=self.colors["border"])
                    self.items[card] = ("node", node["id"])
                    label = f"{block.get('id')} · {spec_block.label if spec_block else '사용 불가 조건'}"
                    card_text = self.canvas.create_text(x+16*self.scale, by+12*self.scale, text=label, anchor="w", fill=self.colors["text"], font=("Segoe UI", max(7, int(9*self.scale))))
                    self.items[card_text] = ("node", node["id"])
        for index, edge in enumerate(self.workflow["connections"]):
            start = self.ports.get((edge.get("from_node"), "out", edge.get("from_port")))
            end = self.ports.get((edge.get("to_node"), "in", edge.get("to_port")))
            if not start or not end:
                continue
            x, y = start
            ex, ey = end
            spec = self.runtime.registry.get(next(n["type"] for n in self.workflow["nodes"] if n["id"] == edge["from_node"]))
            color = "#60a5fa" if spec.outputs[edge["from_port"]].type == "Flow" else "#34d399"
            item = self.canvas.create_line(x, y, x+70, y, ex-70, ey, ex, ey, smooth=True, arrow="last", fill="#fbbf24" if index == self.selected_edge else color, width=3)
            self.items[item] = ("edge", index)
            self.canvas.tag_lower(item)
            if simple and edge["from_port"] in {"true", "false"}:
                label = self.canvas.create_text((x+ex)/2, (y+ey)/2-10, text="조건 만족" if edge["from_port"] == "true" else "조건 불일치", fill=self.colors["muted"], font=("Segoe UI", 8))
                self.items[label] = ("edge", index)
        errors = validate(self.workflow, self.runtime.registry)
        self.validation.set("검증: " + (" · ".join(errors[:3]) + (f" 외 {len(errors)-3}건" if len(errors) > 3 else "") if errors else "실행 가능"))

    def point(self, x, y):
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def hit(self, event):
        for item in reversed(self.canvas.find_overlapping(event.x-6, event.y-6, event.x+6, event.y+6)):
            if item in self.items:
                return self.items[item]
        return None

    def press(self, event):
        self.canvas.focus_set()
        hit = self.hit(event)
        if not self.apply():
            return
        self.selected_edge = None
        if hit and hit[0] in {"port", "link"} and hit[2] == "out":
            self.connecting = hit[1:]
        elif hit and hit[0] in {"node", "port", "link"}:
            self.selected = hit[1]
            self.remember()
            self.drag = (event.x, event.y, *self.node()["position"])
        elif hit and hit[0] == "edge":
            self.selected_edge = hit[1]
            self.selected = None
        else:
            self.selected = None
        self.inspect()
        self.draw()

    def motion(self, event):
        if self.drag and self.node():
            x, y, nx, ny = self.drag
            self.node()["position"] = [nx + (event.x-x)/self.scale, ny + (event.y-y)/self.scale]
            self.draw()
        elif self.connecting:
            self.canvas.delete("pending")
            nid, direction, port = self.connecting
            x, y = self.ports[(nid, direction, port)]
            self.canvas.create_line(x, y, event.x, event.y, fill=self.colors["accent"], dash=(4, 4), tags="pending")

    def release(self, event):
        if self.connecting:
            hit = self.hit(event)
            source, _, port = self.connecting
            if self.mode.get() == "simple" and hit and (hit[0] == "node" or hit[0] == "link" and hit[2] == "in"):
                self.connect(source, hit[1])
            elif hit and hit[0] == "port" and hit[2] == "in":
                edge = {"from_node": source, "from_port": port, "to_node": hit[1], "to_port": hit[3]}
                nodes = {n["id"]: n for n in self.workflow["nodes"]}
                out = self.runtime.registry.outputs_for(nodes[source]).get(port)
                inp = self.runtime.registry.inputs_for(nodes[hit[1]]).get(hit[3])
                if out and inp and out.type == inp.type == "Flow":
                    self.connect(source, hit[1], port, hit[3])
                else:
                    updated = deepcopy(self.workflow)
                    updated["connections"].append(edge)
                    errors = validate(updated, self.runtime.registry)
                    invalid = [e for e in errors if any(word in e for word in ("순환", "포트 타입", "중복 연결", "하나의 연결", "데이터 공급자"))]
                    if invalid:
                        self.append("연결 불가: " + " · ".join(invalid))
                    else:
                        self.remember()
                        self.workflow = updated
            self.connecting = None
        self.drag = None
        self.inspect()
        self.draw()

    def connect(self, source_id, target_id, from_port=None, to_port=None):
        if not self.apply():
            return False
        try:
            smart = self.mode.get() == "simple" or self.smart.get()
            updated, added, unresolved = connect_nodes(self.workflow, self.runtime.registry, source_id, target_id, from_port, to_port,
                                                      auto_data=smart)
            if smart:
                updated, repaired, unresolved = repair_inputs(updated, self.runtime.registry)
                added.extend(repaired)
        except ValueError as exc:
            self.append("연결 불가: " + str(exc))
            return False
        if updated != self.workflow:
            self.remember()
            self.workflow = updated
            self.selected_edge = None
            inferred = sum("auto_for" in edge for edge in added)
            self.append(f"노드 연결 완료 · 데이터 {inferred}개 자동 연결")
        for message in unresolved:
            self.append(message)
        self.inspect()
        self.draw()
        return True

    def _canvas_configure(self, event):
        if self.fit_pending and event.width > 120 and event.height > 120:
            self.fit_pending = False
            self.fit_canvas()

    def fit_canvas(self):
        bounds = self.canvas.bbox("all")
        if not bounds or self.canvas.winfo_width() < 120 or self.canvas.winfo_height() < 120:
            return
        left, top, right, bottom = bounds
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = max(.25, min(1.2, self.scale * min((width-40)/max(right-left, 1), (height-40)/max(bottom-top, 1))))
        center_x = ((left+right)/2-self.offset[0])/self.scale
        center_y = ((top+bottom)/2-self.offset[1])/self.scale
        self.scale = scale
        self.offset = [width/2-center_x*scale, height/2-center_y*scale]
        self.draw()

    def zoom(self, event):
        scale = max(.35, min(1.8, self.scale * (1.1 if event.delta > 0 else 1/1.1)))
        ratio = scale / self.scale
        self.offset = [event.x - (event.x-self.offset[0])*ratio, event.y - (event.y-self.offset[1])*ratio]
        self.scale = scale
        self.draw()

    def pan_motion(self, event):
        x, y, ox, oy = self.pan
        self.offset = [ox + event.x-x, oy + event.y-y]
        self.draw()

    def run(self):
        if not self.apply():
            return
        errors = validate(self.workflow, self.runtime.registry)
        if errors:
            self.error("\n".join(errors))
            return
        triggers = [n for n in self.workflow["nodes"] if n["type"].startswith("trigger.")]
        trigger = self.node() if self.node() in triggers else triggers[0]
        payload = {}
        if trigger["type"] == "trigger.folder_created":
            path = filedialog.askopenfilename(parent=self, title="테스트할 입력 파일 선택")
            if not path:
                return
            payload["file_path"] = path
        try:
            if not self.runtime.submit(self.workflow, trigger["id"], payload):
                self.append("실행 대기열이 가득 찼습니다.")
        except ValueError as exc:
            self.error(exc)

    def poll(self):
        for event in self.app.drain_automation_events():
            if event[0] == self.workflow["id"]:
                if event[1] == "outputs":
                    message = event[2]
                    if self.preview_signature != message["signature"]:
                        self.preview_outputs.clear()
                    self.preview_signature = message["signature"]
                    self.preview_outputs[message["node_id"]] = message["outputs"]
                else:
                    if event[1] == "status" and str(event[2]).startswith("실행 시작"):
                        self.preview_outputs, self.preview_signature = {}, None
                    self.append(f"[{event[1]}] {event[2]}")
        self.poll_job = self.after(200, self.poll)

    def append(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", str(message) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 500:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def error(self, error):
        messagebox.showerror("워크플로", str(error), parent=self)


class Manager(tk.Frame):
    def __init__(self, parent, app, history=False):
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app, self.runtime, self.history = app, app.automation, history
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=10)
        ttk.Label(bar, text="자동화 실행 기록" if history else "자동화 관리", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Button(bar, text="새로고침", command=self.refresh).pack(side="right")
        if not history:
            for label, action in (("활성화", self.enable), ("비활성화", self.disable), ("실행 중지", self.stop)):
                ttk.Button(bar, text=label, command=action).pack(side="right", padx=3)
            ttk.Label(self, text="활성화된 폴더 감시는 앱이 열려 있는 동안 작동합니다. 기존 파일은 처리하지 않습니다.").pack(anchor="w", padx=10)
        columns = ("name", "started", "duration", "status") if history else ("name", "status", "nodes")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        labels = {"name": "워크플로", "started": "실행 시각", "duration": "소요 시간", "status": "상태", "nodes": "노드 수"}
        for column in columns:
            self.tree.heading(column, text=labels[column])
            self.tree.column(column, width=130)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.detail = tk.Text(self, height=10, wrap="word", bg=palette(app.dark_mode)["field"], fg=palette(app.dark_mode)["text"], state="disabled")
        self.detail.pack(fill="x", padx=10, pady=(0, 10))
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.records = {}
        for record in self.runtime.logger.recent() if self.history else self.runtime.store.list():
            self.records[record["id"]] = record
            if self.history:
                start = datetime.fromisoformat(record["started"])
                duration = f"{(datetime.fromisoformat(record['finished'])-start).total_seconds():.2f}s" if record["finished"] else "진행 중"
                values = (record["name"], start.astimezone().strftime("%m-%d %H:%M:%S"), duration, record["status"])
            else:
                wid = record["id"]
                status = "실행 중" if wid in self.runtime.running else "활성" if wid in self.runtime.watches else "비활성"
                if wid in self.runtime.errors:
                    status = "오류"
                values = (record.get("name", wid), status, len(record["nodes"]))
            self.tree.insert("", "end", iid=record["id"], values=values)

    def current(self):
        selection = self.tree.selection()
        return self.records.get(selection[0]) if selection else None

    def show_detail(self, _event=None):
        record = self.current()
        if record:
            text = record["detail"] if self.history else self.runtime.errors.get(record["id"], "") + "\n" + json.dumps(record, ensure_ascii=False, indent=2)
            self.detail.configure(state="normal")
            self.detail.delete("1.0", "end")
            self.detail.insert("1.0", text)
            self.detail.configure(state="disabled")

    def enable(self):
        record = self.current()
        if not record:
            return
        paths = [f"{n['type']}: {n.get('config', {})}" for n in record["nodes"]]
        if messagebox.askyesno("자동화 활성화", "다음 작업과 접근 경로를 확인하세요.\n\n" + "\n".join(paths) + "\n\n폴더 감시를 활성화할까요?", parent=self):
            try:
                self.runtime.enable(record)
            except (ValueError, OSError) as exc:
                messagebox.showerror("활성화 실패", str(exc), parent=self)
            self.refresh()

    def disable(self):
        record = self.current()
        if record:
            self.runtime.disable(record["id"])
            self.refresh()

    def stop(self):
        record = self.current()
        if record:
            self.runtime.stop(record["id"])
            self.refresh()
