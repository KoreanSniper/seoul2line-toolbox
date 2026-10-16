from pathlib import Path
import shutil
import threading
import time

from app.automation.graph import topological, validate
from app.services.images import convert_image
from app.automation.conditions import evaluate, migrate_workflow
from app.automation.data import InputResolver, execution_signature
from app.file_ops import retry_on_windows_lock


class Cancelled(Exception):
    pass


def reserve_target(directory, name):
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    base = Path(name)
    for index in range(10000):
        candidate = directory / (base.name if index == 0 else f"{base.stem}_{index}{base.suffix}")
        try:
            with candidate.open("xb"):
                pass
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("출력 파일 이름을 확보할 수 없습니다.")


class WorkflowExecutor:
    def __init__(self, registry):
        self.registry = registry

    def execute(self, workflow, trigger_id, payload=None, cancel=None, emit=None):
        workflow = migrate_workflow(workflow)
        errors = validate(workflow, self.registry)
        if errors:
            raise ValueError("\n".join(errors))
        cancel = cancel or threading.Event()
        emit = emit or (lambda *args: None)
        nodes = {n["id"]: n for n in workflow["nodes"]}
        if trigger_id not in nodes or not nodes[trigger_id]["type"].startswith("trigger."):
            raise ValueError("실행할 트리거를 찾을 수 없습니다.")
        graph = {nid: set() for nid in nodes}
        for edge in workflow["connections"]:
            graph[edge["from_node"]].add(edge["to_node"])
        active, values, completed = {trigger_id}, {}, []
        signature = execution_signature(workflow, self.registry)
        started = time.monotonic()
        for nid in topological(graph):
            if cancel.is_set():
                raise Cancelled("사용자가 실행을 중지했습니다.")
            if time.monotonic() - started > 300:
                raise RuntimeError("실행 제한 시간(300초)을 초과했습니다.")
            if nid not in active:
                continue
            node = nodes[nid]
            spec = self.registry.get(node["type"])
            config = {**spec.defaults, **node.get("config", {})}
            resolver = InputResolver(node, workflow, self.registry, values)
            emit("log", f"{nid}: {self.registry.get(node['type']).label}")
            if node["type"] == "logic.condition":
                def check_condition():
                    if cancel.is_set():
                        raise Cancelled("사용자가 실행을 중지했습니다.")
                    if time.monotonic() - started > 300:
                        raise RuntimeError("실행 제한 시간(300초)을 초과했습니다.")
                result = evaluate(config, self.registry.conditions, resolver.get, check=check_condition)
                outputs, branch = {"result": result}, "true" if result else "false"
                if config.get("passthrough"):
                    outputs["file_path"] = resolver.get(config["passthrough"])
                emit("log", f"{nid}: 조건 결과 {result}")
            else:
                for name, port in self.registry.inputs_for(node).items():
                    if port.type != "Flow":
                        config[name] = resolver.get(name)
                outputs, branch = self._run(node["type"], config, payload or {}, cancel, emit)
            values[nid] = outputs
            emit("outputs", {"node_id": nid, "outputs": outputs, "signature": signature})
            completed.append(nid)
            for edge in workflow["connections"]:
                if edge["from_node"] == nid and edge["from_port"] == branch:
                    active.add(edge["to_node"])
        if cancel.is_set():
            raise Cancelled("사용자가 실행을 중지했습니다.")
        return {"completed": completed, "outputs": values}

    def _run(self, type_id, config, payload, cancel, emit):
        if type_id.startswith("trigger."):
            path = payload.get("file_path", config.get("file_path", ""))
            return {"file_path": str(path)}, "flow"
        if type_id == "data.files":
            return {"files": config["files"]}, "flow"
        if type_id.startswith("file."):
            source = Path(config["source_path"]).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {source}")
            name = source.with_suffix("." + config["format"]).name if type_id == "file.convert_image" else source.name
            target = reserve_target(config["output_dir"], name)
            try:
                if cancel.is_set():
                    raise Cancelled("실행 중지")
                if type_id == "file.convert_image":
                    convert_image(source, target, config["format"])
                else:
                    # Copy completely before removing a source, including across volumes.
                    convert_copy(source, target)
                    if type_id == "file.move":
                        source.unlink()
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return {"file_path": str(target)}, "flow"
        if type_id in {"output.notify", "output.log"}:
            emit("notify" if type_id == "output.notify" else "log", str(config.get("message", "완료")))
            return {}, "flow"
        spec = self.registry.get(type_id)
        if spec.handler:
            return spec.handler(config, cancel, emit), "flow"
        raise ValueError(f"실행할 수 없는 노드: {type_id}")


def convert_copy(source, target):
    import os
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix=".toolbox-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        shutil.copy2(source, temporary)
        retry_on_windows_lock(os.replace, temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
