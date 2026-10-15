"""Minimal inspector; advanced graphs are preserved and shown read-only."""
from copy import deepcopy
import tkinter as tk
from tkinter import messagebox, ttk

from app.automation.conditions import update_block
from app.automation.condition_ui import parse_value
from app.automation.smart_connections import repair_inputs


SIMPLE_LABELS = {"trigger.folder_created": "파일 감시", "logic.condition": "조건",
                 "file.convert_image": "변환", "file.move": "이동"}
FIELD_LABELS = {"path": "감시 폴더", "recursive": "하위 폴더 포함", "format": "변환 형식",
                "output_dir": "출력 폴더", "source_path": "입력 파일"}
SIMPLE_CONDITIONS = {"always_true", "always_false", "file.extension", "file.exists", "file.size"}


class SimpleConditionEditor(ttk.Frame):
    def __init__(self, parent, editor, node):
        super().__init__(parent)
        self.editor, self.node = editor, node
        self.registry = editor.runtime.registry
        self.fields = {}
        config = node.get("config", {})
        items = config.get("blocks", [])
        if len(items) != 1 or config.get("expression") != {"block": items[0].get("id")} or items[0].get("type") not in SIMPLE_CONDITIONS:
            ttk.Label(self, text="복합 조건 또는 고급 조건입니다.\n설정을 유지하며 고급 모드에서 편집할 수 있습니다.", wraplength=235).pack(anchor="w", pady=8)
            ttk.Button(self, text="고급 모드에서 편집", command=lambda: editor.set_mode("advanced")).pack(fill="x")
            return
        self.block = items[0]
        spec = self.registry.conditions.get(self.block["type"])
        choices = {s.label: s.id for s in self.registry.conditions.specs.values() if s.id in SIMPLE_CONDITIONS}
        self.type_choice = tk.StringVar(value=spec.label)
        ttk.Label(self, text="조건 종류").pack(anchor="w", pady=(8, 3))
        selector = ttk.Combobox(self, textvariable=self.type_choice, values=list(choices), state="readonly")
        selector.pack(fill="x")
        selector.bind("<<ComboboxSelected>>", lambda e: self.change_type(choices[self.type_choice.get()]))
        settings = {**spec.defaults, **self.block.get("config", {})}
        if spec.id == "file.extension":
            ttk.Label(self, text="파일 확장자 (예: png)").pack(anchor="w", pady=(8, 3))
            var = tk.StringVar(value=settings["extension"])
            self.fields["extension"] = (var, "String")
            ttk.Entry(self, textvariable=var).pack(fill="x")
        if spec.operators:
            operator_names = {"eq": "같음", "ne": "다름", "le": "이하", "lt": "미만", "ge": "이상", "gt": "초과", "exists": "파일이 있음", "missing": "파일이 없음"}
            self.operator_choices = {operator_names[op]: op for op in spec.operators}
            self.operator = tk.StringVar(value=operator_names.get(settings["operator"], settings["operator"]))
            ttk.Label(self, text="비교 방법").pack(anchor="w", pady=(8, 3))
            ttk.Combobox(self, textvariable=self.operator, values=list(self.operator_choices), state="readonly").pack(fill="x")
        if spec.id == "file.size":
            ttk.Label(self, text="기준 크기 (바이트, 10MB = 10485760)", wraplength=235).pack(anchor="w", pady=(8, 3))
            threshold_key = f"{self.block['id']}.threshold"
            if any(e["to_node"] == node["id"] and e["to_port"] == threshold_key for e in editor.workflow["connections"]):
                ttk.Label(self, text="기준 크기: 연결된 값 사용").pack(anchor="w")
            else:
                var = tk.StringVar(value=settings["threshold"])
                self.fields["threshold"] = (var, "Number")
                ttk.Entry(self, textvariable=var).pack(fill="x")
        if spec.inputs:
            ttk.Label(self, text="검사할 파일은 앞 단계에서 자동 전달됩니다.", wraplength=235).pack(anchor="w", pady=10)
        ttk.Button(self, text="설정 적용", command=editor.apply).pack(fill="x", pady=5)
        ttk.Button(self, text="세부 조건 편집 (고급)", command=lambda: editor.set_mode("advanced")).pack(fill="x")

    def collect(self):
        config = deepcopy(self.node.get("config", {}))
        if not hasattr(self, "block"):
            return config
        settings = config["blocks"][0].setdefault("config", {})
        for key, (var, type_id) in self.fields.items():
            settings[key] = parse_value(var.get(), type_id)
        if hasattr(self, "operator"):
            settings["operator"] = self.operator_choices.get(self.operator.get(), self.operator.get())
        return config

    def change_type(self, type_id):
        editor = self.editor
        if not editor.apply():
            return
        updated, removed = update_block(editor.workflow, self.node["id"], self.block["id"], type_id, self.registry)
        if removed:
            messagebox.showinfo("조건 변경", f"새 조건과 맞지 않는 연결 {len(removed)}개를 해제하고 필요한 입력을 다시 연결합니다.", parent=self)
        updated, _, _ = repair_inputs(updated, self.registry)
        editor.remember()
        editor.workflow = updated
        editor.inspect()
        editor.draw()
