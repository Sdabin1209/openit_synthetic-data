"""B3(표준성 점검 2026-10-29): 스키마 위반 오류에 입력 값이 실리면 안 된다.
기대값은 OWASP 로깅·오류 처리(오류에 민감값 비노출)와 ADR 0003('값은 사유에 담지 않는다'), docs/design.md 부록 A('보고서·매니페스트·결과·오류 레코드에 입력 값이 없다')에서 온다.
잘못된 값(MARK)을 넣었을 때 BoundaryError 메시지·details, 보고서(import_report.json), HTTP 오류 본문 어디에도 MARK가 나오면 실패한다."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from boundary_contracts import canonical
from boundary_contracts.errors import BoundaryError
from conftest import SURVEY_DIR
from synthetic_data.importer import run_import
from synthetic_data.store import FileDatasetStore, MemoryDatasetStore
from test_import import cfg_for, write_input
from test_service import Srv, WT, body_of

MARK = "ZZ-환자발화-비밀값-31337"


def dump(e: BoundaryError) -> str:
    return e.message + json.dumps(e.to_record(), ensure_ascii=False) + str(e)


def tamper_sample(manifest: dict, blobs: dict) -> tuple[dict, dict]:
    """첫 파일의 첫 줄 origin에 MARK를 넣고 해시들을 다시 맞춘다(해시 검사가 아니라 스키마 검사에서 걸리게)."""
    m, b = copy.deepcopy(manifest), dict(blobs)
    path = m["files"][0]["path"]
    lines = b[path].decode().split("\n")
    rec = json.loads(lines[0])
    rec["origin"] = MARK
    lines[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    b[path] = "\n".join(lines).encode()
    tmp = Path(__import__("tempfile").mkdtemp()) / "f"
    tmp.write_bytes(b[path])
    m["files"][0]["content_hash"] = canonical.file_hash(tmp)
    m.pop("content_hash")
    m["content_hash"] = canonical.content_hash(m)
    return m, b


def test_validators_messages_carry_no_value(validators):
    for fn, name, rec in ((validators.boundary, "ActionExtractionSample", {"origin": MARK}),
                          (validators.survey, "QuestionBank", {"questions": MARK})):
        with pytest.raises(BoundaryError) as e:
            fn(name, rec)
        assert e.value.code == "INVALID_RECORD" and MARK not in dump(e.value)


def test_store_publish_sample_violation_carries_no_value(captured, validators, tmp_path):
    from conftest import write_files
    m, b = tamper_sample(*captured)
    for st in (MemoryDatasetStore(validators), FileDatasetStore(tmp_path / "s", validators)):
        with pytest.raises(BoundaryError) as e:
            st.publish(m, write_files(tmp_path / "src", b))
        assert e.value.code == "INVALID_RECORD" and "ActionExtractionSample" in e.value.message
        assert MARK not in dump(e.value)


def test_store_publish_manifest_violation_carries_no_value(captured, validators):
    m = copy.deepcopy(captured[0])
    m["dataset_id"] = m["dataset_id"]
    m["generator_version"] = {"x": MARK}          # 문자열이어야 하는 필드
    with pytest.raises(BoundaryError) as e:
        MemoryDatasetStore(validators).publish(m, {})
    assert e.value.code == "INVALID_RECORD" and MARK not in dump(e.value)


def test_http_error_body_carries_no_value(tmp_path, captured):
    s = Srv(tmp_path)
    try:
        m, b = tamper_sample(*captured)
        code, body, _ = s.call("POST", "/v1/datasets", body_of(m, b), WT)
        assert code == 400
        assert MARK not in body.decode()
    finally:
        s.close()


def test_import_report_and_error_record_carry_no_value(tmp_path, validators):
    """게시 단계에서 저장소가 스키마 위반을 내는 경우(게시기의 사전 검증을 통과한 뒤)에도 보고서에 값이 없다."""
    write_input(tmp_path / "in")

    class Tampering(MemoryDatasetStore):
        def publish(self, manifest, files):
            first = sorted(files)[0]
            p = Path(files[first])
            rec = json.loads(p.read_text(encoding="utf-8").split("\n")[0])
            rec["origin"] = MARK
            lines = p.read_text(encoding="utf-8").split("\n")
            lines[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            p.write_text("\n".join(lines), encoding="utf-8")
            entry = next(f for f in manifest["files"] if f["path"] == first)
            entry["content_hash"] = canonical.file_hash(p)
            manifest.pop("content_hash")
            manifest["content_hash"] = canonical.content_hash(manifest)
            return super().publish(manifest, files)

    cfg = cfg_for(tmp_path)
    with pytest.raises(BoundaryError) as e:
        run_import(cfg, store=Tampering(validators), validators=validators)
    assert MARK not in dump(e.value)
    assert MARK not in (tmp_path / "work" / "import_report.json").read_text(encoding="utf-8")
