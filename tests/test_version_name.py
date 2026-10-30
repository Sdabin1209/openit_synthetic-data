"""A7(표준성 점검 2026-10-29): 생략한 version은 `v` + digest의 앞 32 16진수(128비트).
기대값: 48비트(12자리)는 생일 문제로 약 1,700만 개 버전에서 충돌 확률이 1/2에 이르지만 128비트는 무시할 수 있다(생일 한계 ≈ 2^(n/2)). 값은 결정표(D106)의 지시이며 측정한 것이 아니다."""
from __future__ import annotations

from conftest import make_cfg_raw, run
from synthetic_data.wiring.import_job import run_import
from synthetic_data.components.dataset_store import MemoryDatasetStore
from test_import import cfg_for, write_input


def test_import_version_is_128_bit_prefix(tmp_path, validators):
    write_input(tmp_path / "in")
    r = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert r.version == "v" + r.dataset_digest[len("sha256:"):][:32]


def test_run_version_is_128_bit_prefix(tmp_path, validators):
    _, r = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators)
    assert r.version == "v" + r.dataset_digest[len("sha256:"):][:32]
