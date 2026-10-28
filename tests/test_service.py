"""I2 HTTP 서버(synthetic_data.service) 시험: 읽기/쓰기, 멱등, 버전 불변, 권한·크기·경로 조작.
계약 클라이언트(boundary_contracts.clients.HttpDatasetStore)가 들어오면 test_service_contract.py가 그것으로 같은 서버를 읽는다."""
from __future__ import annotations

import io
import json
import tarfile
import threading
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
    def __init__(self, tmp_path, **kw):
        self.svc = Service(tmp_path / "root", Validators(SURVEY_DIR), parse_tokens(f"model-lab={RT}"),
                           parse_tokens(f"synthetic-data={WT}"), log=lambda s: None, **kw)
        self.httpd = make_server(self.svc)
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
    assert publish(srv, captured, token=None)[0] == 403
    assert srv.call("GET", "/v1/datasets", token="x" * 40)[0] == 403
    assert srv.call("GET", "/v1/datasets", token=None)[0] == 403
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
        assert st == 400 and json.loads(body)["code"] == "INVALID_RECORD"
        assert s.call("POST", "/v1/datasets", b"x" * 100, WT, {"Content-Length": "100"})[0] == 400
    finally:
        s.close()


def test_disk_full_is_503(tmp_path, captured):
    s = Srv(tmp_path, free_bytes=lambda: 0)
    try:
        assert publish(s, captured)[0] == 503
    finally:
        s.close()


def test_auth_failure_throttle_spares_valid_tokens(tmp_path):
    s = Srv(tmp_path, auth_fail_limit=3)
    try:
        for _ in range(3):
            assert s.call("GET", "/v1/datasets", token="y" * 40)[0] == 403
        assert s.call("GET", "/v1/datasets", token="y" * 40)[0] == 503
        assert s.call("GET", "/v1/datasets")[0] == 200
    finally:
        s.close()


def test_write_role_must_be_synthetic_data(tmp_path):
    with pytest.raises(ValueError):
        Service(tmp_path / "r", Validators(SURVEY_DIR), {}, parse_tokens("other=" + WT), log=lambda s: None)


def test_secrets_not_in_responses(srv, captured):
    for st, body, _ in (srv.call("GET", "/v1/datasets", token="y" * 40), publish(srv, captured, token=RT)):
        assert RT.encode() not in body and WT.encode() not in body
