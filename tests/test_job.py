from __future__ import annotations

import json
from pathlib import Path

import pytest
from boundary_contracts.errors import BoundaryError

import doubles
from boundary_contracts import PIPELINE_SCHEMA_VERSION
from conftest import SURVEY_DIR, make_cfg_raw, run
from synthetic_data.__main__ import main
from synthetic_data.config import ConfigError
from synthetic_data.wiring.plans import parse_config
from synthetic_data.components.dataset_store import FileDatasetStore, MemoryDatasetStore


def read_all(store, m):
    out = {}
    for e in m["files"]:
        out[e["path"]] = [json.loads(x) for x in store.open_file(m["dataset_id"], m["version"], e["path"]).read().decode().splitlines()]
    return out


@pytest.fixture
def published(tmp_path, validators):
    st = MemoryDatasetStore(validators.contract_version)
    cfg, res = run(make_cfg_raw(tmp_path), st, validators)
    return st, res, st.get_manifest(res.dataset_id, res.version)


def test_reproducible_same_content_hash(tmp_path, validators):
    r1 = run(make_cfg_raw(tmp_path / "a"), MemoryDatasetStore(validators.contract_version), validators)[1]
    r2 = run(make_cfg_raw(tmp_path / "b"), FileDatasetStore(tmp_path / "s", validators.contract_version), validators)[1]
    assert r1.content_hash == r2.content_hash and r1.dataset_digest == r2.dataset_digest and r1.version == r2.version


def test_reproducible_file_bytes(tmp_path, validators):
    s1, s2 = MemoryDatasetStore(validators.contract_version), MemoryDatasetStore(validators.contract_version)
    _, a = run(make_cfg_raw(tmp_path / "a"), s1, validators)
    _, b = run(make_cfg_raw(tmp_path / "b"), s2, validators)
    m = s1.get_manifest(a.dataset_id, a.version)
    for e in m["files"]:
        assert s1.open_file(a.dataset_id, a.version, e["path"]).read() == s2.open_file(b.dataset_id, b.version, e["path"]).read()


def test_different_seed_changes_digest(tmp_path, validators):
    a = run(make_cfg_raw(tmp_path / "a"), MemoryDatasetStore(validators.contract_version), validators)[1]
    b = run(make_cfg_raw(tmp_path / "b", seed=8), MemoryDatasetStore(validators.contract_version), validators)[1]
    assert a.dataset_digest != b.dataset_digest


def test_rerun_is_already_published_even_with_new_created_at(tmp_path, validators):
    st = MemoryDatasetStore(validators.contract_version)
    a = run(make_cfg_raw(tmp_path / "a"), st, validators)[1]
    raw = make_cfg_raw(tmp_path / "b", created_at="2027-01-01T00:00:00Z")
    b = run(raw, st, validators)[1]
    assert b.status == "ALREADY_PUBLISHED" and b.content_hash == a.content_hash
    assert st.list_versions("ds-test") == [a.version]


def test_seed_samples(published):
    st, res, m = published
    seeds = [r for recs in read_all(st, m).values() for r in recs if r["origin"] == "FAILURE_CASE_SEED"]
    assert {r["seed_case_id"] for r in seeds} == {"fc-a", "fc-b"}
    assert all(r["question_set"]["id"] == "qs-main" for r in seeds)
    a = next(r for r in seeds if r["seed_case_id"] == "fc-a")
    b = next(r for r in seeds if r["seed_case_id"] == "fc-b")
    assert a["sample_id"].startswith("as-") and isinstance(a["expected"], dict)
    assert b["sample_id"].startswith("rs-") and isinstance(b["expected"], str)
    assert {e["role"] for e in m["files"]} == {"LORA_A", "LORA_B"}      # 게시 때 저장소가 v2 샘플 스키마로 다시 검증했다


def test_not_deidentified_case_rejected(tmp_path, validators):
    fs = doubles.make_failure_store(doubles.make_bank("main"))
    fs.add(doubles.failure_case("fc-raw", "tr-p", {"items": []}, deidentified=False))
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, fstore=fs)
    assert e.value.code == "INVALID_RECORD"


def test_seed_without_matching_question_is_skipped(tmp_path, validators):
    """시드의 문항(Q11, 'unseen' 은행의 문항)이 지정한 문항 세트(qs-main)에 없으면 건너뛴다."""
    reader = doubles.make_question_reader()
    ref = reader.latest("qs-main")
    fs = doubles.make_failure_store(doubles.make_bank("main"))
    inp = dict(doubles.a_input(), question_id="Q11")
    fs.add(doubles.failure_case("fc-x", "tr-x2", doubles.a_expected(), question_set=ref, expected_kind="LORA_A", reviewed_input=inp))
    cfg, res = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, reader=reader, fstore=fs)
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    assert any(s["case_id"] == "fc-x" and "문항 세트에 없음" in s["reason"] for s in rep["skipped_seeds"])


