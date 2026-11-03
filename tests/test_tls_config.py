"""U99(TLS 점검): 영역은 TLS 서버가 되지 않고(사이드카가 끝낸다), 나가는 HTTPS는 표준 환경 변수(SSL_CERT_FILE)만으로 사설 루트를 믿는다.
고정 주소·검증 끄기·sslmode 덮어쓰기가 코드에 없는지, 사설 루트를 SSL_CERT_FILE로 믿는 HTTPS 호출이 되는지 확인한다.
왜 시험 안에서 인증서를 만드나: 시험이 외부 CA나 설치처에 기대지 않게 한다(openssl 명령 도구만 쓴다)."""
from __future__ import annotations

import re
import threading
import shutil
import ssl
import subprocess

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from boundary_contracts.errors import BoundaryError
from openit_link.clients import HttpDatasetStore
from conftest import HANG_GUARD_SECONDS

PKG = Path(__file__).resolve().parent.parent / "synthetic_data"
CODE = [p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts and p.name != "schema_registry.py" and "_schema.py" not in p.name]


def test_no_hardcoded_service_address_in_code():
    # 이웃 호출 주소는 설정(base_url)으로만 들어온다. 코드에 http(s):// 문자열이 있으면 docstring 밖 리터럴이라도 실패시킨다(스키마 $id·표준 URL 제외)
    bad = []
    for p in CODE:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"https?://", line) and "json-schema.org" not in line and "openit.invalid" not in line:
                bad.append(f"{p.relative_to(PKG)}:{i}")
    assert not bad, bad


def test_no_code_disables_verification_or_overrides_sslmode():
    pat = re.compile(r"verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False|_create_unverified_context|sslmode")
    bad = [f"{p.relative_to(PKG)}:{i}" for p in CODE for i, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pat.search(l)]
    assert not bad, bad


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl 명령 도구가 없다")
def test_https_call_trusts_private_root_via_ssl_cert_file(tmp_path, monkeypatch):
    def sh(*a):
        subprocess.run(a, cwd=tmp_path, check=True, capture_output=True, timeout=HANG_GUARD_SECONDS)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "root.key", "-out", "root.pem", "-days", "1", "-subj", "/CN=test-root",
       "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign")
    sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "srv.key", "-out", "srv.csr", "-subj", "/CN=localhost")
    (tmp_path / "ext.cnf").write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=CA:FALSE\n")
    sh("openssl", "x509", "-req", "-in", "srv.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-out", "srv.pem", "-days", "1", "-extfile", "ext.cnf")

    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "srv.pem", tmp_path / "srv.key")
    httpd = HTTPServer(("127.0.0.1", 0), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"https://localhost:{httpd.server_address[1]}"
    try:
        # 루트를 알리지 않으면 검증이 실패한다(연결 불가). 시스템 저장소가 이 루트를 모르는 것이 전제다.
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        with pytest.raises(BoundaryError) as ei:
            HttpDatasetStore(url, "tok", 5).get_manifest("ds-x", "1")
        assert ei.value.code == "UNAVAILABLE" and not seen
        # 표준 환경 변수만으로 사설 루트를 믿는다(클라이언트 설정 변경 없음)
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "root.pem"))
        try:
            HttpDatasetStore(url, "tok", 5).get_manifest("ds-x", "1")
        except BoundaryError:
            pass      # 본문 `{}`는 계약 위반일 수 있다. 여기서 보는 것은 TLS 핸드셰이크와 요청 도달뿐이다.
        assert seen, "TLS 핸드셰이크 뒤 요청이 서버에 닿지 않았다"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_client_refuses_plain_http_outside_loopback():
    # 계약 v3.4.1: loopback 밖 http://는 생성 시 거부된다. 이 영역은 계약 클라이언트로만 이웃을 부르므로(직접 urllib 호출 없음) 이 거부가 곧 영역의 보증이다.
    with pytest.raises(ValueError):
        HttpDatasetStore("http://dataset-store:8080", "tok", 5)
    HttpDatasetStore("http://127.0.0.1:1", "tok", 5)


