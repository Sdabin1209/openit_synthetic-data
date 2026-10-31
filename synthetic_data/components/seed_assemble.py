"""시드 샘플 조립. SeedAssembleInput -> SeedAssembly.
확정된 실패 사례(시드)를 FAILURE_CASE_SEED 샘플 레코드로 만든다. v1 생성 경로(발화·응답 생성, 노이즈, 정답 구성)는 ADR 0010으로 제거했다.
시드의 입력은 FailureCase.reviewed_input(LoRA-A는 ActionExtractionInput, LoRA-B는 ResponseRequest)이다. v1에 있던 노이즈 변형은 만들지 않는다(원문 위치 source_text가 v2 출력에 없다)."""
from __future__ import annotations

import copy
from collections import Counter

from boundary_contracts import PIPELINE_SCHEMA_VERSION, canonical

from ..types.schema_registry import check

EXT = "synthetic-data"


def _short_hash(*parts, n: int = 16) -> str:
    return canonical.sha256_hash(list(parts))[7:7 + n]


def _record(sample_id: str, scenario_id: str, ref: dict, origin: str, inp: dict, expected, ext: dict, seed_case_id: str) -> dict:
    """샘플 봉투(2.0.0): ActionExtractionSample/ResponseSample에는 runtime_contract_version, style_guide_version, noise_types가 없다."""
    return {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": sample_id, "scenario_id": scenario_id,
            "question_set": copy.deepcopy(ref), "split": "TRAIN", "origin": origin, "input": inp, "expected": expected,
            "ext": {EXT: ext}, "seed_case_id": seed_case_id}


def run(inp: dict) -> dict:
    check("SeedAssembleInput", inp)
    out, skipped, stats = [], [], Counter()
    for p in inp["pairs"]:
        s, ref = p["seed"], p["ref"]
        scen = "sd-" + _short_hash(s["case_id"])
        if s["role"] == "LORA_A":
            used = {s["input"]["question_id"]}
        else:
            nxt = s["input"].get("next")
            used = {nxt["question_id"]} if isinstance(nxt, dict) and "question_id" in nxt else set()
        if not used <= set(p["question_ids"]):
            skipped.append({"case_id": s["case_id"], "reason": "시드의 문항이 지정한 문항 세트에 없음"})
            continue
        if p["affected_question_ids"] is not None and not used <= set(p["affected_question_ids"]):      # 변경 분류의 영향 문항만 다시 만든다(affected_only)
            skipped.append({"case_id": s["case_id"], "reason": "시드의 문항이 변경 분류의 영향 문항이 아님"})
            continue
        prefix, name = ("rs-" + _short_hash(scen, ref["version"]), "seed_lora_b") if s["role"] == "LORA_B" else ("as-" + _short_hash(scen, ref["version"], "clean"), "seed_lora_a")
        out.append(_record(prefix, scen, ref, "FAILURE_CASE_SEED", copy.deepcopy(s["input"]), copy.deepcopy(s["expected"]), {"kind": "SEED"}, s["case_id"]))
        stats[name] += 1
    res = {"samples": out, "skipped": skipped, "stats": dict(stats)}
    check("SeedAssembly", res)
    return res
