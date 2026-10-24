# Cloudflare Chat Transfer

기존 네트워크 메뉴의 Same-WiFi LAN 통합을 대체한다. 저장된 도구 ID `network.lan_remote`는 유지한다. PC마다 Toolbox를 실행하고 동일한 Workers 주소·서버 인증 토큰·방 코드로 연결한다. LAN 포트 개방이나 같은 Wi-Fi가 필요하지 않다.

## 서버 배포

Cloudflare 계정에 로그인할 수 있는 환경에서 Node.js 22 이상과 npm을 준비한다. R2 사용을 활성화해야 한다. 아래 명령은 `server/cloudflare`에서 실행한다.

```powershell
npm ci
npx wrangler login
npx wrangler r2 bucket create toolbox-chat-files
npx wrangler secret put SERVICE_TOKEN
npm run deploy
```

`SERVICE_TOKEN` 프롬프트에는 충분히 긴 임의 문자열을 입력한다. 이 값은 Cloudflare API 토큰이 아니라 이 전송 서버만을 위한 공유 암호다. 참가자에게 Cloudflare 계정/API 토큰을 전달하지 않는다. 기존 같은 이름의 R2 버킷이 있으면 재사용하거나 `wrangler.toml`의 `bucket_name`을 변경한다. 배포 후 출력되는 `https://toolbox-chat-transfer.<계정>.workers.dev` 주소를 사용한다. 로컬 파일에 실제 토큰을 커밋하지 않는다.

로컬 개발:

```powershell
npx wrangler dev --ip 127.0.0.1 --port 8787 --var SERVICE_TOKEN:local-test-token
```

앱에는 `http://127.0.0.1:8787`과 `local-test-token`을 입력한다. HTTP는 localhost·루프백에서만 허용된다.

## 앱 사용

1. 네트워크 → Cloudflare Chat Transfer → 연결 옵션을 연다.
2. Workers 서버 주소, 서버 인증 토큰, 표시 이름을 입력하고 적용한다.
3. 새 방 만들기를 누른 뒤 복사로 전체 방 코드를 복사한다.
4. 상대 PC도 같은 서버 주소와 인증 토큰을 입력하고, 전달받은 전체 방 코드로 방 참가를 누른다.
5. 입력창에서 Enter 또는 전송으로 채팅한다. 파일 추가에서 여러 파일을 선택하면 순서대로 업로드한다. 상대방의 파일 카드에서 다운로드를 눌러 저장 위치를 선택한다.

표시 이름은 인증된 계정이 아니며 다른 참가자와 중복될 수 있다. 방 코드는 방 ID와 256비트 임의 공유 키로 구성된다. 서버에는 방 키의 SHA-256만 저장한다. 방 코드와 서버 인증 토큰을 모두 아는 사람은 해당 방의 내용과 파일에 접근할 수 있다.

## 동작·한도

- Workers는 HTTPS API, Durable Objects의 SQLite는 방·채팅·파일 메타데이터, 비공개 R2 버킷은 파일 내용을 처리한다. 채팅은 1.5초마다 새 이벤트를 조회한다. WebSocket 방식은 아니다.
- 연결 지역은 Cloudflare 자동 라우팅이며 수동 지역 선택은 제공하지 않는다. 응답 시간은 클라이언트가 실제 HTTP 요청 시간을 측정한다.
- 방은 생성 후 24시간이 지나면 접근이 차단된다. Durable Object 알람이 방 기록·R2 파일을 삭제한다. 알람 실행 지연·재시도 동안 실제 저장소 삭제는 늦어질 수 있다.
- 파일당 1바이트~25 MiB, 방당 최대 100개 파일, 메시지당 4,000자, 표시 이름 40자, 최근 이벤트 500개를 유지한다. 오래된 파일 이벤트는 채팅 보존 한도에 따라 목록에서 사라질 수 있으며 파일은 만료 시 삭제된다.
- 업로드·다운로드는 64 KiB 단위로 처리한다. 진행률·속도·예상 시간은 실제 처리 바이트를 기준으로 표시한다. 업로드 완료는 서버의 R2 저장 응답까지 받은 뒤 표시한다.
- 연결 해제·도구 종료 시 취소 신호를 보내고 이전 연결의 UI 결과는 무시한다. 대기 중인 네트워크 I/O는 최대 20초 소켓 타임아웃 후 종료될 수 있다. 서버가 이미 저장한 파일은 방 만료까지 남을 수 있다.
- 다운로드는 같은 폴더의 임시 파일에 쓴 뒤 크기를 확인하고 최종 경로로 교체한다. 실패·취소 시 기존 대상 파일을 보존하고 임시 파일을 정리한다.
- 서버 주소·표시 이름만 앱 설정에 저장한다. 인증 토큰·방 코드는 디스크에 저장하지 않는다. 복사한 방 코드는 OS 클립보드에 남는다.
- HTTPS는 전송 구간 암호화다. 종단간 암호화는 구현하지 않았으며 서버 운영자는 내용을 읽을 수 있다. 기존 원격 명령 실행 기능은 이 채팅·파일 도구에서 제거했다.
- 파일 선택·다운로드·기록·필터를 제공한다. OS 파일 드래그 앤 드롭, 전송 재개, 개별 전송 취소, 사용자 계정 인증은 후속 항목이다. 전송 취소는 연결 해제를 사용한다.

공유 토큰을 가진 참가자는 방을 생성할 수 있다. 공개 서비스로 운영하려면 계정 인증, 사용자별 사용량·요청 제한과 비용 모니터링을 별도로 적용해야 한다. 현재 구현은 신뢰하는 소규모 사용자 간 사용을 전제로 한다.

## 검증

```powershell
# 저장소 루트
python -m unittest discover -s tests -p test_cloudflare_transfer.py -v
# server/cloudflare
npm test
```

Python 통합 검사는 Node.js 22 이상의 `node:sqlite`와 실제 Worker 코드를 이용한 로컬 HTTP 테스트 서버를 실행한다. 서버 검사는 인증·방 격리·커서·메시지 제한·파일 무결성·R2 실패 복구·만료 삭제를 검사한다. 실제 Wrangler 로컬 런타임에서도 두 Python 클라이언트의 한글 채팅과 2,560,000바이트 R2 파일 왕복을 검증했다. 운영 Cloudflare 계정 배포·인터넷 구간 테스트와 설치본 빌드는 아직 수행하지 않았다.

Cloudflare 공식 문서: [Durable Objects 구성](https://developers.cloudflare.com/durable-objects/get-started/), [SQLite Storage API](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/), [Workers에서 R2 사용](https://developers.cloudflare.com/r2/api/workers/workers-api-usage/).
