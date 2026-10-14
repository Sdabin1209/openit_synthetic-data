"""시드 수집기. 실패 사례 읽기 SDK(I7, boundary_contracts.sdk.FailureStore)로만 읽는다.

규칙: 정답이 확정된 사례(review_status=CONFIRMED이고 expected 있음)만 쓴다. 비식별(deidentified=true)이 아닌 사례를 받으면
BoundaryError(INVALID_RECORD)로 거부한다(브리프 5절). 그 밖에 쓸 수 없는 사례는 사유와 함께 건너뛴다(보고서에 남는다)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from boundary_contracts.errors import BoundaryError
from boundary_contracts.sdk import FailureStore

from .schemas import Validators


@dataclass
class Seed:
    case_id: str
    version: int
    role: str            # PARSER | GENERATOR
    input: dict
    expected: dict


def collect_seeds(store: FailureStore, v: Validators, *, page_size: int = 100) -> tuple[list[Seed], list[dict]]:
    seeds, skipped, cursor = [], [], None
    while True:
        items, cursor = store.list_cases(review_status="CONFIRMED", latest_only=True, cursor=cursor, limit=page_size)
        for case in items:
            seed, why = _one(store, v, case)
            if seed:
                seeds.append(seed)
            else:
                skipped.append({"case_id": case.get("case_id"), "reason": why})
        if cursor is None:
            break
    seeds.sort(key=lambda s: s.case_id)
    return seeds, skipped


def _one(store: FailureStore, v: Validators, case: dict) -> tuple[Optional[Seed], Optional[str]]:
    if case.get("deidentified") is not True:
        raise BoundaryError("INVALID_RECORD", f"비식별되지 않은 실패 사례를 받았다: {case.get('case_id')}")
    v.boundary("FailureCase", case, what=f"FailureCase {case.get('case_id')}")
    if case["runtime_contract_version"] != v.runtime_contract_version:
        return None, "runtime_contract_version 불일치"
    if case["review_status"] != "CONFIRMED":
        return None, "CONFIRMED 아님"
    exp = case.get("expected")
    if not exp:
        return None, "expected 없음"
    trace = store.get_trace(case["deidentified_trace_ref"])
    if v.check_survey("TurnTrace", trace):
        return None, "trace가 TurnTrace 스키마를 위반"
    if not v.check_survey("ParserOutput", exp) and trace.get("parser_input"):
        return Seed(case["case_id"], case["version"], "PARSER", trace["parser_input"], exp), None
    if not v.check_survey("GeneratorOutput", exp) and trace.get("generator_input"):
        return Seed(case["case_id"], case["version"], "GENERATOR", trace["generator_input"], exp), None
    return None, "expected의 종류(ParserOutput/GeneratorOutput)와 trace 입력이 맞지 않음"