def test_reviewed_only(tmp_path, validators):
    reader = doubles.make_question_reader()
    reader.add("qs-main", "2", doubles.make_bank("main", wording=" (개정)"), approved=False)
    st0 = MemoryDatasetStore(validators.contract_version)
    _, res0 = run(make_cfg_raw(tmp_path / "a"), st0, validators, reader=reader)     # 버전 미지정: 검수된 최신(1)
    assert {q["version"] for q in st0.get_manifest(res0.dataset_id, res0.version)["question_sets"]} == {"1"}
    raw = make_cfg_raw(tmp_path / "b", question_sets=[{"id": "qs-main", "version": "2"}, {"id": "qs-unseen", "usage": "HELD_OUT_EVAL"}])
    with pytest.raises(BoundaryError) as e:
        run(raw, MemoryDatasetStore(validators.contract_version), validators, reader=reader)
    assert e.value.code == "FAILED_PRECONDITION"
    raw["reviewed_only"] = False
    st = MemoryDatasetStore(validators.contract_version)
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
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, reader=reader)
    assert e.value.code == "INTEGRITY_ERROR"


def test_boundary_error_from_neighbor_propagates(tmp_path, validators):
    class Down(doubles.FakeQuestionReader):
        def latest(self, *a, **k):
            raise BoundaryError("UNAVAILABLE", "점검 중")
    with pytest.raises(BoundaryError) as e:
        run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, reader=Down())
    assert e.value.retryable


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
    assert FileDatasetStore(tmp_path / "st", __import__("synthetic_data.wiring.survey", fromlist=["Survey"]).Survey(SURVEY_DIR).contract_version).list_versions("ds-test") == [out["version"]]
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


def _seed_store_v2(ref):
    fs = doubles.make_failure_store(doubles.make_bank("main"))
    base = fs.get_case("fc-a")
    fs.add(doubles.failure_case("fc-new", "tr-new", base["expected"], question_set=ref, expected_kind="LORA_A",
                                reviewed_input=base["reviewed_input"]))
    return fs


def test_seed_uses_failurecase_question_set_without_config_fallback(tmp_path, validators):
    reader = doubles.make_question_reader()
    ref = reader.latest("qs-main")
    fs = _seed_store_v2(ref)
    raw = make_cfg_raw(tmp_path, seeds={"enabled": True})          # question_set_id 없음
    st = MemoryDatasetStore(validators.contract_version)
    cfg, res = run(raw, st, validators, reader=reader, fstore=fs)
    m = st.get_manifest(res.dataset_id, res.version)
    assert m["seed_case_ids"] == ["fc-new"]                         # 문항 세트 참조 없는 사례(fc-a, fc-b)는 건너뜀
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    assert {s["case_id"] for s in rep["skipped_seeds"]} == {"fc-a", "fc-b"}


def test_seed_question_set_not_in_run_is_skipped(tmp_path, validators):
    reader = doubles.make_question_reader()
    other = dict(reader.latest("qs-main"), content_hash="sha256:" + "3" * 64)
    fs = _seed_store_v2(other)
    cfg, res = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, reader=reader, fstore=fs)
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    assert any(s["case_id"] == "fc-new" and "학습 풀" in s["reason"] for s in rep["skipped_seeds"])


def test_labels_never_copied_from_contract_examples():
    """boundary-contracts의 examples/ 정답 예시는 읽지도 복사하지도 않는다. 합성 정답은 라벨 기준 구현에서만 나온다."""
    src = Path(__file__).resolve().parent.parent / "synthetic_data"
    for p in src.rglob("*.py"):
        assert "examples" not in p.read_text(encoding="utf-8"), p


def test_seed_needs_reviewed_input_and_v2_schema(tmp_path, validators):
    reader = doubles.make_question_reader()
    ref = reader.latest("qs-main")
    fs = _seed_store_v2(ref)
    base = fs.get_case("fc-a")
    fs.add(doubles.failure_case("fc-noinput", "tr-n", base["expected"], question_set=ref, expected_kind="LORA_A"))
    bad_in = dict(base["reviewed_input"], user_utterance="")
    fs.add(doubles.failure_case("fc-badinput", "tr-b2", base["expected"], question_set=ref, expected_kind="LORA_A", reviewed_input=bad_in))
    v1_exp = {"items": []}
    fs.add(doubles.failure_case("fc-v1exp", "tr-v1", v1_exp, question_set=ref, expected_kind="LORA_A", reviewed_input=base["reviewed_input"]))
    fs.add(doubles.failure_case("fc-oldkind", "tr-old", base["expected"], question_set=ref, expected_kind="PARSER",
                                reviewed_input=base["reviewed_input"]))
    cfg, res = run(make_cfg_raw(tmp_path), MemoryDatasetStore(validators.contract_version), validators, reader=reader, fstore=fs)
    rep = json.loads((cfg.work_dir / "report.json").read_text())
    skipped = {s["case_id"]: s["reason"] for s in rep["skipped_seeds"]}
    assert "reviewed_input 없음" in skipped["fc-noinput"]
    assert "스키마를 위반" in skipped["fc-badinput"] and "스키마를 위반" in skipped["fc-v1exp"]
    assert "fc-oldkind" not in skipped             # v1 종류 이름은 모르는 값이라 expected 형태(객체)로 판별해 LORA_A로 쓴다
    assert any("PARSER" in n for n in rep["notes"])


