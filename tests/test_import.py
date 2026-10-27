"""게시기(import) 시험. 입력은 이 리포가 직접 만든 가짜 행이다(실제 학습 데이터가 아니다)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import doubles
from conftest import SURVEY_DIR, ROOT
from synthetic_data.importer import INPUT_FILES, InputError, parse_import_config, run_import
from synthetic_data.config import ConfigError
from synthetic_data.store import MemoryDatasetStore

QS = [{"id": "qs-external", "version": "1", "content_hash": "sha256:" + "0" * 64}]


def row(role, n, scenario, **over):
    if role == "LORA_A":
        user, asst = json.dumps(doubles.a_input(f"발화 {n}"), ensure_ascii=False), json.dumps(doubles.a_expected(), ensure_ascii=False)
    else:
        user, asst = json.dumps(doubles.b_input(f"발화 {n}"), ensure_ascii=False), doubles.b_expected()
    r = {"human_review": "auto_only", "scenario_id": scenario, "split": "x",
         "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": user}, {"role": "assistant", "content": asst}]}
    r.update(over)
    return r


def write_input(d: Path, per_file=3, mutate=None):
    d.mkdir(parents=True, exist_ok=True)
    k = 0
    for name, role, split in INPUT_FILES:
        lines = []
        for i in range(per_file):
            k += 1
            lines.append(row(role, k, f"sc-{split}-{i}"))
        if mutate:
            lines = mutate(name, lines)
        (d / name).write_bytes(("\n".join(l if isinstance(l, str) else json.dumps(l, ensure_ascii=False) for l in lines) + "\n").encode())


def cfg_for(tmp, **over):
    raw = {"dataset_id": "ds-imp", "input_dir": str(tmp / "in"), "survey_schema_dir": str(SURVEY_DIR), "question_sets": QS,
           "source_label": "fake-test", "turn_engine_version": "0.0.0-test", "created_at": "2026-10-27T00:00:00Z",
           "tolerance": {"max_invalid_rows": 0, "max_invalid_rate": 0.0},
           "output": {"work_dir": str(tmp / "work"), "store": {"kind": "memory"}}}
    raw.update(over)
    return parse_import_config(raw, tmp)


def report(tmp):
    return json.loads((tmp / "work" / "import_report.json").read_text(encoding="utf-8"))


def test_publishes_valid_input(tmp_path, validators):
    write_input(tmp_path / "in")
    store = MemoryDatasetStore(validators)
    res = run_import(cfg_for(tmp_path), store=store, validators=validators)
    assert res.status == "PUBLISHED" and res.counts["rows_total"] == 18 and res.counts["rows_invalid"] == 0
    m = store.get_manifest("ds-imp", res.version)
    assert sorted(f["sample_count"] for f in m["files"]) == [3] * 6
    assert {f["role"] for f in m["files"]} == {"LORA_A", "LORA_B"}
    imp = m["ext"]["synthetic-data"]["import"]
    assert all(v["sha256"].startswith("sha256:") for v in imp["inputs"].values()) and imp["rows_valid"] == 18
    assert report(tmp_path)["row_split_field_values"]["lora_a_train.jsonl"] == {"x": 3}


def test_idempotent(tmp_path, validators):
    write_input(tmp_path / "in")
    store = MemoryDatasetStore(validators)
    a = run_import(cfg_for(tmp_path), store=store, validators=validators)
    b = run_import(cfg_for(tmp_path), store=store, validators=validators)
    assert b.status == "ALREADY_PUBLISHED" and a.version == b.version and a.dataset_digest == b.dataset_digest
    assert a.content_hash == b.content_hash and len(store.list_versions("ds-imp")) == 1


def test_changed_input_changes_digest(tmp_path, validators):
    write_input(tmp_path / "in")
    a = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)
    write_input(tmp_path / "in", per_file=4)
    b = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)
    assert a.dataset_digest != b.dataset_digest


def bad_mutator(name, lines):
    if name == "lora_a_train.jsonl":
        lines = lines + ["이건 JSON이 아님", {"messages": []}, row("LORA_A", 99, "sc-bad")]
        lines[-1]["messages"][2]["content"] = json.dumps({"action": "NEXT"})      # v2 출력 위반
    if name == "lora_b_val.jsonl":
        lines = lines + [row("LORA_B", 98, "sc-bad2", human_review="weird")]
    return lines


def test_invalid_rows_rejected_with_counts_by_reason(tmp_path, validators):
    write_input(tmp_path / "in", mutate=bad_mutator)
    store = MemoryDatasetStore(validators)
    res = run_import(cfg_for(tmp_path), store=store, validators=validators)
    assert res.status == "REJECTED" and store.list_versions("ds-imp") == []
    r = report(tmp_path)
    assert r["total_rows"] == 22 and r["invalid_rows"] == 4 and r["valid_rows"] == 18
    reasons = r["invalid_reasons_by_file"]["lora_a_train.jsonl"]
    assert any(k.startswith("record_json") for k in reasons) and any(k.startswith("record_shape") for k in reasons)
    assert any(k.startswith("output_schema") for k in reasons)
    assert any(k.startswith("sample_schema") for k in r["invalid_reasons_by_file"]["lora_b_val.jsonl"])
    assert r["result"]["status"] == "REJECTED"


def test_within_tolerance_publishes_only_valid_rows(tmp_path, validators):
    write_input(tmp_path / "in", mutate=bad_mutator)
    cfg = cfg_for(tmp_path, tolerance={"max_invalid_rows": 4, "max_invalid_rate": 0.2})
    store = MemoryDatasetStore(validators)
    res = run_import(cfg, store=store, validators=validators)
    assert res.status == "PUBLISHED"
    m = store.get_manifest("ds-imp", res.version)
    assert sum(f["sample_count"] for f in m["files"]) == 18
    assert m["ext"]["synthetic-data"]["import"]["rows_invalid"] == 4        # 버린 건수가 매니페스트에 남는다


def test_rate_over_tolerance_rejects_even_if_count_ok(tmp_path, validators):
    write_input(tmp_path / "in", mutate=bad_mutator)
    res = run_import(cfg_for(tmp_path, tolerance={"max_invalid_rows": 100, "max_invalid_rate": 0.01}),
                     store=MemoryDatasetStore(validators), validators=validators)
    assert res.status == "REJECTED"


def test_v1_shaped_rows_all_rejected(tmp_path, validators):
    """v1 내용(다른 형식)은 명확한 사유로 전부 실패한다."""
    def v1(name, lines):
        return [{"input": {"utterance": "x"}, "expected": {"items": []}} for _ in lines]
    write_input(tmp_path / "in", mutate=v1)
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)
    assert res.status == "REJECTED"
    assert set(report(tmp_path)["invalid_reasons_total"]) == {"record_shape: messages가 [system,user,assistant] 각각 문자열 content를 가진 3개가 아니다"}


def test_missing_file_is_input_error(tmp_path, validators):
    write_input(tmp_path / "in")
    (tmp_path / "in" / "lora_b_test.jsonl").unlink()
    with pytest.raises(InputError, match="lora_b_test.jsonl"):
        run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)


def test_scenario_overlap_rejected(tmp_path, validators):
    def overlap(name, lines):
        if name == "lora_a_test.jsonl":
            lines[0] = row("LORA_A", 77, "sc-TRAIN-0")
        return lines
    write_input(tmp_path / "in", mutate=overlap)
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)
    assert res.status == "REJECTED" and "scenario_id" in res.rejected_reasons[0]


def test_empty_file_rejected(tmp_path, validators):
    write_input(tmp_path / "in")
    (tmp_path / "in" / "lora_a_val.jsonl").write_bytes(b"")
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)
    assert res.status == "REJECTED"


@pytest.mark.parametrize("over", [{"question_sets": []}, {"source_label": ""}, {"tolerance": {"max_invalid_rows": 0}},
                                  {"tolerance": {"max_invalid_rows": 0, "max_invalid_rate": 2}}, {"dataset_id": "bad id"}])
def test_config_errors(tmp_path, over):
    with pytest.raises(ConfigError):
        cfg_for(tmp_path, **over)


def test_example_config_parses():
    parse_import_config(json.loads((ROOT / "configs" / "import.example.json").read_text(encoding="utf-8")), ROOT / "configs")


def test_cli_exit_codes(tmp_path):
    write_input(tmp_path / "in", mutate=bad_mutator)
    raw = {"dataset_id": "ds-cli", "input_dir": str(tmp_path / "in"), "survey_schema_dir": str(SURVEY_DIR), "question_sets": QS,
           "source_label": "fake", "turn_engine_version": "0.0.0-test", "tolerance": {"max_invalid_rows": 0, "max_invalid_rate": 0},
           "output": {"work_dir": str(tmp_path / "w"), "store": {"kind": "file", "root": str(tmp_path / "s")}}}
    cfgp = tmp_path / "c.json"
    cfgp.write_text(json.dumps(raw), encoding="utf-8")
    run = lambda: subprocess.run([sys.executable, "-m", "synthetic_data", "import", "--config", str(cfgp)], cwd=ROOT,
                                 capture_output=True, text=True)
    p = run()
    assert p.returncode == 4 and json.loads(p.stdout)["status"] == "REJECTED"
    write_input(tmp_path / "in")
    p = run()
    assert p.returncode == 0 and json.loads(p.stdout)["status"] == "PUBLISHED"
    assert json.loads(run().stdout)["status"] == "ALREADY_PUBLISHED"
    (tmp_path / "in" / "lora_a_test.jsonl").unlink()
    assert run().returncode == 2
