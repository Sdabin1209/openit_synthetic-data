"""HTTP 서버 구현(표준 도구로 교체)이 보장해야 하는 성질. 구현이 바뀌어도 이 성질은 같다(D111).

왜 따로 두나: 교체 전후에 같은 시험이 통과해야 '동작을 바꾸지 않았다'를 말할 수 있다.
  1. 느린 클라이언트(헤더를 흘리는 연결)가 다른 요청을 막지 않는다.
  2. 유휴 연결은 timeout 뒤 서버가 닫는다.
  3. 종료 신호에 진행 중 요청은 끝까지 응답한다.
  4. 상한을 넘는 본문은 거절하고 서버는 계속 일한다.
  5. 연결을 많이 열었다 닫아도 서버가 회복한다."""
from __future__ import annotations

import socket
import threading
import time

from test_service import Srv, WT


def _conn(s):
    c = socket.create_connection(("127.0.0.1", s.httpd.server_address[1]))
    c.settimeout(30)      # 왜 30초: 판정은 응답·종료 여부이고 시간이 아니다. 이 값은 서버가 매달릴 때만 닿는 바깥 마감이다(부하 아래 느려져도 판정이 갈리지 않게 넉넉히)
    return c


def test_slow_header_clients_do_not_block_other_requests(tmp_path):
    s = Srv(tmp_path, **Srv.IDLE(30.0))
    slow = []
    try:
        for _ in range(8):
            c = _conn(s)
            c.sendall(b"GET /v1/datasets HTTP/1.1\r\nHost: x\r\nX-A: ab")      # 헤더를 끝내지 않는다
            slow.append(c)
        # 느린 머리글 연결 8개가 있어도 다른 요청이 응답을 받는다. 응답 시간은 재지 않는다(call의 10초 마감이 바깥 마감, 벽시계 상한은 부하에 흔들린다)
        assert s.call("GET", "/v1/datasets")[0] == 200
    finally:
        for c in slow:
            c.close()
        s.close()


def test_idle_connection_is_closed_after_timeout(tmp_path):
    s = Srv(tmp_path, **Srv.IDLE(1.0))
    try:
        c = _conn(s)
        c.settimeout(60)      # 바깥 마감: 서버가 닫지 않으면 여기서 timeout 예외로 실패한다. 닫는 시점은 재지 않는다(부하에 흔들림)
        assert c.recv(10) == b""                  # 아무것도 보내지 않으면 서버가 닫는다
        c.close()
        assert s.call("GET", "/v1/datasets")[0] == 200
    finally:
        s.close()


def test_in_flight_request_finishes_when_server_is_shutting_down(tmp_path):
    s = Srv(tmp_path)
    orig = s.svc.list_ids
    started = threading.Event()

    def slow_list():
        started.set()                             # 요청이 처리 중이라는 신호(고정 sleep 대신 사건으로 기다린다)
        time.sleep(0.8)
        return orig()
    s.svc.list_ids = slow_list
    out = {}
    t = threading.Thread(target=lambda: out.update(r=s.call("GET", "/v1/datasets")))
    t.start()
    assert started.wait(30)                       # 요청이 처리 중이다
    s.close()                                     # 종료 신호 + 서버 닫기
    t.join(60)
    assert out["r"][0] == 200


def test_oversized_body_is_refused_and_server_keeps_working(tmp_path):
    s = Srv(tmp_path, max_body=1000)
    try:
        c = _conn(s)
        c.sendall(b"POST /v1/datasets HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + WT.encode()
                  + b"\r\nContent-Length: 5000\r\n\r\n")      # 머리글만 보낸다: 서버가 Content-Length만 보고 413을 보내고 닫는 동안 본문을 보내면 연결 재설정 경쟁이 난다
        status = c.recv(200).split(b" ")[1]
        assert status in (b"400", b"413")
        c.close()
        assert s.call("GET", "/v1/datasets")[0] == 200
    finally:
        s.close()


def test_server_recovers_after_connection_flood(tmp_path):
    s = Srv(tmp_path)
    flood = []
    try:
        for _ in range(60):
            try:
                flood.append(_conn(s))
            except OSError:
                break
        for c in flood:
            c.close()
        deadline = time.monotonic() + 60      # 바깥 마감(회복 여부가 판정, 속도는 아니다)
        code = None
        while time.monotonic() < deadline:
            code = s.call("GET", "/v1/datasets")[0]
            if code == 200:
                break
            time.sleep(0.2)
        assert code == 200
    finally:
        s.close()


def test_sigterm_stops_the_service_process_cleanly(tmp_path):
    """진입점(python -m synthetic_data.service)이 SIGTERM에 종료 코드 0으로 끝난다(컨테이너 stop)."""
    import os
    import signal
    import subprocess
    import sys
    import urllib.request
    from conftest import SURVEY_DIR
    env = {**os.environ, "DATASET_STORE_ROOT": str(tmp_path / "r"), "DATASET_STORE_SURVEY_SCHEMA_DIR": str(SURVEY_DIR),
           "DATASET_STORE_PORT": "0", "DATASET_STORE_HOST": "127.0.0.1", "DATASET_STORE_READ_TOKENS": "model-lab=" + "ab12cd34" * 4,
           "DATASET_STORE_DRAIN_GRACE": "2"}
    p = subprocess.Popen([sys.executable, "-m", "synthetic_data.service"], env=env, stdout=subprocess.PIPE, text=True)
    try:
        port = int(p.stdout.readline().split()[-1])
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=30).status == 200
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=60) == 0      # 바깥 마감: 종료 코드가 판정이고 종료 속도는 아니다(드레인 2초 + 부하 여유)
    finally:
        if p.poll() is None:
            p.kill()
