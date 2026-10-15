"""Condition format registry, expression trees and dynamic port maintenance.

Condition blocks are data, never executable graph nodes. External connections
target '<block-id>.<input-name>'; expressions refer to stable block IDs.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import operator
from pathlib import Path
import re
from typing import Callable
import uuid

from app.automation.ports import Port, compatible, missing, value_matches


COMPARISONS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
               "le": operator.le, "gt": operator.gt, "ge": operator.ge}


@dataclass(frozen=True)
class ConditionSpec:
    id: str
    label: str
    inputs: dict[str, Port]
    evaluator: Callable
    defaults: dict = field(default_factory=dict)
    operators: tuple[str, ...] = ()


class ConditionRegistry:
    def __init__(self):
        self.specs = {}

    def register(self, spec):
        if spec.id in self.specs:
            raise ValueError(f"중복 조건 형식: {spec.id}")
        self.specs[spec.id] = spec

    def get(self, type_id):
        return self.specs.get(type_id) if isinstance(type_id, str) else None


def builtin_conditions():
    registry = ConditionRegistry()
    file_path = {"file_path": Port("FilePath", True)}
    specs = (
        ConditionSpec("always_true", "항상 참", {}, lambda v, c: True),
        ConditionSpec("always_false", "항상 거짓", {}, lambda v, c: False),
        ConditionSpec("file.extension", "파일 확장자 비교", file_path,
                      lambda v, c: COMPARISONS[c["operator"]](Path(v["file_path"]).suffix.lower(), "." + c["extension"].lower().lstrip(".")),
                      {"extension": "png", "operator": "eq"}, ("eq", "ne")),
        ConditionSpec("file.exists", "파일 존재 여부", file_path,
                      lambda v, c: Path(v["file_path"]).expanduser().is_file() == (c["operator"] == "exists"),
                      {"operator": "exists"}, ("exists", "missing")),
        ConditionSpec("file.size", "파일 크기 비교 (바이트)", {**file_path, "threshold": Port("Number", True)},
                      lambda v, c: COMPARISONS[c["operator"]](Path(v["file_path"]).expanduser().stat().st_size, v["threshold"]),
                      {"threshold": 10485760, "operator": "le"}, tuple(COMPARISONS)),
        ConditionSpec("string.compare", "문자열 비교", {"a": Port("String", True), "b": Port("String", True)},
                      lambda v, c: (v["b"] in v["a"] if c["operator"] == "contains" else v["a"].startswith(v["b"]) if c["operator"] == "starts_with" else COMPARISONS[c["operator"]](v["a"], v["b"])),
                      {"a": "", "b": "", "operator": "eq"}, ("eq", "ne", "contains", "starts_with")),
        ConditionSpec("number.compare", "숫자 비교", {"a": Port("Number", True), "b": Port("Number", True)},
                      lambda v, c: COMPARISONS[c["operator"]](v["a"], v["b"]),
                      {"a": 0, "b": 0, "operator": "eq"}, tuple(COMPARISONS)),
        ConditionSpec("boolean.check", "Boolean 검사", {"value": Port("Boolean", True)},
                      lambda v, c: v["value"] if c["operator"] == "is_true" else not v["value"],
                      {"value": True, "operator": "is_true"}, ("is_true", "is_false")),
    )
    for spec in specs:
        registry.register(spec)
    return registry


def new_block(type_id="always_true", registry=None):
    spec = (registry or builtin_conditions()).get(type_id)
    return {"id": "c_" + uuid.uuid4().hex[:8], "type": type_id,
            "config": deepcopy(spec.defaults) if spec else {}}


def default_condition():
    block = new_block()
    return {"blocks": [block], "expression": {"block": block["id"]}}


def blocks(config):
    value = config.get("blocks", [])
    return value if isinstance(value, list) else []


def dynamic_inputs(config, registry):
    result = {"flow_in": Port("Flow")}
    for block in blocks(config):
        if not isinstance(block, dict) or not isinstance(block.get("id"), str):
            continue
        spec = registry.get(block.get("type"))
        if spec:
            result.update({f"{block['id']}.{key}": port for key, port in spec.inputs.items()})
    return result


def input_default(config, key, registry):
    block_id, name = key.split(".", 1)
    block = next((b for b in blocks(config) if isinstance(b, dict) and b.get("id") == block_id), None)
    if block is None:
        return None
    spec = registry.get(block.get("type"))
    settings = block.get("config", {})
    return {**(spec.defaults if spec else {}), **(settings if isinstance(settings, dict) else {})}.get(name)


def expression_errors(expression, block_ids):
    errors, count = [], 0
    def visit(tree, depth=0):
        nonlocal count
        count += 1
        if depth > 16 or count > 256:
            errors.append("조건식 크기/중첩 제한을 초과했습니다.")
            return
        if not isinstance(tree, dict):
            errors.append("잘못된 조건식 트리입니다.")
            return
        if "block" in tree:
            if set(tree) != {"block"} or not isinstance(tree["block"], str) or tree["block"] not in block_ids:
                errors.append("조건식이 알 수 없는 조건 블록을 참조합니다.")
            return
        op, children = tree.get("op"), tree.get("children")
        if not isinstance(op, str) or op not in {"and", "or", "not"} or not isinstance(children, list) or not children or (op == "not" and len(children) != 1):
            errors.append("AND/OR에는 1개 이상, NOT에는 정확히 1개의 하위 조건이 필요합니다.")
            return
        if len(children) > 64:
            errors.append("한 연산자에는 최대 64개 하위 조건을 허용합니다.")
            return
        for child in children:
            visit(child, depth + 1)
    visit(expression)
    return errors


def validate_condition(config, registry):
    errors, ids = [], set()
    items = config.get("blocks")
    if not isinstance(items, list) or not 1 <= len(items) <= 64:
        return ["조건 형식 블록은 1~64개가 필요합니다."]
    for block in items:
        if not isinstance(block, dict) or not isinstance(block.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", block["id"]):
            errors.append("잘못된 조건 블록 ID입니다.")
            continue
        if block["id"] in ids:
            errors.append("중복 조건 블록 ID입니다.")
        ids.add(block["id"])
        spec = registry.get(block.get("type"))
        if not spec:
            errors.append(f"사용 불가 조건 형식: {block.get('type')}")
            continue
        if not isinstance(block.get("config", {}), dict):
            errors.append(f"{block['id']}: 조건 설정은 객체여야 합니다.")
            continue
        settings = {**spec.defaults, **block.get("config", {})}
        if spec.operators and settings.get("operator") not in spec.operators:
            errors.append(f"{block['id']}: 잘못된 비교 연산자입니다.")
        if spec.id == "file.extension" and (not isinstance(settings.get("extension"), str) or not settings["extension"].strip().lstrip(".")):
            errors.append(f"{block['id']}: 확장자가 필요합니다.")
    errors.extend(expression_errors(config.get("expression"), ids))
    passthrough = config.get("passthrough")
    if passthrough is not None and (not isinstance(passthrough, str) or dynamic_inputs(config, registry).get(passthrough) != Port("FilePath", True)):
        errors.append("잘못된 이전 버전 파일 경로 전달 포트입니다.")
    return errors


def evaluate(config, registry, resolve, check=None):
    errors = validate_condition(config, registry)
    if errors:
        raise ValueError("\n".join(errors))
    by_id = {b["id"]: b for b in config["blocks"]}
    results = {}
    def leaf(block_id):
        if check:
            check()
        if block_id in results:
            return results[block_id]
        block = by_id[block_id]
        spec = registry.get(block["type"])
        settings = {**spec.defaults, **block.get("config", {})}
        values = {}
        for name, port in spec.inputs.items():
            value = resolve(f"{block_id}.{name}")
            if port.required and missing(value, port):
                raise ValueError(f"{block_id}.{name}: 필수 조건 입력이 없습니다.")
            if value is not None and not value_matches(value, port.type):
                raise ValueError(f"{block_id}.{name}: {port.type} 입력 타입이 아닙니다.")
            values[name] = value
        result = spec.evaluator(values, settings)
        if not isinstance(result, bool):
            raise ValueError(f"{block_id}: 조건 평가 결과는 Boolean이어야 합니다.")
        results[block_id] = result
        return result
    def visit(tree):
        if "block" in tree:
            return leaf(tree["block"])
        if tree["op"] == "and":
            return all(visit(child) for child in tree["children"])
        if tree["op"] == "or":
            return any(visit(child) for child in tree["children"])
        return not visit(tree["children"][0])
    return visit(config["expression"])


def prune_expression(tree, removed_id):
    if not isinstance(tree, dict):
        return tree
    if "block" in tree:
        return None if tree["block"] == removed_id else tree
    children = [prune_expression(child, removed_id) for child in tree.get("children", [])]
    children = [child for child in children if child is not None]
    return {**tree, "children": children} if children else None


def update_block(workflow, node_id, block_id, type_id, registry):
    """Return a reviewable new graph and removed edges; never mutate the caller."""
    updated = deepcopy(workflow)
    node = next(n for n in updated["nodes"] if n["id"] == node_id)
    block = next(b for b in node["config"]["blocks"] if b["id"] == block_id)
    spec = registry.conditions.get(type_id)
    if spec is None:
        raise ValueError("알 수 없는 조건 형식입니다.")
    old = registry.conditions.get(block.get("type"))
    config = deepcopy(spec.defaults)
    old_config = block.get("config", {})
    old_config = old_config if isinstance(old_config, dict) else {}
    for key, value in old_config.items():
        if key in spec.inputs and old and key in old.inputs and old.inputs[key].type == spec.inputs[key].type and value_matches(value, spec.inputs[key].type):
            config[key] = value
        elif key in spec.defaults and key not in spec.inputs and key != "operator" and type(value) is type(spec.defaults[key]):
            config[key] = value
    if old_config.get("operator") in spec.operators:
        config["operator"] = old_config["operator"]
    block.update(type=type_id, config=config)
    passthrough = node["config"].get("passthrough")
    port = registry.inputs_for(node).get(passthrough) if isinstance(passthrough, str) else None
    if passthrough and (not port or port.type != "FilePath"):
        node["config"].pop("passthrough")
    removed = reconcile_connections(updated, node_id, registry, block_id)
    return updated, removed


def reconcile_connections(workflow, node_id, registry, block_id=None):
    nodes = {n["id"]: n for n in workflow["nodes"]}
    ports = registry.inputs_for(nodes[node_id])
    kept, removed = [], []
    for edge in workflow["connections"]:
        if edge["from_node"] == node_id and edge["from_port"] not in registry.outputs_for(nodes[node_id]):
            removed.append(edge)
            continue
        if edge["to_node"] != node_id:
            kept.append(edge)
            continue
        if block_id is not None and not edge["to_port"].startswith(block_id + "."):
            kept.append(edge)
            continue
        source = nodes.get(edge["from_node"])
        output = registry.outputs_for(source).get(edge["from_port"]) if source else None
        inp = ports.get(edge["to_port"])
        # Preserve unknown formats and their edges until the user changes them.
        if not output or not inp or not compatible(output, inp):
            removed.append(edge)
        else:
            kept.append(edge)
    workflow["connections"] = kept
    return removed


def migrate_workflow(workflow):
    result = deepcopy(workflow)
    if not isinstance(result, dict) or not isinstance(result.get("nodes"), list):
        return result
    migrated = {}
    for node in result["nodes"]:
        if not isinstance(node, dict) or node.get("type") != "logic.extension" or not isinstance(node.get("config", {}), dict):
            continue
        old = node.get("config", {})
        block_id = "legacy_extension"
        settings = {"extension": old.get("extension", "png"), "operator": "eq"}
        if "source_path" in old:
            settings["file_path"] = old["source_path"]
        node["type"] = "logic.condition"
        node["config"] = {"blocks": [{"id": block_id, "type": "file.extension", "config": settings}],
                          "expression": {"block": block_id}, "passthrough": f"{block_id}.file_path",
                          "legacy_config": old}
        migrated[node["id"]] = block_id
    for edge in result.get("connections", []):
        if isinstance(edge, dict) and isinstance(edge.get("to_node"), str) and edge["to_node"] in migrated:
            if edge.get("to_port") == "flow":
                edge["to_port"] = "flow_in"
            elif edge.get("to_port") == "source_path":
                edge["to_port"] = f"{migrated[edge['to_node']]}.file_path"
    return result
