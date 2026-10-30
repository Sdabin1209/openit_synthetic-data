"""허용치 판정. ImportJudgeInput -> ImportJudgement.

허용치는 설정에서 오고 코드에 기본값이 없다(비식별·pending 정책의 기본은 가장 엄격하다, docs/adr/0005)."""
from __future__ import annotations

from ..types.schema_registry import check


def run(inp: dict) -> dict:
    check("ImportJudgeInput", inp)
    tol, total, bad = inp["tolerance"], inp["total_rows"], inp["invalid_rows"]
    rejected = []
    if total == 0:
        rejected.append("입력이 비어 있다(총 0행)")
    rate = (bad / total) if total else 1.0
    if bad > tol["max_invalid_rows"]:
        rejected.append(f"검증 실패 행 {bad}건이 허용 건수 {tol['max_invalid_rows']}를 넘는다")
    if rate > tol["max_invalid_rate"]:
        rejected.append(f"검증 실패율 {bad}/{total}={rate:.6f}이 허용 비율 {tol['max_invalid_rate']}를 넘는다")
    for name, n in inp["valid_by_file"].items():
        if n == 0:
            rejected.append(f"{name}: 통과한 행이 0건이다")
    npend = inp["pending_total"]
    if npend and inp["pending_policy"] == "reject":
        rejected.append(f"human_review가 pending인 행이 {npend}건 있다(pending_policy=reject)")
    if tol["max_pii_suspect_rows"] is not None and inp["pii_rows_total"] > tol["max_pii_suspect_rows"]:
        rejected.append(f"개인정보 의심 패턴 행 {inp['pii_rows_total']}건이 허용 {tol['max_pii_suspect_rows']}를 넘는다")
    out = {"reasons": rejected, "exclude_pending": bool(npend and inp["pending_policy"] == "exclude")}
    check("ImportJudgement", out)
    return out
