# Cloudflare Chat Transfer

기존 네트워크 메뉴의 Same-WiFi LAN 통합을 대체한다. 저장된 도구 ID `network.lan_remote`는 유지한다. PC마다 Toolbox를 실행하고 동일한 Workers 주소·서버 인증 토큰·방 코드로 연결한다. LAN 포트 개방이나 같은 Wi-Fi가 필요하지 않다.

## 서버 배포

Cloudflare 계정에 로그인할 수 있는 환경에서 Node.js 22 이상과 npm을 준비한다. **Workers Free 플랜을 사용한다. R2 활성화·결제 정보 등록·Workers Paid 가입은 이 구성에 필요하지 않다.** 아래 명령은 `server/cloudflare`에서 실행한다.

```powershell
npm ci
npx wrangler login
npx wrangler secret put SERVICE_TOKEN
npm run deploy
```

`SERVICE_TOKEN` 프롬프트에는 충분히 긴 임의 문자열을 입력한다. 이 값은 Cloudflare API 토큰이 아니라 이 전송 서버만을 위한 공유 암호다. 참가자에게 Cloudflare 계정/API 토큰을 전달하지 않는다. 이 앱은 사용자 요청으로 기본 서버 `https://toolbox-chat-transfer.seoul2linejh.workers.dev`와 배포용 공용 접속 키를 코드에 포함한다. 기본 서버에 배포할 때 SERVICE_TOKEN은 앱에 포함한 공용 키와 일치해야 한다. 개인 Cloudflare 계정/API 토큰이나 다른 비밀은 코드에 넣지 않는다. 배포용 공용 키는 앱에서 추출할 수 있는 값이며, 방 접근은 별도의 임의 방 코드로 제한한다.

로컬 개발:

```powershell
npx wrangler dev --ip 127.0.0.1 --port 8787 --var SERVICE_TOKEN:local-test-token
```

앱 UI의 서버는 내장 주소로 고정된다. 로컬 프로토콜 개발은 `TransferClient("http://127.0.0.1:8787", "local-test-token", "테스트")` 또는 통합 테스트로 수행한다. HTTP는 localhost·루프백에서만 허용된다.

## 앱 사용

1. 네트워크 → Cloudflare Chat Transfer를 연다. 내장 서버 주소와 공용 접속 키로 연결한다.
2. 새 방 만들기를 누른 뒤 복사로 전체 방 코드를 복사한다.
3. 상대 PC는 전달받은 방 코드를 입력하고 방 참가를 누른다. 기본 서버에서는 주소·접속 키를 따로 입력하지 않는다.
4. 입력창에서 Enter 또는 전송으로 채팅한다. 파일 추가에서 여러 파일을 선택하면 순서대로 업로드한다. 상대방의 파일 카드에서 다운로드를 눌러 저장 위치를 선택한다.
5. 유저 설정에서 닉네임을 1~40자로 입력하고 저장한다. 변경한 닉네임은 다음 메시지부터 반영되고 재실행 후에도 유지된다. 취소하면 편집 전 이름을 유지한다. 서버 주소·공용 키 입력과 기본 서버 복원 기능은 제공하지 않는다.

표시 이름은 인증된 계정이 아니며 다른 참가자와 중복될 수 있다. 방 코드는 방 ID와 256비트 임의 공유 키로 구성된다. 서버에는 방 키의 SHA-256만 저장한다. 방 코드와 서버 인증 토큰을 모두 아는 사람은 해당 방의 내용과 파일에 접근할 수 있다.

## 동작·한도

