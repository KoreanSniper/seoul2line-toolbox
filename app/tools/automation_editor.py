from app.automation.ui import Editor
from app.tool_registry import SectionSpec, ToolSpec


def register(registry):
    registry.register_section(SectionSpec("자동화", "A", "노드를 연결하는 사용자 정의 자동화", 45))
    registry.register(ToolSpec("automation.editor", "워크플로 편집기", "자동화", Editor, 0))
