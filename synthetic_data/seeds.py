"""시드 수집기. 실패 사례 읽기 SDK(I7, boundary_contracts.sdk.FailureStore)로만 읽는다.

규칙: 정답이 확정된 사례(review_status=CONFIRMED이고 expected 있음)만 쓴다. 비식별(deidentified=true)이 아닌 사례를 받으면
BoundaryError(INVALID_RECORD)로 거부한다(브리프 5절). 그 밖에 쓸 수 없는 사례는 사유와 함께 건너뛴다(보고서에 남는다)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import boundary_contracts
from boundary_contracts.errors import BoundaryError
from boundary_contracts.sdk import FailureStore

from .schemas import Validators


@dataclass
class Seed:
    case_id: str
    version: int
    role: str            # LORA_A | LORA_B
    input: dict
    expected: object     # LORA_A는 객체(ActionExtraction), LORA_B는 문자열(ResponseText)
    question_set: Optional[dict] = None   # FailureCase 1.1의 question_set. 1.0 레코드는 None


def collect_seeds(store: FailureStore, v: Validators, *, page_size: int = 100, notes: Optional[list] = None) -> tuple[list[Seed], list[dict]]:
    seeds, skipped, cursor = [], [], None
    while True:
        items, cursor = store.list_cases(review_status="CONFIRMED", latest_only=True, cursor=cursor, limit=page_size)
        for case in items:
            seed, why = _one(store, v, case, notes)
            if seed:
                seeds.append(seed)
            else:
                skipped.append({"case_id": case.get("case_id"), "reason": why})
        if cursor is None:
            break
    seeds.sort(key=lambda s: s.case_id)
    return seeds, skipped


def _one(store: FailureStore, v: Validators, case: dict, notes: Optional[list] = None) -> tuple[Optional[Seed], Optional[str]]:
    if case.get("deidentified") is not True:
        raise BoundaryError("INVALID_RECORD", f"비식별되지 않은 실패 사례를 받았다: {case.get('case_id')}")
    # 읽기 모드(CONVENTIONS 1절): 형식은 I7 클라이언트가 이미 검증했다. 모르는 필드·열거값은 받아들이고 보고서에 남긴다.
    if notes is not None:
        known = set(boundary_contracts.load_schema("FailureCase")["properties"])
        extra = sorted(set(case) - known)
        if extra:
            notes.append(f"{case['case_id']}: 모르는 필드 무시 {extra}")
        if case.get("expected_kind") not in (None, "LORA_A", "LORA_B"):
            notes.append(f"{case['case_id']}: 모르는 expected_kind {case['expected_kind']!r}, expected 형태로 판별")
    if case["runtime_contract_version"] != v.runtime_contract_version:
        return None, "runtime_contract_version 불일치"
    if case["review_status"] != "CONFIRMED":
        return None, "CONFIRMED 아님"
    exp = case.get("expected")
    if not exp:
        return None, "expected 없음"
    # 2.0.0: 시드의 입력은 검토자가 쓴 reviewed_input만 쓴다. v2의 비식별 trace 키(extract_*, response_* 등)는 survey-service가 정하며 아직 미정이라 trace에서는 입력을 꺼내지 않는다.
    kind = case.get("expected_kind")
    qs = case.get("question_set")
    if kind not in ("LORA_A", "LORA_B"):                 # 생략되었거나 모르는 값: expected의 형태로 판별(객체면 LORA_A, 문자열이면 LORA_B)
        kind = "LORA_A" if isinstance(exp, dict) else "LORA_B" if isinstance(exp, str) else None
        if kind is None:
            return None, "expected의 종류를 판별할 수 없음"
    inp = case.get("reviewed_input")
    if not inp:
        return None, "reviewed_input 없음(v2 trace 키는 미정이라 trace에서 입력을 만들지 않는다)"
    if kind == "LORA_A":
        if not isinstance(exp, dict) or v.check_boundary("ActionExtraction", exp) or v.check_boundary("ActionExtractionInput", inp):
            return None, "expected 또는 reviewed_input이 ActionExtraction/ActionExtractionInput 스키마를 위반"
    else:
        if not isinstance(exp, str) or v.check_boundary("ResponseText", exp) or v.check_boundary("ResponseRequest", inp):
            return None, "expected 또는 reviewed_input이 ResponseText/ResponseRequest 스키마를 위반"
    return Seed(case["case_id"], case["version"], kind, inp, exp, qs), None