def test_regeneration_affected_only_excludes_sets_without_follow_up(tmp_path, validators):
    """regeneration.mode=affected_only: REGENERATE_SAMPLES 후속 작업이 없는 문항 세트는 제외하고, 남은 것이 없으면 할 일이 없다."""
    change = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "classification_id": "cc-1", "to": {}, "change_kinds": ["TEXT"],
              "affected_slots": ["Q3.hours"], "follow_ups": ["REEVALUATE_MODEL"], "created_at": "2026-10-15T00:00:00Z"}
    reader = doubles.make_question_reader()
    reader.add("qs-main", "2", doubles.make_bank("main", wording=" (개정)"), change=change)
    raw = make_cfg_raw(tmp_path, regeneration={"mode": "affected_only"}, question_sets=[{"id": "qs-main", "version": "2"}])
    _, res = run(raw, MemoryDatasetStore(validators.contract_version), validators, reader=reader)
    assert res.status == "NOTHING_TO_DO"


def _regen_run(tmp_path, validators, affected_slots):
    change = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "classification_id": "cc-2", "to": {}, "change_kinds": ["SLOT"],
              "affected_slots": affected_slots, "follow_ups": ["REGENERATE_SAMPLES"], "created_at": "2026-10-15T00:00:00Z"}
    reader = doubles.make_question_reader()
    reader.add("qs-main", "2", doubles.make_bank("main", wording=" (개정)"), change=change)
    raw = make_cfg_raw(tmp_path, regeneration={"mode": "affected_only"}, question_sets=[{"id": "qs-main", "version": "2"}])
    cfg, res = run(raw, MemoryDatasetStore(validators.contract_version), validators, reader=reader)
    return res, json.loads((cfg.work_dir / "report.json").read_text())


def test_regeneration_affected_only_rebuilds_only_the_affected_questions(tmp_path, validators):
    """브리프 3-1: REGENERATE_SAMPLES이면 해당 문항의 샘플만 다시 만든다. 시드 fc-a는 Q3, fc-b는 다음 문항 Q4를 쓴다."""
    res, rep = _regen_run(tmp_path, validators, ["Q3.hours"])
    assert res.status == "PUBLISHED" and res.counts["origin.FAILURE_CASE_SEED"] == 1
    assert any(k.startswith("lora_a.") for k in res.counts) and not any(k.startswith("lora_b.") for k in res.counts)
    skipped = {x["case_id"]: x["reason"] for x in rep["skipped_seeds"]}
    assert skipped == {"fc-b": "시드의 문항이 변경 분류의 영향 문항이 아님"}


def test_regeneration_affected_only_with_no_listed_slots_rebuilds_everything(tmp_path, validators):
    """영향 칸 목록이 비면 문항을 좁히지 않는다(전부 다시 만든다)."""
    res, rep = _regen_run(tmp_path, validators, [])
    assert res.counts["origin.FAILURE_CASE_SEED"] == 2 and rep["skipped_seeds"] == []


def test_regeneration_full_mode_ignores_affected_slots(tmp_path, validators):
    """full 모드는 변경 분류를 읽지 않으므로 문항 제한이 없다."""
    reader = doubles.make_question_reader()
    raw = make_cfg_raw(tmp_path, question_sets=[{"id": "qs-main"}])
    _, res = run(raw, MemoryDatasetStore(validators.contract_version), validators, reader=reader)
    assert res.counts["origin.FAILURE_CASE_SEED"] == 2


def test_v1_generation_config_keys_are_rejected(tmp_path, validators):
    """제거된 v1 생성 키(scenarios·generators·style_guide_version)는 알 수 없는 키로 거부한다(ADR 0014)."""
    for key, val in (("scenarios", {"variants": 3}), ("generators", {"utterance": "rule"}), ("style_guide_version", "1")):
        with pytest.raises(ConfigError, match=key):
            parse_config(make_cfg_raw(tmp_path, **{key: val}), tmp_path)