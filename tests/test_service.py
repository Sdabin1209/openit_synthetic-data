"""I2 HTTP 서버(synthetic_data.service) 시험: 읽기/쓰기, 멱등, 버전 불변, 권한·크기·경로 조작.
계약 클라이언트(boundary_contracts.clients.HttpDatasetStore)가 들어오면 test_service_contract.py가 그것으로 같은 서버를 읽는다."""
from __future__ import annotations

import io
import json
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import SURVEY_DIR
from synthetic_data.schemas import Validators
from synthetic_data.service.app import Service, make_server, parse_tokens

RT, WT = "r" * 8 + "abcdef0123456789" * 2, "w" * 8 + "fedcba9876543210" * 2


def tar_of(entries: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def body_of(manifest, blobs) -> bytes:
    e = {"manifest.json": json.dumps(manifest).encode()}
    e.update({"files/" + k: v for k, v in blobs.items()})
    return tar_of(e)


class Srv:
    @staticmethod
    def IDLE(sec):
        """유휴 연결 timeout 설정(구현마다 이름이 다르므로 한 곳에 둔다)."""
        return {"channel_timeout": sec}

    SERVER_KW = ("channel_timeout", "connection_limit", "threads", "drain_grace")

    def __init__(self, tmp_path, **kw):
        skw = {k: kw.pop(k) for k in self.SERVER_KW if k in kw}
        self.svc = Service(tmp_path / "root", Validators(SURVEY_DIR), parse_tokens(f"model-lab={RT}"),
                           parse_tokens(f"synthetic-data={WT}"), log=lambda s: None, **kw)
        self.httpd = make_server(self.svc, **skw)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def call(self, method, path, body=None, token=RT, headers=None):
        h = dict(headers or {})
        if token:
            h["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.url + path, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path)
    yield s
    s.close()


def publish(srv, captured, token=WT):
    m, blobs = captured
    return srv.call("POST", "/v1/datasets", body_of(m, blobs), token)


def test_health_ready_no_auth(srv):
    assert srv.call("GET", "/healthz", token=None)[0] == 200
    assert srv.call("GET", "/readyz", token=None)[0] == 200


def test_publish_read_roundtrip_and_idempotent(srv, captured):
    m, blobs = captured
    st, body, _ = publish(srv, captured)
    assert st == 201 and json.loads(body)["content_hash"] == m["content_hash"]
    assert publish(srv, captured)[0] == 200                                   # 멱등
    did, ver = m["dataset_id"], m["version"]
    assert json.loads(srv.call("GET", "/v1/datasets")[1]) == {"items": [did], "next_cursor": None}
    assert json.loads(srv.call("GET", f"/v1/datasets/{did}/versions")[1])["items"] == [ver]
    assert json.loads(srv.call("GET", f"/v1/datasets/{did}/versions/{ver}")[1]) == m
    st, tb, h = srv.call("GET", f"/v1/datasets/{did}/versions/{ver}/files")
    assert st == 200 and h["Content-Type"] == "application/x-tar"
    with tarfile.open(fileobj=io.BytesIO(tb)) as tf:
        assert {x.name: tf.extractfile(x).read() for x in tf} == blobs
    p0 = m["files"][0]["path"]
    enc = p0.replace("/", "%2F")
    st, b, h = srv.call("GET", f"/v1/datasets/{did}/versions/{ver}/files/{enc}")
    assert st == 200 and b == blobs[p0] and h["Content-Type"] == "application/octet-stream"


def test_version_is_immutable(srv, captured):
    m, blobs = captured
    publish(srv, captured)
    m2 = dict(m)
    m2["created_at"] = "2026-10-16T00:00:00Z"
    from boundary_contracts import canonical
    m2["content_hash"] = canonical.content_hash(m2)
    st, body, _ = srv.call("POST", "/v1/datasets", body_of(m2, blobs), WT)
    assert st == 409 and json.loads(body)["code"] == "CONFLICT"
    assert json.loads(srv.call("GET", f"/v1/datasets/{m['dataset_id']}/versions/{m['version']}")[1]) == m   # 원본 그대로


def test_read_token_cannot_publish_and_no_token(srv, captured):
    assert publish(srv, captured, token=RT)[0] == 403
    assert publish(srv, captured, token=None)[0] == 401      # 토큰 없음/틀림은 401, 권한 부족만 403(CONVENTIONS 9절, D106)
    assert srv.call("GET", "/v1/datasets", token="x" * 40)[0] == 401
    assert srv.call("GET", "/v1/datasets", token=None)[0] == 401
    assert srv.call("GET", "/v1/datasets")[0] == 200
    assert json.loads(srv.call("GET", "/v1/datasets")[1])["items"] == []       # 거절된 게시는 아무것도 남기지 않는다


def test_write_token_can_read(srv, captured):
    publish(srv, captured)
    assert srv.call("GET", "/v1/datasets", token=WT)[0] == 200


def test_missing_is_404(srv, captured):
    m, _ = captured
    assert srv.call("GET", "/v1/datasets/nope/versions/v1")[0] == 404
    publish(srv, captured)
    base = f"/v1/datasets/{m['dataset_id']}/versions/{m['version']}"
    assert srv.call("GET", base + "/files/not-in-manifest.jsonl")[0] == 404


@pytest.mark.parametrize("evil", ["..%2F..%2Fetc%2Fpasswd", "%2Fetc%2Fpasswd", "a%5Cb", "..", "%2E%2E%2Fx"])
def test_path_tampering_on_read(srv, captured, evil):
    m, _ = captured
    publish(srv, captured)
    st, body, _ = srv.call("GET", f"/v1/datasets/{m['dataset_id']}/versions/{m['version']}/files/{evil}")
    assert st in (400, 404) and b"root:" not in body


def test_id_tampering(srv):
    for p in ("/v1/datasets/..%2F..%2Fx/versions", "/v1/datasets/a%2Fb/versions/v1"):
        assert srv.call("GET", p)[0] in (400, 404)


def test_publish_tar_tampering(srv, captured):
    m, blobs = captured
    good = {"manifest.json": json.dumps(m).encode(), **{"files/" + k: v for k, v in blobs.items()}}
    cases = {
        "dotdot": {**good, "files/../../evil": b"x"},
        "absolute": {**good, "/etc/evil": b"x"},
        "stray": {**good, "other.txt": b"x"},
        "extra_file": {**good, "files/extra.jsonl": b"{}\n"},
        "no_manifest": {k: v for k, v in good.items() if k != "manifest.json"},
        "missing_file": {k: v for k, v in good.items() if k != "files/" + m["files"][0]["path"]},
    }
    for name, e in cases.items():
        st, body, _ = srv.call("POST", "/v1/datasets", tar_of(e), WT)
        assert st == 400, name
    assert srv.call("POST", "/v1/datasets", b"not a tar", WT)[0] == 400
    # 심볼릭 링크
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        info = tarfile.TarInfo("manifest.json"); info.type = tarfile.SYMTYPE; info.linkname = "/etc/passwd"
        tf.addfile(info)
    assert srv.call("POST", "/v1/datasets", buf.getvalue(), WT)[0] == 400
    assert json.loads(srv.call("GET", "/v1/datasets")[1])["items"] == []


def test_manifest_path_tampering_and_hash_mismatch(srv, captured):
    m, blobs = captured
    import copy
    from boundary_contracts import canonical
    bad = copy.deepcopy(m)
    bad["files"][0]["path"] = "../x.jsonl"
    bad["content_hash"] = canonical.content_hash(bad)
    assert srv.call("POST", "/v1/datasets", body_of(bad, blobs), WT)[0] == 400
    tampered = dict(blobs)
    k = m["files"][0]["path"]
    tampered[k] = blobs[k] + b"\n"
    assert srv.call("POST", "/v1/datasets", body_of(m, tampered), WT)[0] in (400, 422)


def test_size_limits(tmp_path, captured):
    s = Srv(tmp_path, max_body=1000)
    try:
        st, body, _ = publish(s, captured)
        # 본문 상한은 waitress(max_request_body_size)가 본문을 받기 전에 413으로 거절한다(RFC 9110 15.5.14). 이전 구현은 앱이 400 INVALID_RECORD로 답했다
        assert st == 413
        assert s.call("POST", "/v1/datasets", b"x" * 100, WT, {"Content-Length": "100"})[0] == 400
    finally:
        s.close()


def test_disk_full_is_503(tmp_path, captured):
    s = Srv(tmp_path, free_bytes=lambda: 0)
    try:
        assert publish(s, captured)[0] == 503
    finally:
        s.close()


def test_auth_failure_throttle_blocks_even_valid_token(tmp_path):
    s = Srv(tmp_path, auth_fail_limit=3)
    try:
        for _ in range(3):
            assert s.call("GET", "/v1/datasets", token="y" * 40)[0] == 401
        assert s.call("GET", "/v1/datasets", token="y" * 40)[0] == 503
        assert s.call("GET", "/v1/datasets")[0] == 503          # 차단 중에는 올바른 토큰도 거부(추측이 맞는지 알려 주지 않는다)
        assert s.call("GET", "/healthz", token=None)[0] == 200  # 살아 있음 확인은 인증 전이다
        assert len(s.svc._fails["127.0.0.1"]) == 3             # 차단 중에는 쌓이지 않는다
    finally:
        s.close()


def test_auth_failure_window_expires_and_frees_memory(tmp_path):
    s = Srv(tmp_path, auth_fail_limit=2)
    s.svc.auth_fail_window = 0.3
    try:
        for _ in range(2):
            s.call("GET", "/v1/datasets", token="y" * 40)
        assert s.call("GET", "/v1/datasets")[0] == 503
        time.sleep(0.4)
        assert s.call("GET", "/v1/datasets")[0] == 200
        assert "127.0.0.1" not in s.svc._fails                  # 창이 지나면 주소 항목이 사라진다
    finally:
        s.close()


def test_write_role_must_be_synthetic_data(tmp_path):
    with pytest.raises(ValueError):
        Service(tmp_path / "r", Validators(SURVEY_DIR), {}, parse_tokens("other=" + WT), log=lambda s: None)


def test_secrets_not_in_responses(srv, captured):
    for st, body, _ in (srv.call("GET", "/v1/datasets", token="y" * 40), publish(srv, captured, token=RT)):
        assert RT.encode() not in body and WT.encode() not in body


def test_concurrent_same_version_publish(srv, captured):
    res = []
    ts = [threading.Thread(target=lambda: res.append(publish(srv, captured)[0])) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(res) == [200, 200, 200, 201]


def test_concurrent_same_version_different_content_is_409(srv, captured):
    import copy
    from boundary_contracts import canonical
    m, blobs = captured
    m2 = copy.deepcopy(m)
    m2["created_at"] = "2026-10-16T00:00:00Z"
    m2["content_hash"] = canonical.content_hash(m2)
    res = []
    bodies = [body_of(m, blobs), body_of(m2, blobs)] * 2
    ts = [threading.Thread(target=lambda b=b: res.append(srv.call("POST", "/v1/datasets", b, WT)[0])) for b in bodies]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert 503 not in res and res.count(201) == 1 and set(res) <= {200, 201, 409}


def test_global_publish_limit_is_503(tmp_path, captured):
    s = Srv(tmp_path)
    for _ in range(8):
        s.svc.publish_slots.acquire()
    try:
        assert publish(s, captured)[0] == 503
    finally:
        s.close()


def _raw(srv, data: bytes, wait=0.3) -> bytes:
    import socket
    c = socket.create_connection(("127.0.0.1", srv.httpd.server_address[1]))
    c.settimeout(3)
    c.sendall(data)
    time.sleep(wait)
    try:
        return c.recv(500)
    except OSError:
        return b""
    finally:
        c.close()


@pytest.mark.parametrize("cl", ["abc", "-5", "1, 2", "+3", "1e3"])
def test_bad_content_length_400(srv, cl):
    r = _raw(srv, f"POST /v1/datasets HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {WT}\r\nContent-Length: {cl}\r\n\r\n".encode())
    assert r.startswith(b"HTTP/1.1 400"), r


def test_duplicate_content_length_400(srv):
    r = _raw(srv, f"POST /v1/datasets HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {WT}\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n".encode())
    assert r.startswith(b"HTTP/1.1 400"), r


def test_long_uri_and_bad_request_line_do_not_kill_logging(srv):
    logs = []
    srv.svc.log = logs.append
    # 표준 라이브러리 서버는 64KiB 넘는 요청 줄을 414로 거절했다. waitress는 헤더 전체 262144바이트까지 받고 그 아래는 앱이 인증부터 답한다(401).
    assert _raw(srv, b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n").startswith((b"HTTP/1.1 414", b"HTTP/1.1 401"))
    assert _raw(srv, b"GET /" + b"a" * 300000 + b" HTTP/1.1\r\nHost: x\r\n\r\n").startswith((b"HTTP/1.1 414", b"HTTP/1.0 431"))
    assert b"400" in _raw(srv, b"GARBAGE\r\n\r\n")
    assert not any("내부 오류" in x for x in logs)
    assert srv.call("GET", "/v1/datasets")[0] == 200


def test_tar_name_collisions_and_long_names(srv, captured):
    for e in ({"manifest.json": b"{}", "manifest.json/x": b"1"},
              {"manifest.json": b"{}", "files/a": b"1", "files/a/b": b"1"},
              {"manifest.json": b"{}", "files/" + "a" * 300: b"1"},
              {"manifest.json": b"{}", "./manifest.json": b"[]"},
              {"manifest.json": b"{}", "files/./k": b"1", "files/k": b"2"}):
        assert srv.call("POST", "/v1/datasets", tar_of(e), WT)[0] == 400, list(e)


def test_alias_cannot_overwrite_listed_file(srv, captured):
    m, blobs = captured
    e = {"manifest.json": json.dumps(m).encode(), **{"files/" + k: v for k, v in blobs.items()}}
    e["files/./" + list(blobs)[0]] = b"evil"
    assert srv.call("POST", "/v1/datasets", tar_of(e), WT)[0] == 400


def test_sparse_and_entry_limit(tmp_path, captured):
    s = Srv(tmp_path, max_entries=3)
    try:
        assert s.call("POST", "/v1/datasets", tar_of({f"files/f{i}": b"x" for i in range(4)} | {"manifest.json": b"{}"}), WT)[0] == 400
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:", format=tarfile.GNU_FORMAT) as tf:
            i = tarfile.TarInfo("manifest.json"); i.type = tarfile.GNUTYPE_SPARSE; i.size = 0
            tf.addfile(i)
        assert s.call("POST", "/v1/datasets", buf.getvalue(), WT)[0] == 400
    finally:
        s.close()


def test_disk_check_uses_three_times_body(tmp_path, captured):
    m, blobs = captured
    n = len(body_of(m, blobs))
    s = Srv(tmp_path, min_free_gb=0, free_bytes=lambda: 3 * n - 1)
    s2 = Srv(tmp_path / "b", min_free_gb=0, free_bytes=lambda: 3 * n)
    try:
        assert publish(s, captured)[0] == 503
        assert publish(s2, captured)[0] == 201
    finally:
        s.close(); s2.close()


def test_download_limit_503(srv, captured):
    m, _ = captured
    publish(srv, captured)
    for _ in range(8):
        srv.svc.download_slots.acquire()
    base = f"/v1/datasets/{m['dataset_id']}/versions/{m['version']}"
    assert srv.call("GET", base + "/files")[0] == 503
    assert srv.call("GET", base + "/files/" + m["files"][0]["path"].replace("/", "%2F"))[0] == 503
    assert srv.call("GET", base)[0] == 200                      # manifest 조회는 영향 없다


def test_tampered_stored_file_is_integrity_error_not_served(srv, captured):
    m, _ = captured
    publish(srv, captured)
    p0 = m["files"][0]["path"]
    f = srv.svc.store._vdir(m["dataset_id"], m["version"]) / "files" / p0
    f.write_bytes(f.read_bytes() + b"x")
    base = f"/v1/datasets/{m['dataset_id']}/versions/{m['version']}"
    assert srv.call("GET", base + "/files/" + p0.replace("/", "%2F"))[0] == 422
    assert srv.call("GET", base + "/files")[0] == 422


def test_empty_dataset_dir_hidden_and_startup_cleans_tmp(tmp_path, captured):
    s = Srv(tmp_path)
    try:
        (s.svc.store.root / "ghost").mkdir()
        (s.svc.store.root / "ghost" / ".tmp-abc").mkdir()
        assert json.loads(s.call("GET", "/v1/datasets")[1])["items"] == []
    finally:
        s.close()
    s2 = Srv(tmp_path)      # 같은 루트로 다시 시작
    try:
        assert not (s2.svc.store.root / "ghost" / ".tmp-abc").exists()
    finally:
        s2.close()


def test_same_token_for_read_and_write_refused(tmp_path):
    with pytest.raises(ValueError):
        Service(tmp_path / "r", Validators(SURVEY_DIR), parse_tokens("model-lab=" + WT), parse_tokens("synthetic-data=" + WT),
                log=lambda s: None)


def test_write_token_may_read_by_design(srv):
    """쓰기 토큰은 읽기를 포함한다는 설계 고정. 근거는 ADR 0012(게시자가 자기 게시를 확인, 같은 토큰을 읽기에도 두면 시작 거부)."""
    assert srv.call("GET", "/v1/datasets", token=WT)[0] == 200
