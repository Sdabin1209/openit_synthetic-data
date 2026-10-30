"""시드 수집. SeedCollectInput -> SeedCollection.

규칙: 정답이 확정된 사례(review_status=CONFIRMED이고 expected 있음)만 쓴다. 비식별(deidentified=true)이 아닌 사례는 입력 스키마가 거부한다(브리프 5절).
그 밖에 쓸 수 없는 사례는 사유와 함께 건너뛴다(보고서에 남는다). 읽기 모드(CONVENTIONS 1절): 형식은 I7 클라이언트가 이미 검증했고, 모르는 필드·열거값은 받아들이고 메모에 남긴다."""
from __future__ import annotations

import boundary_contracts

from ..types.schema_registry import check, contract_codes


def _one(case: dict, survey_version: int, notes: list):
    known = set(boundary_contracts.load_schema("FailureCase")["properties"])
    extra = sorted(set(case) - known)
    if extra:
        notes.append(f"{case['case_id']}: 모르는 필드 무시 {extra}")
    if case.get("expected_kind") not in (None, "LORA_A", "LORA_B"):
        notes.append(f"{case['case_id']}: 모르는 expected_kind {case['expected_kind']!r}, expected 형태로 판별")
    if case["runtime_contract_version"] != survey_version:
        return None, "runtime_contract_version 불일치"
    if case["review_status"] != "CONFIRMED":
        return None, "CONFIRMED 아님"
    exp = case.get("expected")
    if not exp:
        return None, "expected 없음"
    # 2.0.0: 시드의 입력은 검토자가 쓴 reviewed_input만 쓴다. v2의 비식별 trace 키는 survey-service가 정하며 아직 미정이라 trace에서는 입력을 꺼내지 않는다.
    kind = case.get("expected_kind")
    if kind not in ("LORA_A", "LORA_B"):                 # 생략되었거나 모르는 값: expected의 형태로 판별(객체면 LORA_A, 문자열이면 LORA_B)
        kind = "LORA_A" if isinstance(exp, dict) else "LORA_B" if isinstance(exp, str) else None
        if kind is None:
            return None, "expected의 종류를 판별할 수 없음"
    inp = case.get("reviewed_input")
    if not inp:
        return None, "reviewed_input 없음(v2 trace 키는 미정이라 trace에서 입력을 만들지 않는다)"
    if kind == "LORA_A":
        if not isinstance(exp, dict) or contract_codes("ActionExtraction", exp) or contract_codes("ActionExtractionInput", inp):
            return None, "expected 또는 reviewed_input이 ActionExtraction/ActionExtractionInput 스키마를 위반"
    else:
        if not isinstance(exp, str) or contract_codes("ResponseText", exp) or contract_codes("ResponseRequest", inp):
            return None, "expected 또는 reviewed_input이 ResponseText/ResponseRequest 스키마를 위반"
    return {"case_id": case["case_id"], "version": case["version"], "role": kind, "input": inp, "expected": exp, "question_set": case.get("question_set")}, None


def run(inp: dict) -> dict:
    check("SeedCollectInput", inp)
    seeds, skipped, notes = [], [], []
    for case in inp["cases"]:
        seed, why = _one(case, inp["survey_contract_version"], notes)
        if seed:
            seeds.append(seed)
        else:
            skipped.append({"case_id": case.get("case_id"), "reason": why})
    seeds.sort(key=lambda s: s["case_id"])
    out = {"seeds": seeds, "skipped": skipped, "notes": notes}
    check("SeedCollection", out)
    return out