def test_server_binds_only_to_the_given_host(tmp_path):
    # DATASET_STORE_HOST=127.0.0.1이면 그 주소에만 붙는다(0.0.0.0이 아니다). 사이드카 뒤에서 바깥 인터페이스에 평문을 열지 않기 위해서다.
    from test_service import Srv
    s = Srv(tmp_path / "srv")
    try:
        assert s.httpd.server_address[0] == "127.0.0.1"
    finally:
        s.close()


def test_log_write_failure_does_not_fail_the_request(tmp_path):
    # R10.5: 로그 쓰기가 예외를 내도 요청은 200이다(요청 로그 줄이 실패해도 응답을 막지 않는다)
    from test_service import Srv
    def broken(msg):
        raise OSError("로그 쓰기 실패")
    s = Srv(tmp_path / "srv", log=broken)
    try:
        st, body, _ = s.call("GET", "/healthz", token=None)
        assert st == 200
    finally:
        s.close()


def test_default_timeouts_follow_r10_3():
    from synthetic_data.components import import_plan, run_plan, link_question_reader, link_failure_reader
    import inspect
    assert import_plan.DEFAULT_TIMEOUT == run_plan.DEFAULT_TIMEOUT == 300.0      # tar 게시
    for fn in (link_question_reader.http_question_reader, link_failure_reader.http_failure_store):
        assert inspect.signature(fn).parameters["timeout"].default == 10.0


