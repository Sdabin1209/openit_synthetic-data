"""시드 잡 보고서 조립. RunReportInput -> ReportDocument(계약 SyntheticRunReport).
deploy와 사람이 읽는 형식이라 내보내기 전에 계약으로 자기 검사한다(D107). 단계에 도달하지 못했으면 해당 키가 없다. 경계 호출이 실패하면 `error`(BoundaryError 레코드)가 남는다."""
from __future__ import annotations

from collections import Counter

from ..types.schema_registry import check, check_contract


def run(inp: dict) -> dict:
    check("RunReportInput", inp)
    r = {"job_version": inp["tool_version"], "dataset_id": inp["dataset_id"], "notes": inp["notes"], "dropped": inp["dropped"], "skipped_seeds": inp["skipped_seeds"]}
    for k in ("pii_suspect", "generation", "dataset_digest", "result", "error"):
        if k in inp:
            r[k] = inp[k]
    if "samples" in inp:
        c = Counter()
        for s in inp["samples"]:
            c[f"{'lora_a' if s['sample_id'].startswith('as-') else 'lora_b'}.{s['split']}"] += 1
            c[f"origin.{s['origin']}"] += 1
            c[f"kind.{s['ext']['synthetic-data']['kind']}"] += 1
        r["counts"] = dict(sorted(c.items()))
    check_contract("SyntheticRunReport", r)
    out = {"report": r}
    check("ReportDocument", out)
    return out
