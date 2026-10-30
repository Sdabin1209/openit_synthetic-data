"""D4(표준성 점검 2026-10-29, 단계 B): 영역 사이 서비스 API의 인증 상태 코드.
기대값은 CONVENTIONS.md 9절 '401과 403' 보충 규칙(D106)과 RFC 9110 15.5.2·11.6.1, RFC 6750 3절에서 온다:
토큰이 없거나 틀리면 401 + `WWW-Authenticate: Bearer`, 토큰은 맞지만 권한이 없을 때(읽기 토큰으로 게시)만 403, 본문 code는 둘 다 PERMISSION_DENIED.
/healthz·/readyz는 인증이 없다. 과다 요청(인증 실패 제한)은 503 UNAVAILABLE이다(같은 절 '과다 요청'). 요청은 raw HTTP로 보낸다."""
from __future__ import annotations

import json
import socket

import pytest

from test_service import RT, WT, Srv


def raw(srv, method, path, token=None, body=b"", scheme="Bearer"):
    host, port = srv.httpd.server_address[:2]
    h = f"{method} {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\nContent-Length: {len(body)}\r\n"
    if token is not None:
        h += f"Authorization: {scheme} {token}\r\n"
    with socket.create_connection((host, port), timeout=30) as s:      # 바깥 마감(부하 여유)
        s.sendall(h.encode() + b"\r\n" + body)
        buf = b""
        while chunk := s.recv(65536):
            buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    hdrs = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
    return int(lines[0].split()[1]), hdrs, rest


@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path)
    yield s
    s.close()


@pytest.mark.parametrize("method,path", [("GET", "/v1/datasets"), ("POST", "/v1/datasets"), ("GET", "/v1/datasets/x/versions")])
@pytest.mark.parametrize("token", [None, "x" * 40])
def test_missing_or_wrong_token_is_401_with_www_authenticate(srv, method, path, token):
    code, hdrs, body = raw(srv, method, path, token, b"{}" if method == "POST" else b"")
    assert code == 401 and hdrs.get("www-authenticate") == "Bearer"
    assert json.loads(body)["code"] == "PERMISSION_DENIED"


def test_wrong_scheme_is_401(srv):
    code, hdrs, _ = raw(srv, "GET", "/v1/datasets", RT, scheme="Basic")
    assert code == 401 and hdrs.get("www-authenticate") == "Bearer"


def test_valid_read_token_cannot_publish_is_403_without_www_authenticate(srv):
    code, hdrs, body = raw(srv, "POST", "/v1/datasets", RT, b"{}")
    assert code == 403 and "www-authenticate" not in hdrs
    assert json.loads(body)["code"] == "PERMISSION_DENIED"


def test_valid_tokens_and_unauthenticated_probes_unchanged(srv):
    assert raw(srv, "GET", "/v1/datasets", RT)[0] == 200
    assert raw(srv, "GET", "/v1/datasets", WT)[0] == 200
    assert raw(srv, "GET", "/healthz")[0] == 200 and raw(srv, "GET", "/readyz")[0] == 200


def test_throttle_is_503_unavailable_not_429(tmp_path):
    s = Srv(tmp_path, auth_fail_limit=2)
    try:
        for _ in range(2):
            assert raw(s, "GET", "/v1/datasets", "y" * 40)[0] == 401
        code, hdrs, body = raw(s, "GET", "/v1/datasets", RT)
        assert code == 503 and json.loads(body)["code"] == "UNAVAILABLE"      # 영역 사이 서비스 API는 429가 아니라 503
        assert raw(s, "GET", "/healthz")[0] == 200
    finally:
        s.close()


def test_role_failure_403_is_not_counted_as_auth_failure(tmp_path):
    s = Srv(tmp_path, auth_fail_limit=2)
    try:
        for _ in range(5):
            assert raw(s, "POST", "/v1/datasets", RT, b"{}")[0] == 403
        assert raw(s, "GET", "/v1/datasets", RT)[0] == 200
    finally:
        s.close()
