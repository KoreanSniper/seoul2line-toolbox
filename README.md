# seoul2line Toolbox

Windows용 Python 데스크톱 도구함입니다. Tkinter 기반의 한 화면 안에서 게임 실행, 개발 작업, 파일 관리, 네트워크 확인, 미니게임과 샌드박스를 함께 제공합니다.

[기능 목록](#기능-목록) · [설치 및 실행](#설치-및-실행) · [자동화 안내](docs/AUTOMATION.md)

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

일반 사용자는 [최신 설치 프로그램](https://github.com/KoreanSniper/seoul2line-toolbox/releases/latest)에서 EXE를 받으면 됩니다. Python 설치는 필요하지 않습니다. `update_installer.bat`도 최신 정식 릴리스를 받아 SHA-256·크기를 검증한 뒤 설치 화면을 엽니다.

소스에서 빌드하려면 Python 3.11 이상과 Inno Setup 6을 설치하고 다음 명령을 실행합니다. `release/seoul2line-toolbox-setup.exe`와 검증용 `release/update.json`이 생성됩니다.

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -InstallDependencies
# 또는 update_installer.bat --build
```

버전은 `app/version.py`의 `VERSION`에서 관리합니다. 해당 버전과 같은 `v2.0.1` 형식의 태그를 push하면 GitHub Actions가 빌드하고 실행 파일의 화면·메뉴·기본 플러그인 로딩을 검사한 뒤 설치 EXE와 `update.json`을 정식 Release에 게시합니다. Actions에서 수동 실행하면 배포 전 검토용 artifact만 생성됩니다.

설치본은 시작 시와 실행 중 6시간마다 새 버전을 백그라운드에서 확인합니다. 설치 확인을 누르면 다운로드·체크섬 검증 후 앱을 종료하고 같은 폴더에 업데이트한 뒤 다시 실행합니다. 설정에서 자동 확인을 끄거나 수동으로 확인할 수 있습니다. 소스 실행에서는 설치본으로 자동 교체하지 않습니다.

설치본의 사용자 설정·게임 저장·사용자 플러그인·업데이트 로그는 `%LOCALAPPDATA%\seoul2line Toolbox\user_data`에 보관되므로 앱을 덮어써도 유지됩니다. 기존 설치 폴더의 `user_data`는 최초 실행 시 기존 파일을 덮어쓰지 않고 복사합니다. 소스 실행은 프로젝트의 `user_data`를 사용합니다. 업데이트 실패 로그는 사용자 데이터의 `updates/install-update.log`에서 확인할 수 있습니다.

처음 실행하면 `user_data` 폴더와 설정 파일이 생성될 수 있습니다. 외부 프로그램 실행·파일 삭제·네트워크 기능은 사용자가 입력한 경로와 권한의 영향을 받습니다.

## 기능 목록

기본 도구와 기본 제공 플러그인의 기능을 메뉴별로 정리했습니다. 개발 예정 기능은 [TODO](docs/TODO.md)에서 확인할 수 있습니다.

### 홈

| 도구 | 주요 기능 |
| --- | --- |
| 개요 | 검색·모니터·자동화·설정 바로가기, 카테고리별 전체 도구 목록 |
| 시스템 모니터 | CPU·RAM·GPU·VRAM·디스크·네트워크 사용량 주기적 조회 |

하드웨어·운영체제에 따라 일부 측정값은 `확인 불가`로 표시될 수 있습니다. GPU·VRAM 조회는 NVIDIA의 `nvidia-smi`를 사용합니다.

### 게임

| 도구 | 주요 기능 |
| --- | --- |
| 게임 실행기 | Valorant·Minecraft·Steam 실행, 실행 경로 관리 |
| 배경음악 | MP3 재생 목록, 재생·일시정지·정지, 반복 방식·음량 조절 |
| 작업공간 프리셋 | 마크 개발·Python·게임 프리셋에 등록된 프로그램을 함께 실행 |

### 개발자

기본 제공 `developer_tools` 플러그인에서 제공합니다.

| 도구 | 주요 기능 |
| --- | --- |
| Minecraft Toolkit | 선택자·execute·tellraw·give·summon·scoreboard 등 마인크래프트 커맨드 생성 |
| 코드 편집기 | 코드 파일 열기·편집·저장 |
| Git / GitHub | 브랜치·변경·원격 저장소 조회, Pull·추가·커밋·Push, GitHub 페이지 열기 |
| 통합 터미널 | 작업 경로에서 명령 실행, 실행 결과 확인 |
| 개발자 변환기 | JSON 정리·압축, Base64·URL 인코드·디코드, 타임스탬프·진수 변환, UUID 생성 |
| 스크래치패드 | 간단한 메모 작성·저장 |

### 네트워크

| 도구 | 주요 기능 |
| --- | --- |
| 네트워크 상태 | 네트워크 정보 조회, Ping 등 진단 명령 실행, 결과 로그 복사 |
| Same-WiFi LAN 통합 | 서버·클라이언트 연결, 텍스트·파일 송수신, 사용자 허용 시 수신 명령 실행 |

### 파일

| 도구 | 주요 기능 |
| --- | --- |
| 파일 관리자 | 폴더 탐색, 파일 생성·이동·삭제, 파일 작업 단축키 |
| 파일 형식 변환 | 이미지·음성·동영상·문서·데이터·압축 파일의 형식 변환 |
| CUR / ANI 커서 편집기 | 커서 프레임 열기·그리기·채우기, 밝기·대비·회색조·반전·배경 투명화, CUR·ANI 저장 |
| 클립보드 기록 | 텍스트 클립보드 기록, 이전 내용 복사·기록 관리 |
| 파일 비교 / Diff | 두 텍스트 파일의 차이 비교 |
| 프로세스 관리자 | 실행 중인 프로세스 조회·선택 종료 |
| 영역 캡쳐 | PrintScreen으로 화면 영역 선택, PNG 저장·이미지 클립보드 복사 |

파일 변환은 형식에 따라 외부 변환 프로그램이나 추가 패키지가 필요합니다.

### 자동화

| 도구 | 주요 기능 |
| --- | --- |
| 워크플로 편집기 | 노드 배치·연결, 간편·고급 모드, 조건 분기, 데이터 자동 전달, 검증·테스트 실행·저장 |
| 자동화 관리 | 저장한 워크플로 관리, 파일 감시 활성화·비활성화 |
| 자동화 실행 기록 | 워크플로 실행 결과·오류 로그 확인 |

파일 감시 → 조건 → 이미지 변환 → 파일 이동 등을 연결할 수 있습니다. 감시는 앱 실행 중에 동작하며, 사용 예제는 [자동화 안내](docs/AUTOMATION.md)를 참고하세요.

### 미니게임

| 도구 | 주요 기능 |
| --- | --- |
| 미니게임 허브 | 물결·밤하늘·회로·노을 장면 전환과 쉬어가는 화면 |
| 항성계 시뮬레이터 (GPU) | 별·행성·블랙홀을 다루는 GPU 항성계 시뮬레이션 |
| TRSim | 앱 내장 철도 관제 게임. 14개 역 분기 전환, 열차 운행·충돌 회피, 저장·불러오기 |
| 공장 자동화 | 격자 위 생산·운송·판매 설비 배치, 자원 채굴·제련과 설비 운영 |
| 한국 주식 | 가상 주식 매수·매도, 가격 차트·보유 자산·거래 이력, 가격 갱신 제어 |
| Micro Warfare | 2D RTS 전장·카메라, 유닛 선택·A* 이동, 채굴·건설·강화·생산 대기열, 전투·적 전략 AI, 게임 모드·저장·전투 통계 |
| Orbit Lab | 2D 우주 카메라, 행성·위성 생성·질량 설정, 만유인력 시뮬레이션, 시간 배속·일시정지, 우주선 발사·방향·추력·연료 제어 |

### 설정·설치·업데이트

| 기능 | 제공 내용 |
| --- | --- |
| 테마 및 화면 | 다크·라이트·그린 테마와 10색 미리보기 |
| 실행 경로 | 게임 실행 파일·Minecraft 폴더 선택, Steam URI 설정 |
| 단축키 | 파일 작업 단축키 편집, 형식·중복 확인 |
| 설정 공통 | 메뉴 이동 시 입력 유지, 변경 상태 표시, 하단 저장·취소 버튼 |
| ZIP 플러그인 설치 | ZIP 선택 → 안전 경고 확인 → 압축 검증·해제 → 사용자 플러그인 폴더 설치 |
| 플러그인 관리 | 플러그인 재검색, 활성화·비활성화, 로딩 상태·오류 확인 |
| 설치 프로그램 | Inno Setup 기반 Windows 설치 EXE, 사용자 데이터와 설치 파일 분리 |
| 자동 업데이트 | 설치본 시작 시·6시간마다 새 버전 확인, 수동 확인, 다운로드 검증 후 설치·재실행 |
| 실행·업데이트 BAT | `run.bat`으로 실행, `update_installer.bat`으로 최신 설치본 받기, `--build`로 소스 빌드 |

### 플러그인 예제

| 도구·메뉴 | 주요 기능 |
| --- | --- |
| 플러그인 예제 | 외부 플러그인의 도구 화면 등록 예제 |
| 예제 메뉴 실행 | 플러그인에서 사이드바 메뉴·액션을 추가하는 예제 |

도구는 `app/tool_registry.py`가 `app/tools`를 자동 탐색하고 각 모듈의 `register()`를 호출해 등록합니다. 추가 플러그인은 자체 섹션·도구·메뉴를 등록할 수 있습니다.

## 공통 사용법

- `Ctrl+K`: 상단 중앙 통합 검색창으로 이동 (↑/↓ 선택, Enter 실행, Esc 닫기)
- 왼쪽 메뉴: 섹션과 도구 전환
- 다크/라이트/그린 테마: 설정 → 테마 및 화면에서 팔레트를 고른 뒤 `저장`으로 적용
- 보조 탐색: 기본은 펼친 상태입니다. 왼쪽 아래 `도구 목록 펼치기` / `도구 목록 접기`로 전환하거나 목록 제목 옆 `‹`로 접을 수 있으며, 조절한 너비를 복원합니다.
- 지갑: 미니게임에서 사용하는 툴코인 잔액 표시

도구 화면은 선택된 순간 생성됩니다. 따라서 사용하지 않는 도구의 갱신 루프가 계속 CPU를 사용하는 것을 피할 수 있습니다. 단, 한국 주식 가격 엔진은 앱 전체에서 공유되며 한국 주식 화면의 가격 갱신 버튼으로 시작·중지합니다.

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
