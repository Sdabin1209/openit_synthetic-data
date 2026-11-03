"""U99(TLS 점검): 영역은 TLS 서버가 되지 않고(사이드카가 끝낸다), 나가는 HTTPS는 표준 환경 변수(SSL_CERT_FILE)만으로 사설 루트를 믿는다.
고정 주소·검증 끄기·sslmode 덮어쓰기가 코드에 없는지, 사설 루트를 SSL_CERT_FILE로 믿는 HTTPS 호출이 되는지 확인한다.
왜 시험 안에서 인증서를 만드나: 시험이 외부 CA나 설치처에 기대지 않게 한다(openssl 명령 도구만 쓴다)."""
from __future__ import annotations

import re
import shutil
import ssl
import subprocess
import threading
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
