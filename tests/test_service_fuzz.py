"""I2 서버 퍼징 성격 시험(시드 고정): 무작위 경로·헤더·메서드·tar 항목 이름과 크기를 보내도 크래시·5xx 없이
정의된 오류 코드만 나오는지 본다. 표준 라이브러리 HTTP 서버라 파서 결함이 이후에도 나올 수 있어 둔다(ADR 0012)."""
from __future__ import annotations

import http.client
import socket
import random

import pytest

from conftest import HANG_GUARD_SECONDS

from test_service import RT, WT, Srv, tar_of

# 왜: HTTP.md가 정의한 오류 코드(+성공 코드). 5xx(503 제외)나 이 밖의 코드는 처리되지 않은 예외로 본다.
OK = {200, 201, 204}
DEFINED = OK | {400, 401, 403, 404, 405, 409, 413, 422, 429, 503}
SEED = 20261028
ALPHABET = ["a", "Z", "0", ".", "..", "/", "\\", "%2F", "%2f", "%00", "%", "?", "#", " ", "é", "한", "\x01", ";", "=", "~", "*"]


def rnd_text(r, n=12):
    return "".join(r.choice(ALPHABET) for _ in range(r.randint(0, n)))


def raw(srv, method, target, headers, body=None):
    host, port = srv.url.replace("http://", "").split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=HANG_GUARD_SECONDS)      # 시간 초과는 None(허용)으로 처리돼 거짓 통과만 낼 수 있다(아래 except)
    try:
        c.putrequest(method, target, skip_host=False, skip_accept_encoding=True)
        for k, v in headers:
            c.putheader(k, v)
        c.endheaders(body)
        c.sock.shutdown(socket.SHUT_WR)      # 요청을 다 보냈다고 알린다: Content-Length보다 짧은 본문에서 서버가 더 기다리지 않고 바로 닫는다(실제 시간을 기다리지 않는다)
        r = c.getresponse()
        r.read()
        return r.status
    except (http.client.HTTPException, ConnectionError, OSError, UnicodeError):
        return None                                  # 서버가 연결을 닫는 것은 허용(크래시 아님); 서버 생존은 마지막에 확인
    finally:
        c.close()


@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path)
    yield s
    s.close()


def test_fuzz_paths_headers_methods(srv):
    r = random.Random(SEED)
    bad = []
    for _ in range(300):
        method = r.choice(["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS", rnd_text(r, 4) or "X"])
        target = "/" + r.choice(["v1/datasets", "v1/datasets/ds", "healthz", "readyz", ""]) + "/".join(rnd_text(r) for _ in range(r.randint(0, 4)))
        hdr = []
        tok = r.choice([RT, WT, rnd_text(r, 40), "", None])
        if tok is not None:
            hdr.append(("Authorization", r.choice(["Bearer ", "bearer ", "Basic ", ""]) + tok))
        if r.random() < .3:
            hdr.append(("Content-Length", r.choice(["-1", "abc", "99999999999999999999", "0", "5"])))
        if r.random() < .3:
            hdr.append((rnd_text(r, 8) or "X-F", rnd_text(r, 200)))
        body = None if r.random() < .6 else bytes(r.getrandbits(8) for _ in range(r.randint(0, 64)))
        if body is not None and not any(k == "Content-Length" for k, _ in hdr):
            hdr.append(("Content-Length", str(len(body))))
        try:
            st = raw(srv, method, target, hdr, body)
        except (ValueError, UnicodeError):
            continue                                  # 클라이언트가 보내지 못하는 조합
        known = method in {"GET", "POST", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"}
        if st == 501 and not known:
            continue                                  # RFC 9110 15.6.2: 모르는 메서드 토큰은 501
        if st is not None and st not in DEFINED:
            bad.append((method, target, hdr, st))
    assert not bad, bad[:5]
    assert srv.call("GET", "/healthz", token=None)[0] == 200         # 서버가 계속 산다


def test_fuzz_publish_tar_entries(srv, captured):
    r = random.Random(SEED + 1)
    m, blobs = captured
    bad = []
    for _ in range(120):
        entries = {"manifest.json": r.choice([b"{}", b"[", b"", b"\xff\xfe", __import__("json").dumps(m).encode()])}
        for _ in range(r.randint(0, 4)):
            name = r.choice(["files/", "", "/", "../x", "files/../../x", "manifest.json", "files/" + rnd_text(r), rnd_text(r, 30)])
            entries[name or "x"] = bytes(r.getrandbits(8) for _ in range(r.choice([0, 1, 100, 5000])))
        body = tar_of(entries) if r.random() < .8 else bytes(r.getrandbits(8) for _ in range(r.randint(0, 2000)))
        if r.random() < .2:
            body = body[: r.randint(0, len(body))]      # 잘린 tar
        st, _, _ = srv.call("POST", "/v1/datasets", body, WT)
        if st not in DEFINED:
            bad.append((st, list(entries)))
        assert st != 201 or entries["manifest.json"].startswith(b"{")
    assert not bad, bad[:5]
    assert srv.call("GET", "/healthz", token=None)[0] == 200
