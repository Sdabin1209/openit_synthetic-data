from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from boundary_contracts.errors import BoundaryError

import doubles
from conftest import SURVEY_DIR, make_cfg_raw, run
from synthetic_data.__main__ import main
from synthetic_data.config import ConfigError, parse_config
from synthetic_data.store import FileDatasetStore, MemoryDatasetStore


def read_all(store, m):
    out = {}
    for e in m["files"]:
        out[e["path"]] = [json.loads(x) for x in store.open_file(m["dataset_id"], m["version"], e["path"]).read().decode().splitlines()]
    return out


@pytest.fixture
def published(tmp_path, validators):
    st = MemoryDatasetStore(validators)
    cfg, res = run(make_cfg_raw(tmp_path), st, validators)
    return st, res, st.get_manifest(res.dataset_id, res.version)


def test_end_to_end_manifest(published):
    st, res, m = published
    assert res.status == "PUBLISHED" and res.content_hash == m["content_hash"]
    assert m["runtime_contract_version"] == 1 and m["scenario_disjoint_across_splits"] is True
    assert m["turn_engine_version"] == "0.0.0-test" and m["seed_case_ids"] == ["fc-g", "fc-p"]
    assert {r["id"] for r in m["question_sets"]} == {"qs-main", "qs-unseen"}
    assert m["generator_version"].startswith("rule-utterance@")
    assert sum(e["sample_count"] for e in m["files"]) > 100
    roles = {e["role"] for e in m["files"]}
    assert roles == {"PARSER", "GENERATOR"}


def test_scenarios_disjoint_across_splits(published):
    st, res, m = published
    seen = {}
    for path, recs in read_all(st, m).items():
        for r in recs:
            seen.setdefault(r["split"], set()).add(r["scenario_id"])
    assert set(seen) == {"TRAIN", "VALIDATION", "EVAL"}
    for a, b in (("EVAL", "TRAIN"), ("EVAL", "VALIDATION"), ("TRAIN", "VALIDATION")):
        assert not seen[a] & seen[b]


def test_same_scenario_variants_stay_together(published):
    st, res, m = published
    where = {}
    for recs in read_all(st, m).values():
        for r in recs:
            where.setdefault(r["scenario_id"], set()).add(r["split"])
    assert all(len(v) == 1 for v in where.values())
    noisy = [r for recs in read_all(st, m).values() for r in recs if r.get("noise_types")]
    assert noisy, "노이즈 변형이 하나도 없다"


def test_unseen_question_set_eval(published):
    st, res, m = published
    unseen = [e for e in m["files"] if e["path"].endswith("eval_unseen.jsonl")]
    assert unseen and all(e["split"] == "EVAL" for e in unseen)
    unseen_ids = {r["id"] for e in unseen for r in e["question_sets"]}
    assert unseen_ids == {"qs-unseen"}
    train_ids = {r["id"] for e in m["files"] if e["split"] in ("TRAIN", "VALIDATION") for r in e["question_sets"]}
    assert "qs-unseen" not in train_ids
    data = read_all(st, m)
    for recs in data.values():
        for r in recs:
            if r["question_set"]["id"] == "qs-unseen":
                assert r["split"] == "EVAL"
    assert m["ext"]["synthetic-data"]["unseen_eval_files"] == sorted(e["path"] for e in unseen)


def test_no_quality_drops_besides_duplicates(tmp_path, validators):
    cfg_raw = make_cfg_raw(tmp_path)
    run(cfg_raw, MemoryDatasetStore(validators), validators)
    rep = json.loads((Path(cfg_raw["output"]["work_dir"]) / "report.json").read_text())
    assert set(rep["dropped"]) <= {"duplicate_input", "synthetic_dropped_for_seed_input"}, rep["dropped"]
    assert (Path(cfg_raw["output"]["work_dir"]) / "review_sample.jsonl").stat().st_size > 0


def test_reproducible_same_content_hash(tmp_path, validators):
    r1 = run(make_cfg_raw(tmp_path / "a"), MemoryDatasetStore(validators), validators)[1]
    r2 = run(make_cfg_raw(tmp_path / "b"), FileDatasetStore(tmp_path / "s", validators), validators)[1]
    assert r1.content_hash == r2.content_hash and r1.dataset_digest == r2.dataset_digest and r1.version == r2.version


