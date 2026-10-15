# seoul2line Toolbox plugins

설정 화면의 `ZIP 파일 선택하기`에서 플러그인 ZIP을 선택하고 안전 경고를 확인하면 `user_data/plugins/plugin_<id>/`에 자동 설치되고 즉시 불러옵니다. ZIP 최상위 또는 바로 아래의 플러그인 폴더에 `plugin.json`과 실행 코드가 있어야 합니다. 기존 ID나 폴더는 덮어쓰지 않으며, 암호화·링크·안전하지 않은 경로가 있는 ZIP은 거부합니다. ZIP은 파일 10,000개, 압축 해제 크기 256MB까지 지원합니다.

수동 설치 시에는 프로젝트의 `plugins/` 또는 사용자 데이터의 `user_data/plugins/` 아래에 플러그인 폴더를 만들고 설정 화면에서 `플러그인 다시 검색`을 누르면 등록됩니다.

```text
plugins/
  my_plugin/
    plugin.json
    plugin.py
    assets/
    menus/
      my_menu.py
    tools/
      my_tool.py
```

`plugin.json` 예시:

```json
{
  "id": "my_plugin",
  "name": "내 플러그인",
  "version": "1.0.0",
  "entrypoint": "plugin.py"
}
```

`plugin.py`는 선택적인 공통 진입점입니다. 플러그인 로더는 그 다음 `menus/*.py`와 `tools/*.py`를 자동으로 읽고 각 파일의 `register(registry)`를 호출합니다. `assets/`에는 이미지, 아이콘, 템플릿 같은 플러그인 리소스를 둡니다.

`menus/*.py` 파일은 사이드바 최상위 메뉴를 등록합니다.

```python
from app.tool_registry import SectionSpec


def register(registry) -> None:
    registry.register_section(SectionSpec("내 메뉴", "P", "플러그인이 제공하는 기능", 60))
```

`tools/*.py` 파일은 해당 메뉴의 도구를 등록합니다.

```python
import tkinter as tk
from app.tool_registry import MenuSpec, SectionSpec, ToolSpec


def build(parent: tk.Widget, app: object) -> tk.Widget:
    frame = tk.Frame(parent)
    tk.Label(frame, text="외부 플러그인 도구").pack(padx=20, pady=20)
    return frame


def register(registry) -> None:
    registry.register(ToolSpec("my_plugin.tool", "내 플러그인", "내 메뉴", build, 0))

    def open_menu(app) -> None:
        app.show_section("내 메뉴")

    registry.register_menu(MenuSpec("my_plugin.menu", "내 메뉴 열기", "내 메뉴", open_menu, 0))
```

`register_menu()`로 등록한 메뉴는 해당 섹션의 왼쪽 메뉴와 `Ctrl+K` 커맨드 팔레트에 표시됩니다. 액션 함수는 Toolbox 앱 인스턴스를 받아 다른 화면을 열거나 원하는 작업을 실행할 수 있습니다.

플러그인 코드는 앱 프로세스 안에서 실행됩니다. 신뢰할 수 있는 플러그인만 설치하고, 네트워크·파일·프로세스 권한은 플러그인 코드가 직접 사용하는 범위로 제한해야 합니다.

## 기본 Developer 메뉴

`plugins/developer_tools`는 기본 Developer 사이드바 메뉴를 플러그인으로 제공하는 예제입니다. 기본 도구 파일을 플러그인에서 재사용할 수도 있고, 완전히 새로운 도구 모듈을 플러그인 폴더 안에 함께 둘 수도 있습니다. 이 플러그인을 비활성화하면 Developer 메뉴와 그 안의 도구도 함께 사라집니다.
