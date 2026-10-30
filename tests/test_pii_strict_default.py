"""B14·C4(표준성 점검 2026-10-29): 개인정보 의심 패턴은 기본이 거부(strict)이고 시드(run) 경로에도 같은 검사가 있다.
기대값: ADR 0005 제목('기본값은 가장 엄격하다')과 헤드 결정표 D106. 경고만으로 두려면 설정에서 명시적으로 null(=경고만)이나 허용 건수를 적는다."""
from __future__ import annotations

import json

import pytest

import doubles
from boundary_contracts.errors import BoundaryError
from conftest import make_cfg_raw, run
from synthetic_data.config import ConfigError
from synthetic_data.wiring.plans import parse_config
from synthetic_data.wiring.import_job import run_import
from synthetic_data.components.dataset_store import MemoryDatasetStore
from test_import import cfg_for, row, set_utt, write_input

PHONE = "연락처는 010-1234-5678 입니다"


def with_pii(name, lines):
    if name == "lora_a_train.jsonl":
        lines[0] = set_utt(row("LORA_A", 1, "sc-t-p"), PHONE)
    return lines


def tol(**kw):
    return {"max_invalid_rows": 0, "max_invalid_rate": 0, **kw}


def test_import_rejects_pii_suspect_by_default(tmp_path, validators):
    write_input(tmp_path / "in", mutate=with_pii)
    res = run_import(cfg_for(tmp_path, tolerance=tol()), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert res.status == "REJECTED" and any("개인정보" in r for r in res.rejected_reasons)
    assert "1234-5678" not in json.dumps(res.rejected_reasons, ensure_ascii=False)


def test_import_null_is_explicit_warn_only(tmp_path, validators):
    write_input(tmp_path / "in", mutate=with_pii)
    res = run_import(cfg_for(tmp_path, tolerance=tol(max_pii_suspect_rows=None)), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert res.status == "PUBLISHED"


def seed_store(utterance):
    fs = doubles.FakeFailureStore()
    fs.add(doubles.failure_case("fc-a", "tr-a", doubles.a_expected(), expected_kind="LORA_A", reviewed_input=doubles.a_input(utterance)))
    return fs


def test_run_rejects_pii_suspect_seed_by_default(tmp_path, validators):
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, fstore=seed_store(PHONE))
    assert e.value.code == "INVALID_RECORD" and "1234-5678" not in e.value.message and "fc-a" in e.value.message


def test_run_clean_seed_publishes_and_null_is_warn_only(tmp_path, validators):
    _, ok = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, fstore=seed_store("한 다섯 시간 정도 자요"))
    assert ok.status == "PUBLISHED"
    raw = make_cfg_raw(tmp_path, seeds={"enabled": True, "question_set_id": "qs-main", "max_pii_suspect_rows": None})
    _, warn = run(raw, MemoryDatasetStore(validators.contract_version), validators, fstore=seed_store(PHONE))
    assert warn.status == "PUBLISHED"


def test_run_config_validates_pii_limit(tmp_path):
    for bad in (-1, "0", True):
        with pytest.raises(ConfigError):
            parse_config(make_cfg_raw(tmp_path, seeds={"enabled": True, "max_pii_suspect_rows": bad}), tmp_path)
