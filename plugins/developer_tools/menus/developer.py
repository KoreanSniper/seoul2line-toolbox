from app.tool_registry import SectionSpec


def register(registry) -> None:
    # The developer sidebar entry belongs to this plugin so disabling it removes the whole menu.
    registry.register_section(SectionSpec("개발자", "D", "커맨드, 코드, Git 작업", 20))
