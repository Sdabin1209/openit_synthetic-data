"""계약 클라이언트(boundary_contracts.clients.HttpDatasetStore)로 이 영역의 실제 서버를 읽고 쓴다(D100 적합성).
클라이언트가 설치된 계약 버전에 없으면 건너뛴다(HttpDatasetStore가 생기기 전 계약)."""
from __future__ import annotations

import pytest
from boundary_contracts.errors import BoundaryError

clients = pytest.importorskip("boundary_contracts.clients")
if not hasattr(clients, "HttpDatasetStore"):
    pytest.skip("설치된 boundary-contracts에 HttpDatasetStore가 없다", allow_module_level=True)

from conftest import write_files
from test_service import RT, WT, Srv


@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path)
    yield s
    s.close()


def test_client_roundtrip(srv, captured, tmp_path):
    m, blobs = captured
    w, r = clients.HttpDatasetStore(srv.url, WT), clients.HttpDatasetStore(srv.url, RT)
    files = write_files(tmp_path / "src", blobs)
    assert w.publish(m, files) == m
    assert w.publish(m, files) == m                       # 멱등
    assert r.list_ids()[0] == [m["dataset_id"]]
    assert r.list_versions(m["dataset_id"]) == [m["version"]]
    assert r.get_manifest(m["dataset_id"], m["version"]) == m
    p = m["files"][0]["path"]
    assert r.open_file(m["dataset_id"], m["version"], p).read() == blobs[p]
    out = r.download(m["dataset_id"], m["version"], dest=tmp_path / "dl")
    assert {x.relative_to(out).as_posix(): x.read_bytes() for x in out.rglob("*") if x.is_file()} == blobs


def test_client_read_token_cannot_publish(srv, captured, tmp_path):
    m, blobs = captured
    r = clients.HttpDatasetStore(srv.url, RT)
    with pytest.raises(BoundaryError) as e:
        r.publish(m, write_files(tmp_path / "src", blobs))
    assert e.value.code == "PERMISSION_DENIED"


def test_client_missing_is_not_found(srv):
    r = clients.HttpDatasetStore(srv.url, RT)
    with pytest.raises(BoundaryError) as e:
        r.get_manifest("nope", "v1")
    assert e.value.code == "NOT_FOUND"
