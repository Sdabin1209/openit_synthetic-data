"""dataset-store 서버의 성질. 시간·실제 소켓 타이밍에 기대는 시험은 두지 않는다(tests/TIMING.md).

느린 연결을 N초에 끊는가, 유휴 연결이 닫히는가, 큰 본문이 413인가, 연결 폭주 뒤 회복하는가, SIGTERM에 멈추는가는 waitress·openit_link·운영체제의 동작이다(분류 A: 라이브러리).
의존은 시험하지 않는다(표준 관행). 이 영역의 책임은 둘이다: (1) 올바른 값을 넘겼는가(아래 test_*_values), (2) 우리 코드의 종료 절차가 맞는가(진행 중 요청 마무리).
실제 서버가 끝까지 맞물리는지는 scripts/smoke_service.sh와 deploy E2E의 몫이다."""
from __future__ import annotations

import signal
import threading
import types

import pytest

from synthetic_data.components import link_dataset_store_server as mod
from conftest import HANG_GUARD_SECONDS
from test_service import FakeClock, Srv, WT


def test_waitress_receives_the_configured_limits(tmp_path, monkeypatch):
    """(1) 값 확인: 연결 상한·유휴 timeout·스레드 수·본문 상한이 waitress에 그대로 간다(시간을 재지 않는다)."""
    seen = {}
    monkeypatch.setattr(mod, "create_server", lambda app, **kw: seen.update(kw) or object())
    s = Srv.__new__(Srv)
    from test_service import Service, FileDatasetStore, Survey, SURVEY_DIR, parse_tokens, RT
    svc = Service(FileDatasetStore(tmp_path / "root" / "datasets", Survey(SURVEY_DIR).contract_version), tmp_path / "root",
                  parse_tokens(f"model-lab={RT}"), parse_tokens(f"synthetic-data={WT}"), log=lambda m: None, max_body=1234, clock=FakeClock())
    mod.make_server(svc, "127.0.0.1", 0, threads=3, connection_limit=7, channel_timeout=11, drain_grace=5)
    assert (seen["threads"], seen["connection_limit"], seen["channel_timeout"], seen["max_request_body_size"]) == (3, 7, 11, 1234)
    assert seen["clear_untrusted_proxy_headers"] is True


def test_defaults_are_the_documented_starting_values():
    """ADR 0012·0017의 시작값(측정 안 함)이 그대로다. 값을 바꾸면 ADR을 먼저 고친다."""
    assert (mod.DEFAULT_THREADS, mod.DEFAULT_CONNECTIONS, mod.DEFAULT_IDLE_TIMEOUT, mod.DEFAULT_DRAIN_GRACE) == (16, 32, 30, 8)


def test_publish_route_uses_the_service_body_limit(tmp_path):
    """(1) 값 확인: 413은 openit_link.Route(max_body)가 낸다(라이브러리). 우리는 서비스 설정을 그대로 넘기고 본문을 스트리밍으로 받는다."""
    s = Srv(tmp_path, max_body=1000)
    try:
        post = next(r for r in mod.make_routes(s.svc) if r.method == "POST")
        assert post.max_body == 1000 and post.stream_body is True
    finally:
        s.close()


def test_in_flight_request_finishes_when_server_is_shutting_down(tmp_path):
    """(우리 코드) 종료 절차: 종료 신호를 받은 뒤에도 진행 중인 요청은 끝까지 응답한다. 사건으로만 순서를 맞춘다(sleep·벽시계 없음)."""
    s = Srv(tmp_path)      # 가짜 시계는 멈춰 있어 드레인 한도가 지나지 않는다: 진행 중 요청이 끝나야만 close가 돌아온다
    orig = s.svc.list_ids
    started, release = threading.Event(), threading.Event()

    def blocked_list():
        started.set()                         # 요청이 처리 중이라는 신호
        assert release.wait(HANG_GUARD_SECONDS)      # 종료 신호가 선 뒤 아래 스레드가 풀어 준다
        return orig()
    s.svc.list_ids = blocked_list
    out = {}
    t = threading.Thread(target=lambda: out.update(r=s.call("GET", "/v1/datasets")))
    t.start()
    assert started.wait(HANG_GUARD_SECONDS)

    def release_after_stop():
        assert s.httpd._stop.wait(HANG_GUARD_SECONDS)      # 종료 신호가 서면 곧바로 깨어난다(Event 대기)
        release.set()
    threading.Thread(target=release_after_stop, daemon=True).start()
    s.close()                                 # 종료 신호 + 드레인 + 서버 닫기
    t.join(HANG_GUARD_SECONDS)
    assert out["r"][0] == 200


