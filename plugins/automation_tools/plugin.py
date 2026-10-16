"""Bundled automation menus; execution and storage remain owned by the host."""
from app.automation.ui import Editor, Manager
from app.tool_registry import SectionSpec, ToolSpec


def build_history(parent, app):
    return Manager(parent, app, history=True)


def register(registry):
    registry.register_section(SectionSpec("자동화", "A", "노드를 연결하는 사용자 정의 자동화", 45))
    registry.register(ToolSpec("automation.editor", "워크플로 편집기", "자동화", Editor, 0))
    registry.register(ToolSpec("automation.history", "자동화 실행 기록", "자동화", build_history, 10))
    registry.register(ToolSpec("automation.manager", "자동화 관리", "자동화", Manager, 20))
