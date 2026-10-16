# TRSim — 내장 철도 관제 게임

미니게임 → TRSim에서 바로 플레이합니다. 별도 프로젝트나 Python 프로세스를 실행하지 않습니다.
작업공간 프리셋의 TRSim도 같은 내장 화면을 엽니다.

`C:\Coding\GAME_MOD\TRSim\main.py`의 Rail Panic Dispatcher를
`app/games/trsim/view.py`로 편입했습니다. 원본 프로젝트는 수정하지 않았습니다.
기존 도구 ID `minigame.trsim`과 14개 역·화물·러시아워·점수·예산·평판 규칙을 유지합니다.

## 조작

- 역 클릭: 다음 분기 방향으로 전환
- 열차 클릭: 정차·재출발
- 맵을 클릭한 뒤 `1`~`9`: 해당 역의 분기 전환
- `P`: 추천 경로 표시, `Space`: 일시정지, `N`: 새 판
- `Ctrl+S`: 저장, `Ctrl+L`: 불러오기
- 좁은 창의 `관제실` 버튼: 상세 정보 패널 표시·숨기기

지도는 화면 크기에 맞춰 축소·확대됩니다. 다른 도구로 이동하면 게임 타이머가 취소됩니다.
게임을 이어가려면 이동 전에 저장하세요. 단축키는 게임 맵에 포커스가 있을 때만 작동합니다.

## 저장

소스 실행은 `user_data/trsim/dispatcher_save.json`에 저장합니다.
설치본은 `%LOCALAPPDATA%\seoul2line Toolbox\user_data\trsim\dispatcher_save.json`에 저장합니다.
저장은 임시 파일을 만든 뒤 교체하며, 잘못된 저장 파일을 불러오면 현재 게임을 유지합니다.
기존 외부 프로젝트의 `dispatcher_save.json`도 같은 위치로 복사하면 불러올 수 있습니다.