def test_reproducible_file_bytes(tmp_path, validators):
    s1, s2 = MemoryDatasetStore(validators), MemoryDatasetStore(validators)
    _, a = run(make_cfg_raw(tmp_path / "a"), s1, validators)
    _, b = run(make_cfg_raw(tmp_path / "b"), s2, validators)
    m = s1.get_manifest(a.dataset_id, a.version)
    for e in m["files"]:
        assert s1.open_file(a.dataset_id, a.version, e["path"]).read() == s2.open_file(b.dataset_id, b.version, e["path"]).read()


def test_different_seed_changes_digest(tmp_path, validators):
    a = run(make_cfg_raw(tmp_path / "a"), MemoryDatasetStore(validators), validators)[1]
    b = run(make_cfg_raw(tmp_path / "b", seed=8), MemoryDatasetStore(validators), validators)[1]
    assert a.dataset_digest != b.dataset_digest


def test_rerun_is_already_published_even_with_new_created_at(tmp_path, validators):
    st = MemoryDatasetStore(validators)
    a = run(make_cfg_raw(tmp_path / "a"), st, validators)[1]
    raw = make_cfg_raw(tmp_path / "b", created_at="2027-01-01T00:00:00Z")
    b = run(raw, st, validators)[1]
    assert b.status == "ALREADY_PUBLISHED" and b.content_hash == a.content_hash
    assert st.list_versions("ds-test") == [a.version]


def test_explicit_version_conflict_on_different_content(tmp_path, validators):
    st = MemoryDatasetStore(validators)
    run(make_cfg_raw(tmp_path / "a", version="v1"), st, validators)
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path / "b", version="v1", seed=99), st, validators)
    assert e.value.code == "CONFLICT"
    again = run(make_cfg_raw(tmp_path / "c", version="v1"), st, validators)[1]
    assert again.status == "PUBLISHED"       # 같은 내용이면 멱등 게시


def test_seed_samples(published):
    st, res, m = published
    seeds = [r for recs in read_all(st, m).values() for r in recs if r["origin"] == "FAILURE_CASE_SEED"]
    assert {r["seed_case_id"] for r in seeds} == {"fc-p", "fc-g"}
    assert all(r["question_set"]["id"] == "qs-main" for r in seeds)
    parser_seed = [r for r in seeds if r["sample_id"].startswith("ps-")]
    assert any(r.get("noise_types") for r in parser_seed)


def test_not_deidentified_case_rejected(tmp_path, validators):
    fs = doubles.make_failure_store(doubles.make_bank("main"))
    fs.add(doubles.failure_case("fc-raw", "tr-p", {"items": []}, deidentified=False))
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators), validators, fstore=fs)
    assert e.value.code == "INVALID_RECORD"


def test_seed_without_matching_question_is_skipped(tmp_path, validators):
    fs = doubles.make_failure_store(doubles.make_bank("main"))
    other = doubles.make_bank("unseen")["questions"][0]
    from synthetic_data import bank as bk
    pin = {"utterance": "두 잔이요", "last_directive": None, "awaiting_questions": [other],
           "question_names": bk.question_names(doubles.make_bank("unseen")), "answered_slots": [], "guide_list": []}
    pout = {"items": []}
    fs.add(doubles.failure_case("fc-x", "tr-x2", pout), doubles.make_trace("fc-x", parser_input=pin, parser_output=pout))
    cfg, res = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators), validators, fstore=fs)
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    assert any(s["case_id"] == "fc-x" for s in rep["skipped_seeds"])


