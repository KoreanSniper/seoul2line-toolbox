from app.tool_registry import MenuSpec, SectionSpec


def open_example(app: object) -> None:
    for tool in app.registry.tools_for("플러그인"):
        if tool.id == "example_plugin.demo":
            app.show_tool_from_palette(tool)
            return


def register(registry) -> None:
    registry.register_section(SectionSpec("플러그인", "P", "예제 플러그인이 제공하는 메뉴", 60))
    registry.register_menu(MenuSpec("example_plugin.menu", "예제 메뉴 실행", "플러그인", open_example, 0))
