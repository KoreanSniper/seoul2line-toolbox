# seoul2line Toolbox v2 변경 번호표

사용자가 `n번 취소해줘`라고 말하면 아래 번호를 기준으로 되돌린다.

## 007. [v2.0] 3D 폭발·파괴 시뮬레이터 삭제

- 사용자 요청으로 해당 미니게임의 런처, 새로 추가한 파괴 엔진과 렌더러, 파괴 테스트를 삭제했다. 기존 지형·전략 코드와 이미지 에셋은 보존한다.
- 미니게임 등록 순서와 작업 공간의 산 만들기 실행 프리셋, README 목록에서도 제거했다.
- 아래 001~006번은 과거 변경 이력이다.

## 006. [v2.0] Phase 4를 3D 물리 기반 폭발·파괴 시뮬레이터로 전환

- 목적: 기존 3D 지형과 카메라를 유지하고 국가·유닛·외교·건설 조작을 폭발 및 구조물 파괴 실험으로 교체한다.
- 주요 파일: `app/tools/minigame_mountain_sim.py`, `app/games/mountain_sim/destruction.py`, `app/games/mountain_sim/destruction_view.py`, `tests/test_destruction.py`, `README.md`
- 포함 기능: 목재·벽돌·콘크리트 구조물, 거리·질량에 따른 폭발 충격, 연결 파손과 지지대 상실에 따른 붕괴, 고정 시간 간격 중력·마찰·반발 및 블록 충돌, 폭발 범위 표시, 세기·속도 조절, 일시정지와 같은 맵 초기화. 축 정렬 블록 모델이며 지형 자체는 파괴하지 않는다.
- 검증: 물리 단위 테스트 및 실제 지형에서의 배치·폭발·지형 보존 검증. 검증용 Python에 pygame/PyOpenGL이 없어 실제 3D 창의 시각 검증은 수행하지 못했다.
- 취소 기준: 런처와 3D 실행 루프·렌더링·UI를 005번 전략 모드로 복구하고 새 destruction 모듈과 해당 테스트를 제거한다. 지형 생성 수식에는 변경이 없다.

## 001. [v2.0] app/tools 에셋 분리 및 프로젝트 현실화

- 목적: `app/tools` 디렉토리를 정화하기 위해 산악 시뮬레이터 이미지 에셋을 격리하고, 에셋 경로를 동적 참조로 바꾸며, README의 의존성 설명을 실제 프로젝트 구성에 맞춘다.
- 주요 파일: `app/tools/minigame_mountain_sim.py`, `app/assets/images/mountain_loading_campaign.png`, `app/assets/images/mountain_loading_bar_frame.png`, `README.md`, `docs/CHANGE_LOG.md`
- 포함 기능: 로딩 캠페인 이미지와 로딩 바 프레임 이미지를 `app/assets/images/`로 이동, `Path(__file__).resolve().parent.parent / "assets" / "images"` 기반 이미지 경로 참조, `requirements.txt` 설치 안내 추가.
- 취소 기준: 두 이미지 파일을 `app/tools/`로 되돌리고 `minigame_mountain_sim.py`의 이미지 경로를 `Path(__file__).with_name(...)` 방식으로 복구하며, README의 001번 의존성 현실화 문구와 이 변경 기록 항목을 제거한다.

## 002. [v2.0] 게임 로직 및 셰이더 엔진 격리 (app/games 신설)

