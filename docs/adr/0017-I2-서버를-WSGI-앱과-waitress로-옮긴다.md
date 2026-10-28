# ADR 0017: I2 서버를 WSGI 앱과 waitress로 옮긴다

상태: 채택 (2026-10-29, D111). ADR 0012의 "표준 라이브러리 HTTP 서버" 결정과 그 안의 연결 상한·헤더 마감·스레드 서버 구현을 대체한다 (Supersedes 0012 일부). 인증, 락, 디스크 여유, tar 검사, 응답 계약은 0012 그대로다.

## 맥락
`http.server.ThreadingHTTPServer` 위에 연결 상한 세마포어, 헤더 수신 마감 래퍼(`_DeadlineRaw`), 요청 본문 drain, Content-Length 검사, 종료 절차를 직접 만들었다. Python 문서는 `http.server`를 운영용으로 권하지 않는다(보안 점검을 하지 않았다고 경고, 원문 대조는 이번에 하지 않음). 헤드가 D111로 WSGI(PEP 3333) + waitress로 바꾸기로 했다.

## 결정
- 앱은 WSGI 함수(`make_app`)이고 서버는 waitress 3.0.2다. 단일 프로세스·다중 스레드 설계(락과 세마포어가 프로세스 안에 있다)라 prefork 서버(gunicorn)가 아니라 waitress다.
- 지운 자체 코드: `_DeadlineRaw`(헤더 마감), `_Server`(연결 상한 세마포어), `BaseHTTPRequestHandler` 서브클래스, 본문 drain, Content-Length 직접 검사, 본문 상한 직접 검사.
- 남긴 것(서버가 아니라 서비스 로직): 토큰 인증과 역할, 인증 실패 제한, 데이터셋 ID 단위 락, 게시·다운로드 슬롯, 디스크 여유 검사, tar 검사.
- 종료: `DatasetServer.serve_forever`가 종료 신호에 새 연결을 받지 않고 진행 중 요청을 `drain_grace`초까지 마저 처리한다. 왜 waitress `run()`을 그대로 쓰지 않나: 종료 신호에 주 루프를 먼저 끝내 작업 스레드가 쓴 응답이 소켓으로 나가지 못하고, 스레드는 5초만 기다린다(waitress 3.0.2 소스를 읽어 확인: `waitress/server.py:323-330` `BaseWSGIServer.run()`은 `wasyncore.loop`를 `except (SystemExit, KeyboardInterrupt)`로 빠져나온 뒤 `task_dispatcher.shutdown()`을 부르고, `waitress/task.py:117` `ThreadedTaskDispatcher.shutdown(cancel_pending=True, timeout=5)`는 스레드를 5초만 기다리고 대기 중 작업을 취소한다. 응답을 소켓에 쓰는 것은 주 루프(`wasyncore`)라 루프가 끝난 뒤에는 작업 스레드가 낸 응답이 나가지 않는다).

## 값과 출처 (모두 측정 안 함)
| 값 | waitress 설정 | 출처 |
|---|---|---|
| 본문 상한 1GiB | `max_request_body_size` | ADR 0012 값을 그대로 옮김(추정, 측정 안 함) |
| 유휴 연결 30초 | `channel_timeout` | 이전 소켓 timeout 값 유지(측정 안 함) |
| 동시 연결 32 | `connection_limit` | 이전 값 유지(측정 안 함) |
| 작업 스레드 16 | `threads` | 제약: 동시 게시 8 + 동시 다운로드 8. waitress 기본은 4(측정 안 함) |
| 정리 주기 min(5초, timeout) | `cleanup_interval` | waitress 기본 30초면 유휴 연결이 최대 timeout+30초 남는다. 5초는 측정 없는 선택 |
| 종료 대기 8초 | `DATASET_STORE_DRAIN_GRACE` | 제약: Docker stop 기본 대기 10초에서 2초 여유. 큰 게시는 8초를 넘을 수 있고 그러면 끊긴다(deploy가 `stop_grace_period`를 늘리면 값도 올린다) |

## 동작이 바뀐 곳 (감수)
1. **본문 상한 초과**: 앱의 400 INVALID_RECORD(JSON)에서 waitress의 **413**(text/plain)로. 본문을 받기 전에 거절하는 성질은 같다. 계약 클라이언트는 JSON이 아닌 오류를 일반 오류로 다룬다(HTTP.md와 CONVENTIONS.md에 413 항목은 없다: grep으로 확인. 계약에 413을 더할지는 헤드 판단).
2. **인증 전에 본문을 받는다**: waitress는 본문을 다 받은 뒤 앱을 부른다(1GiB까지, 512KiB 넘는 것은 임시 파일). 이전에는 헤더만 보고 401/403을 내고 본문을 읽지 않았다. 인증 안 된 클라이언트가 연결당 최대 `max_body`를 디스크에 쓰게 할 수 있다. 상한은 `connection_limit × max_body`이고 내부망 전용(deploy ADR 0032)이라 수용했다. 줄이려면 앞단 프록시에서 인증하거나 `max_body`를 실제 크기에 맞춘다.
3. **연결 상한 초과**: 이전 즉시 503에서, waitress는 상한에 닿으면 새 연결 수락을 멈추고 backlog에서 기다리게 한다. 503을 내지 않는다.
4. **헤더 수신 총 시간 마감 없음**: waitress는 비동기라 느린 헤더가 작업 스레드를 잡지 않는다(시험으로 확인: 헤더를 흘리는 연결 8개가 있어도 다른 요청이 2초 안에 처리됨). 다만 바이트를 계속 흘리면 `channel_timeout`에 걸리지 않고 연결 한 칸을 차지한다(연결 상한이 방어선). 이전 10초 총 마감은 사라졌다.
5. **너무 긴 요청 줄**: 64KiB 초과 414에서, 헤더 전체 262144바이트(waitress 기본) 초과 시 431로. 그 아래는 앱이 인증부터 답한다.
6. **WSGI 경로**: `PATH_INFO`는 퍼센트 디코딩돼 있어 `%2F`가 `/`로 바뀐다. 앱은 `REQUEST_URI`의 원래 경로를 라우팅에 쓴다.

## 검토한 대안
- gunicorn(prefork): 프로세스마다 락·슬롯이 따로 생겨 데이터셋 락과 슬롯 상한이 깨진다. 버린다.
- uvicorn/ASGI: 앱이 동기 파일 I/O 중심이라 얻는 것이 없다.
- 직접 유지: D111이 정한 방향과 반대다.

## 결과
얻는 것: 연결·timeout·본문 상한·스레드를 설정으로 얻고 자체 서버 코드 약 150줄이 사라졌다. 감수하는 것: 위 동작 변화, 의존 하나 추가(`waitress==3.0.2`, `requirements.lock`, `requirements-service.txt`).

## 되돌리는 조건
인증 전 본문 수신(2번)이 문제가 되고 프록시 앞단 인증을 둘 수 없다면, 본문 크기 상한을 낮추거나 이 서버를 앞단 인증이 있는 구성으로 바꾸는 새 ADR을 쓴다.
