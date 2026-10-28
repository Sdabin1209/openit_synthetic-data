"""시드 샘플 조립: 확정된 실패 사례(Seed)를 FAILURE_CASE_SEED 샘플 레코드로 만든다. v1 생성 경로(발화·응답 생성, 노이즈, 정답 구성)는 ADR 0010으로 제거했다."""
from __future__ import annotations

import copy
from collections import Counter
from typing import Optional

from . import PIPELINE_SCHEMA_VERSION
from .rng import short_hash

EXT = "synthetic-data"


def _record(sample_id: str, scenario_id: str, ref: dict, origin: str, inp: dict, expected, ext: dict, *,
            seed_case_id: Optional[str] = None) -> dict:
    """샘플 봉투(2.0.0): ActionExtractionSample/ResponseSample에는 runtime_contract_version, style_guide_version, noise_types가 없다."""
    rec = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": sample_id, "scenario_id": scenario_id,
           "question_set": copy.deepcopy(ref), "split": "TRAIN",
           "origin": origin, "input": inp, "expected": expected, "ext": {EXT: ext}}
    if seed_case_id:
        rec["seed_case_id"] = seed_case_id
    return rec


def build_seed_samples(pairs: list) -> tuple[list, list, Counter]:
    """시드 사례를 FAILURE_CASE_SEED 샘플로(2.0.0). 시드의 입력은 FailureCase.reviewed_input(LoRA-A는 ActionExtractionInput, LoRA-B는 ResponseRequest)이다.
    v1에 있던 노이즈 변형은 만들지 않는다(원문 위치 source_text가 v2 출력에 없다). 변형 방법은 미정이다."""
    out, skipped, stats = [], [], Counter()
    for s, ctx in pairs:
        qids = {q["question_id"] for q in ctx.bank["questions"]}
        scen = "sd-" + short_hash(s.case_id)
        if s.role == "LORA_A":
            used = {s.input["question_id"]}
        else:
            nxt = s.input.get("next")
            used = {nxt["question_id"]} if isinstance(nxt, dict) and "question_id" in nxt else set()
        if not used <= qids:
            skipped.append({"case_id": s.case_id, "reason": "시드의 문항이 지정한 문항 세트에 없음"})
            continue
        if s.role == "LORA_B":
            out.append(_record("rs-" + short_hash(scen, ctx.ref["version"]), scen, ctx.ref, "FAILURE_CASE_SEED",
                               copy.deepcopy(s.input), copy.deepcopy(s.expected), {"kind": "SEED"}, seed_case_id=s.case_id))
            stats["seed_lora_b"] += 1
            continue
        out.append(_record("as-" + short_hash(scen, ctx.ref["version"], "clean"), scen, ctx.ref, "FAILURE_CASE_SEED",
                           copy.deepcopy(s.input), copy.deepcopy(s.expected), {"kind": "SEED"}, seed_case_id=s.case_id))
        stats["seed_lora_a"] += 1
    return out, skipped, stats
