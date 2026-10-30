"""human_review가 pending인 행을 걷어낸다(pending_policy=exclude). PendingFilterInput -> PendingFilterResult.
왜 기본이 아닌가: pending을 걸러낼지는 사용자 결정이라 기본은 report(보고만)다(docs/adr/0005)."""
from __future__ import annotations

from ..types.schema_registry import check


def run(inp: dict) -> dict:
    check("PendingFilterInput", inp)
    files, excluded, reasons = {}, 0, []
    for name, recs in inp["files"].items():
        kept = [r for r in recs if r.get("human_review") != "pending"]
        excluded += len(recs) - len(kept)
        files[name] = kept
        if not kept:
            reasons.append(f"{name}: pending 제외 뒤 행이 0건이다")
    out = {"files": files, "excluded": excluded, "reasons": reasons}
    check("PendingFilterResult", out)
    return out