- Workers는 HTTPS API, Durable Objects의 SQLite는 방·채팅·파일 메타데이터와 파일 내용을 처리한다. 파일은 256 KiB 이하 BLOB 조각으로 저장하고 스트리밍으로 다운로드한다. R2는 사용하지 않는다. 채팅은 무료 요청 한도를 절약하기 위해 3초마다 새 이벤트를 조회한다. WebSocket 방식은 아니다.
- 연결 지역은 Cloudflare 자동 라우팅이며 수동 지역 선택은 제공하지 않는다. 응답 시간은 클라이언트가 실제 HTTP 요청 시간을 측정한다.
- 방은 생성 후 24시간이 지나면 접근이 차단된다. Durable Object 알람이 방 기록·파일 조각을 삭제한다. 알람 실행 지연·재시도 동안 실제 저장소 삭제는 늦어질 수 있다.
- 파일당 1바이트~25 MiB, 방당 최대 100개 파일·합계 100 MiB, 메시지당 4,000자, 표시 이름 40자, 최근 이벤트 500개를 유지한다. 오래된 파일 이벤트는 채팅 보존 한도에 따라 목록에서 사라질 수 있으며 파일은 만료 시 삭제된다.
- 업로드·다운로드는 64 KiB 단위로 처리한다. 진행률·속도·예상 시간은 실제 처리 바이트를 기준으로 표시한다. 업로드 완료는 서버의 SQLite 저장 응답까지 받은 뒤 표시한다.
- 연결 해제·도구 종료 시 취소 신호를 보내고 이전 연결의 UI 결과는 무시한다. 대기 중인 네트워크 I/O는 최대 20초 소켓 타임아웃 후 종료될 수 있다. 서버가 이미 저장한 파일은 방 만료까지 남을 수 있다.
- 다운로드는 같은 폴더의 임시 파일에 쓴 뒤 크기를 확인하고 최종 경로로 교체한다. 실패·취소 시 기존 대상 파일을 보존하고 임시 파일을 정리한다.
- 유저 설정은 닉네임만 앱 설정에 저장한다. 서버 주소·공용 접속 키는 내장 값을 사용하며 설정 UI에 노출하지 않는다. 과거 설정 파일의 서버 주소는 연결에 사용하지 않는다. 방 코드는 설정 파일에 저장하지 않는다. 복사한 방 코드는 OS 클립보드에 남는다.
- HTTPS는 전송 구간 암호화다. 종단간 암호화는 구현하지 않았으며 서버 운영자는 내용을 읽을 수 있다. 기존 원격 명령 실행 기능은 이 채팅·파일 도구에서 제거했다.
- 파일 선택·다운로드·기록·필터를 제공한다. OS 파일 드래그 앤 드롭, 전송 재개, 개별 전송 취소, 사용자 계정 인증은 후속 항목이다. 전송 취소는 연결 해제를 사용한다.

**무료 운영 조건:** Cloudflare 대시보드에서 Workers 플랜이 Free인지 확인하고 유료 플랜으로 전환하지 않는다. Workers Free는 하루 100,000 요청, SQLite Durable Objects Free는 하루 100,000 요청·13,000 GB-s·일별 SQL 읽기/쓰기 한도 및 계정 합계 5 GB 저장 한도를 적용한다. 한도를 넘으면 요청/작업이 실패하며, Free 플랜에 대해서 초과 사용료가 청구되는 방식은 아니다. 한도는 계정의 다른 앱과 공유한다. 방당 100 MiB 제한만으로 계정 전체 한도 초과를 막을 수는 없다. 이미 가입한 유료 플랜이나 R2 서비스는 이 코드 변경으로 해지되지 않는다.

공유 토큰을 가진 참가자는 방을 생성할 수 있다. 공개 서비스로 운영하려면 계정 인증, 사용자별 사용량·요청 제한과 비용 모니터링을 별도로 적용해야 한다. 현재 구현은 신뢰하는 소규모 사용자 간 사용을 전제로 한다.

## 검증

```powershell
# 저장소 루트
python -m unittest discover -s tests -p test_cloudflare_transfer.py -v
# server/cloudflare
npm test
```

Python 통합 검사는 Node.js 22 이상의 `node:sqlite`와 실제 Worker 코드를 이용한 로컬 HTTP 테스트 서버를 실행한다. 서버 검사는 인증·방 격리·커서·메시지 제한·파일 무결성·SQLite 실패 복구·만료 삭제·조각 크기·방 총용량·잘린 본문·동시 업로드 거부를 검사한다. 실제 Wrangler 로컬 런타임에서 R2 없이 두 Python 클라이언트의 한글 채팅과 최대 25 MiB 파일 왕복·SHA-256 일치를 검증했다. 운영 Cloudflare 계정 배포·인터넷 구간 테스트와 설치본 빌드는 아직 수행하지 않았다.

Cloudflare 공식 문서: [Durable Objects 구성](https://developers.cloudflare.com/durable-objects/get-started/), [SQLite Storage API](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/), [Durable Objects 무료 한도·과금 정책](https://developers.cloudflare.com/durable-objects/platform/pricing/), [Workers 무료 한도](https://developers.cloudflare.com/workers/platform/limits/).
