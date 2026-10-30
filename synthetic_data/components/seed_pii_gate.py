"""시드의 개인정보 의심 패턴 관문. SeedPiiGateInput -> SeedPiiGateResult.
시드의 입력·정답에 개인정보 의심 패턴이 있으면 기본으로 거부한다(import의 max_pii_suspect_rows와 같은 기본, 표준성 점검 C4). 거부 메시지에는 사례 ID만 있고 값은 없다."""
from __future__ import annotations

from ..types.schema_registry import check


def run(inp: dict) -> dict:
    check("SeedPiiGateInput", inp)
    hits, mx = inp["hits"], inp["max_suspect"]
    rejected = bool(hits) and mx is not None and len(hits) > mx
    out = {"suspect_rows": len(hits), "patterns": sorted(inp["patterns"]), "rejected": rejected,
           "message": f"개인정보 의심 패턴이 있는 시드 사례 {len(hits)}건이 허용 {mx}건을 넘는다: {sorted(hits)[:10]}" if rejected else None}
    check("SeedPiiGateResult", out)
    return out
