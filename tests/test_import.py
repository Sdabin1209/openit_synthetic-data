"""게시기(import) 시험. 입력은 이 리포가 직접 만든 가짜 행이다(실제 학습 데이터가 아니다)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import doubles
from conftest import RULES_VERSION, SURVEY_DIR, ROOT
from synthetic_data.components.import_source import INPUT_FILES
from synthetic_data.wiring.import_job import InputError, run_import
from synthetic_data.wiring.plans import load_import_config, parse_import_config
from synthetic_data.config import ConfigError
from synthetic_data.components.dataset_store import MemoryDatasetStore

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
           "source_label": "fake-test", "action_rules_version": RULES_VERSION, "created_at": "2026-10-27T00:00:00Z",
           "tolerance": {"max_invalid_rows": 0, "max_invalid_rate": 0.0},
           "output": {"work_dir": str(tmp / "work"), "store": {"kind": "memory"}}}
    raw.update(over)
    return parse_import_config(raw, tmp)


def report(tmp):
    return json.loads((tmp / "work" / "import_report.json").read_text(encoding="utf-8"))


def test_publishes_valid_input(tmp_path, validators):
    write_input(tmp_path / "in")
    store = MemoryDatasetStore(validators.contract_version)
    res = run_import(cfg_for(tmp_path), store=store, survey=validators)
    assert res.status == "PUBLISHED" and res.counts["rows_total"] == 18 and res.counts["rows_invalid"] == 0
    m = store.get_manifest("ds-imp", res.version)
    assert sorted(f["sample_count"] for f in m["files"]) == [3] * 6
    assert {f["role"] for f in m["files"]} == {"LORA_A", "LORA_B"}
    imp = m["ext"]["synthetic-data"]["import"]
    assert all(v["sha256"].startswith("sha256:") for v in imp["inputs"].values()) and imp["rows_valid"] == 18
    r = report(tmp_path)
    assert r["row_split_field"]["lora_a_train.jsonl"] == {"absent": 0, "distinct_values": 1}      # 값은 적지 않는다
    assert r["deid_attested"] is False and r["origin_assumed"] == "SYNTHETIC" and r["semantic_checks"]["performed"] is False
    assert m["ext"]["synthetic-data"]["import"]["deid_attested"] is False


def test_idempotent(tmp_path, validators):
    write_input(tmp_path / "in")
    store = MemoryDatasetStore(validators.contract_version)
    a = run_import(cfg_for(tmp_path), store=store, survey=validators)
    b = run_import(cfg_for(tmp_path), store=store, survey=validators)
    assert b.status == "ALREADY_PUBLISHED" and a.version == b.version and a.dataset_digest == b.dataset_digest
    assert a.content_hash == b.content_hash and len(store.list_versions("ds-imp")) == 1


def test_changed_input_changes_digest(tmp_path, validators):
    write_input(tmp_path / "in")
    a = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    write_input(tmp_path / "in", per_file=4)
    b = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
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
    store = MemoryDatasetStore(validators.contract_version)
    res = run_import(cfg_for(tmp_path), store=store, survey=validators)
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
    store = MemoryDatasetStore(validators.contract_version)
    res = run_import(cfg, store=store, survey=validators)
    assert res.status == "PUBLISHED"
    m = store.get_manifest("ds-imp", res.version)
    assert sum(f["sample_count"] for f in m["files"]) == 18
    assert m["ext"]["synthetic-data"]["import"]["rows_invalid"] == 4        # 버린 건수가 매니페스트에 남는다


def test_rate_over_tolerance_rejects_even_if_count_ok(tmp_path, validators):
    write_input(tmp_path / "in", mutate=bad_mutator)
    res = run_import(cfg_for(tmp_path, tolerance={"max_invalid_rows": 100, "max_invalid_rate": 0.01}),
                     store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert res.status == "REJECTED"


def test_v1_shaped_rows_all_rejected(tmp_path, validators):
    """v1 내용(다른 형식)은 명확한 사유로 전부 실패한다."""
    def v1(name, lines):
        return [{"input": {"utterance": "x"}, "expected": {"items": []}} for _ in lines]
    write_input(tmp_path / "in", mutate=v1)
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert res.status == "REJECTED"
    assert set(report(tmp_path)["invalid_reasons_total"]) == {"record_shape: messages가 [system,user,assistant] 각각 문자열 content를 가진 3개가 아니다"}


def test_missing_file_is_input_error(tmp_path, validators):
    write_input(tmp_path / "in")
    (tmp_path / "in" / "lora_b_test.jsonl").unlink()
    with pytest.raises(InputError, match="lora_b_test.jsonl"):
        run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)


def test_scenario_overlap_rejected(tmp_path, validators):
    def overlap(name, lines):
        if name == "lora_a_test.jsonl":
            lines[0] = row("LORA_A", 77, "sc-TRAIN-0")
        return lines
    write_input(tmp_path / "in", mutate=overlap)
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert res.status == "REJECTED" and "scenario_id" in res.rejected_reasons[0]


def test_empty_file_rejected(tmp_path, validators):
    write_input(tmp_path / "in")
    (tmp_path / "in" / "lora_a_val.jsonl").write_bytes(b"")
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
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
           "source_label": "fake", "action_rules_version": RULES_VERSION, "tolerance": {"max_invalid_rows": 0, "max_invalid_rate": 0},
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


# ---- 점검 반영(SD-1~SD-4, SD-7, 의심 패턴) ----
def set_utt(r, text):
    u = json.loads(r["messages"][1]["content"])
    u["user_utterance"] = text
    r["messages"][1]["content"] = json.dumps(u, ensure_ascii=False)
    return r


def test_cross_split_duplicate_utterance_rejected(tmp_path, validators):
    """SD-3: scenario_id가 달라도 공백·구두점만 다른 같은 발화가 TRAIN과 EVAL에 있으면 거부한다."""
    def leak(name, lines):
        if name == "lora_a_train.jsonl":
            lines[0] = set_utt(row("LORA_A", 1, "sc-t-x"), "저는 하루에 담배를 한 갑 피워요.")
        if name == "lora_a_test.jsonl":
            lines[0] = set_utt(row("LORA_A", 2, "sc-e-x"), "저는  하루에 담배를 한 갑 피워요")
        return lines
    write_input(tmp_path / "in", mutate=leak)
    store = MemoryDatasetStore(validators.contract_version)
    res = run_import(cfg_for(tmp_path), store=store, survey=validators)
    assert res.status == "REJECTED" and "같은 입력" in res.rejected_reasons[0]
    r = report(tmp_path)
    assert r["cross_split_duplicate_inputs"]["EVAL~TRAIN"] == 1 and store.list_versions("ds-imp") == []
    assert "담배" not in json.dumps(r, ensure_ascii=False)                    # 발화 본문은 보고서에 없다
    ok = run_import(cfg_for(tmp_path, tolerance={"max_invalid_rows": 0, "max_invalid_rate": 0,
                                                  "max_cross_split_duplicate_inputs": 1}),
                    store=store, survey=validators)
    assert ok.status == "PUBLISHED"


def test_other_question_same_utterance_is_not_a_leak(tmp_path, validators):
    def same(name, lines):
        if name == "lora_a_train.jsonl":
            lines[0] = set_utt(row("LORA_A", 1, "sc-t-x"), "네")
        if name == "lora_a_test.jsonl":
            r = set_utt(row("LORA_A", 2, "sc-e-x"), "네")
            u = json.loads(r["messages"][1]["content"]); u["question_id"] = "Q4"
            r["messages"][1]["content"] = json.dumps(u, ensure_ascii=False)
            lines[0] = r
        return lines
    write_input(tmp_path / "in", mutate=same)
    assert run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators).status == "PUBLISHED"


SECRET = "홍길동SECRET010-9999-8888"


def test_no_input_values_in_reasons_report_or_manifest(tmp_path, validators):
    """SD-1: 위반한 값(이름·전화번호가 든 가짜 값)이 사유·보고서·불변 매니페스트에 섞이지 않는다."""
    def leak(name, lines):
        if name == "lora_a_train.jsonl":
            bad = row("LORA_A", 91, "sc-bad", human_review=SECRET)
            bad["messages"][2]["content"] = json.dumps({"action": SECRET, "values": [{"key": SECRET}], "next_item": 5}, ensure_ascii=False)
            u = json.loads(bad["messages"][1]["content"]); u["extra_" + "field"] = SECRET; u["state"] = {"a": SECRET}
            bad["messages"][1]["content"] = json.dumps(u, ensure_ascii=False)
            lines = lines + [bad, "{" + SECRET]
        return lines
    write_input(tmp_path / "in", mutate=leak)
    store = MemoryDatasetStore(validators.contract_version)
    res = run_import(cfg_for(tmp_path, tolerance={"max_invalid_rows": 5, "max_invalid_rate": 0.5}), store=store, survey=validators)
    assert res.status == "PUBLISHED"
    blob = (tmp_path / "work" / "import_report.json").read_text(encoding="utf-8")
    blob += json.dumps(store.get_manifest("ds-imp", res.version), ensure_ascii=False) + json.dumps(res.__dict__, ensure_ascii=False)
    assert SECRET not in blob and "홍길동" not in blob and "9999" not in blob
    assert any(k.startswith("output_schema: ") and "#" in k for k in report(tmp_path)["invalid_reasons_total"])


def test_version_pinned_rerun_with_other_created_at_is_idempotent(tmp_path, validators):
    """SD-4"""
    write_input(tmp_path / "in")
    store = MemoryDatasetStore(validators.contract_version)
    a = run_import(cfg_for(tmp_path, version="v-pin"), store=store, survey=validators)
    b = run_import(cfg_for(tmp_path, version="v-pin", created_at="2026-12-01T00:00:00Z"), store=store, survey=validators)
    assert a.status == "PUBLISHED" and b.status == "ALREADY_PUBLISHED" and a.content_hash == b.content_hash
    write_input(tmp_path / "in", per_file=4)
    from boundary_contracts.errors import BoundaryError
    with pytest.raises(BoundaryError) as e:
        run_import(cfg_for(tmp_path, version="v-pin"), store=store, survey=validators)
    assert e.value.code == "CONFLICT"


def _with_pending(name, lines):
    if name in ("lora_a_train.jsonl", "lora_b_train.jsonl"):
        lines[0]["human_review"] = "pending"
    return lines


def test_pending_policies(tmp_path, validators):
    """SD-2: 기본은 보고만(싣는다), exclude는 뺀다, reject는 거부한다."""
    write_input(tmp_path / "in", mutate=_with_pending)
    st = MemoryDatasetStore(validators.contract_version)
    d = run_import(cfg_for(tmp_path), store=st, survey=validators)
    assert d.status == "PUBLISHED" and report(tmp_path)["pending_rows"] == 2 and report(tmp_path)["pending_excluded"] == 0
    assert report(tmp_path)["human_review_counts"] == {"auto_only": 16, "pending": 2}
    ex = run_import(cfg_for(tmp_path, pending_policy="exclude"), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert ex.status == "PUBLISHED" and report(tmp_path)["pending_excluded"] == 2 and ex.dataset_digest != d.dataset_digest
    assert run_import(cfg_for(tmp_path, pending_policy="reject"), store=MemoryDatasetStore(validators.contract_version), survey=validators).status == "REJECTED"
    with pytest.raises(ConfigError):
        cfg_for(tmp_path, pending_policy="drop")
    with pytest.raises(ConfigError):
        cfg_for(tmp_path, origin="FAILURE_CASE_SEED")


def test_pii_suspect_counts_without_values(tmp_path, validators):
    """비식별 의심 패턴은 건수만 센다. 기본은 거부(2026-10-29, B14), tolerance.max_pii_suspect_rows: null이면 경고만, 허용 건수를 정하면 그 수까지 통과한다."""
    def pii(name, lines):
        if name == "lora_a_train.jsonl":
            lines[0] = set_utt(row("LORA_A", 1, "sc-t-p"), "연락처는 010-1234-5678 입니다")
            lines[1] = set_utt(row("LORA_A", 2, "sc-t-q"), "메일 a.b@example.com 로 주세요")
        if name == "lora_b_train.jsonl":
            lines[0] = set_utt(row("LORA_B", 3, "sc-t-r"), "901231-1234567")
        return lines
    write_input(tmp_path / "in", mutate=pii)
    warn = {"max_invalid_rows": 0, "max_invalid_rate": 0, "max_pii_suspect_rows": None}
    res = run_import(cfg_for(tmp_path, tolerance=warn), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert res.status == "PUBLISHED"
    r = report(tmp_path)
    assert r["pii_suspect"]["rows_total"] == 3 and r["pii_suspect"]["rows_by_kind"] == {"email": 1, "phone_mobile": 1, "rrn": 1}
    assert "1234-5678" not in json.dumps(r) and r["deid_attested"] is False
    rej = run_import(cfg_for(tmp_path, tolerance={"max_invalid_rows": 0, "max_invalid_rate": 0, "max_pii_suspect_rows": 2}),
                     store=MemoryDatasetStore(validators.contract_version), survey=validators)
    assert rej.status == "REJECTED"


def test_pii_patterns_have_bounded_non_nested_repeats():
    """ReDoS 방어(OWASP)는 시간을 재지 않고 구조로 본다: 모든 반복 수량자에 상한이 있고(무한 반복 없음) 중첩 반복이 없다."""
    import re
    from synthetic_data.components import pii_scan
    parser = getattr(re, "_parser", None) or __import__("sre_parse")
    MAXREPEAT = parser.MAXREPEAT

    def walk(items, depth):
        for op, av in items:
            name = str(op)
            if name in ("MAX_REPEAT", "MIN_REPEAT"):
                _lo, hi, sub = av
                assert hi < MAXREPEAT, "상한 없는 반복"
                assert depth == 0 or not _has_repeat(sub), "중첩 반복"
                walk(sub, depth + 1)
            elif name == "SUBPATTERN":
                walk(av[-1], depth)
            elif name == "BRANCH":
                for b in av[1]:
                    walk(b, depth)

    def _has_repeat(sub):
        return any(str(op) in ("MAX_REPEAT", "MIN_REPEAT") for op, _ in sub)

    for rx in pii_scan.PII_PATTERNS.values():
        walk(parser.parse(rx.pattern), 0)
    assert pii_scan.PII_SCAN_LIMIT > 0      # 입력 길이 상한도 있다
    evil = "a" * 19000 + "@" + "1" * 900 + "0" + "-" * 90
    pii_scan.run({"items": [{"input": {"user_utterance": evil}, "expected": evil}]})      # 상한 때문에 끝난다(시간은 재지 않는다)


def test_same_utterance_same_question_different_state_is_reported_not_rejected(tmp_path, validators):
    """실측(C1 데이터)에서 나온 모양: 발화·문항은 같고 state만 다른 LoRA-A 행은 참고 건수로만 센다."""
    def diff_state(name, lines):
        if name == "lora_a_train.jsonl":
            lines[0] = set_utt(row("LORA_A", 1, "sc-t-x"), "네 맞아요")
        if name == "lora_a_test.jsonl":
            r = set_utt(row("LORA_A", 2, "sc-e-x"), "네 맞아요")
            u = json.loads(r["messages"][1]["content"]); u["state"] = {"Q3.hours": {"value": 5, "status": "ANSWERED"}}
            r["messages"][1]["content"] = json.dumps(u, ensure_ascii=False)
            lines[0] = r
        return lines
    write_input(tmp_path / "in", mutate=diff_state)
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators.contract_version), survey=validators)
    r = report(tmp_path)
    assert res.status == "PUBLISHED" and r["cross_split_duplicate_utterances"]["EVAL~TRAIN"] == 1
    assert r["cross_split_duplicate_inputs"]["EVAL~TRAIN"] == 0


@pytest.mark.skipif(not __import__("os").environ.get("SD_REFERENCE_DATA_DIR"), reason="SD_REFERENCE_DATA_DIR(실제 파일 경로)가 없다")
def test_real_reference_data_if_provided(tmp_path, validators):
    """선택 시험: 실제 파일 6개를 읽기 전용으로 검증한다. 데이터는 리포에 없고 건수 기대값은 C1 빌드의 것이다."""
    import os
    cfg = cfg_for(tmp_path, input_dir=os.environ["SD_REFERENCE_DATA_DIR"])
    res = run_import(cfg, store=MemoryDatasetStore(validators.contract_version), survey=validators)
    r = report(tmp_path)
    assert r["invalid_rows"] == 0 and r["total_rows"] == res.counts["rows_total"]


def test_unknown_import_config_key_is_rejected(tmp_path):
    """SD-01: import 설정도 run처럼 알 수 없는 최상위 키(오타)를 거부한다(ADR 0014). 오타 키가 조용히 무시되면 안 된다."""
    for key in ("pending_polcy", "tolerence", "scenarios"):
        with pytest.raises(ConfigError, match=key):
            cfg_for(tmp_path, **{key: "report"})


def test_shipped_import_example_has_only_known_keys():
    """SD-01: 거부가 켜져도 리포에 있는 import 예시 설정은 통과해야 한다."""
    load_import_config(Path(__file__).resolve().parent.parent / "configs" / "import.example.json")
