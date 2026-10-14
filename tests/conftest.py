from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import doubles
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


class CaptureStore(MemoryDatasetStore):
    """게시된 매니페스트와 파일 바이트를 시험이 다시 쓰려고 붙잡는다."""
    def __init__(self, v):
        super().__init__(v)
        self.captured = None

    def publish(self, manifest, files):
        self.captured = (copy.deepcopy(manifest), {k: Path(p).read_bytes() for k, p in files.items()})
        return super().publish(manifest, files)


@pytest.fixture(scope="session")
def captured(validators, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cap")
    st = CaptureStore(validators)
    _, res = run(make_cfg_raw(tmp), st, validators)
    assert res.status == "PUBLISHED"
    return st.captured


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