def test_reviewed_only(tmp_path, validators):
    reader = doubles.make_question_reader()
    reader.add("qs-main", "2", doubles.make_bank("main", wording=" (개정)"), approved=False)
    st0 = MemoryDatasetStore(validators)
    _, res0 = run(make_cfg_raw(tmp_path / "a"), st0, validators, reader=reader)     # 버전 미지정: 검수된 최신(1)
    assert {q["version"] for q in st0.get_manifest(res0.dataset_id, res0.version)["question_sets"]} == {"1"}
    raw = make_cfg_raw(tmp_path / "b", question_sets=[{"id": "qs-main", "version": "2"}, {"id": "qs-unseen", "usage": "HELD_OUT_EVAL"}])
    with pytest.raises(BoundaryError) as e:
        run(raw, MemoryDatasetStore(validators), validators, reader=reader)
    assert e.value.code == "FAILED_PRECONDITION"
    raw["reviewed_only"] = False
    st = MemoryDatasetStore(validators)
    _, r = run(raw, st, validators, reader=reader)
    assert {q["version"] for q in st.get_manifest(r.dataset_id, r.version)["question_sets"]} == {"2", "1"}


def test_bank_hash_mismatch_is_integrity_error(tmp_path, validators):
    class Bad(doubles.FakeQuestionReader):
        def get_question_bank(self, ref):
            b = super().get_question_bank(ref)
            b["questions"][0]["name"] += "x"
            return b
    reader = Bad()
    reader.add("qs-main", "1", doubles.make_bank("main"))
    reader.add("qs-unseen", "1", doubles.make_bank("unseen"))
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators), validators, reader=reader)
    assert e.value.code == "INTEGRITY_ERROR"


def test_boundary_error_from_neighbor_propagates(tmp_path, validators):
    class Down(doubles.FakeQuestionReader):
        def latest(self, *a, **k):
            raise BoundaryError("UNAVAILABLE", "점검 중")
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators), validators, reader=Down())
    assert e.value.retryable


def test_regeneration_affected_only(tmp_path, validators):
    reader = doubles.make_question_reader()
    change = {"pipeline_schema_version": "1.0", "classification_id": "cc-1", "to": {}, "change_kinds": ["TEXT"],
              "affected_slots": ["Q3.hours"], "follow_ups": ["REGENERATE_SAMPLES"], "created_at": "2026-10-15T00:00:00Z"}
    reader.add("qs-main", "2", doubles.make_bank("main", wording=" (개정)"), change=change)
    raw = make_cfg_raw(tmp_path, regeneration={"mode": "affected_only"}, seeds={"enabled": False},
                       question_sets=[{"id": "qs-main", "version": "2"}])
    st = MemoryDatasetStore(validators)
    _, res = run(raw, st, validators, reader=reader)
    m = st.get_manifest(res.dataset_id, res.version)
    qids = set()
    for recs in read_all(st, m).values():
        for r in recs:
            if r["sample_id"].startswith("ps-"):
                qids |= {q["question_id"] for q in r["input"]["awaiting_questions"]}
    assert qids == {"Q3"}
    # REGENERATE_SAMPLES가 없으면 할 일이 없다
    reader2 = doubles.make_question_reader()
    reader2.add("qs-main", "2", doubles.make_bank("main", wording=" (개정)"), change=dict(change, follow_ups=["REEVALUATE_MODEL"]))
    _, res2 = run(make_cfg_raw(tmp_path / "n", regeneration={"mode": "affected_only"}, seeds={"enabled": False},
                               question_sets=[{"id": "qs-main", "version": "2"}]), MemoryDatasetStore(validators), validators, reader=reader2)
    assert res2.status == "NOTHING_TO_DO"


def test_generators_are_swappable(tmp_path, validators):
    raw = make_cfg_raw(tmp_path, seeds={"enabled": False}, scenarios={"variants": 1, "noise_variants": 0},
                       generators={"utterance": "custom_gens:FixedUtteranceGenerator", "response": "custom_gens:FixedResponseGenerator"})
    st = MemoryDatasetStore(validators)
    _, res = run(raw, st, validators)
    m = st.get_manifest(res.dataset_id, res.version)
    assert "fixed-utt@9.9" in m["generator_version"] and "fixed-resp@9.9" in m["generator_version"]
    data = read_all(st, m)
    parser = [r for recs in data.values() for r in recs if r["sample_id"].startswith("ps-")]
    assert parser and all(r["input"]["utterance"] == "몰라요" for r in parser)
    gen = [r for recs in data.values() for r in recs if r["sample_id"].startswith("gs-")]
    assert gen and all(r["input"]["directive"]["action"] == "ASK_NEXT" for r in gen)


