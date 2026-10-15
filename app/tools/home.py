import tkinter as tk

from app.tool_registry import ToolSpec, cards
from app.palette import palette


def build(parent: tk.Widget, app: object) -> tk.Widget:
    colors = palette(app.dark_mode)
    frame = tk.Frame(parent, bg=colors["panel"])
    body = tk.Frame(frame, bg=colors["panel"])
    body.pack(fill="both", expand=True, padx=14, pady=14)
    tk.Label(
        body,
        text="게임 실행, 마인크래프트 커맨드, 코드 편집, Git, 네트워크 확인, 파일 정리를 한곳에서 처리하는 가벼운 Python 도구함입니다.",
        fg=colors["muted"],
        bg=colors["panel"],
        font=("Segoe UI", 10),
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(0, 14))
    cards(
        body,
        [
            ("Ctrl+K 커맨드 팔레트", "어디서든 메뉴와 도구 이름을 검색해서 바로 이동합니다. 도구가 늘어날수록 핵심 탐색 방식이 됩니다."),
            ("가벼운 기본 구조", "Tkinter만 사용하고, 열지 않은 메뉴는 작업하지 않아서 메모리와 CPU 사용을 줄입니다."),
            ("확장 쉬운 메뉴", "app/tools에 파일을 추가하고 ToolSpec을 등록하면 새 메뉴나 도구가 자동으로 붙습니다."),
            ("원클릭 작업", "게임 실행, Git 버튼, 파일 단축키, 커맨드 생성 기능을 바로 사용할 수 있습니다."),
            ("확장 도구 추가됨", "시스템 모니터, 통합 터미널, 스크래치패드, 개발자 변환기, 프로세스 관리자, LAN 통합, 클립보드 기록, Diff를 사용할 수 있습니다."),
        ],
    ).pack(fill="x")
    return frame


def register(registry) -> None:
    registry.register(ToolSpec("home.overview", "개요", "홈", build, 0))
