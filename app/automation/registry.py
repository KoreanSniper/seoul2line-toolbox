from dataclasses import dataclass, field
from typing import Callable
from app.automation.ports import Port
from app.automation.conditions import builtin_conditions, default_condition, dynamic_inputs, input_default


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    category: str
    inputs: dict[str, Port]
    outputs: dict[str, Port]
    defaults: dict = field(default_factory=dict)
    required_config: tuple[str, ...] = ()
    handler: Callable | None = None


class NodeRegistry:
    def __init__(self):
        self.specs: dict[str, NodeSpec] = {}
        self.conditions = builtin_conditions()

    def register(self, spec: NodeSpec):
        if spec.id in self.specs:
            raise ValueError(f"중복 노드 타입: {spec.id}")
        self.specs[spec.id] = spec

    def get(self, type_id):
        return self.specs.get(type_id)

    def inputs_for(self, node):
        if node.get("type") == "logic.condition":
            return dynamic_inputs(node.get("config", {}), self.conditions)
        spec = self.get(node.get("type"))
        return spec.inputs if spec else {}

    def outputs_for(self, node):
        spec = self.get(node.get("type"))
        if not spec:
            return {}
        if node.get("type") == "logic.condition" and not node.get("config", {}).get("passthrough"):
            return {k: p for k, p in spec.outputs.items() if k != "file_path"}
        return spec.outputs

    def input_default(self, node, key):
        if node["type"] == "logic.condition":
            return input_default(node.get("config", {}), key, self.conditions)
        spec = self.get(node["type"])
        return {**(spec.defaults if spec else {}), **node.get("config", {})}.get(key)


def builtin_registry():
    registry = NodeRegistry()
    flow = {"flow": Port("Flow")}
    path = {"source_path": Port("FilePath", True)}
    for spec in (
        NodeSpec("trigger.manual", "수동 실행", "트리거", {}, {**flow, "file_path": Port("FilePath")}, {"file_path": ""}),
        NodeSpec("trigger.folder_created", "폴더 감시", "트리거", {}, {**flow, "file_path": Port("FilePath")}, {"path": "", "recursive": False}, ("path",)),
        NodeSpec("logic.extension", "파일 형식 조건", "논리·데이터", {**flow, **path}, {"true": Port("Flow"), "false": Port("Flow"), "file_path": Port("FilePath")}, {"extension": "png"}, ("extension",)),
        NodeSpec("logic.condition", "Condition · 통합 조건", "논리·데이터", {"flow_in": Port("Flow")}, {"true": Port("Flow"), "false": Port("Flow"), "result": Port("Boolean"), "file_path": Port("FilePath")}, default_condition()),
        NodeSpec("data.files", "파일 목록 합치기", "논리·데이터", {**flow, "files": Port("FileList")}, {**flow, "files": Port("FileList")}, {"files": []}),
        NodeSpec("file.convert_image", "이미지 변환", "파일", {**flow, **path}, {**flow, "file_path": Port("FilePath")}, {"format": "webp", "output_dir": ""}, ("format", "output_dir")),
        NodeSpec("file.move", "파일 이동", "파일", {**flow, **path}, {**flow, "file_path": Port("FilePath")}, {"output_dir": ""}, ("output_dir",)),
        NodeSpec("file.copy", "파일 복사", "파일", {**flow, **path}, {**flow, "file_path": Port("FilePath")}, {"output_dir": ""}, ("output_dir",)),
        NodeSpec("output.notify", "완료 알림", "출력", flow, flow, {"message": "자동화 작업이 완료되었습니다."}),
        NodeSpec("output.log", "로그", "출력", flow, flow, {"message": "작업 완료"}),
    ):
        registry.register(spec)
    return registry
