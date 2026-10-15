# seoul2line Toolbox

Windows용 Python 데스크톱 도구함입니다. Tkinter 기반의 한 화면 안에서 게임 실행, 개발 작업, 파일 관리, 네트워크 확인, 미니게임과 샌드박스를 함께 제공합니다.

## 빠른 시작

### 요구 사항

- Windows
- Python 3.11 이상 권장
- `tkinter`가 포함된 Python 설치

### 설치 및 실행

```powershell
py -m pip install -r requirements.txt
py main.py
```

또는 Windows 탐색기에서 `run.bat`을 실행합니다.

## Windows 설치 파일 만들기

로컬에서 Inno Setup 설치 후 다음 명령을 실행하면 `release/seoul2line-toolbox-setup.exe`가 생성됩니다.

```powershell
pwsh -ExecutionPolicy Bypass -File installer\build.ps1
```

GitHub에 올린 뒤 `v1.0.0` 같은 태그를 push하면 GitHub Actions가 PyInstaller로 실행 파일을 만들고 Inno Setup 설치 파일을 Release에 자동으로 첨부합니다. 수동 실행은 Actions의 `Windows installer` 워크플로에서 가능합니다.

처음 실행하면 `user_data` 폴더와 설정 파일이 생성될 수 있습니다. 외부 프로그램 실행·파일 삭제·네트워크 기능은 사용자가 입력한 경로와 권한의 영향을 받습니다.

## 메뉴와 주요 도구

### 홈

- 개요와 빠른 시작
- 시스템 모니터

### 게임

- 게임 실행기: Valorant, Minecraft, Steam 실행 경로 관리
- 배경음악
- 작업공간 프리셋

### 개발자

- Minecraft Toolkit: 커맨드 조합, 선택자·execute·tellraw·give·summon·scoreboard 생성
- 코드 편집기
- Git / GitHub 도구
- 통합 터미널
- 개발자 변환기
- 스크래치패드

### 네트워크

- 네트워크 상태와 ping 확인
- Same-WiFi LAN 통합 도구

### 파일

- 파일 관리자
- 클립보드 기록
- 파일 비교 / Diff
- 프로세스 관리자
- 영역 캡처
- 파일 형식 변환: 이미지, 미디어, 문서, 데이터, 압축 파일 변환
- CUR / ANI 커서 편집기: 프레임 수정, 밝기·대비·회색조·반전, CUR·ANI 저장

### 미니게임

- 미니게임 허브
- GPU 항성계 시뮬레이터
- TRSim
- 공장 자동화
- Micro Warfare: 2D RTS 전장, A* 이동, 채굴·건설·생산, 자동 교전과 적 경제·전략 AI, 3가지 게임 모드, 저장·불러오기 및 전투 통계
- Orbit Lab: 2D 우주 공간, 천체·위성 생성과 질량 설정, 만유인력 시뮬레이션, 시간 제어 및 우주선 발사·추력 제어
- 한국 주식

### 설정

- 테마, 단축키, 실행 경로 설정

도구는 `app/tool_registry.py`가 `app/tools`를 자동 탐색하고 각 모듈의 `register()`를 호출해 등록합니다. 도구를 추가해도 메인 창에 별도 목록을 직접 수정할 필요가 없습니다.

## 공통 사용법

- `Ctrl+K`: 커맨드 팔레트 열기
- 왼쪽 메뉴: 섹션과 도구 전환
- 다크/라이트 테마: 설정 메뉴에서 변경
- 지갑: 미니게임에서 사용하는 툴코인 잔액 표시

도구 화면은 선택된 순간 생성됩니다. 따라서 사용하지 않는 도구의 갱신 루프가 계속 CPU를 사용하는 것을 피할 수 있습니다. 단, 한국 주식 가격 엔진은 앱 전체에서 공유되며 상단의 가격 갱신 버튼으로 시작·중지합니다.

## 데이터 저장

| 경로 | 내용 |
| --- | --- |
| `user_data/config.json` | 테마, 단축키, 실행 경로, 지갑, 공장 자동화 등 일반 설정 |
| `user_data/stocks.db` | 한국 주식 가격, history, 보유 수량, 평균 매입가, 거래 이력 |
| `user_data/` | 캡처·수신 파일 등 사용자 생성 데이터 |

주식 데이터는 SQLite로 저장됩니다. 가격 엔진은 SQLite WAL과 busy timeout을 사용하며, 저장 실패가 발생하면 재시도 후 화면 상태에 오류를 표시합니다. `config.json`의 기존 한국 주식 데이터는 최초 마이그레이션 이후 `stocks.db`로 이동합니다.

사용자 데이터를 초기화하거나 백업하기 전에는 앱을 종료해 진행 중인 저장 작업이 끝났는지 확인하세요. `config.json`과 `stocks.db`는 함께 백업해야 지갑과 주식 상태를 같은 시점으로 복원할 수 있습니다.

