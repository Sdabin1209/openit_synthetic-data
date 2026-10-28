"""A3(표준성 점검 2026-10-29): 파일 저장소 게시는 임시 파일 쓰기 -> 파일 fsync -> rename -> 디렉터리 fsync 순서여야 한다.
기대값: POSIX 원자적 교체 관행(fsync(2): 데이터가 저장 장치에 쓰이기 전에는 rename이 내구하지 않다). 헤드 결정표 D106.
정전 자체는 사용자 공간에서 재현할 수 없다(재현 못 함). 대신 fsync·rename의 호출 순서를 가로채 확인한다(장애 주입은 rename 직전 중단까지)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from boundary_contracts.errors import BoundaryError
from conftest import write_files
from synthetic_data.store import FileDatasetStore
from synthetic_data.store import file_store as fs_mod


@pytest.fixture
def trace(monkeypatch):
    events = []
    real_fsync, real_rename = os.fsync, os.rename

    def fsync(fd):
        events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        return real_fsync(fd)

    def rename(a, b):
        events.append(("rename", str(a), str(b)))
        return real_rename(a, b)

    monkeypatch.setattr(fs_mod.os, "fsync", fsync)
    monkeypatch.setattr(fs_mod.os, "rename", rename)
    return events


def test_publish_fsyncs_files_then_renames_then_fsyncs_directory(tmp_path, validators, captured, trace):
    m, blobs = captured
    root = tmp_path / "store"
    FileDatasetStore(root, validators).publish(m, write_files(tmp_path / "src", blobs))
    i = next(k for k, e in enumerate(trace) if e[0] == "rename")
    before = {e[1] for e in trace[:i] if e[0] == "fsync"}
    tmp_dir = Path(trace[i][1])
    for f in m["files"]:
        assert str(tmp_dir / "files" / f["path"]) in before, f["path"]
    assert str(tmp_dir / "manifest.json") in before and str(tmp_dir / "meta.json") in before
    assert str(tmp_dir) in before and str(tmp_dir / "files") in before
    after = {e[1] for e in trace[i + 1:] if e[0] == "fsync"}
    assert str(root / m["dataset_id"]) in after and str(root) in after


def test_crash_before_rename_leaves_no_visible_version(tmp_path, validators, captured, monkeypatch):
    class Crash(BaseException):
        pass

    def boom(a, b):
        raise Crash()

    monkeypatch.setattr(fs_mod.os, "rename", boom)
    m, blobs = captured
    st = FileDatasetStore(tmp_path / "store", validators)
    with pytest.raises(Crash):
        st.publish(m, write_files(tmp_path / "src", blobs))
    assert st.list_versions(m["dataset_id"]) == []
    with pytest.raises(BoundaryError) as e:
        st.get_manifest(m["dataset_id"], m["version"])
    assert e.value.code == "NOT_FOUND"
