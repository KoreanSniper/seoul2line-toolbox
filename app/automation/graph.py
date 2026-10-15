import math
from collections import deque
from app.automation.conditions import migrate_workflow, validate_condition
from app.automation.ports import compatible, missing, value_matches


def validate(workflow, registry):
    """Validate both graph kinds. A flow join runs once after active parents.

    Data edges never activate a node; every data producer must be an ancestor
    in the flow graph, ensuring deterministic input resolution.
    """
    errors = []
    if not isinstance(workflow, dict) or workflow.get("schema_version") != 1:
        return ["지원하지 않는 워크플로 형식입니다."]
    workflow = migrate_workflow(workflow)
    if not isinstance(workflow.get("id"), str) or not workflow["id"]:
        errors.append("워크플로 ID가 필요합니다.")
    nodes, connections = workflow.get("nodes"), workflow.get("connections")
    if not isinstance(nodes, list) or not isinstance(connections, list):
        return errors + ["nodes와 connections는 목록이어야 합니다."]
    if not nodes or len(nodes) > 200 or len(connections) > 2000:
        errors.append("노드는 1~200개, 연결은 최대 2000개까지 허용됩니다.")
    by_id, specs = {}, {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            errors.append("잘못된 노드 ID입니다.")
            continue
        nid = node["id"]
        if nid in by_id:
            errors.append(f"중복 노드 ID: {nid}")
        by_id[nid] = node
        type_id = node.get("type", "")
        if not isinstance(type_id, str):
            errors.append(f"{nid}: 잘못된 노드 타입입니다.")
            specs[nid] = None
            continue
        spec = registry.get(type_id)
        specs[nid] = spec
        if not spec:
            errors.append(f"{nid}: 사용 불가 노드 {node.get('type')}")
            continue
        config = node.get("config", {})
        if not isinstance(config, dict):
            errors.append(f"{nid}: config는 객체여야 합니다.")
            continue
        if type_id == "logic.condition":
            errors.extend(f"{nid}: {error}" for error in validate_condition(config, registry.conditions))
        for key in spec.required_config:
            if not isinstance(config.get(key), str) or not config[key].strip():
                errors.append(f"{nid}: {key} 설정이 필요합니다.")
        if node["type"] == "file.convert_image" and (not isinstance(config.get("format"), str) or config["format"] not in {"png", "webp", "jpg", "jpeg", "bmp", "gif", "tiff", "tif", "ico"}):
            errors.append(f"{nid}: 지원하지 않는 이미지 형식입니다.")
        if "recursive" in config and not isinstance(config["recursive"], bool):
            errors.append(f"{nid}: recursive는 Boolean이어야 합니다.")
        position = node.get("position", [0, 0])
        if not isinstance(position, list) or len(position) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in position):
            errors.append(f"{nid}: 잘못된 위치입니다.")
    graph = {nid: set() for nid in by_id}
    flows = {nid: set() for nid in by_id}
    occupied, seen, data_edges = set(), set(), []
    for edge in connections:
        if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) for k in ("from_node", "from_port", "to_node", "to_port")):
            errors.append("잘못된 연결입니다.")
            continue
        a, b = edge["from_node"], edge["to_node"]
        sa, sb = specs.get(a), specs.get(b)
        if a not in by_id or b not in by_id or not sa or not sb:
            errors.append("연결된 노드를 사용할 수 없습니다.")
            continue
        if not isinstance(by_id[a].get("config", {}), dict) or not isinstance(by_id[b].get("config", {}), dict):
            continue
        out, inp = registry.outputs_for(by_id[a]).get(edge["from_port"]), registry.inputs_for(by_id[b]).get(edge["to_port"])
        if not out or not inp or not compatible(out, inp):
            errors.append(f"{a} → {b}: 포트 타입이 호환되지 않습니다.")
            continue
        signature = tuple(edge[k] for k in ("from_node", "from_port", "to_node", "to_port"))
        if signature in seen:
            errors.append("중복 연결입니다.")
        seen.add(signature)
        graph[a].add(b)
        if inp.type == "Flow":
            flows[a].add(b)
        else:
            key = (b, edge["to_port"])
            if key in occupied and not inp.allows_multiple:
                errors.append(f"{b}: 데이터 입력은 하나의 연결만 허용됩니다.")
            occupied.add(key)
            data_edges.append((a, b))
    order = topological(graph)
    if order is None:
        errors.append("순환 연결은 허용되지 않습니다.")
    def reachable(start):
        found, todo = set(), [start]
        while todo:
            for child in flows[todo.pop()]:
                if child not in found:
                    found.add(child)
                    todo.append(child)
        return found
    descendants = {nid: reachable(nid) for nid in by_id}
    triggers = [nid for nid, n in by_id.items() if isinstance(n.get("type"), str) and n["type"].startswith("trigger.")]
    if not triggers:
        errors.append("트리거가 필요합니다.")
    activated = set(triggers)
    for nid in triggers:
        activated.update(descendants[nid])
    for a, b in data_edges:
        if b not in descendants[a]:
            errors.append(f"{a} → {b}: 데이터 공급자는 실행 경로의 앞에 있어야 합니다.")
    for nid, spec in specs.items():
        if not spec:
            continue
        if nid not in activated:
            errors.append(f"{nid}: 트리거에서 연결되지 않았습니다.")
        config = by_id[nid].get("config", {})
        if not isinstance(config, dict):
            continue
        for key, port in registry.inputs_for(by_id[nid]).items():
            if port.type == "Flow" or (nid, key) in occupied:
                continue
            value = registry.input_default(by_id[nid], key)
            if port.required and missing(value, port):
                errors.append(f"{nid}: 필수 입력 {key}가 없습니다.")
            elif value is not None and not value_matches(value, port.type):
                errors.append(f"{nid}: {key} 입력 타입은 {port.type}이어야 합니다.")
    return errors


def topological(graph):
    degree = dict.fromkeys(graph, 0)
    for children in graph.values():
        for child in children:
            degree[child] += 1
    todo = deque(n for n, d in degree.items() if not d)
    order = []
    while todo:
        node = todo.popleft()
        order.append(node)
        for child in sorted(graph[node]):
            degree[child] -= 1
            if not degree[child]:
                todo.append(child)
    return order if len(order) == len(graph) else None