## 개발 구조

```text
main.py                    앱 시작점
app/main_window.py         메인 창, 메뉴, 공통 지갑, 전역 가격 엔진
app/tool_registry.py       도구 자동 검색과 등록
app/plugin_system.py       외부 플러그인 검색·검증·로딩
app/config.py              JSON 설정 로드·병합·저장
app/economy.py             툴코인 지갑 기능
app/ui.py                  공통 Tkinter UI 컴포넌트
app/tools/                 실제 도구 모듈
plugins/                   프로젝트에 포함하는 플러그인과 예제
app/games/                 게임별 로직과 렌더러
app/assets/                이미지 등 정적 리소스
docs/                      구조, 사양, 개발 참고 문서
user_data/                 실행 중 생성되는 사용자 데이터
```

### 새 도구 추가

`app/tools/example.py`를 만들고 `register()`에서 `ToolSpec`을 등록합니다.

```python
import tkinter as tk
from app.tool_registry import ToolSpec


def build(parent: tk.Widget, app: object) -> tk.Widget:
    frame = tk.Frame(parent)
    tk.Label(frame, text="내 도구").pack()
    return frame


def register(registry) -> None:
    registry.register(ToolSpec(
        "developer.example",
        "내 도구",
        "개발자",
        build,
        50,
    ))
```

도구에서 백그라운드 작업을 사용할 때는 Tkinter 위젯을 작업 스레드에서 직접 변경하지 말고 `after()`를 이용해 UI 스레드에서 반영합니다. 종료 시 스레드와 `after()` 작업을 취소하고, 파일·프로세스·네트워크 입력은 실패 가능한 작업으로 취급해야 합니다.

### 외부 플러그인 추가

설정의 `ZIP 파일 선택하기` 버튼으로 플러그인 ZIP을 고르고 안전 경고를 확인하면 `user_data/plugins/plugin_<id>/`에 압축을 해제하고 바로 불러옵니다. `plugin.json`은 ZIP 최상위 또는 바로 아래 플러그인 폴더에 있어야 합니다. 기존 플러그인은 덮어쓰지 않습니다.

외부 확장은 `plugins/` 또는 사용자별 `user_data/plugins/` 아래에 폴더 단위로 추가합니다. 폴더에는 `plugin.json`과 `plugin.py`가 필요하며, `plugin.py`의 `register(registry)`에서 `SectionSpec`으로 왼쪽 최상위 메뉴를, `ToolSpec`으로 도구를, `MenuSpec`으로 메뉴 액션을 등록합니다. `SectionSpec`은 `Home`, `Game`, `Developer`처럼 사이드바에 표시되는 카테고리입니다. `MenuSpec`은 섹션 왼쪽 목록과 `Ctrl+K` 커맨드 팔레트에 표시됩니다. 앱 설정 화면의 `플러그인 다시 검색`으로 즉시 반영할 수 있습니다. 비활성화된 플러그인과 로딩 오류는 설정 화면에서 상태를 확인할 수 있습니다.

플러그인은 앱 프로세스 안에서 실행되므로 신뢰할 수 있는 코드만 설치해야 합니다. 전체 형식과 예제는 `plugins/README.md`를 참고하세요.

## 검증

현재 저장소에는 전체 자동화 테스트 스위트가 아직 없습니다. 변경 후 최소한 다음을 실행합니다.

```powershell
py -m py_compile app\main_window.py app\config.py app\tools\minigame_korean_stocks.py
```

GUI 변경은 실제 창에서 메뉴 전환, 빠른 시작·중지, 앱 종료, 창 크기 변경까지 확인해야 합니다. 주식 도구는 매수·매도, 시장 초기화, SQLite 저장 실패, DB 잠금, 상승장·하락장·횡보장을 함께 확인합니다.

## 문제 해결

- `ModuleNotFoundError`: `py -m pip install -r requirements.txt`를 다시 실행합니다.
- Tkinter 창이 열리지 않음: tkinter가 포함된 Python 설치를 사용하고 Windows 디스플레이 세션에서 실행합니다.
- 주식 가격이 갱신되지 않음: 상단 가격 갱신 버튼 상태와 주식 도구의 오류 메시지를 확인합니다.
- 설정이 초기화됨: 앱 종료 후 `user_data/config.json`의 백업을 확인합니다.
- 주식 상태가 이상함: 앱을 종료한 뒤 `user_data/stocks.db`를 백업하고, 복구가 필요하면 TODO의 DB 검증·백업 절차를 먼저 진행합니다.

## 문서

- [개발 참고](docs/한국어_개발_참고.md)
- [관리자 구조도](docs/관리자 구조도.md)
- [전체 사양](docs/SPECIFICATION.md)
- [변경 기록](docs/CHANGE_LOG.md)
- [TODO](docs/TODO.md)
