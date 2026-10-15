"""Lazy per-port resolution shared by execution and read-only previews."""
from copy import deepcopy
import json
import hashlib
from app.automation.ports import compatible, missing, value_matches


class InputResolver:
    def __init__(self, node, workflow, registry, outputs):
        self.node, self.workflow, self.registry, self.outputs = node, workflow, registry, outputs
        self.ports = registry.inputs_for(node)
        self.nodes = {n["id"]: n for n in workflow["nodes"]}
        self.cache = {}

    def get(self, name):
        if name in self.cache:
            return self.cache[name]
        port = self.ports[name]
        edges = [e for e in self.workflow["connections"] if e["to_node"] == self.node["id"] and e["to_port"] == name]
        if edges:
            if len(edges) > 1 and not port.allows_multiple:
                raise ValueError(f"{self.node['id']}.{name}: 데이터 입력은 하나의 연결만 허용됩니다.")
            values = []
            # JSON connection order is the collection order, independent of
            # topological execution order. File lists are flattened one level.
            for edge in edges:
                output = self.outputs.get(edge["from_node"], {})
                if edge["from_port"] not in output:
                    raise ValueError(f"{self.node['id']}.{name}: 실행되지 않은 분기의 데이터 입력입니다.")
                value = output[edge["from_port"]]
                declared = self.registry.outputs_for(self.nodes[edge["from_node"]])[edge["from_port"]]
                if not compatible(declared, port):
                    raise ValueError(f"{self.node['id']}.{name}: 포트 타입이 호환되지 않습니다.")
                if not value_matches(value, declared.type):
                    raise ValueError(f"{edge['from_node']}.{edge['from_port']}: 출력 타입은 {declared.type}이어야 합니다.")
                if port.type == "FileList":
                    values.extend(value if isinstance(value, list) else [value])
                else:
                    values.append(value)
            value = values if port.allows_multiple or port.type == "FileList" else values[0]
        else:
            value = self.registry.input_default(self.node, name)
        if port.required and missing(value, port):
            raise ValueError(f"{self.node['id']}.{name}: 필수 입력이 없습니다.")
        expected = "FileList" if port.type == "FileList" else port.type
        items = value if port.allows_multiple and edges and port.type != "FileList" else [value]
        for item in items:
            if item is not None and not value_matches(item, expected):
                raise ValueError(f"{self.node['id']}.{name}: 입력 타입은 {expected}이어야 합니다.")
        self.cache[name] = deepcopy(value)
        return self.cache[name]


def execution_signature(workflow, registry=None):
    if registry is None:
        from app.automation.registry import builtin_registry
        registry = builtin_registry()
    nodes = []
    for node in workflow["nodes"]:
        spec = registry.get(node["type"])
        normalized = {k: deepcopy(v) for k, v in node.items() if k != "position"}
        config = {**(deepcopy(spec.defaults) if spec else {}), **normalized.get("config", {})}
        if node["type"] == "logic.condition":
            for block in config.get("blocks", []):
                format_spec = registry.conditions.get(block.get("type"))
                block["config"] = {**(format_spec.defaults if format_spec else {}), **block.get("config", {})}
        normalized["config"] = config
        nodes.append(normalized)
    content = json.dumps({"nodes": nodes, "connections": workflow["connections"]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