def test_config_requires_split_ratios(tmp_path):
    raw = make_cfg_raw(tmp_path)
    del raw["split"]
    with pytest.raises(ConfigError):
        parse_config(raw, Path("."))
    raw = make_cfg_raw(tmp_path, split={"ratios": {"TRAIN": 1, "VALIDATION": 0}})
    with pytest.raises(ConfigError):
        parse_config(raw, Path("."))


def test_cli(tmp_path, capsys):
    raw = make_cfg_raw(tmp_path, output={"work_dir": str(tmp_path / "w"), "store": {"kind": "file", "root": str(tmp_path / "st")}})
    cfgp = tmp_path / "job.json"
    cfgp.write_text(json.dumps(raw))
    assert main(["run", "--config", str(cfgp)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "PUBLISHED"
    assert main(["run", "--config", str(cfgp), "--created-at", "2030-01-01T00:00:00Z"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ALREADY_PUBLISHED"
    assert FileDatasetStore(tmp_path / "st", __import__("synthetic_data.schemas", fromlist=["Validators"]).Validators(survey_schema_dir=SURVEY_DIR)).list_versions("ds-test") == [out["version"]]
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert main(["run", "--config", str(bad)]) == 2
    raw2 = dict(raw, survey_schema_dir=str(tmp_path / "nowhere"))
    cfg2 = tmp_path / "job2.json"
    cfg2.write_text(json.dumps(raw2))
    assert main(["run", "--config", str(cfg2)]) == 3


def test_hashes_only_via_canonical():
    src = Path(__file__).resolve().parent.parent / "synthetic_data"
    for p in src.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert "hashlib" not in text and "sha256(" not in text, p


def _seed_store_v11(ref):
    fs = doubles.make_failure_store(doubles.make_bank("main"))
    base_p = fs.get_case("fc-p")
    tr = fs.get_trace("tr-p")
    fs.add(doubles.failure_case("fc-new", "tr-new", base_p["expected"], question_set=ref, expected_kind="PARSER"),
           dict(tr, session_id="sess-new"))
    return fs


def test_seed_uses_failurecase_question_set_without_config_fallback(tmp_path, validators):
    reader = doubles.make_question_reader()
    ref = reader.latest("qs-main")
    fs = _seed_store_v11(ref)
    raw = make_cfg_raw(tmp_path, seeds={"enabled": True})          # question_set_id 없음
    st = MemoryDatasetStore(validators)
    cfg, res = run(raw, st, validators, reader=reader, fstore=fs)
    m = st.get_manifest(res.dataset_id, res.version)
    assert m["seed_case_ids"] == ["fc-new"]                         # 참조 없는 1.0 사례(fc-p, fc-g)는 건너뜀
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    assert {s["case_id"] for s in rep["skipped_seeds"]} == {"fc-p", "fc-g"}


def test_seed_question_set_not_in_run_is_skipped(tmp_path, validators):
    reader = doubles.make_question_reader()
    other = dict(reader.latest("qs-main"), content_hash="sha256:" + "3" * 64)
    fs = _seed_store_v11(other)
    cfg, res = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators), validators, reader=reader, fstore=fs)
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    assert any(s["case_id"] == "fc-new" and "학습 풀" in s["reason"] for s in rep["skipped_seeds"])


def test_affected_slots_split_at_last_dot():
    from synthetic_data.job import _affected_questions
    assert _affected_questions({"affected_slots": ["Q3b.sub.frequency", "Q1.status"]}) == {"Q3b.sub", "Q1"}
    assert _affected_questions({"affected_slots": []}) is None


def test_labels_never_copied_from_contract_examples(published):
    """boundary-contracts의 examples/ 정답 예시는 읽지도 복사하지도 않는다. 합성 정답은 라벨 기준 구현에서만 나온다."""
    from synthetic_data.job import __file__ as _  # noqa
    src = Path(__file__).resolve().parent.parent / "synthetic_data"
    for p in src.rglob("*.py"):
        assert "examples" not in p.read_text(encoding="utf-8"), p
    st, res, m = published
    for recs in read_all(st, m).values():
        for r in recs:
            if r["origin"] == "SYNTHETIC" and r["sample_id"].startswith("gs-"):
                assert r["expected"]["is_fallback"] is False