# --- RUNTIME 3.4.4 대조 (R5.1, R10.11, R8.1, R3.10, R4.1, R1.8) ---
def _get(srv, path, token=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(srv.url + path, headers={"Authorization": "Bearer " + token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=HANG_GUARD_SECONDS) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_health_bodies_follow_health_status_and_not_ready_spelling(tmp_path):
    # R5.1: 200 + 비어 있지 않은 HealthStatus 본문, 아님은 503 + status=not_ready
    import json
    from boundary_contracts import validator
    from test_service import Srv
    s = Srv(tmp_path / "srv")
    try:
        for path, want in (("/healthz", "ok"), ("/readyz", "ready")):
            st, body, _ = _get(s, path)
            assert st == 200 and json.loads(body)["status"] == want
            validator("HealthStatus").validate(json.loads(body))
        good = s.svc.tmp
        s.svc.tmp = tmp_path / "no-such-dir" / "x"      # 저장소 쓰기 불가를 만든다
        st, body, _ = _get(s, "/readyz")
        assert st == 503 and json.loads(body)["status"] == "not_ready"
        validator("HealthStatus").validate(json.loads(body))
        # R4.1: 저장소가 돌아오면 재시작 없이 다시 ready
        s.svc.tmp = good
        assert _get(s, "/readyz")[0] == 200
    finally:
        s.close()


def test_metrics_is_unauthenticated_prometheus_text_and_200_while_storage_is_down(tmp_path):
    # R10.11: 인증 없음(토큰이 틀려도 401·403 없음), Prometheus 텍스트, 저장소가 멈춰도 200
    from test_service import Srv
    s = Srv(tmp_path / "srv")
    try:
        s.svc.tmp = tmp_path / "no-such-dir" / "x"
        assert _get(s, "/readyz")[0] == 503
        for tok in (None, "wrong-token"):
            st, body, h = _get(s, "/metrics", tok)
            assert st == 200 and h["Content-Type"].startswith("text/plain")
            text = body.decode()
            assert "# TYPE dataset_store_up gauge\ndataset_store_up 1\n" in text
    finally:
        s.close()


def test_internal_error_log_has_class_and_location_without_message(tmp_path, monkeypatch):
    # R8.1: 앱 바깥 층(make_app)에서 잡은 503 내부 오류는 예외 종류와 위치(파일:줄)만 로그에 남기고 메시지는 남기지 않는다
    import re
    from synthetic_data.components import link_dataset_store_server as m
    from test_service import Srv
    class Exploding:
        def __init__(self, *a, **k):
            pass
        def __call__(self, environ, start_response):
            raise RuntimeError("SECRET-MESSAGE-31337")
    monkeypatch.setattr(m, "App", Exploding)
    logs = []
    s = Srv(tmp_path / "srv", log=logs.append)
    try:
        st, body, _ = _get(s, "/v1/datasets")
        assert st == 503 and b"SECRET-MESSAGE-31337" not in body
        line = [l for l in logs if "내부 오류" in l]
        assert line and re.search(r"내부 오류 RuntimeError \S+\.py:\d+", line[0]) and "SECRET-MESSAGE" not in line[0]
    finally:
        s.close()


def test_job_clients_go_out_through_the_area_egress_proxy(tmp_path, monkeypatch):
    # R1.8·CONVENTIONS 13: 이웃(I1)을 부르는 클라이언트는 OPENIT_EGRESS_PROXY의 CONNECT 터널로만 나간다.
    # 가짜 프록시가 CONNECT 줄을 기록하고 403으로 거절한다 -> 계약 클라이언트는 직접 연결하지 않았다.
    import socket
    from synthetic_data.wiring.run_job import load_factory
    seen = []
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(1)

    def serve():
        c, _ = ls.accept()
        seen.append(c.recv(4096).split(b"\r\n")[0])
        c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        c.close()
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    tok = tmp_path / "tok"
    tok.write_text("t" * 40)
    monkeypatch.setenv("SD_TEST_TOKEN_FILE", str(tok))
    monkeypatch.setenv("OPENIT_EGRESS_PROXY", f"http://127.0.0.1:{ls.getsockname()[1]}")
    spec = {"factory": "synthetic_data.adapters:http_question_reader", "kwargs": {"base_url": "https://question-authoring:8443", "token_env": "SD_TEST_TOKEN"}}
    try:
        with pytest.raises(BoundaryError):
            load_factory(spec)(**spec["kwargs"]).latest("qs-main", reviewed_only=True)
        t.join(HANG_GUARD_SECONDS)
        assert seen == [b"CONNECT question-authoring:8443 HTTP/1.1"]
    finally:
        ls.close()


def test_publish_client_also_uses_the_egress_proxy(tmp_path, monkeypatch):
    # R1.8: 잡의 게시 클라이언트(I2)도 OPENIT_EGRESS_PROXY를 egress_proxy로 받는다(잘못된 형식이면 클라이언트가 거부 = 값이 클라이언트까지 닿았다는 증거)
    from synthetic_data.components import link_dataset_publish
    tok = tmp_path / "tok"
    tok.write_text("t" * 40)
    monkeypatch.setenv("SD_TEST_TOKEN_FILE", str(tok))
    spec = {"base_url": "https://dataset-store:8443", "token_env": "SD_TEST_TOKEN", "timeout": 300.0}
    monkeypatch.setenv("OPENIT_EGRESS_PROXY", "http://example.org:3128")      # loopback 밖은 계약이 거부한다
    with pytest.raises(ValueError):
        link_dataset_publish.build(spec)
    monkeypatch.setenv("OPENIT_EGRESS_PROXY", "http://127.0.0.1:3128")
    link_dataset_publish.build(spec)


def test_survey_schema_location_is_not_an_environment_input():
    # R9.1: 계약 Env 스키마에 없는 입력 이름을 만들지 않는다. 이미지 안 경로는 모듈 상수다
    root = PKG.parent
    text = "\n".join(p.read_text(encoding="utf-8") for p in CODE) + (root / "Dockerfile").read_text(encoding="utf-8")
    assert "SYNTHETIC_SURVEY_SCHEMA_DIR" not in text and "SURVEY_SCHEMA_DIR=" not in text
    assert 'env.get("DATASET_STORE_SURVEY_SCHEMA_DIR"' not in text


def test_image_survey_dir_overrides_job_config_only_inside_the_image(tmp_path, monkeypatch):
    from synthetic_data import config
    monkeypatch.setattr(config, "IMAGE_SURVEY_SCHEMA_DIR", tmp_path / "absent")
    assert config.survey_dir_override() is None            # 개발 환경: 설정의 survey_schema_dir을 쓴다
    (tmp_path / "img").mkdir()
    monkeypatch.setattr(config, "IMAGE_SURVEY_SCHEMA_DIR", tmp_path / "img")
    assert config.survey_dir_override() == str(tmp_path / "img")      # 이미지 안: 이 경로가 우선