- 목적: app/tools 디렉토리에서 register()가 없는 순수 게임 엔진(산악 시뮬)과 OpenGL 셰이더 렌더러를 app/games 하위로 격리하여 도구 디렉토리의 순수성을 확보하고 앱 로딩 오버헤드를 제거한다.
- 주요 파일: app/games/mountain_sim/strategy_phase1.py, app/games/starsystem/renderer/*, app/tools/minigame_mountain_sim.py, app/tools/chill_starsystem_gpu.py, docs/CHANGE_LOG.md
- 취소 기준: app/games 하위의 모듈들을 app/tools로 원복하고 minigame_mountain_sim.py와 chill_starsystem_gpu.py의 import 경로를 이전으로 되돌린다.

## 003. [v2.0] 산악 시뮬레이터 유닛 이동 물리 정상화, 지면 오프셋 적용, 지형 개편 및 자동 검증

- 목적: 산악 시뮬레이터 유닛 이동 중 순간 경사도 판정으로 이동이 마비되는 문제를 제거하고, 유닛 렌더링을 지형 표면 위로 띄우며, 중심 평야와 외곽 능선 중심의 절차적 지형으로 개편한다.
- 주요 파일: app/games/mountain_sim/strategy_phase1.py, app/tools/minigame_mountain_sim.py, docs/CHANGE_LOG.md
- 포함 기능: 런타임 이동 판정의 순간 기울기 검사 제거, 유닛 렌더링 지면 오프셋 적용, 레거시 반도/대륙 마스크 삭제, 중심 평야와 외곽 능선 기반 지형 공식 적용, 문법 검사와 헤드리스 스모크 테스트 검증.
- 취소 기준: update_unit/follow_path_step의 순간 경사도 검사를 복구하고, 유닛 렌더링 지면 오프셋을 제거하며, terrain_base_height_uv/world_height_uv와 레거시 마스크 구조를 003번 이전으로 되돌린다.

## 004. [v2.0] 웅장한 횡단 산맥 복원, 반응형 GUI 스케일링 및 로딩바 그라데이션 구현

- 목적: 산악 시뮬레이터 지형에 중앙부를 가로지르는 웅장한 산맥과 통행 가능한 고개를 복원하고, 전략 UI를 해상도에 맞게 확장하며, 로딩바를 주황에서 황금빛으로 이어지는 그라데이션으로 개선한다.
- 주요 파일: app/games/mountain_sim/strategy_phase1.py, app/tools/minigame_mountain_sim.py, docs/CHANGE_LOG.md
- 포함 기능: 횡단 산맥/고봉/분지/고개 기반 지형 공식, 산악 지형 보행 가능 비율 48%~58% 검증, 해상도 기반 Phase 4 UI 스케일링, 확대형 미니맵, 로딩바 버텍스 색상 그라데이션.
- 취소 기준: terrain_base_height_uv의 004번 산맥/고개 수식을 003번 지형 공식으로 되돌리고, draw_phase4_ui의 반응형 스케일링과 draw_loading_screen의 그라데이션 채우기를 제거한다.

## 005. [v2.0] 매크로 구조 보장 유기적 지형, 수도 선정 단계 edge 기반 연결성 필터, HUD 콘솔 및 F11 전체화면

- 목적: seed 기반 4방향 회전 매크로 레이아웃(산악/해양/강 대각선)으로 산악 감옥 구조를 방지하고, 수도 선정 단계 자체에서 실제 네비게이션 연결성을 검증하여 고립 수도를 사전 차단한다. 하단 통합 RTS HUD 콘솔과 F11 전체화면도 추가한다.
- 주요 파일: app/games/mountain_sim/strategy_phase1.py, app/tools/minigame_mountain_sim.py, docs/CHANGE_LOG.md
- 포함 기능: _macro_rotate/_macro_diagonal_mask 헬퍼, 매크로 지형 구조, river_mask_uv 매크로 대각선 연동, is_nav_edge_traversable 기반 main component BFS, nearest_walkable_grid 기반 수도 nav 스냅, 수도→nav 셀 is_segment_traversable 검증, 수도 고도 범위 0.10~0.32, 8수도 A* 전수 검증, F11 토글, 상단 리본 바, 하단 통합 전략 HUD 콘솔.
- 취소 기준: terrain_base_height_uv/_macro_rotate/_macro_diagonal_mask를 004번 상태로 복구하고, river_mask_uv의 macro_river 연동을 제거한다. establish_capital_positions의 main_component BFS 및 nearest_walkable_grid/is_segment_traversable 수도 필터를 제거하고, is_valid_capital_position의 h_ratio 조건을 제거한다. draw_phase4_ui를 004번 UI로 복구하고 K_F11 핸들러를 삭제한다.
