from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import doubles
import survey_schema
from boundary_contracts import PIPELINE_SCHEMA_VERSION
from synthetic_data.wiring.plans import parse_config
from synthetic_data.wiring.run_job import run_job
from synthetic_data.wiring.survey import Survey
from synthetic_data.components.dataset_store import FileDatasetStore, MemoryDatasetStore

ROOT = Path(__file__).resolve().parent.parent
# 매달림 감시(U422): 시험이 실제 시간으로 판정하지 않는다. 가짜에게서 신호를 기다리는 대기와 하위 프로세스·소켓 마감은 정상이면 즉시(또는 수 초) 끝나고 코드가 진짜로
# 멈췄을 때만 이 값에 닿는다. 정상 경로(ms~수십 초)의 수십~수천 배이고 판정(옳고 그름)에 쓰지 않는다. 시험마다 숫자를 따로 쓰지 않고 이 상수 하나를 쓴다.
HANG_GUARD_SECONDS = 300
# 왜: 문진 스키마는 형제 폴더가 아니라 설치된 패키지(requirements.lock의 태그)에서 읽는다. 새 머신에는 이웃 폴더가 없다.
SURVEY_DIR = survey_schema.contract_version_dir(1)
# 왜: 규칙 세대는 계약의 규칙 데이터가 정본이다. 시험에도 리터럴을 두지 않는다(계약 3.0.0)
from boundary_contracts.action_rules import load_rules  # noqa: E402
RULES_VERSION = str(load_rules()["rules_version"])


def make_cfg_raw(tmp_path: Path, **over) -> dict:
    raw = {
        "dataset_id": "ds-test", "seed": 7, "created_at": "2026-10-15T00:00:00Z", 
        "survey_schema_dir": str(SURVEY_DIR),
        "adapters": {"question_reader": {"factory": "doubles:make_question_reader"},
                     "failure_store": {"factory": "doubles:make_failure_store_factory"}},
        "question_sets": [{"id": "qs-main", "usage": "TRAIN_POOL"}, {"id": "qs-unseen", "usage": "HELD_OUT_EVAL"}],
        "seeds": {"enabled": True, "question_set_id": "qs-main"},
        "split": {"ratios": {"TRAIN": 0.6, "VALIDATION": 0.2, "EVAL": 0.2}},
        "output": {"work_dir": str(tmp_path / "work"), "store": {"kind": "memory"}},
    }
    raw.update(over)
    return raw


@pytest.fixture(scope="session")
def validators():
    return Survey(SURVEY_DIR)


@pytest.fixture
def cfg_raw(tmp_path):
    return make_cfg_raw(tmp_path)


def run(cfg_raw: dict, store, validators, *, reader=None, fstore=None, **kw):
    cfg = parse_config(cfg_raw, Path("."))
    reader = reader or doubles.make_question_reader()
    fstore = fstore or doubles.make_failure_store(doubles.make_bank("main"))
    return cfg, run_job(cfg, question_reader=reader, failure_store=fstore, store=store, survey=validators, **kw)


def v2_sample(role: str, n: int, split: str, ref: dict, *, scenario: str = None, origin: str = "SYNTHETIC") -> dict:
    """손으로 지은 v2 샘플(ActionExtractionSample/ResponseSample)."""
    a = role == "LORA_A"
    rec = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": f"{'as' if a else 'rs'}-{n:04d}",
           "scenario_id": scenario or f"sc-{n:04d}", "split": split, "origin": origin, "question_set": copy.deepcopy(ref),
           "input": doubles.a_input(f"발화 {n}") if a else doubles.b_input(f"발화 {n}"),
           "expected": doubles.a_expected() if a else doubles.b_expected(),
           "ext": {"synthetic-data": {"kind": "HAND"}}}
    return rec


def build_v2_dataset(tmp: Path):
    """v2 샘플을 package()로 묶은 (매니페스트, 파일 바이트). 생성기를 거치지 않는다."""
    from synthetic_data.components import run_package
    r = doubles.make_question_reader()
    ctxs = []
    for qid, use in (("qs-main", "TRAIN_POOL"), ("qs-unseen", "HELD_OUT_EVAL")):
        ref = r.latest(qid)
        ctxs.append({"ref": ref, "usage": use})
    main, unseen = ctxs[0]["ref"], ctxs[1]["ref"]
    samples, n = [], 0
    for role in ("LORA_A", "LORA_B"):
        for split, count, ref in (("TRAIN", 3, main), ("VALIDATION", 1, main), ("EVAL", 1, main), ("EVAL", 1, unseen)):
            for _ in range(count):
                n += 1
                samples.append(v2_sample(role, n, split, ref))
    cfg = parse_config(make_cfg_raw(tmp), Path("."))
    packaged = run_package.run({"samples": samples, "contexts": ctxs, "dataset_id": cfg.dataset_id, "version": cfg.version, "contract_version": 1,
                                "generator_version": "test-hand@0", "action_rules_version": cfg.action_rules_version,
                                "created_at": "2026-10-15T00:00:00Z", "pipeline_schema_version": PIPELINE_SCHEMA_VERSION})
    return packaged["manifest"], {f["path"]: f["text"].encode("utf-8") for f in packaged["files"]}


@pytest.fixture(scope="session")
def captured(tmp_path_factory):
    return build_v2_dataset(tmp_path_factory.mktemp("cap"))


def write_files(tmp: Path, blobs: dict) -> dict:
    out = {}
    for k, b in blobs.items():
        p = tmp / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
        out[k] = p
    return out


@pytest.fixture(params=["memory", "file"])
def store(request, validators, tmp_path):
    return MemoryDatasetStore(validators.contract_version) if request.param == "memory" else FileDatasetStore(tmp_path / "store", validators.contract_version)
