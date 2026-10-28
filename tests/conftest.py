from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import doubles
from boundary_contracts import PIPELINE_SCHEMA_VERSION
from synthetic_data.config import parse_config
from synthetic_data.job import run_job
from synthetic_data.schemas import Validators
from synthetic_data.store import FileDatasetStore, MemoryDatasetStore

ROOT = Path(__file__).resolve().parent.parent
SURVEY_DIR = ROOT.parent / "survey-service" / "schema"


def make_cfg_raw(tmp_path: Path, **over) -> dict:
    raw = {
        "dataset_id": "ds-test", "seed": 7, "created_at": "2026-10-15T00:00:00Z", "turn_engine_version": "0.0.0-test",
        "survey_schema_dir": str(SURVEY_DIR),
        "adapters": {"question_reader": {"factory": "doubles:make_question_reader"},
                     "failure_store": {"factory": "doubles:make_failure_store_factory"}},
        "question_sets": [{"id": "qs-main", "usage": "TRAIN_POOL"}, {"id": "qs-unseen", "usage": "HELD_OUT_EVAL"}],
        "scenarios": {"variants": 2, "noise_variants": 1},
        "seeds": {"enabled": True, "question_set_id": "qs-main"},
        "split": {"ratios": {"TRAIN": 0.6, "VALIDATION": 0.2, "EVAL": 0.2}},
        "output": {"work_dir": str(tmp_path / "work"), "store": {"kind": "memory"}},
    }
    raw.update(over)
    return raw


@pytest.fixture(scope="session")
def validators():
    return Validators(survey_schema_dir=SURVEY_DIR)


@pytest.fixture
def cfg_raw(tmp_path):
    return make_cfg_raw(tmp_path)


def run(cfg_raw: dict, store, validators, *, reader=None, fstore=None, **kw):
    cfg = parse_config(cfg_raw, Path("."))
    reader = reader or doubles.make_question_reader()
    fstore = fstore or doubles.make_failure_store(doubles.make_bank("main"))
    return cfg, run_job(cfg, question_reader=reader, failure_store=fstore, store=store, validators=validators, **kw)


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
    from synthetic_data.package import package
    from synthetic_data.context import QuestionSetContext
    r = doubles.make_question_reader()
    ctxs = []
    for qid, use in (("qs-main", "TRAIN_POOL"), ("qs-unseen", "HELD_OUT_EVAL")):
        ref = r.latest(qid)
        ctxs.append(QuestionSetContext(ref, r.get_question_bank(ref), use))
    main, unseen = ctxs[0].ref, ctxs[1].ref
    samples, n = [], 0
    for role in ("LORA_A", "LORA_B"):
        for split, count, ref in (("TRAIN", 3, main), ("VALIDATION", 1, main), ("EVAL", 1, main), ("EVAL", 1, unseen)):
            for _ in range(count):
                n += 1
                samples.append(v2_sample(role, n, split, ref))
    cfg = parse_config(make_cfg_raw(tmp), Path("."))
    manifest, files, _ = package(samples, ctxs, cfg, staging=tmp / "stage", contract=1, generator_version="test-hand@0",
                                 turn_engine_version="0.0.0-test", created_at="2026-10-15T00:00:00Z")
    return manifest, {k: Path(p).read_bytes() for k, p in files.items()}


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
    return MemoryDatasetStore(validators) if request.param == "memory" else FileDatasetStore(tmp_path / "store", validators)
