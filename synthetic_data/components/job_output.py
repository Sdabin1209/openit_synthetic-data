"""잡이 표준 출력·오류에 내는 한 줄. JobOutputInput -> JobOutputLine.
deploy가 읽는 형식이라 내보내기 전에 계약(SyntheticJobResult, SyntheticJobError)으로 자기 검사한다(D107).
RESULT에서 rejected_reasons가 빈 목록이면 뺀다: 계약은 이 필드를 import 거부 때만 요구한다."""
from __future__ import annotations

import json

from ..types.schema_registry import check, check_contract


def run(inp: dict) -> dict:
    check("JobOutputInput", inp)
    rec = dict(inp["record"])
    if inp["kind"] == "RESULT":
        if rec.get("rejected_reasons") == [] and rec.get("status") != "REJECTED":
            del rec["rejected_reasons"]
        check_contract("SyntheticJobResult", rec)
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    else:
        check_contract("SyntheticJobError", rec)
        line = json.dumps(rec, ensure_ascii=False)
    out = {"line": line}
    check("JobOutputLine", out)
    return out
