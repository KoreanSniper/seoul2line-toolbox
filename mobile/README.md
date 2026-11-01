# S2 Toolbox Mobile

기존 PC 앱과 독립적인 Python + Kivy Android 앱. 저장소 루트의 `mobile/`에서 개발한다.
첨부된 다크·라이트·그린 시안의 색상과 기하학 장식을 참고하고 기존 Toolbox 로고를 사용한다.

## Windows에서 미리 실행

저장소 루트에서:

```powershell
py -m pip install -r mobile/requirements.txt
py mobile/main.py
```

홈·상단 로고·전체 도구 검색·하단 5개 탭·세 테마를 제공한다.
하단은 메뉴 1위 / 메뉴 2위 / 홈 / 도구 1위 / 설정 순서다.
처음에는 오디오 / 개발 도구 / 홈 / TTS / 설정을 표시한다.
메뉴·도구 화면에 들어갈 때 사용 횟수를 저장하고 추천을 갱신한다.
홈·설정은 고정이며 나머지 탭은 0.55초 길게 눌러 현재 항목 고정·다른 항목 선택·고정 해제가 가능하다.
설정 화면에서도 같은 기능에 접근할 수 있다. 동일 항목을 다른 슬롯에 고정하면 기존 고정을 이동한다.

개발자 변환기와 스크래치패드는 오프라인으로 동작한다.
TTS·사운드보드·PC 연결·TC 동기화는 아직 준비 안내 화면이다.
PC 연결 및 TC 잔액을 실제 연결된 것처럼 표시하지 않으며 네트워크 요청도 하지 않는다.

## 데이터와 리소스

- 개인화: Kivy `App.user_data_dir`의 `mobile-settings.json`. 테마·사용 횟수·고정값만 저장한다.
- 메모: 같은 폴더의 `scratchpad.txt`. 0.7초 입력 대기 후, 화면 이동·테마 변경·앱 일시정지·종료 때 저장한다.
- 메모는 최대 200,000자이며 이전 저장본 `scratchpad.previous.txt` 한 단계를 보관한다.
  복구는 확인창에서 실행하며 교체 전 현재 파일은 `scratchpad.before-restore.txt`에 보관한다.
  읽을 수 없는 기존 파일은 자동 덮어쓰지 않는다. 저장 실패는 메모 화면에 표시하고 입력을 유지한다.
- 변환기 입력/결과는 앱 실행 중 메모리에만 보관한다. 입력·방식 변경 시 이전 결과를 지운다.
- PC `config.json`을 읽거나 복사하지 않는다. 임시 파일을 쓴 뒤 원자적으로 교체한다.
- 한국어 글꼴: Google Fonts의 Nanum Gothic, SIL Open Font License. `assets/OFL.txt` 동봉.
- 기존 로고를 `assets/toolbox-logo.png`로 복사하여 PC 폴더 없이 패키징한다.
- `local_data/`, `.buildozer/`, `bin/`, APK/AAB는 Git에서 제외한다.

## 검증

```powershell
py -m unittest mobile.tests.test_model -v
py -m unittest mobile.tests.test_offline_tools -v
py -m mobile.tests.smoke_ui
py -m mobile.tests.smoke_offline
```

두 번째 명령은 실제 Kivy 창을 실행한다. 임시 설정 경로로 홈·검색·설정·PC 메뉴와
좁은 화면을 검사하고 `mobile/local_data/previews/`에 PNG를 남긴다.
합성 터치로 짧은 탭·0.55초 길게 누르기·의도하지 않은 이동 방지·고정/해제 저장·
손가락 이동 후 취소를 확인하고 Android 앱 일시정지 콜백의 저장 반환도 검사한다.
이는 Windows 검사이며 Android 설치·키보드·시스템 인셋·실물 터치 검증을 대신하지 않는다.

## 오프라인 도구

변환기는 JSON 정리/압축, UTF-8 Base64 인코딩/디코딩, 2·8·10·16진수 정수 변환을 제공한다.
변환 입력은 32,768자, 정수는 접두사를 제외한 1,024자리까지 지원한다.
JSON은 숫자 토큰의 정밀도를 보존하고 중복 키·NaN/Infinity를 거부한다.
중첩 64단계와 결과 262,144자 제한을 두어 과도한 출력으로 화면이 멈추는 상황을 줄인다.
메모는 자동 저장 상태와 글자 수를 표시하며 이전 저장본 복구가 가능하다.
이 데이터는 Android 앱 전용 경로에 저장되며 앱 삭제 시 제거될 수 있다.

## Android APK 빌드

Kivy 공식 문서는 Buildozer를 Linux/macOS 또는 Windows의 WSL에서 실행하도록 안내한다.
Windows PowerShell에서 직접 Buildozer를 실행하지 않는다.

1. WSL2 Ubuntu 또는 Linux에 Python·JDK·Android 빌드 의존성을 설치한다.
2. 저장소의 `mobile/`을 Linux 홈 디렉터리로 복사한다. `/mnt/c`에서 빌드하지 않는다.
3. 별도 Python 가상환경에 Buildozer를 설치하고 공식 설치 안내의 의존성을 적용한다.
4. 복사한 `mobile/`에서 `buildozer -v android debug`를 실행한다.
5. 처음 나오는 SDK 라이선스를 직접 확인한다. 생성 파일은 `bin/`에 저장된다.
6. 테스트 기기에 설치하여 실행·뒤로 가기·앱 전환·재시작·탭 고정을 확인한다.

초기 대상: Android 8.0/API 26 이상, arm64-v8a, 세로 화면, target API 35.
현재 빌드 설정은 초안이며 APK 생성·설치로 검증하기 전에는 Android 지원 확인으로 간주하지 않는다.
SDK/NDK 다운로드와 빌드에는 인터넷이 필요하다. 현재 단계는 Android 권한을 요청하지 않는다.

공식 참고:
- [Kivy Android 패키징](https://kivy.org/doc/stable/guide/packaging-android.html)
- [Buildozer 설치·WSL 안내](https://buildozer.readthedocs.io/en/latest/installation/)
- [나눔고딕 원본과 라이선스](https://github.com/google/fonts/tree/main/ofl/nanumgothic)

## 후속 설계

2차는 오프라인 기본 도구, 3차는 Cloudflare Workers + Durable Objects 연결,
4차는 PC 상태·실행·자동화, 이후 고급 도구·경제·TC·배포 순서로 진행한다.
TC는 서버 원장과 거래 ID를 기준으로 원자 처리하고 오프라인에서는 조회 캐시만 사용한다.
인증·권한 검증·재연결·양방향 파일 전송은 별도 단계에서 구현한다.