def _drain_server(tmp_path, monkeypatch, channels, grace):
    """드레인이 보는 최소 인터페이스만 가진 가짜 waitress 서버(active_channels)로 DatasetServer를 만든다."""
    fake = types.SimpleNamespace(active_channels=channels)
    monkeypatch.setattr(mod, "create_server", lambda app, **kw: fake)
    from test_service import Service, FileDatasetStore, Survey, SURVEY_DIR, parse_tokens, RT
    clock = FakeClock()
    svc = Service(FileDatasetStore(tmp_path / "root" / "datasets", Survey(SURVEY_DIR).contract_version), tmp_path / "root",
                  parse_tokens(f"model-lab={RT}"), parse_tokens(f"synthetic-data={WT}"), log=lambda m: None, clock=clock)
    return mod.make_server(svc, "127.0.0.1", 0, drain_grace=grace), clock


def test_drain_gives_up_when_the_grace_passes_with_a_request_that_never_ends(tmp_path, monkeypatch):
    """(우리 코드) 끝나지 않는 진행 중 요청이 있으면 drain_grace가 지난 뒤 포기한다. 시계는 시험이 흘린다(poll 한 번에 1초), 실제로 기다리지 않는다."""
    busy = types.SimpleNamespace(requests=[1], total_outbufs_len=0, request=None)      # 요청이 하나 처리 중인 채널(끝나지 않는다)
    srv, clock = _drain_server(tmp_path, monkeypatch, {1: busy}, grace=8)
    polls = []
    assert srv._drain(lambda: (polls.append(1), clock.advance(1.0))) is False
    assert len(polls) == 8 and busy.requests == [1]      # 한도(8초)만큼 흘린 뒤 포기했고 요청은 끝나지 않은 채다


def test_drain_returns_at_once_when_nothing_is_in_flight(tmp_path, monkeypatch):
    idle = types.SimpleNamespace(requests=[], total_outbufs_len=0, request=None)
    srv, clock = _drain_server(tmp_path, monkeypatch, {1: idle}, grace=8)
    polls = []
    assert srv._drain(lambda: polls.append(1)) is True and polls == []


def test_drain_finishes_when_the_request_ends_before_the_grace(tmp_path, monkeypatch):
    busy = types.SimpleNamespace(requests=[1], total_outbufs_len=0, request=None)
    srv, clock = _drain_server(tmp_path, monkeypatch, {1: busy}, grace=8)

    def poll():
        clock.advance(1.0)
        if clock() >= 1003.0:
            busy.requests = []      # 3초째에 요청이 끝난다
    assert srv._drain(poll) is True


def test_sigterm_handler_stops_the_server_loop(tmp_path, monkeypatch):
    """(우리 코드) 진입점(wiring/service.main)이 SIGTERM·SIGINT에 서버 정지 사건을 세운다. 실제 신호·프로세스 없이 등록된 처리기를 직접 부른다(신호 전달은 운영체제 몫).
    설정 값 확인(1)도 겸한다: DATASET_STORE_DRAIN_GRACE가 서버에 간다."""
    from conftest import SURVEY_DIR
    from synthetic_data.wiring import service as wsvc
    handlers, made = {}, {}

    class FakeSrv:
        _stop = threading.Event()
        server_address = ("127.0.0.1", 1234)

        def serve_forever(self):
            handlers[signal.SIGTERM](signal.SIGTERM, None)      # 종료 신호가 온 것으로 처리기를 부른다
            assert self._stop.is_set()

        def server_close(self):
            made["closed"] = True

    def fake_make_server(svc, host, port, **kw):
        made.update(kw, host=host)
        return FakeSrv()
    monkeypatch.setattr(wsvc, "make_server", fake_make_server)
    monkeypatch.setattr(wsvc.signal, "signal", lambda sig, fn: handlers.update({sig: fn}))
    env = {"DATASET_STORE_ROOT": str(tmp_path / "r"), "DATASET_STORE_SURVEY_SCHEMA_DIR": str(SURVEY_DIR), "DATASET_STORE_PORT": "0",
           "DATASET_STORE_HOST": "127.0.0.1", "DATASET_STORE_READ_TOKENS": "model-lab=" + "ab12cd34" * 4, "DATASET_STORE_DRAIN_GRACE": "2"}
    assert wsvc.main(env) == 0
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT} and made["closed"] and made["drain_grace"] == 2.0
