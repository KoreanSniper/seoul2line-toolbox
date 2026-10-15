"""Plan atomic flow + data connections without executing or changing settings."""
from collections import deque
from copy import deepcopy

from app.automation.graph import topological
from app.automation.ports import compatible


EDGE_KEYS = ("from_node", "from_port", "to_node", "to_port")


def edge_key(edge):
    return tuple(edge[k] for k in EDGE_KEYS)


def flow_edges(workflow, registry):
    nodes = {n["id"]: n for n in workflow["nodes"]}
    for edge in workflow["connections"]:
        source, target = nodes.get(edge["from_node"]), nodes.get(edge["to_node"])
        if not source or not target:
            continue
        out = registry.outputs_for(source).get(edge["from_port"])
        inp = registry.inputs_for(target).get(edge["to_port"])
        if out and inp and out.type == inp.type == "Flow":
            yield edge


def default_flow_port(ports, output=False):
    names = [name for name, port in ports.items() if port.type == "Flow"]
    for preferred in (("flow", "true") if output else ("flow_in", "flow")):
        if preferred in names:
            return preferred
    if len(names) == 1:
        return names[0]
    raise ValueError("실행 포트를 고급 모드에서 선택하세요.")


def ancestors(workflow, registry, start):
    parents = {n["id"]: [] for n in workflow["nodes"]}
    for edge in flow_edges(workflow, registry):
        parents[edge["to_node"]].append(edge["from_node"])
    result, todo = {}, deque([(start, 0)])
    while todo:
        node_id, distance = todo.popleft()
        if node_id in result:
            continue
        result[node_id] = distance
        todo.extend((parent, distance + 1) for parent in parents.get(node_id, []))
    return result


def infer_output(workflow, registry, source_id, input_name, input_port):
    nodes = {n["id"]: n for n in workflow["nodes"]}
    candidates = []
    for node_id, distance in ancestors(workflow, registry, source_id).items():
        for name, port in registry.outputs_for(nodes[node_id]).items():
            if port.type == "Flow" or not compatible(port, input_port):
                continue
            leaf_name = input_name.rsplit(".", 1)[-1]
            match = 3 if name == leaf_name else 0
            if input_port.type in {"FilePath", "FileList"}:
                match += 2 if name in {"file_path", "files"} else 0
            match += 1 if port.type == input_port.type else 0
            candidates.append(((distance, -match), node_id, name))
    if not candidates:
        return None, "호환 출력 없음"
    best = min(rank for rank, _, _ in candidates)
    winners = [(node_id, name) for rank, node_id, name in candidates if rank == best]
    return (winners[0], None) if len(winners) == 1 else (None, "호환 출력이 여러 개임")


def connect_nodes(workflow, registry, source_id, target_id, from_port=None, to_port=None, auto_data=True):
    """Return (new workflow, added edges, unresolved inputs), preserving bindings.

    Nearest flow ancestors provide data when a Condition has no file output.
    Manual comparison constants are retained. Ambiguous outputs are never guessed.
    The whole plan, including inferred edges, must remain acyclic.
    """
    updated = deepcopy(workflow)
    nodes = {n["id"]: n for n in updated["nodes"]}
    if source_id not in nodes or target_id not in nodes or source_id == target_id:
        raise ValueError("서로 다른 두 노드를 연결하세요.")
    source, target = nodes[source_id], nodes[target_id]
    outputs, inputs = registry.outputs_for(source), registry.inputs_for(target)
    from_port = from_port or default_flow_port(outputs, output=True)
    to_port = to_port or default_flow_port(inputs)
    out, inp = outputs.get(from_port), inputs.get(to_port)
    if not out or not inp or out.type != "Flow" or inp.type != "Flow":
        raise ValueError("호환되는 실행 포트가 필요합니다.")
    flow = dict(zip(EDGE_KEYS, (source_id, from_port, target_id, to_port)))
    signatures = {edge_key(edge) for edge in updated["connections"]}
    added, unresolved = [], []
    if edge_key(flow) not in signatures:
        updated["connections"].append(flow)
        added.append(flow)
    if auto_data:
        for name, port in inputs.items():
            if port.type == "Flow":
                continue
            bindings = [e for e in updated["connections"] if e["to_node"] == target_id and e["to_port"] == name]
            if bindings and not port.allows_multiple:
                continue
            manual = registry.input_default(target, name)
            if port.type not in {"FilePath", "FileList"} and manual is not None and manual != "":
                continue  # Do not replace comparison constants by a previous result.
            choice, reason = infer_output(updated, registry, source_id, name, port)
            if not choice:
                if port.required and (manual is None or manual == ""):
                    unresolved.append(f"{name}: {reason} · 고급 모드에서 선택하세요.")
                continue
            node_id, output_name = choice
            data = dict(zip(EDGE_KEYS, (node_id, output_name, target_id, name)))
            if edge_key(data) in signatures:
                continue
            data["auto_for"] = dict(flow)
            updated["connections"].append(data)
            signatures.add(edge_key(data))
            added.append(data)
    if len(updated["connections"]) > 2000:
        raise ValueError("연결은 최대 2000개까지 허용됩니다.")
    graph = {node_id: set() for node_id in nodes}
    for edge in updated["connections"]:
        if edge["from_node"] in nodes and edge["to_node"] in nodes:
            graph[edge["from_node"]].add(edge["to_node"])
    if topological(graph) is None:
        raise ValueError("순환 연결은 허용되지 않습니다.")
    return updated, added, unresolved


def repair_inputs(workflow, registry, node_id=None):
    updated, added, unresolved = prune_auto_connections(workflow, registry), [], []
    for edge in list(flow_edges(updated, registry)):
        if node_id is not None and edge["to_node"] != node_id:
            continue
        updated, changes, errors = connect_nodes(updated, registry, edge["from_node"], edge["to_node"], edge["from_port"], edge["to_port"])
        added.extend(changes)
        unresolved.extend(errors)
    return updated, added, list(dict.fromkeys(unresolved))


def prune_auto_connections(workflow, registry):
    updated = deepcopy(workflow)
    flow_keys = {edge_key(e) for e in flow_edges(updated, registry)}
    ancestry = {}
    kept = []
    for edge in updated["connections"]:
        owner = edge.get("auto_for")
        if isinstance(owner, dict) and all(isinstance(owner.get(key), str) for key in EDGE_KEYS):
            target = edge["to_node"]
            if target not in ancestry:
                ancestry[target] = ancestors(updated, registry, target)
            if edge_key(owner) not in flow_keys or edge["from_node"] == target or edge["from_node"] not in ancestry[target]:
                continue
        kept.append(edge)
    updated["connections"] = kept
    return updated


def disconnect(workflow, registry, index, simple=False):
    updated = deepcopy(workflow)
    removed = updated["connections"].pop(index)
    is_flow = any(edge_key(e) == edge_key(removed) for e in flow_edges(workflow, registry))
    if is_flow:
        def keep(edge):
            owner = edge.get("auto_for")
            if isinstance(owner, dict) and all(isinstance(owner.get(key), str) for key in EDGE_KEYS) and edge_key(owner) == edge_key(removed):
                return False
            if simple and (edge["from_node"], edge["to_node"]) == (removed["from_node"], removed["to_node"]):
                output = registry.outputs_for(next(n for n in updated["nodes"] if n["id"] == edge["from_node"])).get(edge["from_port"])
                if output and output.type != "Flow":
                    return False
            return True
        updated["connections"] = [edge for edge in updated["connections"] if keep(edge)]
    return prune_auto_connections(updated, registry)
