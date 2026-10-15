"""Inspector for embedded condition blocks and nested Boolean expressions."""
from copy import deepcopy
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.automation.conditions import (evaluate, new_block, prune_expression,
                                       reconcile_connections, update_block)
from app.automation.data import InputResolver, execution_signature


def parse_value(text, type_id):
    if type_id in {"Number", "JSON", "FileList"}:
        try:
            value = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{type_id} 값이 올바르지 않습니다: {text}") from exc
        from app.automation.ports import value_matches
        if not value_matches(value, type_id):
            raise ValueError(f"{type_id} 값이 올바르지 않습니다: {text}")
        return value
    return text


class ConditionEditor(ttk.Frame):
    def __init__(self, parent, editor, node):
        super().__init__(parent)
        self.editor, self.node = editor, node
        self.registry = editor.runtime.registry
        self.fields = {}
        self.tree_paths = {}
        ttk.Label(self, text="내부 조건식 · 실행 흐름과 별도").pack(anchor="w", pady=(8, 0))
        self.tree = ttk.Treeview(self, show="tree", height=5, selectmode="browse")
        self.tree.pack(fill="x", pady=4)
        self.render_tree(node.get("config", {}).get("expression"))
        ops = ttk.Frame(self)
        ops.pack(fill="x")
        for op in ("and", "or", "not"):
            ttk.Button(ops, text=op.upper() + " 감싸기", padding=2, command=lambda o=op: self.wrap(o)).pack(side="left", expand=True, fill="x")
        edit_ops = ttk.Frame(self)
        edit_ops.pack(fill="x", pady=3)
        self.group_op = tk.StringVar(value="and")
        ttk.Combobox(edit_ops, textvariable=self.group_op, values=("and", "or", "not"), state="readonly", width=6).pack(side="left")
        ttk.Button(edit_ops, text="그룹 변경", padding=2, command=self.change_group).pack(side="left", expand=True, fill="x")
        ttk.Button(edit_ops, text="감싸기 해제", padding=2, command=self.unwrap).pack(side="left", expand=True, fill="x")
        ttk.Label(self, text="선택한 식을 감싸거나, 선택한 그룹에 새 조건을 삽입합니다.", wraplength=235).pack(anchor="w", pady=4)
        self.type_labels = {spec.label: spec.id for spec in self.registry.conditions.specs.values()}
        self.add_type = tk.StringVar(value=next(iter(self.type_labels)))
        ttk.Combobox(self, textvariable=self.add_type, values=list(self.type_labels), state="readonly", width=22).pack(fill="x")
        ttk.Button(self, text="조건 형식 블록 추가", command=self.add_block).pack(fill="x", pady=4)
        for block in node.get("config", {}).get("blocks", []):
            if isinstance(block, dict):
                self.card(block)
        ttk.Button(self, text="설정 적용", command=editor.apply).pack(fill="x", pady=5)
        ttk.Button(self, text="조건 결과 미리보기", command=self.preview).pack(fill="x")
        self.preview_text = tk.StringVar(value="실행 이력이 있으면 해당 출력값을 사용합니다.")
        ttk.Label(self, textvariable=self.preview_text, wraplength=235).pack(anchor="w", pady=5)

    def render_tree(self, tree, parent="", path=(), depth=0):
        if depth > 16:
            return
        if not isinstance(tree, dict):
            label = "조건식 없음 / 형식 오류"
        elif "block" in tree:
            block = next((b for b in self.node.get("config", {}).get("blocks", []) if isinstance(b, dict) and b.get("id") == tree["block"]), {})
            spec = self.registry.conditions.get(block.get("type"))
            label = f"{tree['block']} · {spec.label if spec else '사용 불가'}"
        else:
            label = str(tree.get("op", "잘못된 식")).upper()
        item = self.tree.insert(parent, "end", text=label, open=True)
        self.tree_paths[item] = path
        if isinstance(tree, dict) and isinstance(tree.get("children"), list):
            for index, child in enumerate(tree["children"][:64]):
                self.render_tree(child, item, (*path, index), depth + 1)

    def card(self, block):
        block_id = block.get("id", "")
        spec = self.registry.conditions.get(block.get("type"))
        card = ttk.LabelFrame(self, text=f"내부 블록: {block_id}", padding=6)
        card.pack(fill="x", pady=7)
        label = spec.label if spec else f"사용 불가: {block.get('type')}"
        selected_type = tk.StringVar(value=label)
        selector = ttk.Combobox(card, textvariable=selected_type, values=list(self.type_labels), state="readonly", width=22)
        selector.pack(fill="x")
        selector.bind("<<ComboboxSelected>>", lambda e, bid=block_id, v=selected_type: self.change_type(bid, self.type_labels[v.get()]))
        ttk.Button(card, text="이 조건 삭제", command=lambda bid=block_id: self.remove_block(bid), padding=2).pack(anchor="e", pady=3)
        self.fields[block_id] = {}
        if not spec or not isinstance(block.get("config", {}), dict):
            ttk.Label(card, text="원본 데이터를 보존합니다. 형식을 선택하면 교체됩니다.", wraplength=220).pack()
            return
        settings = {**spec.defaults, **block.get("config", {})}
        if spec.operators:
            var = tk.StringVar(value=settings.get("operator", ""))
            self.fields[block_id]["operator"] = (var, "String")
            ttk.Label(card, text="비교 연산자").pack(anchor="w")
            ttk.Combobox(card, textvariable=var, values=spec.operators, state="readonly").pack(fill="x")
        keys = list(spec.inputs) + [k for k in spec.defaults if k not in spec.inputs and k != "operator"]
        for key in keys:
            port = spec.inputs.get(key)
            name = f"{block_id}.{key}"
            ttk.Label(card, text=f"{key}" + (f" · {port.type}" if port else "")).pack(anchor="w", pady=(5, 0))
            edges = [e for e in self.editor.workflow["connections"] if e["to_node"] == self.node["id"] and e["to_port"] == name]
            if edges:
                ttk.Label(card, text="자동 전달 ← " + ", ".join(f"{e['from_node']}.{e['from_port']}" for e in edges), wraplength=220).pack(anchor="w")
                continue
            value = settings.get(key, "")
            type_id = port.type if port else "String"
            var = tk.BooleanVar(value=value) if type_id == "Boolean" else tk.StringVar(value=json.dumps(value, ensure_ascii=False) if type_id in {"Number", "FileList", "JSON"} and value != "" else value)
            self.fields[block_id][key] = (var, type_id)
            if type_id == "Boolean":
                ttk.Checkbutton(card, text="참(True)", variable=var).pack(anchor="w")
            else:
                ttk.Entry(card, textvariable=var).pack(fill="x")
                if type_id == "FilePath":
                    def browse(v=var):
                        path = filedialog.askopenfilename(parent=self)
                        if path:
                            v.set(path)
                    ttk.Button(card, text="파일 선택", command=browse, padding=2).pack(anchor="e")

    def collect(self):
        config = deepcopy(self.node.get("config", {}))
        for block in config.get("blocks", []):
            if not isinstance(block, dict):
                continue
            fields = self.fields.get(block.get("id"), {})
            if fields:
                settings = block.setdefault("config", {})
                for key, (var, type_id) in fields.items():
                    settings[key] = var.get() if type_id == "Boolean" else parse_value(var.get(), type_id)
        return config

    def selected_path(self):
        selection = self.tree.selection()
        return self.tree_paths.get(selection[0], ()) if selection else ()

    @staticmethod
    def subtree(config, path):
        tree = config["expression"]
        for index in path:
            tree = tree["children"][index]
        return tree

    @staticmethod
    def set_subtree(config, path, tree):
        if not path:
            config["expression"] = tree
        else:
            parent = ConditionEditor.subtree(config, path[:-1])
            parent["children"][path[-1]] = tree

    def commit(self, workflow, removed=()):
        if removed:
            details = "\n".join(f"{e['from_node']}.{e['from_port']} → {e['to_node']}.{e['to_port']}" for e in removed)
            messagebox.showinfo("조건 입력 포트 변경", f"새 형식과 호환되지 않는 연결 {len(removed)}개를 해제합니다.\n{details}", parent=self)
        editor = self.editor
        if editor.mode.get() == "simple" or editor.smart.get():
            from app.automation.smart_connections import repair_inputs
            workflow, _, _ = repair_inputs(workflow, self.registry)
        editor.remember()
        editor.workflow = workflow
        editor.inspect()
        editor.draw()

    def add_block(self, type_id=None):
        path = self.selected_path()
        if not self.editor.apply():
            return
        workflow = deepcopy(self.editor.workflow)
        node = next(n for n in workflow["nodes"] if n["id"] == self.node["id"])
        config = node["config"]
        if len(config.get("blocks", [])) >= 64:
            self.editor.error("조건 형식은 최대 64개입니다.")
            return
        block = new_block(type_id or self.type_labels[self.add_type.get()], self.registry.conditions)
        config.setdefault("blocks", []).append(block)
        leaf = {"block": block["id"]}
        selected = self.subtree(config, path) if config.get("expression") else None
        if selected and selected.get("op") in {"and", "or"}:
            selected["children"].append(leaf)
        elif selected:
            self.set_subtree(config, path, {"op": "and", "children": [selected, leaf]})
        else:
            config["expression"] = leaf
        self.commit(workflow)

    def change_type(self, block_id, type_id):
        if not self.editor.apply():
            return
        updated, removed = update_block(self.editor.workflow, self.node["id"], block_id, type_id, self.registry)
        self.commit(updated, removed)

    def remove_block(self, block_id):
        if not self.editor.apply():
            return
        workflow = deepcopy(self.editor.workflow)
        node = next(n for n in workflow["nodes"] if n["id"] == self.node["id"])
        config = node["config"]
        if len(config["blocks"]) == 1:
            self.editor.error("Condition에는 최소 1개의 조건 형식이 필요합니다.")
            return
        config["blocks"] = [b for b in config["blocks"] if b["id"] != block_id]
        config["expression"] = prune_expression(config["expression"], block_id) or {"block": config["blocks"][0]["id"]}
        if str(config.get("passthrough", "")).startswith(block_id + "."):
            config.pop("passthrough", None)
        removed = reconcile_connections(workflow, node["id"], self.registry, block_id)
        self.commit(workflow, removed)

    def wrap(self, op):
        path = self.selected_path()
        if not self.editor.apply():
            return
        workflow = deepcopy(self.editor.workflow)
        config = next(n for n in workflow["nodes"] if n["id"] == self.node["id"])["config"]
        tree = self.subtree(config, path)
        self.set_subtree(config, path, {"op": op, "children": [tree]})
        self.commit(workflow)

    def change_group(self):
        path = self.selected_path()
        if not self.editor.apply():
            return
        workflow = deepcopy(self.editor.workflow)
        config = next(n for n in workflow["nodes"] if n["id"] == self.node["id"])["config"]
        tree = self.subtree(config, path)
        op = self.group_op.get()
        if not isinstance(tree, dict) or "op" not in tree:
            self.editor.error("조건식 트리에서 논리 그룹을 선택하세요.")
            return
        if op == "not" and len(tree.get("children", [])) != 1:
            self.editor.error("NOT 그룹에는 하위 조건이 정확히 1개 필요합니다.")
            return
        tree["op"] = op
        self.commit(workflow)

    def unwrap(self):
        path = self.selected_path()
        if not self.editor.apply():
            return
        workflow = deepcopy(self.editor.workflow)
        config = next(n for n in workflow["nodes"] if n["id"] == self.node["id"])["config"]
        tree = self.subtree(config, path)
        if not isinstance(tree, dict) or len(tree.get("children", [])) != 1:
            self.editor.error("하위 조건이 1개인 그룹만 감싸기를 해제할 수 있습니다.")
            return
        self.set_subtree(config, path, tree["children"][0])
        self.commit(workflow)

    def preview(self):
        try:
            config = self.collect()
            node = {**self.node, "config": config}
            workflow = deepcopy(self.editor.workflow)
            workflow["nodes"] = [node if n["id"] == node["id"] else n for n in workflow["nodes"]]
            signature = execution_signature(workflow, self.registry)
            outputs = self.editor.preview_outputs if signature == self.editor.preview_signature else {}
            resolver = InputResolver(node, workflow, self.registry, outputs)
            result = evaluate(config, self.registry.conditions, resolver.get)
            self.preview_text.set(f"결과: {result} · " + ("최근 실행 출력값 사용" if outputs else "직접 입력값 사용"))
        except (ValueError, OSError, KeyError) as exc:
            self.preview_text.set(f"미리보기: {exc}\n연결된 입력은 먼저 테스트 실행하세요.")
